# OJ 在线评测系统

程序设计训练（Python）课程大作业：基于 FastAPI + Streamlit 构建的小型完整在线评测（Online Judge）系统。

## 功能特性

- **题目管理**（Step 1）：题目配置 JSON 存储、字段校验、增删改查
- **评测控制**（Step 2）：异步评测、Python/C++ 多语言、动态注册语言、时间/内存限制（TLE/MLE 判定）
- **评测管理**（Step 3）：提交列表、详情、重新评测、分页筛选
- **用户管理**（Step 4）：注册/登录/登出、Session 认证、权限管理（user/admin/banned）
- **评测日志**（Step 5）：测试点明细、可见性配置、访问审计
- **前端交互**（Step 6）：Streamlit 三组页面（用户/题目/评测提交）
- **AI 智能命题**（进阶）：需求出题、模型配置（URL/模型/密钥/计价币种）、实时进度轮询、中断、Token 与费用统计

## 技术栈

- 后端：FastAPI（全部 `async def` 异步接口）
- 前端：Streamlit
- 存储：JSON 文件（`data/` 目录）
- 认证：Starlette SessionMiddleware + bcrypt
- 评测：asyncio + subprocess + psutil（Windows 兼容方案）

## 目录结构

```
bh2/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 全局配置
│   ├── schemas.py           # 统一响应 helper
│   ├── models.py            # Pydantic 模型
│   ├── deps.py              # 认证/权限/限流依赖
│   ├── storage.py           # JSON 存储层
│   ├── judge/               # 评测引擎（runner/engine/queue）
│   ├── ai/                  # AI 命题引擎（LLM 调用/任务状态机/中断）
│   └── routers/             # 路由（problems/languages/submissions/users/logs/ai）
├── frontend/app.py          # Streamlit 前端
├── data/                    # 运行时数据（git 忽略）
├── run_backend.py           # 后端启动脚本
├── run_frontend.py          # 前端启动脚本
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动后端

```bash
python run_backend.py
```

后端运行在 `http://127.0.0.1:8000`

### 3. 启动前端

```bash
python run_frontend.py
```

前端运行在 `http://127.0.0.1:8501`

### 4. 初始账户

- 用户名：`admin`
- 密码：`admintestpassword`

## API 文档

所有接口、参数、状态码详见 `requirements/api.md`。接口遵循统一响应结构：

```json
{"code": 200, "msg": "success", "data": ...}
```

## 评测状态说明

| 状态 | 含义 |
|------|------|
| AC | Accepted Answer（输出正确） |
| WA | Wrong Answer（输出错误） |
| TLE | Time Limit Exceeded（超时） |
| MLE | Memory Limit Exceeded（超内存） |
| RE | Runtime Error（运行时错误） |
| CE | Compilation Error（编译错误） |
| UNK | Unknown Error（未知错误） |

每个测试点 10 分，得分 = AC 测试点数 × 10。

## 环境说明

- 开发环境为 Windows，资源限制采用 `asyncio.wait_for`（时间）+ `psutil`（内存）跨平台方案
- C++ 评测依赖 `g++` 编译器（需在 PATH 中，验收环境为 Linux）
