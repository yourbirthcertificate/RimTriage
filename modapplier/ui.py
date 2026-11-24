"""Main window, pages and the inspector."""
import html
import os
from collections import Counter
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QCompleter, QDialog,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QTableView, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import advisor, core, diagnose, saves, support, theme, tracker
from .core import CORE
from .state import State
from .widgets import FLAGS, ChipDelegate, DepGraphView, ModModel, ModProxy, OrderModel, col, paint_chips

PAGES = [("mods", "Mods"), ("order", "Order"), ("deps", "Dependencies"), ("problems", "Problems"), ("diag", "Diagnose"), ("saves", "Saves"), ("profiles", "Profiles")]
KIND_LABEL = {"missing": "Missing", "conflict": "Conflict", "rule": "Rule", "dropped": "Dropped rule", "outdated": "Outdated", "skipped": "Skipped",
              "enable": "Needs", "unavailable": "Unavailable"}
_ICONS = []
# the process check fails safe: if Windows can't list processes, the game counts as running
NOT_SURE = " If it is already closed, Windows could not confirm that, so the app is playing safe. Try again in a moment."


# ------------------------------------------------------------------ helpers
def set_icon(btn, name, token="text", size=18):
    _ICONS.append((btn, name, token, size))
    btn.setIcon(theme.icon(name, theme.cur[token], size))
    btn.setIconSize(QSize(size, size))


def refresh_icons():
    for btn, name, token, size in _ICONS:
        try:
            btn.setIcon(theme.icon(name, theme.cur[token], size))
        except RuntimeError:
            pass


def label(text="", role=None, wrap=False):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(wrap)
    return w


def tbtn(text="", icon=None, tip="", token="text", checkable=False, icon_only=False):
    b = QToolButton()
    b.setObjectName("tb")
    b.setText(text)
    b.setToolTip(tip or text)
    b.setCursor(Qt.PointingHandCursor)
    b.setCheckable(checkable)
    b.setToolButtonStyle(Qt.ToolButtonIconOnly if icon_only else Qt.ToolButtonTextBesideIcon)
    if icon:
        set_icon(b, icon, token)
    return b


def pbtn(text, icon=None, primary=False, ghost=False, tip=""):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setProperty("primary", True)
    if ghost:
        b.setProperty("ghost", True)
    if tip:
        b.setToolTip(tip)
    if icon:
        set_icon(b, icon, "accent_text" if primary else "text")
    return b


def chip_button(text):
    b = QPushButton(text)
    b.setProperty("chip", True)
    b.setCheckable(True)
    b.setCursor(Qt.PointingHandCursor)
    return b


def card(layout):
    f = QFrame()
    f.setObjectName("card")
    f.setLayout(layout)
    return f


def page_layout(page, title, subtitle=""):
    v = QVBoxLayout(page)
    v.setContentsMargins(22, 18, 22, 12)
    v.setSpacing(12)
    head = QHBoxLayout()
    t = QVBoxLayout()
    t.setSpacing(0)
    t.addWidget(label(title, "h1"))
    sub = label(subtitle, "muted")
    t.addWidget(sub)
    head.addLayout(t)
    head.addStretch(1)
    v.addLayout(head)
    return v, head, sub


def set_table(t, row):
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(row)
    t.setShowGrid(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.ExtendedSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setFocusPolicy(Qt.StrongFocus)
    t.horizontalHeader().setHighlightSections(False)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    t.horizontalHeader().setStretchLastSection(True)
    t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)


def steam_url(pid_folder):
    return "steam://url/CommunityFilePage/" + pid_folder


def open_url(url):
    if url:
        QDesktopServices.openUrl(QUrl(url))


# --------------------------------------------------------------- mods page
class ModTable(QTableView):
    spacePressed = Signal()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.modifiers():
            self.spacePressed.emit()
            return
        super().keyPressEvent(e)


def build_tag_menu(st, menu, pids):
    tags = st.all_tags()
    add = menu.addMenu("Add tag")
    for t in tags:
        add.addAction(t, lambda t=t: st.add_tag(pids, t))
    add.addSeparator()
    add.addAction("New tag…", lambda: _new_tag(st, menu.parent(), pids))
    rem = menu.addMenu("Remove tag")
    own = sorted({t for p in pids for t in st.tags.get(p, [])})
    for t in own:
        rem.addAction(t, lambda t=t: st.remove_tag(pids, t))
    rem.setEnabled(bool(own))
    if tags:
        menu.addSeparator()
        on = menu.addMenu("Tick everything tagged")
        off = menu.addMenu("Untick everything tagged")
        for t in tags:
            ids = [p for p, v in st.tags.items() if t in v]
            on.addAction("%s (%d)" % (t, len(ids)), lambda ids=ids: st.set_checked(ids, True))
            off.addAction("%s (%d)" % (t, len(ids)), lambda ids=ids: st.set_checked(ids, False))


def _new_tag(st, parent, pids):
    name, ok = QInputDialog.getText(parent, "New tag", "Tag name (for example QoL, Combat, Visual):")
    if ok and name.strip():
        st.add_tag(pids, name)


class ModsPage(QWidget):
    def __init__(self, st, win):
        super().__init__()
        self.st, self.win = st, win
        v, head, self.sub = page_layout(self, "Mods", "")
        auto = pbtn("Auto-select", "wand", tip="Tick every compatible mod and leave out the broken or outdated ones")
        auto.clicked.connect(st.auto_select)
        cur = pbtn("From current ModsConfig", "download", ghost=True, tip="Tick exactly what RimWorld has enabled right now")
        cur.clicked.connect(st.from_current)
        ref = pbtn("Refresh library", "refresh", ghost=True,
                   tip="Re-read your mod folders after subscribing or removing mods (F5). Keeps your ticks and order.")
        ref.clicked.connect(st.refresh_library)
        head.addWidget(ref)
        head.addWidget(cur)
        head.addWidget(auto)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods (Ctrl+F)")
        self.search.setToolTip("Matches name, author, tag or package id")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(150)
        bar.addWidget(self.search, 1)
        self.kind_box = QComboBox()
        self.kind_box.setToolTip("Which mods to show")
        self.kind_box.setMinimumWidth(150)
        self.kinds = {}

        class _Kind:  # keeps `kinds["unverified"].setChecked(True)` working for the rest of the app
            def __init__(s, box, i):
                s.box, s.i = box, i

            def setChecked(s, on):
                if on:
                    s.box.setCurrentIndex(s.i)
        for i, (key, text) in enumerate((("all", "Show: all mods"), ("ticked", "Show: ticked"), ("unticked", "Show: not ticked"),
                                         ("problems", "Show: problems"), ("outdated", "Show: outdated"),
                                         ("unverified", "Show: unverified code"), ("updated", "Show: updated in 7 days"))):
            self.kind_box.addItem(text, key)
            self.kinds[key] = _Kind(self.kind_box, i)
        self.kind_box.currentIndexChanged.connect(lambda _i: self.proxy.set_filter(kind=self.kind_box.currentData()))
        bar.addWidget(self.kind_box)
        self.tag_box = QComboBox()
        self.tag_box.setMinimumWidth(120)
        self.tag_box.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.tag_box.currentIndexChanged.connect(lambda: self.proxy.set_filter(tag=self.tag_box.currentData() or ""))
        bar.addWidget(self.tag_box)
        bar.addStretch(1)
        self.bulk = {}
        for key, text, icon, tip in (("tick", "Tick", "check", "Tick every mod shown"), ("untick", "Untick", "close", "Untick every mod shown"),
                                     ("invert", "Invert", "refresh", "Flip every mod shown")):
            b = tbtn("", icon, tip, icon_only=True)
            self.bulk[key] = b
            bar.addWidget(b)
        tag = tbtn("Tags", "tag", "Tag the selected mods, or tick and untick by tag")
        tag.setPopupMode(QToolButton.InstantPopup)
        self.tag_menu = QMenu(self)
        self.tag_menu.aboutToShow.connect(self.fill_tag_menu)
        tag.setMenu(self.tag_menu)
        bar.addWidget(tag)
        v.addLayout(bar)

        self.model = ModModel(st, self.selected_pids)
        self.proxy = ModProxy(st)
        self.proxy.setSourceModel(self.model)
        self.table = ModTable()
        self.table.setModel(self.proxy)
        set_table(self.table, 30)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(1, Qt.AscendingOrder)
        self.table.setItemDelegateForColumn(7, ChipDelegate(self.table))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        h = self.table.horizontalHeader()
        for i, w in enumerate((42, 290, 120, 100, 56, 74, 98)):
            h.resizeSection(i, w)
        v.addWidget(self.table, 1)

        self.kinds["all"].setChecked(True)
        self.search.textChanged.connect(lambda t: self.proxy.set_filter(text=t))
        self.bulk["tick"].clicked.connect(lambda: st.set_checked(self.visible_pids(), True))
        self.bulk["untick"].clicked.connect(lambda: st.set_checked(self.visible_pids(), False))
        self.bulk["invert"].clicked.connect(lambda: st.invert(self.visible_pids()))
        self.table.spacePressed.connect(self.toggle_selected)
        self.table.doubleClicked.connect(lambda i: i.column() != 0 and self.toggle_selected())
        self.table.customContextMenuRequested.connect(self.context)
        self.table.selectionModel().currentRowChanged.connect(
            lambda cur, _: cur.isValid() and st.select(self.proxy.data(cur, Qt.UserRole)))
        st.changed.connect(self.on_changed)
        st.reset.connect(self.on_changed)

    def on_changed(self):
        st = self.st
        self.sub.setText("%d ticked of %d installed" % (st.n_ticked(), len(st.mods)))
        tags = st.all_tags()
        have = [self.tag_box.itemData(i) for i in range(1, self.tag_box.count())]
        if tags != have or not self.tag_box.count():
            cur = self.tag_box.currentData()
            self.tag_box.blockSignals(True)
            self.tag_box.clear()
            self.tag_box.addItem("All tags", "")
            for t in tags:
                self.tag_box.addItem(t, t)
            i = self.tag_box.findData(cur)
            self.tag_box.setCurrentIndex(max(i, 0))
            self.tag_box.blockSignals(False)
        self.proxy.invalidateFilter()

    def selected_pids(self):
        sm = self.table.selectionModel()
        return [self.proxy.data(i, Qt.UserRole) for i in sm.selectedRows()] if sm else []

    def visible_pids(self):
        return [self.proxy.index(r, 0).data(Qt.UserRole) for r in range(self.proxy.rowCount())]

    def toggle_selected(self):
        sel = self.selected_pids()
        if sel:
            self.st.set_checked(sel, not self.st.checked.get(sel[0], False))

    def fill_tag_menu(self):
        self.tag_menu.clear()
        sel = self.selected_pids()
        if not sel:
            self.tag_menu.addAction("Select some mods first").setEnabled(False)
            return
        build_tag_menu(self.st, self.tag_menu, sel)

    def context(self, pos):
        sel = self.selected_pids()
        if not sel:
            return
        st, p = self.st, sel[0]
        m = st.mods[p]
        menu = QMenu(self)
        on = st.checked.get(p, False)
        menu.addAction("Untick" if on else "Tick", self.toggle_selected)
        if len(sel) == 1:
            menu.addAction("Tick with requirements", lambda: st.enable_with_requirements(p))
            menu.addAction("Untick with dependents", lambda: st.disable_with_dependents(p))
            menu.addAction("Show in dependency finder", lambda: self.win.show_page("deps"))
        menu.addSeparator()
        build_tag_menu(st, menu, sel)
        menu.addSeparator()
        menu.addAction("Open mod folder", lambda: os.startfile(str(m.path)))
        if m.source == "workshop":
            menu.addAction("Open Steam page", lambda: open_url(steam_url(m.path.name)))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def goto(self, pid):
        if pid not in self.model.pids:
            return
        src = self.model.index(self.model.pids.index(pid), 0)
        idx = self.proxy.mapFromSource(src)
        if not idx.isValid():
            self.search.clear()
            self.kinds["all"].setChecked(True)
            self.tag_box.setCurrentIndex(0)
            idx = self.proxy.mapFromSource(src)
        self.table.selectRow(idx.row())
        self.table.scrollTo(idx, QAbstractItemView.PositionAtCenter)

    def set_row(self, row):
        self.table.verticalHeader().setDefaultSectionSize(row)


# ---------------------------------------------------------------- order page
class MovedDialog(QDialog):
    def __init__(self, parent, mods, moved):
        super().__init__(parent)
        self.setWindowTitle("What moved")
        self.resize(820, 520)
        v = QVBoxLayout(self)
        v.addWidget(label("%d mods moved" % len(moved), "h2"))
        v.addWidget(label("Biggest moves first. Each row shows the first rule behind the new position.", "muted"))
        t = QTableWidget(min(len(moved), 200), 4)
        t.setHorizontalHeaderLabels(["Mod", "From", "To", "Why"])
        set_table(t, 28)
        for r, (p, a, b, why) in enumerate(moved[:200]):
            for c, txt in enumerate((mods[p].name, str(a + 1), str(b + 1), why)):
                t.setItem(r, c, QTableWidgetItem(txt))
        t.setColumnWidth(0, 300)
        t.setColumnWidth(1, 60)
        t.setColumnWidth(2, 60)
        v.addWidget(t, 1)
        ok = pbtn("Close", primary=True)
        ok.clicked.connect(self.accept)
        v.addWidget(ok, 0, Qt.AlignRight)


class RulesDialog(QDialog):
    """Your own rules and pins, with a way to take them back."""

    def __init__(self, parent, st):
        super().__init__(parent)
        self.st = st
        self.setWindowTitle("Your rules")
        self.resize(560, 420)
        v = QVBoxLayout(self)
        v.addWidget(label("Rules you saved from the Order page. They beat the community rules.", "muted", True))
        self.list = QListWidget()
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        rm = pbtn("Remove selected", "trash")
        rm.clicked.connect(self.remove)
        row.addWidget(rm)
        row.addStretch(1)
        close = pbtn("Close", primary=True)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)
        self.fill()

    def fill(self):
        self.list.clear()
        nm = lambda p: self.st.mods[p].name if p in self.st.mods else p  # noqa
        for r in self.st.user["after"]:
            it = QListWidgetItem("%s always loads after %s" % (nm(r[0]), nm(r[1])))
            it.setData(Qt.UserRole, ("after", r))
            self.list.addItem(it)
        for k, txt in (("top", "is pinned to the start"), ("bottom", "is pinned to the end")):
            for p in self.st.user[k]:
                it = QListWidgetItem("%s %s" % (nm(p), txt))
                it.setData(Qt.UserRole, (k, p))
                self.list.addItem(it)
        if not self.list.count():
            self.list.addItem("Nothing saved yet. Right-click a mod in the load order to add a rule.")
            self.list.item(0).setFlags(Qt.NoItemFlags)

    def remove(self):
        for it in self.list.selectedItems():
            kind, val = it.data(Qt.UserRole) or (None, None)
            if kind == "after":
                self.st.forget_rule(val)
            elif kind:
                self.st.pin(val, None)
        self.fill()


class OrderTable(QTableView):
    def keyPressEvent(self, e):
        if e.modifiers() & Qt.AltModifier and e.key() in (Qt.Key_Up, Qt.Key_Down):
            self.parent().parent().move_sel("up" if e.key() == Qt.Key_Up else "down")
            return
        super().keyPressEvent(e)


