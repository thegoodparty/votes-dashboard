# Prompt addon for `weekly-votes-prompt.md`

Paste the following two additions into the Cowork prompt `weekly-votes-prompt.md` in the Drive folder `1td1ae4pGBZ59TZ8tHTKWZb-CvqerjlpS`.

---

## 1) Add a new step to the Workflow section

After step 5 (save workbook), before step 6 (share link), insert:

> **5b. Export dashboard JSON.** After saving `VOTES Metrics.xlsx`, copy `export_dashboard_json.py` (in the project folder) into the current working directory and run it:
>
> ```bash
> python3 export_dashboard_json.py
> ```
>
> This reads every date-named tab and writes `data.json` in the project folder. The dashboard's GitHub Action consumes this file. If the script exits nonzero, investigate and fix **before** proceeding — do NOT delete `data.json` manually, since the existing file is the last-known-good snapshot.

## 2) Add `export_dashboard_json.py` to the project folder

Upload the file `cowork-addon/export_dashboard_json.py` from the `goodpartyorg/votes-dashboard` repo into the Drive folder alongside `VOTES Metrics.xlsx`.

---

## Why this is kept minimal

- The script is self-contained (reads xlsx → writes json, no network, no Drive API calls from inside Cowork).
- It validates structure itself before writing — if a metric row is missing from any tab, it aborts and preserves the prior `data.json`.
- It uses `openpyxl` which is already in the Cowork Python environment (`create_votes_workbook.py` uses it).
- No new secrets, no API calls out of Cowork.
