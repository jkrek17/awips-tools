#!/usr/bin/env python3
"""Review and publish the HF extratropical low archive site.

Wraps the manual "export -> build -> commit" workflow into one deliberate
command. Nothing here ever pushes to git or touches credentials: the sheet is
either fetched read-only through a companion Apps Script endpoint, or the CSVs
are exported by hand and the fetch step is skipped.

    fetch  ->  build  ->  report the delta  ->  (optionally) deploy

Fetching (optional, see --no-fetch)
------------------------------------
The Google Sheet stays restricted to "anyone in NOAA", so the anonymous CSV
export URL does not work here - Google would just hand back a sign-in page.
Instead a small Apps Script web app, deployed and owned by someone who already
has the sheet open, exports each tab as CSV over a plain HTTPS GET:

    GET <HF_EXPORT_URL>?token=<HF_EXPORT_TOKEN>&tab=atl|pac

That URL and token are configuration, not secrets to hardcode. Provide them as
environment variables:

    export HF_EXPORT_URL="https://script.google.com/macros/s/AKfycb.../exec"
    export HF_EXPORT_TOKEN="<the shared secret the Apps Script checks>"

or in a local, gitignored file tools/publish.local.json:

    {"url": "https://script.google.com/macros/s/AKfycb.../exec",
     "token": "<the shared secret the Apps Script checks>"}

Environment variables win if both are set. Neither this script, nor git, ever
needs to know a Google account password, OAuth token or service account key -
the Apps Script runs as its owner and only ever hands out read-only CSV to
whoever holds the shared token.

If neither is configured, that is a perfectly normal way to run this tool:
export the two tabs from the sheet by hand into data/hf_lows/ (File > Download
> Comma Separated Values, one per tab) and run with --no-fetch. Everything
downstream - build, delta report, deploy - works the same either way.

Building
--------
Delegates entirely to tools/build_hf_lows.py (imported, not reimplemented) so
there is exactly one place that knows how to parse, repair and classify a row.

Reporting
---------
The heart of this tool. Before overwriting anything, it loads the payload
currently published at docs/data/hf-lows.json (from git HEAD, so uncommitted
scratch edits in the working tree do not masquerade as "published"; falling
back to the working-tree file if git has none) and diffs it against the fresh
build: events added/removed/modified, season counts that moved, data-quality
notes that appeared or disappeared, and total event/fix counts. Use this to
decide whether the new data is actually ready to go out.

Deploying
---------
Only with --deploy TARGET, and only after you confirm (or pass --yes). Copies
docs/ into TARGET as a single directory swap so the live site is never caught
half-updated, and leaves anything under TARGET that this tool did not put
there alone.

--flat additionally collapses that copy into a single directory: every file
lands directly in TARGET with no assets/ or data/ subdirectories, and
docs/index.html is rewritten so its src=/href= attributes point at the bare
filenames instead. This exists for the one NOAA web server whose upload UI
can only take individual files into one folder, not whole directories - it
cannot reproduce docs/'s assets/ and data/ layout, so the flattened build is
the only thing it can receive. Before writing anything, --flat verifies the
assumption that makes this safe (no two files share a basename, and no CSS/JS
outside index.html hardcodes an assets/... or data/... path) and refuses to
deploy rather than guess if that assumption ever stops holding.

Usage:
    python3 tools/publish.py                       # fetch, build, report - no writes to TARGET
    python3 tools/publish.py --no-fetch             # build from CSVs already on disk
    python3 tools/publish.py --deploy /var/www/hf   # also publish, after confirmation
    python3 tools/publish.py --deploy /var/www/hf --yes   # publish unattended (e.g. cron)
    python3 tools/publish.py --deploy /var/www/flat --flat --yes  # flat, single-folder deploy
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(ROOT, "docs")
BUILD_SCRIPT = os.path.join(ROOT, "tools", "build_hf_lows.py")
PUBLISHED_JSON = "docs/data/hf-lows.json"          # relative to ROOT, and in git

# tools/build_hf_lows.py lives next to this script, so `import build_hf_lows`
# just works (Python puts a script's own directory on sys.path[0]). We call
# its build() directly rather than re-parsing CSVs ourselves - there is
# exactly one implementation of the normalization rules, and it stays there.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_hf_lows  # noqa: E402  (must follow the sys.path tweak above)

# Basin key -> destination CSV, matching build_hf_lows.BASINS. The Apps Script
# endpoint takes the short key (it looks the tab up itself), which also means
# this script does not care if someone reorders or renames tabs later.
FETCH_TARGETS = [
    ("atl", "data/hf_lows/HF_Data_-_Atl.csv"),
    ("pac", "data/hf_lows/HF_Data_-_Pac.csv"),
]

ENV_URL = "HF_EXPORT_URL"
ENV_TOKEN = "HF_EXPORT_TOKEN"
LOCAL_CONFIG = os.path.join(ROOT, "tools", "publish.local.json")

# A fetch this much smaller than what's already on disk is treated as
# suspicious rather than "the forecaster deleted most of the archive" - most
# likely a truncated response or an error page that happened to parse.
MIN_ROW_FRACTION = 0.5
MIN_ROWS_ABSOLUTE = 10

REQUEST_TIMEOUT_S = 30


# ---------------------------------------------------------------------------
# Endpoint configuration - env vars or a gitignored local file, never a secret
# baked into the script.
# ---------------------------------------------------------------------------

def load_endpoint_config():
    """Return (url, token, source) or (None, None, reason) if unconfigured."""
    url = os.environ.get(ENV_URL)
    token = os.environ.get(ENV_TOKEN)
    if url and token:
        return url, token, f"environment variables {ENV_URL}/{ENV_TOKEN}"

    file_url = file_token = None
    if os.path.exists(LOCAL_CONFIG):
        try:
            with open(LOCAL_CONFIG, encoding="utf-8") as fh:
                cfg = json.load(fh)
            file_url, file_token = cfg.get("url"), cfg.get("token")
        except (OSError, ValueError) as exc:
            return None, None, f"could not read {LOCAL_CONFIG}: {exc}"

    url = url or file_url
    token = token or file_token
    if url and token:
        return url, token, f"tools/publish.local.json (with any {ENV_URL}/{ENV_TOKEN} override)"

    return None, None, "not configured"


CONFIG_HELP = f"""\
No export endpoint is configured, so there is nothing to fetch automatically.