class OrderPage(QWidget):
    def __init__(self, st, win):
        super().__init__()
        self.st, self.win = st, win
        v, head, self.sub = page_layout(self, "Load order", "")
        self.mode = QComboBox()
        for k, t in core.MODES.items():
            self.mode.addItem(t, k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(st.mode)))
        self.mode.setToolTip("Strict: only the rules. Balanced: rules plus library, patch and last-load guesses.\n"
                             "Grouped: also bands interface and visual mods together.")
        self.mode.currentIndexChanged.connect(self.mode_changed)
        head.addWidget(label("Sort mode", "muted"))
        head.addWidget(self.mode)
        smart = pbtn("Smart sort", "wand", primary=True, tip="Re-sort every mod from the rules and show what moved")
        smart.clicked.connect(self.smart)
        gentle = pbtn("Gentle sort", "refresh", ghost=True,
                      tip="Keep the order in your ModsConfig.xml. New mods are slotted in and only what breaks a rule moves.")
        gentle.clicked.connect(self.gentle)
        head.addWidget(gentle)
        head.addWidget(smart)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.state_lbl = QLabel()
        bar.addWidget(self.state_lbl)
        self.fix_btn = tbtn("Fix", "shield", "Repair broken rules while moving as few mods as possible")
        self.fix_btn.clicked.connect(self.fix)
        bar.addWidget(self.fix_btn)
        val = tbtn("Check", "problems", "List every rule this order breaks")
        val.clicked.connect(self.validate)
        bar.addWidget(val)
        bar.addStretch(1)
        for key, icon, tip in (("top", "top", "Move to the start (after the game files)"), ("up", "up", "Move up (Alt+Up)"),
                               ("down", "down", "Move down (Alt+Down)"), ("bottom", "bottom", "Move to the end")):
            b = tbtn("", icon, tip, icon_only=True)
            b.clicked.connect(lambda _=False, k=key: self.move_sel(k))
            bar.addWidget(b)
        place = tbtn("Place", "target", "Place correctly: put the selected mods where the rules say they belong, without touching the rest")
        place.clicked.connect(self.place)
        bar.addWidget(place)
        reset = tbtn("Reset", "refresh", "Reset to auto: throw away manual moves")
        reset.clicked.connect(self.reset_auto)
        bar.addWidget(reset)
        self.comm = QCheckBox("Community")
        self.comm.setToolTip("Use the community load-order rules")
        self.comm.setChecked(True)
        self.comm.toggled.connect(st.set_use_community)
        bar.addWidget(self.comm)
        upd = tbtn("", "download", "Download the latest community rules from GitHub", icon_only=True)
        upd.clicked.connect(win.update_rules)
        bar.addWidget(upd)
        mine = tbtn("Rules", "pin", "Rules and pins you saved")
        mine.clicked.connect(lambda: RulesDialog(self, st).exec())
        bar.addWidget(mine)
        v.addLayout(bar)

        self.model = OrderModel(st)
        self.table = OrderTable()
        self.table.setModel(self.model)
        set_table(self.table, 30)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.viewport().setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DragDrop)
        self.table.setDropIndicatorShown(True)
        self.table.setDragDropOverwriteMode(False)
        self.table.setDefaultDropAction(Qt.MoveAction)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        for i, w in enumerate((56, 330, 90)):
            self.table.horizontalHeader().resizeSection(i, w)
        v.addWidget(self.table, 1)
        v.addWidget(label("Drag rows to reorder. Moves you make stay until you press Smart sort or Reset to auto.", "caption"))

        self.table.customContextMenuRequested.connect(self.context)
        self.table.selectionModel().currentRowChanged.connect(
            lambda cur, _: cur.isValid() and st.select(self.model.rows[cur.row()][0]))
        self.model.modelReset.connect(self.after_reset)
        st.orderChanged.connect(self.refresh_status)
        st.reset.connect(self.refresh_status)

    def showEvent(self, e):
        self.model.active = True
        if self.model.dirty:
            self.model.refresh()
        self.refresh_status()
        super().showEvent(e)

    def hideEvent(self, e):
        self.model.active = False
        super().hideEvent(e)

    def selected_pids(self):
        return [self.model.rows[i.row()][0] for i in self.table.selectionModel().selectedRows()]

    def after_reset(self):
        moved = self.st.last_moved
        self.st.last_moved = []
        if not moved:
            return
        rows = [i for i, (p, _) in enumerate(self.model.rows) if p in set(moved)]
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for r in rows:
            self.table.selectionModel().select(self.model.index(r, 0), flags)
        if rows:
            self.table.scrollTo(self.model.index(rows[0], 0), QAbstractItemView.EnsureVisible)

    def refresh_status(self):
        if not self.isVisible() or not self.st.mods:
            return
        pl = self.st.plan()
        n = len(pl.violations)
        manual = self.st.manual is not None
        self.sub.setText("%d mods, %s" % (len(pl.order), "your manual order" if manual else "sorted automatically"))
        c = theme.cur["danger" if n else "ok"]
        self.state_lbl.setText('<span style="color:%s">&#9679;</span>&nbsp; %s' % (
            c, "%d rules broken" % n if n else "All rules satisfied"))
        self.fix_btn.setText("Fix %d" % n if n else "Fix")
        self.fix_btn.setEnabled(bool(n))

    def mode_changed(self):
        self.st.set_mode(self.mode.currentData())
        if self.st.manual is not None:
            self.win.toast("Sort mode changed. Press Smart sort to apply it to your current order.")

    def gentle(self):
        r = self.st.gentle_sort()
        if not r["added"] and not r["moved"]:
            self.win.toast("Your file's order already follows the rules. Nothing moved.")
        else:
            self.win.toast("Kept %d mods in place, added %d new, moved %d to satisfy the rules." % (r["kept"], r["added"], r["moved"]))

    def smart(self):
        moved = self.st.smart_sort()
        if not moved:
            self.win.toast("Already in the best order. Nothing moved.")
        else:
            MovedDialog(self, self.st.mods, moved).exec()

    def fix(self):
        n = self.st.fix_order()
        self.win.toast("Fixed the broken rules by moving %d mods" % n)

    def validate(self):
        pl = self.st.plan()
        if not pl.violations:
            self.win.toast("No broken rules")
            return
        d = QDialog(self)
        d.setWindowTitle("Broken rules")
        d.resize(700, 420)
        v = QVBoxLayout(d)
        lst = QListWidget()
        for viol in pl.violations:
            it = QListWidgetItem(core.violation_text(viol, self.st.mods))
            it.setData(Qt.UserRole, viol[1])
            lst.addItem(it)
        lst.itemDoubleClicked.connect(lambda it: (d.accept(), self.goto(it.data(Qt.UserRole))))
        v.addWidget(lst, 1)
        row = QHBoxLayout()
        fix = pbtn("Fix them", "shield", primary=True)
        fix.clicked.connect(lambda: (d.accept(), self.fix()))
        close = pbtn("Close")
        close.clicked.connect(d.accept)
        row.addStretch(1)
        row.addWidget(close)
        row.addWidget(fix)
        v.addLayout(row)
        d.exec()

    def goto(self, pid):
        for i, (p, _) in enumerate(self.model.rows):
            if p == pid:
                self.table.selectRow(i)
                self.table.scrollTo(self.model.index(i, 0), QAbstractItemView.PositionAtCenter)
                return

    def move_sel(self, where):
        sel = self.selected_pids()
        if sel:
            self.st.move_by(sel, where)

    def place(self):
        sel = self.selected_pids()
        if not sel:
            self.win.toast("Select the mods you want placed first")
            return
        rep = self.st.place_correctly(sel)
        self.win.toast("Placed %d mods where their rules put them" % len(rep))

    def reset_auto(self):
        self.st.push_undo()
        self.st.manual = None
        self.st._plan = None
        self.st.orderChanged.emit()
        self.win.toast("Back to automatic order")

    def context(self, pos):
        sel = self.selected_pids()
        if not sel:
            return
        st = self.st
        order = [p for p, _ in self.model.rows]
        p = sel[0]
        i = order.index(p)
        menu = QMenu(self)
        menu.addAction("Move to start", lambda: st.move_by(sel, "top"))
        menu.addAction("Move to end", lambda: st.move_by(sel, "bottom"))
        menu.addAction("Place correctly", self.place)
        if len(sel) == 1:
            menu.addSeparator()
            if i > 0:
                prev = order[i - 1]
                menu.addAction("Always load after %s" % st.mods[prev].name, lambda: self.remember(p, prev, False))
            if i + 1 < len(order):
                nxt = order[i + 1]
                menu.addAction("Always load before %s" % st.mods[nxt].name, lambda: self.remember(p, nxt, True))
            menu.addAction("Pin to the start", lambda: st.pin(p, "top"))
            menu.addAction("Pin to the end", lambda: st.pin(p, "bottom"))
            if p in st.user["top"] or p in st.user["bottom"]:
                menu.addAction("Remove pin", lambda: st.pin(p, None))
            menu.addSeparator()
            menu.addAction("Show in Mods", lambda: self.win.show_mod(p))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def remember(self, p, other, before):
        self.st.remember(p, other, before)
        self.win.toast("Saved. %s will keep that position." % self.st.mods[p].name)

    def set_row(self, row):
        self.table.verticalHeader().setDefaultSectionSize(row)


# ------------------------------------------------------------ dependencies
class DepsPage(QWidget):
    STATE_TEXT = {"on": "ticked", "off": "not ticked", "outdated": "outdated", "missing": "not installed",
                  "unavailable": "needs something missing", "focus": ""}

    def __init__(self, st, win):
        super().__init__()
        self.st, self.win, self.pid = st, win, None
        v, head, self.sub = page_layout(self, "Dependency finder", "Pick a mod to see what it needs and what needs it")
        self.pick = QComboBox()
        self.pick.setEditable(True)
        self.pick.setInsertPolicy(QComboBox.NoInsert)
        self.pick.setMinimumWidth(260)
        self.pick.lineEdit().setPlaceholderText("Type a mod name")
        head.addWidget(self.pick)
        self.up = pbtn("Tick with requirements", "check", tip="Tick this mod and everything it needs")
        self.down = pbtn("Untick with dependents", "close", ghost=True, tip="Untick this mod and everything that needs it")
        self.up.clicked.connect(lambda: self.pid and st.enable_with_requirements(self.pid))
        self.down.clicked.connect(lambda: self.pid and st.disable_with_dependents(self.pid))
        head.addWidget(self.up)
        head.addWidget(self.down)

        split = QSplitter(Qt.Vertical)
        self.tabs = QTabWidget()
        gwrap = QWidget()
        gl = QVBoxLayout(gwrap)
        gl.setContentsMargins(0, 10, 0, 0)
        self.graph = DepGraphView()
        gl.addWidget(self.graph, 1)
        row = QHBoxLayout()
        row.addWidget(label("Left: what it needs. Right: what needs it. Solid arrows are requirements, red dashes are conflicts. "
                            "Scroll to zoom, drag to pan, click a box to jump.", "caption"))
        row.addStretch(1)
        fit = tbtn("Fit", "target")
        fit.clicked.connect(self.graph.fit)
        row.addWidget(fit)
        gl.addLayout(row)
        self.tabs.addTab(gwrap, "Graph")
        self.req = QTreeWidget()
        self.req.setHeaderLabels(["Requires", "State"])
        self.req.header().resizeSection(0, 420)
        self.tabs.addTab(self.req, "Requires")
        self.need = QTreeWidget()
        self.need.setHeaderLabels(["Needed by", "State"])
        self.need.header().resizeSection(0, 420)
        self.tabs.addTab(self.need, "Needed by")
        split.addWidget(self.tabs)

        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 6, 0, 0)
        h2 = QHBoxLayout()
        self.miss_title = label("Missing dependencies", "h2")
        h2.addWidget(self.miss_title)
        h2.addStretch(1)
        self.open_btn = pbtn("Open in Steam", "link", ghost=True, tip="Open the download page for the selected mod")
        self.open_btn.clicked.connect(self.open_missing)
        h2.addWidget(self.open_btn)
        self.sub_btn = pbtn("Subscribe to all missing…", "link", primary=True,
                            tip="Step through the Workshop pages of every missing dependency")
        self.sub_btn.clicked.connect(self.subscribe_all)
        h2.addWidget(self.sub_btn)
        bl.addLayout(h2)
        self.miss = QTableWidget(0, 3)
        self.miss.setHorizontalHeaderLabels(["Missing mod", "Needed by", "Which mods"])
        set_table(self.miss, 28)
        self.miss.setColumnWidth(0, 300)
        self.miss.setColumnWidth(1, 90)
        bl.addWidget(self.miss, 1)
        split.addWidget(box)
        split.setSizes([480, 200])
        v.addWidget(split, 1)

        for tree in (self.req, self.need):
            tree.itemDoubleClicked.connect(lambda it, _=0: it.data(0, Qt.UserRole) and st.select(it.data(0, Qt.UserRole)))
        self.miss.doubleClicked.connect(lambda _: self.open_missing())
        self.pick.activated.connect(self.picked)
        self.pick.lineEdit().returnPressed.connect(self.picked)
        st.selected.connect(self.show_mod)
        st.reset.connect(self.on_reset)
        st.changed.connect(self.refresh)

    def on_reset(self):
        st = self.st
        names = sorted(((m.name, p) for p, m in st.mods.items()), key=lambda x: x[0].lower())
        self.pick.blockSignals(True)
        self.pick.clear()
        for n, p in names:
            self.pick.addItem(n, p)
        self.pick.setCurrentIndex(-1)
        self.pick.blockSignals(False)
        comp = QCompleter([n for n, _ in names], self.pick)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.pick.setCompleter(comp)
        comp.activated.connect(lambda _t: self.picked())
        self.pid = None
        self.fill_missing()

    def picked(self):
        i = self.pick.findText(self.pick.currentText(), Qt.MatchFixedString | Qt.MatchCaseSensitive)
        if i < 0:
            i = self.pick.findText(self.pick.currentText(), Qt.MatchFixedString)
        if i >= 0:
            self.st.select(self.pick.itemData(i))

    def show_mod(self, pid):
        if pid not in self.st.mods:
            return
        self.pid = pid
        i = self.pick.findData(pid)
        self.pick.blockSignals(True)
        self.pick.setCurrentIndex(i)
        self.pick.blockSignals(False)
        self.refresh()

    def refresh(self):
        st, pid = self.st, self.pid
        if not st.mods:
            return
        self.fill_missing()
        if not pid or pid not in st.mods:
            return
        m = st.mods[pid]
        self.sub.setText("%s  ·  %s" % (m.name, m.pid))
        nodes, edges = core.neighborhood(pid, st.mods, st.rev, st.checked, st.broken, st.target)
        self.graph.set_graph(nodes, edges, st.select)
        self.req.clear()
        self.fill_tree(self.req.invisibleRootItem(), core.requires_tree(pid, st.mods, st.checked, st.broken, st.target))
        self.req.expandToDepth(1)
        if not self.req.topLevelItemCount():
            self.req.addTopLevelItem(QTreeWidgetItem(["This mod needs nothing else", ""]))
        self.need.clear()
        direct = sorted(st.rev.get(pid, ()), key=lambda p: st.mods[p].name.lower())
        for p in direct:
            it = QTreeWidgetItem([st.mods[p].name, "ticked" if st.checked.get(p) else "not ticked"])
            it.setData(0, Qt.UserRole, p)
            it.setForeground(1, col("on" if st.checked.get(p) else "off"))
            self.need.addTopLevelItem(it)
        extra = len(core.all_dependents(pid, st.rev)) - len(direct)
        if extra > 0:
            self.need.addTopLevelItem(QTreeWidgetItem(["…and %d more through other mods" % extra, ""]))
        if not direct:
            self.need.addTopLevelItem(QTreeWidgetItem(["No installed mod needs this one", ""]))

    def fill_tree(self, parent, nodes):
        for n in nodes:
            it = QTreeWidgetItem([n["name"], self.STATE_TEXT.get(n["state"], n["state"])])
            it.setData(0, Qt.UserRole, n["pid"])
            it.setForeground(1, col(n["state"]))
            parent.addChild(it)
            if n["children"]:
                self.fill_tree(it, n["children"])

    def fill_missing(self):
        rep = core.missing_report(self.st.mods)
        self.miss_title.setText("Missing dependencies (%d)" % len(rep))
        self.miss.setRowCount(len(rep))
        for r, (name, url, who) in enumerate(rep):
            for c, txt in enumerate((name, str(len(who)), ", ".join(who[:6]) + ("…" if len(who) > 6 else ""))):
                it = QTableWidgetItem(txt)
                it.setData(Qt.UserRole, url)
                self.miss.setItem(r, c, it)
        self.open_btn.setEnabled(bool(rep))
        self.sub_btn.setEnabled(bool(rep))

    def subscribe_all(self):
        items = saves.missing_dep_items(self.st.mods)
        if not items:
            self.win.toast("No dependency is missing")
            return
        SubscribeDialog(self.win, self.st, items, "Subscribe to missing dependencies").exec()

    def open_missing(self):
        r = self.miss.currentRow()
        if r >= 0:
            url = self.miss.item(r, 0).data(Qt.UserRole)
            if url:
                open_url(url)
            else:
                self.win.toast("No download link in that mod's About.xml. Search the Workshop for its name.")


