"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    # 1. Any metric value in pr["metrics"] that is NaN or inf
    for k, v in pr.get("metrics", {}).items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            problems.append(f"metric {k} is NaN or inf")

    # 2. Row count matches manifest items x seeds
    items_cnt = pr.get("manifest", {}).get("items", 0)
    seeds = pr.get("manifest", {}).get("seeds", [])
    expected_len = items_cnt * len(seeds)
    if len(pr.get("rows", [])) != expected_len:
        problems.append(f"row count {len(pr.get('rows', []))} != manifest items ({items_cnt}) x seeds ({len(seeds)})")

    # 3. (item_id, seed) set vs baseline (and duplicate rows)
    pr_pairs = [(r.get("item_id"), r.get("seed")) for r in pr.get("rows", [])]
    if len(pr_pairs) != len(set(pr_pairs)):
        problems.append("duplicate (item_id, seed) rows in PR")
    base_pairs = [(r.get("item_id"), r.get("seed")) for r in base.get("rows", [])]
    if set(pr_pairs) != set(base_pairs):
        problems.append("PR (item_id, seed) set differs from baseline")

    # 4. evaluator_failures or None values for graded spec metrics
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s)")
    graded_spec_metrics = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for r in pr.get("rows", []):
        for m in graded_spec_metrics:
            if r.get(m) is None:
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has None for graded metric {m}")
                break
        if any("has None for graded metric" in p for p in problems):
            break

    # 5. Slice tags integrity
    pr_slices = {r.get("item_id"): tuple(sorted(r.get("slices") or [])) for r in pr.get("rows", [])}
    base_slices = {r.get("item_id"): tuple(sorted(r.get("slices") or [])) for r in base.get("rows", [])}
    for item_id, ps in pr_slices.items():
        if item_id in base_slices and ps != base_slices[item_id]:
            problems.append(f"item {item_id} slice tags {ps} differ from baseline {base_slices[item_id]}")
            break

    # 6. Ratchet check with base_spec
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        base_m_map = {m["id"]: m for m in base_spec.get("metrics", [])}
        spec_m_map = {m["id"]: m for m in spec.get("metrics", [])}
        for mid, bm in base_m_map.items():
            if mid not in spec_m_map:
                problems.append(f"metric {mid} dropped from spec")
                continue
            sm = spec_m_map[mid]
            if bm.get("blocking") and not sm.get("blocking"):
                problems.append(f"metric {mid} made non-blocking")
            bth = bm.get("threshold", {})
            sth = sm.get("threshold", {})
            if "min" in bth and ("min" not in sth or sth["min"] < bth["min"]):
                problems.append(f"metric {mid} min threshold loosened from {bth.get('min')} to {sth.get('min')}")
            if "max" in bth and ("max" not in sth or sth["max"] > bth["max"]):
                problems.append(f"metric {mid} max threshold loosened from {bth.get('max')} to {sth.get('max')}")
            if "max_increase" in bth and ("max_increase" not in sth or sth["max_increase"] > bth["max_increase"]):
                problems.append(f"metric {mid} max_increase loosened from {bth.get('max_increase')} to {sth.get('max_increase')}")
            if bth.get("no_significant_drop") and not sth.get("no_significant_drop"):
                problems.append(f"metric {mid} dropped no_significant_drop")

        base_s_map = {s["name"]: s for s in base_spec.get("slices", [])}
        spec_s_map = {s["name"]: s for s in spec.get("slices", [])}
        for sname, bs in base_s_map.items():
            if sname not in spec_s_map:
                problems.append(f"slice {sname} dropped from spec")
                continue
            ss = spec_s_map[sname]
            if bs.get("blocking") and not ss.get("blocking"):
                problems.append(f"slice {sname} made non-blocking")
            if "min" in bs and ("min" not in ss or ss["min"] < bs["min"]):
                problems.append(f"slice {sname} min loosened from {bs.get('min')} to {ss.get('min')}")
            if bs.get("no_significant_drop") and not ss.get("no_significant_drop"):
                problems.append(f"slice {sname} dropped no_significant_drop")

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})

    for s in spec.get("slices", []):
        sname = s["name"]
        mid = s["metric"]
        blocking = s.get("blocking", False)
        slice_id = f"slice:{sname}/{mid}"

        a = per_item(pr, mid, slice_name=sname)
        b = per_item(base, mid, slice_name=sname)
        if not a:
            continue

        val = round(sum(a.values()) / len(a), 4)
        verdict = "ok"
        note = ""

        if "min" in s and val < s["min"]:
            verdict = "fail"

        if s.get("no_significant_drop") and a and b:
            shared = sorted(set(a) & set(b))
            if shared:
                d, lo, hi = stats.paired_bootstrap(
                    [a[k] for k in shared],
                    [b[k] for k in shared],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"

        if verdict != "ok" and blocking:
            blocked.append(slice_id)

        label = "ok" if verdict == "ok" else ("BLOCK" if blocking else "warn")
        lines.append(f"  {slice_id:<22} {val!s:<8} {json.dumps(s):<40} {note:<28} {label}")

    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
