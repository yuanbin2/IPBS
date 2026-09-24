"""Generate the 智能个人博客系统 app icon (ICO + PNG) using pure Python.

Design (brand palette from frontend themes: #276678 teal / #182329 dark):
  - rounded-square (squircle) badge instead of a plain circle — modern app-icon
    convention and it stands out next to circular avatars
  - diagonal teal gradient with a soft top-left sheen and a 1px inner
    highlight so the badge keeps its edge on dark taskbars
  - a properly proportioned "B" (stem + two bowl rings for Blog) with a soft
    drop shadow for depth
  - a four-point sparkle at the upper right — the "AI/agent" signal

Quality: the master is rendered at 2x (512) with analytic anti-aliasing on the
signed-distance fields, then every shipped size (256/64/48/32/16) is produced
by exact box-filter downscaling, so small sizes are smooth instead of jagged.
"""
import math
import struct
import zlib

MASTER = 512  # supersampled master; shipped sizes are box-downscaled from it
WHITE = (255, 255, 255)
SPARKLE = (206, 232, 240)


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def mix(a, b, t):
    t = clamp01(t)
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def sd_round_rect(px, py, x0, y0, x1, y1, r):
    """Signed distance to a rounded rectangle (negative inside).

    Standard box-SDF with the corner radius folded into the half-extents;
    a point beyond a corner measures to the corner arc, not to the square.
    """
    qx = abs(px - (x0 + x1) / 2) - ((x1 - x0) / 2 - r)
    qy = abs(py - (y0 + y1) / 2) - ((y1 - y0) / 2 - r)
    return min(max(qx, qy), 0.0) + math.sqrt(max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2) - r


def sd_capsule(px, py, ax, ay, bx, by, r):
    """Signed distance to a capsule (segment with round caps), negative inside."""
    abx, aby = bx - ax, by - ay
    length2 = abx * abx + aby * aby
    t = 0.0 if length2 == 0 else clamp01(((px - ax) * abx + (py - ay) * aby) / length2)
    dx, dy = px - (ax + abx * t), py - (ay + aby * t)
    return math.sqrt(dx * dx + dy * dy) - r


def sd_arc(px, py, cx, cy, r, t, a0_deg, a1_deg):
    """Signed distance to a circular arc band (the B's bowl rings).

    Measures to the arc itself inside [a0, a1] and to the nearest endpoint
    outside it, so the stroke has flat ends instead of wrapping around.
    """
    a0, a1 = math.radians(a0_deg), math.radians(a1_deg)
    angle = math.atan2(py - cy, px - cx)
    if a0 <= angle <= a1:
        ax, ay = cx + r * math.cos(angle), cy + r * math.sin(angle)
    else:
        e0x, e0y = cx + r * math.cos(a0), cy + r * math.sin(a0)
        e1x, e1y = cx + r * math.cos(a1), cy + r * math.sin(a1)
        d0 = (px - e0x) ** 2 + (py - e0y) ** 2
        d1 = (px - e1x) ** 2 + (py - e1y) ** 2
        ax, ay = (e0x, e0y) if d0 <= d1 else (e1x, e1y)
    return math.sqrt((px - ax) ** 2 + (py - ay) ** 2) - t


def coverage(sd: float) -> float:
    """Analytic anti-aliasing: 1px-wide transition across the SDF boundary."""
    return clamp01(0.5 - sd)


# Glyph geometry (512 canvas). Stroke radius 22 (44px on 512) keeps the B
# legible at 16px; each bowl is a right-half ring plus three bars that tie it
# back to the stem, so the junction reads as a letter, not a filled blob.
BADGE = (40, 40, 472, 472, 112)          # x0, y0, x1, y1, corner radius
STEM = (185, 165, 185, 347, 22)          # ax, ay, bx, by, stroke radius
BOWL_UP = (245, 210, 46, 22, -90, 90)    # cx, cy, ring radius, stroke radius, arc degrees
BOWL_DOWN = (245, 302, 46, 22, -90, 90)
BAR_TOP = (207, 164, 245, 164, 22)       # ax, ay, bx, by, stroke radius
BAR_MID = (207, 256, 245, 256, 22)
BAR_BOTTOM = (207, 348, 245, 348, 22)
SPARK_V = (398, 132, 398, 200, 12)
SPARK_H = (372, 166, 424, 166, 12)

GRAD_TOP_LEFT = (62, 147, 166)           # #3E93A6
GRAD_MID = (39, 102, 120)                # #276678 brand teal
GRAD_BOTTOM_RIGHT = (18, 33, 42)         # #12212A


