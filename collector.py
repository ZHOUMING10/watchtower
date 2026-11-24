"""模拟采集端：没有硬件也能先把服务端链路跑通。

以后接 ESP32 时，只需把 build_payload() 换成真实传感器读数，
上报的 HTTP 部分一行都不用改 —— 这就是「先定接口」的好处。
"""
import json
import random
import time
import urllib.request

from config import DEVICE_ID, DEVICE_TOKEN, INTERVAL, URL

# 随机游走的当前值，让曲线像真实温度，而不是每帧乱跳
state = {"temperature": 24.0, "humidity": 50.0}


def build_payload():
    state["temperature"] = round(
        max(-40, min(125, state["temperature"] + random.uniform(-0.6, 0.6))), 1
    )
    state["humidity"] = round(
        max(0, min(100, state["humidity"] + random.uniform(-1.5, 1.5))), 1
    )
    # 约 5% 概率造一个高温尖峰，给阶段 2 的告警面板留出可演示的数据
    if random.random() < 0.05:
        state["temperature"] = round(random.uniform(36.0, 42.0), 1)
    return {
        "device_id": DEVICE_ID,
        "temperature": state["temperature"],
        "humidity": state["humidity"],
    }


def send(payload):
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Device-Token": DEVICE_TOKEN,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status


if __name__ == "__main__":
    print(f"device={DEVICE_ID} -> {URL} every {INTERVAL}s, Ctrl+C to stop")
    while True:
        payload = build_payload()
        try:
            code = send(payload)
            print(f"[{time.strftime('%H:%M:%S')}] {code} {payload}")
        except Exception as exc:
            # 服务没开或网络断了都不能让采集端崩掉，重试即可
            print(f"[{time.strftime('%H:%M:%S')}] send failed: {exc}")
        time.sleep(INTERVAL)
