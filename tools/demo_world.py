"""A fictional RimWorld install for screenshots and demos: made-up mods, a made-up crash log and made-up saves.
Nothing here comes from a real machine or a real colony."""
import random
import re
import time
from pathlib import Path

ADJ = ["Clover", "Mossy", "Ember", "Tidal", "Hollow", "Brass", "Lantern", "Willow", "Copper", "Drift", "Amber", "Fern",
       "Granite", "Harbor", "Juniper", "Kestrel", "Marble", "Nettle", "Orchard", "Pebble", "Quartz", "Russet"]
NOUN = ["Farming", "Cooking", "Armory", "Medicine", "Hauling", "Textures", "Animals", "Weather", "Traders", "Raids",
        "Furniture", "Lighting", "Research", "Prisoners", "Colonists", "Biomes", "Mining", "Crafting", "Storage", "Walls"]
OFFICIAL = (("Core", "Ludeon.RimWorld", "Core"), ("Royalty", "Ludeon.RimWorld.Royalty", "Royalty"),
            ("Ideology", "Ludeon.RimWorld.Ideology", "Ideology"), ("Biotech", "Ludeon.RimWorld.Biotech", "Biotech"),
            ("Anomaly", "Ludeon.RimWorld.Anomaly", "Anomaly"), ("Odyssey", "Ludeon.RimWorld.Odyssey", "Odyssey"))
ABOUT = """<?xml version="1.0" encoding="utf-8"?>
<ModMetaData><name>{name}</name><author>{author}</author><packageId>{pid}</packageId>
<supportedVersions>{versions}</supportedVersions>
<modDependencies>{deps}</modDependencies><loadAfter>{after}</loadAfter><incompatibleWith>{incompat}</incompatibleWith>
<description>{desc}</description></ModMetaData>"""
STAMP = "%Y-%m-%d %H:%M:%S"