def render_master(size: int = MASTER) -> bytearray:
    """Render the icon at `size` with analytic AA; returns RGBA bytes."""
    scale = size / MASTER
    pixels = bytearray(size * size * 4)
    diagonal = MASTER * 2

    for y in range(size):
        py = y / scale
        for x in range(size):
            px = x / scale

            # --- badge shape ---
            badge_sd = sd_round_rect(px, py, *BADGE)
            badge_cov = coverage(badge_sd)

            # --- background: diagonal gradient + sheen ---
            t_diag = (px + py) / diagonal
            if t_diag < 0.55:
                bg = mix(GRAD_TOP_LEFT, GRAD_MID, t_diag / 0.55)
            else:
                bg = mix(GRAD_MID, GRAD_BOTTOM_RIGHT, (t_diag - 0.55) / 0.45)

            # soft radial sheen, top-left
            sx, sy = (px - 170) / 300, (py - 140) / 300
            sheen = clamp01(1.0 - math.sqrt(sx * sx + sy * sy))
            bg = mix(bg, WHITE, sheen * 0.16)

            # 1px inner highlight keeps the badge edge crisp on dark taskbars
            edge = clamp01(1.0 - abs(badge_sd + 2.0) / 2.0)
            bg = mix(bg, (150, 210, 224), edge * 0.35)

            # --- B shadow, then B ---
            shadow = max(
                coverage(sd_capsule(px, py - 7, *STEM[:4], STEM[4])),
                coverage(sd_arc(px, py - 7, *BOWL_UP)),
                coverage(sd_arc(px, py - 7, *BOWL_DOWN)),
                coverage(sd_capsule(px, py - 7, *BAR_TOP[:4], BAR_TOP[4])),
                coverage(sd_capsule(px, py - 7, *BAR_MID[:4], BAR_MID[4])),
                coverage(sd_capsule(px, py - 7, *BAR_BOTTOM[:4], BAR_BOTTOM[4])),
            )
            bg = mix(bg, (10, 20, 26), shadow * 0.35)

            glyph = max(
                coverage(sd_capsule(px, py, *STEM[:4], STEM[4])),
                coverage(sd_arc(px, py, *BOWL_UP)),
                coverage(sd_arc(px, py, *BOWL_DOWN)),
                coverage(sd_capsule(px, py, *BAR_TOP[:4], BAR_TOP[4])),
                coverage(sd_capsule(px, py, *BAR_MID[:4], BAR_MID[4])),
                coverage(sd_capsule(px, py, *BAR_BOTTOM[:4], BAR_BOTTOM[4])),
            )
            fg = mix(bg, WHITE, glyph)

            # --- sparkle (four-point star from two crossed capsules) ---
            spark = max(
                coverage(sd_capsule(px, py, *SPARK_V[:4], SPARK_V[4])),
                coverage(sd_capsule(px, py, *SPARK_H[:4], SPARK_H[4])),
            )
            fg = mix(fg, SPARKLE, spark)

            alpha = int(255 * badge_cov)
            offset = (y * size + x) * 4
            # 颜色通道是 0-255 标度，按 0-255 截取（clamp01 只用于混合系数）
            pixels[offset : offset + 4] = bytes(
                (
                    int(max(0, min(255, fg[0]))),
                    int(max(0, min(255, fg[1]))),
                    int(max(0, min(255, fg[2]))),
                    alpha,
                )
            )
    return pixels


def box_downscale(src: bytearray, src_size: int, dst_size: int) -> bytearray:
    """Exact box-filter downscale (area average) — no nearest-neighbor jaggies."""
    out = bytearray(dst_size * dst_size * 4)
    ratio = src_size / dst_size
    for dy in range(dst_size):
        y0, y1 = int(dy * ratio), max(int((dy + 1) * ratio), int(dy * ratio) + 1)
        for dx in range(dst_size):
            x0, x1 = int(dx * ratio), max(int((dx + 1) * ratio), int(dx * ratio) + 1)
            acc = [0, 0, 0, 0]
            count = 0
            for sy in range(y0, y1):
                for sx in range(x0, x1):
                    idx = (sy * src_size + sx) * 4
                    for c in range(4):
                        acc[c] += src[idx + c]
                    count += 1
            offset = (dy * dst_size + dx) * 4
            out[offset : offset + 4] = bytes(c // count for c in acc)
    return out


def make_png(rgba, width, height):
    """Encode RGBA pixels as PNG."""

    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride : (y + 1) * stride])

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def make_ico(pngs):
    """Create ICO from list of (width, height, png_data)."""
    count = len(pngs)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    directory = b""
    image_data = b""
    for w, h, png in pngs:
        directory += struct.pack("<BBBBHHII", w & 255, h & 255, 0, 0, 1, 32, len(png), offset)
        image_data += png
        offset += len(png)
    return header + directory + image_data


if __name__ == "__main__":
    print(f"Rendering {MASTER}x{MASTER} master (analytic AA)...")
    master = render_master()

    sizes = [256, 64, 48, 32, 16]
    png_by_size = {}
    for size in sizes:
        pixels = master if size == MASTER else box_downscale(master, MASTER, size)
        png_by_size[size] = make_png(pixels, size, size)
        print(f"  {size}x{size}: {len(png_by_size[size]):,} bytes")

    ico = make_ico([(size, size, png_by_size[size]) for size in sizes])
    with open("icon.ico", "wb") as f:
        f.write(ico)
    with open("icon.png", "wb") as f:
        f.write(png_by_size[256])
    print(f"icon.ico: {len(ico):,} bytes ({len(sizes)} sizes)")
    print(f"icon.png: {len(png_by_size[256]):,} bytes (256x256)")
    print("Done!")
