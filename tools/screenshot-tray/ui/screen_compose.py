"""Compose screen captures using one logical-to-output-pixel coordinate system.

Inputs cover whole QScreen geometries.  QImage dimensions are physical pixels;
the returned processing image always has DPR 1.  Shared logical boundaries are
rounded once in the output space, so adjacent monitors cannot leave a seam.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage, QPainter, QRegion


@dataclass(frozen=True)
class ScreenCapture:
    geometry: QRect  # global logical coordinates
    image: QImage     # physical pixels of the whole screen
    dpr: float


def compose_selection(selection: QRect, captures: list[ScreenCapture], output_dpr: float) -> QImage | None:
    if selection.isEmpty() or not math.isfinite(output_dpr) or output_dpr <= 0:
        return None
    width = round(selection.width() * output_dpr)
    height = round(selection.height() * output_dpr)
    if width <= 0 or height <= 0 or width * height > 100_000_000:
        return None
    output = QImage(width, height, QImage.Format.Format_ARGB32)
    if output.isNull():
        return None
    output.setDevicePixelRatio(1)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    painted = False
    remaining = QRegion(selection)
    for capture in captures:
        geometry, source, dpr = capture.geometry, capture.image, capture.dpr
        part = selection.intersected(geometry)
        if part.isEmpty():
            continue
        if source.isNull() or geometry.isEmpty() or not math.isfinite(dpr) or dpr <= 0:
            painter.end()
            return None
        if abs(source.width() - round(geometry.width() * dpr)) > 2 or abs(source.height() - round(geometry.height() * dpr)) > 2:
            painter.end()
            return None
        # Round edges, never rounded widths: a shared edge has one pixel address.
        sx0 = round((part.left() - geometry.left()) * dpr)
        sy0 = round((part.top() - geometry.top()) * dpr)
        sx1 = round((part.left() + part.width() - geometry.left()) * dpr)
        sy1 = round((part.top() + part.height() - geometry.top()) * dpr)
        tx0 = round((part.left() - selection.left()) * output_dpr)
        ty0 = round((part.top() - selection.top()) * output_dpr)
        tx1 = round((part.left() + part.width() - selection.left()) * output_dpr)
        ty1 = round((part.top() + part.height() - selection.top()) * output_dpr)
        if sx0 < 0 or sy0 < 0 or sx1 > source.width() or sy1 > source.height() or sx1 <= sx0 or sy1 <= sy0:
            painter.end()
            return None
        piece = source.copy(sx0, sy0, sx1 - sx0, sy1 - sy0)
        if piece.isNull():
            painter.end()
            return None
        piece.setDevicePixelRatio(1)
        target_w, target_h = tx1 - tx0, ty1 - ty0
        if target_w <= 0 or target_h <= 0:
            painter.end()
            return None
        if piece.width() != target_w or piece.height() != target_h:
            piece = piece.scaled(target_w, target_h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            if piece.isNull():
                painter.end()
                return None
            piece.setDevicePixelRatio(1)
        painter.drawImage(tx0, ty0, piece)
        painted = True
        remaining = remaining.subtracted(QRegion(part))
    painter.end()
    return output if painted and remaining.isEmpty() else None
