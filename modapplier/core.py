"""Core logic for RimWorld Mod Applier. No UI code in here."""
import heapq
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
SETTINGS_FILE = APP_DIR / "settings.json"
PROFILE_DIR = APP_DIR / "profiles"
APPID = "294100"
CORE = "ludeon.rimworld"
DLC_ORDER = ["ludeon.rimworld.royalty", "ludeon.rimworld.ideology", "ludeon.rimworld.biotech",
             "ludeon.rimworld.anomaly", "ludeon.rimworld.odyssey"]
TIER_NAMES = ["Core", "DLC", "Harmony", "Early", "Library", "Mod", "Patch", "Last"]
COMMUNITY_FILE = APP_DIR / "communityRules.json"
USER_RULES_FILE = APP_DIR / "user_rules.json"
COMMUNITY_URL = "https://raw.githubusercontent.com/RimSort/Community-Rules-Database/main/communityRules.json"
FRAMEWORK_RE = re.compile(r"\b(framework|library|lib|api|core)\b", re.I)
PATCH_RE = re.compile(r"\b(patch(es)?|compat(ibility)?|fix(es)?|translations?)\b", re.I)
LAST_IDS = {"bs.performance", "krkr.rocketman"}


# ----------------------------------------------------------------- data model
@dataclass
class Dep:
    ids: tuple
    display: str
    url: str = ""


@dataclass
class Mod:
    pid: str
    name: str
    path: Path
    source: str  # official | local | workshop
    author: str = ""
    versions: list = field(default_factory=list)
    deps: list = field(default_factory=list)
    after: set = field(default_factory=set)
    before: set = field(default_factory=set)
    incompat: set = field(default_factory=set)
    desc: str = ""
    load_dirs: list = field(default_factory=list)   # folders the game really loads for the current version
    dlls: list = field(default_factory=list)        # lowercase base names of the DLLs in those folders


def vkey(s):
    m = re.match(r"v?(\d+)\.(\d+)", str(s).strip().lower())
    return (int(m.group(1)), int(m.group(2))) if m else None


def version_ok(mod, target):
    if mod.source == "official" or not mod.versions:
        return True
    t = vkey(target)
    allowed = {t, (t[0], t[1] - 1)}  # current build + the one before it
    return any(vkey(v) in allowed for v in mod.versions)


def max_version(mod):
    ks = [k for k in map(vkey, mod.versions) if k]
    return "%d.%d" % max(ks) if ks else "?"


# ------------------------------------------------------------------- parsing
def _dep_items(node):
    out = []
    for li in node.findall("li"):
        pid = (li.findtext("packageId") or "").strip().lower()
        if not pid:
            continue
        alts = [(a.text or "").strip().lower() for a in li.findall("alternativePackageIds/li")]
        url = (li.findtext("steamWorkshopUrl") or li.findtext("downloadUrl") or "").strip()
        out.append(Dep(tuple([pid] + [a for a in alts if a]),
                       (li.findtext("displayName") or pid).strip(), url))
    return out


def _collect(root, tag, target, deps=False):
    nodes = []
    n = root.find(tag)
    if n is not None:
        nodes.append(n)
    b = root.find(tag + "ByVersion")
    if b is not None:
        best, tk = None, vkey(target)
        for c in b:
            k = vkey(c.tag)
            if k and k <= tk and (best is None or k > best[0]):
                best = (k, c)
        if best:
            nodes.append(best[1])
    if deps:
        seen, out = set(), []
        for n in nodes:
            for d in _dep_items(n):
                if d.ids not in seen:
                    seen.add(d.ids)
                    out.append(d)
        return out
    return {(li.text or "").strip().lower() for n in nodes for li in n.findall("li") if (li.text or "").strip()}


