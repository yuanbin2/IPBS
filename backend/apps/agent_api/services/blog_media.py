"""Storage and validation helpers for intentionally public blog images."""

import hashlib
import re
from pathlib import Path

from PIL import Image, UnidentifiedImageError

BLOG_IMAGE_NAME_RE = re.compile(r"\A[0-9a-f]{32}\.(?:png|jpg|gif|webp)\Z")
BLOG_IMAGE_FORMATS = {
    ".png": ("PNG", "image/png"),
    ".jpg": ("JPEG", "image/jpeg"),
    ".gif": ("GIF", "image/gif"),
    ".webp": ("WEBP", "image/webp"),
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_TOTAL_PIXELS = 40_000_000
MAX_IMAGE_FRAMES = 100


def is_blog_image_name(filename: str) -> bool:
    return bool(BLOG_IMAGE_NAME_RE.fullmatch(filename))


def validate_blog_image(file_obj, filename: str, *, decode_frames: bool = False) -> tuple[str, str]:
    """Validate size, extension, decoded format, dimensions, and frame limits."""
    if not is_blog_image_name(filename):
        raise ValueError("invalid blog image name")
    expected_format, content_type = BLOG_IMAGE_FORMATS[Path(filename).suffix]
    file_obj.seek(0, 2)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > MAX_IMAGE_BYTES:
        raise ValueError("blog image is too large")

    try:
        with Image.open(file_obj) as image:
            if image.format != expected_format:
                raise ValueError("image extension does not match content")
            frame_count = getattr(image, "n_frames", 1)
            if frame_count > MAX_IMAGE_FRAMES or image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("image dimensions or frame count exceed limits")
            image.verify()

        file_obj.seek(0)
        if decode_frames:
            with Image.open(file_obj) as image:
                decoded_pixels = 0
                for frame_index in range(getattr(image, "n_frames", 1)):
                    image.seek(frame_index)
                    frame_pixels = image.width * image.height
                    decoded_pixels += frame_pixels
                    if frame_pixels > MAX_IMAGE_PIXELS or decoded_pixels > MAX_IMAGE_TOTAL_PIXELS:
                        raise ValueError("decoded image exceeds limits")
                    image.load()
    except (UnidentifiedImageError, OSError, EOFError, Image.DecompressionBombError) as exc:
        raise ValueError("invalid blog image") from exc
    finally:
        file_obj.seek(0)
    return expected_format, content_type


def sha256_file(file_obj) -> str:
    digest = hashlib.sha256()
    file_obj.seek(0)
    for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
        digest.update(chunk)
    file_obj.seek(0)
    return digest.hexdigest()
