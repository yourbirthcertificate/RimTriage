"""Compatibility sweep: log reader, static scan and the crash finder's bisect logic. No UI code."""
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import core
from .core import CORE, DLC_ORDER

HARMONY = "brrainz.harmony"
ESSENTIAL = {CORE, HARMONY, *DLC_ORDER}
SKIP_DIRS = {"textures", "sounds", "languages", "patches", "news", "source", "src", "preview", "materials", "meshes", "about"}
IGNORE_DLL = ("assembly-csharp", "0harmony", "unitystubs", "mscorlib", "netstandard", "system.", "unityengine", "unity.",
              "microsoft.", "monomod", "mono.", "waylith", "rimworldwaylith", "ludeon")
LOG_DIR_REL = Path("AppData/LocalLow/Ludeon Studios/RimWorld by Ludeon Studios/Logs")


def default_log_dir():
    return Path(os.environ.get("USERPROFILE", "~")) / LOG_DIR_REL


# ----------------------------------------------------------- assembly index
def build_assembly_index(mods, progress=None):
    """dll base name (lowercase) -> [package ids that load it]. Uses the folders each mod really loads
    for this game version (LoadFolders.xml aware), so unused old-version DLLs don't count."""
    idx = defaultdict(list)
    for p, m in mods.items():
        for d in m.dlls:
            idx[d].append(p)
    return dict(idx)


# --------------------------------------------------------------- log reader
HDR = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)\.\d+\s+(ERROR|WARN|INFO)\s+\[(\w+)\]\s?(.*)")
FRAME_DLL = re.compile(r"\bin ([\w.\-+]+?)\.dll\b")
KIND_WEIGHT = {"instantiate": 6, "async": 6, "typeload": 3, "error": 2, "xml": 1, "patchfail": 0.3, "symptom": 0}
RULES_FILE = core.APP_DIR / "diagnose_rules.json"
DEFAULT_RULES = {
    "_help": ("How the log reader scores errors. weights: points per error kind (instantiate = a mod failed to start, async = "
              "fatal error during game setup, symptom = repeated fallout that is never blamed). A mod is a 'cause' when it has a "
              "fatal error and at least cause_min_score points, a 'suspect' from suspect_min_score. framework_factor scales plain "
              "errors of shared libraries (they are often just victims). ignore_dll_prefixes: DLLs "
              "never blamed (game and system files). Delete this file to restore the defaults."),
    "weights": KIND_WEIGHT,
    "cause_min_score": 6,
    "suspect_min_score": 2,
    "framework_factor": 0.5,
    "ignore_dll_prefixes": list(IGNORE_DLL),
}


def load_rules():
    """Defaults, overridden by diagnose_rules.json when it exists and parses."""
    rules = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in DEFAULT_RULES.items()}
    try:
        user = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        rules["weights"].update({k: float(v) for k, v in user.get("weights", {}).items() if k in KIND_WEIGHT})
        for k in ("cause_min_score", "suspect_min_score", "framework_factor"):
            if k in user:
                rules[k] = float(user[k])
        if isinstance(user.get("ignore_dll_prefixes"), list):
            rules["ignore_dll_prefixes"] = [str(x).lower() for x in user["ignore_dll_prefixes"]]
    except (OSError, ValueError, AttributeError):
        pass
    return rules


def ensure_files():
    if not RULES_FILE.exists():
        try:
            RULES_FILE.write_text(json.dumps(DEFAULT_RULES, indent=2), encoding="utf-8")
        except OSError:
            pass


@dataclass
class Evidence:
    pid: str
    score: float = 0.0
    verdict: str = "noise"          # cause | suspect | noise
    count: int = 0
    heads: list = field(default_factory=list)   # [(headline, count, line)]
    kinds: set = field(default_factory=set)
    lib: bool = False               # a framework or library other mods depend on


@dataclass
class Analysis:
    path: str
    n_err: int = 0
    n_warn: int = 0
    fatal: dict = None              # first fatal block: time, line, headline, pids
    symptoms: int = 0
    notes: list = field(default_factory=list)
    rows: list = field(default_factory=list)    # [Evidence], worst first


def _kind(msg):
    if "Error while instantiating a mod" in msg:
        return "instantiate"
    if "Exception from asynchronous event" in msg or "ErrorWhileGeneratingMap" in msg:
        return "async"
    if "Could not regenerate layer" in msg or "Exception was thrown while trying to handle exception" in msg:
        return "symptom"
    if "Patch operation" in msg:
        return "patchfail"
    if "TypeLoadException" in msg or "ReflectionTypeLoadException" in msg or "BadImageFormatException" in msg \
            or "MissingMethodException" in msg or "MissingFieldException" in msg:
        return "typeload"
    if msg.startswith(("XML error", "Config error", "Could not find class")):
        return "xml"
    return "error"


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_blocks(lines):
    blocks, cur = [], None
    for i, l in enumerate(lines, 1):
        m = HDR.match(l)
        if m:
            if cur:
                blocks.append(cur)
            cur = {"line": i, "time": m.group(2), "level": m.group(3), "msg": m.group(5).strip(), "body": []}
        elif cur is not None:
            cur["body"].append(l)
    if cur:
        blocks.append(cur)
    return blocks