# ----------------------------------------------------------------- problems
class ProblemsPage(QWidget):
    def __init__(self, st, win):
        super().__init__()
        self.st, self.win, self.rows, self.kind = st, win, [], "all"
        v, head, self.sub = page_layout(self, "Problems", "")
        self.fix = pbtn("Fix load-order rules", "shield", primary=True)
        self.fix.clicked.connect(lambda: win.toast("Fixed by moving %d mods" % st.fix_order()))
        head.addWidget(self.fix)
        bar = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.chips = {}
        for key in ("all", "missing", "conflict", "rule", "dropped", "outdated", "skipped"):
            b = chip_button(KIND_LABEL.get(key, "All"))
            self.group.addButton(b)
            self.chips[key] = b
            bar.addWidget(b)
            b.toggled.connect(lambda on, k=key: on and self.set_kind(k))
        bar.addStretch(1)
        v.addLayout(bar)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Type", "Mod", "Detail"])
        set_table(self.table, 30)
        self.table.setItemDelegateForColumn(0, ChipDelegate(self.table))
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 300)
        self.table.doubleClicked.connect(self.jump)
        v.addWidget(self.table, 1)
        self.chips["all"].setChecked(True)
        st.orderChanged.connect(self.refresh)
        st.changed.connect(self.refresh)

    def showEvent(self, e):
        self.refresh()
        super().showEvent(e)

    def build(self):
        st, rows = self.st, []
        pl = st.plan()
        nm = lambda p: st.mods[p].name  # noqa
        for w in pl.warnings:
            rows.append(("rule", "", w, None))
        for v in pl.violations:
            rows.append(("rule", nm(v[1]), core.violation_text(v, st.mods), v[1]))
        for d in pl.dropped_rules:
            rows.append(("dropped", nm(d[1]), core.dropped_rule_text(d, st.mods), d[1]))
        for p, d in sorted(st.broken.items(), key=lambda x: nm(x[0]).lower()):
            gone = not any(x in st.mods for x in d.ids)
            rows.append(("missing", nm(p), ("Needs %s, which is not installed. %s" if gone else "Needs %s, which cannot load. %s") % (d.display, d.url), p))
        on = {p for p, v in st.checked.items() if v}
        seen = set()
        for p in on:
            for x in st.mods[p].incompat:
                if x in on and x in st.mods and (x, p) not in seen:
                    seen.add((p, x))
                    rows.append(("conflict", nm(p), "Incompatible with %s, and both are ticked" % nm(x), p))
        for p, m in st.mods.items():
            if not core.version_ok(m, st.target):
                rows.append(("outdated", m.name, "Supports up to %s, the game is %s" % (core.max_version(m), st.target), p))
        for n, why in st.dups + st.bad:
            rows.append(("skipped", n, why, None))
        return rows

    def refresh(self):
        if not self.isVisible() or not self.st.mods:
            return
        self.rows = self.build()
        counts = {k: sum(1 for r in self.rows if r[0] == k) for k in KIND_LABEL}
        for k, b in self.chips.items():
            b.setText(("All (%d)" % len(self.rows)) if k == "all" else "%s (%d)" % (KIND_LABEL[k], counts[k]))
        self.sub.setText("%d things worth a look" % len(self.rows))
        self.fix.setVisible(bool(self.st.plan().violations))
        self.fill()

    def set_kind(self, k):
        self.kind = k
        self.fill()

    def fill(self):
        rows = [r for r in self.rows if self.kind in ("all", r[0])]
        self.table.setRowCount(len(rows))
        for i, (k, mod, detail, pid) in enumerate(rows):
            a = QTableWidgetItem()
            a.setData(FLAGS, [(k, KIND_LABEL[k])])
            a.setData(Qt.UserRole, pid)
            self.table.setItem(i, 0, a)
            self.table.setItem(i, 1, QTableWidgetItem(mod))
            d = QTableWidgetItem(detail)
            d.setToolTip(detail)
            self.table.setItem(i, 2, d)

    def jump(self, idx):
        pid = self.table.item(idx.row(), 0).data(Qt.UserRole)
        if pid:
            self.win.show_mod(pid)


# ----------------------------------------------------------------- profiles
class ProfilesPage(QWidget):
    def __init__(self, st, win):
        super().__init__()
        self.st, self.win = st, win
        v, head, self.sub = page_layout(self, "Profiles", "Save, switch, compare and share mod lists")
        imp = pbtn("Import list…", "download", ghost=True, tip="Read a mod list from a .json or ModsConfig-style .xml file")
        exp = pbtn("Export list…", "upload", ghost=True, tip="Save your load order as .json or .xml (RimPy and RimSort read the xml)")
        imp.clicked.connect(self.import_list)
        exp.clicked.connect(self.export_list)
        head.addWidget(imp)
        head.addWidget(exp)

        grid = QGridLayout()
        grid.setSpacing(14)
        left = QVBoxLayout()
        left.addWidget(label("Saved profiles", "h2"))
        self.list = QListWidget()
        left.addWidget(self.list, 1)
        r = QHBoxLayout()
        for text, icon, fn, primary in (("Load", "check", self.load, True), ("Save current as…", "save", self.save_as, False),
                                        ("Delete", "trash", self.delete, False)):
            b = pbtn(text, icon, primary=primary)
            b.clicked.connect(fn)
            r.addWidget(b)
        left.addLayout(r)
        grid.addWidget(card(self._pad(left)), 0, 0)

        right = QVBoxLayout()
        right.addWidget(label("Backups of ModsConfig.xml", "h2"))
        self.backs = QListWidget()
        right.addWidget(self.backs, 1)
        r = QHBoxLayout()
        rb = pbtn("Restore", "refresh")
        rb.clicked.connect(self.restore)
        ob = pbtn("Open folder", "folder", ghost=True)
        ob.clicked.connect(lambda: os.startfile(str(Path(st.s["config_path"]).parent)))
        r.addWidget(rb)
        r.addWidget(ob)
        right.addLayout(r)
        grid.addWidget(card(self._pad(right)), 0, 1)

        cmp_ = QVBoxLayout()
        cmp_.addWidget(label("Compare", "h2"))
        row = QHBoxLayout()
        self.a, self.b = QComboBox(), QComboBox()
        row.addWidget(label("From", "muted"))
        row.addWidget(self.a, 1)
        row.addWidget(label("to", "muted"))
        row.addWidget(self.b, 1)
        cmp_.addLayout(row)
        two = QHBoxLayout()
        self.added, self.removed = QListWidget(), QListWidget()
        for title, lst in (("Added", self.added), ("Removed", self.removed)):
            col_ = QVBoxLayout()
            hdr = label(title, "muted")
            setattr(self, title.lower() + "_lbl", hdr)
            col_.addWidget(hdr)
            col_.addWidget(lst, 1)
            two.addLayout(col_)
        cmp_.addLayout(two, 1)
        grid.addWidget(card(self._pad(cmp_)), 1, 0, 1, 2)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        v.addLayout(grid, 1)
        self.list.itemDoubleClicked.connect(lambda _: self.load())
        self.a.currentIndexChanged.connect(self.compare)
        self.b.currentIndexChanged.connect(self.compare)

    @staticmethod
    def _pad(layout):
        layout.setContentsMargins(14, 12, 14, 12)
        return layout

    def showEvent(self, e):
        self.refresh()
        super().showEvent(e)

    def refresh(self):
        profs = core.list_profiles()
        self.list.clear()
        self.list.addItems(profs or [])
        if not profs:
            it = QListWidgetItem("No profiles yet. Press Save current as…")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)
        self.backs.clear()
        for f in core.list_backups(self.st.s["config_path"]):
            it = QListWidgetItem(time.strftime("%d %b %Y, %H:%M:%S", time.localtime(f.stat().st_mtime)))
            it.setData(Qt.UserRole, str(f))
            self.backs.addItem(it)
        if not self.backs.count():
            it = QListWidgetItem("No backups yet. One is saved every time you apply.")
            it.setFlags(Qt.NoItemFlags)
            self.backs.addItem(it)
        keep = (self.a.currentData(), self.b.currentData())
        for box in (self.a, self.b):
            box.blockSignals(True)
            box.clear()
            box.addItem("Current selection", "#selection")
            box.addItem("Current ModsConfig.xml", "#config")
            for p in profs:
                box.addItem(p, p)
        for box, k in ((self.a, keep[0] or "#config"), (self.b, keep[1] or "#selection")):
            box.setCurrentIndex(max(0, box.findData(k)))
            box.blockSignals(False)
        self.compare()

    def compare(self):
        st = self.st
        try:
            added, removed = core.profile_diff(st.profile_on(self.a.currentData()), st.profile_on(self.b.currentData()), st.mods)
        except Exception:
            added, removed = [], []
        nm = lambda p: st.mods[p].name if p in st.mods else p + " (not installed)"  # noqa
        self.added.clear()
        self.removed.clear()
        self.added.addItems([nm(p) for p in added])
        self.removed.addItems([nm(p) for p in removed])
        self.added_lbl.setText("Added (%d)" % len(added))
        self.removed_lbl.setText("Removed (%d)" % len(removed))

    def current(self):
        it = self.list.currentItem()
        return it.text() if it and it.flags() & Qt.ItemIsEnabled else None

    def load(self):
        n = self.current()
        if n:
            self.st.load_profile(n)

    def save_as(self):
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:", text=self.st.s.get("last_profile", ""))
        if ok and name.strip():
            self.st.save_profile(name.strip())
            self.refresh()
            self.win.toast("Saved profile %s" % name.strip())

    def delete(self):
        n = self.current()
        if n and QMessageBox.question(self, "Delete profile", "Delete the profile '%s'?" % n) == QMessageBox.Yes:
            core.delete_profile(n)
            self.refresh()

    def restore(self):
        it = self.backs.currentItem()
        f = it.data(Qt.UserRole) if it else None
        if not f:
            return
        if core.game_running():
            QMessageBox.critical(self, "RimWorld is running", "Close RimWorld first." + NOT_SURE)
            return
        if QMessageBox.question(self, "Restore backup", "Replace ModsConfig.xml with the backup from %s?\nYour current file is backed up first." % it.text()) == QMessageBox.Yes:
            cfg = Path(self.st.s["config_path"])
            core.backup_config(cfg)
            shutil.copy2(f, cfg)
            self.st.sync_config_hash()
            self.refresh()
            self.win.toast("Backup restored")

    def import_list(self):
        f, _ = QFileDialog.getOpenFileName(self, "Import a mod list", "", "Mod lists (*.json *.xml)")
        if not f:
            return
        try:
            n, missing, workshop = self.st.import_list(f)
        except Exception as e:  # noqa
            QMessageBox.critical(self, "Could not read that file", str(e))
            return
        msg = "Ticked %d mods from the list." % n
        if missing:
            msg += "\n\n%d mods in the list are not installed:\n%s" % (len(missing), "\n".join(
                ("%s  (Workshop %s)" % (p, workshop[p]) if p in workshop else p) for p in missing[:25]))
        QMessageBox.information(self, "Imported", msg)

    def export_list(self):
        f, _ = QFileDialog.getSaveFileName(self, "Export your load order", "modlist.json", "JSON (*.json);;ModsConfig XML (*.xml)")
        if f:
            core.export_modlist(f, self.st.order_ids(), self.st.mods, core.game_version_str(self.st.s["game_dir"]))
            self.win.toast("Exported %d mods" % len(self.st.order_ids()))


# ---------------------------------------------------------------- inspector
class _SizeSignal(QObject):
    done = Signal(str, int)


