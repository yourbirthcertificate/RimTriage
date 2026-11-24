"""Workshop update tracking and 'last known good' snapshots. No UI code.

Steam records when each subscribed mod was last updated in appworkshop_294100.acf. A snapshot stores your ticked
order and those times at a moment you called the setup working, so later you can see exactly what changed."""
import json
import re
import time
from pathlib import Path

from . import core

HISTORY_DIR = core.APP_DIR / "history"
KEEP = 12


# ------------------------------------------------------------------- Steam
def parse_vdf(text):
    """Minimal Valve KeyValues reader. Enough for appworkshop_*.acf."""
    stack, key = [{}], None
    for q, brace in re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text):
        if brace == "{":
            new = {}
            stack[-1][key] = new
            stack.append(new)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
        elif key is None:
            key = q
        else:
            stack[-1][key] = q
            key = None
    return stack[0]


def workshop_times(workshop_dir):
    """{workshop id: unix time of its last update} from Steam's manifest, or {} when it can't be read."""
    if not workshop_dir:
        return {}
    acf = Path(workshop_dir).parents[1] / "appworkshop_294100.acf"
    try:
        root = parse_vdf(acf.read_text(encoding="utf-8", errors="ignore")).get("AppWorkshop", {})
        out = {}
        for wid, v in root.get("WorkshopItemsInstalled", {}).items():
            if isinstance(v, dict) and str(v.get("timeupdated", "")).isdigit():
                out[wid] = int(v["timeupdated"])
        return out
    except (OSError, IndexError, AttributeError):
        return {}


def update_times(mods, workshop_dir):
    """{package id: unix time the mod last changed}. Workshop mods use Steam's record, local ones the file date."""
    wt = workshop_times(workshop_dir)
    out = {}
    for p, m in mods.items():
        if m.source == "official":
            continue
        ts = wt.get(m.path.name) if m.source == "workshop" else None
        if not ts:
            try:
                ts = int((m.path / "About" / "About.xml").stat().st_mtime)
            except OSError:
                ts = None
        if ts:
            out[p] = ts
    return out


def fmt_date(ts):
    return time.strftime("%d %b %Y", time.localtime(ts)) if ts else "unknown"


def fmt_ago(ts, now=None):
    if not ts:
        return "unknown"
    d = ((now or time.time()) - ts) / 86400.0
    if d < 1:
        return "today"
    if d < 2:
        return "yesterday"
    if d < 60:
        return "%d days ago" % d
    return fmt_date(ts)


# --------------------------------------------------------------- snapshots
def make_snapshot(order, mods, updated, game="", label=""):
    return {"time": int(time.time()), "label": label, "game": game, "order": list(order),
            "known": sorted(mods), "updated": {p: updated[p] for p in order if p in updated},
            "names": {p: mods[p].name for p in order if p in mods}}


def save_good(snap):
    HISTORY_DIR.mkdir(exist_ok=True)
    f = HISTORY_DIR / ("good_%d.json" % snap["time"])
    f.write_text(json.dumps(snap), encoding="utf-8")
    for old in sorted(HISTORY_DIR.glob("good_*.json"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return f


def list_good():
    out = []
    for f in sorted(HISTORY_DIR.glob("good_*.json"), reverse=True) if HISTORY_DIR.exists() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return out


def load_good():
    snaps = list_good()
    return snaps[0] if snaps else None


# ----------------------------------------------------------------- compare
def compare(snap, now_order, updated_now, mods):
    """What differs from the snapshot. -> [{pid, kind, ts, detail}] with kinds
    updated, new, enabled, disabled, removed, moved. Most suspicious first."""
    old_order = snap["order"]
    old_set, now_set = set(old_order), set(now_order)
    known, old_upd, base_t = set(snap.get("known", [])), snap.get("updated", {}), snap["time"]
    names = snap.get("names", {})
    nm = lambda p: mods[p].name if p in mods else names.get(p, p)  # noqa
    out = []
    for p in now_order:
        if p not in mods:
            continue
        ts, was = updated_now.get(p), old_upd.get(p)
        if p in old_set:
            if ts and ((was and ts > was) or (not was and ts > base_t)):
                out.append({"pid": p, "kind": "updated", "ts": ts,
                            "detail": "Updated %s%s" % (fmt_ago(ts), " (was %s)" % fmt_date(was) if was else "")})
        elif known and p not in known:
            out.append({"pid": p, "kind": "new", "ts": ts, "detail": "Installed since then, and ticked"})
        else:
            out.append({"pid": p, "kind": "enabled", "ts": ts, "detail": "You ticked it since then"})
    for p in old_order:
        if p not in now_set:
            out.append({"pid": p, "kind": "removed" if p not in mods else "disabled", "ts": None,
                        "detail": "No longer installed" if p not in mods else "You unticked it since then"})
    common_old = [p for p in old_order if p in now_set]
    common_new = [p for p in now_order if p in old_set]
    for p in core.moved_mods(common_old, common_new)[:60]:
        out.append({"pid": p, "kind": "moved", "ts": None, "detail": "Load position changed"})
    rank = {"updated": 0, "new": 1, "enabled": 2, "moved": 3, "disabled": 4, "removed": 5}
    out.sort(key=lambda c: (rank[c["kind"]], -(c["ts"] or 0)))
    return out


def recent(updated_now, mods, ticked, days=7, now=None):
    """Ticked mods updated in the last `days`, newest first. The fallback when there is no snapshot yet."""
    cut = (now or time.time()) - days * 86400
    rows = [(ts, p) for p, ts in updated_now.items() if ts >= cut and p in mods and p in ticked]
    return [{"pid": p, "kind": "updated", "ts": ts, "detail": "Updated %s" % fmt_ago(ts)} for ts, p in sorted(rows, reverse=True)]
