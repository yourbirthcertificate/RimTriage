"""Design tokens, stylesheet and drawn icons. Colors are tokens; widgets never hard-code hex."""
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

DARK = dict(bg="#101216", surface="#171a20", surface2="#1e222a", surface3="#262b35", border="#2d333f",
            text="#e9ebef", muted="#9aa2b0", accent="#f2a93b", accent_text="#1b1305", accent_hover="#f7bd66",
            danger="#f27c7c", warn="#ebb64f", ok="#66cc94", info="#72aaff", sel="#2a3446", focus="#72aaff",
            nav="#0c0e12")
LIGHT = dict(bg="#f2f3f6", surface="#ffffff", surface2="#eceef3", surface3="#e1e5ec", border="#cfd4de",
             text="#1a1d23", muted="#566070", accent="#a65f00", accent_text="#ffffff", accent_hover="#8d5100",
             danger="#b3321f", warn="#8f5a00", ok="#17784a", info="#1a5cc0", sel="#d9e5f8", focus="#1a5cc0",
             nav="#e6e9f0")
KIND_COLOR = {"missing": "danger", "conflict": "danger", "unavailable": "danger", "enable": "info", "outdated": "warn",
              "rule": "warn", "dropped": "warn", "unverified": "warn", "skipped": "muted", "on": "ok", "off": "muted", "focus": "accent"}


def tokens(name):
    return DARK if name == "dark" else LIGHT


cur = dict(DARK)  # tokens of the active theme, read by delegates and custom-painted widgets


def use(name):
    cur.clear()
    cur.update(tokens(name))


def alpha(color, a):
    c = QColor(color)
    c.setAlphaF(a)
    return c


# ------------------------------------------------------------------ icons
def _poly(p, pts, close=False, fill=False):
    poly = QPolygonF([QPointF(x, y) for x, y in pts])
    if fill or close:
        p.drawPolygon(poly)
    else:
        p.drawPolyline(poly)