class _SizeJob(QRunnable):
    def __init__(self, pid, path, sig):
        super().__init__()
        self.pid, self.path, self.sig = pid, path, sig

    def run(self):
        total = 0
        try:
            for root, _, files in os.walk(self.path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        except Exception:
            pass
        self.sig.done.emit(self.pid, total)


class ChipRow(QWidget):
    def __init__(self):
        super().__init__()
        self.flags = []
        self.setFixedHeight(30)

    def set_flags(self, flags):
        self.flags = flags
        self.setVisible(bool(flags))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        paint_chips(p, self.rect(), self.flags, 0)


class Inspector(QFrame):
    def __init__(self, st, win):
        super().__init__()
        self.setObjectName("inspector")
        self.setMinimumWidth(330)
        self.st, self.win, self.pid = st, win, None
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 12)
        v.setSpacing(8)
        self.title = label("Select a mod", "h2", True)
        self.author = label("", "muted", True)
        self.chips = ChipRow()
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.hide()
        v.addWidget(self.title)
        v.addWidget(self.author)
        v.addWidget(self.chips)
        v.addWidget(self.preview)
        self.tabs = QTabWidget()
        self.details = QTextBrowser()
        self.details.setFrameShape(QFrame.NoFrame)
        self.details.setOpenLinks(False)
        self.details.anchorClicked.connect(lambda u: open_url(u.toString()))
        self.tabs.addTab(self.details, "Details")
        self.req = QTreeWidget()
        self.req.setHeaderHidden(True)
        self.req.setFrameShape(QFrame.NoFrame)
        self.tabs.addTab(self.req, "Needs")
        self.need = QTreeWidget()
        self.need.setHeaderHidden(True)
        self.need.setFrameShape(QFrame.NoFrame)
        self.tabs.addTab(self.need, "Needed by")
        self.rules = QTreeWidget()
        self.rules.setHeaderHidden(True)
        self.rules.setFrameShape(QFrame.NoFrame)
        self.tabs.addTab(self.rules, "Rules")
        v.addWidget(self.tabs, 1)
        self.b_up = pbtn("Tick with requirements", "check")
        self.b_down = pbtn("Untick with dependents", "close", ghost=True)
        self.b_up.clicked.connect(lambda: self.pid and st.enable_with_requirements(self.pid))
        self.b_down.clicked.connect(lambda: self.pid and st.disable_with_dependents(self.pid))
        v.addWidget(self.b_up)
        v.addWidget(self.b_down)
        row = QHBoxLayout()
        self.b_folder = tbtn("Folder", "folder")
        self.b_steam = tbtn("Steam", "link")
        self.b_tags = tbtn("Tags", "tag")
        self.b_tags.setPopupMode(QToolButton.InstantPopup)
        self.tag_menu = QMenu(self)
        self.tag_menu.aboutToShow.connect(self.fill_tags)
        self.b_tags.setMenu(self.tag_menu)
        self.b_folder.clicked.connect(lambda: self.pid and os.startfile(str(st.mods[self.pid].path)))
        self.b_steam.clicked.connect(lambda: self.pid and open_url(steam_url(st.mods[self.pid].path.name)))
        for b in (self.b_folder, self.b_steam, self.b_tags):
            row.addWidget(b)
        v.addLayout(row)
        for tree in (self.req, self.need):
            tree.itemDoubleClicked.connect(lambda it, _=0: it.data(0, Qt.UserRole) and st.select(it.data(0, Qt.UserRole)))
        self.rules.itemDoubleClicked.connect(lambda it, _=0: it.data(0, Qt.UserRole) and st.select(it.data(0, Qt.UserRole)))
        self.sig = _SizeSignal()
        self.sig.done.connect(self.size_done)
        self.size_txt = ""
        st.selected.connect(self.show_mod)
        st.changed.connect(self.refresh)
        self.set_enabled(False)

    def set_enabled(self, on):
        for b in (self.b_up, self.b_down, self.b_folder, self.b_steam, self.b_tags):
            b.setEnabled(on)

    def fill_tags(self):
        self.tag_menu.clear()
        if self.pid:
            build_tag_menu(self.st, self.tag_menu, [self.pid])

    def show_mod(self, pid):
        if pid not in self.st.mods:
            return
        self.pid = pid
        self.size_txt = "calculating…"
        self.refresh()
        QThreadPool.globalInstance().start(_SizeJob(pid, str(self.st.mods[pid].path), self.sig))

    def size_done(self, pid, total):
        if pid == self.pid:
            self.size_txt = "%.1f MB" % (total / 1048576.0)
            self.refresh_details()

    def refresh(self):
        st, pid = self.st, self.pid
        if not pid or pid not in st.mods:
            return
        m = st.mods[pid]
        self.set_enabled(True)
        self.b_steam.setEnabled(m.source == "workshop")
        self.title.setText(m.name)
        self.author.setText(m.author or "Unknown author")
        self.chips.set_flags(st.status.get(pid, []))
        px = None
        for n in ("Preview.png", "Preview.jpg", "preview.png"):
            f = m.path / "About" / n
            if f.exists():
                px = QPixmap(str(f))
                break
        if px and not px.isNull():
            self.preview.setPixmap(px.scaled(300, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.preview.show()
        else:
            self.preview.hide()
        self.refresh_details()
        self.req.clear()
        self._tree(self.req.invisibleRootItem(), core.requires_tree(pid, st.mods, st.checked, st.broken, st.target))
        self.req.expandToDepth(1)
        if not self.req.topLevelItemCount():
            self.req.addTopLevelItem(QTreeWidgetItem(["Needs nothing else"]))
        self.need.clear()
        for p in sorted(st.rev.get(pid, ()), key=lambda p: st.mods[p].name.lower()):
            it = QTreeWidgetItem([st.mods[p].name + ("" if st.checked.get(p) else "  (not ticked)")])
            it.setData(0, Qt.UserRole, p)
            self.need.addTopLevelItem(it)
        if not self.need.topLevelItemCount():
            self.need.addTopLevelItem(QTreeWidgetItem(["No installed mod needs this"]))
        self.fill_rules(m)

    def _tree(self, parent, nodes):
        for n in nodes:
            txt = "%s   %s" % (n["name"], DepsPage.STATE_TEXT.get(n["state"], ""))
            it = QTreeWidgetItem([txt])
            it.setData(0, Qt.UserRole, n["pid"])
            it.setForeground(0, col(n["state"]) if n["state"] not in ("on",) else col("text"))
            parent.addChild(it)
            self._tree(it, n["children"])

    def fill_rules(self, m):
        st = self.st
        self.rules.clear()
        nm = lambda p: st.mods[p].name if p in st.mods else p  # noqa
        groups = [("Loads after", [x for x in m.after]), ("Loads before", [x for x in m.before]),
                  ("Conflicts with", [x for x in m.incompat])]
        c = st.community.get(m.pid)
        if c:
            groups += [("Community: after", list(c["after"])), ("Community: before", list(c["before"]))]
            if c["top"] or c["bottom"]:
                groups.append(("Community", ["loads " + ("early" if c["top"] else "last")]))
        mine = [r for r in st.user["after"] if r[0] == m.pid or r[1] == m.pid]
        groups.append(("Your rules", [("%s after %s" % (nm(r[0]), nm(r[1]))) for r in mine]))
        for title, items in groups:
            if not items:
                continue
            g = QTreeWidgetItem(["%s (%d)" % (title, len(items))])
            self.rules.addTopLevelItem(g)
            for x in sorted(items, key=lambda x: nm(x).lower()):
                it = QTreeWidgetItem([nm(x) + ("" if x in st.mods or title == "Your rules" or " " in x else "  (not installed)")])
                if x in st.mods:
                    it.setData(0, Qt.UserRole, x)
                g.addChild(it)
            g.setExpanded(True)
        if not self.rules.topLevelItemCount():
            self.rules.addTopLevelItem(QTreeWidgetItem(["No load-order rules"]))

    def refresh_details(self):
        st, pid = self.st, self.pid
        if not pid or pid not in st.mods:
            return
        m = st.mods[pid]
        e = html.escape
        t = theme.cur
        rows = [("Package id", m.pid), ("Source", m.source.title()), ("Supports", ", ".join(m.versions) or "not stated"),
                ("Size", self.size_txt), ("Folder", str(m.path)), ("Tags", ", ".join(st.tags.get(pid, [])) or "none")]
        body = "".join('<tr><td style="color:%s;padding-right:10px">%s</td><td>%s</td></tr>' % (t["muted"], a, e(b)) for a, b in rows)
        desc = e(m.desc[:1200]).replace("\n", "<br>")
        self.details.setHtml('<table cellspacing="3">%s</table><p style="color:%s">%s</p>' % (body, t["muted"], desc or "No description."))


# ----------------------------------------------------------------- diagnose
class _JobSignals(QObject):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn, sig):
        super().__init__()
        self.fn, self.sig = fn, sig

    def run(self):
        try:
            self.sig.done.emit(self.fn(self.sig.progress.emit))
        except Exception as e:  # noqa
            self.sig.failed.emit(str(e))


def run_job(owner, fn, on_done, on_fail=None, on_progress=None):
    """Run fn(progress) off the UI thread. Callbacks come back on the UI thread."""
    sig = _JobSignals()
    jobs = owner.__dict__.setdefault("_jobs", [])
    jobs.append(sig)
    sig.done.connect(lambda r: (jobs.remove(sig), on_done(r)))
    sig.failed.connect(lambda m: (jobs.remove(sig), (on_fail or (lambda _m: None))(m)))
    if on_progress:
        sig.progress.connect(on_progress)
    QThreadPool.globalInstance().start(_Job(fn, sig))


VERDICT = {"cause": ("missing", "Likely cause"), "suspect": ("outdated", "Suspect"), "noise": ("skipped", "Noise")}
SEV = {"error": ("conflict", "Problem"), "warn": ("outdated", "Warning"), "info": ("enable", "Tip")}


class LogTab(QWidget):
    def __init__(self, st, win, page):
        super().__init__()
        self.st, self.win, self.page, self.A = st, win, page, None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(10)
        bar = QHBoxLayout()
        self.src = QComboBox()
        self.src.addItem("Player.log (latest run)", "Player.log")
        self.src.addItem("Player-prev.log (the run before)", "Player-prev.log")
        self.src.addItem("Choose a file…", "")
        bar.addWidget(self.src)
        go = pbtn("Analyze log", "search", primary=True, tip="Read the log and trace each error back to the mod that caused it")
        go.clicked.connect(self.analyze)
        bar.addWidget(go)
        op = tbtn("Open log", "folder", "Open the log file in your editor")
        op.clicked.connect(lambda: os.startfile(str(self.log_path())) if self.log_path().exists() else None)
        bar.addWidget(op)
        rules = tbtn("Edit rules", "sliders", "Change how errors are scored and what the advisor is told")
        rules.setPopupMode(QToolButton.InstantPopup)
        rm = QMenu(self)
        rm.addAction("Error scoring (diagnose_rules.json)", lambda: self.open_rule_file(diagnose.RULES_FILE, diagnose.ensure_files))
        rm.addAction("Advisor instructions (advisor_prompt.txt)", lambda: self.open_rule_file(advisor.PROMPT_FILE, advisor.ensure_files))
        rm.addSeparator()
        rm.addAction("Reset both to the defaults", self.reset_rules)
        rules.setMenu(rm)
        bar.addWidget(rules)
        bar.addStretch(1)
        self.status = label("", "muted")
        bar.addWidget(self.status)
        v.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setOpenExternalLinks(False)
        box = QVBoxLayout()
        box.addWidget(self.summary)
        box.setContentsMargins(16, 12, 16, 12)
        self.sumcard = card(box)
        self.sumcard.hide()
        self.top_w = QWidget()
        tv = QVBoxLayout(self.top_w)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(10)
        tv.addWidget(self.sumcard)
        av = QVBoxLayout()
        av.setContentsMargins(16, 12, 16, 12)
        av.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label("Advisor", "h2"))
        self.adv_src = label("", "muted")
        top.addWidget(self.adv_src)
        top.addStretch(1)
        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.setMinimumWidth(190)
        self.model_box.lineEdit().setPlaceholderText("model, e.g. qwen2.5:7b")
        self.model_box.setCurrentText(st.s.get("ollama_model", ""))
        self.model_box.setToolTip("A model you downloaded with Ollama. It runs on this computer only.")
        self.ask_btn = pbtn("Explain with local model", "wand",
                            tip="A small model on this PC rewrites the explanation in plain language. It cannot change the recommendations, and it unloads when done.")
        self.ask_btn.clicked.connect(self.ask_model)
        top.addWidget(self.model_box)
        top.addWidget(self.ask_btn)
        av.addLayout(top)
        self.adv_text = QLabel()
        self.adv_text.setWordWrap(True)
        self.adv_text.setTextFormat(Qt.RichText)
        av.addWidget(self.adv_text)
        self.adv_rows = QVBoxLayout()
        self.adv_rows.setSpacing(6)
        av.addLayout(self.adv_rows)
        self.adv_card = card(av)
        self.adv_card.hide()
        tv.addWidget(self.adv_card)
        tv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.top_w)
        self.split = QSplitter(Qt.Vertical)
        self.split.addWidget(scroll)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Verdict", "Mod", "Errors", "Most common error"])
        set_table(self.table, 30)
        self.table.setItemDelegateForColumn(0, ChipDelegate(self.table))
        for i, w in enumerate((130, 300, 70)):
            self.table.setColumnWidth(i, w)
        self.table.currentCellChanged.connect(lambda r, *_: self.pick(r))
        bot = QWidget()
        bv = QVBoxLayout(bot)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(10)
        bv.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.noise = QCheckBox("Show noise (patch messages)")
        self.noise.toggled.connect(self.fill)
        row.addWidget(self.noise)
        row.addStretch(1)
        self.b_sel = pbtn("Untick selected", "close", ghost=True)
        self.b_sel.clicked.connect(self.untick_selected)
        self.b_cause = pbtn("Untick likely causes", "check", primary=True)
        self.b_cause.clicked.connect(self.untick_causes)
        row.addWidget(self.b_sel)
        row.addWidget(self.b_cause)
        bv.addLayout(row)
        self.split.addWidget(bot)
        self.split.setSizes([430, 300])
        self.split.setChildrenCollapsible(False)
        v.addWidget(self.split, 1)
        self.shown = []

    def log_path(self):
        name = self.src.currentData()
        base = diagnose.default_log_dir()
        return base / name if name else Path("")

    def analyze(self):
        if not self.src.currentData():
            f, _ = QFileDialog.getOpenFileName(self, "Pick a RimWorld log", str(diagnose.default_log_dir()), "Logs (*.log *.txt)")
            if not f:
                return
            path = Path(f)
        else:
            path = self.log_path()
        if not path.exists():
            QMessageBox.information(self, "No log found", "There's no log at\n%s\n\nStart RimWorld once, then try again." % path)
            return
        self.status.setText("Reading the log…")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def work(progress):
            idx = self.page.get_index(progress)
            return diagnose.analyze_log(path, self.st.mods, idx)
        run_job(self, work, self.done, self.failed,
                lambda a, b: self.status.setText("Indexing mod files… %d of %d" % (a, b)))

    def failed(self, msg):
        QApplication.restoreOverrideCursor()
        self.status.setText("")
        QMessageBox.critical(self, "Could not read the log", msg)

    def done(self, A):
        QApplication.restoreOverrideCursor()
        self.A = A
        self.status.setText("%d errors, %d warnings" % (A.n_err, A.n_warn))
        mods, e = self.st.mods, ""
        parts = []
        causes = [r for r in A.rows if r.verdict == "cause"]
        if A.fatal:
            names = ", ".join("<b>%s</b>" % html.escape(mods[p].name) for p in A.fatal["pids"] if p in mods) or "an unknown mod"
            parts.append("The colony failed to load at %s. The first fatal error came from %s: <i>%s</i>" % (
                A.fatal["time"], names, html.escape(A.fatal["headline"][:150])))
        elif causes:
            parts.append("No fatal map error, but these mods failed to start: " + ", ".join(
                "<b>%s</b>" % html.escape(mods[r.pid].name) for r in causes[:4]))
        else:
            parts.append("No fatal errors found in this log.")
        started = [r for r in causes if "instantiate" in r.kinds and r.pid not in diagnose.ESSENTIAL]
        if started:
            parts.append("Failed to start: " + ", ".join(html.escape(mods[r.pid].name) for r in started[:6]) + ".")
        parts += [html.escape(n) for n in A.notes]
        self.summary.setText("<br><br>".join(parts))
        self.sumcard.show()
        self.fill()
        self.show_advice(advisor.rule_advice(A, mods, self.page.scan.found, self.st.updated_map()))

    def fill(self, *_):
        if not self.A:
            return
        rows = [r for r in self.A.rows if r.pid in self.st.mods and (self.noise.isChecked() or r.verdict != "noise")]
        self.shown = rows
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            kind, text = VERDICT[r.verdict]
            a = QTableWidgetItem()
            a.setData(FLAGS, [(kind, text)])
            self.table.setItem(i, 0, a)
            name = self.st.mods[r.pid].name + ("  (essential)" if r.pid in diagnose.ESSENTIAL else "  (framework)" if r.lib else "")
            self.table.setItem(i, 1, QTableWidgetItem(name))
            self.table.setItem(i, 2, QTableWidgetItem(str(r.count)))
            head = r.heads[0]
            it = QTableWidgetItem(head[0])
            it.setToolTip("\n".join("%d x  %s   (line %d)" % (c, h, ln) for h, c, ln in r.heads[:6]))
            self.table.setItem(i, 3, it)

    def pick(self, r):
        if 0 <= r < len(self.shown):
            self.st.select(self.shown[r].pid)

    def open_rule_file(self, path, ensure):
        ensure()
        if path.exists():
            os.startfile(str(path))
            self.win.toast("Edit and save the file, then analyze the log again. Changes apply on the next run.")

    def reset_rules(self):
        if QMessageBox.question(self, "Reset rules", "Replace both rule files with the built-in defaults?") != QMessageBox.Yes:
            return
        for f in (diagnose.RULES_FILE, advisor.PROMPT_FILE):
            f.unlink(missing_ok=True)
        diagnose.ensure_files()
        advisor.ensure_files()
        self.win.toast("Rules are back to the defaults")

    # ---- advisor
    def show_advice(self, adv):
        mods = self.st.mods
        self.adv_src.setText("built-in rules" if adv.source == "rules" else "AI explanation (%s). Recommendations come from the rules." % adv.source)
        steps = "".join("<li>%s</li>" % html.escape(s) for s in adv.steps)
        self.adv_text.setText("%s%s" % (html.escape(adv.summary), "<ol style='margin-top:6px'>%s</ol>" % steps if steps else ""))
        while self.adv_rows.count():
            it = self.adv_rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for a in adv.actions:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            conf = {"high": "missing", "medium": "outdated", "low": "skipped"}[a.confidence]
            chip = QLabel("%s confidence" % a.confidence)
            chip.setStyleSheet("color:%s; font-weight:600" % theme.cur[theme.KIND_COLOR[conf]])
            chip.setFixedWidth(120)
            h.addWidget(chip)
            verb = {"untick": "Untick", "update": "Update", "reorder": "Reorder", "check": "Check", "keep": "Keep"}[a.action]
            t = QLabel("<b>%s</b> %s: %s" % (verb, html.escape(mods[a.pid].name), html.escape(a.why)))
            t.setWordWrap(True)
            h.addWidget(t, 1)
            b = pbtn("Untick" if a.action == "untick" else "Show", ghost=True)
            if a.action == "untick":
                b.clicked.connect(lambda _=False, p=a.pid: (self.st.set_checked([p], False), self.win.toast("Unticked %s" % mods[p].name)))
            else:
                b.clicked.connect(lambda _=False, p=a.pid: self.win.show_mod(p))
            h.addWidget(b)
            self.adv_rows.addWidget(row)
        ids = [a.pid for a in adv.actions if a.action == "untick"]
        if len(ids) > 1:
            allb = pbtn("Untick all %d recommended" % len(ids), "check", primary=True)
            allb.clicked.connect(lambda: self.win.toast("Unticked %d mods. Apply and test again." % self.st.set_checked(ids, False)))
            self.adv_rows.addWidget(allb, 0, Qt.AlignLeft)
        self.adv_card.show()

    def ask_model(self):
        if not self.A:
            self.win.toast("Analyze a log first")
            return
        st = self.st
        url, wanted = st.s.get("ollama_url", advisor.DEFAULT_URL), self.model_box.currentText().strip()
        upd = st.updated_map()
        ctx, cand = advisor.build_context(self.A, st.mods, self.page.scan.found, st.target, st.n_ticked(), upd)
        base = advisor.rule_advice(self.A, st.mods, self.page.scan.found, upd)
        cand.update({a.pid: st.mods[a.pid].name for a in base.actions})
        self.ask_btn.setEnabled(False)
        self.adv_src.setText("asking the model… it reloads each time, so allow up to two minutes")

        def work(progress):
            models = advisor.list_models(url)
            if not models:
                raise OSError("Ollama is running but has no models yet.")
            model = advisor.pick_model(models, wanted)
            return advisor.ask(url, model, ctx, cand, base), models
        run_job(self, work, self.model_done, self.model_failed)

    def model_done(self, res):
        adv, models = res
        self.ask_btn.setEnabled(True)
        self.model_box.clear()
        self.model_box.addItems(models)
        self.model_box.setCurrentText(adv.source)
        self.st.s["ollama_model"] = adv.source
        core.save_settings(self.st.s)
        self.show_advice(adv)

    def model_failed(self, msg):
        self.ask_btn.setEnabled(True)
        self.adv_src.setText("built-in rules (model unavailable)")
        QMessageBox.information(
            self, "Local model not ready",
            "%s\n\nTo set it up:\n1. Install Ollama from ollama.com (or run: winget install Ollama.Ollama)\n"
            "2. Download a model: ollama pull qwen2.5:7b\n3. Leave Ollama running, then press Ask again.\n\n"
            "The built-in advice above still works without it." % msg)

    def picked_pids(self):
        return [self.shown[i.row()].pid for i in self.table.selectionModel().selectedRows() if i.row() < len(self.shown)]

    def untick_selected(self):
        ids = [p for p in self.picked_pids() if p not in diagnose.ESSENTIAL]
        n = self.st.set_checked(ids, False)
        self.win.toast("Unticked %d mods" % n if n else "Nothing to untick")

    def untick_causes(self):
        if not self.A:
            self.win.toast("Analyze a log first")
            return
        ids = [r.pid for r in self.A.rows if r.verdict == "cause" and r.pid not in diagnose.ESSENTIAL]
        n = self.st.set_checked(ids, False)
        self.win.toast("Unticked %d likely causes. Apply and test again." % n if n else "No likely causes to untick")


