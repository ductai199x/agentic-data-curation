"""Time-to-adapt report: a table per release and the halving curve (inline SVG, no plotting dependency).

Per run: hours from release to detected, first samples, batch ready, model updated; detection before/after.
time_to_adapt_h = model_updated - detected (when the watch caught the release; release if unknown), or 0 when the
model already met the target before any update. That is the pipeline's own speed, the number that should halve;
release_to_update_h adds the watch latency on top. The curve plots time_to_adapt per release on a log2 axis next to
the ideal "halve every release" line; hollow points are updates that did not reach the detection target.
"""

import csv
import math
from pathlib import Path

from adapt.timeline import hours_between, load_events, EVENT_ORDER

COLUMNS = ["run_id", "dry_run", "release", "detected_h", "first_samples_h", "batch_ready_h", "model_updated_h",
           "time_to_adapt_h", "release_to_update_h", "target_met", "before_ladder_auc", "after_ladder_auc", "regressions_flagged"]


def build_rows(timeline_path: Path, include_dry_run: bool = True) -> list[dict]:
    rows = []
    for run_id, events in load_events(timeline_path).items():
        release = events.get("release", {}).get("at")
        dry = any(e.get("dry_run") for e in events.values())
        if dry and not include_dry_run: continue
        h = {e: hours_between(release, events[e]["at"]) if e in events else None for e in EVENT_ORDER}
        before, after = events.get("eval_before", {}), events.get("eval_after", {})
        start = events.get("detected", events.get("release", {})).get("at")
        if before.get("meets_target"): adapt_h, met = 0.0, True   # generalized zero-shot: nothing to adapt
        elif "model_updated" in events:
            adapt_h, met = hours_between(start, events["model_updated"]["at"]), bool(after.get("meets_target"))
        else: adapt_h, met = None, None
        rows.append({"run_id": run_id, "dry_run": dry, "release": release, "detected_h": h["detected"],
                     "first_samples_h": h["first_samples"], "batch_ready_h": h["batch_ready"],
                     "model_updated_h": h["model_updated"], "time_to_adapt_h": adapt_h,
                     "release_to_update_h": 0.0 if before.get("meets_target") else h["model_updated"], "target_met": met,
                     "before_ladder_auc": before.get("ladder_mean_auc"), "after_ladder_auc": after.get("ladder_mean_auc"),
                     "regressions_flagged": ",".join(after.get("regressions_flagged", {}) or [])})
    return sorted(rows, key=lambda r: r["release"] or "")


def _fmt(v):
    if v is None: return "–"
    if isinstance(v, float): return f"{v:.2f}"
    return str(v)


def halving_svg(rows: list[dict], width: int = 640, height: int = 320) -> str:
    points = [(i, r["time_to_adapt_h"], r["run_id"], r["target_met"]) for i, r in enumerate(rows) if r["time_to_adapt_h"] is not None]
    pad_l, pad_b, pad_t, pad_r = 60, 50, 20, 20
    if not points:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><text x="20" y="40">No completed adaptations yet</text></svg>'
    floor = 1 / 60  # hours; 0 h (already detected) is drawn on the floor
    ys = [max(floor, p[1]) for p in points]
    ideal = [max(floor, ys[0] / 2 ** k) for k in range(len(points))]
    top = math.ceil(math.log2(max(ys + ideal))) + 1
    bottom = math.floor(math.log2(floor))
    n = max(2, len(points))
    sx = lambda i: pad_l + i * (width - pad_l - pad_r) / (n - 1)
    sy = lambda v: pad_t + (top - math.log2(v)) * (height - pad_t - pad_b) / (top - bottom)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" font-size="11">']
    for e in range(bottom, top + 1):
        y = sy(2 ** e); label = f"{2 ** e * 60:.0f} min" if 2 ** e < 1 else f"{2 ** e:g} h" if 2 ** e < 48 else f"{2 ** e / 24:g} d"
        parts.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{y:.1f}" y2="{y:.1f}" stroke="#ddd"/><text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end">{label}</text>')
    path = " ".join(f"{'M' if k == 0 else 'L'}{sx(k):.1f},{sy(v):.1f}" for k, v in enumerate(ideal))
    parts.append(f'<path d="{path}" fill="none" stroke="#999" stroke-dasharray="4 4"/><text x="{width - pad_r}" y="{pad_t + 10}" text-anchor="end" fill="#999">ideal: halve each release</text>')
    path = " ".join(f"{'M' if k == 0 else 'L'}{sx(k):.1f},{sy(v):.1f}" for k, v in enumerate(ys))
    parts.append(f'<path d="{path}" fill="none" stroke="#2a6fdb" stroke-width="2"/>')
    for k, (_, v, run_id, met) in enumerate(points):
        fill = "#2a6fdb" if met else "white"
        parts.append(f'<circle cx="{sx(k):.1f}" cy="{sy(ys[k]):.1f}" r="4" fill="{fill}" stroke="#2a6fdb" stroke-width="2"/>'
                     f'<text x="{sx(k):.1f}" y="{height - pad_b + 16}" text-anchor="middle">{run_id.rsplit("_", 1)[0][:18]}</text>')
    parts.append(f'<text x="{pad_l}" y="{height - 8}">release (in order)  ·  y: time from detection to updated model (log2; hollow = target not met)</text></svg>')
    return "\n".join(parts)


def write_report(timeline_path: Path, reports_dir: Path, include_dry_run: bool = True) -> Path:
    rows = build_rows(timeline_path, include_dry_run)
    reports_dir.mkdir(parents=True, exist_ok=True)
    with open(reports_dir / "time_to_adapt.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS); writer.writeheader(); writer.writerows(rows)
    (reports_dir / "halving_curve.svg").write_text(halving_svg(rows))
    lines = ["# Time to adapt", "", "Stage hours are measured from the generator's release; time_to_adapt_h runs from detection to the updated model.", "",
             "| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(_fmt(r[c]) for c in COLUMNS) + " |" for r in rows]
    lines += ["", "![halving curve](halving_curve.svg)", ""]
    out = reports_dir / "TIME_TO_ADAPT.md"
    out.write_text("\n".join(lines))
    return out