def parse_about(path, target, source, folder):
    data = path.read_bytes()
    root = None
    try:
        root = ET.fromstring(data.lstrip(b"\xef\xbb\xbf \r\n\t"))
    except ET.ParseError:
        pass
    if root is None:  # broken XML: salvage the essentials with regex
        txt = data.decode("utf-8", "ignore")
        pid = re.search(r"<packageId>\s*([^<]+?)\s*</packageId>", txt, re.I)
        nm = re.search(r"<name>\s*([^<]+?)\s*</name>", txt, re.I)
        if not pid:
            return None
        return Mod(pid.group(1).strip().lower(), nm.group(1) if nm else folder, path.parent.parent, source)
    pid = (root.findtext("packageId") or "").strip().lower()
    if not pid:
        return None
    m = Mod(pid, (root.findtext("name") or folder).strip(), path.parent.parent, source,
            (root.findtext("author") or root.findtext("authors/li") or "").strip())
    m.desc = re.sub(r"<[^>]+>", "", root.findtext("description") or "").strip()
    m.versions = [(li.text or "").strip() for li in root.findall("supportedVersions/li")]
    m.deps = _collect(root, "modDependencies", target, deps=True)
    m.after = _collect(root, "loadAfter", target) | _collect(root, "forceLoadAfter", target)
    m.before = _collect(root, "loadBefore", target) | _collect(root, "forceLoadBefore", target)
    m.incompat = _collect(root, "incompatibleWith", target)
    return m


def load_dirs(path, target):
    """The folders RimWorld loads from a mod for this game version.
    LoadFolders.xml wins when present (the node for this version, else the newest older one, else <default>).
    Without it: the mod root, Common, and the newest version folder that is not newer than the game."""
    path, tk = Path(path), vkey(target)
    lf = path / "LoadFolders.xml"
    if lf.is_file():
        try:
            root = ET.parse(lf).getroot()
        except (ET.ParseError, OSError):
            root = None
        if root is not None:
            best, dflt = None, None
            for child in root:
                k = vkey(child.tag) if re.fullmatch(r"v?\d+\.\d+", str(child.tag)) else None
                if child.tag == "default":
                    dflt = child
                elif k and tk and k <= tk and (best is None or k > best[0]):
                    best = (k, child)
            node = best[1] if best else dflt
            if node is not None:
                out = []
                for li in node.findall("li"):
                    rel = (li.text or "").strip().strip("/\\")
                    d = path / rel if rel else path
                    if d.is_dir() and d not in out:
                        out.append(d)
                return out or [path]
    out = [path]
    if (path / "Common").is_dir():
        out.append(path / "Common")
    best = None
    try:
        for d in path.iterdir():
            if d.is_dir() and re.fullmatch(r"v?\d+\.\d+", d.name):
                k = vkey(d.name)
                if k and tk and k <= tk and (best is None or k > best[0]):
                    best = (k, d)
    except OSError:
        pass
    if best:
        out.append(best[1])
    return out


def _dll_names(dirs):
    names = []
    for d in dirs:
        a = d / "Assemblies"
        if a.is_dir():
            for root, _, files in os.walk(a):
                names += [f[:-4].lower() for f in files if f.lower().endswith(".dll")]
    return sorted(set(names))


def unverified(mod, target):
    """Built for the previous game version only, and it ships code. On a pre-release build that is the likeliest to crash."""
    if mod.source == "official" or not mod.dlls or not mod.versions:
        return False
    t = vkey(target)
    ks = {vkey(v) for v in mod.versions}
    return bool(t) and t not in ks and (t[0], t[1] - 1) in ks


def scan(game, workshop, target):
    """Returns (mods, duplicates, unreadable). First source wins: official > local > workshop."""
    mods, dups, bad = {}, [], []
    sources = []
    if game:
        sources.append(("official", Path(game) / "Data"))
        sources.append(("local", Path(game) / "Mods"))
    if workshop:
        sources.append(("workshop", Path(workshop)))
    for source, base in sources:
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            about = d / "About" / "About.xml"
            if not about.is_file():
                continue
            try:
                m = parse_about(about, target, source, d.name)
            except Exception as e:  # noqa
                bad.append((d.name, "unreadable About.xml: %s" % e))
                continue
            if m is None:
                bad.append((d.name, "no packageId in About.xml"))
            elif m.pid in mods:
                dups.append((m.name, "duplicate of %s (kept %s copy)" % (mods[m.pid].path.name, mods[m.pid].source)))
            else:
                if source != "official":
                    m.load_dirs = load_dirs(m.path, target)
                    m.dlls = _dll_names(m.load_dirs)
                mods[m.pid] = m
    return mods, dups, bad


