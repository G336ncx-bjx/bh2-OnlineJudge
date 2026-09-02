"""OJ 系统前端 —— Streamlit 实现。

通过 REST API 与 FastAPI 后端交互，不直接读写后端数据。
覆盖三组页面：用户、题目、评测提交。
"""
import json
import time

import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_javascript import st_javascript

# 后端地址
BACKEND = "http://127.0.0.1:8000"

st.set_page_config(page_title="OJ 在线评测系统", page_icon="⚖️", layout="wide")

# 用户角色中文映射（内部仍用英文枚举值，仅展示层翻译）
ROLE_ZH = {
    "user": "普通用户",
    "admin": "管理员",
    "banned": "已封禁",
}
# 审计日志操作中文映射
LOG_ACTION_ZH = {
    "view_log": "查看评测日志",
}


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
            return None, None, "不支持的请求方法"
        # 保存 session cookie；logout 会返回 session=null 清空 cookie，此时应清除登录态
        if "session" in resp.cookies:
            val = resp.cookies["session"]
            if val in ("", "null", None):
                st.session_state.pop("session_cookie", None)
            else:
                st.session_state["session_cookie"] = val
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


def _restore_session():
    """从浏览器 localStorage 读回会话（session cookie + 用户信息），刷新后恢复登录态。

    Streamlit 的 session_state 是服务端内存态，刷新页面会丢失，导致登录态丢失。
    为满足 step6「安全保存身份信息 / 正确保存和传递登录会话」的要求，把会话持久化
    到浏览器 localStorage，脚本每次运行（含刷新）时读回。
    仅在 session_state 里还没有 cookie 时才读回，避免覆盖已有会话。
    """
    if "session_cookie" in st.session_state:
        return
    # 已退出登录（logout 已清 cookie 并设置本标记）→ 持续跳过读回，避免把旧会话恢复回来。
    # 该标记随 rerun 保留，直到用户重新登录成功才清除；页面刷新后 session_state 清空、
    # 标记消失，才会重新从 localStorage 读回（此时后端 session 已失效，读回的 cookie 也无效）。
    if st.session_state.get("_logged_out"):
        return
    # 通过 streamlit_javascript.st_javascript 从浏览器 localStorage 同步读回会话。
    # 注意：st_javascript 采用「两段式回传」——首次返回默认值 0（表示"尚未拿到"），
    # 触发一次 rerun，第二次才返回真实值。因此 key 必须固定（保持组件实例稳定）。
    stored = st_javascript(
        "window.localStorage.getItem('oj_session')", key="oj_session_get"
    )
    if not isinstance(stored, str) or not stored:
        return
    try:
        payload = json.loads(stored)
    except (json.JSONDecodeError, TypeError):
        return
    # cookie 与 user_info 必须同时有效才恢复，避免「半截会话」（有 user_info 无 cookie）
    if payload.get("cookie") and payload.get("user_info"):
        st.session_state["session_cookie"] = payload["cookie"]
        st.session_state["user_info"] = payload["user_info"]
        # 恢复当前菜单页，让刷新后停留在刷新前的页面而非回落到默认「题目」
        if payload.get("menu"):
            st.session_state["menu"] = payload["menu"]


def _sync_localstorage():
    """在每次 run 的稳定阶段（main 末尾）同步浏览器 localStorage。

    三种状态分别处理，避免时序竞态把尚未恢复的会话误删：
    - 已登录（有 cookie 且 user_info）→ 写入当前会话（含当前菜单页）；
    - 明确登出（_logged_out 标记）→ 删除 localStorage 残留会话；
    - 其它（如「恢复探测中」的过渡 run，此时 st_javascript 尚未回传真实值）→ 不动。

    「不动」这一步是关键：F5 刷新后第一次 run 里 st_javascript 返回默认值 0，
    session_state 里还没有 cookie，若此时贸然 removeItem，会把浏览器里还未来得及
    读回的 oj_session 清掉，导致登录态永远无法恢复。

    用 components.html 注入 <script> 在 iframe 加载时确定执行 setItem / removeItem，
    放在 main 末尾执行，不受后续 st.rerun() 干扰（本次 run 正常渲染到浏览器，脚本必执行）。
    """
    cookie = st.session_state.get("session_cookie", "")
    user_info = st.session_state.get("user_info")
    if cookie and user_info:
        payload = {
            "cookie": cookie,
            "user_info": user_info,
            # 同时持久化当前菜单页，刷新后恢复到原页面
            "menu": st.session_state.get("menu", "题目"),
        }
        components.html(
            "<script>(function(){try{window.localStorage.setItem('oj_session',"
            + json.dumps(json.dumps(payload, ensure_ascii=False))
            + ");}catch(e){}})();</script>",
            height=0,
            scrolling=False,
        )
    elif st.session_state.get("_logged_out"):
        # 明确登出：清掉浏览器里残留的旧会话
        components.html(
            "<script>(function(){try{window.localStorage.removeItem('oj_session');}catch(e){}})();</script>",
            height=0,
            scrolling=False,
        )
    # 其它情况（过渡态）什么都不做，避免误删