This is a normal way to run this tool - not every setup has the Apps Script
deployed yet. Two options:

  1. Export the two tabs by hand (File > Download > Comma Separated Values,
     once per tab) into data/hf_lows/, then run again with --no-fetch to
     build from those files, review the delta, and deploy.

  2. Ask whoever owns the sheet to deploy the companion Apps Script web app
     (it reads the restricted sheet on your behalf and hands back CSV to
     anyone holding a shared token, so the sheet itself never has to be
     shared beyond "anyone in NOAA"). Then set:

         export {ENV_URL}="https://script.google.com/macros/s/AKfycb.../exec"
         export {ENV_TOKEN}="<the shared secret the Apps Script checks>"

     or write the same two values to tools/publish.local.json (already
     gitignored - never commit a token):

         {{"url": "https://script.google.com/macros/s/AKfycb.../exec",
          "token": "<the shared secret the Apps Script checks>"}}
"""


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

class FetchError(Exception):
    """A fetch or validation failure with a message meant to be read, not a traceback."""


def fetch_url(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_S) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise FetchError(
            f"HTTP {exc.code} from the export endpoint.\n{_snippet(body)}") from None
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
        raise FetchError(
            f"Could not reach the export endpoint: {exc}\n"
            f"Check network connectivity and that {ENV_URL} is correct, or "
            f"run with --no-fetch to build from the CSVs already on disk."
        ) from None
    if status != 200:
        raise FetchError(f"HTTP {status} from the export endpoint.\n{_snippet(body)}")
    return body


def _snippet(text: str, n: int = 300) -> str:
    text = text.strip()
    return (text[:n] + " ...[truncated]") if len(text) > n else text


def looks_like_signin_or_html(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith(("<!doctype html", "<html")) or "accounts.google.com" in head


def validate_csv(text: str, basin_key: str, dest_path: str) -> int:
    """Confirm `text` is really the CSV we expect. Returns the data-row count."""
    if looks_like_signin_or_html(text):
        raise FetchError(
            f"Got an HTML page back for basin '{basin_key}' instead of CSV - this is "
            f"what Google (or a misconfigured Apps Script deployment) returns instead "
            f"of data when access is refused.\n"
            f"If this is straight from Google: the sheet must stay restricted to "
            f"'anyone in NOAA', so fetch it through the Apps Script endpoint instead "
            f"of a direct sheet URL.\n"
            f"If this is from the Apps Script endpoint: check that it is deployed as "
            f"'Execute as: Me' / 'Who has access: Anyone', and that {ENV_TOKEN} matches "
            f"what it expects.\n{_snippet(text)}")

    import csv as _csv
    import io as _io
    try:
        rows = list(_csv.reader(_io.StringIO(text)))
    except _csv.Error as exc:
        raise FetchError(f"Response for basin '{basin_key}' does not parse as CSV: {exc}\n"
                          f"{_snippet(text)}") from None
    if len(rows) < 2:
        raise FetchError(f"Response for basin '{basin_key}' has no data rows.\n{_snippet(text)}")

    # Reuse build_hf_lows's own column matching so "expected header" means
    # exactly the same thing here as it does at build time.
    cols = build_hf_lows.map_columns(rows[0])
    missing = [f for f in build_hf_lows.COLUMN_ALIASES if f not in cols]
    if missing:
        raise FetchError(
            f"Response for basin '{basin_key}' does not look like the HF low sheet: "
            f"no column found for {', '.join(missing)} (header was {rows[0]!r}).\n"
            f"This usually means an Apps Script error page came back instead of CSV.\n"
            f"{_snippet(text)}")

    data_rows = sum(1 for r in rows[1:] if any(str(c).strip() for c in r))
    if data_rows < MIN_ROWS_ABSOLUTE:
        raise FetchError(
            f"Response for basin '{basin_key}' has only {data_rows} data row(s), which "
            f"is implausibly small for this archive; refusing to overwrite the CSV on "
            f"disk with it.")

    existing_path = os.path.join(ROOT, dest_path)
    if os.path.exists(existing_path):
        with open(existing_path, newline="", encoding="utf-8-sig") as fh:
            existing_all_rows = list(_csv.reader(fh))
        existing_rows = sum(1 for r in existing_all_rows[1:] if any(str(c).strip() for c in r))
        if existing_rows > 0 and data_rows < existing_rows * MIN_ROW_FRACTION:
            raise FetchError(
                f"Response for basin '{basin_key}' has {data_rows} data rows, versus "
                f"{existing_rows} currently on disk - more than a {int(MIN_ROW_FRACTION*100)}% "
                f"drop. That is more consistent with a truncated fetch than a real edit "
                f"to the archive; refusing to overwrite {dest_path} with it. Re-run, or "
                f"pass --no-fetch to build from the existing file.")
    return data_rows


def fetch_basin(base_url: str, token: str, basin_key: str, dest_path: str) -> int:
    url = base_url + "?" + urllib.parse.urlencode({"token": token, "tab": basin_key})
    text = fetch_url(url)
    data_rows = validate_csv(text, basin_key, dest_path)

    # Write to a temp file next to the destination (same filesystem, so the
    # final move is a single rename) and only then replace the real CSV - a
    # crash or a validation failure above never leaves a half-written or
    # corrupt file in data/hf_lows/.
    dest_abs = os.path.join(ROOT, dest_path)
    os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(dest_abs), prefix=".fetch-", suffix=".csv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp_path, dest_abs)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return data_rows


def do_fetch() -> None:
    url, token, source = load_endpoint_config()
    if not url:
        print(CONFIG_HELP)
        raise SystemExit(1)
    print(f"Fetching from the export endpoint (config from {source})...")
    for basin_key, dest_path in FETCH_TARGETS:
        try:
            n = fetch_basin(url, token, basin_key, dest_path)
        except FetchError as exc:
            print(f"\nFetch failed for basin '{basin_key}':\n{exc}", file=sys.stderr)
            raise SystemExit(1) from None
        print(f"  {basin_key}: wrote {dest_path} ({n} data rows)")


# ---------------------------------------------------------------------------
# Building - all delegated to build_hf_lows
# ---------------------------------------------------------------------------

def load_published_payload():
    """The payload currently live, for diffing against. git HEAD if possible
    (so an uncommitted scratch build in the working tree never masquerades as
    "already published"), else whatever is on disk, else None (first run)."""
    try:
        blob = subprocess.run(
            ["git", "show", f"HEAD:{PUBLISHED_JSON}"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        return json.loads(blob)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        pass
    disk_path = os.path.join(ROOT, PUBLISHED_JSON)
    if os.path.exists(disk_path):
        with open(disk_path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def run_build(data_source: str | None = None):
    """Build the payload and write docs/data/*, exactly as tools/build_hf_lows.py
    does when run directly - reusing its own functions rather than
    re-implementing the write step differently in two places.

    `data_source` records how the CSVs in data/hf_lows/ got there for this
    particular run ("fetched" via the Apps Script endpoint, "local" when
    --no-fetch was passed) - build_hf_lows.py itself has no way to know that,
    so main() tells it."""
    payload = build_hf_lows.build(data_source=data_source)

    data_dir = os.path.join(DOCS_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    compact = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    with open(os.path.join(data_dir, "hf-lows.json"), "w", encoding="utf-8") as fh:
        fh.write(compact)
    with open(os.path.join(data_dir, "hf-lows.js"), "w", encoding="utf-8") as fh:
        fh.write("/* generated by tools/build_hf_lows.py - do not edit */\n")
        fh.write("window.HF_DATA = " + compact + ";\n")
    with open(os.path.join(data_dir, "qc-report.txt"), "w", encoding="utf-8") as fh:
        fh.write(build_hf_lows.qc_report(payload))
    return payload


