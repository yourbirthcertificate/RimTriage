"""Builds the README logo, the GitHub social preview and the app screenshots.

Every screenshot is taken from a fictional demo install (tools/demo_world.py), never from a real machine.
Run:  python tools/make_images.py        (a window flashes on screen while it works)"""
import os
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import demo_world  # noqa: E402

DEMO = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "rimtriage-demo"   # a neutral path, so no user name shows in images
SHOTS = ROOT / "docs" / "screenshots"
ASSETS = ROOT / "assets"


# ------------------------------------------------------------------ logo
def draw_logos(Qt, QImage, QPainter, QColor, QFont, QRectF, QLinearGradient, QRadialGradient, appicon):
    def lockup(dark):
        W, H = 1200, 300
        img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.drawImage(30, 40, appicon.make_image(220))
        f = QFont("Segoe UI Semibold", 1)
        f.setPixelSize(132)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        fm = p.fontMetrics()
        x = 290
        p.setPen(QColor("#f2a93b"))
        p.drawText(x, 160, "Rim")
        x += fm.horizontalAdvance("Rim")
        p.setPen(QColor("#e9ebef" if dark else "#1a1d23"))
        p.drawText(x, 160, "Triage")
        t = QFont("Segoe UI", 1)
        t.setPixelSize(34)
        p.setFont(t)
        p.setPen(QColor("#9aa2b0" if dark else "#566070"))
        p.drawText(294, 222, "Sort, diagnose, and recover your RimWorld mod lists.")
        p.end()
        return img
    lockup(True).save(str(ASSETS / "logo-dark.png"))
    lockup(False).save(str(ASSETS / "logo-light.png"))

    W, H = 1280, 640
    img = QImage(W, H, QImage.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor("#0e1014"))
    g.setColorAt(1, QColor("#1c212b"))
    p.fillRect(0, 0, W, H, g)
    glow = QRadialGradient(330, 320, 330)
    glow.setColorAt(0, QColor(242, 169, 59, 70))
    glow.setColorAt(1, QColor(242, 169, 59, 0))
    p.fillRect(0, 0, W, H, glow)
    p.drawImage(130, 130, appicon.make_image(400))
    f = QFont("Segoe UI Semibold", 1)
    f.setPixelSize(130)
    f.setWeight(QFont.Bold)
    p.setFont(f)
    fm = p.fontMetrics()
    p.setPen(QColor("#f2a93b"))
    p.drawText(600, 290, "Rim")
    p.setPen(QColor("#e9ebef"))
    p.drawText(600 + fm.horizontalAdvance("Rim"), 290, "Triage")
    t = QFont("Segoe UI", 1)
    t.setPixelSize(38)
    p.setFont(t)
    p.setPen(QColor("#b9c0cc"))
    p.drawText(QRectF(604, 318, 600, 120), Qt.TextWordWrap, "Sort, diagnose, and recover your RimWorld mod lists.")
    x = 604
    c = QFont("Segoe UI Semibold", 1)
    c.setPixelSize(30)
    p.setFont(c)
    for word in ("Sort", "Diagnose", "Recover"):
        w = p.fontMetrics().horizontalAdvance(word) + 44
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(242, 169, 59, 40))
        p.drawRoundedRect(x, 470, w, 58, 29, 29)
        p.setPen(QColor("#f6c56e"))
        p.drawText(QRectF(x, 470, w, 58), Qt.AlignCenter, word)
        x += w + 16
    p.end()
    img.save(str(ASSETS / "social-preview.png"))