# ---------------------------------------------------------------- analysis
def broken_set(mods):
    """pid -> Dep that can't be satisfied (not installed, or itself broken). Transitive."""
    broken, changed = {}, True
    while changed:
        changed = False
        for m in mods.values():
            if m.pid in broken:
                continue
            for d in m.deps:
                if not any(x in mods and x not in broken for x in d.ids):
                    broken[m.pid] = d
                    changed = True
                    break
    return broken


def auto_checked(mods, target, broken, safe=False):
    """Which mods to tick by default. `safe` also leaves out previous-version mods that ship code."""
    cand = {p for p, m in mods.items() if p not in broken and version_ok(m, target) and not (safe and unverified(m, target))}
    changed = True
    while changed:
        changed = False
        for p in list(cand):
            m = mods[p]
            if m.source != "official" and any(not any(x in cand for x in d.ids) for d in m.deps):
                cand.discard(p)
                changed = True
    return {p: p in cand for p in mods}


def compute_status(mods, checked, target, broken):
    """pid -> list of (kind, text). kinds: missing, conflict, enable, outdated."""
    out = {}
    on = {p for p, v in checked.items() if v}
    for p, m in mods.items():
        fl = []
        if p in broken:
            d = broken[p]
            fl.append(("missing", ("Missing: %s" if not any(x in mods for x in d.ids) else "Needs unavailable: %s") % d.display))
        if checked.get(p):
            c = sorted(mods[x].name for x in m.incompat if x in on and x in mods)
            if c:
                fl.append(("conflict", "Conflicts with " + ", ".join(c[:3])))
            off = [d.display for d in m.deps if not any(x in on for x in d.ids)
                   and any(x in mods and x not in broken for x in d.ids)]
            if off and p not in broken:
                fl.append(("enable", "Needs " + ", ".join(off[:3]) + " (off)"))
        if not version_ok(m, target):
            fl.append(("outdated", "Outdated (%s)" % max_version(m)))
        elif unverified(m, target):
            fl.append(("unverified", "Unverified (%s, code)" % max_version(m)))
        out[p] = fl
    return out


def status_text(flags):
    return "; ".join(t for _, t in flags)


# ------------------------------------------------------------- smart rules
MODES = {"strict": "Strict", "balanced": "Balanced", "grouped": "Grouped"}
UI_RE = re.compile(r"\b(ui|menu|menus|tab|tabs|icon|icons|interface|architect|toolbar|hud|tooltips?|dialogs?|dropdowns?)\b", re.I)
GFX_RE = re.compile(r"\b(textures?|retextures?|graphics|visuals?|hd|4k|upscal\w*|skins?|recolou?r\w*|portraits?|shaders?|cosmetics?)\b", re.I)


def _keys(v):
    return {str(k).lower() for k in v} if isinstance(v, dict) else set()


def _flag(v):
    return isinstance(v, dict) and bool(v.get("value"))


def load_community():
    """RimSort community-rules database -> {pid: {after, before, top, bottom}}."""
    try:
        raw = json.loads(COMMUNITY_FILE.read_text(encoding="utf-8")).get("rules", {})
    except Exception:
        return {}
    out = {}
    for pid, r in raw.items():
        if isinstance(r, dict):
            out[pid.lower()] = {"after": _keys(r.get("loadAfter")), "before": _keys(r.get("loadBefore")),
                                "top": _flag(r.get("loadTop")), "bottom": _flag(r.get("loadBottom"))}
    return out


def download_community():
    import urllib.request
    req = urllib.request.Request(COMMUNITY_URL, headers={"User-Agent": "rimworld-mod-applier"})
    data = urllib.request.urlopen(req, timeout=60).read()
    n = len(json.loads(data)["rules"])  # raises if the format isn't what we expect
    COMMUNITY_FILE.write_bytes(data)
    return n


def load_user_rules():
    try:
        r = json.loads(USER_RULES_FILE.read_text())
    except Exception:
        r = {}
    return {"top": list(r.get("top", [])), "bottom": list(r.get("bottom", [])),
            "after": [list(x) for x in r.get("after", [])]}  # after: [mod, other] = mod loads after other


def save_user_rules(r):
    USER_RULES_FILE.write_text(json.dumps(r, indent=1))


def _norm_user(u):
    u = u or {}
    return {"top": u.get("top", []), "bottom": u.get("bottom", []), "after": u.get("after", [])}