# ---------------------------------------------------------------------------
# Delta report - the part this tool exists for
# ---------------------------------------------------------------------------

def decode_lows(payload):
    """Turn the array-encoded lows back into {(basin, id): {field: value}}."""
    fields = payload["lowFields"]
    out = {}
    for row in payload["lows"]:
        rec = dict(zip(fields, row))
        out[(rec["basin"], rec["id"])] = rec
    return out


def season_counts(lows_by_key):
    counts = {}
    for (basin, _id), rec in lows_by_key.items():
        counts[(basin, rec["season"])] = counts.get((basin, rec["season"]), 0) + 1
    return counts


def note_fingerprint(note):
    return (note.get("basin"), note.get("id"), note.get("date"), note.get("kind"),
            note.get("detail"))


def print_delta(old_payload, new_payload) -> bool:
    """Print the human-readable delta. Returns True if anything changed."""
    changed = False

    if old_payload is None:
        print("No previously published payload found (git HEAD has no "
              f"{PUBLISHED_JSON}, and none is on disk) - this looks like the first "
              "build. Nothing to compare against.")
        old_payload = {"lows": [], "lowFields": new_payload["lowFields"],
                       "qc": {"counts": {}, "notes": []}}
        changed = True

    old_lows, new_lows = decode_lows(old_payload), decode_lows(new_payload)
    old_keys, new_keys = set(old_lows), set(new_lows)

    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    common = old_keys & new_keys
    modified = sorted(k for k in common if old_lows[k] != new_lows[k])

    if added or removed or modified:
        changed = True
        print(f"Events: {len(added)} added, {len(removed)} removed, "
              f"{len(modified)} modified")
        for basin, low_id in added:
            rec = new_lows[(basin, low_id)]
            print(f"  + {basin} {low_id}  season {build_hf_lows.season_label(rec['season'])}  "
                  f"{rec['start']} -> {rec['end']}  peak {rec['peak']}")
        for basin, low_id in removed:
            rec = old_lows[(basin, low_id)]
            print(f"  - {basin} {low_id}  season {build_hf_lows.season_label(rec['season'])}  "
                  f"{rec['start']} -> {rec['end']}")
        for basin, low_id in modified:
            before, after = old_lows[(basin, low_id)], new_lows[(basin, low_id)]
            changed_fields = sorted(f for f in after if before.get(f) != after.get(f))
            print(f"  ~ {basin} {low_id}  changed: {', '.join(changed_fields)}")
    else:
        print("Events: no additions, removals or modifications")

    old_seasons, new_seasons = season_counts(old_lows), season_counts(new_lows)
    season_keys = sorted(set(old_seasons) | set(new_seasons))
    season_diffs = [(b, s) for (b, s) in season_keys
                     if old_seasons.get((b, s), 0) != new_seasons.get((b, s), 0)]
    if season_diffs:
        changed = True
        print("Per-season event counts changed:")
        for basin, season in season_diffs:
            print(f"  {basin} {build_hf_lows.season_label(season)}: "
                  f"{old_seasons.get((basin, season), 0)} -> {new_seasons.get((basin, season), 0)}")
    else:
        print("Per-season event counts: unchanged")

    old_counts = old_payload.get("qc", {}).get("counts", {})
    new_counts = new_payload.get("qc", {}).get("counts", {})
    count_keys = sorted(set(old_counts) | set(new_counts))
    count_diffs = [k for k in count_keys if old_counts.get(k, 0) != new_counts.get(k, 0)]
    if count_diffs:
        changed = True
        print("Data-quality counts changed:")
        for k in count_diffs:
            print(f"  {k}: {old_counts.get(k, 0)} -> {new_counts.get(k, 0)}")
    else:
        print("Data-quality counts: unchanged")

    old_notes = {note_fingerprint(n) for n in old_payload.get("qc", {}).get("notes", [])}
    new_notes = {note_fingerprint(n) for n in new_payload.get("qc", {}).get("notes", [])}
    new_only, resolved = new_notes - old_notes, old_notes - new_notes
    if new_only or resolved:
        changed = True
        print(f"Data-quality notes: {len(new_only)} new, {len(resolved)} resolved")
        for basin, low_id, date, kind, detail in sorted(new_only, key=lambda t: (t[0] or "", t[1] or "")):
            print(f"  + [{kind}] {basin} {low_id} {date}: {detail}")
        for basin, low_id, date, kind, detail in sorted(resolved, key=lambda t: (t[0] or "", t[1] or "")):
            print(f"  - [{kind}] {basin} {low_id} {date}: {detail}")
    else:
        print("Data-quality notes: unchanged")

    old_fixes = old_counts.get("fixes", 0)
    new_fixes = new_counts.get("fixes", 0)
    print(f"Totals: events {len(old_keys)} -> {len(new_keys)}, "
          f"fixes {old_fixes} -> {new_fixes}")

    if not changed:
        print("\nNo changes: this build matches the currently published data.")
    return changed


