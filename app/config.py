"""全局配置：路径、常量、默认值。"""
import os

# 项目根目录（app/ 的上一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 运行时数据目录（存放题目、语言、用户、提交等，git 忽略）
DATA_DIR = os.path.join(BASE_DIR, "data")
PROBLEMS_DIR = os.path.join(DATA_DIR, "problems")
SUBMISSIONS_DIR = os.path.join(DATA_DIR, "submissions")
LANGUAGES_FILE = os.path.join(DATA_DIR, "languages.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
AUDIT_LOGS_FILE = os.path.join(DATA_DIR, "audit_logs.json")
AI_MODEL_CONFIG_FILE = os.path.join(DATA_DIR, "ai_model_config.json")
AI_TASKS_DIR = os.path.join(DATA_DIR, "ai_tasks")

# 评测临时工作目录
JUDGE_TMP_DIR = os.path.join(DATA_DIR, "tmp")

# Session 密钥（课程用途，硬编码即可）
SESSION_SECRET_KEY = "oj-course-secret-key-please-change-in-production"

# 初始管理员
INIT_ADMIN_USERNAME = "admin"
INIT_ADMIN_PASSWORD = "admintestpassword"

# 默认资源限制
DEFAULT_TIME_LIMIT = 3.0   # 秒
DEFAULT_MEMORY_LIMIT = 128  # MB

# 编译阶段时限（独立于运行时限；编译需预留编译器冷启动时间，应远大于运行时限）
COMPILE_TIME_LIMIT = 30.0  # 秒
COMPILE_MEMORY_LIMIT = 512  # MB

# 提交频率限制：1 分钟内最多 N 次
RATE_LIMIT_WINDOW = 60      # 秒
RATE_LIMIT_MAX = 3          # 次

# 每个测试点分值
TESTCASE_SCORE = 10


def ensure_dirs() -> None:
    """确保数据目录存在。"""
    for d in (DATA_DIR, PROBLEMS_DIR, SUBMISSIONS_DIR, JUDGE_TMP_DIR, AI_TASKS_DIR):
        os.makedirs(d, exist_ok=True)
