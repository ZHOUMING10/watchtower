"""统一读取配置。

安全习惯第 1 条：密钥只放本地 .env，不写进代码、不提交到 Git。
这里用标准库手写解析，是为了阶段 1 只依赖 Flask 这一个第三方包。
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _load_env():
    env_file = BASE / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            # setdefault：命令行里显式设置的环境变量优先级更高，方便临时改配置
            os.environ.setdefault(key.strip(), value.strip())


_load_env()

DEVICE_TOKEN = os.environ.get("WATCHTOWER_DEVICE_TOKEN", "dev-token-change-me")
HOST = os.environ.get("WATCHTOWER_HOST", "127.0.0.1")
PORT = int(os.environ.get("WATCHTOWER_PORT", "5000"))
# 注意：改了 PORT 就要同步改 URL，否则采集端还往旧端口发
URL = os.environ.get("WATCHTOWER_URL", f"http://127.0.0.1:{PORT}/api/ingest")
INTERVAL = int(os.environ.get("WATCHTOWER_INTERVAL", "10"))
DEVICE_ID = os.environ.get("WATCHTOWER_DEVICE_ID", "lab-01")

# 告警与离线判定的阈值放配置里，以后调规则不用改代码
ALERT_TEMP = float(os.environ.get("WATCHTOWER_ALERT_TEMP", "35.0"))
OFFLINE_AFTER = int(os.environ.get("WATCHTOWER_OFFLINE_AFTER", "60"))

DB_PATH = BASE / "watchtower.db"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
