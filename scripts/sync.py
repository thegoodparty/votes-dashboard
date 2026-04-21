#!/usr/bin/env python3
"""
Sync VOTES metrics data from Drive to the repo.

Primary path: Cowork writes data.json to the Drive folder; we download + validate + commit it.
Fallback path: no data.json in Drive yet — parse VOTES Metrics.xlsx directly.

Exits nonzero on validation failure so the GitHub Action fails loudly.
"""
import io
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


DRIVE_FOLDER_ID = "1td1ae4pGBZ59TZ8tHTKWZb-CvqerjlpS"
XLSX_NAME = "VOTES Metrics.xlsx"
JSON_NAME = "data.json"

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "metrics-config.json"
OUTPUT_PATH = REPO_ROOT / "data.json"

SPREADSHEET_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_TAG = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
SHEET_RID_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


# ---------- Drive auth & discovery ----------

def drive_client():
    key_json = os.environ.get("GDRIVE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        sys.exit("GDRIVE_SERVICE_ACCOUNT_KEY env var not set")
    info = json.loads(key_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def find_file(svc, folder_id, name):
    """Return file metadata dict or None."""
    q = f"'{folder_id}' in parents and name = '{name}' and trashed = false"
    resp = svc.files().list(q=q, fields="files(id, name, mimeType, modifiedTime)").execute()
    files = resp.get("files", [])
    return files[0] if files else None


def download_bytes(svc, file_id):
    request = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# ---------- XLSX fallback parser ----------

def col_to_idx(ref):
    letters = "".join(c for c in ref if c.isalpha())
    idx = 0
    for c in letters:
        idx = idx * 26 + (ord(c.upper()) - ord("A") + 1)
    return idx - 1


RAW_DATA_SHEET_NAME = "raw data"


def _read_sheet_rows(z, sheet_path, shared):
    """Read a single sheet's cells, returning a list of row dicts: {col_idx: value}."""
    with z.open(sheet_path) as f:
        sheet_root = ET.parse(f).getroot()
    sheet_data = sheet_root.find("s:sheetData", SPREADSHEET_NS)

    rows = []
    for row in sheet_data.findall("s:row", SPREADSHEET_NS):
        cells = {}
        for c in row.findall("s:c", SPREADSHEET_NS):
            ref = c.get("r")
            t = c.get("t")
            v_elem = c.find("s:v", SPREADSHEET_NS)
            is_elem = c.find("s:is", SPREADSHEET_NS)
            if t == "s" and v_elem is not None:
                val = shared[int(v_elem.text)]
            elif t == "inlineStr" and is_elem is not None:
                t_sub = is_elem.find("s:t", SPREADSHEET_NS)
                val = t_sub.text if t_sub is not None else ""
            elif v_elem is not None:
                val = v_elem.text
            else:
                val = ""
            cells[col_to_idx(ref)] = val
        rows.append(cells)
    return rows


def _coerce_number(raw):
    """Return int/float for numeric-looking values, None otherwise."""
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    return int(val) if val.is_integer() else val


def _extract_metric_id(label):
    """Return the 'V' in 'V - Velocity (...)' or None if no match."""
    m = re.match(r"^([A-Z])\s*-\s*", label or "")
    return m.group(1) if m else None


def _parse_raw_data_sheet(z, sheet_path, shared):
    """
    Parse a 'raw data' tab with layout:
      Date | V - Velocity | O - Operations | T - Testing | E - Experience | S - Security
      YYYY-MM-DD | ...values...

    Returns (weeks_sorted, series_by_id, labels_by_id) or raises ValueError on bad shape.
    """
    rows = _read_sheet_rows(z, sheet_path, shared)
    if not rows:
        raise ValueError("'raw data' sheet is empty")

    header = rows[0]
    # Column 0 is the date column; columns 1..N are metrics.
    col_to_mid = {}          # column index -> metric id
    labels_by_id = {}        # metric id -> header label
    for col_idx in sorted(header.keys()):
        if col_idx == 0:
            continue
        label = str(header[col_idx] or "")
        mid = _extract_metric_id(label)
        if mid is None:
            print(f"[warn] 'raw data' header col {col_idx} {label!r} has no 'X - ' prefix; ignoring")
            continue
        col_to_mid[col_idx] = mid
        labels_by_id[mid] = label

    if not col_to_mid:
        raise ValueError("'raw data' sheet has no recognized metric columns")

    per_week = {}  # date -> {mid: value}
    for r in rows[1:]:
        date_raw = str(r.get(0, "") or "").strip()
        if not date_raw:
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_raw):
            print(f"[warn] 'raw data' row with non-ISO date {date_raw!r}; skipping")
            continue
        week_values = {}
        for col_idx, mid in col_to_mid.items():
            week_values[mid] = _coerce_number(r.get(col_idx, ""))
        per_week[date_raw] = week_values

    if not per_week:
        raise ValueError("'raw data' sheet has no data rows")

    weeks_sorted = sorted(per_week.keys())
    all_ids = sorted(labels_by_id.keys())
    series = {mid: [per_week[w].get(mid) for w in weeks_sorted] for mid in all_ids}
    return weeks_sorted, series, labels_by_id


def _parse_date_tabs(z, date_sheets, shared):
    """Fallback: parse each date-named tab as one week."""
    weeks = []
    per_week_values = {}
    labels_by_id = {}

    for sheet_name, sheet_path in date_sheets:
        rows = _read_sheet_rows(z, sheet_path, shared)
        week_values = {}
        for r in rows[1:]:
            metric_name = r.get(0, "")
            current = r.get(2, "")  # column C
            if not metric_name:
                continue
            mid = _extract_metric_id(str(metric_name))
            if mid is None:
                continue
            labels_by_id.setdefault(mid, str(metric_name))
            week_values[mid] = _coerce_number(current)
        weeks.append(sheet_name)
        per_week_values[sheet_name] = week_values

    weeks_sorted = sorted(set(weeks))
    all_ids = sorted(labels_by_id.keys())
    series = {mid: [per_week_values[w].get(mid) for w in weeks_sorted] for mid in all_ids}
    return weeks_sorted, series, labels_by_id


def parse_xlsx(xlsx_bytes):
    """
    Parse the workbook. Prefers the 'raw data' tab (layout: Date | V | O | T | E | S).
    Falls back to per-date tabs if 'raw data' is missing or malformed.
    Returns (weeks_sorted, series_by_id, labels_by_id).
    """
    z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))

    # Workbook relationships -> sheet file targets
    with z.open("xl/_rels/workbook.xml.rels") as f:
        rels_root = ET.parse(f).getroot()
    rid_to_target = {
        rel.get("Id"): rel.get("Target")
        for rel in rels_root.findall(REL_TAG)
    }

    with z.open("xl/workbook.xml") as f:
        wb_root = ET.parse(f).getroot()

    sheets = []
    sheets_container = wb_root.find("s:sheets", SPREADSHEET_NS)
    for sheet in sheets_container.findall("s:sheet", SPREADSHEET_NS):
        name = sheet.get("name")
        rid = sheet.get(SHEET_RID_ATTR)
        target = rid_to_target.get(rid)
        if target is None:
            print(f"[warn] sheet {name!r} has no matching relationship; skipping")
            continue
        # Resolve Target to zip archive path. Targets may be:
        #   (a) absolute: "/xl/worksheets/sheet1.xml"  -> strip leading slash
        #   (b) relative to rels file's parent (xl/): "worksheets/sheet1.xml" -> prepend "xl/"
        #   (c) already rooted: "xl/worksheets/sheet1.xml" -> use as-is
        if target.startswith("/"):
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = "xl/" + target
        sheets.append((name, target))

    # Shared strings (may be absent)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        with z.open("xl/sharedStrings.xml") as f:
            ss_root = ET.parse(f).getroot()
        for si in ss_root.findall("s:si", SPREADSHEET_NS):
            t = si.find("s:t", SPREADSHEET_NS)
            shared.append(t.text if t is not None else "")

    # Prefer 'raw data' tab (case-insensitive match)
    raw_data_sheet = next(
        ((n, p) for n, p in sheets if n.strip().lower() == RAW_DATA_SHEET_NAME),
        None,
    )
    if raw_data_sheet is not None:
        name, path = raw_data_sheet
        print(f"Using {name!r} tab (single-sheet layout).")
        try:
            return _parse_raw_data_sheet(z, path, shared)
        except ValueError as e:
            print(f"[warn] {name!r} tab unusable ({e}); falling back to date tabs.")

    # Fallback: iterate date-named tabs
    date_sheets = [
        (n, p) for n, p in sheets
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", n)
    ]
    if not date_sheets:
        raise ValueError(
            "No 'raw data' tab and no date-named tabs found in workbook."
        )
    print(f"Using {len(date_sheets)} date-named tabs (fallback layout).")
    return _parse_date_tabs(z, date_sheets, shared)


