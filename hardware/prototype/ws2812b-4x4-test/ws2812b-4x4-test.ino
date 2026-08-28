// ============================================================
// WS2812B-5050 4x4 矩阵测试 — ESP32-S3-DevKitC-1
// ============================================================
// Wiring（4x4 模块，库内 WS2812B-5050-4x4）:
//   ESP32-S3  3V3(或外接5V) -> 模块 VCC
//   ESP32-S3  GPIO15       -> 模块 DIN
//   ESP32-S3  GND          -> 模块 GND（共地）
//   (模块 DOUT 可空接，或接到下一块 DIN 级联)
//
// 电源：16 颗灯珠满白约 960mA。3V3 供电请保持低亮度（默认 30）；
//       要满亮度需外接 5V 到模块 VCC，并共地。
//
// 灯序：模块为蛇形扫描（右下角 1→16），像素 0 在右下角。
//
// Library: Adafruit NeoPixel 1.15.5
// Board: ESP32S3 Dev Module (esp32:esp32:esp32s3)
// ============================================================

#include <Adafruit_NeoPixel.h>

#define PIN         15          // ESP32-S3 GPIO15
#define NUMPIXELS   16          // 4x4 = 16 颗

Adafruit_NeoPixel pixels(NUMPIXELS, PIN, NEO_GRB + NEO_KHZ800);

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("WS2812B 4x4 test starting...");

  pixels.begin();
  pixels.setBrightness(30);     // 实测 3V3 下 30 亮度合适；80 偏亮，满白需外接5V
  pixels.clear();
  pixels.show();
  delay(300);
}

void loop() {
  // 1) 全亮单色循环：验证 16 颗都能亮 + 颜色顺序
  allColor(255, 0, 0);   // 红
  allColor(0, 255, 0);   // 绿
  allColor(0, 0, 255);   // 蓝
  allColor(255, 255, 255); // 白（3V3 下会偏暗/偏色，属正常）

  // 2) 累积铺路：验证完整蛇形路径（路径逐渐铺满，可看清走向）
  verifyTrail(255, 80, 0); // 橙色铺路 + 慢速逐颗带序号

  // 3) 追逐灯（knight rider）：沿蛇形来回
  knightRider(0, 255, 128);

  // 4) 熄灭
  pixels.clear();
  pixels.show();
  delay(800);
}

// 累积铺路：从像素0开始一颗颗点亮且不熄灭，路径像画线一样铺满
// （实测确认：每列从下往上爬，列间底部相连）
void verifyTrail(uint8_t r, uint8_t g, uint8_t b) {
  for (int pass = 0; pass < 3; pass++) {
    for (int i = 0; i < NUMPIXELS; i++) {
      pixels.setPixelColor(i, pixels.Color(r, g, b));
      pixels.show();
      Serial.print("trail to pixel "); Serial.println(i);
      delay(250);
    }
    delay(1500);   // 16 颗铺满后停留，便于观察整条路径
    pixels.clear();
    pixels.show();
    delay(800);
  }
  // 逐颗慢速走一遍（带序号，方便核对每个位置）
  for (int i = 0; i < NUMPIXELS; i++) {
    pixels.clear();
    pixels.setPixelColor(i, pixels.Color(0, 255, 255));
    pixels.show();
    Serial.print("pixel "); Serial.println(i);
    delay(400);
  }
}

// 全部 16 颗同时显示一种颜色
void allColor(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < NUMPIXELS; i++) {
    pixels.setPixelColor(i, pixels.Color(r, g, b));
  }
  pixels.show();
  delay(1200);
}

// 逐颗点亮一圈（按蛇形像素顺序 0..15）
void pixelWalk(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < NUMPIXELS; i++) {
    pixels.clear();
    pixels.setPixelColor(i, pixels.Color(r, g, b));
    pixels.show();
    delay(120);
  }
}

// 追逐灯：一颗高亮沿蛇形来回跑
void knightRider(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < NUMPIXELS; i++) {
    pixels.clear();
    pixels.setPixelColor(i, pixels.Color(r, g, b));
    pixels.show();
    delay(60);
  }
  for (int i = NUMPIXELS - 2; i > 0; i--) {
    pixels.clear();
    pixels.setPixelColor(i, pixels.Color(r, g, b));
    pixels.show();
    delay(60);
  }
}
