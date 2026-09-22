"""Generate a Knowledge Agent icon (ICO + PNG) using pure Python."""
import struct, zlib, math

SIZE = 256
TEAL = (39, 102, 120)
DARK_TEAL = (23, 38, 46)
WHITE = (255, 255, 255)

def create_rgba_pixels():
    """Create RGBA pixel array for the icon."""
    pixels = bytearray()
    cx, cy = SIZE / 2, SIZE / 2
    outer_r = SIZE / 2 - 8

    for y in range(SIZE):
        for x in range(SIZE):
            dx = x - cx
            dy = y - cy
            dist = math.sqrt(dx * dx + dy * dy)

            # Circle mask with anti-aliasing
            if dist > outer_r + 1:
                pixels.extend([0, 0, 0, 0])
                continue

            alpha = 255
            if dist > outer_r - 1:
                alpha = int(255 * (outer_r + 1 - dist) / 2)
                alpha = max(0, min(255, alpha))

            if alpha == 0:
                pixels.extend([0, 0, 0, 0])
                continue

            # Gradient background
            t = (dy + outer_r) / (2 * outer_r)
            r = int(TEAL[0] + (DARK_TEAL[0] - TEAL[0]) * t * 0.5)
            g = int(TEAL[1] + (DARK_TEAL[1] - TEAL[1]) * t * 0.5)
            b = int(TEAL[2] + (DARK_TEAL[2] - TEAL[2]) * t * 0.5)

            # Draw bold "K" centered
            lx = x - 72
            ly = y - 50
            is_letter = False

            # Vertical bar
            if 25 <= lx <= 58 and 25 <= ly <= 205:
                is_letter = True

            # Upper diagonal
            if not is_letter and 58 <= lx <= 160:
                t2 = (lx - 58) / 102
                arm_y = 115 - t2 * 85
                if abs(ly - arm_y) <= 18:
                    is_letter = True

            # Lower diagonal
            if not is_letter and 58 <= lx <= 170:
                t2 = (lx - 58) / 112
                arm_y = 115 + t2 * 70
                if abs(ly - arm_y) <= 18:
                    is_letter = True

            if is_letter:
                pixels.extend([255, 255, 255, alpha])
            else:
                pixels.extend([r, g, b, alpha])

    return bytes(pixels)

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
        directory += struct.pack("<BBBBHHII",
            w & 255, h & 255, 0, 0, 1, 32, len(png), offset)
        image_data += png
        offset += len(png)
    return header + directory + image_data

if __name__ == "__main__":
    print("Generating 256x256 icon...")
    rgba = create_rgba_pixels()
    png_256 = make_png(rgba, 256, 256)

    def downscale(src, sw, dw):
        ratio = sw / dw
        out = bytearray()
        for dy in range(dw):
            for dx in range(dw):
                sx = int(dx * ratio)
                sy = int(dy * ratio)
                idx = (sy * sw + sx) * 4
                out.extend(src[idx:idx+4])
        return bytes(out)

    print("Creating smaller sizes...")
    png_64 = make_png(downscale(rgba, 256, 64), 64, 64)
    png_32 = make_png(downscale(rgba, 256, 32), 32, 32)

    ico = make_ico([(256, 256, png_256), (64, 64, png_64), (32, 32, png_32)])

    with open("icon.ico", "wb") as f:
        f.write(ico)
    with open("icon.png", "wb") as f:
        f.write(png_256)

    print(f"icon.ico: {len(ico):,} bytes")
    print(f"icon.png: {len(png_256):,} bytes")
    print("Done!")