class ScanTab(QWidget):
    def __init__(self, st, win, page):
        super().__init__()
        self.st, self.win, self.page, self.found = st, win, page, []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(10)
        bar = QHBoxLayout()
        go = pbtn("Scan my mods", "shield", primary=True, tip="Check the ticked list without starting the game")
        go.clicked.connect(self.run)
        bar.addWidget(go)
        self.deep = QCheckBox("Also compare defs between mods (slower)")
        self.deep.setToolTip("Reads every ticked mod's Defs folder to find mods that define the same things.")
        bar.addWidget(self.deep)
        bar.addStretch(1)
        self.status = label("", "muted")
        bar.addWidget(self.status)
        v.addLayout(bar)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        v.addWidget(self.bar)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Level", "Finding", "Detail"])
        set_table(self.table, 30)
        self.table.setItemDelegateForColumn(0, ChipDelegate(self.table))
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 240)
        self.table.currentCellChanged.connect(lambda r, *_: self.pick(r))
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(label("Fixes are suggestions. Nothing changes until you press the button, and undo covers it.", "caption"))
        row.addStretch(1)
        self.fix_btn = pbtn("Apply fix to selected", "check", primary=True)
        self.fix_btn.clicked.connect(self.apply_fix)
        row.addWidget(self.fix_btn)
        v.addLayout(row)

    def run(self):
        st = self.st
        deep = self.deep.isChecked()
        order = st.order_ids() if deep else []
        checked, broken, target = dict(st.checked), dict(st.broken), st.target
        self.bar.setRange(0, 0)
        self.bar.show()
        self.status.setText("Scanning…")

        def work(progress):
            idx = self.page.get_index(lambda a, b: progress(a, b))
            out = diagnose.quick_scan(st.mods, checked, broken, target, idx)
            if deep:
                out += diagnose.def_overlap(st.mods, checked, order, lambda a, b: progress(a, b))
            return out
        run_job(self, work, self.done, self.failed, self.prog)

    def prog(self, a, b):
        self.bar.setRange(0, max(b, 1))
        self.bar.setValue(a)

    def failed(self, msg):
        self.bar.hide()
        self.status.setText("")
        QMessageBox.critical(self, "Scan failed", msg)

    def done(self, found):
        self.bar.hide()
        order = {"error": 0, "warn": 1, "info": 2}
        self.found = sorted(found, key=lambda f: order[f.sev])
        n = Counter(f.sev for f in self.found)
        self.status.setText("%d problems, %d warnings, %d tips" % (n["error"], n["warn"], n["info"]) if self.found else "Nothing found")
        self.table.setRowCount(len(self.found))
        for i, f in enumerate(self.found):
            kind, text = SEV[f.sev]
            a = QTableWidgetItem()
            a.setData(FLAGS, [(kind, text)])
            self.table.setItem(i, 0, a)
            self.table.setItem(i, 1, QTableWidgetItem(f.title))
            d = QTableWidgetItem(f.detail)
            d.setToolTip(f.detail + ("\n\nFix: %s %d mods" % (f.fix[0], len(f.fix[1])) if f.fix else ""))
            self.table.setItem(i, 2, d)
        if not self.found:
            self.win.toast("The scan found nothing to worry about")

    def pick(self, r):
        if 0 <= r < len(self.found) and self.found[r].pids:
            self.st.select(self.found[r].pids[0])

    def apply_fix(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        ticks, unticks = [], []
        for r in rows:
            f = self.found[r] if r < len(self.found) else None
            if f and f.fix:
                (ticks if f.fix[0] == "tick" else unticks).extend(f.fix[1])
        if not ticks and not unticks:
            self.win.toast("Select a finding that has a fix")
            return
        n = self.st.set_checked(unticks, False) + self.st.set_checked(ticks, True)
        self.win.toast("Applied %d changes. Scan again to check." % n)


class CrashTab(QWidget):
    """Narrows a crash or black screen down to one mod by testing the start of your load order.

    Three stages: search (halve the list), confirm (the culprit with only what it needs), and, when the
    confirmation passes, partner search (what else has to be loaded for it to break)."""

    def __init__(self, st, win, page):
        super().__init__()
        self.st, self.win, self.page, self.b, self.backup = st, win, page, None, None
        self.removed, self.mode, self.culprit, self.partner, self.ess, self.confirm_list = [], "search", None, None, 1, []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        # intro
        w = QWidget()
        il = QVBoxLayout(w)
        il.setSpacing(12)
        il.addWidget(label("Find the mod that breaks your game", "h2"))
        il.addWidget(label("The game crashes, hangs or shows a black screen, but you don't know which of your mods did it. "
                           "This writes the first half of your load order to ModsConfig.xml, you start the game and load your colony, "
                           "then tell the app whether the problem is still there. Each answer halves the search, so about 10 rounds "
                           "cover 900 mods.", "muted", True))
        il.addWidget(label("Your original ModsConfig.xml is backed up first and can be restored at any time. "
                           "Mods that others depend on are always loaded before the ones that need them, so every test list is valid.", "muted", True))
        il.addWidget(label("When it finds a mod, it confirms the result by testing that mod with only what it needs. "
                           "If the problem does not show up there, the mod breaks only next to another one, and the app can look for the other mod.", "caption", True))
        self.start_btn = pbtn("Start the search", "play", primary=True)
        self.start_btn.clicked.connect(self.start)
        il.addWidget(self.start_btn, 0, Qt.AlignLeft)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        bb = QHBoxLayout()
        bb.addWidget(self.banner, 1)
        rb = pbtn("Restore my list", "refresh")
        rb.clicked.connect(self.restore_left_over)
        bb.addWidget(rb)
        bb.setContentsMargins(14, 10, 14, 10)
        self.banner_card = card(bb)
        self.banner_card.hide()
        il.addWidget(self.banner_card)
        il.addStretch(1)
        self.stack.addWidget(w)
        # round
        w = QWidget()
        rl = QVBoxLayout(w)
        rl.setSpacing(12)
        self.round_title = label("", "h2")
        self.round_body = label("", "muted", True)
        self.prog = QProgressBar()
        self.prog.setTextVisible(False)
        rl.addWidget(self.round_title)
        rl.addWidget(self.round_body)
        rl.addWidget(self.prog)
        row = QHBoxLayout()
        self.launch = pbtn("Launch RimWorld", "play", ghost=True)
        self.launch.clicked.connect(lambda: open_url("steam://rungameid/" + core.APPID))
        self.bad_btn = pbtn("Still broken", "close", primary=True)
        self.good_btn = pbtn("Works fine", "check")
        self.unsure_btn = pbtn("Not sure, test again", "refresh", ghost=True,
                               tip="Use this if the game crashed in a different way or you could not tell. It reloads the same test list.")
        self.bad_btn.clicked.connect(lambda: self.answer(True))
        self.good_btn.clicked.connect(lambda: self.answer(False))
        self.unsure_btn.clicked.connect(self.unsure)
        for b in (self.launch, self.bad_btn, self.good_btn, self.unsure_btn):
            row.addWidget(b)
        row.addStretch(1)
        stop = pbtn("Stop and restore my list", "refresh", ghost=True)
        stop.clicked.connect(self.stop)
        row.addWidget(stop)
        rl.addLayout(row)
        self.round_hint = label("Close RimWorld before you answer. If the game won't even start with this list, that counts as 'Still broken'.", "caption", True)
        rl.addWidget(self.round_hint)
        rl.addStretch(1)
        self.stack.addWidget(w)
        # result
        w = QWidget()
        xl = QVBoxLayout(w)
        xl.setSpacing(12)
        self.res_title = label("", "h2", True)
        self.res_body = label("", "muted", True)
        xl.addWidget(self.res_title)
        xl.addWidget(self.res_body)
        row = QHBoxLayout()
        self.r_untick = pbtn("Untick it and restore my list", "check", primary=True)
        self.r_alt = pbtn("Untick the other mod instead", "check")
        self.r_partner = pbtn("Find the other mod", "search")
        self.r_more = pbtn("Look for another problem", "search", ghost=True)
        self.r_keep = pbtn("Just restore my list", "refresh", ghost=True)
        self.r_untick.clicked.connect(lambda: self.finish([self.culprit]))
        self.r_alt.clicked.connect(lambda: self.finish([self.partner]))
        self.r_partner.clicked.connect(self.start_partner)
        self.r_keep.clicked.connect(lambda: self.finish([]))
        self.r_more.clicked.connect(self.more)
        for b in (self.r_untick, self.r_alt, self.r_partner, self.r_more, self.r_keep):
            row.addWidget(b)
        row.addStretch(1)
        xl.addLayout(row)
        xl.addStretch(1)
        self.stack.addWidget(w)
        self.check_left_over()

    # ---- safety net: a session left open when the app closed
    def check_left_over(self):
        f = self.st.s.get("crash_backup")
        left = bool(f and Path(f).exists() and self.b is None)
        self.banner.setText("A crash search was left open. Your ModsConfig.xml may still hold a test list. "
                            "Restore your list before starting another search.")
        self.banner_card.setVisible(left)
        self.start_btn.setEnabled(not left)

    def restore_left_over(self):
        if self.end_session():
            self.b, self.mode = None, "search"
            self.check_left_over()

    def game_closed(self):
        """Every write to ModsConfig.xml and every restore goes through here. RimWorld rewrites that file when it exits,
        so touching it while the game runs would be lost or would spoil the test."""
        if core.game_running():
            QMessageBox.warning(self, "RimWorld is running", "Close RimWorld first. The game rewrites ModsConfig.xml when it exits, "
                                "so changing it now would be lost or would spoil the test." + NOT_SURE)
            return False
        return True

    def clear_session(self):
        self.st.s.pop("crash_backup", None)
        core.save_settings(self.st.s)

    def restore(self, f):
        """Put the original file back. Returns 'ok', 'blocked' (game running), 'missing' (no backup file) or 'failed'."""
        if not self.game_closed():
            return "blocked"
        if not f or not Path(f).exists():
            return "missing"
        try:
            shutil.copy2(f, self.st.s["config_path"])
        except OSError as e:
            QMessageBox.critical(self, "Could not restore", "%s\n\nYour backup is still at:\n%s" % (e, f))
            return "failed"
        self.st.sync_config_hash()
        self.win.toast("Your ModsConfig.xml is back as it was")
        return "ok"

    def end_session(self):
        """Restore the original list and close the session record. The record stays until the restore really worked,
        so the Restore button keeps pointing at the right backup. Returns True when the session is closed."""
        r = self.restore(self.st.s.get("crash_backup") or self.backup)
        if r in ("blocked", "failed"):
            return False
        if r == "missing":
            QMessageBox.warning(self, "Backup not found", "The backup of your original ModsConfig.xml is gone, so there is nothing to restore. "
                                "ModsConfig.xml may still hold a test list. Pick an older copy on the Profiles page, or use "
                                "'From current ModsConfig' on the Mods page.")
        self.clear_session()
        return True

    def write_list(self, ids):
        """Write a test list. False when the game is running or the write failed."""
        if not self.game_closed():
            return False
        try:
            core.write_config(self.st.s["config_path"], ids, core.game_version_str(self.st.s["game_dir"]))
        except Exception as e:  # noqa
            QMessageBox.critical(self, "Could not write the test list", str(e))
            return False
        self.st.sync_config_hash()
        return True

    # ---- flow
    def start(self):
        st = self.st
        old = st.s.get("crash_backup")
        if old:
            if Path(old).exists():  # never bury the original backup under a new session
                QMessageBox.information(self, "Finish the last search first",
                                        "A previous crash search was never finished, so ModsConfig.xml may still hold a test list. "
                                        "Press 'Restore my list' on this page first. Starting now would bury your original file.")
                self.check_left_over()
                return
            self.clear_session()  # its backup is gone, so there is nothing left to protect
        if not self.game_closed():
            return
        plan = st.apply_plan(True)
        order = [p for p, _ in plan.order]
        self.ess = sum(1 for _, t in plan.order if t <= 2)
        if len(order) - self.ess < 2:
            QMessageBox.information(self, "Nothing to search", "Tick some mods first.")
            return
        if QMessageBox.question(self, "Start the search",
                                "This overwrites ModsConfig.xml with test lists until you finish or stop. "
                                "Your current file is backed up first.\n\nStart?") != QMessageBox.Yes:
            return
        self.backup = core.backup_config(st.s["config_path"])
        if not self.backup:
            QMessageBox.critical(self, "Could not back up ModsConfig.xml", "Without a backup the search would not be safe, so it did not start.")
            return
        st.s["crash_backup"] = str(self.backup)
        core.save_settings(st.s)
        self.b = diagnose.Bisect(order, self.ess)
        self.removed, self.mode, self.partner = [], "search", None
        self.next_round()

    def show_round(self, title, body, prog=None):
        self.round_title.setText(title)
        self.round_body.setText(body)
        if prog:
            self.prog.setRange(0, max(prog[1], 1))
            self.prog.setValue(prog[0])
        self.stack.setCurrentIndex(1)

    def next_round(self):
        size = self.b.next_size()
        if size is None:
            return self.after_search()
        if not self.write_list(self.b.test_list(size)):
            return
        total = self.b.total_rounds()
        last = self.st.mods[self.b.order[size - 1]].name
        what = "Looking for the other mod" if self.mode == "partner" else "Round %d of about %d" % (self.b.rounds + 1, total)
        self.show_round("%s: testing the first %d mods" % (what, size),
                        "RimWorld now has the first %d mods of your load order (up to %s)%s. Start the game, load your colony "
                        "and see if the problem is still there." % (
                            size, last, " plus %s and what it needs" % self.st.mods[self.culprit].name if self.mode == "partner" else ""),
                        (min(self.b.rounds, total), total))

    def answer(self, broken):
        if core.game_running():
            QMessageBox.information(self, "RimWorld is running", "Close the game, then answer." + NOT_SURE)
            return
        if self.mode == "confirm":
            return self.show_result(confirmed=broken)
        self.b.answer(self.b.next_size(), broken)
        self.next_round()

    def unsure(self):
        ids = self.confirm_list if self.mode == "confirm" else self.b.test_list(self.b.next_size())
        if self.write_list(ids):
            self.round_hint.setText("Same list again. Close the game, launch it and look once more. If it keeps behaving differently, "
                                    "stop and restore, then try again when the problem is easier to reproduce.")

    def after_search(self):
        if self.mode == "partner":
            self.partner = self.b.culprit()
            return self.show_result(partner=True)
        self.culprit = self.b.culprit()
        self.begin_confirm()

    def begin_confirm(self):
        """Test the culprit with only the essentials and what it needs."""
        c, mods = self.culprit, self.st.mods
        full = self.b.full
        reqs = core.all_requirements(c, mods, self.st.broken)
        keep = set(full[:self.ess]) | reqs | {c}
        self.confirm_list = [p for p in full if p in keep]
        if not self.write_list(self.confirm_list):
            return
        self.mode = "confirm"
        self.show_round("Confirm: testing %s on its own" % mods[c].name,
                        "RimWorld now has only the essentials, what %s needs and %s itself (%d mods). Does the problem still happen?" % (
                            mods[c].name, mods[c].name, len(self.confirm_list)),
                        (self.b.rounds, self.b.rounds + 1))

    def start_partner(self):
        """It broke with everything before it but not alone: find the mod it needs company from."""
        c, mods = self.culprit, self.st.mods
        full = self.b.full
        before = full[:full.index(c)]
        extra = core.all_requirements(c, mods, self.st.broken) | {c}
        self.b = diagnose.Bisect(before, self.ess, extra=extra, full=full)
        self.mode = "partner"
        self.next_round()

    def show_result(self, confirmed=None, partner=False):
        mods = self.st.mods
        c, nm = self.culprit, mods[self.culprit].name
        self.r_alt.hide()
        self.r_partner.hide()
        self.r_more.show()
        if partner:
            pn = mods[self.partner].name if self.partner in mods else self.partner
            self.res_title.setText("It breaks when %s and %s are both loaded" % (nm, pn))
            self.res_body.setText("%s works with only what it needs, and fails once %s is added. Untick either one. "
                                  "If you are unsure which, keep the one you care about more." % (nm, pn))
            self.r_untick.setText("Untick %s" % nm[:28])
            self.r_alt.setText("Untick %s" % pn[:28])
            self.r_alt.show()
            self.r_more.hide()
        elif confirmed:
            self.res_title.setText("Confirmed: %s breaks the game" % nm)
            self.res_body.setText("Without the mods after it the game works, and %s still breaks it when loaded with only what it needs. "
                                  "Untick it, or look for an update." % nm)
            self.r_untick.setText("Untick it and restore my list")
        else:
            self.res_title.setText("Likely an interaction: %s breaks only next to another mod" % nm)
            self.res_body.setText("The problem starts when %s is added, but it did not show up with %s on its own. "
                                  "Another mod is involved. The app can look for it, or you can untick %s now." % (nm, nm, nm))
            self.r_untick.setText("Untick %s and restore" % nm[:24])
            self.r_partner.show()
        self.stack.setCurrentIndex(2)

    def finish(self, to_untick):
        if not self.end_session():
            return
        ids = [p for p in to_untick if p]
        if ids:
            n = self.st.set_checked(ids, False)
            self.win.toast("Unticked %s and restored your ModsConfig.xml. Apply when ready." % ", ".join(self.st.mods[p].name for p in ids[:2]))
        self.b, self.mode = None, "search"
        self.stack.setCurrentIndex(0)
        self.check_left_over()

    def more(self):
        """Take the culprit out and check whether the rest of the list still has the problem."""
        c = self.culprit
        rest = [p for p in self.b.full if p != c]
        if not self.write_list(rest):
            return
        self.removed.append(c)
        self.b = diagnose.Bisect(rest, self.ess)
        self.mode = "verify"
        self.show_round("Check: your full list without %s" % self.st.mods[c].name,
                        "RimWorld now has every mod except those already found (%d). Does the problem still happen?" % len(self.removed),
                        (0, 1))
        self.good_btn.setText("Works fine, I'm done")
        self.good_btn.clicked.disconnect()
        self.good_btn.clicked.connect(self.verify_good)
        self.bad_btn.clicked.disconnect()
        self.bad_btn.clicked.connect(self.verify_bad)

    def _reset_buttons(self):
        for b, fn in ((self.good_btn, lambda: self.answer(False)), (self.bad_btn, lambda: self.answer(True))):
            b.clicked.disconnect()
            b.clicked.connect(fn)
        self.good_btn.setText("Works fine")

    def verify_good(self):
        self.finish_many()

    def verify_bad(self):
        self._reset_buttons()
        self.mode = "search"
        self.next_round()

    def finish_many(self):
        if not self.end_session():
            return
        self._reset_buttons()
        n = self.st.set_checked(self.removed, False)
        self.win.toast("Unticked %d mods that caused problems. Apply when ready." % n)
        self.b, self.mode = None, "search"
        self.stack.setCurrentIndex(0)
        self.check_left_over()

    def stop(self):
        if not self.end_session():
            return
        if self.mode == "verify":
            self._reset_buttons()
        self.b, self.mode = None, "search"
        self.stack.setCurrentIndex(0)
        self.check_left_over()


CHANGE = {"updated": ("outdated", "Updated"), "new": ("enable", "New"), "enabled": ("enable", "Ticked"),
          "disabled": ("skipped", "Unticked"), "removed": ("skipped", "Removed"), "moved": ("skipped", "Moved")}


class ChangesTab(QWidget):
    """What changed since the setup last worked. Steam's update times plus your ticks and order."""

    def __init__(self, st, win, page):
        super().__init__()
        self.st, self.win, self.page, self.rows, self.snaps = st, win, page, [], []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(10)
        bar = QHBoxLayout()
        self.base = QComboBox()
        self.base.setMinimumWidth(330)
        self.base.currentIndexChanged.connect(self.refresh)
        bar.addWidget(label("Compare with", "muted"))
        bar.addWidget(self.base)
        bar.addStretch(1)
        self.mark_btn = pbtn("Mark current setup as working", "check", primary=True,
                             tip="Save your ticked mods, their order and Steam's update times as a baseline")
        self.mark_btn.clicked.connect(self.mark)
        self.back_btn = pbtn("Roll back my list", "refresh", ghost=True,
                             tip="Restore the ticks and order from the selected baseline. Mod files stay as they are.")
        self.back_btn.clicked.connect(self.rollback)
        bar.addWidget(self.back_btn)
        bar.addWidget(self.mark_btn)
        v.addLayout(bar)
        self.info = label("", "muted", True)
        v.addWidget(self.info)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Change", "Mod", "When", "Detail", "Notes"])
        set_table(self.table, 30)
        for i, w in enumerate((110, 300, 110, 330)):
            self.table.setColumnWidth(i, w)
        self.table.setItemDelegateForColumn(0, ChipDelegate(self.table))
        self.table.setItemDelegateForColumn(4, ChipDelegate(self.table))
        self.table.currentCellChanged.connect(lambda r, *_: self.pick(r))
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(label("Steam keeps only the newest version of each mod, so the app can't put old mod files back. "
                            "It shows what updated, and can roll back your list and order.", "caption", True), 1)
        self.b_sel = pbtn("Untick selected", "close", ghost=True)
        self.b_sel.clicked.connect(self.untick)
        row.addWidget(self.b_sel)
        v.addLayout(row)

    def showEvent(self, e):
        self.reload_bases()
        super().showEvent(e)

    def reload_bases(self):
        self.snaps = tracker.list_good()
        keep = self.base.currentIndex()
        self.base.blockSignals(True)
        self.base.clear()
        for s in self.snaps:
            self.base.addItem("Working setup from %s, %s (%d mods)" % (tracker.fmt_date(s["time"]), time.strftime("%H:%M", time.localtime(s["time"])), len(s["order"])), s["time"])
        self.base.addItem("No baseline: just show mods updated in the last 7 days", 0)
        self.base.setCurrentIndex(keep if 0 <= keep < self.base.count() else 0)
        self.base.blockSignals(False)
        self.refresh()

    def current_snap(self):
        i = self.base.currentIndex()
        return self.snaps[i] if 0 <= i < len(self.snaps) else None

    def refresh(self, *_):
        st = self.st
        if not st.mods:
            return
        snap = self.current_snap()
        self.back_btn.setEnabled(bool(snap))
        order = st.order_ids()
        if snap:
            self.rows = tracker.compare(snap, order, st.updated, st.mods)
            n = Counter(r["kind"] for r in self.rows)
            self.info.setText("Since %s: %d updated, %d new, %d ticked, %d unticked, %d moved." % (
                tracker.fmt_date(snap["time"]), n["updated"], n["new"], n["enabled"], n["disabled"] + n["removed"], n["moved"]))
        else:
            self.rows = tracker.recent(st.updated, st.mods, {p for p, v in st.checked.items() if v})
            self.info.setText("No baseline yet. These are the ticked mods that updated in the last 7 days. Once the game runs well, "
                              "press 'Mark current setup as working' so later you can see exactly what changed.")
        self.fill()
        if self.page.index is None and st.mods:
            run_job(self, lambda progress: self.page.get_index(progress), lambda _r: self.fill(), None)

    def notes(self, pid):
        out = []
        A = self.page.log.A
        if A and any(e.pid == pid and e.verdict != "noise" for e in A.rows):
            out.append(("missing", "In log errors"))
        if self.page.index and any(pid in v for k, v in self.page.index.items() if k not in ("0harmony",)):
            out.append(("outdated", "Has code"))
        return out

    def fill(self, *_):
        st = self.st
        rows = sorted(self.rows, key=lambda r: (not any(k == "missing" for k, _ in self.notes(r["pid"])) or r["kind"] != "updated",
                                                0 if r["kind"] == "updated" else 1, -(r["ts"] or 0)))
        self.shown = rows
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            kind, text = CHANGE[r["kind"]]
            a = QTableWidgetItem()
            a.setData(FLAGS, [(kind, text)])
            self.table.setItem(i, 0, a)
            self.table.setItem(i, 1, QTableWidgetItem(st.mods[r["pid"]].name if r["pid"] in st.mods else r["pid"]))
            self.table.setItem(i, 2, QTableWidgetItem(tracker.fmt_ago(r["ts"]) if r["ts"] else ""))
            self.table.setItem(i, 3, QTableWidgetItem(r["detail"]))
            n = QTableWidgetItem()
            n.setData(FLAGS, self.notes(r["pid"]))
            self.table.setItem(i, 4, n)

    def pick(self, r):
        if 0 <= r < len(getattr(self, "shown", [])) and self.shown[r]["pid"] in self.st.mods:
            self.st.select(self.shown[r]["pid"])

    def mark(self):
        label_text, ok = QInputDialog.getText(self, "Mark as working", "Optional note (for example 'before the Anomaly update'):")
        if not ok:
            return
        snap = self.st.mark_good(label_text.strip())
        self.win.toast("Saved as working: %d mods, %s" % (len(snap["order"]), tracker.fmt_date(snap["time"])))
        self.reload_bases()

    def rollback(self):
        snap = self.current_snap()
        if snap and QMessageBox.question(self, "Roll back my list", "Restore the ticks and order from %s?\n\nMod files are not changed. "
                                         "You can undo this with Ctrl+Z." % tracker.fmt_date(snap["time"])) == QMessageBox.Yes:
            n = self.st.rollback_list(snap)
            self.win.toast("Restored %d mods from that setup. Apply when ready." % n)

    def untick(self):
        ids = [self.shown[i.row()]["pid"] for i in self.table.selectionModel().selectedRows() if i.row() < len(getattr(self, "shown", []))]
        n = self.st.set_checked([p for p in ids if p in self.st.mods], False)
        self.win.toast("Unticked %d mods" % n if n else "Nothing to untick")


class LiveTab(QWidget):
    """Follows Player.log while RimWorld starts, and says when something fatal happens."""
    status = Signal(str, bool)   # text for the bottom bar, whether it is bad news

    def __init__(self, st, win, page):
        super().__init__()
        self.st, self.win, self.page = st, win, page
        self.tail, self.watching, self.seen, self.absent, self.ticks, self.warned, self.started_at = None, False, False, 0, 0, False, 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(10)
        top = QHBoxLayout()
        self.state_lbl = label("Not watching", "h2")
        top.addWidget(self.state_lbl)
        top.addStretch(1)
        self.toggle = pbtn("Start watching", "play", primary=True, tip="Follow the game's log while it starts. Apply and launch does this for you.")
        self.toggle.clicked.connect(lambda: self.stop() if self.watching else self.start())
        top.addWidget(self.toggle)
        v.addLayout(top)
        self.counts = label("Press Start watching, then launch RimWorld. Fatal errors show up here as they happen.", "muted", True)
        v.addWidget(self.counts)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        bl = QHBoxLayout()
        bl.setContentsMargins(14, 10, 14, 10)
        bl.addWidget(self.banner, 1)
        self.b_good = pbtn("Mark as working", "check", primary=True)
        self.b_good.clicked.connect(self.mark_good)
        self.b_full = pbtn("Analyze full log", "search")
        self.b_full.clicked.connect(self.analyze)
        bl.addWidget(self.b_full)
        bl.addWidget(self.b_good)
        self.banner_card = card(bl)
        self.banner_card.hide()
        v.addWidget(self.banner_card)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Level", "Mod", "Message"])
        set_table(self.table, 30)
        for i, w in enumerate((90, 110, 240)):
            self.table.setColumnWidth(i, w)
        self.table.setItemDelegateForColumn(1, ChipDelegate(self.table))
        self.table.currentCellChanged.connect(lambda r, *_: self.pick(r))
        v.addWidget(self.table, 1)
        self.shown = []

    # ---- control
    def log_path(self):
        return diagnose.default_log_dir() / "Player.log"

    def start(self):
        if self.watching or not self.st.mods:
            return
        self.watching, self.seen, self.absent, self.ticks, self.warned, self.started_at = True, False, 0, 0, False, time.time()
        self.tail = None  # a new session starts from a clean slate
        self.table.setRowCount(0)
        self.banner_card.hide()
        self.toggle.setText("Stop watching")
        self.set_state("Getting ready…", False)

        def work(progress):
            return self.page.get_index(progress)
        run_job(self, work, self.index_ready, lambda m: self.stop(), None)

    def index_ready(self, idx):
        if not self.watching:
            return
        self.tail = diagnose.LogTail(self.log_path(), self.st.mods, idx)
        running = core.game_running()
        if not running and self.log_path().exists():  # skip a stale log from an earlier run
            self.tail.pos = self.log_path().stat().st_size
        self.set_state("Game running" if running else "Waiting for RimWorld to start…", False)
        self.seen = running
        self.timer.start()

    def stop(self, quiet=False):
        self.timer.stop()
        self.watching = False
        self.toggle.setText("Start watching")
        if not quiet:
            self.set_state("Not watching", False)
        self.status.emit("", False)

    def set_state(self, text, bad):
        self.state_lbl.setText(text)
        n = self.tail
        if n:
            self.counts.setText("%d errors, %d warnings, %d fatal. Fatal means a mod failed to start or the game failed during setup." % (n.n_err, n.n_warn, n.n_fatal))
        self.status.emit(("%s: %d errors" % ("Watching", n.n_err) if n and self.watching else ""), bool(n and n.n_fatal))

    # ---- polling
    def tick(self):
        t = self.tail
        self.ticks += 1
        new = t.poll()
        if new:
            self.fill()
            named = [(e, p) for e in new if e.fatal for p in e.pids if p in self.st.mods]
            pick = next(((e, p) for e, p in named if p not in diagnose.ESSENTIAL), None) or (named[0] if named else None)
            if pick and not self.warned:
                self.warned = True
                fatal, mod = pick[0], self.st.mods[pick[1]].name
                self.win.toast("%s failed: %s. Open Diagnose, Live log." % (mod, fatal.head[:70]), 9000)
        if self.ticks % 3 == 0:
            running = core.game_running()
            if running:
                self.seen, self.absent = True, 0
            elif self.seen:
                self.absent += 1
            elif time.time() - self.started_at > 300:
                self.stop()
                self.set_state("RimWorld did not start within five minutes", False)
                return
            if self.seen and self.absent >= 4:
                return self.finish()
        self.set_state("Game running" if self.seen else "Waiting for RimWorld to start…", bool(t.n_fatal))

    def finish(self):
        t = self.tail
        ev = t.flush()
        self.fill()
        self.stop(quiet=True)
        if t.n_fatal == 0:
            self.set_state("Game closed: clean session", False)
            self.banner.setText("That session had no fatal errors (%d errors in total, mostly harmless messages). "
                                "If it played well, mark this setup as working so you can compare against it later." % t.n_err)
            self.b_good.show()
            self.b_full.hide()
        else:
            self.set_state("Game closed: %d fatal errors" % t.n_fatal, True)
            self.banner.setText("The log has fatal errors. Analyze the full log to see the likely cause and what to untick.")
            self.b_good.hide()
            self.b_full.show()
        self.banner_card.show()
        self.win.toast(self.state_lbl.text())

    # ---- table
    def fill(self):
        t = self.tail
        mods = self.st.mods
        self.shown = sorted(t.events, key=lambda e: (not e.fatal, e.line))
        self.table.setRowCount(len(self.shown))
        for i, e in enumerate(self.shown):
            kind, text = ("missing", "Fatal") if e.fatal else (("skipped", "Fallout") if e.kind == "symptom" else ("outdated", "Error"))
            a = QTableWidgetItem(e.time)
            self.table.setItem(i, 0, a)
            c = QTableWidgetItem()
            c.setData(FLAGS, [(kind, text)])
            self.table.setItem(i, 1, c)
            self.table.setItem(i, 2, QTableWidgetItem(", ".join(mods[p].name for p in e.pids[:2] if p in mods)))
            m = QTableWidgetItem(("%s   (x%d)" % (e.head, e.count)) if e.count > 1 else e.head)
            m.setToolTip(e.head)
            self.table.setItem(i, 3, m)

    def pick(self, r):
        if 0 <= r < len(self.shown):
            for p in self.shown[r].pids:
                if p in self.st.mods:
                    self.st.select(p)
                    return

    def mark_good(self):
        snap = self.st.mark_good("after a clean launch")
        self.banner_card.hide()
        self.win.toast("Saved as working: %d mods" % len(snap["order"]))

    def analyze(self):
        self.page.tabs.setCurrentWidget(self.page.log)
        self.page.log.src.setCurrentIndex(0)
        self.page.log.analyze()


class DiagnosePage(QWidget):
    def __init__(self, st, win):
        super().__init__()
        self.st, self.win, self.index = st, win, None
        v, head, self.sub = page_layout(self, "Diagnose", "Find out why the game crashes, hangs or shows a black screen")
        sb = tbtn("Copy support bundle", "folder", "A short summary you can paste into Discord or a forum. Paths are removed.")
        sb.setPopupMode(QToolButton.InstantPopup)
        sm = QMenu(self)
        sm.addAction("Summary only", lambda: self.copy_bundle(False))
        sm.addAction("Summary with the full load order", lambda: self.copy_bundle(True))
        sb.setMenu(sm)
        head.addWidget(sb)
        self.tabs = QTabWidget()
        self.log = LogTab(st, win, self)
        self.scan = ScanTab(st, win, self)
        self.crash = CrashTab(st, win, self)
        self.changes = ChangesTab(st, win, self)
        self.live = LiveTab(st, win, self)
        self.tabs.addTab(self.changes, "What changed")
        self.tabs.addTab(self.log, "Log reader")
        self.tabs.addTab(self.scan, "Compatibility scan")
        self.tabs.addTab(self.crash, "Crash finder")
        self.tabs.addTab(self.live, "Live log")
        v.addWidget(self.tabs, 1)
        st.reset.connect(lambda: setattr(self, "index", None))

    def copy_bundle(self, include_order):
        st = self.st
        if not st.mods:
            return
        order, plan, upd = st.order_ids(), st.plan(), st.updated_map()
        checked, broken = dict(st.checked), dict(st.broken)
        known, log = self.log.A, diagnose.default_log_dir() / "Player.log"

        def work(progress):
            if known is None and log.exists():
                return diagnose.analyze_log(log, st.mods, self.get_index(progress))
            return known

        def done(A):
            text = support.build_bundle(core.game_version_str(st.s["game_dir"]), st.target, st.mods, checked, order, plan, broken, A, upd, include_order)
            QApplication.clipboard().setText(text)
            self.win.toast("Copied the support bundle (%d lines). Paste it where you are asking for help." % (text.count("\n") + 1))
        self.win.toast("Reading the log…", 1500)
        run_job(self, work, done, lambda m: QMessageBox.critical(self, "Could not build the bundle", m))

    def get_index(self, progress=None):
        """Index of which mod ships which DLL. Built once per scan, safe to call from a worker thread."""
        if self.index is None:
            self.index = diagnose.build_assembly_index(self.st.mods, progress)
        return self.index

    def showEvent(self, e):
        self.crash.check_left_over()
        super().showEvent(e)


# ---------------------------------------------------------------- settings
class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.s = win, win.st.s
        self.setWindowTitle("Settings")
        self.resize(640, 0)
        v = QVBoxLayout(self)
        g = QGridLayout()
        g.setSpacing(8)
        self.edits = {}
        for i, (k, text, isfile) in enumerate((("game_dir", "RimWorld folder", False), ("workshop_dir", "Workshop folder (294100)", False),
                                               ("config_path", "ModsConfig.xml", True))):
            g.addWidget(label(text, "muted"), i, 0)
            e = QLineEdit(self.s.get(k, ""))
            self.edits[k] = e
            g.addWidget(e, i, 1)
            b = pbtn("Browse", ghost=True)
            b.clicked.connect(lambda _=False, e=e, f=isfile: self.browse(e, f))
            g.addWidget(b, i, 2)
        g.addWidget(label("Theme", "muted"), 3, 0)
        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.setCurrentIndex(self.theme.findData(self.s.get("theme", "dark")))
        g.addWidget(self.theme, 3, 1)
        g.addWidget(label("Row density", "muted"), 4, 0)
        self.dens = QComboBox()
        self.dens.addItem("Comfortable", "comfortable")
        self.dens.addItem("Compact", "compact")
        self.dens.setCurrentIndex(self.dens.findData(self.s.get("density", "comfortable")))
        g.addWidget(self.dens, 4, 1)
        self.safe = QCheckBox("Auto-select leaves out mods made for the previous game version that contain code")
        self.safe.setToolTip("On a pre-release build these are the likeliest to crash. You can still tick them by hand.")
        self.safe.setChecked(bool(self.s.get("safe_auto")))
        g.addWidget(self.safe, 5, 0, 1, 3)
        v.addLayout(g)
        row = QHBoxLayout()
        row.addStretch(1)
        c = pbtn("Cancel", ghost=True)
        c.clicked.connect(self.reject)
        ok = pbtn("Save", primary=True)
        ok.clicked.connect(self.save)
        row.addWidget(c)
        row.addWidget(ok)
        v.addLayout(row)

    def browse(self, e, isfile):
        f = QFileDialog.getOpenFileName(self, "Pick the file", e.text())[0] if isfile else QFileDialog.getExistingDirectory(self, "Pick the folder", e.text())
        if f:
            e.setText(f)

    def save(self):
        changed = any(self.s.get(k) != e.text() for k, e in self.edits.items())
        for k, e in self.edits.items():
            self.s[k] = e.text()
        self.s["theme"], self.s["density"] = self.theme.currentData(), self.dens.currentData()
        safe_changed = bool(self.s.get("safe_auto")) != self.safe.isChecked()
        self.s["safe_auto"] = self.safe.isChecked()
        core.save_settings(self.s)
        self.accept()
        self.win.apply_theme()
        if safe_changed and not changed:
            self.win.toast("Saved. Press Auto-select on the Mods page to apply it.")
        if changed:
            self.win.st.rescan()


# -------------------------------------------------------------- main window
def style_titlebar(win, t):
    try:
        import ctypes
        hwnd = int(win.winId())
        dark = ctypes.c_int(1 if t is theme.DARK else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)
        c = QColor(t["nav"])
        ref = ctypes.c_int(c.red() | (c.green() << 8) | (c.blue() << 16))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ref), 4)
    except Exception:
        pass


