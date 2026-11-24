"""Watchtower 服务端：采集链路（阶段 1）+ 状态面板（阶段 2）。

为什么先写成单文件：先把「收数据 -> 校验 -> 落库 -> 能查」这条链路跑通，
再拆模块。链路没跑通之前拆文件，只会增加排错难度。
"""
import logging
import sqlite3
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from flask import Flask, g, jsonify, render_template, request

from config import ALERT_TEMP, DB_PATH, DEVICE_TOKEN, HOST, LOG_DIR, OFFLINE_AFTER, PORT

app = Flask(__name__)

# 运维第一课：出事时能查到发生了什么。
# RotatingFileHandler 让日志不会无限膨胀把磁盘写满。
_file_handler = RotatingFileHandler(
    LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
app.logger.addHandler(_file_handler)
app.logger.setLevel(logging.INFO)


def get_db():
    """每个请求共用一个连接，请求结束自动关闭。"""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        # 按时间建索引：后面查「最近 N 条」才不会全表扫描
        db.execute(
            """CREATE TABLE IF NOT EXISTS readings (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   device_id TEXT NOT NULL,
                   temperature REAL NOT NULL,
                   humidity REAL NOT NULL,
                   created_at TEXT NOT NULL
               )"""
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_readings_time ON readings(created_at)"
        )
        # 阶段 2 加了按温度查告警，给这个条件也留一个索引
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_readings_temp ON readings(temperature)"
        )
        db.commit()


@app.get("/")
def index():
    """面板由 Flask 同源提供：前端不用配 CORS，也不用单独起一个静态服务器。"""
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    """健康检查：给进程守护和监控用，不查数据库，保证永远快。"""
    return jsonify(status="ok", time=datetime.now(timezone.utc).isoformat())


@app.post("/api/ingest")
def ingest():
    # 令牌放请求头而不是 URL，避免出现在访问日志里被泄露
    if request.headers.get("X-Device-Token") != DEVICE_TOKEN:
        app.logger.warning("rejected ingest from %s", request.remote_addr)
        return jsonify(error="unauthorized"), 401

    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")
    temp, humid = data.get("temperature"), data.get("humidity")

    # 服务端永远不信任客户端：类型、范围都要校验
    if not isinstance(device_id, str) or not device_id.strip():
        return jsonify(error="bad device_id"), 400
    try:
        temp, humid = float(temp), float(humid)
    except (TypeError, ValueError):
        return jsonify(error="temperature/humidity must be numbers"), 400
    if not (-40 <= temp <= 125 and 0 <= humid <= 100):
        return jsonify(error="reading out of range"), 400

    now = datetime.now(timezone.utc).isoformat()
    # 参数化查询：值永远不拼进 SQL 字符串，这是防注入的底线
    get_db().execute(
        "INSERT INTO readings (device_id, temperature, humidity, created_at) "
        "VALUES (?, ?, ?, ?)",
        (device_id.strip(), temp, humid, now),
    )
    get_db().commit()
    app.logger.info("reading device=%s temp=%.1f humid=%.1f", device_id, temp, humid)
    return jsonify(ok=True, created_at=now), 201


@app.get("/api/readings")
def readings():
    # 上限防止一次把整张表拉爆；下限防止负数导致 SQLite 不限行
    try:
        limit = max(1, min(int(request.args.get("limit", "20")), 200))
    except ValueError:
        return jsonify(error="limit must be an integer"), 400
    rows = get_db().execute(
        "SELECT * FROM readings ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/status")
def status():
    """给面板用的一次性聚合：在线状态 + 最新读数 + 近期告警。

    为什么在服务端算：离线判定要靠时间差，各台设备的时钟不一致，
    放前端算结果会打架；而且以后改告警规则，只需要改这一处。
    """
    latest = get_db().execute(
        "SELECT * FROM readings ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        return jsonify(
            online=False,
            latest=None,
            alerts=[],
            alert_count=0,
            threshold=ALERT_TEMP,
            offline_after=OFFLINE_AFTER,
        )

    age = (
        datetime.now(timezone.utc) - datetime.fromisoformat(latest["created_at"])
    ).total_seconds()
    alerts = get_db().execute(
        "SELECT * FROM readings WHERE temperature >= ? ORDER BY id DESC LIMIT 10",
        (ALERT_TEMP,),
    ).fetchall()
    return jsonify(
        online=age <= OFFLINE_AFTER,
        age_seconds=round(age, 1),
        latest=dict(latest),
        alerts=[dict(r) for r in alerts],
        alert_count=len(alerts),
        threshold=ALERT_TEMP,
        offline_after=OFFLINE_AFTER,
    )


# 建表放在模块级，而不是 if __name__ 里面：
# python app.py 会执行 __main__ 块，但 gunicorn 用 app:app 只是 import 模块，
# 那段永远不会跑。放这里才能保证两种启动方式都能建表。
# CREATE TABLE IF NOT EXISTS 是幂等的，多个 worker 同时 import 也安全
# （sqlite3.connect 默认 timeout=5s，会等锁而不是立刻报错）。
init_db()

if __name__ == "__main__":
    app.logger.info("watchtower starting on %s:%s", HOST, PORT)
    # debug=False：Flask 调试器允许远程执行代码，任何时候都不要对外打开
    app.run(host=HOST, port=PORT, debug=False)