# ---------------------------------------------------------------------------
# Deploying - the human-gated, mostly-atomic copy into a web root
# ---------------------------------------------------------------------------

MANIFEST_NAME = ".awips-publish-manifest.json"


def validate_deploy_target(target: str) -> str:
    if not target or not target.strip():
        raise SystemExit("Refusing to deploy: empty target path.")
    home = os.path.expanduser("~")
    abspath = os.path.realpath(target)
    unsafe = {os.path.realpath("/"), os.path.realpath(home)}
    if abspath in unsafe:
        raise SystemExit(f"Refusing to deploy to {target!r} - that looks like '/' or your "
                          f"home directory, not a dedicated web root.")
    if not os.path.isdir(abspath):
        raise SystemExit(f"Refusing to deploy: {target!r} does not exist. Create the web "
                          f"root directory first (this tool will not create it for you), "
                          f"then run --deploy again.")
    if abspath == os.path.realpath(ROOT) or abspath == os.path.realpath(DOCS_DIR):
        raise SystemExit(f"Refusing to deploy into the repository itself ({target!r}).")
    return abspath


# docs/data/qc-report.txt is the plain-text data-quality report - every
# repair, flag and drop the build made (see build_hf_lows.qc_report()). It is
# still generated on every build and stays under docs/data/ in the repo,
# because it is genuinely useful there: for local development, and for CI's
# staleness check that confirms docs/data/ matches what the CSVs on disk
# would produce. But it never belongs on the public web server - the "Data
# quality" tab that used to show this in the UI was removed (see the comment
# above renderMethod() in docs/assets/js/app.js), nothing the page loads at
# runtime fetches this file, and the forecaster who owns this site does not
# want the raw QC report - which can name specific stations/observations
# treated as bad data - sitting at a guessable URL on a NOAA server with no
# UI pointing at it and no auth in front of it. So it is excluded here, at
# the one place both --deploy and --flat build their file list from, rather
# than trusted to stay out of some downstream list forever.
NOT_DEPLOYED = {"data/qc-report.txt"}