class SubscribeDialog(QDialog):
    """Walks through mods you need to subscribe to. Steam does the subscribing; this opens each page in turn
    and notices when the download lands in the Workshop folder."""

    def __init__(self, parent, st, items, title="Subscribe to missing mods"):
        super().__init__(parent)
        self.st, self.parent_win = st, parent
        self.items = sorted(items, key=lambda i: (not i.get("id"), i["name"].lower()))
        self.state = {i: "todo" for i in range(len(self.items))}
        self.setWindowTitle(title)
        self.resize(820, 560)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.addWidget(label(title, "h2"))
        v.addWidget(label("Press Open next. Steam shows the Workshop page; press Subscribe there. The download is picked up here "
                          "automatically for mods that have a Workshop id. Mods without one open a download link or a Workshop search.", "muted", True))
        if len(self.items) > 40:
            v.addWidget(label("That is a lot of mods. Ones with a Workshop id come first, and you can stop at any point.", "caption", True))
        self.table = QTableWidget(len(self.items), 3)
        self.table.setHorizontalHeaderLabels(["Mod", "Why", "Status"])
        set_table(self.table, 28)
        self.table.setItemDelegateForColumn(2, ChipDelegate(self.table))
        self.table.setColumnWidth(0, 360)
        self.table.setColumnWidth(1, 200)
        for r, it in enumerate(self.items):
            self.table.setItem(r, 0, QTableWidgetItem(it["name"]))
            self.table.setItem(r, 1, QTableWidgetItem(it.get("why", "")))
            self.table.setItem(r, 2, QTableWidgetItem())
        v.addWidget(self.table, 1)
        self.count = label("", "muted")
        v.addWidget(self.count)
        row = QHBoxLayout()
        self.next_btn = pbtn("Open next", "link", primary=True)
        self.next_btn.clicked.connect(self.open_next)
        sel = pbtn("Open selected", "link", ghost=True)
        sel.clicked.connect(self.open_selected)
        cp = pbtn("Copy list", "folder", ghost=True)
        cp.clicked.connect(self.copy_list)
        done = pbtn("Refresh library and close", "refresh")
        done.clicked.connect(self.finish)
        for b in (self.next_btn, sel, cp):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(done)
        v.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.paint()

    def workshop_dir(self):
        return Path(self.st.s.get("workshop_dir", ""))

    def paint(self):
        labels = {"todo": ("skipped", "To do"), "opened": ("enable", "Opened"), "done": ("on", "Installed")}
        for r in range(len(self.items)):
            self.table.item(r, 2).setData(FLAGS, [labels[self.state[r]]])
        n = sum(1 for s in self.state.values() if s == "done")
        self.count.setText("%d of %d installed" % (n, len(self.items)))
        self.table.viewport().update()

    def open_item(self, r):
        open_url(saves.item_url(self.items[r]))
        if self.state[r] == "todo":
            self.state[r] = "opened"
        self.paint()

    def open_next(self):
        r = next((i for i in range(len(self.items)) if self.state[i] == "todo"), None)
        if r is None:
            self.parent_win.toast("Nothing left to open")
            return
        self.table.selectRow(r)
        self.open_item(r)

    def open_selected(self):
        rows = [i.row() for i in self.table.selectionModel().selectedRows()]
        if rows:
            self.open_item(rows[0])

    def poll(self):
        base = self.workshop_dir()
        changed = False
        for r, it in enumerate(self.items):
            if self.state[r] != "done" and it.get("id") and (base / it["id"]).exists():
                self.state[r] = "done"
                changed = True
        if changed:
            self.paint()

    def copy_list(self):
        QApplication.clipboard().setText("\n".join("%s  %s" % (i["name"], saves.item_url(i)) for i in self.items))
        self.parent_win.toast("Copied %d lines" % len(self.items))

    def finish(self):
        self.timer.stop()
        self.accept()
        self.st.refresh_library()

    def reject(self):
        self.timer.stop()
        super().reject()


