"""Support bundle: a short, paste-ready summary of a setup and its last crash. No UI code."""
import hashlib

from . import core
from .advisor import redact
from .diagnose import ESSENTIAL


def order_hash(order):
    """Short fingerprint of a load order, so two people can tell whether they run the same list."""
    return hashlib.sha1("\n".join(order).encode("utf-8")).hexdigest()[:8]


def build_bundle(game, target, mods, checked, order, plan, broken, A=None, updated=None, include_order=False):
    """Markdown for Discord or a forum. Paths and user names are removed. The load order is only added on request."""
    updated = updated or {}
    ticked = [p for p, v in checked.items() if v and p in mods]
    unv = [p for p in ticked if core.unverified(mods[p], target)]
    nm = lambda p: mods[p].name if p in mods else p  # noqa
    L = ["**RimWorld Mod Applier support bundle**",
         "Game %s | %d mods ticked | load order #%s | %d made for the previous version with code" % (
             game or target, len(ticked), order_hash(order), len(unv))]
    if A:
        L += ["", "**Log:** %d errors, %d warnings" % (A.n_err, A.n_warn)]
        if A.fatal:
            who = ", ".join(nm(p) for p in A.fatal["pids"] if p in mods) or "no mod identified"
            L.append("First fatal error at %s in %s: `%s`" % (A.fatal["time"], who, redact(A.fatal["headline"])[:140]))
        causes = [r for r in A.rows if r.verdict == "cause" and r.pid in mods]
        if causes:
            L.append("Likely causes:")
            for r in causes[:6]:
                tag = " (essential)" if r.pid in ESSENTIAL else " (framework)" if r.lib else ""
                L.append("- %s `%s`%s: %d errors, e.g. `%s`" % (nm(r.pid), r.pid, tag, r.count, redact(r.heads[0][0])[:100]))
        sus = [r for r in A.rows if r.verdict == "suspect" and r.pid in mods][:5]
        if sus:
            L.append("Other suspects: " + ", ".join("%s (%d)" % (nm(r.pid), r.count) for r in sus))
        if A.symptoms:
            L.append("%d 'could not regenerate layer' errors (fallout from an unbuilt map)" % A.symptoms)
    if updated:
        rows = sorted(updated.items(), key=lambda kv: nm(kv[0]).lower())
        L += ["", "**Updated recently:** " + ", ".join("%s (%s)" % (nm(p), t.replace("updated ", "")) for p, t in rows[:12])
              + (" and %d more" % (len(rows) - 12) if len(rows) > 12 else "")]
    health = []
    if broken:
        health.append("%d mods with a missing dependency" % len(broken))
    if plan is not None:
        if plan.violations:
            health.append("%d broken load-order rules" % len(plan.violations))
        if plan.dropped_rules:
            health.append("%d sorting rules left out (they would loop)" % len(plan.dropped_rules))
    conflicts = [p for p in ticked if any(x in set(ticked) for x in mods[p].incompat)]
    if conflicts:
        health.append("%d ticked mods declare an incompatible mod is also ticked" % len(conflicts))
    L += ["", "**Setup:** " + ("; ".join(health) if health else "no missing dependencies, broken rules or declared conflicts")]
    if include_order:
        L += ["", "**Load order** (package ids):", "```"] + ["%d %s" % (i, p) for i, p in enumerate(order, 1)] + ["```"]
    return "\n".join(L)