def name_index(mods):
    idx = {}
    for p, m in mods.items():
        idx.setdefault(_norm(m.name), p)
    return idx


def attribute(msg, text, asm_index, name_idx, ignore):
    """Which mods does an error block point at? Uses the DLLs named in its stack trace, the type that failed to
    start, and the [Mod name] prefix some mods put on their log lines."""
    pids = set()
    for dll in FRAME_DLL.findall(text):
        d = dll.lower()
        if d.startswith(ignore):
            continue
        pids.update(asm_index.get(d, []))
    m = re.search(r"instantiating a mod of type ([\w.]+)", msg)
    if m:
        root = m.group(1).split(".")[0].lower()
        if root == "harmonymod":
            pids.add(HARMONY)
        else:
            pids.update(asm_index.get(root, []))
    m = re.match(r"\[([^\]]+?)(?: - Start of stack trace)?\]", msg)
    if m and _norm(m.group(1)) in name_idx:
        pids.add(name_idx[_norm(m.group(1))])
    return pids


def analyze_log(path, mods, asm_index):
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    A = Analysis(str(path))
    rules = load_rules()
    weight, ignore = rules["weights"], tuple(rules["ignore_dll_prefixes"])
    name_idx = name_index(mods)
    rev = core.reverse_deps(mods)
    libs = {p for p, m in mods.items() if m.source != "official" and (len(rev.get(p, ())) >= 3 or core.FRAMEWORK_RE.search(m.name))}
    ev, fatal_blocks = {}, []

    def add(pid, kind, head, line):
        e = ev.setdefault(pid, Evidence(pid, lib=pid in libs))
        # a shared library is often just the victim in someone else's stack trace, so its plain errors count for less
        e.score += weight[kind] * (rules["framework_factor"] if e.lib and kind in ("error", "typeload") else 1)
        e.count += 1
        e.kinds.add(kind)
        for i, (h, c, ln) in enumerate(e.heads):
            if h == head:
                e.heads[i] = (h, c + 1, ln)
                return
        e.heads.append((head, 1, line))

    for b in parse_blocks(lines):
        if b["level"] == "WARN":
            A.n_warn += 1
            continue
        if b["level"] != "ERROR":
            continue
        A.n_err += 1
        kind = _kind(b["msg"])
        if kind == "symptom":
            A.symptoms += "Could not regenerate layer" in b["msg"]
        text = "\n".join([b["msg"]] + b["body"][:60])
        head = re.sub(r"\s+", " ", re.sub(r"\d+", "N", b["msg"]))[:160]
        pids = attribute(b["msg"], text, asm_index, name_idx, ignore)
        if kind == "async":
            fatal_blocks.append({"time": b["time"], "line": b["line"], "headline": b["msg"][:200], "pids": sorted(pids),
                                 "mapish": any(k in text for k in ("InitNewGame", "MapDrawer", "FinalizeInit", "LoadGame", "set_CurrentMap"))})
        for p in pids:
            add(p, kind, head, b["line"])
    # the fatal error that matters: the first one with a named mod during map or game setup
    A.fatal = next((f for f in fatal_blocks if f["mapish"] and f["pids"]), None) \
        or next((f for f in fatal_blocks if f["pids"]), None) or (fatal_blocks[0] if fatal_blocks else None)
    for e in ev.values():
        has_fatal = bool(e.kinds & {"instantiate", "async"})
        e.verdict = "cause" if has_fatal and e.score >= rules["cause_min_score"] else (
            "suspect" if e.score >= rules["suspect_min_score"] else "noise")
        e.heads.sort(key=lambda h: -h[1])
    A.rows = sorted(ev.values(), key=lambda e: (-e.score, -e.count))
    if HARMONY in ev and "instantiate" in ev[HARMONY].kinds:
        A.notes.append("Harmony's own runtime patching failed to start. Mods that rely on Harmony transpilers or newer Harmony "
                       "attributes can misbehave on this build, and removing Harmony itself will not help.")
    if any("Waylith" in l for l in lines[:400]) or any("RimWorldWaylith" in l for l in lines[:4000]):
        A.notes.append("This game build runs on a new engine layer (Waylith), not standard Unity. Older mods that touch Unity "
                       "internals are the most likely to break.")
    if A.symptoms:
        A.notes.append("%d 'could not regenerate layer' errors (fog, sand, snow) are a symptom: the colony map was never built "
                       "because an earlier error aborted map creation." % A.symptoms)
    return A


