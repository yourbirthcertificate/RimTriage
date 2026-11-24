"""Save-game mod checks and subscribe-queue helpers. No UI code.

A RimWorld .rws file starts with a <meta> block listing the game version and every mod the colony ran with:
modIds (in load order), modSteamIds and modNames as parallel lists. Only that header is read, never the colony data."""
import os
import re
from pathlib import Path
from urllib.parse import quote

from . import core
from .core import CORE

SAVE_DIR_REL = Path("AppData/LocalLow/Ludeon Studios/RimWorld by Ludeon Studios/Saves")
MAX_HEADER = 2_000_000
WORKSHOP_MIN = 10_000_000   # real Workshop ids are 9 to 10 digits; DLC app ids (for example 1149640) are smaller


def default_save_dir():
    return Path(os.environ.get("USERPROFILE", "~")) / SAVE_DIR_REL


def _li(block):
    return [re.sub(r"\s+", " ", x).strip() for x in re.findall(r"<li>(.*?)</li>", block or "", re.S)]


def _unescape(s):
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")


def read_save_meta(path):
    """-> {name, path, mtime, size, game, mods: [{id, steam, name}]} or None when the file isn't a readable save."""
    path = Path(path)
    try:
        st = path.stat()
        head = b""
        with open(path, "rb") as f:
            while len(head) < MAX_HEADER:
                chunk = f.read(65536)
                if not chunk:
                    break
                head += chunk
                if b"</meta>" in head:
                    break
    except OSError:
        return None
    text = head.decode("utf-8", errors="replace")
    end = text.find("</meta>")
    if end < 0:
        return None
    meta = text[:end]
    game = re.search(r"<gameVersion>(.*?)</gameVersion>", meta, re.S)
    ids = [x.lower() for x in _li(re.search(r"<modIds>(.*?)</modIds>", meta, re.S).group(1))] if "<modIds>" in meta else []
    steam = _li(re.search(r"<modSteamIds>(.*?)</modSteamIds>", meta, re.S).group(1)) if "<modSteamIds>" in meta else []
    names = [_unescape(x) for x in _li(re.search(r"<modNames>(.*?)</modNames>", meta, re.S).group(1))] if "<modNames>" in meta else []
    mods = []
    for i, p in enumerate(ids):
        sid = steam[i] if i < len(steam) and steam[i].isdigit() and int(steam[i]) >= WORKSHOP_MIN else ""
        mods.append({"id": p, "steam": sid, "name": names[i] if i < len(names) else p})
    return {"name": path.stem, "path": str(path), "mtime": int(st.st_mtime), "size": st.st_size,
            "game": game.group(1).strip() if game else "", "mods": mods}


def list_saves(folder=None):
    folder = Path(folder) if folder else default_save_dir()
    out = []
    for f in sorted(folder.glob("*.rws"), key=lambda p: -p.stat().st_mtime) if folder.exists() else []:
        m = read_save_meta(f)
        if m:
            out.append(m)
    return out


def _major_minor(v):
    m = re.match(r"(\d+)\.(\d+)", v or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def compare_save(meta, mods, checked, target, broken):
    """How the current mod list stacks up against what a save was made with.
    -> dict(ok, off, missing, outdated, extra, order, game_note) with lists of save-mod dicts (extra = pids)."""
    ok, off, missing, outdated = [], [], [], []
    ids = {m["id"] for m in meta["mods"]}
    for m in meta["mods"]:
        p = m["id"]
        if p not in mods:
            missing.append(m)
        elif not checked.get(p) and p != CORE:
            off.append(m)
        elif p in broken or not core.version_ok(mods[p], target):
            outdated.append(m)
        else:
            ok.append(m)
    extra = [p for p, v in checked.items() if v and p in mods and p not in ids]
    sv, tv = _major_minor(meta["game"]), _major_minor(target)
    note = ""
    if sv and tv and sv != tv:
        note = "Saved on %s, and the game is %s." % (meta["game"].split(" ")[0], target) + (
            " Loading an older save on a newer version usually works, but older mods may not." if sv < tv else " This save is newer than the game.")
    return {"ok": ok, "off": off, "missing": missing, "outdated": outdated, "extra": extra, "game_note": note}


def match_order(meta, mods):
    """The save's own load order, limited to what is installed."""
    return [m["id"] for m in meta["mods"] if m["id"] in mods]


def verdict(cmp):
    """Chip for the saves list: (kind, text)."""
    if cmp["missing"]:
        return "missing", "Missing %d" % len(cmp["missing"])
    if cmp["off"]:
        return "enable", "%d not ticked" % len(cmp["off"])
    if cmp["outdated"]:
        return "outdated", "%d may not load" % len(cmp["outdated"])
    if cmp["extra"]:
        return "skipped", "+%d extra" % len(cmp["extra"])
    return "on", "Matches"


# ----------------------------------------------------- subscribe queue items
def workshop_id(url):
    """Workshop id out of a steam:// or steamcommunity link, else ''."""
    m = re.search(r"(?:CommunityFilePage/|[?&]id=)(\d{6,})", url or "")
    return m.group(1) if m else ""


def item_url(item):
    """Where to send the user for one queue item: its Workshop page, its download link, or a Workshop search."""
    if item.get("id"):
        return "steam://url/CommunityFilePage/" + item["id"]
    if item.get("url") and item["url"].startswith(("http://", "https://", "steam://")):
        return item["url"]
    return "https://steamcommunity.com/workshop/browse/?appid=%s&searchtext=%s&browsesort=textsearch" % (core.APPID, quote(item["name"]))


def missing_dep_items(mods):
    """Dependencies nobody installed, as queue items: {name, id, url, why}. Most needed first."""
    rep = {}
    for m in mods.values():
        for d in m.deps:
            if not any(x in mods for x in d.ids):
                r = rep.setdefault(d.ids[0], {"name": d.display, "id": "", "url": "", "who": []})
                r["who"].append(m.name)
                r["id"] = r["id"] or workshop_id(d.url)
                r["url"] = r["url"] or d.url
    out = [{"name": r["name"], "id": r["id"], "url": r["url"],
            "why": "needed by %d mod%s" % (len(r["who"]), "" if len(r["who"]) == 1 else "s")} for r in rep.values()]
    return sorted(out, key=lambda r: (-int(r["why"].split()[2]), r["name"].lower()))


def missing_save_items(meta, cmp, save_label=None):
    """Mods a save needs that aren't installed, as queue items."""
    label = save_label or meta["name"]
    return [{"name": m["name"], "id": m["steam"], "url": "", "why": "in %s" % label}
            for m in cmp["missing"] if not m["id"].startswith("ludeon.")]