def logout():
    api_call("POST", "/api/auth/logout")
    st.session_state.pop("session_cookie", None)
    st.session_state.pop("user_info", None)
    # 标记「已登出」，阻止 _restore_session 在本次 rerun 时把旧会话读回
    st.session_state["_logged_out"] = True
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
            padding-left: 2rem;
            padding-right: 2rem;
            max-width: 1100px;
        }
        /* 顶栏容器：突破 block-container 宽度限制，铺满视口 */
        .oj-topbar {
            margin-left: calc(-50vw + 50% + 2rem);
            margin-right: calc(-50vw + 50% + 2rem);
            padding-left: 1rem;
            padding-right: 1rem;
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
            font-size: 20px;
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
        /* 左标题区容器：防溢出重叠 */
        .oj-brand {
            overflow: hidden;
            white-space: nowrap;
        }
        /* 导航按钮：胶囊样式，保证完整可点击、不换行、不截断 */
        .oj-navbtn button {
            width: 100%;
            min-width: 0;
            border-radius: 10px;
            border: 1px solid #d6dfe4;
            padding: 7px 6px;
            font-size: 13px;
            white-space: nowrap !important;
            overflow: visible !important;
            text-overflow: clip !important;
            transition: all .15s ease;
            min-height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
        }
        .oj-navbtn button:hover {
            border-color: #1a2a6c;
            color: #1a2a6c;
        }
        /* 顶栏右侧：用户信息与退出按钮同一行右对齐 */
        .oj-user-row {
            text-align: right;
            line-height: 1.4;
            white-space: nowrap;
        }
        .oj-logout-wrap {
            display: flex;
            justify-content: flex-end;
        }
        .oj-logout-wrap button {
            width: auto;
            min-width: 0;
            border-radius: 8px;
            border: 1px solid #d6dfe4;
            padding: 6px 12px;
            font-size: 12px;
            white-space: nowrap !important;
            overflow: visible !important;
            text-overflow: clip !important;
            min-height: 34px;
            line-height: 1;
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
        /* 删除按钮：红色调（st-key 类加在最外层 stElementContainer 上） */
        div[data-testid="stElementContainer"][class*="st-key-prob_del"] button {
            border-color: #e0b4b4 !important;
            color: #c0392b !important;
            background: #fdf3f3 !important;
        }
        div[data-testid="stElementContainer"][class*="st-key-prob_del"] button:hover {
            border-color: #c0392b !important;
            background: #fbe4e4 !important;
        }
        /* 新增按钮：绿色调（key 固定 problem_create） */
        div[data-testid="stElementContainer"][class*="st-key-problem_create"] button {
            background: #1e8e3e !important;
            border-color: #1e8e3e !important;
            color: #ffffff !important;
        }
        div[data-testid="stElementContainer"][class*="st-key-problem_create"] button:hover {
            background: #187a34 !important;
            border-color: #187a34 !important;
        }
        /* 提交评测相关绿色按钮（题目详情「提交评测」、提交页「查看提交记录」） */
        div[data-testid="stElementContainer"][class*="st-key-submit_from_detail"] button,
        div[data-testid="stElementContainer"][class*="st-key-goto_submission_list"] button {
            background: #1e8e3e !important;
            border-color: #1e8e3e !important;
            color: #ffffff !important;
        }
        div[data-testid="stElementContainer"][class*="st-key-submit_from_detail"] button:hover,
        div[data-testid="stElementContainer"][class*="st-key-goto_submission_list"] button:hover {
            background: #187a34 !important;
            border-color: #187a34 !important;
        }
        /* 表格文字居中：dataframe / table / 表格单元格 */
        [data-testid="stDataFrame"] table td,
        [data-testid="stTable"] table td,
        [data-testid="stTable"] table th,
        [data-testid="stDataFrame"] table th {
            text-align: center !important;
        }
        /* 提交详情：头部标题 */
        .oj-detail-head {
            font-size: 20px;
            font-weight: 800;
            color: #1a2a6c;
            margin: 4px 0 14px 0;
        }
        .oj-detail-title {
            display: inline-block;
            margin-left: 10px;
            padding: 3px 12px;
            font-size: 14px;
            font-weight: 700;
            color: #1a2a6c;
            background: #eef1ff;
            border-radius: 20px;
            vertical-align: middle;
        }
        /* 提交详情：元信息卡片 */
        .oj-meta-card {
            display: flex;
            flex-wrap: wrap;
            gap: 1px;
            background: #e6ebef;
            border: 1px solid #e6ebef;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 2px 10px rgba(26, 42, 108, .05);
        }
        .oj-meta-item {
            flex: 1 1 0;
            min-width: 140px;
            background: #ffffff;
            padding: 12px 18px;
            text-align: center;
        }
        .oj-meta-k {
            font-size: 12px;
            color: #8a9aa5;
            margin-bottom: 5px;
            letter-spacing: .5px;
        }
        .oj-meta-v {
            font-size: 16px;
            font-weight: 700;
            color: #2b3445;
            word-break: break-all;
        }
        /* 提交详情：统计卡片 */
        .oj-stat-row {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin: 14px 0 4px 0;
        }
        .oj-stat-card {
            flex: 1 1 0;
            min-width: 140px;
            padding: 14px 18px;
            background: #ffffff;
            border: 1px solid #e6ebef;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(26, 42, 108, .05);
        }
        .oj-stat-k {
            font-size: 12px;
            color: #8a9aa5;
            margin-bottom: 6px;
            letter-spacing: .5px;
        }
        .oj-stat-v {
            font-size: 22px;
            font-weight: 800;
            color: #1a2a6c;
        }
        .oj-stat-score {
            color: #1e8e3e;
        }
        .oj-stat-ok .oj-stat-v { color: #1e8e3e; }
        .oj-stat-err .oj-stat-v { color: #c0392b; }
        .oj-stat-wait .oj-stat-v { color: #b26a00; }
        /* 测试点明细：自绘表格 */
        .oj-case-table {
            margin: 8px 0 16px 0;
            border: 1px solid #e6ebef;
            border-radius: 12px;
            overflow: hidden;
            background: #ffffff;
            box-shadow: 0 2px 10px rgba(26, 42, 108, .06);
        }
        .oj-case-title {
            padding: 10px 16px;
            font-size: 14px;
            font-weight: 700;
            color: #1a2a6c;
            background: linear-gradient(90deg, #eef1ff, #f7f9ff);
            border-bottom: 1px solid #e6ebef;
        }
        .oj-case-table table {
            width: 100%;
            border-collapse: collapse;
            margin: 0;
        }
        .oj-case-table th {
            background: #f5f8fc;
            color: #55627a;
            font-size: 12px;
            font-weight: 700;
            text-align: center;
            padding: 9px 12px;
            border-bottom: 1px solid #e6ebef;
            letter-spacing: .5px;
        }
        .oj-case-table td {
            text-align: center;
            padding: 9px 12px;
            font-size: 13px;
            color: #2b3445;
            border-bottom: 1px solid #eef2f6;
            font-variant-numeric: tabular-nums;
        }
        .oj-case-table tbody tr:last-child td {
            border-bottom: none;
        }
        .oj-case-table tbody tr:nth-child(even) {
            background: #fafbfd;
        }
        .oj-case-table tbody tr:hover {
            background: #f2f6ff;
        }
        /* 状态徽章 */
        .oj-tag {
            display: inline-block;
            min-width: 42px;
            padding: 2px 9px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 800;
            text-align: center;
            letter-spacing: .5px;
            margin-right: 6px;
        }
        .oj-tag-sub {
            font-size: 12px;
            color: #8a9aa5;
        }
        .oj-tag-ac  { background: #e7f6ec; color: #1e8e3e; }
        .oj-tag-wa  { background: #fdeaea; color: #c0392b; }
        .oj-tag-tle { background: #fdf3e2; color: #b26a00; }
        .oj-tag-mle { background: #fdeef3; color: #b5377a; }
        .oj-tag-re  { background: #fdeaea; color: #c0392b; }
        .oj-tag-ce  { background: #eef1f4; color: #55627a; }
        .oj-tag-unk { background: #eef1f4; color: #8a9aa5; }
        /* 提交列表：状态徽章 */
        .oj-tag-ok   { background: #e7f6ec; color: #1e8e3e; }
        .oj-tag-err  { background: #fdeaea; color: #c0392b; }
        .oj-tag-wait { background: #fdf3e2; color: #b26a00; }
        /* 提交列表：表头渐变条 */
        .oj-sub-head {
            display: flex;
            padding: 9px 12px;
            background: linear-gradient(90deg, #eef1ff, #f5f8fc);
            border: 1px solid #e6ebef;
            border-bottom: none;
            border-radius: 12px 12px 0 0;
            color: #55627a;
            font-size: 12px;
            font-weight: 700;
            text-align: center;
            letter-spacing: .5px;
        }
        .oj-sub-head span { text-align: center; }
        /* 提交列表：单元格文字 */
        .oj-cell-mono {
            font-family: "SF Mono", Menlo, Consolas, monospace;
            font-size: 12px;
            color: #55627a;
        }
        .oj-cell-lang {
            font-weight: 600;
            color: #1a2a6c;
        }
        .oj-score-num { font-variant-numeric: tabular-nums; }
        .oj-score-full { color: #1e8e3e; font-weight: 800; }
        .oj-score-part { color: #b26a00; font-weight: 700; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_topbar():
    """顶栏：左 logo+标题，中导航按钮（原生 st.button），右用户信息。

    导航用 Streamlit 原生 st.button，点击走 rerun 机制，保证当前页内切换、
    点击区域完整可靠（不再用 iframe <a> 跳转，避免被组件沙箱拦截导致点不动）。
    顶栏用 .oj-topbar 负 margin 铺满视口宽度，正文仍保持居中窄宽。
    """
    inject_css()

    current = st.session_state.get("menu", "题目")

    with st.container():
        st.markdown('<div class="oj-topbar"></div>', unsafe_allow_html=True)

        # 三区布局：左标题 / 中导航 / 右用户（垂直居中对齐）
        col_brand, col_nav, col_user = st.columns(
            [1.6, 4.6, 1.6], gap="small", vertical_alignment="center"
        )

        # 左：logo + 标题
        with col_brand:
            st.markdown(
                '<div class="oj-brand" style="display:flex;align-items:center;gap:10px;">'
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
            # 是否处于题目子视图（详情/新增/编辑）——此时「题目」按钮不应高亮
            in_problem_subview = bool(
                st.session_state.get("view_problem_id")
                or st.session_state.get("problem_view")
                or st.session_state.get("problem_edit_id")
            )
            for i, (name, icon) in enumerate(MENU_ITEMS):
                with nav_cols[i]:
                    if name == "题目":
                        active = name == current and not in_problem_subview
                    else:
                        active = name == current
                    btn_type = "primary" if active else "secondary"
                    st.markdown('<div class="oj-navbtn"></div>', unsafe_allow_html=True)
                    if st.button(
                        f"{icon} {name}",
                        key=f"navbtn_{name}",
                        type=btn_type,
                        use_container_width=True,
                    ):
                        st.session_state["menu"] = name
                        # 点顶栏「题目」总是回到题目列表页，清除子视图状态
                        if name == "题目":
                            st.session_state.pop("view_problem_id", None)
                            st.session_state.pop("problem_view", None)
                            st.session_state.pop("problem_edit_id", None)
                        st.rerun()

        # 右：用户信息（含退出登录按钮，登录后显示）
        with col_user:
            if is_logged_in() and current_user():
                u = current_user()
                role_map = {"admin": "管理员", "user": "用户", "banned": "已封禁"}
                role_text = role_map.get(u["role"], u["role"])
                # 用户名+角色 与 退出按钮 同行，垂直居中，整体右对齐
                ucol_info, ucol_btn = st.columns(
                    [1.2, 1.1], gap="small", vertical_alignment="center"
                )
                with ucol_info:
                    st.markdown(
                        f'<div class="oj-user-row">'
                        f'<span class="oj-user-name">{u["username"]}</span>'
                        f'<span class="oj-user-role">{role_text}</span></div>',
                        unsafe_allow_html=True,
                    )
                with ucol_btn:
                    st.markdown('<div class="oj-logout-wrap"></div>', unsafe_allow_html=True)
                    if st.button("退出登录", key="topbar_logout", use_container_width=True):
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
                    st.session_state.pop("_logged_out", None)
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
def _problem_payload(pid, title, description, input_desc, output_desc,
                     constraints, samples_str, testcases_str, hint,
                     time_limit, memory_limit):
    """把表单字段组装为题目 payload，JSON 解析失败返回 None。"""
    try:
        samples_list = json.loads(samples_str) if samples_str.strip() else []
        testcases_list = json.loads(testcases_str) if testcases_str.strip() else []
    except json.JSONDecodeError:
        return None
    return {
        "id": pid, "title": title, "description": description,
        "input_description": input_desc, "output_description": output_desc,
        "samples": samples_list, "constraints": constraints,
        "testcases": testcases_list, "hint": hint,
        "time_limit": time_limit, "memory_limit": memory_limit,
    }


def _problem_form(prefill: dict | None = None, pid_editable: bool = True):
    """题目表单（新增/编辑共用）。返回提交按钮是否被点击。"""
    p = prefill or {}
    pid = st.text_input(
        "题目标识 (必填)",
        value=p.get("id", ""),
        disabled=not pid_editable,
        help="题目的唯一标识，用于内部检索，建议使用英文/数字（如 P1001），不会对普通用户展示",
    )
    title = st.text_input("标题 (必填)", value=p.get("title", ""))
    description = st.text_area("题目描述 (必填)", value=p.get("description", ""))
    input_desc = st.text_area("输入格式说明 (必填)", value=p.get("input_description", ""))
    output_desc = st.text_area("输出格式说明 (必填)", value=p.get("output_description", ""))
    constraints = st.text_input("数据限制 (必填)", value=p.get("constraints", ""))
    samples_str = st.text_area(
        "样例 (JSON数组，元素含input/output)",
        value=json.dumps(p.get("samples", []), ensure_ascii=False, indent=2)
        if p.get("samples") else "",
    )
    testcases_str = st.text_area(
        "测试点 (JSON数组，元素含input/output)",
        value=json.dumps(p.get("testcases", []), ensure_ascii=False, indent=2)
        if p.get("testcases") else "",
    )
    hint = st.text_input("提示 (可选)", value=p.get("hint", ""))
    c1, c2 = st.columns(2)
    with c1:
        time_limit = st.number_input("时间限制(s)", value=float(p.get("time_limit", 3.0)), step=0.5)
    with c2:
        memory_limit = st.number_input("内存限制(MB)", value=int(p.get("memory_limit", 128)), step=16)

    submitted = st.form_submit_button("提交", type="primary", use_container_width=True)
    return submitted, _problem_payload(
        pid, title, description, input_desc, output_desc, constraints,
        samples_str, testcases_str, hint, time_limit, memory_limit,
    )


def _paginated_list(key, items, row_renderer, page_size=10):
    """通用分页：对 items 切片后调用 row_renderer 逐行渲染，并在底部渲染分页控件。

    key 用于在 session_state 中持久化「当前页码」，切页后 st.rerun() 生效。
    """
    page_key = f"page_{key}"
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)

    # 页码越界时（如删除最后一页的最后一条）自动回退到最后一页
    cur = st.session_state.get(page_key, 0)
    if cur >= total_pages:
        cur = total_pages - 1
        st.session_state[page_key] = cur

    start = cur * page_size
    page_items = items[start:start + page_size]
    for it in page_items:
        row_renderer(it)

    if total_pages <= 1:
        return

    # 分页控件：上一页 / 页码信息+跳转 / 下一页
    st.markdown("---")
    p_prev, p_mid, p_next = st.columns([1, 2, 1], vertical_alignment="center")
    with p_prev:
        if st.button("← 上一页", key=f"{page_key}_prev",
                     disabled=(cur == 0), use_container_width=True):
            st.session_state[page_key] = cur - 1
            st.rerun()
    with p_next:
        if st.button("下一页 →", key=f"{page_key}_next",
                     disabled=(cur >= total_pages - 1), use_container_width=True):
            st.session_state[page_key] = cur + 1
            st.rerun()
    with p_mid:
        # 页码信息 + 输入页码跳转（数字输入框 + 跳转按钮，同排）
        j_info, j_input, j_btn = st.columns([1.6, 1, 0.7], gap="small",
                                            vertical_alignment="center")
        with j_info:
            st.markdown(
                f"第 {cur + 1} / {total_pages} 页 · 共 {total} 条",
                text_alignment="right",
            )
        with j_input:
            # 用 text_input 而非 number_input，避免浏览器原生的英文越界提示气泡，
            # 校验与中文提示全部自己掌控。
            jump_raw = st.text_input(
                "跳转页码", value=str(cur + 1), key=f"{page_key}_jump",
                label_visibility="collapsed",
            )
        with j_btn:
            if st.button("跳转", key=f"{page_key}_go", use_container_width=True):
                raw = (jump_raw or "").strip()
                if not raw.isdigit():
                    st.toast("请输入有效的页码数字")
                else:
                    target = int(raw) - 1
                    if target < 0:
                        st.toast(f"页码不能小于 1")
                    elif target >= total_pages:
                        st.toast(f"页码不能超过 {total_pages} 页")
                    else:
                        st.session_state[page_key] = target
                        st.rerun()


def render_problem_list():
    # 标题行：左「题目列表」+ 右「新增题目」绿色按钮
    head_l, head_r = st.columns([3, 1], vertical_alignment="center")
    with head_l:
        st.subheader("题目列表")
    with head_r:
        if st.button("➕ 新增题目", key="problem_create", use_container_width=True):
            st.session_state["problem_edit_id"] = None
            st.session_state["problem_view"] = "create"
            st.rerun()

    code, data, msg = api_call("GET", "/api/problems/")
    if code != 200:
        st.error(msg)
        return
    if not data:
        st.info("暂无题目")
        return

    _paginated_list("problems", data, _render_problem_row)


def _render_problem_row(p):
    pid = p["id"]
    title = p["title"]
    info_col, act_col = st.columns([4, 1.6], vertical_alignment="center")
    with info_col:
        # 标题作为可点击按钮，点击进入详情（不展示内部 id）
        if st.button(
            title,
            key=f"prob_view_{pid}",
            use_container_width=True,
        ):
            st.session_state["view_problem_id"] = pid
            st.rerun()
    with act_col:
        b1, b2 = st.columns(2, gap="small")
        with b1:
            if st.button("编辑", key=f"prob_edit_{pid}", use_container_width=True):
                st.session_state["problem_edit_id"] = pid
                st.session_state["problem_view"] = "edit"
                st.rerun()
        with b2:
            if st.button("删除", key=f"prob_del_{pid}", use_container_width=True):
                code2, _, msg2 = api_call("DELETE", f"/api/problems/{pid}")
                if code2 == 200:
                    st.success(f"题目「{title}」已删除")
                    st.rerun()
                else:
                    st.error(f"删除失败: {msg2}")


def _render_back_to_list():
    """新增/编辑页顶部的「返回列表」按钮，清除视图状态回到列表。"""
    if st.button("← 返回列表", key="problem_back_to_list"):
        st.session_state.pop("problem_view", None)
        st.session_state.pop("problem_edit_id", None)
        st.rerun()


def render_problem_create():
    st.subheader("新增题目")
    _render_back_to_list()
    with st.form("create_problem_form"):
        submitted, payload = _problem_form()
    if submitted:
        if payload is None:
            st.error("样例/测试点必须是合法 JSON")
        else:
            code, data, msg = api_call("POST", "/api/problems/", payload)
            if code == 200:
                st.success(f"题目 {data['id']} 添加成功")
                st.session_state.pop("problem_view", None)
                st.session_state.pop("problem_edit_id", None)
                st.rerun()
            else:
                st.error(f"添加失败: {msg}")


def render_problem_edit():
    pid = st.session_state.get("problem_edit_id")
    if not pid:
        st.info("未指定要编辑的题目")
        return
    code, data, msg = api_call("GET", f"/api/problems/{pid}")
    if code != 200:
        st.error(msg)
        return
    st.subheader(f"编辑题目: {pid}")
    _render_back_to_list()
    with st.form("edit_problem_form"):
        submitted, payload = _problem_form(prefill=data, pid_editable=False)
    if submitted:
        if payload is None:
            st.error("样例/测试点必须是合法 JSON")
        else:
            code2, data2, msg2 = api_call("PUT", f"/api/problems/{pid}", payload)
            if code2 == 200:
                st.success(f"题目 {pid} 已更新")
                st.session_state.pop("problem_view", None)
                st.session_state.pop("problem_edit_id", None)
                st.rerun()
            else:
                st.error(f"更新失败: {msg2}")


def render_problem_detail():
    pid = st.session_state.get("view_problem_id")
    if not pid:
        return
    code, data, msg = api_call("GET", f"/api/problems/{pid}")
    if code == 200:
        st.subheader(data["title"])
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

        # 操作行：提交评测（绿色）+ 返回列表
        act_l, act_r = st.columns([1, 1], gap="small")
        with act_l:
            if st.button("🚀 提交评测", key=f"submit_from_detail_{pid}", use_container_width=True):
                st.session_state["submit_preselect_pid"] = pid
                st.session_state["menu"] = "评测提交"
                st.session_state.pop("view_problem_id", None)
                # 清除评测相关的残留状态，确保进入「提交代码」页而非详情页
                st.session_state.pop("view_submission_id", None)
                st.session_state.pop("show_submission_list", None)
                st.rerun()
        with act_r:
            if st.button("返回列表", use_container_width=True):
                st.session_state.pop("view_problem_id", None)
                st.rerun()
    else:
        st.error(msg)
        if st.button("返回列表"):
            st.session_state.pop("view_problem_id", None)
            st.rerun()


# ---------------------------------------------------------------- 评测提交页面
def render_submission():
    # 标题行：左「提交代码」+ 右「查看提交记录」按钮（参考题目列表新增按钮设计）
    head_l, head_r = st.columns([3, 1], vertical_alignment="center")
    with head_l:
        st.subheader("提交代码")
    with head_r:
        if st.button("📋 查看提交记录", key="goto_submission_list", use_container_width=True):
            st.session_state.pop("submit_preselect_pid", None)
            st.session_state.pop("view_submission_id", None)
            st.session_state["show_submission_list"] = True
            st.rerun()

    code, probs, msg = api_call("GET", "/api/problems/")
    if code != 200:
        st.error(msg)
        return
    if not probs:
        st.info("暂无题目可提交")
        return

    # 题目下拉框显示「标题」，内部仍用 id 提交
    title_to_id = {p["title"]: p["id"] for p in probs}
    titles = list(title_to_id.keys())

    code, langs, msg = api_call("GET", "/api/languages/")
    lang_names = langs.get("name", []) if langs else []

    # 预选题目（从题目详情页「提交评测」跳转而来）
    preselect_pid = st.session_state.pop("submit_preselect_pid", None)
    preselect_title = None
    if preselect_pid:
        for p in probs:
            if p["id"] == preselect_pid:
                preselect_title = p["title"]
                break

    with st.form("submit_form"):
        # selectbox 显式指定 key，避免 widget 状态漂移导致「用户选 A 却提交成 B」。
        # 预选值只在首次进入时通过 index 设置，之后以用户手动选择为准。
        sel_key = "submit_title_sel"
        if preselect_title and preselect_title in titles:
            title = st.selectbox(
                "题目", titles, key=sel_key, index=titles.index(preselect_title)
            )
        else:
            title = st.selectbox("题目", titles, key=sel_key)
        lang = st.selectbox("语言", lang_names, key="submit_lang_sel")
        code_text = st.text_area("代码", height=300, key="submit_code_area")
        if st.form_submit_button("提交评测"):
            # 从 session_state 读取提交时刻的真实选择，而非闭包变量，避免 form 时序错位
            title = st.session_state.get(sel_key, title)
            lang = st.session_state.get("submit_lang_sel", lang)
            code_text = st.session_state.get("submit_code_area", code_text)
            pid = title_to_id[title]
            code, data, msg = api_call(
                "POST", "/api/submissions/",
                {"problem_id": pid, "language": lang, "code": code_text},
            )
            if code == 200:
                st.session_state["last_submission_id"] = data["submission_id"]
                st.session_state["view_submission_id"] = data["submission_id"]
                st.session_state.pop("show_submission_list", None)
                st.success(f"提交成功，提交编号 {data['submission_id']}，正在跳转查看评测结果...")
                st.rerun()
            else:
                st.error(f"提交失败: {msg}")


def render_submission_list():
    # 标题行：左「提交记录」+ 右「返回提交代码」按钮
    head_l, head_r = st.columns([3, 1], vertical_alignment="center")
    with head_l:
        st.subheader("提交记录")
    with head_r:
        if st.button("✏️ 返回提交代码", key="goto_submit_code", use_container_width=True):
            st.session_state.pop("show_submission_list", None)
            st.rerun()

    u = current_user()
    is_admin_user = bool(u and u.get("role") == "admin")

    code, probs, _ = api_call("GET", "/api/problems/")
    title_to_id = {p["title"]: p["id"] for p in probs} if probs else {}
    titles = list(title_to_id.keys())

    # 筛选条件：题目（显示标题）、状态；管理员额外有用户筛选
    n_filters = 3 if is_admin_user else 2
    cols = st.columns(n_filters)
    with cols[0]:
        pid_title = st.selectbox("按题目筛选", ["(全部)"] + titles)
    with cols[1]:
        status = st.selectbox(
            "按状态筛选",
            ["(全部)", "pending", "success", "error"],
        )
    if is_admin_user:
        code, users_data, _ = api_call("GET", "/api/users/")
        # 管理员可见用户列表
        user_names = []
        if users_data and users_data.get("users"):
            user_names = [x["username"] for x in users_data["users"]]
        with cols[2]:
            sel_user = st.selectbox("按用户筛选", ["(全部)"] + user_names)

    params = {}
    if pid_title != "(全部)":
        params["problem_id"] = title_to_id[pid_title]
    if status != "(全部)":
        params["status"] = status
    if is_admin_user and sel_user != "(全部)":
        # 管理员按用户名筛选，需拿到该用户的 user_id
        if users_data and users_data.get("users"):
            uid_map = {x["username"]: x["user_id"] for x in users_data["users"]}
            params["user_id"] = uid_map.get(sel_user)

    code, data, msg = api_call("GET", "/api/submissions/", params)
    if code != 200:
        st.error(msg)
        return
    subs = data.get("submissions", []) if data else []
    if not subs:
        st.info("暂无提交记录")
        return

    # 表格化展示：提交编号、提交者、题目、状态、得分、语言、时间
    # 采用卡片式行（st.container(border=True)）+ 原生按钮承载题目名点击，跳转最可靠。
    status_zh = {"pending": "评测中", "success": "完成", "error": "出错"}
    status_cls = {"pending": "oj-tag-wait", "success": "oj-tag-ok", "error": "oj-tag-err"}
    st.markdown("💡 点击**题目名称**即可查看该条提交的详情")

    # 表头（渐变条）
    st.markdown(
        '<div class="oj-sub-head"><span style="flex:1.0">提交编号</span>'
        '<span style="flex:1.2">提交者</span><span style="flex:2.0">题目</span>'
        '<span style="flex:1.0">状态</span><span style="flex:1.2">得分</span>'
        '<span style="flex:0.9">语言</span><span style="flex:1.7">提交时间</span></div>',
        unsafe_allow_html=True,
    )

    def _render_sub_row(s):
        score = s.get("score")
        score_str = f"{score} / {s.get('counts', 0) * 10}" if score is not None else "-"
        title = s.get("problem_title") or s.get("problem_id", "")
        stt = s.get("status", "")
        cls = status_cls.get(stt, "oj-tag-wait")
        # 得分配色
        score_cls = "oj-score-num"
        if score is not None:
            total = (s.get("counts", 0) or 0) * 10
            if total and score >= total:
                score_cls = "oj-score-full"
            elif score > 0:
                score_cls = "oj-score-part"

        with st.container(border=True):
            row = st.columns([1.0, 1.2, 2.0, 1.0, 1.2, 0.9, 1.7], gap="small",
                             vertical_alignment="center")
            row[0].markdown(
                f"<span class=\"oj-cell-mono\">{s['submission_id']}</span>",
                unsafe_allow_html=True, text_alignment="center",
            )
            row[1].markdown(
                f"{s.get('username', '-')}",
                text_alignment="center",
            )
            with row[2]:
                if st.button(title, key=f"sub_row_{s['submission_id']}", use_container_width=True):
                    st.session_state["view_submission_id"] = s["submission_id"]
                    st.rerun()
            row[3].markdown(
                f"<span class=\"oj-tag {cls}\">{status_zh.get(stt, stt)}</span>",
                unsafe_allow_html=True, text_alignment="center",
            )
            row[4].markdown(
                f"<span class=\"{score_cls}\">{score_str}</span>",
                unsafe_allow_html=True, text_alignment="center",
            )
            row[5].markdown(
                f"<span class=\"oj-cell-lang\">{s.get('language', '-')}</span>",
                unsafe_allow_html=True, text_alignment="center",
            )
            row[6].markdown(
                f"{s.get('submit_time', '-')}",
                text_alignment="center",
            )

    _paginated_list("submissions", subs, _render_sub_row)


def render_submission_detail():
    sid = st.session_state.get("view_submission_id")
    if not sid:
        return

    code, data, msg = api_call("GET", f"/api/submissions/{sid}")
    if code != 200:
        st.error(msg)
        if st.button("返回提交记录"):
            st.session_state.pop("view_submission_id", None)
            st.session_state["show_submission_list"] = True
            st.rerun()
        return

    # 友好标题：优先题目名，其次题目 id，避免直接暴露裸 submission_id 哈希
    title = data.get("problem_title") or data.get("problem_id") or sid
    st.markdown(
        f"<div class=\"oj-detail-head\">提交详情<span class=\"oj-detail-title\">{title}</span></div>",
        unsafe_allow_html=True,
    )

    # 元信息卡片：提交编号 / 提交者 / 语言 / 提交时间
    meta_items = [
        ("提交编号", sid),
        ("提交者", data.get("username", "-")),
        ("语言", data.get("language", "-")),
        ("提交时间", data.get("submit_time", "-")),
    ]
    meta_html = "".join(
        f"<div class=\"oj-meta-item\"><div class=\"oj-meta-k\">{k}</div>"
        f"<div class=\"oj-meta-v\">{v}</div></div>"
        for k, v in meta_items
    )
    st.markdown(f"<div class=\"oj-meta-card\">{meta_html}</div>", unsafe_allow_html=True)

    status = data.get("status")
    status_zh = {"pending": "评测中", "success": "评测完成", "error": "评测出错"}

    if status == "pending":
        # 轮询：间隔刷新直到评测结束
        st.info(f"⏳ {status_zh.get(status, status)}，正在评测，请稍候...")
        with st.spinner("评测进行中，自动刷新..."):
            time.sleep(1.5)
        st.rerun()
    else:
        score = data.get("score")
        counts = data.get("counts")
        score_str = f"{score} / {counts * 10}" if score is not None else "-"

        # 状态 / 得分 / 测试点数量：统计卡片
        stat_cls = {"success": "oj-stat-ok", "error": "oj-stat-err"}.get(status, "oj-stat-wait")
        stats_html = (
            f"<div class=\"oj-stat-card {stat_cls}\"><div class=\"oj-stat-k\">状态</div>"
            f"<div class=\"oj-stat-v\">{status_zh.get(status, status)}</div></div>"
            f"<div class=\"oj-stat-card\"><div class=\"oj-stat-k\">得分</div>"
            f"<div class=\"oj-stat-v oj-stat-score\">{score_str}</div></div>"
            f"<div class=\"oj-stat-card\"><div class=\"oj-stat-k\">测试点数量</div>"
            f"<div class=\"oj-stat-v\">{counts if counts is not None else '-'}</div></div>"
        )
        st.markdown(f"<div class=\"oj-stat-row\">{stats_html}</div>", unsafe_allow_html=True)

        if data.get("compile_info"):
            ci = data["compile_info"]
            compile_zh = {"success": "成功", "failed": "失败"}.get(ci.get("result"), ci.get("result"))
            st.markdown(f"**编译结果**: {compile_zh}")
            if ci.get("message"):
                st.code(ci["message"])
        if data.get("error_info"):
            st.error(data["error_info"])

        # 日志明细：自绘美观表格
        code2, log, _ = api_call("GET", f"/api/submissions/{sid}/log")
        if code2 == 200 and log and log.get("details"):
            result_map = {
                "AC": ("AC", "oj-tag-ac", "通过"),
                "WA": ("WA", "oj-tag-wa", "答案错误"),
                "TLE": ("TLE", "oj-tag-tle", "超时"),
                "MLE": ("MLE", "oj-tag-mle", "内存超限"),
                "RE": ("RE", "oj-tag-re", "运行错误"),
                "CE": ("CE", "oj-tag-ce", "编译错误"),
                "UNK": ("UNK", "oj-tag-unk", "未知"),
            }
            rows_html = []
            for d in log["details"]:
                code_r, cls, label = result_map.get(d["result"], (d["result"], "oj-tag-unk", ""))
                t = d.get("time")
                m = d.get("memory")
                t_str = f"{t:.3f} s" if isinstance(t, (int, float)) else (t if t is not None else "-")
                m_str = f"{m:.2f} MB" if isinstance(m, (int, float)) else (m if m is not None else "-")
                rows_html.append(
                    f"<tr><td>#{d['id']}</td>"
                    f"<td><span class=\"oj-tag {cls}\">{code_r}</span>"
                    f"<span class=\"oj-tag-sub\">{label}</span></td>"
                    f"<td>{t_str}</td><td>{m_str}</td></tr>"
                )
            table_html = (
                "<div class=\"oj-case-table\">"
                "<div class=\"oj-case-title\">测试点明细</div>"
                "<table><thead><tr><th>测试点</th><th>结果</th><th>时间</th><th>内存</th></tr></thead>"
                f"<tbody>{''.join(rows_html)}</tbody></table></div>"
            )
            st.markdown(table_html, unsafe_allow_html=True)

    # 底部返回按钮
    if st.button("← 返回提交记录", key="sub_detail_back"):
        st.session_state.pop("view_submission_id", None)
        st.session_state["show_submission_list"] = True
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
                    "角色": ROLE_ZH.get(user["role"], user["role"]),
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
            # admin 内置账号锁定为管理员，前端直接禁用改角色操作
            if username == "admin":
                st.info("admin 账号已锁定为管理员，无法修改角色")
            else:
                # 角色下拉框：显示中文，内部用英文枚举值
                role_zh_options = [ROLE_ZH[r] for r in ("user", "admin", "banned")]
                role_zh = st.selectbox("新角色", role_zh_options)
                role_reverse = {v: k for k, v in ROLE_ZH.items()}
                role = role_reverse.get(role_zh, role_zh)
                if st.button("更新角色"):
                    code, d, msg = api_call(
                        "PUT", f"/api/users/{uid_map[username]}/role", {"role": role}
                    )
                    if code == 200:
                        st.success(f"已将 {username} 的角色改为 {role_zh}")
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
                    "操作": LOG_ACTION_ZH.get(log.get("action"), log.get("action")),
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
        col4.metric("费用", f"${usage.get('cost', 0.0):.6f} 美元")

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
    # 刷新后从 localStorage 恢复登录态（须在渲染顶栏、判断登录态之前）
    _restore_session()

    menu = render_topbar()

    if not is_logged_in():
        render_login()
        # 每次 run 末尾统一同步 localStorage（未登录 → 清除，避免残留脏会话）
        _sync_localstorage()
        return

    if menu == "用户":
        render_user_info()
    elif menu == "题目":
        if "view_problem_id" in st.session_state:
            render_problem_detail()
        elif st.session_state.get("problem_view") == "create":
            render_problem_create()
        elif st.session_state.get("problem_view") == "edit":
            render_problem_edit()
        else:
            render_problem_list()
    elif menu == "评测提交":
        if "view_submission_id" in st.session_state:
            render_submission_detail()
        elif st.session_state.get("show_submission_list"):
            render_submission_list()
        else:
            render_submission()
    elif menu == "用户管理":
        render_user_admin()
    elif menu == "AI 命题":
        render_ai()

    # 每次 run 末尾统一同步 localStorage（已登录 → 写入当前会话）
    _sync_localstorage()


if __name__ == "__main__":
    main()
