"""生成实验报告配图：系统架构图 + 评测流程图。

用 PIL 绘制，输出 PNG，供 HTML 报告内嵌引用。
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# 尝试加载中文字体
def _font(size, bold=False):
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",        # 微软雅黑
        r"C:\Windows\Fonts\msyhbd.ttc",      # 微软雅黑粗体
        r"C:\Windows\Fonts\simhei.ttf",      # 黑体
        r"C:\Windows\Fonts\simsun.ttc",      # 宋体
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_box(d, xy, text, fill, text_fill="white", font_size=16, radius=8):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)
    f = _font(font_size, bold=True)
    # 简单居中
    lines = text.split("\n")
    total_h = len(lines) * (font_size + 4)
    y = y0 + (y1 - y0 - total_h) / 2
    for ln in lines:
        w = d.textlength(ln, font=f)
        tx = x0 + (x1 - x0 - w) / 2
        d.text((tx, y), ln, fill=text_fill, font=f)
        y += font_size + 4


def _arrow(d, p0, p1, color="#666666", width=2):
    d.line([p0, p1], fill=color, width=width)
    # 箭头
    import math
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    L = 12
    a1 = ang + math.radians(150)
    a2 = ang - math.radians(150)
    d.line([p1, (p1[0] + L * math.cos(a1), p1[1] + L * math.sin(a1))], fill=color, width=width)
    d.line([p1, (p1[0] + L * math.cos(a2), p1[1] + L * math.sin(a2))], fill=color, width=width)


def gen_architecture():
    W, H = 1280, 820
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # 标题
    f_title = _font(34, bold=True)
    title = "OJ 系统整体架构"
    d.text((W / 2 - d.textlength(title, font=f_title) / 2, 28),
           title, fill="#1a1a2e", font=f_title)

    # 三层结构
    # 前端层
    _draw_box(d, (60, 110, W - 60, 210), "", "#4e79a7", font_size=22)
    d.text((100, 130), "Streamlit 前端（frontend/app.py，1899 行）", fill="white", font=_font(20, bold=True))
    d.text((100, 170), "· 用户页面：注册 / 登录 / 个人中心", fill="white", font=_font(15))
    d.text((460, 170), "· 题目页面：列表 / 详情 / 新增 / 编辑", fill="white", font=_font(15))
    d.text((820, 170), "· 评测提交：选择题目与语言，查看评测结果", fill="white", font=_font(15))
    d.text((100, 192), "· AI 命题页面：模型配置 / 需求输入 / 进度展示 / 历史任务", fill="white", font=_font(15))

    # 箭头：前端 -> 后端
    _arrow(d, (W / 2, 215), (W / 2, 250), "#4e79a7", 3)
    d.text((W / 2 + 15, 220), "REST API（HTTP + Session 鉴权）", fill="#4e79a7", font=_font(16, bold=True))

    # 后端层
    _draw_box(d, (60, 265, W - 60, 470), "", "#59a14f", font_size=22)
    d.text((100, 285), "FastAPI 后端（全 async def 异步接口，2535 行，30+ 接口）", fill="white", font=_font(20, bold=True))

    # 路由层
    d.text((100, 330), "路由层 app/routers/", fill="white", font=_font(18, bold=True))
    d.text((100, 360), "· problems · languages", fill="white", font=_font(15))
    d.text((100, 384), "· submissions · users", fill="white", font=_font(15))
    d.text((100, 408), "· logs · ai", fill="white", font=_font(15))

    # 评测引擎
    d.text((460, 330), "评测引擎 app/judge/", fill="white", font=_font(18, bold=True))
    d.text((460, 360), "· runner：subprocess 异步执行", fill="white", font=_font(15))
    d.text((460, 384), "· engine：编译/运行/比对/判定", fill="white", font=_font(15))
    d.text((460, 408), "· queue：异步评测队列与状态更新", fill="white", font=_font(15))

    # AI 模块
    d.text((820, 330), "AI 模块 app/ai/", fill="white", font=_font(18, bold=True))
    d.text((820, 360), "· llm：httpx 调用 chat completions", fill="white", font=_font(15))
    d.text((820, 384), "· engine：命题任务状态机", fill="white", font=_font(15))
    d.text((820, 408), "· 用量统计与费用计算", fill="white", font=_font(15))

    # 共享层
    d.text((100, 444), "共享：config / storage / schemas / models / deps（Session 认证 + 频率限制）", fill="white", font=_font(15))

    # 箭头：后端 -> 存储
    _arrow(d, (W / 2, 485), (W / 2, 520), "#59a14f", 3)
    d.text((W / 2 + 15, 490), "JSON 文件读写", fill="#59a14f", font=_font(16, bold=True))

    # 存储层
    _draw_box(d, (60, 535, W - 60, 600), "", "#f28e2b", font_size=20)
    d.text((100, 555), "JSON 文件存储（app/storage.py）", fill="white", font=_font(18, bold=True))
    d.text((100, 580), "data/problems/ · data/users/ · data/submissions/ · data/logs/ · data/ai_tasks/ · data/audit_logs.json", fill="white", font=_font(15))

    # 箭头：存储 -> 运行环境
    _arrow(d, (W / 2, 615), (W / 2, 650), "#f28e2b", 3)

    # 底层
    _draw_box(d, (60, 665, W - 60, 740), "运行环境：Python 3.13 + subprocess 子进程沙箱（时间/内存隔离）", "#76b7b2", font_size=20)

    img.save(os.path.join(HERE, "architecture.png"), "PNG")
    print("architecture.png saved")


def gen_judge_flow():
    W, H = 1200, 900
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    f_title = _font(30, bold=True)
    d.text((W / 2 - d.textlength("异步评测引擎流程", font=f_title) / 2, 24),
           "异步评测引擎流程", fill="#1a1a2e", font=f_title)

    steps = [
        ("提交代码", "#4e79a7"),
        ("写入临时目录\n写入源码文件", "#59a14f"),
        ("编译\n(有 compile_cmd)", "#f28e2b"),
        ("逐测试点运行\nsubprocess 子进程", "#e15759"),
        ("资源监控\nwait_for 超时 + psutil 内存", "#76b7b2"),
        ("输出比对\n规范化后逐行比较", "#af7aa1"),
        ("判定状态\nAC/WA/TLE/MLE/RE/CE", "#edc948"),
        ("汇总计分\n每测试点 10 分", "#4e79a7"),
    ]

    x = 100
    y = 100
    w = 1000
    h = 78
    gap = 20
    for i, (txt, color) in enumerate(steps):
        _draw_box(d, (x, y, x + w, y + h), txt, color, font_size=20)
        if i < len(steps) - 1:
            _arrow(d, (x + w / 2, y + h + 2), (x + w / 2, y + h + gap - 4), "#666", 3)
        y += h + gap

    img.save(os.path.join(HERE, "judge_flow.png"), "PNG")
    print("judge_flow.png saved")


def gen_ai_flow():
    W, H = 1200, 780
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    f_title = _font(30, bold=True)
    title = "AI 智能命题：分阶段生成、标程验证与数据质量保障"
    d.text((W / 2 - d.textlength(title, font=f_title) / 2, 24),
           title, fill="#1a1a2e", font=f_title)

    # 阶段流程（横向两列）
    steps = [
        ("① 提交命题需求", "构建 prompt（知识点/难度/参考题目）", "#4e79a7"),
        ("② 生成题目主体 + 测试点规划", "LLM 返回题目 JSON 与 testcase_plan（小/大测试点比例）", "#59a14f"),
        ("③ 分批生成小测试点", "每批 4 个凑够规划数量，单批网络抖动自动重试", "#f28e2b"),
        ("④ 标程重算验证", "模型写标程跑样例自检，重算每个测试点 output 并丢弃坏数据", "#e15759"),
        ("⑤ 生成器产出大测试点", "模型写生成器脚本，本地执行逼近 constraints 上限的数据", "#af7aa1"),
        ("⑥ 校验补全 + 表单导入题库", "必填字段校验 + 默认值补全，可直接/修改后导入", "#76b7b2"),
    ]
    x = 70
    y = 100
    w = 1060
    h = 64
    gap = 14
    for i, (name, desc, color) in enumerate(steps):
        _draw_box(d, (x, y, x + w, y + h), name, color, font_size=18)
        d.text((x + w + 15, y + h / 2 - 8), desc, fill="#333333", font=_font(15))
        if i < len(steps) - 1:
            _arrow(d, (x + w / 2, y + h + 2), (x + w / 2, y + h + gap - 4), "#666", 3)
        y += h + gap

    # 中断机制说明框
    _draw_box(d, (70, y + 10, W - 70, y + 112), "", "#f0f5fa", font_size=16)
    d.text((95, y + 24), "中断机制：真正终止大模型输出", fill="#2a4d75", font=_font(18, bold=True))
    d.text((95, y + 56), "· 全局协程注册表 _RUNNING_TASKS：task_id → asyncio.Task，start_task 登记、结束自动移除",
           fill="#1a1a2e", font=_font(15))
    d.text((95, y + 78), "· cancel 接口调用 task.cancel() 触发 CancelledError，立即打断进行中的 httpx LLM HTTP 请求",
           fill="#1a1a2e", font=_font(15))
    d.text((95, y + 100), "· 网络抖动容错：单次 SSL/空响应自动重试，单批失败不整体失败；服务重启后遗留任务自动标记失效",
           fill="#1a1a2e", font=_font(15))

    img.save(os.path.join(HERE, "ai_flow.png"), "PNG")
    print("ai_flow.png saved")


if __name__ == "__main__":
    gen_architecture()
    gen_judge_flow()
    gen_ai_flow()
    print("全部配图生成完成")
