import test from "node:test";
import assert from "node:assert/strict";
import { detectPixelImageCandidates } from "../../src/features/blog/utils/pixelImageCandidates.ts";

test("像素候选扫描在取消前退出，不创建位图或分配扫描画布", async () => {
  const controller = new AbortController();
  controller.abort();
  const candidates = await detectPixelImageCandidates({} as File, [], controller.signal);
  assert.deepEqual(candidates, []);
});

test("像素条带检测在混排合成图中给出低置信度图片区建议框", async () => {
  const pixels = new Uint8ClampedArray(320 * 200 * 4);
  for (let y = 0; y < 200; y += 1) for (let x = 0; x < 320; x += 1) {
    const offset = (y * 320 + x) * 4;
    const inImage = x >= 80 && x < 240 && y >= 50 && y < 150;
    const shade = inImage ? ((x * 7 + y * 11) % 180 + 45) : 255;
    pixels[offset] = shade;
    pixels[offset + 1] = inImage ? (x * 13 + y * 5) % 220 : 255;
    pixels[offset + 2] = inImage ? (x * 3 + y * 17) % 230 : 255;
    pixels[offset + 3] = 255;
  }
  const oldDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  const oldBitmap = Object.getOwnPropertyDescriptor(globalThis, "createImageBitmap");
  Object.defineProperty(globalThis, "document", { configurable: true, value: {
    createElement: () => ({ width: 0, height: 0, getContext: () => ({
      drawImage() {}, getImageData: () => ({ data: pixels }),
    }) }),
  } });
  Object.defineProperty(globalThis, "createImageBitmap", { configurable: true, value: async () => ({ width: 320, height: 200, close() {} }) });
  try {
    const result = await detectPixelImageCandidates({} as File);
    assert.equal(result.length, 1);
    assert.equal(result[0]!.origin, "pixels");
    assert.ok(result[0]!.confidence <= 0.62);
    assert.ok(result[0]!.x > 0.2 && result[0]!.x < 0.3);
    assert.ok(result[0]!.y <= 0.25 && result[0]!.y > 0.2);
    assert.ok(result[0]!.width > 0.45 && result[0]!.width < 0.55);
    assert.ok(result[0]!.y + result[0]!.height >= 0.75 && result[0]!.height < 0.65);
  } finally {
    if (oldDocument) Object.defineProperty(globalThis, "document", oldDocument);
    else Reflect.deleteProperty(globalThis, "document");
    if (oldBitmap) Object.defineProperty(globalThis, "createImageBitmap", oldBitmap);
    else Reflect.deleteProperty(globalThis, "createImageBitmap");
  }
});