def compute_tiers(ids, mods, community, user, mode):
    """-> (tiers, bands, why). Tier is the coarse group, band splits ordinary mods in Grouped mode."""
    strict = mode == "strict"
    utop, ubot = set(user.get("top", [])), set(user.get("bottom", []))
    dep_count = Counter()
    for p in ids:
        for d in mods[p].deps:
            for x in d.ids:
                if x in ids:
                    dep_count[x] += 1
    tiers, bands, why = {}, {}, defaultdict(list)
    for p in ids:
        m, c = mods[p], community.get(p, {})
        band = 0
        if p == CORE:
            t, r = 0, "game core"
        elif p in DLC_ORDER:
            t, r = 1, "official expansion"
        elif p == "brrainz.harmony":
            t, r = 2, "Harmony loads first"
        elif p in ubot:
            t, r = 7, "pinned to the end by you"
        elif p in utop:
            t, r = 3, "pinned to the start by you"
        elif c.get("bottom") or p in LAST_IDS or "rocketman" in p:
            t, r = 7, "community rule: load last"
        elif c.get("top"):
            t, r = 3, "community rule: load early"
        elif strict:
            t, r = 5, ""
        elif PATCH_RE.search(m.name):
            t, r = 6, "name looks like a patch or compatibility mod"
        elif dep_count[p] >= 2:
            t, r = 4, "library: %d mods need it" % dep_count[p]
        elif FRAMEWORK_RE.search(m.name):
            t, r = 4, "name looks like a framework or library"
        else:
            t, r = 5, ""
            if mode == "grouped":
                if UI_RE.search(m.name):
                    band, r = 1, "interface mod"
                elif GFX_RE.search(m.name):
                    band, r = 2, "visual mod"
        tiers[p], bands[p] = t, band
        if r:
            why[p].append(r)
    return tiers, bands, why


def rule_edges(ids, mods, community, user):
    """(a, b, kind): a loads before b. Strongest rules first."""
    for p in sorted(ids):
        for d in mods[p].deps:
            for x in d.ids:
                yield x, p, "needs"
    for a, b in user.get("after", []):
        yield b, a, "your rule"
    for p in sorted(ids):
        for x in mods[p].after:
            yield x, p, "mod rule"
        for x in mods[p].before:
            yield p, x, "mod rule"
    for p in sorted(ids):
        c = community.get(p)
        if c:
            for x in c["after"]:
                yield x, p, "community"
            for x in c["before"]:
                yield p, x, "community"


@dataclass
class Sorted:
    order: list
    tiers: dict
    bands: dict
    why: dict
    warns: list
    edges: list  # accepted (a, b, kind)
    pre: dict
    succ: dict
    names: dict
    dropped: list = field(default_factory=list)  # [(a, b, kind, chain)] rules left out because they would loop

    def rank(self, p):
        return (self.tiers[p], self.bands[p], self.names[p])


