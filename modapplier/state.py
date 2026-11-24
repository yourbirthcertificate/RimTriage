"""Application state shared by every page. All edits go through here so undo/redo stays honest."""
from PySide6.QtCore import QObject, Signal

from . import core, saves, tracker
from .core import CORE


class State(QObject):
    changed = Signal()        # ticks or statuses changed
    reset = Signal()          # a fresh scan replaced the mod list
    orderChanged = Signal()   # load order or its rules changed
    selected = Signal(str)    # a mod was picked somewhere
    notice = Signal(str)      # short message for the toast
    historyChanged = Signal()

    def __init__(self, s):
        super().__init__()
        self.s = s
        self.mods, self.checked, self.broken, self.status, self.rev = {}, {}, {}, {}, {}
        self.dups, self.bad, self.target = [], [], "1.7"
        self.community = core.load_community()
        self.user = core.load_user_rules()
        self.tags = core.load_tags()
        self.use_community = True
        self.mode = s.get("mode", "balanced")
        self.manual = None          # hand-edited order, or None for "fully automatic"
        self._plan = None
        self.undo_stack, self.redo_stack = [], []
        self.current = None
        self.last_moved = []
        self.config_hash = None     # fingerprint of ModsConfig.xml when we last read or wrote it
        self.updated = {}           # pid -> unix time of the mod's last update

    # ------------------------------------------------------------- saves
    def match_save(self, meta):
        """Tick exactly what a save used (and has installed), in the save's own load order."""
        self.push_undo()
        order = saves.match_order(meta, self.mods)
        keep = set(order)
        self.checked = {p: (p in keep or p == CORE) for p in self.mods}
        self.manual = order or None
        self._refresh()
        return len(order)

    def set_protected(self, save_name, on):
        cur = [n for n in self.s.get("protected_saves", []) if n != save_name]
        self.s["protected_saves"] = cur + ([save_name] if on else [])
        core.save_settings(self.s)

    def link_profile(self, save_name, profile):
        self.s.setdefault("save_profiles", {})[save_name] = profile
        core.save_settings(self.s)

    def protected_needs(self):
        """{pid: [names of protected saves that need it]}."""
        out = {}
        for name in self.s.get("protected_saves", []):
            meta = saves.read_save_meta(saves.default_save_dir() / (name + ".rws"))
            for m in (meta or {}).get("mods", []):
                out.setdefault(m["id"], []).append(name)
        return out

    # ------------------------------------------------ updates and baselines
    def load_updates(self):
        self.updated = tracker.update_times(self.mods, self.s.get("workshop_dir", ""))

    def mark_good(self, label=""):
        """Save the current ticks, order and Steam update times as a baseline that worked."""
        snap = tracker.make_snapshot(self.order_ids(), self.mods, self.updated, core.game_version_str(self.s["game_dir"]), label)
        tracker.save_good(snap)
        return snap

    def rollback_list(self, snap):
        """Restore the ticks and order of a baseline. Mod files themselves are not touched."""
        self.push_undo()
        keep = [p for p in snap["order"] if p in self.mods]
        self.checked = {p: (p in set(keep) or p == CORE) for p in self.mods}
        self.manual = keep or None
        self._refresh()
        return len(keep)

    def updated_map(self):
        """{pid: 'updated 3 days ago'} for ticked mods that changed since the last baseline (or in the last week)."""
        snap = tracker.load_good()
        order = self.order_ids() if self.mods else []
        rows = tracker.compare(snap, order, self.updated, self.mods) if snap else tracker.recent(
            self.updated, self.mods, {p for p, v in self.checked.items() if v})
        return {r["pid"]: "updated " + tracker.fmt_ago(r["ts"]) for r in rows if r["kind"] in ("updated", "new") and r["ts"]}

    def _auto(self):
        """Default ticks, honoring the 'leave out unverified code mods' setting."""
        return core.auto_checked(self.mods, self.target, self.broken, bool(self.s.get("safe_auto")))

    def sync_config_hash(self):
        self.config_hash = core.file_hash(self.s["config_path"])

    def config_changed_elsewhere(self):
        """True when ModsConfig.xml is no longer what we last read or wrote (the game, Steam or another tool touched it)."""
        return self.config_hash is not None and core.file_hash(self.s["config_path"]) != self.config_hash

    # ------------------------------------------------------------ scanning
    def rescan(self):
        self.target = ".".join(core.game_version_str(self.s["game_dir"]).split(".")[:2])
        self.mods, self.dups, self.bad = core.scan(self.s["game_dir"], self.s["workshop_dir"], self.target)
        self.broken = core.broken_set(self.mods)
        self.rev = core.reverse_deps(self.mods)
        self.load_updates()
        self.checked = self._auto()
        self.manual = None
        last = self.s.get("last_profile")
        if last and last in core.list_profiles():
            try:
                self.checked, self.manual = core.apply_profile(last, self.checked)
            except Exception:
                pass
        self.undo_stack, self.redo_stack = [], []
        self.sync_config_hash()
        self._refresh()
        self.reset.emit()
        self.historyChanged.emit()

    def refresh_library(self):
        """Re-read the mod folders but keep your ticks and order. New mods get their automatic state."""
        old_checked, old_manual, old_ids = dict(self.checked), self.manual, set(self.mods)
        self.target = ".".join(core.game_version_str(self.s["game_dir"]).split(".")[:2])
        self.mods, self.dups, self.bad = core.scan(self.s["game_dir"], self.s["workshop_dir"], self.target)
        self.broken = core.broken_set(self.mods)
        self.rev = core.reverse_deps(self.mods)
        self.load_updates()
        auto = self._auto()
        self.checked = {p: old_checked.get(p, auto[p]) for p in self.mods}
        self.manual = [p for p in old_manual if p in self.mods] if old_manual else None
        self.undo_stack, self.redo_stack = [], []
        self._refresh()
        self.reset.emit()
        self.historyChanged.emit()
        new, gone = set(self.mods) - old_ids, old_ids - set(self.mods)
        if new or gone:
            self.notice.emit("Library refreshed: %d new, %d removed" % (len(new), len(gone)))
        else:
            self.notice.emit("Library refreshed: nothing changed in %d mods" % len(self.mods))

    def _refresh(self, order=True):
        self.status = core.compute_status(self.mods, self.checked, self.target, self.broken)
        self._plan = None
        self.changed.emit()
        if order:
            self.orderChanged.emit()

    # ------------------------------------------------------------- history
    def _snap(self):
        return dict(self.checked), (list(self.manual) if self.manual else None)

    def push_undo(self):
        self.undo_stack.append(self._snap())
        del self.undo_stack[:-100]
        self.redo_stack.clear()
        self.historyChanged.emit()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._snap())
            self.checked, self.manual = self.undo_stack.pop()
            self._refresh()
            self.historyChanged.emit()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._snap())
            self.checked, self.manual = self.redo_stack.pop()
            self._refresh()
            self.historyChanged.emit()

    # --------------------------------------------------------------- ticks
    def n_ticked(self):
        return sum(1 for v in self.checked.values() if v)

    def set_checked(self, pids, val, record=True):
        pids = [p for p in pids if p in self.mods and p != CORE and self.checked.get(p) != val]
        if not pids:
            return 0
        if record:
            self.push_undo()
        for p in pids:
            self.checked[p] = val
        self._refresh()
        return len(pids)

    def invert(self, pids):
        self.push_undo()
        for p in pids:
            if p != CORE:
                self.checked[p] = not self.checked[p]
        self._refresh()

    def auto_select(self):
        self.push_undo()
        self.checked = self._auto()
        self._refresh()
        self.notice.emit("Ticked every compatible mod: %d of %d" % (self.n_ticked(), len(self.mods)))

    def from_current(self):
        self.push_undo()
        active = set(core.read_active(self.s["config_path"]))
        self.checked = {p: (p in active or p == CORE) for p in self.mods}
        self.manual = [p for p in core.read_active(self.s["config_path"]) if p in self.mods] or None
        self.sync_config_hash()
        self._refresh()
        self.notice.emit("Loaded the mods from your current ModsConfig.xml")

    def enable_with_requirements(self, pid):
        ids = {pid} | core.all_requirements(pid, self.mods, self.broken)
        n = self.set_checked(ids, True)
        self.notice.emit("Ticked %d mods (%s and what it needs)" % (n, self.mods[pid].name))

    def disable_with_dependents(self, pid):
        ids = {pid} | core.all_dependents(pid, self.rev)
        n = self.set_checked(ids, False)
        self.notice.emit("Unticked %d mods (%s and what needs it)" % (n, self.mods[pid].name))

    def select(self, pid):
        self.current = pid
        self.selected.emit(pid)

    # --------------------------------------------------------------- order
    def plan(self):
        if self._plan is None:
            comm = self.community if self.use_community else {}
            self._plan = core.make_plan(self.mods, self.checked, self.broken, True, comm, self.user, self.mode, self.manual)
            if self.manual is not None:
                self.manual = [p for p, _ in self._plan.order]
        return self._plan

    def order_ids(self):
        return [p for p, _ in self.plan().order]

    def _set_manual(self, order, moved=()):
        pl = self.plan()
        self.manual = list(order)
        pl.order = [(p, pl.sorted.tiers[p]) for p in order]
        pl.violations = core.validate_order(order, pl.sorted)
        self.last_moved = list(moved)
        self.orderChanged.emit()

    def smart_sort(self):
        """Re-sort everything from the rules. Returns [(pid, old, new, reason)] for the mods that moved most."""
        old = self.order_ids()
        self.push_undo()
        self.manual = None
        self._plan = None
        new = self.order_ids()
        po, pn = {p: i for i, p in enumerate(old)}, {p: i for i, p in enumerate(new)}
        moved = [(p, po[p], pn[p]) for p in core.moved_mods(old, new)]
        moved.sort(key=lambda r: -abs(r[1] - r[2]))
        why = self.plan().why
        self.orderChanged.emit()
        return [(p, a, b, (why.get(p) or [""])[0]) for p, a, b in moved]

    def gentle_sort(self):
        """Keep the order in ModsConfig.xml and change only what the rules need.
        Mods new to the list are slotted in, and anything out of rule order moves as few places as possible.
        Returns {kept, added, moved}; a list that is already valid comes back unchanged."""
        ids = set(self.order_ids())
        active = [p for p in core.read_active(self.s["config_path"]) if p in ids]
        comm = self.community if self.use_community else {}
        self.push_undo()
        cur, S = core.sync_order(active, ids, self.mods, comm, self.user, self.mode)
        if core.validate_order(cur, S):
            base = {p: i for i, p in enumerate(cur)}
            tries = [core.sort_order(ids, self.mods, comm, self.user, self.mode, base=base, reverse=r) for r in (False, True)]
            cur = min(tries, key=lambda t: len(core.moved_mods(cur, t.order))).order
        stats = {"kept": len(active), "added": len(ids) - len(active), "moved": len(core.moved_mods(active, [p for p in cur if p in set(active)]))}
        self.manual = cur
        self._plan = None
        self.orderChanged.emit()
        return stats

    def fix_order(self):
        """Repair broken rules while moving as few mods as possible."""
        pl = self.plan()
        order = [p for p, _ in pl.order]
        if not pl.violations:
            return 0
        self.push_undo()
        comm = self.community if self.use_community else {}
        base = {p: i for i, p in enumerate(order)}
        tries = [core.sort_order(set(order), self.mods, comm, self.user, self.mode, base=base, reverse=r) for r in (False, True)]
        S = min(tries, key=lambda t: len(core.moved_mods(order, t.order)))
        moved = len(core.moved_mods(order, S.order))
        self._set_manual(S.order)
        return moved

    def move(self, pids, dest):
        order = self.order_ids()
        mv = set(pids) - {CORE}
        moving = [p for p in order if p in mv]
        if not moving:
            return
        rest = [p for p in order if p not in mv]
        k = sum(1 for p in order[:dest] if p not in mv)
        if rest and rest[0] == CORE:
            k = max(k, 1)
        self.push_undo()
        self._set_manual(rest[:k] + moving + rest[k:], moving)

    def move_by(self, pids, where):
        order = self.order_ids()
        idx = [i for i, p in enumerate(order) if p in set(pids)]
        if not idx:
            return
        dest = {"top": 1, "bottom": len(order), "up": max(1, idx[0] - 1), "down": idx[-1] + 2}[where]
        self.move(pids, dest)

    def place_correctly(self, pids):
        pl = self.plan()
        order = [p for p, _ in pl.order]
        report = []
        self.push_undo()
        for p in pids:
            if p == CORE or p not in pl.sorted.tiers:
                continue
            rest = [q for q in order if q != p]
            order, idx = core.insert_mod(rest, p, pl.sorted)
            report.append((p, idx))
        self._set_manual(order, [p for p, _ in report])
        return report

    def set_mode(self, mode):
        self.mode = mode
        self.s["mode"] = mode
        self._plan = None
        self.orderChanged.emit()

    def set_use_community(self, on):
        self.use_community = on
        self._plan = None
        self.orderChanged.emit()

    def reload_community(self):
        self.community = core.load_community()
        self._plan = None
        self.orderChanged.emit()

    def remember(self, pid, other, before):
        """Keep a position forever: pid always loads after `other`, or (before=True) before it."""
        rule = [other, pid] if before else [pid, other]
        if rule not in self.user["after"]:
            self.user["after"].append(rule)
            core.save_user_rules(self.user)
            self._plan = None
            self.orderChanged.emit()

    def forget_rule(self, rule):
        if rule in self.user["after"]:
            self.user["after"].remove(rule)
            core.save_user_rules(self.user)
            self._plan = None
            self.orderChanged.emit()

    def pin(self, pid, where):
        for k in ("top", "bottom"):
            if pid in self.user[k]:
                self.user[k].remove(pid)
        if where:
            self.user[where].append(pid)
        core.save_user_rules(self.user)
        self._plan = None
        self.orderChanged.emit()

    # ---------------------------------------------------------------- tags
    def all_tags(self):
        return sorted({t for v in self.tags.values() for t in v}, key=str.lower)

    def add_tag(self, pids, tag):
        tag = tag.strip()
        if not tag:
            return
        for p in pids:
            self.tags[p] = sorted(set(self.tags.get(p, [])) | {tag})
        core.save_tags(self.tags)
        self.changed.emit()

    def remove_tag(self, pids, tag):
        for p in pids:
            if tag in self.tags.get(p, []):
                self.tags[p] = [t for t in self.tags[p] if t != tag]
        core.save_tags(self.tags)
        self.changed.emit()

    # ------------------------------------------------------------ profiles
    def save_profile(self, name):
        core.save_profile(name, self.checked, self.manual or self.order_ids())
        self.s["last_profile"] = name
        core.save_settings(self.s)

    def load_profile(self, name):
        self.push_undo()
        base = self._auto()
        self.checked, self.manual = core.apply_profile(name, base)
        self.s["last_profile"] = name
        core.save_settings(self.s)
        self._refresh()
        self.notice.emit("Loaded profile %s" % name)

    def profile_on(self, key):
        """Set of ticked ids for a profile name, or the special keys '#selection' / '#config'."""
        if key == "#selection":
            return {p for p, v in self.checked.items() if v}
        if key == "#config":
            return set(core.read_active(self.s["config_path"]))
        return set(core.read_profile(key).get("on", []))

    def import_list(self, path):
        ids, workshop = core.import_modlist(path)
        known = [p for p in ids if p in self.mods]
        missing = [p for p in ids if p not in self.mods]
        self.push_undo()
        self.checked = {p: (p in set(known) or p == CORE) for p in self.mods}
        self.manual = known or None
        self._refresh()
        return len(known), missing, workshop

    # --------------------------------------------------------------- apply
    def apply_plan(self, drop):
        comm = self.community if self.use_community else {}
        return core.make_plan(self.mods, self.checked, self.broken, drop, comm, self.user, self.mode, self.manual)
