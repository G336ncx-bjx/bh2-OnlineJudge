"""启动前端服务（Streamlit）。"""
import os
import sys


def main():
    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        os.path.join(os.path.dirname(__file__), "frontend", "app.py"),
        "--server.port",
        "8501",
        "--server.headless",
        "true",
    ]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
