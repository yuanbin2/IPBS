"""Verify the generated icon.png by decoding the actual PNG file."""
import struct
import sys
import zlib
from pathlib import Path


def read_png(path):
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos = 8
    width = height = None
    idat = b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", payload[:10])
            assert (bit_depth, color_type) == (8, 6), f"unexpected format {bit_depth}/{color_type}"
        elif ctype == b"IDAT":
            idat += payload
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 4
    pixels = bytearray()
    for y in range(height):
        row_start = y * (stride + 1)
        assert raw[row_start] == 0, "unexpected filter type"
        pixels.extend(raw[row_start + 1:row_start + 1 + stride])
    return width, height, pixels


def px(pixels, w, x, y):
    i = (y * w + x) * 4
    return tuple(pixels[i:i + 4])


w, h, pixels = read_png(sys.argv[1] if len(sys.argv) > 1 else "icon.png")
print(f"尺寸: {w}x{h}")

print("\n=== 1. 圆角四角应为全透明 ===")
for name, (x, y) in {"左上": (3, 3), "右上": (w - 4, 3), "左下": (3, h - 4), "右下": (w - 4, h - 4)}.items():
    print(f"  {name}: rgba={px(pixels, w, x, y)}")

print("\n=== 2. 背景应为青色系（非白非透明）===")
for name, (x, y) in {"上部": (w // 2, 8), "左中": (8, h // 2), "底部": (w - 10, h - 10)}.items():
    print(f"  {name}: rgba={px(pixels, w, x, y)}")

print("\n=== 3. K 字主干应为白色 ===")
stem_x = int(w * 185 / 512)
for frac in (0.36, 0.5, 0.64):
    y = int(h * frac)
    print(f"  stem ({stem_x},{y}): rgba={px(pixels, w, stem_x, y)}")

print("\n=== 4. 星芒应点亮 ===")
sx, sy = int(w * 388 / 512), int(h * 158 / 512)
print(f"  星心 ({sx},{sy}): rgba={px(pixels, w, sx, sy)}")

print("\n=== 5. 抗锯齿与透明统计 ===")
transparent = opaque = partial = 0
for i in range(3, len(pixels), 4):
    a = pixels[i]
    if a == 0:
        transparent += 1
    elif a == 255:
        opaque += 1
    else:
        partial += 1
total = w * h
print(f"  全透明: {transparent} ({transparent*100//total}%) | 不透明: {opaque} ({opaque*100//total}%) | 半透明: {partial}")
print(f"  不透明区占比应≈65%（圆角方牌 432/512 的平方）")

print("\n=== 6. 白色字形重心（应略偏左上，给星芒留位）===")
xs, ys = [], []
for y in range(h):
    for x in range(w):
        r, g, b, a = px(pixels, w, x, y)
        if a > 200 and r > 235 and g > 235 and b > 235:
            xs.append(x)
            ys.append(y)
print(f"  白色像素 x: {min(xs)}~{max(xs)}, y: {min(ys)}~{max(ys)}")
print(f"  重心: ({(min(xs)+max(xs))//2}, {(min(ys)+max(ys))//2})，画布中心 ({w//2}, {h//2})")