class SavesPage(QWidget):
    def __init__(self, st, win):
        super().__init__()
        self.st, self.win, self.metas, self.cmps, self.cur = st, win, None, {}, None
        v, head, self.sub = page_layout(self, "Saves", "Check a colony against your mod list before you load it")
        op = pbtn("Open saves folder", "folder", ghost=True)
        op.clicked.connect(lambda: os.startfile(str(saves.default_save_dir())) if saves.default_save_dir().exists() else None)
        rf = pbtn("Refresh", "refresh", ghost=True)
        rf.clicked.connect(self.load)
        head.addWidget(op)
        head.addWidget(rf)
        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Save", "Saved", "Game", "Mods", "Against your list"])
        set_table(self.table, 30)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setItemDelegateForColumn(4, ChipDelegate(self.table))
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in ((1, 104), (2, 78), (3, 56), (4, 150)):
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
            hh.resizeSection(i, w)
        self.table.currentCellChanged.connect(lambda r, *_: self.show_save(r))
        split.addWidget(self.table)
        right = QVBoxLayout()
        right.setContentsMargins(16, 14, 16, 14)
        right.setSpacing(8)
        self.title = label("Pick a save", "h2", True)
        self.meta_lbl = label("", "muted", True)
        self.note = label("", "caption", True)
        right.addWidget(self.title)
        right.addWidget(self.meta_lbl)
        right.addWidget(self.note)
        self.tabs = QTabWidget()
        self.lists = {}
        for key, name in (("missing", "Missing"), ("off", "Not ticked"), ("outdated", "May not load"), ("extra", "Extra")):
            w = QListWidget()
            self.lists[key] = w
            self.tabs.addTab(w, name)
        right.addWidget(self.tabs, 1)
        self.b_match = pbtn("Match this save", "check", primary=True,
                            tip="Tick exactly the mods this save used (the ones you have installed) and use its load order")
        self.b_need = pbtn("Only tick what it needs", "check", tip="Tick the installed mods the save uses, and leave everything else as it is")
        self.b_sub = pbtn("Subscribe to missing…", "link", tip="Open the Workshop pages for the mods you don't have")
        self.b_match.clicked.connect(self.match)
        self.b_need.clicked.connect(self.tick_needed)
        self.b_sub.clicked.connect(self.subscribe)
        for b in (self.b_match, self.b_need, self.b_sub):
            right.addWidget(b)
        self.protect = QCheckBox("Protect this save when I apply")
        self.protect.setToolTip("Apply warns before it removes a mod this save needs")
        self.protect.toggled.connect(self.set_protect)
        right.addWidget(self.protect)
        lr = QHBoxLayout()
        self.prof = QComboBox()
        self.prof.setMinimumWidth(150)
        lb = pbtn("Link profile", "save", ghost=True)
        lb.clicked.connect(self.link)
        ub = pbtn("Use linked profile", "check", ghost=True)
        ub.clicked.connect(self.use_linked)
        lr.addWidget(self.prof, 1)
        lr.addWidget(lb)
        lr.addWidget(ub)
        right.addLayout(lr)
        self.link_lbl = label("", "caption", True)
        right.addWidget(self.link_lbl)
        self.card = card(right)
        split.addWidget(self.card)
        split.setSizes([800, 360])
        v.addWidget(split, 1)
        st.changed.connect(self.refresh_matches)
        st.reset.connect(lambda: setattr(self, "metas", None))

    def showEvent(self, e):
        if self.metas is None and self.st.mods:
            self.load()
        super().showEvent(e)

    def load(self):
        self.sub.setText("Reading saves…")
        run_job(self, lambda progress: saves.list_saves(), self.done, lambda m: self.sub.setText("Could not read saves: " + m))

    def done(self, metas):
        self.metas = metas
        self.sub.setText("%d saves found. Only each file's header is read." % len(metas) if metas else
                         "No saves found in %s" % saves.default_save_dir())
        self.refresh_matches()

    def compare(self, meta):
        st = self.st
        return saves.compare_save(meta, st.mods, st.checked, st.target, st.broken)

    def refresh_matches(self):
        if self.metas is None or not self.st.mods:
            return
        keep = self.table.currentRow()
        self.cmps = {m["path"]: self.compare(m) for m in self.metas}
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.metas))
        for r, m in enumerate(self.metas):
            for c, txt in enumerate((m["name"], tracker.fmt_date(m["mtime"]), m["game"].split(" ")[0], str(len(m["mods"])))):
                it = QTableWidgetItem(txt)
                if c == 0:
                    it.setToolTip(m["name"])
                self.table.setItem(r, c, it)
            chip = QTableWidgetItem()
            chip.setData(FLAGS, [saves.verdict(self.cmps[m["path"]])])
            self.table.setItem(r, 4, chip)
        self.table.blockSignals(False)
        if 0 <= keep < len(self.metas):
            self.table.selectRow(keep)
            self.show_save(keep)

    def show_save(self, r):
        if self.metas is None or not (0 <= r < len(self.metas)):
            return
        m = self.metas[r]
        self.cur, c = m, self.cmps.get(m["path"]) or self.compare(m)
        self.title.setText(m["name"])
        self.meta_lbl.setText("Saved %s, game %s, %d mods. %d match your list now." % (
            tracker.fmt_date(m["mtime"]), m["game"].split(" ")[0], len(m["mods"]), len(c["ok"])))
        self.note.setText(c["game_note"])
        mods = self.st.mods
        data = {"missing": [x["name"] + ("   (Workshop %s)" % x["steam"] if x["steam"] else "") for x in c["missing"]],
                "off": [x["name"] for x in c["off"]], "outdated": [x["name"] for x in c["outdated"]],
                "extra": [mods[p].name for p in c["extra"]]}
        for i, key in enumerate(("missing", "off", "outdated", "extra")):
            w = self.lists[key]
            w.clear()
            w.addItems(data[key][:600])
            self.tabs.setTabText(i, "%s (%d)" % (("Missing", "Not ticked", "May not load", "Extra")[i], len(data[key])))
        self.b_sub.setEnabled(bool(saves.missing_save_items(m, c)))
        self.b_need.setEnabled(bool(c["off"]))
        s = self.st.s
        self.protect.blockSignals(True)
        self.protect.setChecked(m["name"] in s.get("protected_saves", []))
        self.protect.blockSignals(False)
        self.prof.clear()
        self.prof.addItems(core.list_profiles())
        linked = s.get("save_profiles", {}).get(m["name"])
        self.link_lbl.setText("Linked to profile: %s" % linked if linked else "No profile linked. Link one so this colony's setup is one click away.")
        if linked and self.prof.findText(linked) >= 0:
            self.prof.setCurrentIndex(self.prof.findText(linked))

    def match(self):
        m = self.cur
        if not m:
            return
        c = self.compare(m)
        if c["missing"] and QMessageBox.question(
                self, "Match this save", "%d mods this save used are not installed, so the colony may not load properly.\n\n"
                "Tick the %d you have, in the save's load order?" % (len(c["missing"]), len(saves.match_order(m, self.st.mods)))) != QMessageBox.Yes:
            return
        n = self.st.match_save(m)
        self.win.toast("Ticked %d mods in %s's load order. %d are not installed." % (n, m["name"], len(c["missing"])))

    def tick_needed(self):
        if self.cur:
            c = self.compare(self.cur)
            n = self.st.set_checked([x["id"] for x in c["off"]], True)
            self.win.toast("Ticked %d mods this save needs" % n)

    def subscribe(self):
        if self.cur:
            SubscribeDialog(self.win, self.st, saves.missing_save_items(self.cur, self.compare(self.cur)),
                            "Subscribe to the mods %s needs" % self.cur["name"]).exec()

    def set_protect(self, on):
        if self.cur:
            self.st.set_protected(self.cur["name"], on)
            self.win.toast("%s %s" % (self.cur["name"], "is protected: Apply will warn before removing mods it needs" if on else "is no longer protected"))

    def link(self):
        if self.cur and self.prof.currentText():
            self.st.link_profile(self.cur["name"], self.prof.currentText())
            self.show_save(self.table.currentRow())
            self.win.toast("Linked %s to profile %s" % (self.cur["name"], self.prof.currentText()))

    def use_linked(self):
        p = self.st.s.get("save_profiles", {}).get(self.cur["name"]) if self.cur else None
        if p and p in core.list_profiles():
            self.st.load_profile(p)
        else:
            self.win.toast("No linked profile yet")


