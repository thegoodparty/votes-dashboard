# VOTES Metrics Dashboard

Internal engineering metrics dashboard for GoodParty.org. Visualizes the VOTES quality framework: **V**elocity, **O**perations, **T**esting, **E**xperience, **S**ecurity.

Live URL: see **repo Settings → Pages** after the first successful deploy. Access follows repo access (private repo).

## Architecture

```
Drive folder (VOTES Metrics.xlsx + data.json)
  │
  │  weekly cron + manual workflow_dispatch
  ▼
.github/workflows/sync-metrics.yml
  └─ scripts/sync.py
       ├─ Download data.json from Drive (primary path, once Cowork emits it)
       ├─ Fallback: parse VOTES Metrics.xlsx directly
       ├─ Validate shape against metrics-config.json
       └─ Commit data.json if changed
  │
  ▼
.github/workflows/pages.yml  (triggered by push to data.json / src/)
  └─ Deploys src/ + data.json + metrics-config.json to GitHub Pages
```

Two files live in the repo:

- **`data.json`** — auto-generated, committed by the sync job. Don't hand-edit.
- **`metrics-config.json`** — hand-maintained. Goals, directions, units, display labels. Edit this when a goal changes.

## Deploy checklist

### First-time setup

1. **Service account JSON key** is already added as the repo secret `GDRIVE_SERVICE_ACCOUNT_KEY`, with read-only Viewer access to the Drive folder `1td1ae4pGBZ59TZ8tHTKWZb-CvqerjlpS`.

2. **Enable Pages.** Repo → Settings → Pages → "Build and deployment" → Source: **GitHub Actions**. (The `pages.yml` workflow handles the build.)

3. **Push this repo to `main`.** The pages workflow runs, the site goes live — but will show "Failed to load dashboard data" until step 4 populates `data.json`.

4. **Trigger the first sync.** Repo → Actions → "Sync VOTES metrics from Drive" → Run workflow. This generates `data.json` via the xlsx fallback (Cowork hasn't emitted `data.json` to Drive yet). A successful run commits the file and triggers a Pages rebuild.

5. **Deploy the Cowork prompt addon** — see `cowork-addon/PROMPT_EDIT.md`. Until this is in place, the sync job keeps using the xlsx fallback. Both paths work.

### Ongoing operation

- **Cron:** Mondays 18:00 UTC (11am Pacific). Adjust in `.github/workflows/sync-metrics.yml`.
- **Manual refresh:** Actions → "Sync VOTES metrics from Drive" → Run workflow.
- **Failures surface as red X's on the Actions tab.** The sync is structured to fail loudly rather than silently produce bad data.

## Updating a goal

1. Edit `metrics-config.json` (update `goal_value` and/or `goal_date`).
2. Edit `weekly-votes-prompt.md` in Drive (the `Goal column value` field for that metric).
3. Commit, push. Pages redeploys on the config change.

The two sources of truth for goals (prompt + config) are intentionally duplicated so the spreadsheet stays readable on its own. If this becomes painful, we can move goals to config-only and strip them from the prompt — but that makes the xlsx less self-describing.

## Local development

```bash
# Install deps for the sync script
pip install -r scripts/requirements.txt

# Run sync locally (needs the service account JSON saved somewhere)
export GDRIVE_SERVICE_ACCOUNT_KEY="$(cat path/to/key.json)"
python scripts/sync.py

# Serve the dashboard locally
cd src
cp ../data.json ../metrics-config.json .
python -m http.server 8000
# Visit http://localhost:8000
```

## Adding a new metric

1. Add an entry to `metrics-config.json` with a new `id` (single uppercase letter).
2. Update `weekly-votes-prompt.md` to have Cowork write a new row to the xlsx with that metric's prefix (`X - Whatever (details)`).
3. Next sync run picks it up automatically. The sync script fails loudly if the config has a metric ID the sheet doesn't contain.

## Troubleshooting

**Action fails with `data.json in Drive is not valid JSON`.** The Cowork run produced a malformed JSON. Manually delete `data.json` from the Drive folder (the xlsx fallback will kick in next run), then investigate the Cowork run.

**Action fails with `Validation failed: metrics missing from data`.** A required metric (from `metrics-config.json`) isn't in the spreadsheet. Either Cowork skipped a row, or someone renamed a metric in column A such that the `<LETTER> - ` prefix is no longer first.

**Dashboard shows "Failed to load dashboard data".** The pages deploy shipped without one of the JSON files. Check the most recent "Deploy dashboard to Pages" Action run.

**The current value on a card is `—` but the chart shows data.** The last week's cell was non-numeric (e.g., `"N/A (awaiting PMF)"` or `"Awaiting weekly-senscy-score run"` carry-forward text). Expected for E-row; investigate otherwise.

## Files

| Path | Purpose |
|---|---|
| `metrics-config.json` | Hand-maintained metric definitions (goals, directions, units) |
| `data.json` | Auto-generated weekly time series (created by first sync run; not in initial commit) |
| `scripts/sync.py` | Drive → repo sync logic |
| `scripts/requirements.txt` | Python deps for sync |
| `.github/workflows/sync-metrics.yml` | Weekly cron + manual dispatch |
| `.github/workflows/pages.yml` | Pages deployment |
| `src/index.html` | Dashboard markup |
| `src/style.css` | Dashboard styling |
| `src/app.js` | Chart rendering |
| `src/chart.umd.js` | Vendored Chart.js v4.4.6 (no external CDN dependency) |
| `cowork-addon/export_dashboard_json.py` | To deploy into the Drive project folder |
| `cowork-addon/PROMPT_EDIT.md` | Exact prompt changes for `weekly-votes-prompt.md` |