def sort_order(ids, mods, community=None, user=None, mode="balanced", base=None, reverse=False):
    """Rule-aware topological sort.

    Constraint strength: dependencies > your rules > the mod's own rules > community rules. A weaker rule
    that would create a cycle is dropped instead of scrambling the order. Ties are broken by tier.
    `base` (pid -> position) turns this into a minimal-movement fix of an existing manual order.
    """
    community, user = community or {}, _norm_user(user)
    ids = set(ids)
    tiers, bands, why = compute_tiers(ids, mods, community, user, mode)
    names = {p: mods[p].name.lower() for p in ids}

    def key(p):
        if base is not None:
            return (base.get(p, 10 ** 9), names[p], p)
        tie = DLC_ORDER.index(p) if p in DLC_ORDER else 0
        return (tiers[p], bands[p], tie, names[p], p)

    pre = {p: set() for p in ids}
    succ = {p: set() for p in ids}

    def find_path(src, dst):
        """Chain of 'must load before' links from src to dst, or None."""
        parent, stack = {src: None}, [src]
        while stack:
            n = stack.pop()
            if n == dst:
                path = []
                while n is not None:
                    path.append(n)
                    n = parent[n]
                return path[::-1]
            for s in succ[n]:
                if s not in parent:
                    parent[s] = n
                    stack.append(s)
        return None

    skipped, warns, edges, dropped = Counter(), [], [], []
    for a, b, kind in rule_edges(ids, mods, community, user):
        if a == b or a not in ids or b not in ids or a in pre[b]:
            continue
        if mods[a].source != "official" and mods[b].source == "official":
            continue
        chain = find_path(b, a)
        if chain:  # b already has to load before a, so "a before b" would make a loop
            skipped[kind] += 1
            dropped.append((a, b, kind, chain))
            if kind != "community":
                warns.append("Ignored conflicting rule: '%s' before '%s' (%s)" % (mods[a].name, mods[b].name, kind))
            continue
        pre[b].add(a)
        succ[a].add(b)
        edges.append((a, b, kind))
        why[b].append("after %s [%s]" % (mods[a].name, kind))
    if skipped["community"]:
        warns.append("%d community rules skipped (conflicted with stronger rules)" % skipped["community"])

    pre0, succ0 = pre, succ
    if reverse:  # sort backwards: prerequisites move earlier instead of their dependents moving later
        pre, succ = succ, pre
        fwd = key
        key = lambda p: (-fwd(p)[0],) + tuple(fwd(p)[1:])  # noqa
    indeg = {p: len(pre[p]) for p in ids}
    heap = [(key(p), p) for p in ids if indeg[p] == 0]
    heapq.heapify(heap)
    done, out = set(), []
    while len(out) < len(ids):
        if not heap:  # safety net; cycles are rejected above
            p = min((x for x in ids if x not in done), key=key)
            warns.append("Load-order cycle: forced '%s'" % mods[p].name)
            heap = [(key(p), p)]
        _, p = heapq.heappop(heap)
        if p in done:
            continue
        done.add(p)
        out.append(p)
        for s in succ[p]:
            indeg[s] -= 1
            if indeg[s] == 0 and s not in done:
                heapq.heappush(heap, (key(s), s))
    if reverse:
        out.reverse()
    return Sorted(out, tiers, bands, dict(why), warns, edges, pre0, succ0, names, dropped)


def validate_order(order, S):
    """Rules the current order breaks: [(a, b, kind)] meaning a should load before b."""
    pos = {p: i for i, p in enumerate(order)}
    bad = [(a, b, k) for a, b, k in S.edges if a in pos and b in pos and pos[a] > pos[b]]
    if CORE in pos and pos[CORE] != 0:
        bad.append((CORE, order[0], "game core"))
    return bad


def violation_text(v, mods):
    a, b, k = v
    return "'%s' should load before '%s' (%s)" % (mods[a].name, mods[b].name, k)


def insert_mod(cur, p, S):
    """Where p belongs in the already ordered list cur: after its prerequisites, before what needs it."""
    pos = {q: i for i, q in enumerate(cur)}
    lo = max((pos[a] + 1 for a in S.pre[p] if a in pos), default=0)
    hi = min((pos[b] for b in S.succ[p] if b in pos), default=len(cur))
    mine = S.rank(p)
    ideal = next((i for i, q in enumerate(cur) if S.rank(q) > mine), len(cur))
    idx = min(max(ideal, lo), max(hi, lo))
    return cur[:idx] + [p] + cur[idx:], idx


def moved_mods(old, new):
    """Mods that really jumped between two orders: everything outside the longest run that kept its relative order."""
    import bisect
    po = {p: i for i, p in enumerate(old)}
    seq = [(po[p], p) for p in new if p in po]
    tails, tail_idx, prev = [], [], [None] * len(seq)
    for i, (v, _) in enumerate(seq):
        k = bisect.bisect_left(tails, v)
        if k == len(tails):
            tails.append(v)
            tail_idx.append(i)
        else:
            tails[k] = v
            tail_idx[k] = i
        prev[i] = tail_idx[k - 1] if k else None
    keep, i = set(), (tail_idx[-1] if tail_idx else None)
    while i is not None:
        keep.add(seq[i][1])
        i = prev[i]
    return [p for _, p in seq if p not in keep]


def sync_order(manual, ids, mods, community, user, mode):
    """Keep a hand-made order: drop unticked mods, slot newly ticked ones in the right place."""
    ids = set(ids)
    cur = [p for p in manual if p in ids]
    have = set(cur)
    new = ids - have
    S = sort_order(ids, mods, community, user, mode)
    if new:
        for p in S.order:
            if p in new:
                cur, _ = insert_mod(cur, p, S)
    return cur, S


