#!/usr/bin/env python3
"""Generate icon.png (512 px) + multi-size icon.ico: a film-strip tile with a name tag."""
import sys
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#6b46c1"))
    g.setColorAt(1, QColor("#322659"))
    p.setBrush(QBrush(g))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.2, size * 0.2)
    # film strip: two rows of holes
    p.setBrush(QColor(255, 255, 255, 230))
    hole = size * 0.07
    for i in range(4):
        x = size * 0.16 + i * size * 0.19
        p.drawRoundedRect(QRectF(x, size * 0.16, hole, hole), hole * 0.25, hole * 0.25)
        p.drawRoundedRect(QRectF(x, size * 0.77, hole, hole), hole * 0.25, hole * 0.25)
    # name tag: a white bar with a bold line of "text"
    p.drawRoundedRect(QRectF(size * 0.16, size * 0.36, size * 0.68, size * 0.28), size * 0.05, size * 0.05)
    pen = QPen(QColor("#322659"))
    pen.setWidthF(max(1.0, size * 0.055))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    y = size * 0.50
    p.drawLine(size * 0.24, y, size * 0.44, y)
    p.drawLine(size * 0.50, y, size * 0.60, y)
    p.drawLine(size * 0.66, y, size * 0.76, y)
    p.end()
    return img


if __name__ == "__main__":
    QApplication(sys.argv)
    draw(512).save("icon.png")
    from PIL import Image
    Image.open("icon.png").save("icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("icon.png + icon.ico written")
