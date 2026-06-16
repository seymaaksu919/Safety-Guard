#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <WebSocketsClient.h>
#include "time.h"
#include "board_config.h"

const char* ssid     = "seyma";
const char* password = "12345678";
const char* apiKey   = "fabrika_ortak_gizli_key_123";
const char* deviceId = "esp32cam";

const char* wsHost = "192.168.43.218";
const uint16_t wsPort = 5002;
const char* wsPathPrefix = "/ws/camera";

WebSocketsClient webSocket;
bool wsReady = false;
uint32_t frameSeq = 0;

// Son siber durum: 0=beklemede 1=OK 2=HATA
uint8_t siberDurum = 0;

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length);
bool waitForNtp(int maxWaitSec = 30);
void connectWebSocket();
void siberDurumYaz();

#if defined(LED_GPIO_NUM)
static void setupLedFlash() {
  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, LOW);
}
#endif

void siberDurumYaz() {
  switch (siberDurum) {
    case 1:
      Serial.println("SIBER: OK");
      break;
    case 2:
      Serial.println("SIBER: HATA");
      break;
    default:
      Serial.println("SIBER: BEKLIYOR");
      break;
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("ESP32 WebSocket basladi");

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.frame_size = FRAMESIZE_QVGA;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.jpeg_quality = 12;
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  if (!psramFound()) {
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.fb_count = 1;
  }

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("KAMERA: HATA");
    return;
  }

#if defined(LED_GPIO_NUM)
  setupLedFlash();
#endif

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
  Serial.println(WiFi.localIP());

  configTime(10800, 0, "pool.ntp.org");
  waitForNtp();

  webSocket.onEvent(webSocketEvent);
  connectWebSocket();
  siberDurumYaz();
}

void loop() {
  webSocket.loop();

  if (WiFi.status() != WL_CONNECTED || !wsReady) {
    return;
  }

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    return;
  }

  frameSeq++;
  size_t total = 4 + fb->len;
  uint8_t* buf = (uint8_t*)malloc(total);
  if (buf) {
    buf[0] = (frameSeq >> 24) & 0xFF;
    buf[1] = (frameSeq >> 16) & 0xFF;
    buf[2] = (frameSeq >> 8) & 0xFF;
    buf[3] = frameSeq & 0xFF;
    memcpy(buf + 4, fb->buf, fb->len);
    if (!webSocket.sendBIN(buf, total)) {
      wsReady = false;
      siberDurum = 2;
      siberDurumYaz();
    }
    free(buf);
  }
  esp_camera_fb_return(fb);
  delay(200);
}

void connectWebSocket() {
  siberDurum = 0;
  wsReady = false;

  String path = String(wsPathPrefix);
  path += "?api_key=" + String(apiKey);
  path += "&ts=" + String((unsigned long)time(NULL));
  path += "&device_id=" + String(deviceId);

  webSocket.begin(wsHost, wsPort, path.c_str());
  webSocket.setReconnectInterval(5000);
  webSocket.enableHeartbeat(15000, 3000, 2);
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  uint8_t onceki = siberDurum;

  if (type == WStype_TEXT && payload && length > 0) {
    char msg[128];
    size_t n = length < sizeof(msg) - 1 ? length : sizeof(msg) - 1;
    memcpy(msg, payload, n);
    msg[n] = '\0';

    if (strstr(msg, "AUTH_OK") != nullptr) {
      siberDurum = 1;
      wsReady = true;
    } else if (strstr(msg, "REJECTED") != nullptr || strstr(msg, "ATTACK") != nullptr) {
      siberDurum = 2;
      wsReady = false;
    }
    if (siberDurum != onceki) {
      siberDurumYaz();
    }
    return;
  }

  if (type == WStype_DISCONNECTED || type == WStype_ERROR) {
    wsReady = false;
    if (siberDurum == 1) {
      siberDurum = 2;
      siberDurumYaz();
    }
  }
}

bool waitForNtp(int maxWaitSec) {
  for (int i = 0; i < maxWaitSec; i++) {
    if (time(NULL) > 1700000000L) {
      return true;
    }
    delay(1000);
  }
  return time(NULL) > 1700000000L;
}
