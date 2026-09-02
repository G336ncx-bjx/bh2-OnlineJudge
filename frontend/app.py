"""OJ 系统前端 —— Streamlit 实现。

通过 REST API 与 FastAPI 后端交互，不直接读写后端数据。
覆盖三组页面：用户、题目、评测提交。
"""
import json

import requests
import streamlit as st
import streamlit.components.v1 as components

# 后端地址
BACKEND = "http://127.0.0.1:8000"

st.set_page_config(page_title="OJ 在线评测系统", page_icon="⚖️", layout="wide")


# ---------------------------------------------------------------- API 封装
def api_call(method: str, path: str, data: dict = None, use_session: bool = True):
    """统一 API 调用，携带 session cookie，返回 (code, data, msg)。"""
    url = BACKEND + path
    cookies = {"session": st.session_state.get("session_cookie")} if use_session else {}
    try:
        if method == "GET":
            resp = requests.get(url, params=data, cookies=cookies)
        elif method == "POST":
            resp = requests.post(url, json=data, cookies=cookies)
        elif method == "PUT":
            resp = requests.put(url, json=data, cookies=cookies)
        elif method == "DELETE":
            resp = requests.delete(url, cookies=cookies)
        else:
            return None, None, "unsupported method"
        # 保存 session cookie
        if "session" in resp.cookies:
            st.session_state["session_cookie"] = resp.cookies["session"]
        body = resp.json()
        return body.get("code"), body.get("data"), body.get("msg")
    except requests.exceptions.ConnectionError:
        return None, None, "无法连接后端，请先启动后端服务 (run_backend.py)"
    except Exception as e:
        return None, None, f"请求异常: {e}"


def is_logged_in() -> bool:
    return bool(st.session_state.get("session_cookie"))


def current_user() -> dict | None:
    return st.session_state.get("user_info")


def logout():
    api_call("POST", "/api/auth/logout")
    st.session_state.pop("session_cookie", None)
    st.session_state.pop("user_info", None)
    st.rerun()


# ---------------------------------------------------------------- 顶栏
MENU_ITEMS = [
    ("题目", "📚"),
    ("评测提交", "🚀"),
    ("用户", "👤"),
    ("用户管理", "🛠️"),
    ("AI 命题", "🤖"),
]


