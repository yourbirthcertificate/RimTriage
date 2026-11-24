"""Models, delegates and the dependency graph canvas."""
import time

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, QPointF, QRectF, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QApplication, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView, QStyle, QStyledItemDelegate, QStyleOptionViewItem)

from . import core, theme, tracker
from .core import CORE

SORT = Qt.UserRole + 1
FLAGS = Qt.UserRole + 2


def col(name, a=None):
    c = QColor(theme.cur[theme.KIND_COLOR.get(name, name)])
    if a is not None:
        c.setAlphaF(a)
    return c


# ------------------------------------------------------------------ mods table
class ModModel(QAbstractTableModel):
    COLS = ["", "Name", "Author", "Tags", "Up to", "Source", "Updated", "Status"]

    def __init__(self, state, selected_pids):
        super().__init__()
        self.st, self.selected_pids, self.pids = state, selected_pids, []
        state.reset.connect(self.on_reset)
        state.changed.connect(self.on_changed)

    def on_reset(self):
        self.beginResetModel()
        self.pids = sorted(self.st.mods, key=lambda p: self.st.mods[p].name.lower())
        self.endResetModel()

    def on_changed(self):
        if self.pids:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.pids) - 1, len(self.COLS) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.pids)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLS[section]
        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0 and self.pids[index.row()] != CORE:
            f |= Qt.ItemIsUserCheckable
        return f

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        p = self.pids[index.row()]
        m = self.st.mods.get(p)
        if m is None:
            return None
        c, on = index.column(), self.st.checked.get(p, False)
        if role == Qt.CheckStateRole and c == 0:
            return Qt.Checked if on else Qt.Unchecked
        if role == Qt.DisplayRole:
            ts = self.st.updated.get(p)
            return (None, m.name, m.author, ", ".join(self.st.tags.get(p, [])), core.max_version(m),
                    m.source.title(), tracker.fmt_date(ts) if ts else "", "")[c]
        if role == Qt.UserRole:
            return p
        if role == SORT:
            k = core.vkey(core.max_version(m)) or (0, 0)
            return (0 if on else 1, m.name.lower(), m.author.lower(), ", ".join(self.st.tags.get(p, [])).lower(),
                    k[0] * 100 + k[1], m.source, self.st.updated.get(p, 0), len(self.st.status.get(p, [])))[c]
        if role == FLAGS:
            return self.st.status.get(p, [])
        if role == Qt.ForegroundRole and not on:
            return QColor(theme.cur["muted"])
        if role == Qt.TextAlignmentRole and c in (0, 4):
            return int(Qt.AlignCenter)
        if role == Qt.ToolTipRole:
            if c == 7:
                return core.status_text(self.st.status.get(p, [])) or None
            return "%s\n%s" % (p, m.path)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.CheckStateRole or index.column() != 0:
            return False
        v = value.value if hasattr(value, "value") else int(value)
        p = self.pids[index.row()]
        sel = self.selected_pids()
        self.st.set_checked(sel if p in sel and len(sel) > 1 else [p], v == 2)
        return True


class ModProxy(QSortFilterProxyModel):
    def __init__(self, state):
        super().__init__()
        self.st, self.text, self.kind, self.tag = state, "", "all", ""
        self.setSortRole(SORT)
        self.setDynamicSortFilter(True)

    def set_filter(self, text=None, kind=None, tag=None):
        if text is not None:
            self.text = text.strip().lower()
        if kind is not None:
            self.kind = kind
        if tag is not None:
            self.tag = tag
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        p = self.sourceModel().pids[row]
        m = self.st.mods.get(p)
        if m is None:
            return False
        on, fl, tags = self.st.checked.get(p, False), self.st.status.get(p, []), self.st.tags.get(p, [])
        if self.text and not (self.text in m.name.lower() or self.text in p or self.text in m.author.lower()
                              or any(self.text in t.lower() for t in tags)):
            return False
        if self.tag and self.tag not in tags:
            return False
        k = self.kind
        if k == "updated":
            return self.st.updated.get(p, 0) >= time.time() - 7 * 86400
        return not ((k == "ticked" and not on) or (k == "unticked" and on) or (k == "problems" and not fl)
                    or (k == "unverified" and not any(f[0] == "unverified" for f in fl))
                    or (k == "outdated" and not any(f[0] == "outdated" for f in fl)))


