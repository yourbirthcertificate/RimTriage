<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.png">
    <img alt="RimTriage: Sort, diagnose, and recover your RimWorld mod lists." src="assets/logo-light.png" width="640">
  </picture>
</p>

RimTriage is a Windows desktop tool for people running very large RimWorld mod lists (it was built against 900+ mods on the 1.7 pre-release). It sorts the load order from the rules, and when the game stops loading it helps you find out why and get back to a list that works.

> The app window and exe are still called "RimWorld Mod Applier" internally. The repo is RimTriage.

## Screenshots

All screenshots use a fictional demo install (made-up mods, log and saves), not a real colony.

**Sort the list.** Tick what is compatible, see what is out of date, unverified or missing, and spot what updated recently.

![The Mods page](docs/screenshots/mods.png)

**Know why every mod sits where it does.** Each row shows the rule behind its position.

![The Load order page](docs/screenshots/load-order.png)

**Find the cause.** The log reader traces the first fatal error back to a mod and ranks the rest.

![The log reader](docs/screenshots/log-reader.png)

**See what changed since it last worked.** Updates, new mods and moves since a baseline you marked as working.

![What changed](docs/screenshots/what-changed.png)

| Dependency finder | Crash finder |
| --- | --- |
| ![Dependency finder](docs/screenshots/dependencies.png) | ![Crash finder](docs/screenshots/crash-finder.png) |

| Saves | Apply preview |
| --- | --- |
| ![Saves page](docs/screenshots/saves.png) | ![Apply preview](docs/screenshots/apply-preview.png) |

There is also a light theme:

![Light theme](docs/screenshots/mods-light.png)

## What it does

**Sort**
- Scans your Steam Workshop and local mod folders and reads each mod's `About.xml` and `LoadFolders.xml`.
- Ticks everything compatible by default. Mods made for the previous game version are accepted, and ones that also ship code are flagged "unverified" because they are the likeliest to crash on a pre-release build.
- Sorts with a dependency-aware load order. Rule strength: dependencies, then your own rules, then each mod's own rules, then the [RimSort community rules](https://github.com/RimSort/Community-Rules-Database). A weaker rule that would make a loop is dropped, and every dropped rule is listed with the chain that blocked it.
- Three modes (Strict, Balanced, Grouped), drag-and-drop editing, a rule checker, "fix with the fewest moves", "place this mod correctly", and a gentle sort that keeps the order already in your `ModsConfig.xml`.
- Dependency finder (tree and small graph), tags, profiles, profile compare, undo and redo, import and export.

**Diagnose**
- **Log reader:** traces errors in `Player.log` back to the mod that caused them, using the DLLs named in stack traces. Shared frameworks are down-weighted because they are often just the victim.
- **What changed:** reads Steam's update times and compares your setup with a baseline you marked as working.
- **Live log:** follows `Player.log` while the game starts and tells you when a mod fails.
- **Compatibility scan:** declared conflicts, missing dependencies, near-duplicate mods, patches you left off, and an optional def-overlap check.
- **Crash finder:** halves your load order in rounds to find the mod that breaks the game, confirms the result, and can look for a second mod when two only fail together.
- **Advisor:** plain-language advice from the rules. Optionally, a small local model through [Ollama](https://ollama.com) rewords the explanation. It cannot change what is recommended.
- **Support bundle:** one click copies a short, paste-ready summary (paths and user names removed).

**Recover**
- Every write to `ModsConfig.xml` is shown as a diff first, backed up, written atomically, and refused while RimWorld runs.
- The Saves page reads only each save's header and shows what a colony needs, with one click to match its mod list and load order. Saves can be protected so Apply warns before removing a mod they need.
- A queue walks you through subscribing to missing mods.

## Run it

Needs Windows and Python 3.10 or newer.

```powershell
pip install -r requirements.txt
python rimworld_mod_applier.py
```

Headless sort (writes `ModsConfig.xml` after a backup; add `--dry-run` to only preview):

```powershell
python rimworld_mod_applier.py --auto --dry-run --mode balanced
```

Steam, the game folder and the config path are found automatically. You can change them in Settings.

## Build the exe

```powershell
pip install pyinstaller
python make_icon.py
python -m PyInstaller --noconfirm --onefile --windowed --name RimWorldModApplier --icon assets\RimWorldModApplier.ico --paths . rimworld_mod_applier.py
```

Your settings, profiles and history are stored next to the exe.

## Tests

```powershell
python tests\test_core.py
```

The tests build a small synthetic mod library, save and log, so they need no RimWorld install.

## Pictures

The logo, the GitHub social preview and every screenshot are generated from the demo install in `tools/demo_world.py`:

```powershell
python tools\make_images.py
```

A window flashes on screen while it runs. Nothing from a real machine is used.

## What it touches

- It writes `ModsConfig.xml` (after a backup) and its own files next to the app. It never edits or deletes mods.
- Nothing is uploaded. The community rules are downloaded only when you press Update, and the optional model is only ever contacted on `localhost`.
- Steam pages open only when you ask.

## Limits

- Windows only.
- Built and tested on one machine and one very large mod list. Treat the rules as a good first draft, not a verdict.
- The crash finder assumes the problem stays once the culprit is loaded. Crashes that depend on several mods at once can be reported as "interaction suspected" instead of a single name.
- RimWorld's log has no clear "loaded successfully" line, so the app suggests marking a clean session as working and leaves the decision to you.

## License

MIT. See [LICENSE](LICENSE).

## Credits

- Load-order rules come from the RimSort Community-Rules-Database. They are downloaded on request and not included here.
- UI by [Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/).
- The icon is original artwork.
- Not affiliated with or endorsed by Ludeon Studios. RimWorld is a trademark of Ludeon Studios.
