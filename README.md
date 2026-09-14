# awips-tools

AWIPS tools and procedures.

## Contents

| Path | What it is |
|---|---|
| `GFE/` | GFE procedures, smart tools and shared utilities. |
| `legacy_tools/` | Earlier versions kept for reference; see `legacy_tools/VERSION_CONTROL.md`. |
| `tests/` | Verification scripts and fixtures. |
| `web/TCWind_JTWC/` | Google Apps Script preview of the JTWC tropical cyclone wind tool. |
| `data/hf_lows/` | CSV exports of the hurricane force extratropical low archive workbook. |
| `tools/build_hf_lows.py` | Normalizes those CSVs into the site data under `docs/data/`. |
| `docs/` | The HF extratropical low archive site, published with GitHub Pages. |

## HF extratropical low archive site

A static page for browsing and summarizing hurricane force extratropical lows in
the North Atlantic and North Pacific - tracks, climatology charts, a searchable
event table, and a data quality report. See `docs/README.md`.

Update it in three steps:

```bash
# 1. export each basin tab of the workbook over the CSVs in data/hf_lows/
# 2. rebuild the site data
python3 tools/build_hf_lows.py
# 3. commit both the CSVs and docs/data, then push
```

Preview locally with `python3 -m http.server 8000 --directory docs`.
