"""The app's icon, drawn in code so it stays sharp at every size.

An original mark: a compact disc that doubles as a world seen from orbit. The amber outer rim is the 'rim',
the horizon is the planet's limb, and the dot on the edge is a satellite."""
import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (QColor, QConicalGradient, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)

SIZES = (16, 24, 32, 48, 64, 128, 256)


def paint_icon(p, S):
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    c = QPointF(S / 2.0, S / 2.0)
    R = S * 0.47
    small = S < 40
    p.setPen(Qt.NoPen)
    # amber rim
    g = QLinearGradient(c.x() - R, c.y() - R, c.x() + R, c.y() + R)
    g.setColorAt(0.0, QColor("#ffd98a"))
    g.setColorAt(0.5, QColor("#f2a93b"))
    g.setColorAt(1.0, QColor("#a35d08"))
    p.setBrush(g)
    p.drawEllipse(c, R, R)
    # dark disc body
    Rb = R * (0.8 if small else 0.9)   # a thicker rim reads better when the icon is tiny
    rg = QRadialGradient(c, Rb)
    rg.setColorAt(0.0, QColor("#343c4b"))
    rg.setColorAt(1.0, QColor("#0d0f13"))
    p.setBrush(rg)
    p.drawEllipse(c, Rb, Rb)
    # everything on the data area is clipped to the ring between hub and rim
    area = QPainterPath()
    area.addEllipse(c, Rb * 0.985, Rb * 0.985)
    hubp = QPainterPath()
    hubp.addEllipse(c, R * 0.27, R * 0.27)
    p.save()
    p.setClipPath(area.subtracted(hubp))
    if not small:  # CD sheen and grooves
        cg = QConicalGradient(c, 30)
        for pos, col in ((0.00, (242, 169, 59, 0)), (0.07, (242, 169, 59, 140)), (0.15, (242, 169, 59, 0)),
                         (0.50, (120, 200, 230, 0)), (0.57, (120, 200, 230, 115)), (0.65, (120, 200, 230, 0)), (1.0, (242, 169, 59, 0))):
            cg.setColorAt(pos, QColor(*col))
        p.setBrush(cg)
        p.drawEllipse(c, Rb, Rb)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 26), max(1.0, S * 0.0045)))
        for k in (0.42, 0.54, 0.66, 0.78):
            p.drawEllipse(c, R * k, R * k)
    # planet limb: a bigger circle rising from the lower right, glowing along its edge
    limb = QPainterPath()
    limb.addEllipse(QPointF(c.x() + R * 0.5, c.y() + R * 1.42), R * 1.2, R * 1.2)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(242, 169, 59, 40))
    p.drawPath(limb)
    p.setBrush(Qt.NoBrush)
    if not small:
        p.setPen(QPen(QColor(242, 169, 59, 70), S * 0.07))
        p.drawPath(limb)
    p.setPen(QPen(QColor(255, 214, 130, 250), max(1.4, S * (0.06 if small else 0.032))))
    p.drawPath(limb)
    p.restore()
    # hub
    hg = QRadialGradient(c, R * 0.27)
    hg.setColorAt(0.0, QColor("#f6f8fb"))
    hg.setColorAt(1.0, QColor("#8f98a8"))
    p.setBrush(hg)
    p.setPen(QPen(QColor("#0d0f13"), max(0.8, S * 0.008)))
    p.drawEllipse(c, R * 0.27, R * 0.27)
    # centre hole (truly transparent)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.black)
    p.drawEllipse(c, R * 0.11, R * 0.11)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    # satellite on the rim
    a = math.radians(-44)
    sp = QPointF(c.x() + R * math.cos(a), c.y() + R * math.sin(a))
    p.setPen(Qt.NoPen)
    big_dot = 1.35 if small else 1.0
    p.setBrush(QColor("#0d0f13"))
    p.drawEllipse(sp, R * 0.15 * big_dot, R * 0.15 * big_dot)
    p.setBrush(QColor("#fff0c4"))
    p.drawEllipse(sp, R * 0.095 * big_dot, R * 0.095 * big_dot)


def make_image(size):
    """Transparent ARGB image of the icon. Small sizes are drawn larger and scaled down for clean edges."""
    ss = 4 if size < 128 else 2
    big = QImage(size * ss, size * ss, QImage.Format_ARGB32_Premultiplied)
    big.fill(Qt.transparent)
    p = QPainter(big)
    paint_icon(p, size * ss)
    p.end()
    return big.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def app_icon():
    icon = QIcon()
    for s in SIZES:
        icon.addPixmap(QPixmap.fromImage(make_image(s)))
    return icon