def _draw(name, p, c):
    line = lambda a, b, c_, d: p.drawLine(QPointF(a, b), QPointF(c_, d))  # noqa
    circ = lambda x, y, r: p.drawEllipse(QPointF(x, y), r, r)  # noqa
    if name == "mods":
        for x, y in ((4, 4), (13, 4), (4, 13), (13, 13)):
            p.drawRoundedRect(QRectF(x, y, 7, 7), 1.8, 1.8)
    elif name == "order":
        for y in (6, 12, 18):
            line(9, y, 20, y)
            circ(4.8, y, 1.1)
    elif name == "deps":
        circ(5, 12, 2.5)
        circ(19, 6, 2.5)
        circ(19, 18, 2.5)
        line(7.3, 11, 16.7, 7)
        line(7.3, 13, 16.7, 17)
    elif name == "problems":
        _poly(p, [(12, 4), (21, 20), (3, 20)], close=True)
        line(12, 10, 12, 14)
        p.drawPoint(QPointF(12, 17))
    elif name == "profiles":
        _poly(p, [(12, 4), (21, 9), (12, 14), (3, 9)], close=True)
        _poly(p, [(3, 13), (12, 18), (21, 13)])
    elif name == "search":
        circ(11, 11, 6)
        line(15.5, 15.5, 20, 20)
    elif name in ("undo", "redo"):
        if name == "redo":
            p.translate(24, 0)
            p.scale(-1, 1)
        path = QPainterPath(QPointF(4, 9))
        path.lineTo(14, 9)
        path.cubicTo(18, 9, 20, 11, 20, 14)
        path.cubicTo(20, 17, 18, 19, 14, 19)
        path.lineTo(8, 19)
        p.drawPath(path)
        _poly(p, [(8, 5), (4, 9), (8, 13)])
    elif name == "play":
        _poly(p, [(8, 5), (19, 12), (8, 19)], fill=True)
    elif name == "sliders":
        for y, x in ((7, 8), (12, 15), (17, 10)):
            line(4, y, 20, y)
            p.save()
            p.setBrush(c)
            circ(x, y, 2.4)
            p.restore()
    elif name == "sun":
        circ(12, 12, 4)
        for a in range(8):
            p.save()
            p.translate(12, 12)
            p.rotate(a * 45)
            line(0, -7.5, 0, -9.5)
            p.restore()
    elif name == "moon":
        path = QPainterPath()
        path.addEllipse(QPointF(11, 12), 8, 8)
        cut = QPainterPath()
        cut.addEllipse(QPointF(16, 9), 7, 7)
        p.setBrush(c)
        p.drawPath(path.subtracted(cut))
    elif name == "panel":
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 2.5, 2.5)
        line(15, 4, 15, 20)
    elif name == "tag":
        _poly(p, [(3, 4), (12, 4), (21, 13), (13, 21), (3, 11)], close=True)
        circ(7.5, 8.5, 1.3)
    elif name == "folder":
        _poly(p, [(3, 7), (3, 19), (21, 19), (21, 9), (11, 9), (9, 6), (3, 6)], close=True)
    elif name == "link":
        p.drawRoundedRect(QRectF(4, 8, 12, 12), 2, 2)
        _poly(p, [(14, 4), (20, 4), (20, 10)])
        line(12, 12, 20, 4)
    elif name == "up":
        line(12, 19, 12, 5)
        _poly(p, [(6, 11), (12, 5), (18, 11)])
    elif name == "down":
        line(12, 5, 12, 19)
        _poly(p, [(6, 13), (12, 19), (18, 13)])
    elif name == "top":
        line(5, 4, 19, 4)
        line(12, 20, 12, 8)
        _poly(p, [(6, 13), (12, 7), (18, 13)])
    elif name == "bottom":
        line(5, 20, 19, 20)
        line(12, 4, 12, 16)
        _poly(p, [(6, 11), (12, 17), (18, 11)])
    elif name == "check":
        _poly(p, [(5, 12.5), (10, 17), (19, 7)])
    elif name == "plus":
        line(12, 5, 12, 19)
        line(5, 12, 19, 12)
    elif name == "trash":
        line(4, 7, 20, 7)
        _poly(p, [(6, 7), (7, 20), (17, 20), (18, 7)])
        _poly(p, [(9, 7), (9, 4), (15, 4), (15, 7)])
    elif name == "save":
        _poly(p, [(4, 4), (17, 4), (20, 7), (20, 20), (4, 20)], close=True)
        _poly(p, [(8, 4), (8, 9), (15, 9), (15, 4)])
        p.drawRect(QRectF(7, 14, 10, 6))
    elif name == "download":
        line(12, 4, 12, 15)
        _poly(p, [(6, 10), (12, 16), (18, 10)])
        line(5, 20, 19, 20)
    elif name == "upload":
        line(12, 16, 12, 5)
        _poly(p, [(6, 10), (12, 4), (18, 10)])
        line(5, 20, 19, 20)
    elif name == "wand":
        _poly(p, [(12, 3), (14, 10), (21, 12), (14, 14), (12, 21), (10, 14), (3, 12), (10, 10)], close=True)
    elif name == "shield":
        path = QPainterPath(QPointF(12, 3))
        path.lineTo(20, 6)
        path.lineTo(20, 12)
        path.cubicTo(20, 17, 16, 20, 12, 21)
        path.cubicTo(8, 20, 4, 17, 4, 12)
        path.lineTo(4, 6)
        path.closeSubpath()
        p.drawPath(path)
        _poly(p, [(8.5, 12), (11, 14.5), (15.5, 9.5)])
    elif name == "target":
        circ(12, 12, 6)
        circ(12, 12, 1.2)
        for a, b, c_, d in ((12, 2, 12, 5), (12, 19, 12, 22), (2, 12, 5, 12), (19, 12, 22, 12)):
            line(a, b, c_, d)
    elif name == "refresh":
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 4, 16, 16), 40)
        path.arcTo(QRectF(4, 4, 16, 16), 40, 280)
        p.drawPath(path)
        _poly(p, [(16, 2.5), (18.5, 6.5), (14, 8)])
    elif name == "pulse":
        _poly(p, [(3, 12), (8, 12), (10, 6), (14, 18), (16, 12), (21, 12)])
    elif name == "chev_right":
        _poly(p, [(9, 6), (15, 12), (9, 18)])
    elif name == "chev_down":
        _poly(p, [(6, 9), (12, 15), (18, 9)])
    elif name == "close":
        line(6, 6, 18, 18)
        line(18, 6, 6, 18)
    elif name == "pin":
        _poly(p, [(8, 4), (16, 4), (15, 11), (18, 14), (6, 14), (9, 11)], close=True)
        line(12, 14, 12, 21)
    else:  # unknown: a dot
        circ(12, 12, 3)