def paint_chips(painter, rect, flags, x0=6):
    """Rounded status chips, tinted by kind. Text stays readable without the color."""
    if not flags:
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    f = painter.font()
    f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
    painter.setFont(f)
    fm = QFontMetrics(f)
    x, r = rect.left() + x0, rect.right() - 4
    h = fm.height() + 4
    y = rect.center().y() - h / 2
    for kind, text in flags:
        text = fm.elidedText(text, Qt.ElideRight, 260)
        w = fm.horizontalAdvance(text) + 16
        if x + w > r:
            break
        painter.setPen(Qt.NoPen)
        painter.setBrush(col(kind, 0.16))
        painter.drawRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
        painter.setPen(col(kind))
        painter.drawText(QRectF(x, y, w, h), Qt.AlignCenter, text)
        x += w + 6
    painter.restore()


class ChipDelegate(QStyledItemDelegate):
    """Draws a row of coloured status chips from the FLAGS role."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, option.widget)
        paint_chips(painter, option.rect, index.data(FLAGS) or [], 6)


# ------------------------------------------------------------------ order table
class OrderModel(QAbstractTableModel):
    COLS = ["#", "Name", "Group", "Why it's here"]
    MIME = "application/x-rma-rows"
    TIER_COLOR = ["accent", "accent", "accent", "info", "info", "text", "warn", "muted"]

    def __init__(self, state):
        super().__init__()
        self.st, self.rows, self.bad, self.bad_msg = state, [], set(), {}
        self.active, self.dirty = False, True
        state.orderChanged.connect(self.mark)
        state.reset.connect(self.mark)

    def mark(self):
        self.dirty = True
        if self.active:
            self.refresh()

    def refresh(self):
        self.beginResetModel()
        if self.st.mods:
            pl = self.st.plan()
            self.rows = pl.order
            self.bad, self.bad_msg = set(), {}
            for a, b, k in pl.violations:
                self.bad |= {a, b}
                self.bad_msg.setdefault(b, []).append("Should load after %s (%s)" % (self.st.mods[a].name, k))
                self.bad_msg.setdefault(a, []).append("Should load before %s (%s)" % (self.st.mods[b].name, k))
            self.why = pl.why
        else:
            self.rows, self.why = [], {}
        self.dirty = False
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        p, t = self.rows[index.row()]
        c = index.column()
        if role == Qt.DisplayRole:
            return (index.row() + 1, self.st.mods[p].name, core.TIER_NAMES[t], "; ".join(self.why.get(p, [])[:4]))[c]
        if role == Qt.UserRole:
            return p
        if role == Qt.ForegroundRole:
            if p in self.bad and c == 1:
                return QColor(theme.cur["danger"])
            if c == 2:
                return QColor(theme.cur[self.TIER_COLOR[t]])
            if c in (0, 3):
                return QColor(theme.cur["muted"])
        if role == Qt.TextAlignmentRole and c == 0:
            return int(Qt.AlignCenter)
        if role == Qt.ToolTipRole:
            return "\n".join(self.bad_msg.get(p, [])) or "; ".join(self.why.get(p, []))
        return None

    # drag and drop reordering
    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsDropEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled

    def supportedDropActions(self):
        return Qt.MoveAction

    def mimeTypes(self):
        return [self.MIME]

    def mimeData(self, indexes):
        md = QMimeData()
        rows = sorted({i.row() for i in indexes})
        md.setData(self.MIME, "\n".join(self.rows[r][0] for r in rows).encode())
        return md

    def dropMimeData(self, data, action, row, column, parent):
        if not data.hasFormat(self.MIME):
            return False
        pids = bytes(data.data(self.MIME)).decode().split("\n")
        dest = row if row >= 0 else (parent.row() if parent.isValid() else len(self.rows))
        self.st.move(pids, dest)
        return True


# ------------------------------------------------------------------ graph
class NodeItem(QGraphicsRectItem):
    W, H = 230, 46
    LABEL = {"on": "ticked", "off": "not ticked", "outdated": "outdated", "missing": "not installed",
             "unavailable": "needs something missing", "focus": "selected mod"}

    def __init__(self, key, info, click):
        super().__init__(0, 0, self.W, self.H)
        self.key, self.click = key, click if not str(key).startswith("missing:") else None
        st = info["state"]
        c = col(st)
        self.setPen(QPen(c, 2.4 if st == "focus" else 1.5, Qt.DashLine if st in ("missing", "unavailable") else Qt.SolidLine))
        self.setBrush(QColor(theme.cur["surface2"]))
        if self.click:
            self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(info["name"])
        fm = QFontMetrics(QApplication.font())
        t = QGraphicsSimpleTextItem(fm.elidedText(info["name"], Qt.ElideRight, self.W - 20), self)
        t.setBrush(QColor(theme.cur["text"]))
        t.setPos(10, 4)
        s = QGraphicsSimpleTextItem(self.LABEL.get(st, st), self)
        f = s.font()
        f.setPointSizeF(8)
        s.setFont(f)
        s.setBrush(c)
        s.setPos(10, 24)

    def mousePressEvent(self, e):
        if self.click:
            self.click(self.key)
        e.accept()


class DepGraphView(QGraphicsView):
    GAP_X, GAP_Y = 90, 18

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def set_graph(self, nodes, edges, click):
        sc = self.scene()
        sc.clear()
        if not nodes:
            return
        W, H = NodeItem.W, NodeItem.H
        cols = {}
        for k, n in nodes.items():
            cols.setdefault(n["level"], []).append(k)
        pos = {}
        for lvl, keys in cols.items():
            keys.sort(key=lambda k: nodes[k]["name"].lower())
            for i, k in enumerate(keys):
                y = (i - (len(keys) - 1) / 2) * (H + self.GAP_Y)
                if lvl == 0.0 and k not in ("", ) and nodes[k]["state"] != "focus":
                    y += H * 2.2  # conflicting mods sit below the focused one
                pos[k] = QPointF(lvl * (W + self.GAP_X), y)
        for k, n in nodes.items():
            if n["state"] == "focus":
                pos[k] = QPointF(0, 0)
        for src, dst, kind in edges:
            if src not in pos or dst not in pos:
                continue
            a, b = (dst, src) if kind == "needs" else (src, dst)  # arrows run from provider to consumer
            pa, pb = pos[a], pos[b]
            if kind == "conflict":
                p1, p2 = QPointF(pa.x() + W / 2, pa.y() + H), QPointF(pb.x() + W / 2, pb.y())
            elif pa.x() < pb.x():
                p1, p2 = QPointF(pa.x() + W, pa.y() + H / 2), QPointF(pb.x(), pb.y() + H / 2)
            else:
                p1, p2 = QPointF(pa.x(), pa.y() + H / 2), QPointF(pb.x() + W, pb.y() + H / 2)
            path = QPainterPath(p1)
            dx = (p2.x() - p1.x()) / 2
            path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
            color = {"needs": theme.cur["muted"], "conflict": theme.cur["danger"], "after": theme.cur["info"]}[kind]
            pen = QPen(QColor(color), 1.5, {"needs": Qt.SolidLine, "conflict": Qt.DashLine, "after": Qt.DotLine}[kind])
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(-1)
            sc.addItem(item)
            if kind != "conflict":  # arrow head
                ang = path.angleAtPercent(1.0)
                from math import cos, sin, radians
                r = radians(ang)
                tip = p2
                l = QPointF(cos(r + 2.6), -sin(r + 2.6))
                rr = QPointF(cos(r - 2.6), -sin(r - 2.6))
                head = QPolygonF([tip, tip + l * 9, tip + rr * 9])
                from PySide6.QtWidgets import QGraphicsPolygonItem
                h = QGraphicsPolygonItem(head)
                h.setBrush(QColor(color))
                h.setPen(Qt.NoPen)
                h.setZValue(-1)
                sc.addItem(h)
        for k, n in nodes.items():
            it = NodeItem(k, n, click)
            it.setPos(pos[k])
            sc.addItem(it)
        self.fit()

    def fit(self):
        r = self.scene().itemsBoundingRect().adjusted(-40, -40, 40, 40)
        self.setSceneRect(r)
        self.resetTransform()
        self.fitInView(r, Qt.KeepAspectRatio)
        if self.transform().m11() > 1.1:
            self.resetTransform()
            self.scale(1.1, 1.1)
            self.centerOn(r.center())

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
