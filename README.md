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
| `tools/publish.py` | Fetches, builds, reports the delta, and (on request) deploys to a self-hosted web root. |
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

## Publishing

`tools/publish.py` is an alternative to GitHub Pages, for a site served from a
Linux box you control (shell and cron). It wraps the whole workflow - fetch,
build, review, deploy - into one deliberate command. It never runs `git`, and
never needs a Google account, OAuth token or service account: the sheet stays
restricted to "anyone in NOAA", and every publish is a decision a human makes
after reading a plain-English delta report.

### One-time setup - pick one of two input modes

- **Fetch from the sheet automatically.** The sheet can't be link-shared, so
  the anonymous CSV export URL won't work; instead have the sheet owner deploy
  a small Apps Script web app that exports each tab as CSV over HTTPS
  (`?token=...&tab=atl|pac`), deployed "Execute as: Me" / "Who has access:
  Anyone" so the sheet itself never has to leave "anyone in NOAA". Then set:

  ```bash
  export HF_EXPORT_URL="https://script.google.com/macros/s/AKfycb.../exec"
  export HF_EXPORT_TOKEN="<the shared secret the Apps Script checks>"
  ```

  or put the same two values in `tools/publish.local.json` (already
  gitignored - the token is a secret and must never land in a commit):

  ```json
  {"url": "https://script.google.com/macros/s/AKfycb.../exec",
   "token": "<the shared secret the Apps Script checks>"}
  ```

- **Export by hand.** Download each basin tab as CSV (File > Download > Comma
  Separated Values) into `data/hf_lows/` yourself, and always run with
  `--no-fetch`. No setup needed, and it works today even before the Apps
  Script exists.

Both modes feed the same build, review and deploy steps below.

### Normal workflow

```bash
python3 tools/publish.py                        # fetch, build, print what changed
python3 tools/publish.py --no-fetch              # same, but build from CSVs already on disk
python3 tools/publish.py --deploy /var/www/hf    # also publish, after you type y to confirm
python3 tools/publish.py --deploy /var/www/hf --yes   # publish with no prompt, e.g. from cron
```

Run it without `--deploy` first and read the report before deciding anything:
events added, removed or modified (with dates and basins for the additions),
any season whose event count moved, data-quality notes that appeared or
disappeared, and the total event/fix counts before and after. "No changes"
means the sheet hasn't moved since the last publish - that's the common case
and it says so in one line.

Only pass `--deploy PATH` once that report looks right. It copies `docs/`
into an existing web root as one atomic directory swap, so the live site is
never caught half-updated mid-copy, prints exactly what it wrote, and leaves
anything already in that directory that the site doesn't own untouched.
Without `--yes` it shows the delta report and waits for you to type `y`.

### Moving to cron

Once you trust the report, drop the confirmation and let it run unattended:

```cron
0 6 * * * cd /path/to/awips-tools && python3 tools/publish.py --deploy /var/www/hf --yes >> /var/log/hf-publish.log 2>&1
```

It exits non-zero on any failure (a bad fetch, a bad deploy target) and 0
otherwise, whether or not anything changed - point cron's mail, or whatever
alerts on a non-zero exit, at it, and watch the log for a while before fully
trusting an unattended run.
