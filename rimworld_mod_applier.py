#!/usr/bin/env python3
"""RimWorld Mod Applier.

GUI:       python rimworld_mod_applier.py
Headless:  python rimworld_mod_applier.py --auto [--profile NAME] [--mode strict|balanced|grouped] [--dry-run]
Overrides: --game DIR --workshop DIR --config FILE
"""
import argparse
import sys

from modapplier import core


def run_cli(a, s):
    target = ".".join(core.game_version_str(s["game_dir"]).split(".")[:2])
    mods, dups, bad = core.scan(s["game_dir"], s["workshop_dir"], target)
    broken = core.broken_set(mods)
    checked = core.auto_checked(mods, target, broken)
    manual = None
    if a.profile:
        checked, manual = core.apply_profile(a.profile, checked)
    if a.update_rules:
        print("Downloaded community rules for %d mods" % core.download_community())
    community = {} if a.no_community else core.load_community()
    plan = core.make_plan(mods, checked, broken, True, community, core.load_user_rules(), a.mode, manual)
    print("Game %s | %d mods | %d enabled | %d missing-dep | %d outdated | %d community rules | mode %s" % (
        target, len(mods), len(plan.order), len(broken), sum(not core.version_ok(m, target) for m in mods.values()),
        len(community), a.mode))
    for w in plan.warnings[:20]:
        print("  !", w)
    for v in plan.violations[:10]:
        print("  x", core.violation_text(v, mods))
    for i, (p, t) in enumerate(plan.order[:a.show], 1):
        print("  %3d %-8s %s  <- %s" % (i, core.TIER_NAMES[t], mods[p].name, "; ".join(plan.why.get(p, [])[:3])))
    if a.dry_run:
        print("Dry run: nothing written.")
        return
    print("Backup:", core.backup_config(s["config_path"]))
    core.write_config(s["config_path"], [p for p, _ in plan.order], core.game_version_str(s["game_dir"]))
    print("Wrote", s["config_path"])


def main():
    ap = argparse.ArgumentParser(description="RimWorld Mod Applier")
    ap.add_argument("--auto", action="store_true", help="headless: auto-select, sort and write")
    ap.add_argument("--profile")
    ap.add_argument("--mode", default="balanced", choices=list(core.MODES))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-community", action="store_true", help="ignore the community rules database")
    ap.add_argument("--update-rules", action="store_true", help="download the latest community rules first")
    ap.add_argument("--show", type=int, default=25, help="how many load-order lines to print")
    ap.add_argument("--game")
    ap.add_argument("--workshop")
    ap.add_argument("--config")
    a = ap.parse_args()
    s = core.load_settings()
    for k, v in (("game_dir", a.game), ("workshop_dir", a.workshop), ("config_path", a.config)):
        if v:
            s[k] = v
    if a.auto:
        run_cli(a, s)
    else:
        from modapplier.ui import run_gui
        sys.exit(run_gui(s))


if __name__ == "__main__":
    main()