# ------------------------------------------------------------- static scan
@dataclass
class Finding:
    sev: str            # error | warn | info
    title: str
    detail: str
    pids: list = field(default_factory=list)
    fix: tuple = None   # ("untick" | "tick", [pids])


def _norm_title(name):
    return re.sub(r"\(.*?\)|\[.*?\]|[^a-z0-9]", "", name.lower())


def quick_scan(mods, checked, broken, target, asm_index):
    """Checks that need no file reading beyond the assembly index."""
    out = []
    on = {p for p, v in checked.items() if v}
    nm = lambda p: mods[p].name  # noqa
    # 1. incompatible pairs
    seen = set()
    for p in on:
        for x in mods[p].incompat:
            if x in on and x in mods and (x, p) not in seen:
                seen.add((p, x))
                out.append(Finding("error", "Declared incompatible", "%s says it does not work with %s, and both are ticked." % (nm(p), nm(x)),
                                   [p, x], ("untick", [p])))
    # 2. ticked but missing something
    for p in sorted(on & set(broken), key=lambda q: nm(q).lower()):
        d = broken[p]
        out.append(Finding("error", "Missing dependency", "%s needs %s, which is %s." % (
            nm(p), d.display, "not installed" if not any(x in mods for x in d.ids) else "unable to load"), [p], ("untick", [p])))
    # 3. mods that bundle their own Harmony
    own = [p for p in sorted(on, key=lambda q: nm(q).lower()) if p != HARMONY and p in asm_index.get("0harmony", [])]
    if own:  # one line: most carry it in old version folders where it never loads
        out.append(Finding("info", "%d mods bundle their own Harmony" % len(own),
                           "%s%s. Usually harmless, but a copy that does load can shadow the Harmony mod. Worth a look if Harmony errors appear." % (
                               ", ".join(nm(p) for p in own[:5]), " and %d more" % (len(own) - 5) if len(own) > 5 else ""), own))
    # 4. near-duplicate mods
    groups = defaultdict(list)
    for p in on:
        if mods[p].source != "official":
            n = _norm_title(mods[p].name)
            if len(n) >= 6:
                groups[n].append(p)
    for n, ps in groups.items():
        if len(ps) > 1:
            out.append(Finding("warn", "Looks like the same mod twice", "These share a name: %s." % ", ".join(sorted(nm(p) for p in ps)), ps,
                               ("untick", sorted(ps, key=lambda p: core.vkey(core.max_version(mods[p])) or (0, 0))[:-1])))
    # 5. patches you left off
    for p, m in mods.items():
        if p in on or m.source == "official" or p in broken or not core.version_ok(m, target):
            continue
        hard = {x for d in m.deps for x in d.ids if x in mods and mods[x].source != "official"}
        patchy = bool(core.PATCH_RE.search(m.name))
        if hard and all(h in on for h in hard) and (len(hard) >= 2 or patchy):
            out.append(Finding("info", "A patch you have but left off", "%s is installed and patches %s, which you have ticked." % (
                m.name, " and ".join(sorted(nm(h) for h in hard)[:3])), [p], ("tick", [p])))
    return out


DEF_RE = re.compile(r"<(\w+Def)\b[^>]{0,400}>\s{0,200}<defName>\s*([^<\s]+)\s*</defName>")


def def_overlap(mods, checked, order, progress=None):
    """Mods that define the same def. The later one in the load order wins."""
    on = [p for p in order if checked.get(p) and mods[p].source != "official"]
    owners = defaultdict(list)
    for n, p in enumerate(on):
        if progress and n % 20 == 0:
            progress(n, len(on))
        for base in mods[p].load_dirs or [mods[p].path]:
            defs = Path(base) / "Defs"
            if not defs.is_dir():
                continue
            for root, _, files in os.walk(defs):
                for f in files:
                    if not f.lower().endswith(".xml"):
                        continue
                    fp = Path(root) / f
                    try:
                        if fp.stat().st_size > 3_000_000:
                            continue
                        txt = fp.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    if "<defName>" not in txt:
                        continue
                    for t, name in DEF_RE.findall(txt):
                        owners[(t, name)].append(p)
    pairs = defaultdict(list)
    for key, ps in owners.items():
        ps = list(dict.fromkeys(ps))
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                pairs[(ps[i], ps[j])].append(key[1])
    out = []
    for (a, b), names in sorted(pairs.items(), key=lambda kv: -len(kv[1])):
        related = b in {x for d in mods[a].deps for x in d.ids} or a in {x for d in mods[b].deps for x in d.ids} \
            or b in mods[a].after or a in mods[b].after
        if related or len(names) < 3:
            continue
        out.append(Finding("warn" if len(names) >= 8 else "info", "Defines the same things",
                           "%s and %s both define %d of the same defs (for example %s). %s loads later, so its version wins." % (
                               mods[a].name, mods[b].name, len(names), ", ".join(names[:3]), mods[b].name), [a, b]))
        if len(out) >= 60:
            break
    return out


