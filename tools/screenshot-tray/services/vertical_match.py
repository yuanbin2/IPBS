"""Conservative two-dimensional matching for vertical screenshot capture."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter

from app.constants import (MSG_STITCH_LIMIT_FRAMES, MSG_STITCH_LIMIT_HEIGHT,
                           MSG_STITCH_LIMIT_PIXELS, MSG_STITCH_NO_OVERLAP)

_LOG = logging.getLogger("tray.stitcher")
MAX_FRAMES, MAX_TOTAL_HEIGHT, MAX_TOTAL_PIXELS = 30, 30000, 20_000_000
REASON_NO_OVERLAP = "no_overlap"
REASON_LIMIT_FRAMES = "limit_frames"
REASON_LIMIT_HEIGHT = "limit_height"
REASON_LIMIT_PIXELS = "limit_pixels"


class StitchError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason, self.message = reason, message


def is_limit_reason(reason: str) -> bool:
    return reason in {REASON_LIMIT_FRAMES, REASON_LIMIT_HEIGHT, REASON_LIMIT_PIXELS}


def pixels(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    raw = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), dtype=np.uint8)
    return raw.reshape(image.height(), image.bytesPerLine())[:, :image.width()*3].reshape(image.height(), image.width(), 3).copy()


def downsample(image: QImage) -> QImage:
    return image.scaled(max(1, image.width()//4), max(1, image.height()//4),
                        Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)


def mean_abs_diff(a: QImage, b: QImage) -> float:
    if a.isNull() or b.isNull() or a.size() != b.size():
        return 255.0
    x, y = pixels(a)[::4, ::4].astype(np.int16), pixels(b)[::4, ::4].astype(np.int16)
    return float(np.abs(x-y).mean())


def features(a: np.ndarray) -> np.ndarray:
    h, w, _ = a.shape
    s = a[:, ::max(1, w//480)].astype(np.float32)
    edge = np.abs(np.diff(s, axis=0, prepend=s[:1])).mean(axis=2)
    zones = np.array_split(np.arange(s.shape[1]), min(12, s.shape[1]))
    return np.concatenate([np.concatenate((s[:, z].mean(axis=1), edge[:, z].mean(axis=1)[:, None]), axis=1)
                           for z in zones], axis=1)


def stationary(a: np.ndarray, b: np.ndarray) -> tuple[int, int, bool]:
    h, w, _ = a.shape
    d = np.abs(a[::2].astype(np.int16)-b[::2].astype(np.int16)).mean(axis=2)
    row = d.mean(axis=1)
    top = bottom = 0
    for value in row[:min(64, len(row)//4)]:
        if value > 2.5: break
        top += 2
    for value in row[-min(48, len(row)//5):][::-1]:
        if value > 2.5: break
        bottom += 2
    if top and float(a[:top].std()) < 4:
        top = 0
    if bottom and float(a[-bottom:].std()) < 4:
        bottom = 0
    col = d.mean(axis=0)
    rail_w = min(w//4, 160)
    # A fixed rail starts at the viewport edge.  Counting all quiet columns
    # misses narrow rails and may mistake scattered whitespace for a sidebar.
    left = next((i for i, v in enumerate(col[:rail_w]) if v >= 2.5), rail_w)
    right = next((i for i, v in enumerate(col[-rail_w:][::-1]) if v >= 2.5), rail_w)
    textured_left = bool(left) and float(a[:, :left].std()) > 8
    textured_right = bool(right) and float(a[:, w-right:].std()) > 8
    min_rail = max(12, int(w * .04))
    rail = (left >= min_rail and textured_left) or (right >= min_rail and textured_right)
    return min(top, 128), min(bottom, 96), rail


def verify(a: np.ndarray, b: np.ndarray, shift: int, top: int, footer: int) -> tuple[float, float]:
    h = a.shape[0]
    end = h-shift-footer
    if end-top < 32:
        return 255.0, 0.0
    old = a[shift+top:shift+end:3, ::3].astype(np.int16)
    new = b[top:end:3, ::3].astype(np.int16)
    delta = np.abs(old-new).mean(axis=2)
    zones = np.array_split(np.arange(delta.shape[1]), min(16, delta.shape[1]))
    scores = np.array([float(delta[:, z].mean()) for z in zones])
    background = np.median(np.concatenate((old[::4], new[::4]), axis=0).reshape(-1, 3), axis=0)
    informative = np.array([
        max(float(old[:, z].std()), float(new[:, z].std()),
            float(np.abs(old[:, z].mean(axis=(0, 1))-background).mean()),
            float(np.abs(new[:, z].mean(axis=(0, 1))-background).mean())) > 8
        for z in zones])
    good = scores < 18
    coverage = float(good.mean())
    evidence = int((good & informative).sum())
    if (coverage < .875 or evidence < max(3, (len(zones)+4)//5) or
            evidence < .75 * int(informative.sum())):
        return 255.0, coverage
    return float(scores[good & informative].mean()), coverage


@dataclass
class Match:
    shift: int
    score: float
    coverage: float
    footer: int


class Stitcher:
    def __init__(self) -> None:
        self._canvas: QImage | None = None
        self._anchor: QImage | None = None
        self._frames = 0
        self._footer = 0
        self.last_match: Match | None = None

    @property
    def frames(self) -> int: return self._frames

    def is_empty(self) -> bool: return self._canvas is None

    def canvas(self) -> QImage | None: return self._canvas

    def anchor(self) -> QImage | None: return self._anchor

    def result(self) -> QImage: return QImage(self._canvas) if self._canvas is not None else QImage()

    def reset(self) -> None: self.__init__()

    def append(self, frame: QImage) -> bool:
        if frame.isNull() or frame.width() <= 0 or frame.height() <= 0:
            raise StitchError(REASON_NO_OVERLAP, "抓取画面为空")
        image = frame.convertToFormat(QImage.Format.Format_ARGB32)
        image.setDevicePixelRatio(1)
        if image.height() > MAX_TOTAL_HEIGHT:
            raise StitchError(REASON_LIMIT_HEIGHT, MSG_STITCH_LIMIT_HEIGHT)
        if image.width()*image.height() > MAX_TOTAL_PIXELS:
            raise StitchError(REASON_LIMIT_PIXELS, MSG_STITCH_LIMIT_PIXELS)
        if self._canvas is None:
            self._canvas, self._anchor, self._frames = image, image, 1
            _LOG.info("拼接首帧 size=%dx%d DPR=1", image.width(), image.height())
            return True
        if self._frames >= MAX_FRAMES:
            raise StitchError(REASON_LIMIT_FRAMES, MSG_STITCH_LIMIT_FRAMES)
        if image.size() != self._anchor.size():
            raise StitchError(REASON_NO_OVERLAP, "抓取画面尺寸改变，请重新选区")
        if mean_abs_diff(image, self._anchor) <= 2:
            a = pixels(image)[::2, ::4].astype(np.int16)
            for period in range(8, min(160, image.height()//2)):
                if float(np.abs(a[period:]-a[:-period]).mean()) < 1:
                    raise StitchError(REASON_NO_OVERLAP, "页面内容周期重复，无法确定是否滚动；请缩小选区或避开重复表格")
            return False
        match = self._match(self._anchor, image)
        self.last_match = match
        if match.shift < 16:
            _LOG.info("微滚 shift=%d score=%.2f；保留成功原始帧锚点", match.shift, match.score)
            return False
        canvas = self._canvas
        base_h = canvas.height() - (match.footer if self._frames == 1 else 0)
        new_h = base_h + match.shift
        if new_h <= base_h: return False
        if new_h > MAX_TOTAL_HEIGHT:
            raise StitchError(REASON_LIMIT_HEIGHT, MSG_STITCH_LIMIT_HEIGHT)
        if new_h*image.width() > MAX_TOTAL_PIXELS:
            raise StitchError(REASON_LIMIT_PIXELS, MSG_STITCH_LIMIT_PIXELS)
        merged = QImage(image.width(), new_h, QImage.Format.Format_ARGB32)
        if merged.isNull():
            raise StitchError(REASON_LIMIT_PIXELS, "画布分配失败，已保留当前结果")
        merged.setDevicePixelRatio(1)
        merged.fill(Qt.GlobalColor.transparent)
        p = QPainter(merged)
        p.drawImage(0, 0, canvas, 0, 0, image.width(), base_h)
        p.drawImage(0, base_h, image, 0, image.height()-match.footer-match.shift,
                    image.width(), match.shift)
        p.end()
        self._canvas, self._anchor, self._frames, self._footer = merged, image, self._frames+1, match.footer
        _LOG.info("帧=%d shift=%d overlap=%d score=%.2f coverage=%.2f queue=worker total=%d",
                  self._frames, match.shift, image.height()-match.shift, match.score, match.coverage, new_h)
        return True

    def _match(self, anchor: QImage, frame: QImage) -> Match:
        a, b = pixels(anchor), pixels(frame)
        h, _, _ = a.shape
        top, footer, rail = stationary(a, b)
        if rail:
            raise StitchError(REASON_NO_OVERLAP, "选区含固定侧栏，请避开侧栏重试")
        fa, fb = features(a), features(b)
        coarse = []
        for shift in range(h-31):
            end = h-shift-footer
            if end-top < 32: continue
            coarse.append((float(np.abs(fa[shift+top:shift+end:3]-fb[top:end:3]).mean()), shift))
        coarse.sort()
        candidates = {0, 1, 2, 3, 4, 8, 12, 16}
        for _, shift in coarse[:24]:
            candidates.update(range(max(0, shift-3), min(h-32, shift+3)+1))
        verified = []
        for shift in candidates:
            if shift > h-32: continue
            score, coverage = verify(a, b, shift, top, footer)
            if coverage >= .875: verified.append((score, shift, coverage))
        verified.sort()
        if not verified or verified[0][0] > 12:
            # Check the reverse direction with its own full-height candidates.
            reverse_coarse = []
            for shift in range(16, h-31):
                end = h-shift-footer
                if end-top < 32: continue
                reverse_coarse.append((float(np.abs(fb[shift+top:shift+end:3]-fa[top:end:3]).mean()), shift))
            reverse_coarse.sort()
            reverse = [(s,c) for _, shift in reverse_coarse[:12]
                       for s,c in [verify(b, a, shift, top, footer)] if s < 8 and c >= .875]
            hint = "检测到向上滚动，请向下滚回上一帧附近" if reverse else MSG_STITCH_NO_OVERLAP
            if not reverse:
                # A horizontal drift can share row features with the true seam.
                # Detect it explicitly, but never use it to append a vertical strip.
                for _, shift in coarse[:8]:
                    end = h-shift-footer
                    if end-top < 32: continue
                    x = a[shift+top:shift+end:4].astype(np.int16)
                    y = b[top:end:4].astype(np.int16)
                    for dx in range(-24, 25):
                        if dx == 0: continue
                        if dx > 0:
                            left, right = x[:, dx::4], y[:, :-dx:4]
                        else:
                            left, right = x[:, :dx:4], y[:, -dx::4]
                        n = min(left.shape[1], right.shape[1])
                        if n and float(np.abs(left[:, :n]-right[:, :n]).mean()) < 8:
                            hint = "检测到水平偏移，请固定页面横向位置后重试"
                            break
                    if hint.startswith("检测到水平"): break
            _LOG.warning("拒绝 no_overlap coarse=%s verified=%s top=%d footer=%d", coarse[:3], verified[:3], top, footer)
            raise StitchError(REASON_NO_OVERLAP, hint)
        score, shift, coverage = verified[0]
        alternatives = [(s,d) for s,d,_ in verified if abs(d-shift)>4 and s<score+2]
        if alternatives:
            _LOG.warning("拒绝 ambiguous shift=%d score=%.2f alternatives=%s", shift, score, alternatives[:3])
            raise StitchError(REASON_NO_OVERLAP, "页面内容重复，接缝位置不唯一；请缩小步长")
        if shift and float(a[shift+top:h-footer:4, ::4].std()) < 3:
            raise StitchError(REASON_NO_OVERLAP, "重叠区域缺少可识别内容，请滚回有文字的位置")
        return Match(shift, score, coverage, footer)