def _key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def build(root, seed=7):
    """Create the demo install under `root`. Returns paths, the ids that matter and the crash culprit."""
    rnd = random.Random(seed)
    root = Path(root)
    home = root / "home"
    base = home / "AppData" / "LocalLow" / "Ludeon Studios" / "RimWorld by Ludeon Studios"
    game = root / "steam" / "steamapps" / "common" / "RimWorld"
    ws = root / "steam" / "steamapps" / "workshop" / "content" / "294100"
    acf = root / "steam" / "steamapps" / "workshop" / "appworkshop_294100.acf"
    for d in (base / "Logs", base / "Saves", base / "Config", game / "Mods", ws):
        d.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for folder, pid, name in OFFICIAL:
        (game / "Data" / folder / "About").mkdir(parents=True)
        (game / "Data" / folder / "About" / "About.xml").write_text(ABOUT.format(
            name=name, author="Ludeon Studios", pid=pid, versions="<li>1.7</li>", deps="", after="", incompat="", desc=""))
    (game / "Version.txt").write_text("1.7.5014 rev1195")
    (base / "Config" / "ModsConfig.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<ModsConfigData>\n  <version>1.7.5014 rev1195</version>\n  <activeMods>\n'
        "    <li>ludeon.rimworld</li>\n  </activeMods>\n</ModsConfigData>\n")

    mods, state = [], {"wid": 3300000000}

    def add(name, key=None, versions=("1.6", "1.7"), deps=(), after=(), incompat=(), dll=None, days=None, desc="", author=None, dep_names=None):
        state["wid"] += rnd.randint(1000, 90000)
        pid = "brrainz.harmony" if key == "harmony" else "demo.%s" % (key or _key(name))
        folder = ws / str(state["wid"])
        (folder / "About").mkdir(parents=True)
        dep_xml = "".join("<li><packageId>%s</packageId><displayName>%s</displayName>%s</li>" % (
            d, (dep_names or {}).get(d, d), "<steamWorkshopUrl>steam://url/CommunityFilePage/3300999999</steamWorkshopUrl>" if d == "ghost.library" else "")
            for d in deps)
        li = lambda xs: "".join("<li>%s</li>" % x for x in xs)  # noqa
        (folder / "About" / "About.xml").write_text(ABOUT.format(
            name=name, author=author or rnd.choice(["Fieldsmith", "Mossbeard", "Pebblewright", "Tallow", "Quillmaker"]), pid=pid,
            versions=li(versions), deps=dep_xml, after=li(after), incompat=li(incompat), desc=desc or "A fictional mod for the RimTriage demo."))
        if dll:
            (folder / "Assemblies").mkdir()
            (folder / "Assemblies" / (dll + ".dll")).write_bytes(b"demo")
        days = rnd.randint(8, 380) if days is None else days
        mods.append({"pid": pid, "name": name, "wid": state["wid"], "days": days, "versions": versions, "dll": dll})
        return pid

    harmony = add("Harmony", key="harmony", dll="0Harmony", days=30, author="Library Guild")
    hearth = add("Hearth Framework", deps=[harmony], dll="HearthFramework", days=21, author="Library Guild", dep_names={harmony: "Harmony"})
    quill = add("Quill Library", deps=[harmony], dll="QuillLibrary", days=44, author="Library Guild", dep_names={harmony: "Harmony"})
    clover = add("Clover Farming", deps=[hearth], dll="CloverFarming", days=9, dep_names={hearth: "Hearth Framework"})
    mossy = add("Mossy Cooking", deps=[hearth], days=12, dep_names={hearth: "Hearth Framework"})
    add("Clover Farming + Mossy Cooking Compat Patch", deps=[clover, mossy], days=2, dep_names={clover: "Clover Farming", mossy: "Mossy Cooking"})
    culprit = add("Eyedropper Tool", key="eyedropper", versions=("1.6",), deps=[harmony], dll="EyedropperTool", days=1,
                  dep_names={harmony: "Harmony"}, desc="Pick a texture from the map. Made for 1.6.")
    add("Orchard Extras", deps=["ghost.library"], days=40, dep_names={"ghost.library": "Ghost Library"})
    add("Ironclad Raids", incompat=["demo.peacefulraids"], days=60)
    add("Peaceful Raids", days=75)
    add("Sunbeam Lights", after=["demo.moonbeamlights"], days=90)
    add("Moonbeam Lights", after=["demo.sunbeamlights"], days=95)
    combos = [(a, n) for a in ADJ for n in NOUN]
    rnd.shuffle(combos)
    existing = {m["name"] for m in mods}
    content = []
    for a, n in combos:
        name = "%s %s" % (a, n)
        if name in existing or len(content) >= 110:
            continue
        r = rnd.random()
        versions = ("1.6", "1.7") if r < 0.62 else ("1.6",) if r < 0.82 else ("1.5", "1.6") if r < 0.91 else ("1.4",)
        pool = [hearth] * 4 + [quill] * 3 + [None] * 3 + ([rnd.choice(content)] if content else [None])
        dep = rnd.choice(pool)
        deps = [dep] if dep else []
        has_code = rnd.random() < 0.42
        pid = add(name, versions=versions, deps=deps, dll=("Demo" + _key(name)) if has_code else None,
                  dep_names={d: next((m["name"] for m in mods if m["pid"] == d), d) for d in deps})
        content.append(pid)
        existing.add(name)
    # a handful updated in the last few days, so the update tracker has something to show
    for m in rnd.sample([m for m in mods if m["pid"] != culprit], 11):
        m["days"] = rnd.choice([0, 1, 2, 3])

    items = "".join('\t\t"%d"\n\t\t{\n\t\t\t"size"\t\t"1000"\n\t\t\t"timeupdated"\t\t"%d"\n\t\t\t"manifest"\t\t"1"\n\t\t}\n' % (
        m["wid"], int(now - m["days"] * 86400 - rnd.randint(0, 40000))) for m in mods)
    acf.write_text('"AppWorkshop"\n{\n\t"appid"\t\t"294100"\n\t"WorkshopItemsInstalled"\n\t{\n%s\t}\n}\n' % items)

    # a crash log: the culprit fails to start, then breaks map creation; the colony map is never built
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    L = []
    t = lambda s, lvl, msg: L.append("%s 12:%02d:%02d.%03d %s [Verse] %s" % (day, s // 60, s % 60, (s * 37) % 1000, lvl.ljust(5), msg))  # noqa
    t(1, "INFO", "RimWorld 1.7.5014 rev1195 starting")
    t(40, "ERROR", "Error while instantiating a mod of type EyedropperTool.EyedropperMod: System.Reflection.TargetInvocationException: Exception has been thrown by the target of an invocation.")
    L += [" ---> System.TypeLoadException: Could not load type 'HarmonyLib.HarmonyInfix' from assembly '0Harmony, Version=2.4.2.0'.",
          "   at HarmonyLib.PatchTools.GetPatchMethod(Type patchType, String attributeName) in 0Harmony:token 0x60001c0+0x24",
          "   at EyedropperTool.EyedropperMod..ctor(ModContentPack content) in EyedropperTool.dll:token 0x6000019+0x11"]
    for i in range(3):
        t(55 + i, "ERROR", "Exception while updating the Hearth Framework cache: System.NullReferenceException: Object reference not set to an instance of an object.")
        L += ["   at HearthFramework.Cache.Refresh() in HearthFramework.dll:token 0x6000011+0x0", "   at Verse.Game.UpdatePlay() in Assembly-CSharp.dll:token 0x60001+0x2"]
    for i in range(14):
        t(70 + i, "ERROR", "[Clover Farming + Mossy Cooking Compat Patch] Patch operation Verse.PatchOperationReplace(/Defs/ThingDef[defName=\"Pot%d\"]/label) failed" % i)
    t(300, "ERROR", "Exception from asynchronous event: System.NullReferenceException: Object reference not set to an instance of an object.")
    L += ["   at EyedropperTool.ExtraGui.Manager.NotifyDeselected() in EyedropperTool.dll:token 0x6000059+0x0",
          "   at Verse.Game.set_CurrentMap(Map value) in Assembly-CSharp.dll:token 0x6000a1+0x0",
          "   at Verse.Game.InitNewGame() in Assembly-CSharp.dll:token 0x6000a2+0x0"]
    t(301, "ERROR", "Exception was thrown while trying to handle exception. Exception: System.NullReferenceException: x")
    L += ["   at Verse.MapDrawer.Dispose() in Assembly-CSharp.dll:token 0x60014dc+0x8"]
    for i in range(120):
        t(302 + i // 8, "ERROR", "Could not regenerate layer Verse.SectionLayer_%s: System.NullReferenceException: Object reference not set to an instance of an object." % ("FogOfWar", "Sand", "Snow")[i % 3])
        L += ["   at Verse.Section.RegenerateAllLayers() in Assembly-CSharp.dll:token 0x60014f7+0x2a"]
    for i in range(9):
        t(310 + i, "WARN", "Config error in Clover Farming: unused key %d" % i)
    (base / "Logs" / "Player.log").write_text("\n".join(L) + "\n", encoding="utf-8")

    # saves: one that needs mods you don't have, one that matches, one with unticked mods
    def save(name, pids, game_v, extra_missing=()):
        ids = list(pids) + [e[0] for e in extra_missing]
        steam = {m["pid"]: str(m["wid"]) for m in mods}
        names = {m["pid"]: m["name"] for m in mods}
        (base / "Saves" / (name + ".rws")).write_text(
            '<?xml version="1.0" encoding="utf-8"?><savegame><meta><gameVersion>%s</gameVersion><modIds>%s</modIds><modSteamIds>%s</modSteamIds>'
            "<modNames>%s</modNames></meta><game>demo colony data</game></savegame>" % (
                game_v, "".join("<li>%s</li>" % p for p in ["ludeon.rimworld"] + ids),
                "".join("<li>%s</li>" % (steam.get(p, "0")) for p in ["ludeon.rimworld"] + list(pids)) + "".join("<li>%s</li>" % e[2] for e in extra_missing),
                "".join("<li>%s</li>" % n for n in ["Core"] + [names.get(p, p) for p in pids] + [e[1] for e in extra_missing])))
        import os
        stamp = now - {"Hollowmere": 40 * 86400, "Mossgrave": 3600, "Autosave-1": 1800}.get(name, 0)
        os.utime(base / "Saves" / (name + ".rws"), (stamp, stamp))
    healthy = [m["pid"] for m in mods if m["pid"] != culprit and m["versions"] != ("1.4",) and "ghost" not in m["pid"] and m["pid"] != "demo.orchardextras"]
    save("Mossgrave", healthy, "1.7.5014 rev1195")
    save("Autosave-1", healthy[:-6] + [culprit], "1.7.5014 rev1195")
    save("Hollowmere", healthy[:70], "1.6.4630 rev897",
         [("gone.mod.a", "Lantern Wells", "3101111111"), ("gone.mod.b", "Willow Beds", "3102222222"), ("gone.mod.c", "Drift Signs", "0")])
    return {"home": home, "game": game, "workshop": ws, "config": base / "Config" / "ModsConfig.xml", "culprit": culprit,
            "clover": clover, "mossy": mossy, "patch_name": "Clover Farming + Mossy Cooking Compat Patch", "hearth": hearth, "mods": mods,
            "save": save}