def inject_css():
    """注入全局样式：隐藏默认框架元素，美化顶栏与导航按钮。"""
    st.markdown(
        """
        <style>
        header[data-testid="stHeader"] { background: transparent; }
        #MainMenu, footer { visibility: hidden; }
        .block-container {
            padding-top: 0.8rem;
            padding-bottom: 2rem;
            max-width: 1240px;
        }
        /* 隐藏 iframe 组件默认边框与滚动 */
        iframe {
            border: none !important;
        }
        .oj-divider {
            border-top: 1px solid #e6ebef;
            margin: 14px 0 16px 0;
        }
        /* 顶栏标题 */
        .oj-title {
            font-size: 21px;
            font-weight: 800;
            color: #1a2a6c;
            letter-spacing: 1px;
            white-space: nowrap;
            line-height: 1.2;
        }
        .oj-subtitle {
            font-size: 10px;
            color: #8a9aa5;
            letter-spacing: 2px;
            white-space: nowrap;
        }
        /* 导航按钮：胶囊样式，保证完整可点击、不换行 */
        .oj-navbtn button {
            width: 100%;
            border-radius: 10px;
            border: 1px solid #d6dfe4;
            padding: 7px 10px;
            font-size: 13px;
            white-space: nowrap !important;
            transition: all .15s ease;
            min-height: 40px;
        }
        .oj-navbtn button:hover {
            border-color: #1a2a6c;
            color: #1a2a6c;
        }
        /* 顶栏右侧：用户信息行 + 退出按钮 */
        .oj-user-row {
            text-align: right;
            line-height: 1.4;
            min-height: 22px;
        }
        .oj-logout-wrap {
            display: flex;
            justify-content: flex-end;
            margin-top: 2px;
        }
        .oj-logout-wrap button {
            width: auto;
            border-radius: 8px;
            border: 1px solid #d6dfe4;
            padding: 3px 12px;
            font-size: 12px;
            white-space: nowrap !important;
            min-height: 28px;
        }
        /* 用户区文字 */
        .oj-user-name {
            font-size: 15px;
            font-weight: 700;
            color: #1a2a6c;
        }
        .oj-user-role {
            display: inline-block;
            background: #eef1ff;
            color: #1a2a6c;
            border-radius: 10px;
            padding: 1px 9px;
            font-size: 11px;
            margin-left: 6px;
        }
        .oj-user-guest {
            color: #8a9aa5;
            font-size: 14px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_topbar():
    """顶栏：左 logo+标题，中导航按钮（原生 st.button），右用户信息。

    导航用 Streamlit 原生 st.button，点击走 rerun 机制，保证当前页内切换、
    点击区域完整可靠（不再用 iframe <a> 跳转，避免被组件沙箱拦截导致点不动）。
    """
    inject_css()

    current = st.session_state.get("menu", "题目")

    # 三区布局：左标题 / 中导航 / 右用户（垂直居中对齐）
    col_brand, col_nav, col_user = st.columns(
        [1.25, 4.0, 1.25], gap="small", vertical_alignment="center"
    )

    # 左：logo + 标题
    with col_brand:
        st.markdown(
            '<div style="display:flex;align-items:center;gap:10px;">'
            '<span style="font-size:26px;line-height:1;">⚖️</span>'
            '<span style="display:flex;flex-direction:column;line-height:1.2;">'
            '<span class="oj-title">OJ 在线评测系统</span>'
            '<span class="oj-subtitle">ONLINE JUDGE</span>'
            "</span></div>",
            unsafe_allow_html=True,
        )

    # 中：导航按钮（原生 button，当前页切换）
    with col_nav:
        nav_cols = st.columns(len(MENU_ITEMS), gap="small", vertical_alignment="center")
        for i, (name, icon) in enumerate(MENU_ITEMS):
            with nav_cols[i]:
                active = name == current
                btn_type = "primary" if active else "secondary"
                # 用 markdown 包裹类名以便 CSS 定位（原生 button 保证可点）
                st.markdown('<div class="oj-navbtn"></div>', unsafe_allow_html=True)
                if st.button(
                    f"{icon} {name}",
                    key=f"navbtn_{name}",
                    type=btn_type,
                    use_container_width=True,
                ):
                    st.session_state["menu"] = name
                    st.rerun()

    # 右：用户信息（含退出登录按钮，登录后显示）
    with col_user:
        if is_logged_in() and current_user():
            u = current_user()
            role_map = {"admin": "管理员", "user": "用户", "banned": "已封禁"}
            role_text = role_map.get(u["role"], u["role"])
            # 用户信息与退出按钮同一行：用户名靠右，退出按钮紧随其后
            st.markdown(
                f'<div class="oj-user-row">'
                f'<span class="oj-user-name">{u["username"]}</span>'
                f'<span class="oj-user-role">{role_text}</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="oj-logout-wrap"></div>', unsafe_allow_html=True)
            if st.button("退出登录", key="topbar_logout"):
                logout()
        else:
            st.markdown(
                '<div style="text-align:right;line-height:2.6;">'
                '<span class="oj-user-guest">未登录</span></div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="oj-divider"></div>', unsafe_allow_html=True)
    return current


# ---------------------------------------------------------------- 用户页面
def _inject_password_guard():
    """禁止密码输入框的粘贴(paste)、复制(copy)、剪切(cut)操作。

    Streamlit 的 st.text_input(type="password") 无原生禁止参数，
    故用 components.html 注入 JS，在父页面(Streamlit 主文档)上
    拦截密码框的剪贴板事件；并用 MutationObserver 兜底，保证
    Streamlit rerun 重新渲染输入框后仍能生效。
    """
    components.html(
        """
        <script>
        (function () {
          function guard(el) {
            if (!el || el.dataset.pwdGuarded) return;
            el.dataset.pwdGuarded = "1";
            el.addEventListener("paste", function (e) {
              e.preventDefault();
            });
            el.addEventListener("copy", function (e) {
              e.preventDefault();
            });
            el.addEventListener("cut", function (e) {
              e.preventDefault();
            });
          }
          function scan() {
            try {
              var doc = window.parent.document;
              doc.querySelectorAll('input[type="password"]').forEach(guard);
            } catch (err) {}
          }
          scan();
          // 兜底：监听父文档 DOM 变化，处理 rerun 后新增的输入框
          try {
            var doc = window.parent.document;
            var obs = new MutationObserver(function () { scan(); });
            obs.observe(doc.body, { childList: true, subtree: true });
          } catch (err) {}
        })();
        </script>
        """,
        height=0,
        scrolling=False,
    )


def render_login():
    st.subheader("登录 / 注册")
    _inject_password_guard()
    tab1, tab2 = st.tabs(["登录", "注册"])

    with tab1:
        with st.form("login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            if st.form_submit_button("登录"):
                code, data, msg = api_call(
                    "POST", "/api/auth/login",
                    {"username": username, "password": password}, use_session=False,
                )
                if code == 200:
                    st.session_state["user_info"] = data
                    st.success("登录成功")
                    st.rerun()
                else:
                    st.error(f"登录失败: {msg}")

    with tab2:
        with st.form("register_form"):
            username = st.text_input("用户名 (3-40字符)", key="reg_name")
            password = st.text_input("密码 (至少6位)", type="password", key="reg_pwd")
            if st.form_submit_button("注册"):
                code, data, msg = api_call(
                    "POST", "/api/users/",
                    {"username": username, "password": password}, use_session=False,
                )
                if code == 200:
                    st.success(f"注册成功，欢迎 {data['username']}！请登录。")
                else:
                    st.error(f"注册失败: {msg}")


def render_user_info():
    st.subheader("用户信息")
    u = current_user()
    if not u:
        st.warning("请先登录")
        return
    code, data, msg = api_call("GET", f"/api/users/{u['user_id']}")
    if code == 200:
        st.json(data)
    else:
        st.error(msg)


# ---------------------------------------------------------------- 题目页面
def render_problem_list():
    st.subheader("题目列表")
    code, data, msg = api_call("GET", "/api/problems/")
    if code != 200:
        st.error(msg)
        return
    if not data:
        st.info("暂无题目")
        return
    for p in data:
        if st.button(f"{p['id']} — {p['title']}", key=f"prob_{p['id']}"):
            st.session_state["view_problem_id"] = p["id"]


def render_problem_detail():
    pid = st.session_state.get("view_problem_id")
    if not pid:
        return
    st.subheader(f"题目详情: {pid}")
    code, data, msg = api_call("GET", f"/api/problems/{pid}")
    if code == 200:
        st.markdown(f"### {data['title']}")
        st.write(data["description"])
        st.markdown("**输入格式**")
        st.write(data["input_description"])
        st.markdown("**输出格式**")
        st.write(data["output_description"])
        st.markdown("**样例**")
        for i, s in enumerate(data.get("samples", [])):
            st.markdown(f"样例 {i+1}:")
            st.code(f"输入: {s['input']}\n输出: {s['output']}")
        st.markdown(f"**限制**: {data.get('constraints', '')}")
        if data.get("hint"):
            st.markdown(f"**提示**: {data['hint']}")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"时间限制: {data.get('time_limit', 3.0)}s")
        with col2:
            st.write(f"内存限制: {data.get('memory_limit', 128)}MB")
    else:
        st.error(msg)
    if st.button("返回列表"):
        st.session_state.pop("view_problem_id", None)
        st.rerun()


def render_problem_create():
    st.subheader("新增题目")
    with st.form("create_problem_form"):
        pid = st.text_input("题目 ID (必填)")
        title = st.text_input("标题 (必填)")
        description = st.text_area("题目描述 (必填)")
        input_desc = st.text_area("输入格式说明 (必填)")
        output_desc = st.text_area("输出格式说明 (必填)")
        constraints = st.text_input("数据限制 (必填)")
        samples = st.text_area("样例 (JSON数组，元素含input/output)")
        testcases = st.text_area("测试点 (JSON数组，元素含input/output)")
        hint = st.text_input("提示 (可选)")
        time_limit = st.number_input("时间限制(s)", value=3.0, step=0.5)
        memory_limit = st.number_input("内存限制(MB)", value=128, step=16)
        if st.form_submit_button("提交"):
            try:
                samples_list = json.loads(samples) if samples else []
                testcases_list = json.loads(testcases) if testcases else []
            except json.JSONDecodeError:
                st.error("样例/测试点必须是合法 JSON")
                st.stop()
            payload = {
                "id": pid, "title": title, "description": description,
                "input_description": input_desc, "output_description": output_desc,
                "samples": samples_list, "constraints": constraints,
                "testcases": testcases_list, "hint": hint,
                "time_limit": time_limit, "memory_limit": memory_limit,
            }
            code, data, msg = api_call("POST", "/api/problems/", payload)
            if code == 200:
                st.success(f"题目 {data['id']} 添加成功")
            else:
                st.error(f"添加失败: {msg}")


def render_problem_delete():
    st.subheader("删除题目 (仅管理员)")
    code, data, msg = api_call("GET", "/api/problems/")
    if code != 200:
        st.error(msg)
        return
    if not data:
        st.info("暂无题目")
        return
    pid = st.selectbox("选择题目", [p["id"] for p in data])
    if st.button("删除", type="primary"):
        code, data, msg = api_call("DELETE", f"/api/problems/{pid}")
        if code == 200:
            st.success(f"题目 {pid} 已删除")
        else:
            st.error(f"删除失败: {msg}")


# ---------------------------------------------------------------- 评测提交页面
def render_submission():
    st.subheader("提交代码")
    code, probs, msg = api_call("GET", "/api/problems/")
    if code != 200:
        st.error(msg)
        return
    if not probs:
        st.info("暂无题目可提交")
        return

    code, langs, msg = api_call("GET", "/api/languages/")
    lang_names = langs.get("name", []) if langs else []

    with st.form("submit_form"):
        pid = st.selectbox("题目", [p["id"] for p in probs])
        lang = st.selectbox("语言", lang_names)
        code_text = st.text_area("代码", height=300)
        if st.form_submit_button("提交评测"):
            code, data, msg = api_call(
                "POST", "/api/submissions/",
                {"problem_id": pid, "language": lang, "code": code_text},
            )
            if code == 200:
                st.session_state["last_submission_id"] = data["submission_id"]
                st.success(f"提交成功，submission_id={data['submission_id']}")
            else:
                st.error(f"提交失败: {msg}")


def render_submission_list():
    st.subheader("提交记录")
    code, probs, _ = api_call("GET", "/api/problems/")
    problem_ids = [p["id"] for p in probs] if probs else []

    col1, col2 = st.columns(2)
    with col1:
        pid = st.selectbox("按题目筛选", ["(全部)"] + problem_ids)
    with col2:
        status = st.selectbox("按状态筛选", ["(全部)", "pending", "success", "error"])

    params = {}
    if pid != "(全部)":
        params["problem_id"] = pid
    if status != "(全部)":
        params["status"] = status

    code, data, msg = api_call("GET", "/api/submissions/", params)
    if code != 200:
        st.error(msg)
        return
    subs = data.get("submissions", []) if data else []
    if not subs:
        st.info("暂无提交记录")
        return
    for s in subs:
        sid = s["submission_id"]
        score = s.get("score")
        score_str = f" | 得分 {score}" if score is not None else ""
        if st.button(f"{sid} — {s['status']}{score_str}", key=f"sub_{sid}"):
            st.session_state["view_submission_id"] = sid


def render_submission_detail():
    sid = st.session_state.get("view_submission_id")
    if not sid:
        return
    st.subheader(f"提交详情: {sid}")

    code, data, msg = api_call("GET", f"/api/submissions/{sid}")
    if code != 200:
        st.error(msg)
        return

    if data.get("status") == "pending":
        st.info("评测进行中...")
    else:
        st.write(f"**状态**: {data.get('status')}")
        st.write(f"**得分**: {data.get('score')} / {data.get('counts', 0) * 10}")
        if data.get("compile_info"):
            ci = data["compile_info"]
            st.markdown(f"**编译结果**: {ci.get('result')}")
            if ci.get("message"):
                st.code(ci["message"])
        if data.get("error_info"):
            st.error(data["error_info"])

        # 日志明细
        code, log, msg = api_call("GET", f"/api/submissions/{sid}/log")
        if code == 200 and log and log.get("details"):
            st.markdown("**测试点明细**")
            rows = []
            for d in log["details"]:
                rows.append({
                    "测试点": d["id"],
                    "结果": d["result"],
                    "时间(s)": d["time"],
                    "内存(MB)": d["memory"],
                })
            st.table(rows)

    if st.button("返回列表"):
        st.session_state.pop("view_submission_id", None)
        st.rerun()


# ---------------------------------------------------------------- 用户管理页面
def render_user_admin():
    st.subheader("用户管理 (仅管理员)")
    u = current_user()
    if not u or u.get("role") != "admin":
        st.warning("需要管理员权限")
        return

    tab1, tab2, tab3 = st.tabs(["用户列表", "变更角色", "访问审计"])

    with tab1:
        code, data, msg = api_call("GET", "/api/users/")
        if code == 200 and data:
            rows = []
            for user in data.get("users", []):
                rows.append({
                    "ID": user["user_id"],
                    "用户名": user["username"],
                    "角色": user["role"],
                    "加入时间": user.get("join_time", ""),
                    "提交数": user.get("submit_count", 0),
                    "通过数": user.get("resolve_count", 0),
                })
            st.table(rows)
        else:
            st.error(msg)

    with tab2:
        code, data, msg = api_call("GET", "/api/users/")
        if code == 200 and data:
            users = data.get("users", [])
            uid_map = {u["username"]: u["user_id"] for u in users}
            username = st.selectbox("选择用户", list(uid_map.keys()))
            role = st.selectbox("新角色", ["user", "admin", "banned"])
            if st.button("更新角色"):
                code, d, msg = api_call(
                    "PUT", f"/api/users/{uid_map[username]}/role", {"role": role}
                )
                if code == 200:
                    st.success(f"已将 {username} 角色改为 {role}")
                else:
                    st.error(msg)

    with tab3:
        code, data, msg = api_call("GET", "/api/logs/access/")
        if code == 200 and data:
            rows = []
            for log in data.get("logs", []):
                rows.append({
                    "用户": log.get("user_id"),
                    "题目": log.get("problem_id"),
                    "操作": log.get("action"),
                    "时间": log.get("time"),
                    "状态": log.get("status"),
                })
            st.table(rows)
        else:
            st.error(msg)


# ---------------------------------------------------------------- AI 命题页面
def render_ai():
    st.subheader("AI 智能命题")
    tab1, tab2 = st.tabs(["模型配置", "智能命题"])

    with tab1:
        render_ai_model_config()

    with tab2:
        render_ai_problem()


def render_ai_model_config():
    st.markdown("**配置模型提供商（OpenAI 兼容接口）**")
    code, cfg, _ = api_call("GET", "/api/ai/model-config")
    current = cfg or {}

    with st.form("ai_model_config_form"):
        provider_url = st.text_input(
            "提供商 URL", value=current.get("provider_url", ""),
            placeholder="https://api.example.com/v1",
        )
        model = st.text_input(
            "模型名称", value=current.get("model", ""),
            placeholder="gpt-4o-mini",
        )
        api_key = st.text_input("模型密钥 (API Key)", type="password")
        col1, col2, col3 = st.columns(3)
        with col1:
            input_price = st.number_input(
                "输入单价", value=float(current.get("input_price", 0.0)),
                format="%.6f",
            )
        with col2:
            output_price = st.number_input(
                "输出单价", value=float(current.get("output_price", 0.0)),
                format="%.6f",
            )
        with col3:
            price_unit = st.number_input(
                "计价单位(Token)", value=int(current.get("price_unit", 1000000)),
            )
        if st.form_submit_button("保存配置"):
            code, data, msg = api_call("PUT", "/api/ai/model-config", {
                "provider_url": provider_url,
                "model": model,
                "api_key": api_key,
                "input_price": input_price,
                "output_price": output_price,
                "price_unit": int(price_unit),
            })
            if code == 200:
                st.success("模型配置已更新")
            else:
                st.error(f"配置失败: {msg}")

    if current.get("provider_url"):
        st.info(
            f"当前配置：{current.get('provider_url')} / {current.get('model')} "
            f"（密钥{'已' if current.get('api_key_configured') else '未'}配置）"
        )


def render_ai_problem():
    st.markdown("**输入命题需求，AI 将生成完整题目（含测试点）**")

    code, probs, _ = api_call("GET", "/api/problems/")
    problem_ids = ["(不参考)"] + [p["id"] for p in probs] if probs else ["(不参考)"]

    with st.form("ai_problem_form"):
        requirement = st.text_area(
            "命题需求", height=120,
            placeholder="例：设计一道考察「贪心算法」的中等难度题目，数据规模 1e5，需要 O(n log n) 解法",
        )
        ref_pid = st.selectbox("参考已有题目（可选）", problem_ids)
        if st.form_submit_button("开始命题"):
            if not requirement.strip():
                st.error("请填写命题需求")
            else:
                payload = {"requirement": requirement.strip()}
                if ref_pid != "(不参考)":
                    payload["problem_id"] = ref_pid
                code, data, msg = api_call("POST", "/api/ai/problem-tasks/", payload)
                if code == 200:
                    st.session_state["ai_task_id"] = data["task_id"]
                    st.success("任务已创建")
                    st.rerun()
                else:
                    st.error(f"创建失败: {msg}")

    # 展示当前任务状态
    task_id = st.session_state.get("ai_task_id")
    if task_id:
        render_ai_task_status(task_id)


def render_ai_task_status(task_id: str):
    st.divider()
    st.markdown(f"**任务 {task_id}**")

    code, data, msg = api_call("GET", f"/api/ai/problem-tasks/{task_id}")
    if code != 200:
        st.error(msg)
        return

    status = data.get("status")
    progress = data.get("progress", "")
    result = data.get("result")
    usage = data.get("usage", {})
    error_info = data.get("error_info", "")

    # 状态展示
    status_map = {
        "pending": "⏳ 等待中",
        "running": "🔄 执行中",
        "completed": "✅ 已完成",
        "cancelled": "⛔ 已中断",
        "failed": "❌ 失败",
    }
    st.write(f"**状态**: {status_map.get(status, status)}")
    st.write(f"**进度**: {progress}")

    if error_info:
        st.error(error_info)

    # Token 用量与费用
    if usage:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("输入 Token", usage.get("input_tokens", 0))
        col2.metric("输出 Token", usage.get("output_tokens", 0))
        col3.metric("总 Token", usage.get("total_tokens", 0))
        col4.metric("费用", f"${usage.get('cost', 0.0):.6f} {usage.get('currency', 'USD')}")

    # 运行中：刷新 + 中断按钮
    if status in ("pending", "running"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("刷新状态", use_container_width=True):
                st.rerun()
        with col2:
            if st.button("中断任务", type="primary", use_container_width=True):
                code, _, msg = api_call("PUT", f"/api/ai/problem-tasks/{task_id}/cancel")
                if code == 200:
                    st.warning("任务已中断")
                    st.rerun()
                else:
                    st.error(msg)

    # 完成：展示结果 + 导入题目
    if status == "completed" and result:
        st.markdown("**生成的题目**")
        st.json(result)

        st.markdown("**导入到题库**")
        with st.form("ai_import_form"):
            st.write("可直接导入，或修改后再导入")
            result_json = st.text_area(
                "题目 JSON", value=json.dumps(result, ensure_ascii=False, indent=2),
                height=300,
            )
            if st.form_submit_button("导入题目"):
                try:
                    problem = json.loads(result_json)
                except json.JSONDecodeError:
                    st.error("JSON 格式错误")
                    st.stop()
                code, data, msg = api_call("POST", "/api/problems/", problem)
                if code == 200:
                    st.success(f"题目 {data['id']} 已导入题库")
                else:
                    st.error(f"导入失败: {msg}")


# ---------------------------------------------------------------- 主入口
def main():
    menu = render_topbar()

    if not is_logged_in():
        render_login()
        return

    if menu == "用户":
        render_user_info()
    elif menu == "题目":
        if "view_problem_id" in st.session_state:
            render_problem_detail()
        else:
            sub = st.radio(
                "题目操作", ["查看列表", "新增题目", "删除题目"],
                horizontal=True, label_visibility="collapsed", key="problem_sub",
            )
            if sub == "查看列表":
                render_problem_list()
            elif sub == "新增题目":
                render_problem_create()
            else:
                render_problem_delete()
    elif menu == "评测提交":
        if "view_submission_id" in st.session_state:
            render_submission_detail()
        else:
            sub = st.radio(
                "评测操作", ["提交代码", "提交记录"],
                horizontal=True, label_visibility="collapsed", key="submit_sub",
            )
            if sub == "提交代码":
                render_submission()
            else:
                render_submission_list()
    elif menu == "用户管理":
        render_user_admin()
    elif menu == "AI 命题":
        render_ai()


if __name__ == "__main__":
    main()
