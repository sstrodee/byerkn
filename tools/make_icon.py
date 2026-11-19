"""Generate the byerkn taskbar, window and tray artwork from Instrument Serif."""

import math
from pathlib import Path
import random
import struct

from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase,
                           QGuiApplication, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen)

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def superellipse():
    # Same proportions as the helloytd artwork: exponent 5 and a 3% margin.
    path = QPainterPath()
    for index in range(721):
        angle = math.tau * index / 720
        x, y = math.cos(angle), math.sin(angle)
        point = QPointF(50 + 47 * math.copysign(abs(x) ** 0.4, x),
                        50 + 47 * math.copysign(abs(y) ** 0.4, y))
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


def draw_stone(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 100, size / 100)
    path = superellipse()
    material = QLinearGradient(36, 2, 64, 98)
    for position, color in ((0, '#48484a'), (0.5, '#373739'), (1, '#28282b')):
        material.setColorAt(position, QColor(color))
    painter.fillPath(path, material)
    painter.setClipPath(path)

    grains = random.Random(41)
    for _ in range(9500):
        luminance = grains.choice((0, 255))
        painter.setPen(QPen(QColor(luminance, luminance, luminance, grains.randint(2, 10)), 0.25))
        painter.drawPoint(QPointF(grains.uniform(2, 98), grains.uniform(2, 98)))

    rim = QLinearGradient(10, 4, 90, 98)
    rim.setColorAt(0, QColor(255, 255, 255, 35))
    rim.setColorAt(1, QColor(255, 255, 255, 10))
    painter.setPen(QPen(rim, 1.5))
    painter.drawPath(path)
    painter.end()
    return image


def draw_wordmark(stone, size):
    image = stone.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    font = QFont('Instrument Serif')
    font.setPixelSize(100)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    scale = size / 100
    glyphs = QPainterPath()
    glyphs.addText(QPointF(0, 0), font, 'Bye')
    bounds = glyphs.boundingRect()
    width = 68 if size <= 20 else 63 if size <= 32 else 60

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    # Centre the actual ink. The long descender on y carries little visual weight.
    painter.translate(50, 51)
    painter.scale(width / bounds.width(), width / bounds.width())
    painter.translate(-bounds.center())
    white = QColor('#e7e6e2')
    if size <= 32:
        painter.strokePath(glyphs, QPen(white, 0.20 * bounds.width() / (width * scale), Qt.PenStyle.SolidLine,
                                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.fillPath(glyphs, white)
    painter.end()
    return image


def write_icon():
    font_id = QFontDatabase.addApplicationFont(str(ASSETS / 'fonts/InstrumentSerif-Regular.ttf'))
    if font_id < 0:
        raise RuntimeError('Instrument Serif could not be loaded')
    stone = draw_stone(1024)
    if not draw_wordmark(stone, 512).save(str(ASSETS / 'icon.png')):
        raise RuntimeError('Could not save icon.png')
    entries, images = bytearray(), bytearray()
    offset = 6 + 16 * len(SIZES)
    for size in SIZES:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not draw_wordmark(stone, size).save(buffer, 'PNG'):
            raise RuntimeError(f'Could not encode the {size}px icon')
        frame = bytes(buffer.data())
        side = size % 256
        entries.extend(struct.pack('<BBBBHHII', side, side, 0, 0, 1, 32, len(frame), offset + len(images)))
        images.extend(frame)
    (ASSETS / 'icon.ico').write_bytes(struct.pack('<HHH', 0, 1, len(SIZES)) + entries + images)


if __name__ == '__main__':
    app = QGuiApplication([])
    write_icon()
