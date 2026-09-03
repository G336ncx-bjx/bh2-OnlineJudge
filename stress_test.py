"""OJ 系统梯度压力测试脚本。

用法示例：
  python stress_test.py --scenario read --levels 10,50,100,300
  python stress_test.py --scenario judge --levels 5,10,20
  python stress_test.py --scenario ai --levels 2,5,10
  python stress_test.py --all            # 三个场景全部跑一遍（默认梯度）

设计目标：从低并发到高并发逐档推进，每档输出成功率、延迟分位、
429 限流数、吞吐等指标，用于定位系统拐点与瓶颈，而非一次性灌满。
"""
import argparse
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = "http://127.0.0.1:8000"

# ---------------------------------------------------------------- 通用工具

class Session:
    """带 cookie 的登录会话。"""

    def __init__(self, username, password):
        self.s = requests.Session()
        r = self.s.post(f"{BASE}/api/auth/login",
                        json={"username": username, "password": password},
                        timeout=10)
        if r.status_code != 200 or r.json().get("code") != 200:
            raise RuntimeError(f"登录失败 {username}: {r.status_code} {r.text[:200]}")

    def get(self, path, **kw):
        return self.s.get(f"{BASE}{path}", timeout=30, **kw)

    def post(self, path, **kw):
        return self.s.post(f"{BASE}{path}", timeout=30, **kw)

    def put(self, path, **kw):
        return self.s.put(f"{BASE}{path}", timeout=30, **kw)


def run_batch(fn, args_list, concurrency, desc=""):
    """并发执行 fn(args)，返回每个任务的 (成功bool, 耗时秒, http状态码)。"""
    results = []
    lock = threading.Lock()

    def worker(args):
        t0 = time.perf_counter()
        try:
            code = fn(args)
            dt = time.perf_counter() - t0
            return (code < 400, dt, code)
        except Exception as e:
            dt = time.perf_counter() - t0
            return (False, dt, -1)

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(worker, a) for a in args_list]
        for f in as_completed(futs):
            results.append(f.result())
    return results


def report_level(scenario, level, results, total_requests):
    """打印单档指标。"""
    ok = sum(1 for r in results if r[0])
    fail = len(results) - ok
    codes = {}
    for r in results:
        codes[r[2]] = codes.get(r[2], 0) + 1
    lat = sorted(r[1] for r in results)
    n = len(lat)

    def pct(p):
        if n == 0:
            return 0
        return lat[min(n - 1, int(n * p))]

    ok_lat = sorted(r[1] for r in results if r[0])
    qps = total_requests / (sum(r[1] for r in results) / max(1, len(results))) if results else 0

    print(f"\n  [{scenario}] 并发={level:>4}  请求={total_requests:>5}  "
          f"成功={ok:>5}  失败={fail:>5}  成功率={ok/max(1,len(results))*100:5.1f}%")
    print(f"       HTTP 状态码分布: {dict(sorted(codes.items()))}")
    if lat:
        print(f"       延迟(秒) 均值={statistics.mean(lat):.3f}  "
              f"P50={pct(0.50):.3f}  P95={pct(0.95):.3f}  P99={pct(0.99):.3f}  "
              f"max={max(lat):.3f}")
    # 429 单独提示
    n429 = codes.get(429, 0)
    if n429:
        print(f"       ⚠️ 限流 429 出现 {n429} 次（占 {n429/max(1,len(results))*100:.1f}%）")
    return {"level": level, "total": total_requests, "ok": ok, "fail": fail,
            "rate": ok / max(1, len(results)), "codes": codes,
            "p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99),
            "mean": statistics.mean(lat) if lat else 0, "max": max(lat) if lat else 0}


# ---------------------------------------------------------------- 场景 1：读接口并发

def scenario_read(levels, per_level):
    print("=" * 70)
    print("场景 1：读接口并发（登录态，轮流请求题目列表/详情/语言）")
    print("=" * 70)
    s = Session("admin", "admintestpassword")
    # 预热：拿到题目列表和一个题目 id
    r = s.get("/api/problems/")
    probs = r.json().get("data", [])
    pid = probs[0]["id"] if probs else "P1002"
    paths = [
        "/api/problems/",
        f"/api/problems/{pid}",
        "/api/languages/",
        "/api/submissions/",
    ]
    print(f"  登录态就绪，题目 id={pid}，轮询 {len(paths)} 个读接口")

    summary = []
    for lv in levels:
        n = per_level if per_level else lv * 10
        import itertools
        args = list(itertools.islice(itertools.cycle(paths), n))

        def _get(path):
            r = s.get(path)
            return r.status_code

        results = run_batch(_get, args, lv)
        summary.append(report_level("read", lv, results, n))
        time.sleep(0.5)
    return summary


# ---------------------------------------------------------------- 场景 2：评测提交吞吐

AC_PY = "import sys\nn=int(sys.stdin.read().strip())\ns=0\nf=1\nfor i in range(1,n+1):\n    f*=i\n    s+=f\nprint(s)\n"