# Whole docs/ subtrees that are GitHub Pages content but not part of the
# archive site: they are served by Pages straight from docs/, but they never
# go to the NOAA web server with --deploy and never into a --flat build
# (docs/cps/index.html would collide with the archive's index.html there).
# docs/cps/ itself is not committed - the Pages workflow stages it on every
# build by copying cyclone_phase_space/article/ there (see
# .github/workflows/pages.yml's "Stage the cyclone phase space article"
# step) - so this set exists to protect that local staging copy from the
# NOAA deploy, the same way it would a committed subtree. Read by the
# workflow's flat-sync job the same way NOT_DEPLOYED is, so the two can
# never disagree about what --flat leaves out.
NOT_DEPLOYED_DIRS = {"cps"}


def iter_site_files():
    for dirpath, dirnames, filenames in os.walk(DOCS_DIR):
        rel_dir = os.path.relpath(dirpath, DOCS_DIR)
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d not in NOT_DEPLOYED_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, DOCS_DIR)
            if rel in NOT_DEPLOYED:
                continue
            yield rel


# ---------------------------------------------------------------------------
# --flat: collapsing docs/ into a single directory for the NOAA web UI that
# can only upload individual files, never a directory tree.
#
# This is only safe because docs/index.html is the *only* file that contains
# path references into assets/ or data/ - everything else is loaded by the
# <script>/<link>/<a> tags in index.html, which we rewrite to bare filenames
# below. Before touching anything we re-verify that assumption rather than
# trust it forever: a basename collision or a stray hardcoded path in the
# hand-written CSS/JS under docs/assets would make the flattened site silently
# broken, so both are checked and refused rather than guessed past.
# ---------------------------------------------------------------------------