# -------------------------------------------------------------- crash finder
class Bisect:
    """Finds the first mod, in load order, at which the problem appears.

    A prefix of a valid load order is always dependency-complete, so every test list is loadable.
    Assumes the problem persists once the culprit is included."""

    def __init__(self, order, essentials, extra=(), full=None):
        self.order = list(order)
        self.extra = set(extra)                       # always loaded, on top of the tested prefix
        self.full = list(full) if full else list(order)  # the list every test list is cut from, in load order
        self.lo = max(essentials, 1)   # this many mods are assumed fine
        self.hi = len(order)           # this many are known to reproduce the problem
        self.rounds = 0

    def total_rounds(self):
        import math
        return max(1, math.ceil(math.log2(max(self.hi - self.lo, 2))))

    def next_size(self):
        return None if self.hi - self.lo <= 1 else (self.lo + self.hi) // 2

    def answer(self, size, still_broken):
        self.rounds += 1
        if still_broken:
            self.hi = size
        else:
            self.lo = size

    def culprit(self):
        return self.order[self.hi - 1] if self.hi - self.lo <= 1 else None

    def test_list(self, size):
        keep = set(self.order[:size]) | self.extra
        return [p for p in self.full if p in keep]


# ------------------------------------------------------------- live watcher
@dataclass
class LiveEvent:
    time: str
    kind: str
    head: str
    pids: list
    count: int = 1
    line: int = 0
    fatal: bool = False


class LogTail:
    """Follows Player.log while the game runs and turns finished ERROR blocks into events."""

    SHOWN = {"instantiate", "async", "typeload", "error", "symptom"}

    def __init__(self, path, mods, asm_index):
        self.path, self.mods, self.idx = Path(path), mods, asm_index
        self.name_idx = name_index(mods)
        self.ignore = tuple(load_rules()["ignore_dll_prefixes"])
        self.reset()

    def reset(self):
        self.pos, self.rest, self.cur, self.lineno, self.idle = 0, "", None, 0, 0
        self.events, self.by_key = [], {}
        self.n_err = self.n_warn = self.n_fatal = self.n_noise = 0

    def poll(self):
        """Read what was appended since the last call. Returns the events created by it."""
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.pos:  # the game started a fresh log
            self.reset()
        new = []
        if size > self.pos:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                data = f.read(size - self.pos)
            self.pos, self.idle = size, 0
            lines = (self.rest + data.decode("utf-8", errors="replace")).split("\n")
            self.rest = lines.pop()
            for l in lines:
                ev = self._feed(l.rstrip("\r"))
                if ev:
                    new.append(ev)
        else:
            self.idle += 1
            if self.idle == 2:  # a quiet log: the pending block is complete
                ev = self.flush()
                if ev:
                    new.append(ev)
        return new

    def flush(self):
        return self._finish()

    def _feed(self, line):
        self.lineno += 1
        m = HDR.match(line)
        if m:
            ev = self._finish()
            self.cur = {"line": self.lineno, "time": m.group(2), "level": m.group(3), "msg": m.group(5).strip(), "body": []}
            return ev
        if self.cur is not None and len(self.cur["body"]) < 60:
            self.cur["body"].append(line)
        return None

    def _finish(self):
        b, self.cur = self.cur, None
        if not b:
            return None
        if b["level"] == "WARN":
            self.n_warn += 1
            return None
        if b["level"] != "ERROR":
            return None
        self.n_err += 1
        kind = _kind(b["msg"])
        if kind not in self.SHOWN:
            self.n_noise += 1
            return None
        head = re.sub(r"\s+", " ", re.sub(r"\d+", "N", b["msg"]))[:160]
        pids = sorted(attribute(b["msg"], "\n".join([b["msg"]] + b["body"]), self.idx, self.name_idx, self.ignore))
        key = (kind, head, tuple(pids))
        fatal = kind in ("instantiate", "async")
        if fatal:
            self.n_fatal += 1
        ev = self.by_key.get(key)
        if ev:
            ev.count += 1
            return None
        ev = LiveEvent(b["time"], kind, head, pids, 1, b["line"], fatal)
        self.by_key[key] = ev
        if len(self.events) < 400:
            self.events.append(ev)
        return ev
