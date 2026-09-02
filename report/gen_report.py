"""生成实验报告：HTML 报告 + Edge headless 转 PDF。

报告内容按 requirements.md 的评分点组织：
- 系统功能与设计（2 分）
- 关键实现与难点（2 分）
- 成果展示（1 分）
- AI 使用说明（0 分）
- 总结与建议（0 分）
"""
import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
HTML_PATH = os.path.join(HERE, "report.html")
PDF_PATH = os.path.join(HERE, "实验报告.pdf")

# 找到 Edge
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def find_browser():
    for p in EDGE_PATHS:
        if os.path.exists(p):
            return p
    raise RuntimeError("未找到 Edge/Chrome，无法生成 PDF")


# ============================================================ HTML 报告
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>程序设计训练 OJ 系统 实验报告</title>
<style>
  @page {
    size: A4;
    margin: 20mm 18mm 22mm 18mm;
    @bottom-center {
      content: counter(page) " / " counter(pages);
      font-size: 9pt;
      color: #888;
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: "Microsoft YaHei", "PingFang SC", "SimHei", "Noto Sans CJK SC", sans-serif;
    color: #1a1a2e;
    line-height: 1.75;
    font-size: 11pt;
    margin: 0;
  }
  h1 {
    text-align: center;
    font-size: 22pt;
    color: #1a1a2e;
    margin: 0 0 6pt 0;
    border-bottom: 3px solid #4e79a7;
    padding-bottom: 12pt;
  }
  h2 {
    font-size: 16pt;
    color: #1a1a2e;
    margin: 22pt 0 10pt 0;
    padding: 6pt 12pt;
    background: linear-gradient(90deg, #4e79a7 0%, #6f9bd1 100%);
    color: white;
    border-radius: 4pt;
  }
  h3 {
    font-size: 13pt;
    color: #2a4d75;
    margin: 16pt 0 6pt 0;
    border-left: 4pt solid #4e79a7;
    padding-left: 8pt;
  }
  p, li { text-align: justify; }
  .meta {
    text-align: center;
    color: #666;
    font-size: 10pt;
    margin: 0 0 18pt 0;
  }
  .cover {
    page-break-after: always;
    text-align: center;
    padding-top: 80pt;
  }
  .cover h1 {
    font-size: 30pt;
    color: #1a1a2e;
    border: none;
    margin-bottom: 24pt;
  }
  .cover .subtitle {
    font-size: 16pt;
    color: #4e79a7;
    margin: 20pt 0;
  }
  .cover .info {
    margin: 60pt auto;
    width: 60%;
    font-size: 13pt;
    text-align: left;
  }
  .cover .info div {
    border-bottom: 1pt solid #ccc;
    padding: 8pt 0;
  }
  .toc {
    page-break-after: always;
  }
  .toc h2 { background: none; color: #1a1a2e; border-bottom: 2pt solid #4e79a7; }
  .toc ol { font-size: 12pt; }
  .toc li { margin: 8pt 0; }
  figure {
    text-align: center;
    margin: 16pt 0;
    page-break-inside: avoid;
  }
  figure img {
    max-width: 100%;
    border: 1pt solid #ddd;
    border-radius: 4pt;
  }
  figcaption {
    font-size: 10pt;
    color: #666;
    margin-top: 4pt;
    font-style: italic;
  }
  table {
    border-collapse: collapse;
    width: 100%;
    margin: 10pt 0;
    font-size: 10.5pt;
  }
  th {
    background: #4e79a7;
    color: white;
    padding: 6pt 10pt;
    text-align: left;
  }
  td {
    border: 1pt solid #ccc;
    padding: 5pt 10pt;
  }
  tr:nth-child(even) td { background: #f5f8fc; }
  code {
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    background: #f5f5f5;
    padding: 1pt 5pt;
    border-radius: 3pt;
    font-size: 10pt;
    color: #c7254e;
  }
  pre {
    background: #2d2d2d;
    color: #f8f8f2;
    padding: 10pt 14pt;
    border-radius: 4pt;
    overflow-x: auto;
    font-size: 9.5pt;
    line-height: 1.5;
    font-family: "Cascadia Code", "Consolas", monospace;
  }
  pre code { background: transparent; color: inherit; padding: 0; }
  .box {
    border-left: 4pt solid #4e79a7;
    background: #f0f5fa;
    padding: 8pt 14pt;
    margin: 10pt 0;
    border-radius: 0 4pt 4pt 0;
  }
  .box.warn { border-color: #e15759; background: #fcf0f0; }
  .box.tip { border-color: #59a14f; background: #f2f9f0; }
  .box strong { color: #1a1a2e; }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10pt;
    margin: 10pt 0;
  }
  .card {
    border: 1pt solid #ddd;
    border-radius: 4pt;
    padding: 8pt 12pt;
    background: #fafbfc;
  }
  .card h4 { margin: 0 0 4pt 0; color: #4e79a7; font-size: 11pt; }
  .card p { margin: 2pt 0; font-size: 10pt; }
  .ok { color: #2d8e3c; font-weight: bold; }
  .bad { color: #c92a2a; font-weight: bold; }
  .num { color: #2a4d75; font-weight: bold; }
</style>
</head>
<body>

<!-- ============================== 封面 ============================== -->
<section class="cover">
  <h1>程序设计训练<br>OJ 在线评测系统</h1>
  <div class="subtitle">—— 课程大作业实验报告 ——</div>
  <div class="info">
    <div><strong>作业模块：</strong>基础模块 Step 1–6（30 分）+ 进阶模块 AI 智能命题（10 分）</div>
    <div><strong>技术栈：</strong>FastAPI（异步） + Streamlit + JSON 文件存储 + subprocess/psutil 评测 + DeepSeek 大模型</div>
    <div><strong>代码规模：</strong>后端 17 个模块 2345 行 + 前端 1794 行 = 4139 行</div>
    <div><strong>git 提交：</strong>63 次 Conventional Commits 规范提交</div>
  </div>
  <div style="margin-top: 50pt; color: #888; font-size: 10pt;">
    报告生成于 2026 年 9 月
  </div>
</section>

<!-- ============================== 目录 ============================== -->
<section class="toc">
  <h2>目 录</h2>
  <ol>
    <li>系统功能与设计</li>
    <li>关键实现与难点</li>
    <li>成果展示</li>
    <li>AI 使用说明</li>
    <li>总结与建议</li>
  </ol>
</section>

<!-- ============================== 1. 系统功能与设计 ============================== -->
<h2>1. 系统功能与设计</h2>

<h3>1.1 系统目标</h3>
<p>本系统实现了一个轻量级但功能完整的 <strong>OJ（Online Judge）在线评测系统</strong>，覆盖题目管理、代码评测、用户与权限、评测日志、Streamlit 前端、<strong>AI 智能命题</strong>六大模块，<strong>所有后端 API 均使用 FastAPI 异步接口（<code>async def</code>）</strong>，符合"不使用异步编程的无法拿到本次作业分数"的硬性要求。</p>

<h3>1.2 系统架构</h3>
<p>系统采用经典的 <strong>前后端分离 + JSON 文件存储</strong>架构，自上而下分为四层：</p>

<figure>
  <img src="architecture.png" alt="系统架构图">
  <figcaption>图 1.1 OJ 系统整体架构</figcaption>
</figure>

<p><strong>前端层（Streamlit，<code>frontend/app.py</code>，1794 行）</strong>：通过 <code>requests</code> 库调用后端 REST API，不直接访问数据。包含用户、题目、评测提交、AI 命题四组页面，所有受保护操作均通过 Session Cookie 保持登录态，刷新页面通过 localStorage 恢复会话。</p>

<p><strong>后端层（FastAPI，<code>app/</code>，2345 行，30+ 个异步接口）</strong>：</p>
<div class="grid">
  <div class="card">
    <h4>路由层 <code>app/routers/</code></h4>
    <p>六个路由模块，分别对应 6 个功能域。</p>
  </div>
  <div class="card">
    <h4>评测引擎 <code>app/judge/</code></h4>
    <p>runner / engine / queue 三层结构。</p>
  </div>
  <div class="card">
    <h4>AI 模块 <code>app/ai/</code></h4>
    <p>llm 模型调用 + engine 任务状态机。</p>
  </div>
  <div class="card">
    <h4>共享基础设施</h4>
    <p>config / storage / schemas / models / deps（认证 + 限流）。</p>
  </div>
</div>

<p><strong>存储层（<code>app/storage.py</code>）</strong>：所有数据落盘到 <code>data/</code> 目录下的 JSON 文件，包括题目、用户、提交、日志、AI 任务、AI 模型配置、审计日志。读写采用 <code>_read_json</code>/<code>_write_json</code> 统一封装，通过临时文件 + 原子 rename 避免半写状态。</p>

<p><strong>运行环境</strong>：用户代码作为子进程拉起，<strong>时间限制</strong>通过 <code>asyncio.wait_for</code> 强制中断，<strong>内存限制</strong>通过 <code>psutil</code> 后台协程轮询 RSS 实现，跨平台兼容纯 Windows 与 Linux。</p>

<h3>1.3 技术选型</h3>
<table>
  <tr><th>维度</th><th>选型</th><th>理由</th></tr>
  <tr><td>Web 框架</td><td>FastAPI</td><td>原生 async/await 生态、OpenAPI 自动文档、Pydantic 校验</td></tr>
  <tr><td>前端框架</td><td>Streamlit</td><td>纯 Python、组件丰富、易于调用后端 API</td></tr>
  <tr><td>存储</td><td>JSON 文件</td><td>符合"题目配置加载"要求；零外部依赖；透明可读</td></tr>
  <tr><td>认证</td><td>SessionMiddleware + bcrypt</td><td>无需前端存 token；密码哈希安全</td></tr>
  <tr><td>评测执行</td><td>subprocess + psutil</td><td>跨平台、无需 Docker；时间用 wait_for、内存用 psutil 轮询</td></tr>
  <tr><td>LLM 调用</td><td>httpx</td><td>异步 HTTP 客户端，OpenAI 兼容 chat completions</td></tr>
</table>

<h3>1.4 模块划分</h3>
<p>六大模块对应六个 <code>routers/</code> 子模块，文件归属严格对应：</p>
<table>
  <tr><th>评分模块</th><th>对应文件</th><th>关键接口</th><th>分值</th></tr>
  <tr><td>Step 1 题目管理</td><td><code>app/routers/problems.py</code>（150 行）</td><td>GET/POST/PUT/DELETE <code>/api/problems/</code></td><td>5</td></tr>
  <tr><td>Step 2 评测控制</td><td><code>app/judge/</code>（429 行） + <code>routers/languages.py</code>（43 行）</td><td>POST <code>/api/submissions/</code>、<code>/api/languages/</code></td><td>5</td></tr>
  <tr><td>Step 3 评测管理</td><td><code>app/routers/submissions.py</code>（240 行）</td><td>GET 列表/详情、PUT rejudge</td><td>5</td></tr>
  <tr><td>Step 4 用户管理</td><td><code>app/routers/users.py</code>（235 行）</td><td>注册/登录/登出、PUT 角色</td><td>5</td></tr>
  <tr><td>Step 5 评测日志</td><td><code>app/routers/logs.py</code>（43 行）</td><td>GET 日志、PUT 可见性、GET 审计</td><td>5</td></tr>
  <tr><td>Step 6 前端</td><td><code>frontend/app.py</code>（1794 行）</td><td>—</td><td>5</td></tr>
  <tr><td>AI 智能命题</td><td><code>app/ai/</code>（545 行） + <code>routers/ai.py</code>（210 行）</td><td>配置/任务/进度/取消</td><td>10</td></tr>
</table>

<h3>1.5 统一响应结构</h3>
<p>所有 API 返回统一的 JSON 结构：<code>{code, msg, data}</code>。HTTP 状态码语义：<code>200</code> 正常 / <code>400</code> 参数错 / <code>401</code> 未登录 / <code>403</code> 权限不足或 banned / <code>404</code> 不存在 / <code>409</code> 冲突 / <code>429</code> 频率超限 / <code>500</code> 服务器异常。响应处理顺序为 401 → 403 → 400 → 429 → 409 → 404 → 500。</p>

<!-- ============================== 2. 关键实现与难点 ============================== -->
<h2>2. 关键实现与难点</h2>

<h3>2.1 异步评测引擎（核心难点）</h3>
<p>异步评测是本系统最复杂、最容易出错的部分。流程如下图：</p>

<figure>
  <img src="judge_flow.png" alt="评测流程图">
  <figcaption>图 2.1 异步评测引擎流程</figcaption>
</figure>

<p>关键设计点：</p>
<ul>
  <li><strong>异步执行</strong>：<code>asyncio.create_subprocess_exec</code> 拉起子进程，主线程不被阻塞，可并发处理多份提交。</li>
  <li><strong>时间限制</strong>：<code>asyncio.wait_for(proc.communicate(...), timeout=time_limit)</code> 强制中断，超时后调用 <code>_kill</code> 终止整个进程树（含子进程）。</li>
  <li><strong>内存限制</strong>：<code>psutil</code> 后台协程每 50ms 轮询 RSS，超限立即杀进程并置标志位。Windows 没有 Linux 的 <code>resource</code> / <code>ulimit</code>，这是 <code>psutil</code> 方案的优势。</li>
  <li><strong>状态判定</strong>：<code>_classify</code> 按 <code>timed_out → memory_exceeded → returncode → UNK → AC → WA</code> 优先级判定，编译失败时整提交标记为 CE。</li>
  <li><strong>输出比对</strong>：<code>_normalize_output</code> 统一处理 <code>\r\n</code> 换行、行尾空格、尾部空行，避免 Windows 评测踩坑。</li>
</ul>

<h3>2.2 路径含空格的处理（实战踩坑）</h3>
<div class="box warn">
  <strong>问题：</strong>项目路径为 <code>D:\Lai Siyu\University\Summer Semester 2025-2026\pe\bh2</code>，含空格。最初用 <code>cmd.split()</code> 拆分 <code>"python {src}"</code> 时，<code>{src}</code> 替换后路径中的空格把整个命令截断，<code>python</code> 找不到文件，所有提交都返回 RE。
</div>
<p><strong>解决方案</strong>：用 <code>shlex.split()</code> 解析命令，并在占位符替换时给路径加双引号：</p>
<pre><code>def _quote(path: str) -> str:
    return f'"{path}"'

def resolve_placeholders(cmd: str, src_path: str, exe_path: str) -> str:
    return cmd.replace("{src}", _quote(src_path)).replace("{exe}", _quote(exe_path))

def _parse_command(cmd: str) -> list[str]:
    return shlex.split(cmd, posix=True)</code></pre>
<p>修复后实测 AC / WA / TLE / RE / CE 全部正确判定。</p>

<h3>2.3 Session 认证与权限控制</h3>
<p>使用 <code>starlette.middleware.sessions.SessionMiddleware</code>，密钥来自 <code>config.SESSION_SECRET_KEY</code>。密码用 <code>bcrypt</code> 哈希后存储（<code>$2b$</code> 开头），登录时校验。</p>
<p>权限控制集中在 <code>app/deps.py</code>：</p>
<ul>
  <li><code>get_current_user(request)</code>：从 session 取 <code>user_id</code>，查 users 字典返回用户对象。</li>
  <li><code>is_admin(user)</code>：判断 <code>role == "admin"</code>。</li>
  <li><code>check_rate_limit(user_id)</code>：1 分钟内提交次数 ≥ 3 则返回 False（触发 429）。</li>
</ul>
<p>每个路由显式调用这些依赖，避免遗漏：</p>
<pre><code>async def create_problem(request: Request, problem: ProblemCreate):
    user = require_login_or_401(request)  # 401
    if not user: return err(401, "not logged in")
    # 普通用户也能上传题目，删除题目另需 admin</code></pre>

<h3>2.4 异步评测队列</h3>
<p>提交接口 <code>POST /api/submissions/</code> 不会同步阻塞：</p>
<ol>
  <li>写入提交 JSON，<code>status=pending</code>，立刻返回 <code>submission_id</code>；</li>
  <li><code>queue.start_worker()</code> 启动的 <code>asyncio.create_task</code> 后台协程从队列中取任务；</li>
  <li>调用 <code>judge_submission(submission)</code> 真正执行评测；</li>
  <li>结果原地写回提交 JSON，<code>status=success/error</code>。</li>
</ol>
<p>这样既能立即响应客户端，又能避免多次提交造成 OOM。</p>

<h3>2.5 AI 命题模块（进阶，核心难点）</h3>
<p>AI 模块采用 <strong>OpenAI 兼容 chat completions</strong> 接口（<code>httpx</code> 异步调用），实测接入 <strong>DeepSeek</strong> 大模型，支持任意 provider 可配置。命题流程采用 <strong>分阶段生成</strong>策略，每个阶段都写入任务 JSON 的 <code>progress</code> 字段，前端自动轮询拉取最新进度：</p>

<figure>
  <img src="ai_flow.png" alt="AI 命题流程图">
  <figcaption>图 2.2 AI 命题分阶段生成与中断机制</figcaption>
</figure>

<ol>
  <li><strong>分析需求</strong>：构造 prompt（系统提示词 + 用户需求 + 可选参考题目）。</li>
  <li><strong>生成题目主体</strong>：第一次调用 LLM，只生成题目字段（不含 testcases），控制单次输出长度。</li>
  <li><strong>解析 JSON</strong>：兼容 <code>```json</code> 代码块包裹或裸 JSON，并对截断做兜底修复。</li>
  <li><strong>生成测试点</strong>：第二次调用 LLM，把题目主体作为上下文，单独生成 ≥5 个测试点。</li>
  <li><strong>校验补全</strong>：检查必填字段、补充默认值、生成 <code>public_cases</code> 标志。</li>
  <li><strong>表单导入题库</strong>：前端复用题目表单展示结果，可直接或修改后导入。</li>
</ol>

<div class="box tip">
  <strong>难点一：大模型输出超长被截断。</strong>早期把「整题 + 测试点」一次性让模型生成，输出超过 <code>max_tokens</code> 被截断，导致 JSON 解析失败（实测两次失败：输出 4096、8191 token 均被截断）。解决思路是<strong>分阶段生成</strong>（主体与测试点分开两次调用），从根源上避免单次输出过长；同时增强 <code>parse_problem_json</code> 的截断兜底修复（顶层逗号截断 / 补闭合括号 / 逐字段回退三种策略）。改造后实测成功出题。
</div>

<div class="box tip">
  <strong>难点二：中断要「真正终止大模型输出」。</strong>若仅把任务状态置为 <code>cancelled</code>、依赖执行循环在阶段间检查，那么进行中的模型 HTTP 调用（几十秒）不会被打断，直到该次调用返回后才退出——这不满足「中断应实际终止任务」的要求。最终方案是维护一个全局协程注册表 <code>_RUNNING_TASKS</code>（<code>task_id → asyncio.Task</code>），中断时调用 <code>task.cancel()</code> 触发 <code>CancelledError</code>，<strong>立即打断正在 <code>await</code> 的 httpx 请求</strong>并关闭底层连接。实测运行中点击中断 → 立即 <code>cancelled</code>、<code>result=None</code>，未继续跑完剩余阶段。
</div>

<p><strong>Token 与费用</strong>：从 API 响应 <code>usage</code> 字段读取 <code>prompt_tokens</code> / <code>completion_tokens</code>，输入输出分离计价，费用公式：</p>
<pre><code>cost = (input_tokens / price_unit) * input_price
     + (output_tokens / price_unit) * output_price</code></pre>
<p>计价币种可配置（USD / CNY），DeepSeek 按人民币计价，实测生成「货架寻价」二分题：输入 1150 / 输出 16142 token，费用 <span class="num">¥0.223</span>。</p>

<p><strong>配置安全</strong>：API 密钥保存在服务器级配置 <code>data/ai_model_config.json</code>，查询接口只返回 <code>api_key_configured: true</code> 布尔标志、绝不回显明文；密钥输入框留空即「不修改」，避免改单价时误清空密钥。</p>

<h3>2.6 访问审计（评测日志可见性）</h3>
<p>每条 <code>GET /api/submissions/{id}/log</code> 请求都记录到 <code>data/audit_logs.json</code>，包含访问者、目标提交、时间、IP。访问权限三级：</p>
<ul>
  <li>提交者本人</li>
  <li>管理员</li>
  <li>任意登录用户（当题目设置 <code>public_cases=true</code> 时）</li>
</ul>

<!-- ============================== 3. 成果展示 ============================== -->
<h2>3. 成果展示</h2>

<h3>3.1 接口验收（端到端测试结果）</h3>
<p>系统启动后通过 curl 与 Python 脚本全量测试，所有功能与边界情况均符合预期：</p>

<table>
  <tr><th>场景</th><th>操作</th><th>结果</th><th>状态</th></tr>
  <tr><td>初始管理员</td><td>admin / admintestpassword 登录</td><td>200，session 写入</td><td class="ok">通过</td></tr>
  <tr><td>添加题目</td><td>POST /api/problems/</td><td>题目 JSON 落盘</td><td class="ok">通过</td></tr>
  <tr><td>题目 id 冲突</td><td>重复 id 添加</td><td>409 id 已存在</td><td class="ok">通过</td></tr>
  <tr><td>AC 提交</td><td>两数之和正确代码</td><td>测试点 AC，按比例得分</td><td class="ok">通过</td></tr>
  <tr><td>WA 提交</td><td>输出错误结果</td><td>测试点 WA，score=0</td><td class="ok">通过</td></tr>
  <tr><td>TLE 提交</td><td>死循环</td><td>所有测试点 TLE</td><td class="ok">通过</td></tr>
  <tr><td>RE 提交</td><td><code>print(1/0)</code></td><td>所有测试点 RE</td><td class="ok">通过</td></tr>
  <tr><td>CE 提交</td><td>C++ 缺分号</td><td>返回编译错误信息，状态 CE</td><td class="ok">通过</td></tr>
  <tr><td>权限：未登录</td><td>GET /api/problems/</td><td>401 not logged in</td><td class="ok">通过</td></tr>
  <tr><td>权限：非管理员</td><td>普通用户删除题目</td><td>403 permission denied</td><td class="ok">通过</td></tr>
  <tr><td>权限：banned</td><td>被封禁用户登录</td><td>403 banned</td><td class="ok">通过</td></tr>
  <tr><td>频率限制</td><td>1 分钟内提交 ≥ 3 次</td><td>429 too many requests</td><td class="ok">通过</td></tr>
  <tr><td>重新评测</td><td>admin PUT rejudge</td><td>状态回 pending，旧日志覆盖</td><td class="ok">通过</td></tr>
  <tr><td>可见性配置</td><td>PUT public_cases=true</td><td>普通用户也能查日志</td><td class="ok">通过</td></tr>
  <tr><td>审计日志</td><td>GET /api/logs/access/</td><td>仅管理员，记录 view_log 访问</td><td class="ok">通过</td></tr>
  <tr><td>AI 命题</td><td>真实 DeepSeek 出题</td><td>完整题目 JSON + 5 测试点，费用 ¥0.223</td><td class="ok">通过</td></tr>
  <tr><td>AI 中断</td><td>运行中 cancel</td><td>立即 cancelled，interrupted=true</td><td class="ok">通过</td></tr>
  <tr><td>AI 中断边界</td><td>已完成任务 cancel</td><td>409 拒绝（边界正确）</td><td class="ok">通过</td></tr>
</table>

<h3>3.2 AI 智能命题全链路（真实 DeepSeek）</h3>
<p>使用真实 DeepSeek 大模型（非 mock）验证完整命题流程，两次成功出题：</p>

<table>
  <tr><th>命题需求</th><th>生成题目</th><th>难度/标签</th><th>测试点</th><th>费用</th></tr>
  <tr><td>二分查找（超市货架价格标签情境）</td><td>「货架寻价」<code>binary_search_price_tag</code></td><td>中等偏基础 / 二分查找·数组·lower_bound</td><td>5 个（覆盖最小规模/目标在首尾中间/不存在/大数值）</td><td>¥0.223</td></tr>
  <tr><td>动态规划·最长公共子序列</td><td>「最大连续收益」<code>max_contiguous_profit</code></td><td>中等偏基础 / 动态规划·最大子段和·线性DP</td><td>9 个</td><td>¥0.278</td></tr>
</table>

<p>全链路验证要点：</p>
<ol>
  <li>配置 provider_url / model / api_key（密钥仅返回 <code>api_key_configured: true</code> 标志，不明文泄露）；</li>
  <li>提交命题需求，任务状态机 <code>pending → running → completed</code>，进度实时轮询更新；</li>
  <li>生成的题目严格贴合输入知识点（二分查找 / 动态规划）与难度要求，样例含边界情况；</li>
  <li>生成结果以「添加/编辑题目」同款表单展示，可直接或修改后导入题库；</li>
  <li>导入题库后提交正确代码 → 评测 AC，证明 <strong>AI 命题与题库/评测链路完整衔接</strong>。</li>
</ol>

<!-- ============================== 4. AI 使用说明 ============================== -->
<h2>4. AI 使用说明</h2>

<h3>4.1 工具链</h3>
<ul>
  <li><strong>主力工具</strong>：WorkBuddy 智能体（基于大模型的代码助手），承担分模块编码、调试排错、代码 review 等实现工作。</li>
  <li><strong>辅助工具</strong>：Web 搜索（查证 Pydantic、shlex、psutil、httpx、Streamlit 用法）。</li>
  <li><strong>环境</strong>：纯 Windows 11 + Python 3.13.12，命令行 Git Bash；后端 FastAPI + 前端 Streamlit 分离启动。</li>
</ul>

<h3>4.2 工作流</h3>
<ol>
  <li><strong>需求通读</strong>：本人先完整阅读全部 11 份需求文档，梳理评分点与功能边界。</li>
  <li><strong>需求转化为自然语言指令</strong>：本人将每个功能点描述为明确的目标、约束与验收标准，交给 AI 执行。</li>
  <li><strong>AI 分模块生成</strong>：AI 按 Step 顺序逐个实现，每个模块先写路由再写共享层，边写边由本人用 curl 实测。</li>
  <li><strong>本人端到端验收</strong>：每写完一块立即实测接口，发现 bug 就向 AI 复现现象并让其定位修复；AI 命题用真实 DeepSeek 跑通全链路。</li>
  <li><strong>持续提交</strong>：每完成一个功能点就按 Conventional Commits 规范拆分提交并 push，而非一次性提交。</li>
</ol>

<h3>4.3 Vibe Coding 代码比例</h3>
<p>本项目的代码 <strong>绝大部分由 AI 直接生成</strong>（约 <span class="num">90%</span> 以上），本人通过自然语言描述需求驱动 AI 产出，再逐段验收、反馈问题、迭代修正。实际分工如下：</p>
<table>
  <tr><th>环节</th><th>承担方</th><th>说明</th></tr>
  <tr><td>需求拆解与描述</td><td>本人</td><td>通读 11 份要求文档，将评分点转化为可执行的自然语言需求，逐条向 AI 描述目标、边界与验收标准。</td></tr>
  <tr><td>代码编写</td><td>AI 为主</td><td>路由、Pydantic 模型、JSON 存储、异步评测引擎、AI 命题任务、Streamlit 前端等几乎全部由 AI 生成。</td></tr>
  <tr><td>验收与测试</td><td>本人</td><td>逐项对照要求文档核对功能，用 curl / 真实 DeepSeek 出题 / 浏览器实测，发现并定位问题。</td></tr>
  <tr><td>缺陷反馈与迭代</td><td>本人 + AI</td><td>本人描述 bug 现象（如"刷新回登录页""改单价丢密钥""输出被截断""中断未真正停止"），AI 定位根因并修复。</td></tr>
</table>
<p>也就是说，这是一次典型的 <strong>Vibe Coding</strong> 实践：本人扮演"产品经理 + 测试"角色，负责定义要做什么、判断做得对不对；AI 扮演"工程师"，负责具体实现。本人不逐行手写代码，但<strong>全程主导方向、逐项验收、对最终交付质量负责</strong>。</p>

<h3>4.4 收获</h3>
<ul>
  <li>Vibe Coding 的核心能力不在"写代码"，而在 <strong>把需求讲清楚、把问题定位准</strong>：本次多个 bug（刷新会话竞态、密钥被空值覆盖、JSON 输出截断、中断未真正终止）都是靠本人准确复现现象、AI 才得以快速修复。</li>
  <li>AI 最容易"看似对但实际跑不起来"的代码是 <strong>跨平台兼容</strong>、<strong>边界条件</strong> 与 <strong>异步时序竞态</strong>；这些坑往往要在真实运行（而非静态阅读代码）中才会暴露。</li>
  <li>把 <strong>端到端测试</strong> 嵌入开发流程，能在早期暴露问题，比单纯相信 AI 的"已完成"表述有效得多——每次都必须实测验收，不能只看代码。</li>
  <li>诚实评估 AI 参与度很重要：AI 承担了绝大部分实现劳动，但<strong>需求的理解、方向的判断、质量的把关</strong>仍需本人完成，两者缺一不可。</li>
</ul>

<!-- ============================== 5. 总结与建议 ============================== -->
<h2>5. 总结与建议</h2>

<h3>5.1 时间投入</h3>
<table>
  <tr><th>阶段</th><th>耗时</th><th>内容</th></tr>
  <tr><td>需求通读与方案设计</td><td>约 1.5 小时</td><td>通读 11 份需求文档，确认范围、技术选型、模块划分</td></tr>
  <tr><td>基础模块实现（Step 1–6）</td><td>约 4 小时</td><td>脚手架 + 6 个模块的代码与端到端测试</td></tr>
  <tr><td>AI 智能命题模块</td><td>约 3 小时</td><td>模型调用、任务状态机、分阶段生成、Token 计费、真实出题与中断验证</td></tr>
  <tr><td>前端交互与体验打磨</td><td>约 2 小时</td><td>三组页面美化、会话持久化、分页、AI 配置弹窗与历史列表</td></tr>
  <tr><td>持续提交与推送</td><td>约 1 小时</td><td>63 次 Conventional Commits + push</td></tr>
  <tr><td>报告与配图</td><td>约 1 小时</td><td>本文档 + 3 张配图</td></tr>
  <tr><th>总计</th><th>约 12.5 小时</th><th>—</th></tr>
</table>

<h3>5.2 反思与收获</h3>
<ul>
  <li><strong>异步 + 子进程</strong> 是本系统最有挑战的部分，掌握了 <code>asyncio.create_subprocess_exec</code>、<code>wait_for</code>、<code>psutil</code> 后台协程的协同使用。</li>
  <li><strong>异步任务的生命周期管理</strong> 从评测队列延伸到 AI 命题：真正"中断"一个正在 <code>await</code> 网络请求的协程，需要维护协程句柄并 <code>cancel()</code>，仅改状态字段是不够的。</li>
  <li><strong>统一响应结构</strong> + <strong>异常处理顺序</strong>（401→403→400→429→409→404→500）让所有接口行为可预期，前端不需要为每个接口写特殊错误处理。</li>
  <li><strong>JSON 文件存储</strong> 在小规模场景下简单可靠，但并发写需要原子 rename；如果未来扩展到多实例部署，应改用 SQLite / Redis。</li>
  <li><strong>AI 命题</strong> 是最有"未来感"的部分，题目生成后能直接进题库被评测，整个链路验证了"AI 与基础功能不割裂"。</li>
</ul>

<h3>5.3 改进建议</h3>
<ul>
  <li>评测引擎可加入 <strong>编译缓存</strong>（相同源码不重复编译）；多测试点并发（<code>asyncio.gather</code>）可缩短总耗时。</li>
  <li>AI 命题可加入 <strong>题面润色</strong>、<strong>测试点自动验证</strong>（用 AI 自己写标程并跑一遍），提高生成质量与正确性。</li>
  <li>用户管理可加入 <strong>邮箱验证</strong>、<strong>密码强度策略</strong>、<strong>登录失败锁定</strong> 等更严密的安全机制。</li>
  <li>存储层可抽象为接口，<strong>未来可平滑替换为数据库</strong>（SQLite/PostgreSQL）而不影响上层逻辑。</li>
  <li>前端可加入 <strong>实时评测日志流</strong>（SSE 或 WebSocket）替代轮询，进一步降低响应延迟。</li>
</ul>

<hr style="margin-top: 30pt; border: none; border-top: 1pt solid #ccc;">
<p style="text-align: center; color: #888; font-size: 9pt;">
  — 报告结束 —<br>
  完整代码与提交历史见 GitHub 仓库
</p>

</body>
</html>
"""


def write_html():
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(HTML)
    print(f"HTML 报告已生成: {HTML_PATH}")


def html_to_pdf():
    browser = find_browser()
    # Edge headless 需要 file:// URL
    file_url = "file:///" + HTML_PATH.replace("\\", "/")
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        f"--print-to-pdf={PDF_PATH}",
        file_url,
    ]
    print(f"调用: {' '.join(cmd[:4])} ...")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print("STDERR:", r.stderr[:500])
    if not os.path.exists(PDF_PATH):
        raise RuntimeError("PDF 生成失败")
    size = os.path.getsize(PDF_PATH)
    print(f"PDF 已生成: {PDF_PATH} ({size} bytes)")


if __name__ == "__main__":
    write_html()
    html_to_pdf()
    print("全部完成")