ASSETS_DIR = os.path.join(DOCS_DIR, "assets")

# Local (non-external) reference: not a data: URI, not an absolute http(s)/
# protocol-relative URL, not a bare in-page anchor or a mailto/tel/javascript
# pseudo-scheme. Anything else is a path into this site and, in flat mode,
# gets rewritten (index.html) or must not exist at all (everywhere else).
_EXTERNAL_PREFIXES = ("data:", "http://", "https://", "//", "#",
                      "mailto:", "tel:", "javascript:")


def is_local_ref(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    return not value.lower().startswith(_EXTERNAL_PREFIXES)


_HTML_ATTR_RE = re.compile(r'(?P<pre>\b(?:src|href)\s*=\s*)(?P<q>["\'])(?P<val>.*?)(?P=q)')


def flatten_html(html: str) -> str:
    """Rewrite src=/href= attributes that point at local files to their bare
    basename. Leaves data:, http(s):, protocol-relative, #, mailto: and
    javascript: values untouched, and changes nothing else in the markup."""

    def repl(m: re.Match) -> str:
        val = m.group("val")
        if not is_local_ref(val):
            return m.group(0)
        return f'{m.group("pre")}{m.group("q")}{os.path.basename(val)}{m.group("q")}'

    return _HTML_ATTR_RE.sub(repl, html)


_CSS_URL_RE = re.compile(r'url\(\s*(["\']?)(.*?)\1\s*\)', re.IGNORECASE)
_JS_LOCAL_PATH_STR_RE = re.compile(r'''["'](?:assets|data)/[^"']*["']''')


def scan_flatten_hazards() -> list[str]:
    """Look for path references outside index.html that would break once the
    assets/ and data/ subdirectories are gone: url(...) in CSS, and hardcoded
    "assets/..." / "data/..." string literals in JS. Scoped to docs/assets -
    the hand-written app code - not docs/data, which holds only generated
    data payloads (e.g. a CSV source path recorded as descriptive text, not a
    reference anything loads by). Returns human-readable "file:line: ..."
    problem descriptions; an empty list means the scan found nothing."""
    problems = []
    if not os.path.isdir(ASSETS_DIR):
        return problems
    for dirpath, _dirnames, filenames in os.walk(ASSETS_DIR):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, DOCS_DIR)
            with open(full, encoding="utf-8") as fh:
                lines = fh.readlines()
            if name.endswith(".css"):
                for lineno, line in enumerate(lines, 1):
                    for m in _CSS_URL_RE.finditer(line):
                        if is_local_ref(m.group(2)):
                            problems.append(
                                f"{rel}:{lineno}: {m.group(0)!r} - a local url() "
                                f"reference that a flat, single-directory deploy "
                                f"cannot satisfy")
            elif name.endswith(".js"):
                for lineno, line in enumerate(lines, 1):
                    for m in _JS_LOCAL_PATH_STR_RE.finditer(line):
                        problems.append(
                            f"{rel}:{lineno}: {m.group(0)!r} - a hardcoded "
                            f"assets/... or data/... path string that a flat, "
                            f"single-directory deploy cannot satisfy")
    return problems


def find_basename_collisions(site_files: list[str]) -> dict[str, list[str]]:
    by_base: dict[str, list[str]] = {}
    for rel in site_files:
        by_base.setdefault(os.path.basename(rel), []).append(rel)
    return {base: rels for base, rels in by_base.items() if len(rels) > 1}


