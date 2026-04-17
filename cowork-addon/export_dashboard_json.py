#!/usr/bin/env python3
"""
export_dashboard_json.py

Runs inside Cowork after `VOTES Metrics.xlsx` is saved. Reads all tabs, assembles
a data.json with per-metric time series, writes it to the same project folder.

The dashboard repo's GitHub Action then pulls this data.json, validates it, and
commits it on a weekly cron. If this script fails, the xlsx remains the source
of truth and the Action's fallback path will parse the xlsx directly.

Contract (do not change without also updating the dashboard repo):

  {
    "generated_at": "<ISO 8601 UTC timestamp>",
    "weeks": ["YYYY-MM-DD", ...],                       # sorted ascending
    "series": {
      "V": [<number|null>, ...],                        # aligned to weeks
      "O": [<number|null>, ...],
      "T": [<number|null>, ...],
      "E": [<number|null>, ...],
      "S": [<number|null>, ...]
    },
    "metric_labels_from_sheet": {
      "V": "V - Velocity (...)",
      ...
    }
  }
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

WORKBOOK_PATH = Path("VOTES Metrics.xlsx")
OUTPUT_PATH = Path("data.json")
REQUIRED_IDS = {"V", "O", "T", "E", "S"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def main():
    if not WORKBOOK_PATH.exists():
        sys.exit(f"[export_dashboard_json] {WORKBOOK_PATH} not found in CWD")

    wb = load_workbook(WORKBOOK_PATH, data_only=True)

    per_week = {}        # week -> {metric_id: value|None}
    labels = {}          # metric_id -> label from column A (first seen)

    for name in wb.sheetnames:
        if not DATE_RE.fullmatch(name):
            print(f"[export_dashboard_json] skipping non-date sheet: {name!r}")
            continue
        ws = wb[name]
        week_values = {}
        # Rows 2..onward (row 1 is header); columns A=metric, C=current
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or len(row) < 3:
                continue
            metric_name = row[0]
            current = row[2]
            if not metric_name:
                continue
            m = re.match(r"^([A-Z])\s*-\s*", str(metric_name))
            if not m:
                continue
            mid = m.group(1)
            labels.setdefault(mid, str(metric_name))
            # Coerce to number; anything non-numeric (incl. "N/A (awaiting PMF)") -> None
            if isinstance(current, (int, float)):
                val = int(current) if float(current).is_integer() else float(current)
            else:
                try:
                    f = float(current)
                    val = int(f) if f.is_integer() else f
                except (TypeError, ValueError):
                    val = None
            week_values[mid] = val
        per_week[name] = week_values

    if not per_week:
        sys.exit("[export_dashboard_json] no date-named tabs found in workbook")

    weeks_sorted = sorted(per_week.keys())

    # Self-check: every week must have every required metric ID row present
    # (value can be None for E or for carry-forward failures — structure still must exist).
    # Aborting here prevents overwriting the existing Drive data.json with incomplete data;
    # the dashboard Action will fall back to parsing the xlsx directly if needed.
    for week, mvals in per_week.items():
        missing = REQUIRED_IDS - set(mvals.keys())
        if missing:
            sys.exit(
                f"[export_dashboard_json] week {week} is missing metric rows: "
                f"{sorted(missing)}. Aborting without overwriting data.json."
            )

    # Build aligned series
    all_ids = sorted(REQUIRED_IDS | set(labels.keys()))
    series = {
        mid: [per_week[w].get(mid) for w in weeks_sorted]
        for mid in all_ids
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "weeks": weeks_sorted,
        "series": series,
        "metric_labels_from_sheet": labels,
    }

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"[export_dashboard_json] wrote {OUTPUT_PATH} "
        f"({len(weeks_sorted)} weeks, {len(all_ids)} metrics)."
    )


if __name__ == "__main__":
    main()