@dataclass
class Plan:
    order: list          # [(pid, tier)]
    pulled: list
    dropped: list
    missing: list
    warnings: list
    why: dict = field(default_factory=dict)
    violations: list = field(default_factory=list)
    sorted: object = None
    dropped_rules: list = field(default_factory=list)


def make_plan(mods, checked, broken, drop_missing=True, community=None, user=None, mode="balanced", manual=None):
    ticked = {p for p, v in checked.items() if v and p in mods}
    if CORE in mods:
        ticked.add(CORE)
    missing = sorted(p for p in ticked if p in broken)
    dropped = set()
    if drop_missing:
        dropped = set(missing)
        ticked -= dropped
    pulled, changed = [], True
    while changed:  # auto-enable installed dependencies of ticked mods
        changed = False
        for p in list(ticked):
            for d in mods[p].deps:
                if not any(x in ticked for x in d.ids):
                    c = [x for x in d.ids if x in mods and x not in dropped and not (drop_missing and x in broken)]
                    if c:
                        ticked.add(c[0])
                        pulled.append(c[0])
                        changed = True
    if manual:
        order_ids, S = sync_order(manual, ticked, mods, community or {}, user, mode)
    else:
        S = sort_order(ticked, mods, community, user, mode)
        order_ids = S.order
    warns = list(S.warns)
    viol = validate_order(order_ids, S)
    inc = {}
    for p in ticked:
        for x in mods[p].incompat:
            if x in ticked:
                inc[tuple(sorted((p, x)))] = 1
    for a, b in inc:
        warns.append("Incompatible pair both enabled: %s + %s" % (mods[a].name, mods[b].name))
    return Plan([(p, S.tiers[p]) for p in order_ids], pulled, sorted(dropped), missing, warns, S.why, viol, S, S.dropped)


RULE_KIND_HELP = {"needs": "a dependency", "your rule": "one of your rules", "mod rule": "the mod's own loadAfter/loadBefore",
                  "community": "a community rule"}


def dropped_rule_text(d, mods):
    """Plain description of a rule that was left out, with the chain that blocked it."""
    a, b, kind, chain = d
    nm = lambda p: mods[p].name if p in mods else p  # noqa
    return ("%s should load before %s (%s), but %s already has to load before %s through: %s. "
            "Keeping both would make a loop, so the weaker rule was left out." % (
                nm(a), nm(b), RULE_KIND_HELP.get(kind, kind), nm(b), nm(a), " > ".join(nm(p) for p in chain)))


# --------------------------------------------------------- apply preview
def file_hash(path):
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def config_diff(old_ids, new_ids, mods):
    """What an apply would change in ModsConfig.xml.
    -> dict(added, removed, moved, missing): `missing` are old entries that aren't installed, so they would be dropped."""
    old_set, new_set = set(old_ids), set(new_ids)
    common_old = [p for p in old_ids if p in new_set]
    common_new = [p for p in new_ids if p in old_set]
    removed = [p for p in old_ids if p not in new_set]
    return {"added": [p for p in new_ids if p not in old_set],
            "removed": [p for p in removed if p in mods],
            "missing": [p for p in removed if p not in mods],
            "moved": moved_mods(common_old, common_new)}


# ------------------------------------------------------- dependency finder
def reverse_deps(mods):
    rev = defaultdict(set)
    for m in mods.values():
        for d in m.deps:
            for x in d.ids:
                rev[x].add(m.pid)
    return rev


def dep_state(ids, mods, checked, broken, target):
    """State of a dependency group: on, off, outdated, unavailable or missing; plus the chosen pid."""
    inst = [x for x in ids if x in mods]
    if not inst:
        return "missing", None
    p = next((x for x in inst if checked.get(x)), inst[0])
    if p in broken:
        return "unavailable", p
    if checked.get(p):
        return "on", p
    return ("outdated" if not version_ok(mods[p], target) else "off"), p


def requires_tree(pid, mods, checked, broken, target, depth=8, _path=()):
    out = []
    for d in mods[pid].deps:
        st, p = dep_state(d.ids, mods, checked, broken, target)
        node = {"pid": p, "name": mods[p].name if p else d.display, "state": st, "url": d.url, "children": []}
        if p and p not in _path and depth > 1:
            node["children"] = requires_tree(p, mods, checked, broken, target, depth - 1, _path + (pid,))
        out.append(node)
    return out