_ICON_CACHE = {}


def pixmap(name, color, size=20, dpr=2.0):
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    col = QColor(color)
    pen = QPen(col, 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if name in ("play", "wand", "moon"):
        p.setBrush(col)
    _draw(name, p, col)
    p.end()
    return px


def icon(name, color, size=20):
    key = (name, color, size)
    if key not in _ICON_CACHE:
        _ICON_CACHE[key] = QIcon(pixmap(name, color, size))
    return _ICON_CACHE[key]


# ------------------------------------------------------------- stylesheet
def _asset_dir(theme):
    d = Path(tempfile.gettempdir()) / "rimworld_mod_applier_assets" / theme
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_assets(theme, t):
    d = _asset_dir(theme)
    out = {}

    def save(name, px):
        f = d / (name + ".png")
        px.save(str(f))
        out[name] = f.as_posix()

    for n, col in (("chev_right", t["muted"]), ("chev_down", t["muted"])):
        save(n, pixmap(n, col, 16, 1.0))
    # checkbox indicators, drawn at 16px
    for n, state in (("check_off", 0), ("check_on", 1), ("check_part", 2)):
        px = QPixmap(32, 32)
        px.setDevicePixelRatio(2.0)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, 14, 14)
        if state == 0:
            p.setPen(QPen(QColor(t["muted"]), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 3.5, 3.5)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["accent"]))
            p.drawRoundedRect(r, 3.5, 3.5)
            p.setPen(QPen(QColor(t["accent_text"]), 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if state == 1:
                p.drawPolyline(QPolygonF([QPointF(4.3, 8.3), QPointF(7, 11), QPointF(11.8, 5.2)]))
            else:
                p.drawLine(QPointF(4.5, 8), QPointF(11.5, 8))
        p.end()
        save(n, px)
    return out


def qss(theme, density="comfortable", font_pt=10):
    t = tokens(theme)
    a = _make_assets(theme, t)
    row = 30 if density == "comfortable" else 24
    return """
* { font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: %(pt)dpt; outline: 0; }
QMainWindow, QDialog { background: %(bg)s; }
QWidget { color: %(text)s; }
QWidget#central, QStackedWidget, QSplitter { background: %(bg)s; }
QLabel { background: transparent; }
QLabel[role="muted"] { color: %(muted)s; }
QLabel[role="h1"] { font-size: 15pt; font-weight: 600; }
QLabel[role="h2"] { font-size: 11.5pt; font-weight: 600; }
QLabel[role="caption"] { color: %(muted)s; font-size: 9pt; }
QLabel[role="danger"] { color: %(danger)s; font-weight: 600; }
QFrame#nav { background: %(nav)s; border-right: 1px solid %(border)s; }
QFrame#card, QFrame#inspector { background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px; }
QFrame#inspector { border-radius: 0; border: none; border-left: 1px solid %(border)s; }
QFrame#bottom { background: %(surface)s; border-top: 1px solid %(border)s; }
QFrame#toolbar { background: transparent; }
QToolButton#navbtn { background: transparent; color: %(muted)s; border: none; border-radius: 10px;
    padding: 8px 2px 6px 2px; margin: 2px 8px; font-size: 8.5pt; }
QToolButton#navbtn:hover { background: %(surface2)s; color: %(text)s; }
QToolButton#navbtn:checked { background: %(surface3)s; color: %(accent)s; font-weight: 600; }
QToolButton:focus, QPushButton:focus { border: 1px solid %(focus)s; }
QToolButton[flat="true"], QToolButton#tb { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 5px 8px; }
QToolButton#tb:hover { background: %(surface3)s; }
QToolButton#tb:pressed { background: %(sel)s; }
QToolButton#tb:disabled { color: %(muted)s; }
QToolButton#tb::menu-indicator { image: none; width: 0; }
QPushButton { background: %(surface3)s; border: 1px solid %(border)s; border-radius: 8px; padding: 6px 14px; min-height: 20px; }
QPushButton:hover { border-color: %(muted)s; }
QPushButton:pressed { background: %(sel)s; }
QPushButton:disabled { color: %(muted)s; background: %(surface2)s; }
QPushButton[primary="true"] { background: %(accent)s; color: %(accent_text)s; border: 1px solid %(accent)s; font-weight: 600; padding: 8px 20px; }
QPushButton[primary="true"]:hover { background: %(accent_hover)s; border-color: %(accent_hover)s; }
QPushButton[ghost="true"] { background: transparent; }
QPushButton[ghost="true"]:hover { background: %(surface3)s; }
QPushButton[chip="true"] { border-radius: 14px; padding: 3px 12px; background: transparent; color: %(muted)s; min-height: 18px; }
QPushButton[chip="true"]:checked { background: %(sel)s; color: %(text)s; border-color: %(sel)s; font-weight: 600; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox { background: %(surface2)s; border: 1px solid %(border)s;
    border-radius: 8px; padding: 6px 10px; selection-background-color: %(accent)s; selection-color: %(accent_text)s; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border: 1px solid %(focus)s; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url(%(chev_down)s); width: 14px; height: 14px; }
QComboBox QAbstractItemView, QMenu { background: %(surface2)s; border: 1px solid %(border)s; border-radius: 8px; padding: 4px;
    selection-background-color: %(sel)s; selection-color: %(text)s; }
QMenu::item { padding: 6px 22px 6px 12px; border-radius: 6px; }
QMenu::item:selected { background: %(sel)s; }
QMenu::item:disabled { color: %(muted)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 6px; }
QTableView, QTreeView, QListView, QListWidget, QTreeWidget { background: %(surface)s; alternate-background-color: %(surface)s;
    border: 1px solid %(border)s; border-radius: 10px; gridline-color: transparent; selection-background-color: %(sel)s;
    selection-color: %(text)s; show-decoration-selected: 1; }
QTableView::item, QTreeView::item, QListView::item { padding: 0 6px; border: none; min-height: %(row)dpx; }
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover { background: %(surface2)s; }
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected { background: %(sel)s; color: %(text)s; }
QTableView::indicator, QTreeView::indicator, QListView::indicator { width: 16px; height: 16px; }
QTableView::indicator:unchecked, QTreeView::indicator:unchecked, QListView::indicator:unchecked { image: url(%(check_off)s); }
QTableView::indicator:checked, QTreeView::indicator:checked, QListView::indicator:checked { image: url(%(check_on)s); }
QTableView::indicator:indeterminate { image: url(%(check_part)s); }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { image: url(%(check_off)s); }
QCheckBox::indicator:checked { image: url(%(check_on)s); }
QCheckBox { spacing: 8px; }
QTreeView::branch:has-children:closed { image: url(%(chev_right)s); }
QTreeView::branch:has-children:open { image: url(%(chev_down)s); }
QHeaderView { background: transparent; }
QHeaderView::section { background: %(surface)s; color: %(muted)s; border: none; border-bottom: 1px solid %(border)s;
    padding: 7px 8px; font-weight: 600; font-size: 9pt; }
QHeaderView::section:hover { color: %(text)s; }
QTableCornerButton::section { background: %(surface)s; border: none; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle { background: %(surface3)s; border-radius: 4px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: %(muted)s; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none; height: 0; width: 0; }
QTabWidget::pane { border: none; border-top: 1px solid %(border)s; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: %(muted)s; padding: 8px 14px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: %(text)s; }
QTabBar::tab:selected { color: %(text)s; border-bottom: 2px solid %(accent)s; font-weight: 600; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 6px; }
QSplitter::handle:vertical { height: 6px; }
QToolTip { background: %(surface3)s; color: %(text)s; border: 1px solid %(border)s; padding: 5px 8px; border-radius: 6px; }
QMessageBox { background: %(surface)s; }
QProgressBar { background: %(surface3)s; border: none; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: %(accent)s; border-radius: 4px; }
QLabel#toast { background: %(surface3)s; border: 1px solid %(border)s; border-radius: 10px; padding: 10px 16px; }
QGraphicsView { background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px; }
""" % dict(t, row=row, pt=font_pt, **a)
