/* Watchtower 采集端 · ESP32
 *
 * 职责：每 10 秒把温度湿度 POST 到服务器的 /api/ingest。
 * 服务端一行代码都不改 —— 这就是当初「先定接口、采集端可替换」的意义。
 *
 * 现实说明（重要，别自欺）：
 *   temperature = temperatureRead() → ESP32 芯片自己的温度，通常比室温高 15~25°C
 *   humidity    = 50.0              → 占位值，手上还没有湿度传感器
 * 所以今天这一步验证的是「设备 → 公网 → 服务器」这条路，不是数据真实性。
 * DHT11 到货后，只需替换 readTemperature()/readHumidity() 两个函数体。
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include "secrets.h"

static const char *DEVICE_ID = "esp32-room-01";
// 改成你自己服务器的公网 IP 或域名（这里放的是占位地址）
static const char *ENDPOINT  = "http://192.0.2.10/api/ingest";
static const unsigned long INTERVAL_MS = 10000;
static const unsigned long WIFI_TIMEOUT_MS = 20000;

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("WiFi connecting to [%s] ", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT_MS) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nWiFi OK  ip=%s  rssi=%d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    // 最常见原因：连的是 5GHz 频段，ESP32 只支持 2.4GHz
    Serial.println("\nWiFi FAILED (check 2.4GHz / SSID / password)");
  }
}

float readTemperature() {
  // 芯片内部温度传感器，非环境温度
  return temperatureRead();
}

float readHumidity() {
  // 没有湿度传感器，先发占位值；DHT11 到货后改成 dht.readHumidity()
  return 50.0;
}

void setup() {
  Serial.begin(115200);
  delay(1500);  // 等 USB 串口就绪，否则开头几行日志会丢
  Serial.println("\n=== Watchtower sensor boot ===");
  connectWiFi();
}

void loop() {
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) {
    delay(5000);
    return;
  }

  char body[128];
  snprintf(body, sizeof(body),
           "{\"device_id\":\"%s\",\"temperature\":%.1f,\"humidity\":%.1f}",
           DEVICE_ID, readTemperature(), readHumidity());

  HTTPClient http;
  http.setTimeout(5000);
  http.begin(ENDPOINT);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);

  int code = http.POST((uint8_t *)body, strlen(body));
  if (code > 0) {
    // 201 = 入库成功; 401 = 令牌不对; 400 = 数值越界
    Serial.printf("[%lus] %d %s\n", millis() / 1000, code, http.getString().c_str());
  } else {
    // 负数 = 连不上（WiFi 断了、DNS、服务器没开）
    Serial.printf("[%lus] POST failed: %s\n", millis() / 1000,
                  http.errorToString(code).c_str());
  }
  http.end();

  delay(INTERVAL_MS);
}