def check_flatten_safety(site_files: list[str]) -> None:
    """Refuse rather than guess if flattening would be unsafe. Called before
    any files are written."""
    collisions = find_basename_collisions(site_files)
    if collisions:
        detail = "\n".join(f"  {base}: {', '.join(sorted(rels))}"
                            for base, rels in sorted(collisions.items()))
        raise SystemExit(
            "Refusing --flat deploy: these files would collide onto the same flat "
            "filename, and one would silently overwrite the other:\n" + detail +
            "\nRename one of each pair (or otherwise fix the build) before using --flat.")

    hazards = scan_flatten_hazards()
    if hazards:
        raise SystemExit(
            "Refusing --flat deploy: found reference(s) outside index.html that assume "
            "the assets/ and data/ subdirectories exist, so a flattened build would be "
            "broken in a way that is not obvious from looking at it:\n" +
            "\n".join(f"  {p}" for p in hazards) +
            "\nFix these (or revisit publish.py's --flat support if they are "
            "intentional) before deploying flat.")


# Bare filenames that only ever appear at the top level in a *flat* deploy -
# used to spot a stale flat layout sitting where a normal deploy is about to
# add assets/ and data/ subdirectories alongside it (and vice versa: a stale
# assets/ or data/ subdirectory sitting where a flat deploy is about to add
# bare files). Deliberately excludes index.html and README.md, which are
# top-level in both layouts and so are not evidence of either one.
FLAT_MARKER_BASENAMES = sorted({
    os.path.basename(rel) for rel in
    ["assets/app.css", "assets/charts.css", "assets/globe.css",
     "assets/js/util.js", "assets/js/charts.js", "assets/js/globe.js", "assets/js/app.js",
     "data/hf-lows.js", "data/coastlines.js", "data/currents.js", "data/hf-lows.json"]
})


def detect_mixed_layout(target: str, flat: bool) -> list[str]:
    """Warn (never silently) when TARGET shows evidence of the *other*
    layout - files this run will not remove and that could otherwise linger
    and still be served."""
    warnings = []
    nested_dirs = [d for d in ("assets", "data") if os.path.isdir(os.path.join(target, d))]
    flat_files = [b for b in FLAT_MARKER_BASENAMES if os.path.isfile(os.path.join(target, b))]

    if flat and nested_dirs:
        warnings.append(
            "target already has " + " and ".join(f"{d}/" for d in nested_dirs) +
            " from what looks like a normal (non-flat) deploy. This --flat run will "
            "only remove files it can match to a previous flat deploy's manifest here; "
            "if this target was never deployed flat before, those subdirectories (and "
            "everything in them) will be left behind and could still be reachable on "
            "the server. Remove them by hand, or use a dedicated target directory for "
            "the flat deploy.")
    if not flat and flat_files:
        warnings.append(
            "target already has flat-layout file(s) at the top level: " +
            ", ".join(flat_files) + " - from what looks like a previous --flat deploy. "
            "This normal deploy will add assets/ and data/ subdirectories alongside "
            "them; the new index.html will not reference the old flat copies, but they "
            "will remain on disk unless this tool's manifest already tracks them. "
            "Remove them by hand, or keep using --flat for this target.")
    return warnings


