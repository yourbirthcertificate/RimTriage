"""Portable tests. They build a tiny synthetic mod library, save and log in a temp folder, so they need no RimWorld install.

Run with:  python -m pytest tests      or      python tests/test_core.py"""
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modapplier import advisor, core, diagnose, saves, support, tracker  # noqa: E402

ABOUT = """<?xml version="1.0" encoding="utf-8"?>
<ModMetaData><name>{name}</name><author>tester</author><packageId>{pid}</packageId>
<supportedVersions>{versions}</supportedVersions>
<modDependencies>{deps}</modDependencies><loadAfter>{after}</loadAfter><incompatibleWith>{incompat}</incompatibleWith>
</ModMetaData>"""


def mk(root, folder, pid, name, versions=("1.6", "1.7"), deps=(), after=(), incompat=(), dll=None):
    d = root / folder
    (d / "About").mkdir(parents=True)
    li = lambda xs: "".join("<li>%s</li>" % x for x in xs)  # noqa
    dep = "".join("<li><packageId>%s</packageId><displayName>%s</displayName></li>" % (x, x) for x in deps)
    (d / "About" / "About.xml").write_text(ABOUT.format(name=name, pid=pid, versions=li(versions), deps=dep, after=li(after), incompat=li(incompat)))
    if dll:
        (d / "Assemblies").mkdir()
        (d / "Assemblies" / (dll + ".dll")).write_bytes(b"x")


def library():
    root = Path(tempfile.mkdtemp()) / "workshop"
    root.mkdir()
    mk(root, "1", "brrainz.harmony", "Harmony", dll="0Harmony")
    mk(root, "2", "lib.framework", "Cool Framework", deps=["brrainz.harmony"])
    mk(root, "3", "mod.a", "Mod A", deps=["lib.framework"])
    mk(root, "4", "mod.b", "Mod B", after=["mod.a"])
    mk(root, "5", "mod.patch", "A and B Patch", deps=["mod.a", "mod.b"])
    mk(root, "6", "mod.old", "Old Mod", versions=("1.4",))
    mk(root, "7", "mod.code", "Code Mod", versions=("1.6",), dll="CodeMod")
    mk(root, "8", "mod.orphan", "Orphan", deps=["ghost.mod"])
    mk(root, "9", "mod.x", "Conflict X", incompat=["mod.y"])
    mk(root, "10", "mod.y", "Conflict Y")
    mk(root, "11", "cyc.p", "Cycle P", after=["cyc.q"])
    mk(root, "12", "cyc.q", "Cycle Q", after=["cyc.p"])
    return core.scan(None, str(root), "1.7")


def test_running_game_guard_recognizes_both_windows_executables():
    for exe in ("RimWorldWin64.exe", "RIMWORLD.EXE"):
        output = '"explorer.exe","20","Console","1","1,000 K"\r\n' + (
            '"%s","42","Console","1","20,000 K"\r\n' % exe)
        with patch.object(core.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, stdout=output)) as tasklist:
            assert core.game_running()
            assert tasklist.call_args.args[0] == ["tasklist", "/FO", "CSV", "/NH"]
            assert tasklist.call_args.kwargs["check"]


def test_running_game_guard_matches_image_name_not_substrings():
    output = '"RimWorld.exe.backup","42","Console","1","20,000 K"\r\n'
    with patch.object(core.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, stdout=output)):
        assert not core.game_running()


def test_running_game_guard_blocks_when_process_status_is_unknown():
    for error in (FileNotFoundError(), subprocess.CalledProcessError(1, "tasklist"),
                  subprocess.TimeoutExpired("tasklist", 3)):
        with patch.object(core.subprocess, "run", side_effect=error):
            assert core.game_running()
    for output in ("", "unexpected tasklist output", '"unclosed quote'):
        with patch.object(core.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, stdout=output)):
            assert core.game_running()


def test_command_line_writer_refuses_while_the_game_runs():
    import argparse
    import rimworld_mod_applier as cli
    root = Path(tempfile.mkdtemp()) / "workshop"
    root.mkdir()
    mk(root, "1", "brrainz.harmony", "Harmony", dll="0Harmony")
    mk(root, "2", "mod.a", "Mod A", deps=["brrainz.harmony"])
    cfg = Path(tempfile.mkdtemp()) / "ModsConfig.xml"
    core.write_config(cfg, ["old.mod"], "1.7")
    before = cfg.read_text()
    s = {"game_dir": "", "workshop_dir": str(root), "config_path": str(cfg)}

    def args(dry):
        return argparse.Namespace(profile=None, update_rules=False, no_community=True, mode="balanced", show=0, dry_run=dry)
    with patch.object(core, "game_running", return_value=True):
        try:
            cli.run_cli(args(False), s)
            raise AssertionError("the command line wrote while the game was running")
        except SystemExit as e:
            assert e.code == 1
        assert cfg.read_text() == before and not core.list_backups(cfg)       # nothing written, nothing backed up
        cli.run_cli(args(True), s)                                            # --dry-run still works
        assert cfg.read_text() == before
    with patch.object(core, "game_running", return_value=False):
        cli.run_cli(args(False), s)
    assert core.read_active(cfg) == ["brrainz.harmony", "mod.a"] and len(core.list_backups(cfg)) == 1