def all_requirements(pid, mods, broken=()):
    """Installed mods pid needs, directly or indirectly."""
    seen, stack = set(), [pid]
    while stack:
        for d in mods[stack.pop()].deps:
            x = next((x for x in d.ids if x in mods and x not in broken), None)
            if x and x not in seen and x != pid:
                seen.add(x)
                stack.append(x)
    return seen


def all_dependents(pid, rev):
    seen, stack = set(), [pid]
    while stack:
        for x in rev.get(stack.pop(), ()):
            if x not in seen and x != pid:
                seen.add(x)
                stack.append(x)
    return seen


def missing_report(mods):
    """Dependencies nobody installed: [(display, url, [mod names])] most-needed first."""
    rep = {}
    for m in mods.values():
        for d in m.deps:
            if not any(x in mods for x in d.ids):
                r = rep.setdefault(d.ids[0], [d.display, d.url, []])
                r[2].append(m.name)
                if not r[1] and d.url:
                    r[1] = d.url
    return sorted(((v[0], v[1], sorted(v[2])) for v in rep.values()), key=lambda r: (-len(r[2]), r[0].lower()))


def neighborhood(pid, mods, rev, checked, broken, target, radius=2):
    """Nodes within `radius` links of pid for the graph view.
    -> (nodes {key: {name, state, level}}, edges [(src, dst, kind)]); src needs / loads after / conflicts with dst."""
    nodes = {pid: {"name": mods[pid].name, "state": "focus", "level": 0}}
    edges = []

    def state(p):
        if p in broken:
            return "unavailable"
        if checked.get(p):
            return "on"
        return "outdated" if not version_ok(mods[p], target) else "off"
    frontier = [pid]
    for lvl in range(1, radius + 1):  # requirements: negative levels
        nxt = []
        for p in frontier:
            for d in mods[p].deps:
                st, x = dep_state(d.ids, mods, checked, broken, target)
                key = x or ("missing:" + d.ids[0])
                if key not in nodes:
                    nodes[key] = {"name": mods[x].name if x else d.display, "state": st if x is None else state(x), "level": -lvl}
                    if x:
                        nxt.append(x)
                edges.append((p, key, "needs"))
        frontier = nxt
    frontier = [pid]
    for lvl in range(1, radius + 1):  # dependents: positive levels
        nxt = []
        for p in frontier:
            for x in sorted(rev.get(p, ())):
                if x not in nodes:
                    nodes[x] = {"name": mods[x].name, "state": state(x), "level": lvl}
                    nxt.append(x)
                edges.append((x, p, "needs"))
        frontier = nxt
    for x in mods[pid].incompat:
        if x in mods:
            nodes.setdefault(x, {"name": mods[x].name, "state": state(x), "level": 0.0})
            edges.append((pid, x, "conflict"))
    for x in mods[pid].after:
        if x in mods and x in nodes and (pid, x, "needs") not in edges:
            edges.append((pid, x, "after"))
    return nodes, edges


# ------------------------------------------------------------------ file I/O
def steam_libraries():
    roots = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            roots.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
    except Exception:
        pass
    roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    libs = []
    for r in roots:
        if r.exists() and r not in libs:
            libs.append(r)
        vdf = r / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore")):
                p = Path(m.group(1).replace("\\\\", "\\"))
                if p not in libs:
                    libs.append(p)
    return libs


def detect_paths():
    game = workshop = ""
    for lib in steam_libraries():
        g = lib / "steamapps" / "common" / "RimWorld"
        if not game and g.exists():
            game = str(g)
        w = lib / "steamapps" / "workshop" / "content" / APPID
        if not workshop and w.exists():
            workshop = str(w)
    cfg = Path(os.environ.get("USERPROFILE", "~")) / "AppData/LocalLow/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml"
    return {"game_dir": game, "workshop_dir": workshop, "config_path": str(cfg)}


def load_settings():
    s = detect_paths()
    try:
        s.update({k: v for k, v in json.loads(SETTINGS_FILE.read_text()).items() if v or k == "last_profile"})
    except Exception:
        pass
    return s


def save_settings(s):
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))


def game_version_str(game):
    try:
        return (Path(game) / "Version.txt").read_text().strip()
    except Exception:
        return "1.7"