# ---------- Validation ----------

def validate(data, config):
    """Fail loudly if required metrics are missing or shapes disagree."""
    required_ids = {m["id"] for m in config["metrics"]}
    present_ids = set(data["series"].keys())
    missing = required_ids - present_ids
    if missing:
        sys.exit(f"Validation failed: metrics missing from data: {sorted(missing)}")

    extra = present_ids - required_ids
    if extra:
        print(f"[warn] metrics in data but not in config: {sorted(extra)}")

    n_weeks = len(data["weeks"])
    for mid, series in data["series"].items():
        if len(series) != n_weeks:
            sys.exit(
                f"Validation failed: series {mid!r} has {len(series)} points "
                f"but weeks has {n_weeks}"
            )
        for i, v in enumerate(series):
            if v is not None and not isinstance(v, (int, float)):
                sys.exit(
                    f"Validation failed: series {mid!r}[{i}] is {type(v).__name__} "
                    f"({v!r}); expected number or null"
                )

    # Weeks must be sorted ISO dates
    for w in data["weeks"]:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", w):
            sys.exit(f"Validation failed: non-ISO week name {w!r}")
    if data["weeks"] != sorted(data["weeks"]):
        sys.exit("Validation failed: weeks are not sorted chronologically")


# ---------- Main ----------