def test_scan_and_parse():
    mods, dups, bad = library()
    assert len(mods) == 12 and not dups and not bad
    assert mods["mod.a"].deps[0].ids == ("lib.framework",)
    assert "mod.a" in mods["mod.b"].after
    assert mods["mod.code"].dlls == ["codemod"]


def test_dependencies_and_auto_select():
    mods, _, _ = library()
    broken = core.broken_set(mods)
    assert "mod.orphan" in broken and "mod.a" not in broken
    ck = core.auto_checked(mods, "1.7", broken)
    assert not ck["mod.old"] and not ck["mod.orphan"] and ck["mod.code"] and ck["mod.a"]
    assert not core.auto_checked(mods, "1.7", broken, safe=True)["mod.code"]   # previous version + code
    assert core.unverified(mods["mod.code"], "1.7") and not core.unverified(mods["mod.a"], "1.7")


def test_sort_respects_rules():
    mods, _, _ = library()
    ids = {p for p in mods if p not in ("mod.old", "mod.orphan")}
    S = core.sort_order(ids, mods)
    pos = {p: i for i, p in enumerate(S.order)}
    assert pos["brrainz.harmony"] < pos["lib.framework"] < pos["mod.a"] < pos["mod.b"] < pos["mod.patch"]
    assert not core.validate_order(S.order, S)
    bad = list(S.order)
    bad.append(bad.pop(bad.index("brrainz.harmony")))      # harmony to the end
    assert core.validate_order(bad, S)
    fixed = core.sort_order(ids, mods, base={p: i for i, p in enumerate(bad)}, reverse=True)
    assert not core.validate_order(fixed.order, fixed) and len(core.moved_mods(bad, fixed.order)) <= 2


def test_cycles_are_reported_not_silent():
    mods, _, _ = library()
    S = core.sort_order({"cyc.p", "cyc.q"}, mods)
    assert S.dropped and "loop" in core.dropped_rule_text(S.dropped[0], mods)
    assert set(S.order) == {"cyc.p", "cyc.q"}


def test_config_write_diff_and_backup():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "ModsConfig.xml"
    core.write_config(cfg, ["a", "b", "c"], "1.7")
    assert core.read_active(cfg) == ["a", "b", "c"]
    bak = core.backup_config(cfg)
    core.write_config(cfg, ["a", "c", "d"], "1.7")
    assert bak.exists() and core.read_active(bak) == ["a", "b", "c"]
    mods, _, _ = library()
    diff = core.config_diff(["mod.a", "mod.b", "gone"], ["mod.b", "mod.a", "mod.x"], mods)
    assert diff["added"] == ["mod.x"] and diff["missing"] == ["gone"] and len(diff["moved"]) == 1
    h1 = core.file_hash(cfg)
    cfg.write_text(cfg.read_text() + " ")
    assert core.file_hash(cfg) != h1


def test_bisect_finds_culprit_and_partner():
    order = ["m%d" % i for i in range(200)]
    b = diagnose.Bisect(order, 5)
    while (n := b.next_size()) is not None:
        b.answer(n, "m150" in b.test_list(n))
    assert b.culprit() == "m150" and b.rounds <= 8
    p = diagnose.Bisect(order[:150], 5, extra={"m150"}, full=order)    # breaks only when m40 and m150 are both loaded
    while (n := p.next_size()) is not None:
        p.answer(n, {"m40", "m150"} <= set(p.test_list(n)))
    assert p.culprit() == "m40"