def read_active(config):
    try:
        return [(li.text or "").strip().lower() for li in ET.parse(config).getroot().findall("activeMods/li")]
    except Exception:
        return []


def backup_config(config):
    config = Path(config)
    if not config.exists():
        return None
    dst = config.with_name(config.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(config, dst)
    return dst


def write_config(config, order_ids, version_str):
    config = Path(config)
    root = None
    if config.exists():
        try:
            root = ET.parse(config).getroot()
        except ET.ParseError:
            root = None
    if root is None:
        root = ET.Element("ModsConfigData")
        ET.SubElement(root, "version").text = version_str
    am = root.find("activeMods")
    if am is None:
        am = ET.SubElement(root, "activeMods")
    am.clear()
    for p in order_ids:
        ET.SubElement(am, "li").text = p
    ET.indent(root)
    xml = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    config.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.with_name(config.name + ".tmp")
    tmp.write_text(xml, encoding="utf-8")
    os.replace(tmp, config)


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq RimWorldWin64.exe"], capture_output=True,
                             text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return "RimWorldWin64.exe" in out
    except Exception:
        return False


def profile_path(name):
    return PROFILE_DIR / (re.sub(r"[^\w\- ]", "_", name) + ".json")


def list_profiles():
    return sorted(p.stem for p in PROFILE_DIR.glob("*.json")) if PROFILE_DIR.exists() else []


def save_profile(name, checked, order=None):
    PROFILE_DIR.mkdir(exist_ok=True)
    data = {"on": sorted(p for p, v in checked.items() if v), "off": sorted(p for p, v in checked.items() if not v)}
    if order:
        data["order"] = list(order)
    profile_path(name).write_text(json.dumps(data, indent=1))


def read_profile(name):
    return json.loads(profile_path(name).read_text())


def apply_profile(name, base):
    """-> (checked, order or None). Mods the profile has never seen keep their auto state."""
    prof = read_profile(name)
    out = dict(base)
    for p in prof.get("on", []):
        if p in out:
            out[p] = True
    for p in prof.get("off", []):
        if p in out:
            out[p] = False
    if CORE in out:
        out[CORE] = True
    return out, prof.get("order") or None


def delete_profile(name):
    profile_path(name).unlink(missing_ok=True)


def profile_diff(a_on, b_on, mods):
    """Mods only in B (added) and only in A (removed), as name-sorted pid lists."""
    nm = lambda p: mods[p].name.lower() if p in mods else p  # noqa
    return sorted(set(b_on) - set(a_on), key=nm), sorted(set(a_on) - set(b_on), key=nm)


def list_backups(config):
    c = Path(config)
    return sorted(c.parent.glob(c.name + ".bak-*"), reverse=True) if c.parent.exists() else []


TAGS_FILE = APP_DIR / "tags.json"


def load_tags():
    try:
        return {k: sorted(v) for k, v in json.loads(TAGS_FILE.read_text()).items() if v}
    except Exception:
        return {}


def save_tags(t):
    TAGS_FILE.write_text(json.dumps({k: v for k, v in t.items() if v}, indent=1))


def export_modlist(path, order, mods, version_str="", fmt=None):
    path = Path(path)
    fmt = fmt or ("xml" if path.suffix.lower() == ".xml" else "json")
    if fmt == "xml":  # same shape as ModsConfig.xml, which RimPy and RimSort also read
        root = ET.Element("ModsConfigData")
        ET.SubElement(root, "version").text = version_str
        am = ET.SubElement(root, "activeMods")
        for p in order:
            ET.SubElement(am, "li").text = p
        ET.indent(root)
        path.write_text('<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
    else:
        rows = [{"id": p, "name": mods[p].name if p in mods else p,
                 "workshop": mods[p].path.name if p in mods and mods[p].source == "workshop" else ""} for p in order]
        path.write_text(json.dumps({"app": "rimworld-mod-applier", "game": version_str, "mods": rows}, indent=1), encoding="utf-8")


def import_modlist(path):
    """-> ordered list of lowercase package ids, plus {pid: workshop id} where the file knows them."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8")).get("mods", [])
        return [r["id"].lower() for r in rows], {r["id"].lower(): r["workshop"] for r in rows if r.get("workshop")}
    root = ET.parse(path).getroot()
    return [(li.text or "").strip().lower() for li in root.iter("li") if (li.text or "").strip()], {}