def main():
    config = json.loads(CONFIG_PATH.read_text())
    svc = drive_client()

    # Try data.json first (primary path once Cowork is emitting it)
    json_file = find_file(svc, DRIVE_FOLDER_ID, JSON_NAME)
    if json_file:
        print(f"Found {JSON_NAME} in Drive (modified {json_file['modifiedTime']}); downloading.")
        raw = download_bytes(svc, json_file["id"])
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.exit(f"data.json in Drive is not valid JSON: {e}")
    else:
        # Fallback: parse xlsx directly
        print(f"No {JSON_NAME} in Drive; falling back to parsing {XLSX_NAME}.")
        xlsx_file = find_file(svc, DRIVE_FOLDER_ID, XLSX_NAME)
        if not xlsx_file:
            sys.exit(f"Neither {JSON_NAME} nor {XLSX_NAME} found in Drive folder.")
        xlsx_bytes = download_bytes(svc, xlsx_file["id"])
        weeks, series, labels = parse_xlsx(xlsx_bytes)
        data = {
            "generated_at": xlsx_file["modifiedTime"],
            "weeks": weeks,
            "series": series,
            "metric_labels_from_sheet": labels,
        }

    validate(data, config)

    # Write stable-formatted JSON for clean diffs
    OUTPUT_PATH.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
    print(f"Wrote {OUTPUT_PATH} ({len(data['weeks'])} weeks, {len(data['series'])} metrics).")


if __name__ == "__main__":
    main()