class ApplyDialog(QDialog):
    """Shows exactly what writing the new list does to ModsConfig.xml before anything is written."""

    def __init__(self, parent, mods, diff, old_ids, new_ids, notes, warnings=()):
        super().__init__(parent)
        self.setWindowTitle("Review changes")
        self.resize(760, 560)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.addWidget(label("Write %d mods to ModsConfig.xml?" % len(new_ids), "h2"))
        for w in warnings:
            v.addWidget(label(w, "danger", True))
        counts = ["%d added" % len(diff["added"]), "%d removed" % len(diff["removed"]), "%d moved" % len(diff["moved"])]
        if diff["missing"]:
            counts.append("%d not installed (dropped)" % len(diff["missing"]))
        same = not any(diff.values())
        v.addWidget(label("Nothing changes. The file already matches." if same else ", ".join(counts), "muted"))
        nm = lambda p: mods[p].name if p in mods else p  # noqa
        po, pn = {p: i + 1 for i, p in enumerate(old_ids)}, {p: i + 1 for i, p in enumerate(new_ids)}
        tabs = QTabWidget()
        for title, key in (("Added", "added"), ("Removed", "removed"), ("Moved", "moved"), ("Not installed", "missing")):
            lst = QListWidget()
            for p in diff[key]:
                if key == "moved":
                    lst.addItem("%s   #%d to #%d" % (nm(p), po[p], pn[p]))
                elif key == "missing":
                    lst.addItem("%s   (in your file, but no longer installed)" % p)
                else:
                    lst.addItem(nm(p))
            if not lst.count():
                lst.addItem("None")
                lst.item(0).setFlags(Qt.NoItemFlags)
            tabs.addTab(lst, "%s (%d)" % (title, len(diff[key])))
        v.addWidget(tabs, 1)
        for n in notes:
            v.addWidget(label(n, "muted", True))
        v.addWidget(label("Your current file is backed up first. Nothing is written until you press the button.", "caption", True))
        row = QHBoxLayout()
        row.addStretch(1)
        c = pbtn("Cancel", ghost=True)
        c.clicked.connect(self.reject)
        ok = pbtn("Write to ModsConfig.xml", "check", primary=True)
        ok.clicked.connect(self.accept)
        row.addWidget(c)
        row.addWidget(ok)
        v.addLayout(row)


class MainWindow(QMainWindow):
    def __init__(self, st):
        super().__init__()
        self.st = st
        self.setWindowTitle("RimWorld Mod Applier")
        self.resize(1440, 880)
        self.setMinimumSize(1020, 640)
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # nav rail
        nav = QFrame()
        nav.setObjectName("nav")
        nav.setFixedWidth(100)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(0, 10, 0, 10)
        nl.setSpacing(2)
        self.nav_group = QButtonGroup(self)
        self.nav_btns = {}
        for i, (key, text) in enumerate(PAGES):
            b = QToolButton()
            b.setObjectName("navbtn")
            b.setText(text)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip("%s   (Ctrl+%d)" % (text, i + 1))
            set_icon(b, {"mods": "mods", "order": "order", "deps": "deps", "problems": "problems", "diag": "pulse", "saves": "save", "profiles": "profiles"}[key], "muted", 22)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            self.nav_btns[key] = b
            nl.addWidget(b)
        nl.addStretch(1)
        self.theme_btn = tbtn("", "sun", "Switch between dark and light", icon_only=True)
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.panel_btn = tbtn("", "panel", "Show or hide the inspector (F4)", icon_only=True, checkable=True)
        self.panel_btn.setChecked(True)
        self.panel_btn.toggled.connect(lambda on: self.inspector.setVisible(on))
        sett = tbtn("", "sliders", "Settings", icon_only=True)
        sett.clicked.connect(lambda: SettingsDialog(self).exec())
        for b in (self.panel_btn, self.theme_btn, sett):
            nl.addWidget(b, 0, Qt.AlignHCenter)
        body.addWidget(nav)

        # pages + inspector
        self.split = QSplitter(Qt.Horizontal)
        self.stack = QStackedWidget()
        self.pages = {"mods": ModsPage(st, self), "order": OrderPage(st, self), "deps": DepsPage(st, self),
                      "problems": ProblemsPage(st, self), "diag": DiagnosePage(st, self), "saves": SavesPage(st, self), "profiles": ProfilesPage(st, self)}
        for k, _ in PAGES:
            self.stack.addWidget(self.pages[k])
        self.inspector = Inspector(st, self)
        self.split.addWidget(self.stack)
        self.split.addWidget(self.inspector)
        self.split.setStretchFactor(0, 1)
        self.split.setSizes([1000, 350])
        self.split.setChildrenCollapsible(False)
        body.addWidget(self.split, 1)

        # bottom bar
        bar = QFrame()
        bar.setObjectName("bottom")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 10, 18, 10)
        bl.setSpacing(8)
        bl.addWidget(label("Profile", "muted"))
        self.prof = QComboBox()
        self.prof.setMinimumWidth(190)
        self.prof.activated.connect(self.profile_picked)
        bl.addWidget(self.prof)
        sv = tbtn("", "save", "Save the current mods and order as a profile (Ctrl+S)", icon_only=True)
        sv.clicked.connect(self.save_profile)
        bl.addWidget(sv)
        self.undo_btn = tbtn("", "undo", "Undo (Ctrl+Z)", icon_only=True)
        self.redo_btn = tbtn("", "redo", "Redo (Ctrl+Y)", icon_only=True)
        self.undo_btn.clicked.connect(st.undo)
        self.redo_btn.clicked.connect(st.redo)
        bl.addWidget(self.undo_btn)
        bl.addWidget(self.redo_btn)
        bl.addStretch(1)
        self.watch_btn = tbtn("", "pulse", "RimWorld's log is being watched. Click to see it.")
        self.watch_btn.setVisible(False)
        self.watch_btn.clicked.connect(self.open_live)
        bl.addWidget(self.watch_btn)
        self.pages["diag"].live.status.connect(self.on_watch)
        self.summary = label("", "muted")
        bl.addWidget(self.summary)
        ap = pbtn("Apply", ghost=False, tip="Write the load order to ModsConfig.xml (Ctrl+Enter)")
        ap.clicked.connect(lambda: self.apply(False))
        self.go = pbtn("Apply and launch", "play", primary=True, tip="Apply, then start RimWorld through Steam (Ctrl+Shift+Enter)")
        self.go.clicked.connect(lambda: self.apply(True))
        bl.addWidget(ap)
        bl.addWidget(self.go)
        outer.addWidget(bar)

        self.toast_lbl = QLabel(central)
        self.toast_lbl.setObjectName("toast")
        self.toast_lbl.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast_lbl.hide)

        st.notice.connect(self.toast)
        st.changed.connect(self.update_bar)
        st.historyChanged.connect(self.update_bar)
        st.selected.connect(lambda _p: None)
        self.shortcuts()
        self.apply_theme()
        self.show_page("mods")

    # ----- plumbing
    def shortcuts(self):
        def sc(keys, fn):
            QShortcut(QKeySequence(keys), self, activated=fn)
        sc("Ctrl+F", lambda: (self.show_page("mods"), self.pages["mods"].search.setFocus(), self.pages["mods"].search.selectAll()))
        sc("Ctrl+Z", self.st.undo)
        sc("Ctrl+Y", self.st.redo)
        sc("Ctrl+Shift+Z", self.st.redo)
        sc("Ctrl+S", self.save_profile)
        sc("F4", lambda: self.panel_btn.toggle())
        sc("F5", self.st.refresh_library)
        sc("Ctrl+Return", lambda: self.apply(False))
        sc("Ctrl+Shift+Return", lambda: self.apply(True))
        for i, (k, _) in enumerate(PAGES):
            sc("Ctrl+%d" % (i + 1), lambda k=k: self.show_page(k))

    def show_page(self, key):
        self.stack.setCurrentWidget(self.pages[key])
        self.nav_btns[key].setChecked(True)
        if key == "deps" and self.st.current:
            self.pages["deps"].show_mod(self.st.current)

    def show_mod(self, pid):
        self.show_page("mods")
        self.pages["mods"].goto(pid)

    def apply_theme(self):
        s = self.st.s
        name = s.get("theme", "dark")
        theme.use(name)
        t = theme.cur
        QApplication.instance().setStyleSheet(theme.qss(name, s.get("density", "comfortable")))
        row = 30 if s.get("density", "comfortable") == "comfortable" else 24
        for p in (self.pages["mods"], self.pages["order"]):
            p.set_row(row)
        self.theme_btn.setIcon(theme.icon("sun" if name == "dark" else "moon", t["text"], 18))
        for k, b in self.nav_btns.items():
            pass
        refresh_icons()
        self.theme_btn.setIcon(theme.icon("sun" if name == "dark" else "moon", t["text"], 18))
        style_titlebar(self, theme.DARK if name == "dark" else theme.LIGHT)
        self.st.changed.emit()
        self.st.orderChanged.emit()

    def toggle_theme(self):
        self.st.s["theme"] = "light" if self.st.s.get("theme", "dark") == "dark" else "dark"
        core.save_settings(self.st.s)
        self.apply_theme()

    def toast(self, text, ms=4200):
        self.toast_lbl.setText(text)
        self.toast_lbl.adjustSize()
        c = self.centralWidget()
        self.toast_lbl.move((c.width() - self.toast_lbl.width()) // 2, c.height() - self.toast_lbl.height() - 84)
        self.toast_lbl.show()
        self.toast_lbl.raise_()
        self.toast_timer.start(ms)

    def update_bar(self):
        st = self.st
        self.undo_btn.setEnabled(bool(st.undo_stack))
        self.redo_btn.setEnabled(bool(st.redo_stack))
        nprob = len(st.broken) + sum(1 for fl in st.status.values() if any(k == "conflict" for k, _ in fl))
        self.summary.setText("%d mods ticked   ·   %d with problems" % (st.n_ticked(), nprob))
        names = core.list_profiles()
        cur = self.prof.currentText()
        if [self.prof.itemText(i) for i in range(self.prof.count())] != names:
            self.prof.blockSignals(True)
            self.prof.clear()
            self.prof.addItems(names)
            i = self.prof.findText(st.s.get("last_profile", ""))
            self.prof.setCurrentIndex(i if i >= 0 else -1)
            self.prof.blockSignals(False)

    def profile_picked(self):
        n = self.prof.currentText()
        if n:
            self.st.load_profile(n)

    def save_profile(self):
        name = self.st.s.get("last_profile") or ""
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:", text=name)
        if ok and name.strip():
            self.st.save_profile(name.strip())
            self.prof.blockSignals(True)
            self.update_bar()
            self.prof.setCurrentIndex(self.prof.findText(name.strip()))
            self.prof.blockSignals(False)
            self.toast("Saved profile %s" % name.strip())

    def update_rules(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            n = core.download_community()
        except Exception as e:  # noqa
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Update failed", str(e))
            return
        QApplication.restoreOverrideCursor()
        self.st.reload_community()
        self.toast("Loaded community rules for %d mods" % n)

    def on_watch(self, text, bad):
        self.watch_btn.setVisible(bool(text))
        self.watch_btn.setText(text)
        self.watch_btn.setStyleSheet("color: %s" % theme.cur["danger"] if bad else "")

    def open_live(self):
        self.show_page("diag")
        d = self.pages["diag"]
        d.tabs.setCurrentWidget(d.live)

    # ----- apply
    def apply(self, launch):
        st, s = self.st, self.st.s
        if core.game_running():
            QMessageBox.critical(self, "RimWorld is running", "Close RimWorld first, then apply." + NOT_SURE)
            return
        if st.config_changed_elsewhere():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("ModsConfig.xml changed")
            box.setText("ModsConfig.xml is not what the app last read.")
            box.setInformativeText("The game, Steam or another mod manager rewrote it since then. The next screen compares your new list "
                                   "against the file as it is now, and a backup is made first. To keep what is in the file, cancel and "
                                   "use 'From current ModsConfig' instead.")
            over = box.addButton("Continue", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is not over:
                return
        plan = st.apply_plan(False)
        drop = True
        if plan.missing:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Missing dependencies")
            box.setText("%d ticked mods need a mod you don't have." % len(plan.missing))
            box.setInformativeText("\n".join("• " + st.mods[p].name for p in plan.missing[:12]))
            skip = box.addButton("Skip them", QMessageBox.AcceptRole)
            keep = box.addButton("Enable anyway", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is keep:
                drop = False
            elif box.clickedButton() is not skip:
                return
        plan = st.apply_plan(drop)
        if plan.violations:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Broken load-order rules")
            box.setText("Your order breaks %d rules." % len(plan.violations))
            box.setInformativeText("RimWorld may show errors for these mods. Fixing them moves as few mods as possible.")
            fix = box.addButton("Fix and apply", QMessageBox.AcceptRole)
            box.addButton("Apply as is", QMessageBox.DestructiveRole)
            cancel = box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is cancel or box.clickedButton() is None:
                return
            if box.clickedButton() is fix:
                st.fix_order()
                plan = st.apply_plan(drop)
        new_ids = [p for p, _ in plan.order]
        old_ids = core.read_active(s["config_path"])
        notes = []
        if plan.pulled:
            notes.append("%d required mods were ticked for you." % len(plan.pulled))
        if plan.dropped:
            notes.append("%d mods with missing dependencies are left out." % len(plan.dropped))
        if plan.dropped_rules:
            notes.append("%d sorting rules were left out because they would loop. See Problems." % len(plan.dropped_rules))
        warnings = []
        keep = set(new_ids)
        for save_name in sorted({n for names in st.protected_needs().values() for n in names}):
            lost = [p for p, names in st.protected_needs().items() if save_name in names and p not in keep]
            if lost:
                nm = [st.mods[p].name if p in st.mods else p for p in lost]
                warnings.append("Protected save '%s' needs %d mods this list does not include: %s%s." % (
                    save_name, len(lost), ", ".join(nm[:5]), " and %d more" % (len(nm) - 5) if len(nm) > 5 else ""))
        if ApplyDialog(self, st.mods, core.config_diff(old_ids, new_ids, st.mods), old_ids, new_ids, notes, warnings).exec() != QDialog.Accepted:
            return
        try:
            bak = core.backup_config(s["config_path"])
            core.write_config(s["config_path"], new_ids, core.game_version_str(s["game_dir"]))
            st.sync_config_hash()
        except Exception as e:  # noqa
            QMessageBox.critical(self, "Could not write the file", str(e))
            return
        self.toast("Applied %d mods. Backup: %s" % (len(plan.order), bak.name if bak else "none needed"))
        if launch:
            self.pages["diag"].live.stop(quiet=True)
            self.pages["diag"].live.start()
            open_url("steam://rungameid/" + core.APPID)


def run_gui(s):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("RimWorld Mod Applier")
    try:  # lets Windows group the taskbar button under our own icon instead of Python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RimWorldModApplier.App")
    except Exception:
        pass
    from . import appicon
    app.setWindowIcon(appicon.app_icon())
    theme.use(s.get("theme", "dark"))
    diagnose.ensure_files()
    advisor.ensure_files()
    st = State(s)
    win = MainWindow(st)
    win.show()
    QTimer.singleShot(60, lambda: (QApplication.setOverrideCursor(Qt.WaitCursor), st.rescan(), QApplication.restoreOverrideCursor(),
                                   win.pages["profiles"].refresh(), win.update_bar()))
    return app.exec()