def scenario_judge(levels, per_level):
    print("=" * 70)
    print("场景 2：评测提交吞吐（多用户绕开单用户限流，提交 AC 代码）")
    print("=" * 70)
    # 准备账号：admin 已存在，其余用注册接口临时造一批用户
    sessions = [Session("admin", "admintestpassword")]
    # 查看是否已有足够用户，不足则注册
    r = sessions[0].get("/api/users/")
    existing = []
    if r.status_code == 200:
        existing = [u.get("username") for u in r.json().get("data", {}).get("users", [])]
    # 注册一批压测用户
    import random
    for i in range(30):
        uname = f"stress_{i}"
        if uname in existing:
            continue
        r = requests.post(f"{BASE}/api/users/",
                          json={"username": uname, "password": "stress123"})
    # 登录可用用户（最多 30 个，避开单用户限流）
    for i in range(30):
        uname = f"stress_{i}"
        try:
            sessions.append(Session(uname, "stress123"))
        except RuntimeError:
            pass
    print(f"  可用压测账号数: {len(sessions)}")

    # 取一道题
    r = sessions[0].get("/api/problems/")
    probs = r.json().get("data", [])
    pid = probs[0]["id"] if probs else "P1002"
    print(f"  使用题目: {pid}")

    summary = []
    session_idx = [0]

    def _submit(_):
        # 轮询取账号，模拟多用户并发提交
        s = sessions[session_idx[0] % len(sessions)]
        session_idx[0] += 1
        r = s.post("/api/submissions/",
                   json={"problem_id": pid, "language": "python", "code": AC_PY})
        return r.status_code

    for lv in levels:
        n = per_level if per_level else lv * 10
        args = [None] * n
        results = run_batch(_submit, args, lv)
        summary.append(report_level("judge", lv, results, n))
        time.sleep(1)
    return summary


# ---------------------------------------------------------------- 场景 3：AI 命题并发

REQ = "设计一道考察「数组前缀和」的简单算法题，要求 3 个样例、5 个测试点。"


def scenario_ai(levels, per_level):
    print("=" * 70)
    print("场景 3：AI 命题并发（同时提交多个命题任务，等待跑完出题）")
    print("=" * 70)
    s = Session("admin", "admintestpassword")
    summary = []
    for lv in levels:
        n = per_level if per_level else lv
        print(f"\n  --- 并发提交 {n} 个命题任务 ---")
        task_ids = []

        def _submit(_):
            r = s.post("/api/ai/problem-tasks/", json={"requirement": REQ})
            if r.status_code == 200:
                d = r.json().get("data", {})
                task_ids.append(d.get("task_id"))
            return r.status_code

        results = run_batch(_submit, [None] * n, lv)
        summary.append(report_level("ai-submit", lv, results, n))

        # 等待所有任务到终态（completed/failed/cancelled）
        print(f"      等待 {len(task_ids)} 个任务跑完（分阶段生成，每任务约 30-60s）...")
        deadline = time.time() + 180
        while time.time() < deadline:
            done = 0
            from collections import Counter
            cnt = Counter()
            for tid in task_ids:
                r = s.get(f"/api/ai/problem-tasks/{tid}")
                if r.status_code == 200:
                    st = r.json().get("data", {}).get("status")
                    cnt[st] += 1
                    if st in ("completed", "failed", "cancelled"):
                        done += 1
            print(f"      [{time.strftime('%H:%M:%S')}] 终态 {done}/{len(task_ids)}  分布 {dict(cnt)}")
            if done >= len(task_ids):
                break
            time.sleep(10)
        # 逐个核对生成结果
        ok_title = 0
        for tid in task_ids:
            r = s.get(f"/api/ai/problem-tasks/{tid}")
            d = r.json().get("data", {})
            if d.get("status") == "completed" and d.get("result", {}).get("title"):
                ok_title += 1
        print(f"      结果：成功出题 {ok_title}/{len(task_ids)} 个任务")
    return summary


# ---------------------------------------------------------------- 主入口

def main():
    ap = argparse.ArgumentParser(description="OJ 梯度压力测试")
    ap.add_argument("--scenario", choices=["read", "judge", "ai", "all"],
                    default="all")
    ap.add_argument("--levels", type=str, default="",
                    help="逗号分隔的并发档位，如 10,50,100,300")
    ap.add_argument("--per-level", type=int, default=0,
                    help="每档请求数（默认 = 并发数*10）")
    args = ap.parse_args()

    defaults = {
        "read": [10, 50, 100, 200, 300, 500],
        "judge": [5, 10, 20, 30, 50],
        "ai": [2, 4, 6, 8],
    }

    scenarios = ["read", "judge", "ai"] if args.scenario == "all" else [args.scenario]

    all_summary = {}
    for sc in scenarios:
        levels = [int(x) for x in args.levels.split(",") if x.strip()] if args.levels else defaults[sc]
        t0 = time.perf_counter()
        if sc == "read":
            all_summary[sc] = scenario_read(levels, args.per_level)
        elif sc == "judge":
            all_summary[sc] = scenario_judge(levels, args.per_level)
        elif sc == "ai":
            all_summary[sc] = scenario_ai(levels, args.per_level)
        print(f"\n  场景 {sc} 总耗时: {time.perf_counter()-t0:.1f}s")

    # 汇总表
    print("\n" + "=" * 70)
    print("压测汇总（成功率随并发变化）")
    print("=" * 70)
    for sc, rows in all_summary.items():
        print(f"\n场景 {sc}:")
        for r in rows:
            print(f"  并发 {r['level']:>4} -> 成功率 {r['rate']*100:5.1f}%  "
                  f"P50 {r['p50']:.3f}s  P95 {r['p95']:.3f}s  "
                  f"429数 {r['codes'].get(429,0)}  其他错误 {r['fail']-r['codes'].get(429,0)}")


if __name__ == "__main__":
    main()