def test_save_header_and_comparison():
    mods, _, _ = library()
    f = Path(tempfile.mkdtemp()) / "Colony.rws"
    f.write_text('<?xml version="1.0"?><savegame><meta><gameVersion>1.5.4297 rev1</gameVersion>'
                 "<modIds><li>mod.a</li><li>missing.one</li><li>mod.b</li></modIds>"
                 "<modSteamIds><li>0</li><li>2538411704</li><li>0</li></modSteamIds>"
                 "<modNames><li>Mod A</li><li>Missing &amp; One</li><li>Mod B</li></modNames></meta><game>HUGE</game></savegame>")
    meta = saves.read_save_meta(f)
    assert [m["id"] for m in meta["mods"]] == ["mod.a", "missing.one", "mod.b"] and meta["mods"][1]["steam"] == "2538411704"
    assert meta["mods"][1]["name"] == "Missing & One"
    c = saves.compare_save(meta, mods, {"mod.a": True, "mod.b": False}, "1.7", {})
    assert [m["id"] for m in c["missing"]] == ["missing.one"] and [m["id"] for m in c["off"]] == ["mod.b"] and "older" in c["game_note"]
    assert saves.item_url(saves.missing_save_items(meta, c)[0]).endswith("2538411704")


def test_steam_manifest_and_snapshots():
    assert tracker.parse_vdf('"A" { "k" "v" "B" { "x" "1" } }') == {"A": {"k": "v", "B": {"x": "1"}}}
    mods, _, _ = library()
    upd = {p: 1000 for p in mods}
    snap = tracker.make_snapshot(["mod.a", "mod.b"], mods, upd, "1.7", "good")
    snap["time"] = 2000
    upd2 = dict(upd, **{"mod.a": 3000})
    ch = tracker.compare(snap, ["mod.a", "mod.b", "mod.x"], upd2, mods)
    assert [(c["pid"], c["kind"]) for c in ch][:2] == [("mod.a", "updated"), ("mod.x", "new")] or ch[0]["kind"] == "updated"


def test_log_reader_names_the_mod():
    diagnose.RULES_FILE = Path(tempfile.mkdtemp()) / "none.json"
    root = Path(tempfile.mkdtemp()) / "workshop"
    root.mkdir()
    mk(root, "1", "fake.mod", "Fake Mod", dll="FakeMod")
    mk(root, "2", "other.mod", "Other Mod", dll="OtherMod")
    mods, _, _ = core.scan(None, str(root), "1.7")
    log = Path(tempfile.mkdtemp()) / "Player.log"
    log.write_text(
        "2026-11-24 12:00:00.000 ERROR [Verse] Error while instantiating a mod of type FakeMod.Main: System.Exception: boom\n"
        "   at FakeMod.Main..ctor(ModContentPack content) in FakeMod.dll:token 0x1+0x0\n"
        "2026-11-24 12:00:01.000 ERROR [Verse] Exception from asynchronous event: System.NullReferenceException: x\n"
        "   at FakeMod.Thing.Do() in FakeMod.dll:token 0x2+0x0\n"
        "   at Verse.Game.InitNewGame() in Assembly-CSharp.dll:token 0x3\n"
        "2026-11-24 12:00:02.000 ERROR [Verse] Could not regenerate layer Verse.SectionLayer_Sand: x\n"
        "2026-11-24 12:00:03.000 ERROR [Verse] [Other Mod] Patch operation Verse.PatchOperationAdd(/Defs) failed\n")
    idx = diagnose.build_assembly_index(mods)
    A = diagnose.analyze_log(log, mods, idx)
    causes = [r.pid for r in A.rows if r.verdict == "cause"]
    assert causes == ["fake.mod"] and A.fatal["pids"] == ["fake.mod"] and A.symptoms == 1
    assert [r.verdict for r in A.rows if r.pid == "other.mod"] == ["noise"]
    # the live tail sees the same thing, even when the file arrives in pieces
    live = Path(tempfile.mkdtemp()) / "Player.log"
    tail = diagnose.LogTail(live, mods, idx)
    data = log.read_bytes()
    live.write_bytes(data[:90])
    tail.poll()
    live.write_bytes(data)
    tail.poll(); tail.poll(); tail.poll()
    assert tail.n_fatal == 2 and any(e.pids == ["fake.mod"] for e in tail.events if e.fatal)
    plan = core.make_plan(mods, {"fake.mod": True, "other.mod": True}, {}, True)
    text = support.build_bundle("1.7", "1.7", mods, {"fake.mod": True}, ["fake.mod"], plan, {}, A)
    assert "Fake Mod" in text and "support bundle" in text


def test_privacy_helpers():
    assert "Users" not in advisor.redact(r"failed at C:\Users\someone\AppData\x.dll for me@example.com") and "@" not in advisor.redact("me@example.com")
    for bad in ("http://example.com:11434", "http://192.168.1.5:11434"):
        try:
            advisor.local_url(bad)
        except ValueError:
            continue
        raise AssertionError("remote model host was accepted: " + bad)
    assert advisor.local_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa
                failed += 1
                print("FAIL", name, "->", repr(e))
    sys.exit(1 if failed else 0)