# ------------------------------------------------------------------ screenshots
def main():
    if DEMO.exists():
        shutil.rmtree(DEMO)
    world = demo_world.build(DEMO)
    os.environ["USERPROFILE"] = str(world["home"])          # logs, saves and config are looked up from here
    data = DEMO / "data"
    data.mkdir()
    SHOTS.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(exist_ok=True)

    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QRadialGradient
    from PySide6.QtWidgets import QAbstractItemView, QApplication, QMessageBox
    from modapplier import appicon, core, diagnose, tracker, theme
    core.SETTINGS_FILE, core.PROFILE_DIR, core.TAGS_FILE, core.USER_RULES_FILE = data / "settings.json", data / "profiles", data / "tags.json", data / "rules.json"
    core.COMMUNITY_FILE = data / "none.json"
    tracker.HISTORY_DIR = data / "history"
    diagnose.RULES_FILE = data / "rules_scoring.json"
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    from modapplier.state import State
    from modapplier import ui

    draw_logos(Qt, QImage, QPainter, QColor, QFont, QRectF, QLinearGradient, QRadialGradient, appicon)
    print("logos written")

    s = {"game_dir": str(world["game"]), "workshop_dir": str(world["workshop"]), "config_path": str(world["config"]),
         "theme": "dark", "density": "comfortable", "mode": "balanced"}
    theme.use("dark")
    st = State(s)
    win = ui.MainWindow(st)
    win.resize(1440, 900)
    win.show()
    st.rescan()
    mods = st.mods

    def settle(n=4):
        for _ in range(n):
            app.processEvents()

    def wait(cond, timeout=60):
        t = time.time()
        while not cond() and time.time() - t < timeout:
            app.processEvents()
            time.sleep(0.03)

    def shot(widget, name, width=1600):
        win.toast_lbl.hide()   # no leftover toasts in the pictures
        settle()
        img = widget.grab().toImage()
        if img.width() > width:
            img = img.scaledToWidth(width, Qt.SmoothTransformation)
        img.save(str(SHOTS / (name + ".png")))
        print("  ", name, "%dx%d" % (img.width(), img.height()))

    def row_of(table, pid):
        m = table.model()
        for r in range(m.rowCount()):
            if m.index(r, 0).data(Qt.UserRole) == pid:
                return r
        return -1

    ticked_ids = [p for p in st.order_ids() if p != "ludeon.rimworld"]
    world["save"]("Mossgrave", ticked_ids, "1.7.5014 rev1195")      # a colony that matches the current list exactly
    # mods
    mp = win.pages["mods"]
    win.show_page("mods")
    mp.table.sortByColumn(7, Qt.DescendingOrder)
    settle()
    r = row_of(mp.table, world["culprit"])
    if r >= 0:
        mp.table.selectRow(r)
        st.select(world["culprit"])
    shot(win, "mods")
    # order
    win.show_page("order")
    settle()
    op = win.pages["order"]
    for i, (p, _t) in enumerate(op.model.rows):
        if p == world["hearth"]:
            op.table.selectRow(i)
            op.table.scrollTo(op.model.index(max(i - 6, 0), 0), QAbstractItemView.PositionAtTop)
            st.select(p)
            break
    shot(win, "load-order")
    # dependencies
    win.show_page("deps")
    patch = next(p for p, m in mods.items() if m.name == world["patch_name"])
    st.select(patch)
    shot(win, "dependencies")
    # diagnose: log reader (rules-based advice, no model)
    win.show_page("diag")
    d = win.pages["diag"]
    d.tabs.setCurrentWidget(d.log)
    d.log.analyze()
    wait(lambda: d.log.A is not None)
    st.select(world["culprit"])
    shot(win, "log-reader")
    # what changed: a baseline from five days ago, with a few updates since
    rnd = random.Random(3)
    order = st.order_ids()
    snap = tracker.make_snapshot(order, mods, dict(st.updated), "1.7.5014 rev1195", "before the update")
    snap["time"] -= 5 * 86400
    cands = [p for p in order if mods[p].dlls and p in st.updated and p != world["culprit"]]
    for p in rnd.sample(cands, 5) + [world["culprit"]]:
        snap["updated"][p] = st.updated[p] - 20 * 86400
    gone = rnd.sample([p for p in order if p not in (world["culprit"], world["hearth"]) and mods[p].source != "official"], 3)
    snap["order"] = [p for p in snap["order"] if p not in gone]
    snap["known"] = [p for p in snap["known"] if p not in gone[:2]]
    mv = snap["order"].pop(300 if len(snap["order"]) > 300 else 20)
    snap["order"].insert(40, mv)
    tracker.save_good(snap)
    d.tabs.setCurrentWidget(d.changes)
    d.changes.reload_bases()
    wait(lambda: d.index is not None)
    d.changes.fill()
    shot(win, "what-changed")
    # crash finder, one round in
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    for n in ("warning", "information", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: None))
    core.game_running = lambda: False
    d.tabs.setCurrentWidget(d.crash)
    d.crash.start()
    d.crash.answer(True)
    shot(win, "crash-finder")
    d.crash.stop()
    # saves
    win.show_page("saves")
    sp = win.pages["saves"]
    wait(lambda: sp.metas is not None)
    sp.refresh_matches()
    for i, m in enumerate(sp.metas):
        if m["name"] == "Hollowmere":
            sp.table.selectRow(i)
            sp.show_save(i)
    shot(win, "saves")
    # apply preview
    cur = [p for p in st.order_ids()]
    old = list(cur)
    for p in rnd.sample(old[10:], 6):
        old.remove(p)
    old.insert(5, old.pop(60))
    old.append("retired.mod.demo")
    new = st.order_ids()
    dlg = ui.ApplyDialog(win, mods, core.config_diff(old, new, mods), old, new, ["2 required mods were ticked for you.", "1 sorting rule was left out because it would loop. See Problems."])
    dlg.resize(820, 600)
    dlg.show()
    shot(dlg, "apply-preview", 1200)
    dlg.close()
    # light theme
    st.s["theme"] = "light"
    win.apply_theme()
    win.show_page("mods")
    mp.table.sortByColumn(7, Qt.DescendingOrder)
    shot(win, "mods-light")
    win.close()
    shutil.rmtree(DEMO, ignore_errors=True)
    print("done:", sorted(f.name for f in SHOTS.iterdir()))


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(DEMO, ignore_errors=True)