def deploy(target: str, flat: bool = False) -> None:
    target = validate_deploy_target(target)
    parent = os.path.dirname(target)

    site_files = sorted(iter_site_files())

    if flat:
        # Re-verify the assumption that makes flattening safe, every time -
        # do not just trust that it still holds because it did last time.
        check_flatten_safety(site_files)
        dest_of = {rel: os.path.basename(rel) for rel in site_files}
    else:
        dest_of = {rel: rel for rel in site_files}
    dest_files = sorted(set(dest_of.values()))

    manifest_path = os.path.join(target, MANIFEST_NAME)
    previous_manifest = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                previous_manifest = json.load(fh).get("files", [])
        except (OSError, ValueError):
            previous_manifest = []          # treat an unreadable manifest as "unknown"

    # Stage the whole new tree in a sibling directory on the same filesystem,
    # starting from a copy of what's there now so anything the site doesn't
    # own (other files someone put in the web root) survives untouched.
    staging = tempfile.mkdtemp(dir=parent, prefix=".publish-staging-")
    try:
        if os.listdir(target):
            shutil.copytree(target, staging, dirs_exist_ok=True)

        # Drop files this tool deployed previously but the new build no
        # longer produces (including, when switching --flat on or off
        # against a target this tool has deployed to before, everything the
        # previous layout put there) so removed pages/assets don't linger.
        stale = sorted(set(previous_manifest) - set(dest_files))
        for rel in stale:
            p = os.path.join(staging, rel)
            if os.path.isfile(p) or os.path.islink(p):
                os.remove(p)

        for rel, dest in dest_of.items():
            src = os.path.join(DOCS_DIR, rel)
            dst = os.path.join(staging, dest)
            dst_dir = os.path.dirname(dst)
            if dst_dir:
                os.makedirs(dst_dir, exist_ok=True)
            if flat and rel == "index.html":
                # The one file that carries path references - rewrite them
                # to bare filenames rather than byte-copying.
                with open(src, encoding="utf-8") as fh:
                    html = flatten_html(fh.read())
                with open(dst, "w", encoding="utf-8") as fh:
                    fh.write(html)
            else:
                shutil.copy2(src, dst)

        with open(os.path.join(staging, MANIFEST_NAME), "w", encoding="utf-8") as fh:
            json.dump({"files": dest_files, "flat": flat}, fh)

        # The swap itself: move the live directory aside, move staging into
        # its place, then discard the old one. Two renames back-to-back, with
        # no copying in between, is as close to atomic as stdlib gets for a
        # whole directory - there is no window where TARGET is half-written.
        backup = target + ".prev-" + os.path.basename(staging)
        os.rename(target, backup)
        try:
            os.rename(staging, target)
        except BaseException:
            os.rename(backup, target)       # put the working site back
            raise
        shutil.rmtree(backup)
    except BaseException:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
        raise

    total_size = sum(os.path.getsize(os.path.join(target, dest)) for dest in dest_files)
    layout = "flat" if flat else "directory"
    print(f"Deployed {len(dest_files)} files ({total_size / 1024:.0f} KB) to {target} "
          f"({layout} layout)")
    if stale:
        print(f"Removed {len(stale)} stale file(s) no longer produced by the build:")
        for rel in stale:
            print(f"  - {rel}")
    print("Anything else already in that directory was left alone.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="publish.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-fetch", action="store_true",
                     help="skip fetching from the sheet; build from the CSVs already in "
                          "data/hf_lows/ (this is the normal path when you export the tabs "
                          "by hand, or before the Apps Script endpoint is set up)")
    ap.add_argument("--deploy", metavar="PATH",
                     help="after building and reporting the delta, copy docs/ into this "
                          "existing web-root directory")
    ap.add_argument("--flat", action="store_true",
                     help="with --deploy, write every file directly into the target "
                          "directory instead of recreating docs/'s assets/ and data/ "
                          "subdirectories, and rewrite index.html's local src=/href= "
                          "references to match. Use this when the target is reached "
                          "through a web UI that can only upload individual files into "
                          "one folder, not whole directories.")
    ap.add_argument("--yes", action="store_true",
                     help="with --deploy, skip the confirmation prompt (for cron; without "
                          "it a human has to type y first)")
    args = ap.parse_args()

    if args.flat and args.deploy is None:
        ap.error("--flat only makes sense together with --deploy")

    if not args.no_fetch:
        do_fetch()
        data_source = "fetched"
    else:
        print("Skipping fetch (--no-fetch); building from the CSVs already on disk.")
        data_source = "local"

    old_payload = load_published_payload()
    new_payload = run_build(data_source=data_source)
    counts = new_payload["qc"]["counts"]
    print(f"\nBuilt: lows {counts.get('lows', 0)}  fixes {counts.get('fixes', 0)}  "
          f"seasons {len(new_payload['seasons'])}\n")
    print_delta(old_payload, new_payload)

    if args.deploy is None:
        return 0

    # Validate before asking for confirmation - a human should never be
    # prompted to approve a deploy that was always going to be refused.
    target = validate_deploy_target(args.deploy)
    if args.flat:
        # Same principle: a doomed --flat deploy is refused before the
        # confirmation prompt, not after someone has typed y.
        check_flatten_safety(sorted(iter_site_files()))

    for warning in detect_mixed_layout(target, args.flat):
        print(f"\nWARNING: {warning}")

    print()
    mode = "flat, single-directory" if args.flat else "docs/"
    if not args.yes:
        reply = input(f"Deploy {mode} to {target!r}? [y/N] ").strip().lower()
        if reply != "y":
            print("Not deploying.")
            return 0

    deploy(target, flat=args.flat)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
