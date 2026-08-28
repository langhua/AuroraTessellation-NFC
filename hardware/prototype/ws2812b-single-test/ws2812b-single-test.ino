// ============================================================
// WS2812B-5050 外部单颗测试 — ESP32-S3-DevKitC-1
// ============================================================
// Wiring:
//   ESP32-S3  5Vin(或3V3) -> WS2812B  VDD
//   ESP32-S3  GPIO15      -> WS2812B  DI
//   ESP32-S3  GND         -> WS2812B  GND
//   WS2812B  DO           -> (unconnected)
//
// 注：若 5Vin 供电读数为 0，可先用 3V3 给 VDD 供电验证灯珠能否点亮。
//
// Library: Adafruit NeoPixel 1.15.5
// Board: ESP32S3 Dev Module (esp32:esp32:esp32s3)
// ============================================================

#include <Adafruit_NeoPixel.h>

#define PIN         15          // ESP32-S3 GPIO15
#define NUMPIXELS   1           // 单颗灯珠

Adafruit_NeoPixel pixels(NUMPIXELS, PIN, NEO_GRB + NEO_KHZ800);

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("Onboard WS2812 (GPIO48) test starting...");

  pixels.begin();
  pixels.setBrightness(40);     // 首次测试先调低亮度，保护眼睛和灯珠
  pixels.clear();
  pixels.show();
  delay(300);
}

void loop() {
  // 1) 呼吸渐变：红 → 绿 → 蓝（也顺便验证颜色顺序 GRB）
  fade(255, 0, 0);   // 红
  fade(0, 255, 0);   // 绿
  fade(0, 0, 255);   // 蓝

  // 2) 单色常亮各 1 秒（方便肉眼核对颜色顺序）
  solid(255, 0, 0);
  solid(0, 255, 0);
  solid(0, 0, 255);

  // 3) 白色（三色全亮）
  solid(255, 255, 255);

  // 4) 熄灭
  pixels.clear();
  pixels.show();
  delay(1000);
}

void fade(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i <= 255; i++) {
    pixels.setPixelColor(0, pixels.Color(
      (uint8_t)((long)r * i / 255),
      (uint8_t)((long)g * i / 255),
      (uint8_t)((long)b * i / 255)));
    pixels.show();
    delay(3);
  }
  delay(300);
}

void solid(uint8_t r, uint8_t g, uint8_t b) {
  pixels.setPixelColor(0, pixels.Color(r, g, b));
  pixels.show();
  delay(1000);
}
