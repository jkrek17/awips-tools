#!/usr/bin/env python3
"""Fetch and cache OPC High Seas Forecast text products from the Iowa State IEM archive.

Why this exists: the hurricane-force archive records each storm's HF segment and
almost nothing before it, so the deepening that precedes hurricane-force winds is
not measurable from the archive itself. OPC published that missing phase 4x daily
in the High Seas Forecast (analysed low position + central pressure). This script
is stage 1 of the backfill: it only gets the raw product text onto disk, once. It
does NOT parse, deduplicate or choose between products - tools/parse_hsf.py and
the tracker do that - so a cache record is exactly what the archive served.

Source: Iowa State IEM AFOS archive, via the two endpoints it publishes for this
    list  https://mesonet.agron.iastate.edu/api/1/nws/afos/list.json?pil=<PIL>&date=YYYY-MM-DD
    text  https://mesonet.agron.iastate.edu/api/1/nwstext/<product_id>
The list endpoint takes ONE UTC day, not a month (year=/month= are rejected with
HTTP 422), so a month costs 28-31 list requests before a single product is
fetched. That shapes everything below.

Products (PIL):
    HSFAT1  North Atlantic 31-67N, W of 35W (OPC / KWBC)
    HSFEP1  North Pacific 30-67N            (OPC / KWBC)
    HSFEPI  duplicate of HSFEP1 under a different header. Cached when asked for,
            never merged with HSFEP1 here, so the parser can fall back to it.
HSFAT2 / HSFNP are NHC Miami and NWS Honolulu (tropical) and are not accepted.

Cache (gitignored): data/hsf_cache/<PIL>/<YYYY-MM>.jsonl.gz, one gzipped
JSON-Lines file per PIL-month, one record per product, in issue order:
    {"product_id": "200612100420-KWBC-FZNT01-HSFAT1",
     "issued": "2006-12-10T04:20:00Z", "text": "<the full raw product text>"}
`issued` is the IEM "entered" time of the product, not the time in its header.
Every product the listing reports is kept - amended re-issues (-RRA, -CCA ...)
and the near-duplicate transmissions the archive holds a few minutes apart are
separate records, because deciding which one is authoritative is the parser's job.

Beside each month file sits <YYYY-MM>.listing.json, the product ids the archive
listed for each day. It is what makes a re-run free: without it "does this month
hold everything the listing reports?" could only be answered by re-listing ~30
days per PIL-month, i.e. ~17 000 requests to confirm a finished 24-year cache.
Only the *.jsonl.gz files are cache records; the sidecar is bookkeeping.

Resumable, and that is the point. A month is COMPLETE, and costs zero requests,
only when all three hold:
    * the month is wholly in the past (UTC);
    * every day of it has a recorded listing;
    * its file holds a record for every product id those listings report.
A month file that exists but is short is therefore finished, not skipped. Days
already listed are not listed again (so a run stopped by --max-requests mid-month
resumes where it left off), and neither are products already on disk. The current
month always tops up: days before today are final once listed, today is re-listed
on every run because new forecasts keep arriving. --relist forgets recorded
listings, for the rare case the archive back-fills a past month.

Things that are easy to get wrong, and are handled explicitly:

* The egress proxy in the build container resets connections intermittently
  (ConnectionResetError during the TLS handshake). Every network error is
  retried with backoff (2, 4, 8, 16 s). A request that still fails after that is
  recorded as a gap and the run moves on, so one bad product cannot end a
  24-year run; only FETCH_ABORT_AFTER consecutive exhausted requests (the
  network is plainly down, not glitching) stops it. A 4xx other than 408/429 is a
  refusal, not a glitch, and is not repeated.
* A cache file is only ever replaced whole (temp file + rename), never appended
  to: a kill mid-write would otherwise leave a truncated gzip member that every
  later run has to guess around. A truncated file from some other cause is read
  as far as it goes, with a warning, and topped up.
* Requests are serialised with a pause between them, and are counted against
  --max-requests so a run can be done in chunks. Months are visited in time
  order and PILs are interleaved within a month, so a capped chunk advances all
  requested products evenly rather than finishing one PIL first.
* Gaps stay visible. The closing table is read back from disk, not from this
  run's counters, so it reports what is actually cached vs what the archive
  listed, per year, whether or not this run fetched anything.

Exit status: 0 on success (including a run stopped by --max-requests, which is
progress); 1 if any day could not be listed, or the run was aborted by the
network; 2 if listings were fine but some listed products could not be fetched.
A re-run retries the gaps.

Usage:
    python3 tools/fetch_hsf.py --dry-run                              # read the cache, no network: what a run would cost
    python3 tools/fetch_hsf.py --pil HSFAT1 --start 2006-12 --end 2006-12 --max-requests 300
    python3 tools/fetch_hsf.py --max-requests 5000                    # a chunk of the full 2002-01..now run
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import gzip
import http.client
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data", "hsf_cache")

LIST_URL = "https://mesonet.agron.iastate.edu/api/1/nws/afos/list.json?pil={pil}&date={date}"
TEXT_URL = "https://mesonet.agron.iastate.edu/api/1/nwstext/{pid}"

# The client is named honestly; the archive operator can see who is asking and why.
USER_AGENT = "awips-tools hf-low-archive (+https://github.com/jkrek17/awips-tools) python-urllib"

# HSFEPI is accepted so the parser can fall back to it when HSFEP1 is missing for a
# synoptic time. It is never merged with HSFEP1 here.
PILS = ("HSFAT1", "HSFEP1", "HSFEPI")
DEFAULT_PILS = ("HSFAT1", "HSFEP1")
DEFAULT_START = "2002-01"

DEFAULT_DELAY_S = 0.3          # pause between requests; the archive is a free public service
FETCH_TIMEOUT_S = 60
# Pauses before retries 1..4. Four waits means up to five attempts on one request.
BACKOFF_S = (2, 4, 8, 16)
# 408/429 are the server asking us to slow down, not refusing; everything else in
# 4xx is a refusal and repeating it only adds load.
RETRYABLE_4XX = (408, 429)
# Consecutive requests that exhausted every retry before the run gives up. A proxy
# that resets one connection in ten never gets near this; a dead one gets there in
# a few minutes instead of burning 30 s of backoff per product for hours.
FETCH_ABORT_AFTER = 5

FLUSH_EVERY = 25               # products between whole-file rewrites of the month cache

# Only used to price a --dry-run on months not yet listed: observed ~4.5 products per
# PIL-day (4 synoptic issues plus amendments and near-duplicate transmissions).
EST_PRODUCTS_PER_DAY = 4.5
EST_LATENCY_S = 0.3            # observed round trip per request through the proxy

_YM_RE = re.compile(r"^(\d{4})-(\d{2})$")
_ISSUED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class CapReached(Exception):
    """--max-requests spent. Not an error: the run stops cleanly and can be resumed."""


class RunAborted(Exception):
    """The network is down for good (FETCH_ABORT_AFTER exhausted requests in a row)."""


class FetchError(Exception):
    """One request failed for good (retries exhausted, or a refusal)."""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

class Fetcher:
    """Serialised, throttled, retrying HTTP GET. One instance per run: it owns the
    request budget and the clock the pause is measured against."""

    def __init__(self, delay: float, max_requests: int | None):
        self.delay = delay
        self.max_requests = max_requests
        self.requests = 0          # logical requests, what --max-requests caps
        self.attempts = 0          # wire attempts including retries
        self.retries = 0
        self.failed = 0            # requests that exhausted their retries
        self.bytes = 0
        self._last_end = None
        self._consecutive_failed = 0
        self._ctx = ssl.create_default_context()

    def _pause(self):
        if self._last_end is not None:
            wait = self.delay - (time.monotonic() - self._last_end)
            if wait > 0:
                time.sleep(wait)

    def _once(self, url: str) -> bytes:
        self._pause()
        self.attempts += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, context=self._ctx, timeout=FETCH_TIMEOUT_S) as resp:
                return resp.read()
        finally:
            self._last_end = time.monotonic()

    def get(self, url: str) -> bytes:
        if self.max_requests is not None and self.requests >= self.max_requests:
            raise CapReached()
        self.requests += 1
        last_err = None
        for attempt in range(len(BACKOFF_S) + 1):
            try:
                body = self._once(url)
                self._consecutive_failed = 0
                self.bytes += len(body)
                return body
            except urllib.error.HTTPError as err:
                if 400 <= err.code < 500 and err.code not in RETRYABLE_4XX:
                    self._consecutive_failed = 0          # the server answered; the network is fine
                    raise FetchError(f"HTTP {err.code} {err.reason}") from err
                last_err = err
            # URLError wraps the TLS-handshake reset; a reset after the response has
            # started (or a short body) surfaces as ConnectionError / HTTPException
            # instead, so all of them are the same transient failure.
            except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError,
                    http.client.HTTPException, ssl.SSLError, OSError) as err:
                last_err = err
            if attempt == len(BACKOFF_S):
                break
            wait = BACKOFF_S[attempt]
            self.retries += 1
            print(f"    {type(last_err).__name__}: {last_err} - retry {attempt + 1}/{len(BACKOFF_S)} in {wait}s",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
        self.failed += 1
        self._consecutive_failed += 1
        if self._consecutive_failed >= FETCH_ABORT_AFTER:
            raise RunAborted(f"{self._consecutive_failed} requests in a row failed after "
                             f"{len(BACKOFF_S)} retries each (last: {last_err})")
        raise FetchError(f"gave up after {len(BACKOFF_S) + 1} attempts: {type(last_err).__name__}: {last_err}")


def parse_listing(raw: bytes, pil: str, day: dt.date):
    """List endpoint body -> [(product_id, issued)] in listing order. A body that is
    not the expected JSON raises ValueError, which the caller treats as a failed
    (retryable-on-next-run) listing rather than as 'no products' - an empty day and
    a truncated response must never look alike."""
    obj = json.loads(raw.decode("utf-8"))
    rows = obj["data"]
    out = []
    for r in rows:
        pid, issued = r["product_id"], r["entered"]
        if r.get("pil") not in (None, pil):
            raise ValueError(f"listing for {pil} {day} returned a {r.get('pil')} product: {pid}")
        if not _ISSUED_RE.match(issued):
            raise ValueError(f"unexpected 'entered' value {issued!r} for {pid}")
        out.append((pid, issued))
    return out


# ---------------------------------------------------------------------------
# Cache files
# ---------------------------------------------------------------------------

def month_path(cache_dir: str, pil: str, ym: str) -> str:
    return os.path.join(cache_dir, pil, f"{ym}.jsonl.gz")


def listing_path(cache_dir: str, pil: str, ym: str) -> str:
    return os.path.join(cache_dir, pil, f"{ym}.listing.json")


def atomic_write(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def read_month(path: str) -> dict:
    """{product_id: record} for a month file; {} if absent. Reads as far as the file
    is intact and warns about the rest, so a damaged file is topped up, not fatal."""
    recs = {}
    if not os.path.exists(path):
        return recs
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    recs[r["product_id"]] = {"product_id": r["product_id"], "issued": r["issued"], "text": r["text"]}
                except (ValueError, KeyError):
                    print(f"  warning: {path} line {lineno} unreadable - dropped, will be re-fetched",
                          file=sys.stderr)
    except (EOFError, OSError) as err:
        print(f"  warning: {path} damaged after {len(recs)} records ({err}) - the rest will be re-fetched",
              file=sys.stderr)
    return recs


def write_month(path: str, recs: dict):
    ordered = sorted(recs.values(), key=lambda r: (r["issued"], r["product_id"]))
    body = "".join(json.dumps({"product_id": r["product_id"], "issued": r["issued"], "text": r["text"]},
                              ensure_ascii=False, separators=(",", ":")) + "\n" for r in ordered)
    # mtime=0 so identical content gives an identical file; a re-run that changes
    # nothing does not churn the cache.
    atomic_write(path, gzip.compress(body.encode("utf-8"), compresslevel=9, mtime=0))


def read_listing(path: str) -> dict:
    """{'YYYY-MM-DD': [product_id, ...]} for the days already listed; {} if none."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)["days"]
    except FileNotFoundError:
        return {}
    except (ValueError, KeyError, OSError) as err:
        print(f"  warning: {path} unreadable ({err}) - month will be re-listed", file=sys.stderr)
        return {}


def write_listing(path: str, pil: str, ym: str, days: dict):
    obj = {"pil": pil, "month": ym, "days": {d: days[d] for d in sorted(days)}}
    atomic_write(path, (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# Month logic
# ---------------------------------------------------------------------------

def today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def month_days(ym: str):
    y, m = int(ym[:4]), int(ym[5:])
    return [dt.date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def month_range(start: str, end: str):
    y, m = int(start[:4]), int(start[5:])
    ey, em = int(end[:4]), int(end[5:])
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def final_days(ym: str, today: dt.date):
    """Days of the month whose listing can no longer change: strictly before today."""
    return [d for d in month_days(ym) if d < today]


def listed_ids(days: dict):
    return {pid for ids in days.values() for pid in ids}


def month_state(cache_dir: str, pil: str, ym: str, today: dt.date, relist: bool = False):
    """What is on disk for a PIL-month, and what is still owed.
    Returns dict: recs, days (recorded listings), todo_days (days to list this run),
    missing (listed ids with no record), complete (nothing owed, zero requests)."""
    recs = read_month(month_path(cache_dir, pil, ym))
    days = {} if relist else read_listing(listing_path(cache_dir, pil, ym))
    # today is never trusted from a recorded listing: forecasts are still arriving.
    days = {d: ids for d, ids in days.items() if d < today.isoformat()}
    wanted = [d for d in month_days(ym) if d <= today]
    todo_days = [d for d in wanted if d.isoformat() not in days]
    missing = sorted(listed_ids(days) - set(recs))
    past = month_days(ym)[-1] < today
    complete = past and not todo_days and not missing and os.path.exists(month_path(cache_dir, pil, ym))
    return {"recs": recs, "days": days, "todo_days": todo_days, "missing": missing,
            "complete": complete, "past": past}


class RunStats:
    def __init__(self):
        self.list_failed = []      # (pil, 'YYYY-MM-DD')
        self.text_failed = []      # (pil, product_id)
        self.fetched = 0           # products written this run
        self.skipped_complete = 0  # PIL-months that cost nothing
        self.capped = False
        self.aborted = None


def fetch_month(fetcher: Fetcher, cache_dir: str, pil: str, ym: str, today: dt.date,
                relist: bool, stats: RunStats):
    st = month_state(cache_dir, pil, ym, today, relist)
    if st["complete"]:
        stats.skipped_complete += 1
        print(f"{ym} {pil}  complete ({len(st['recs'])} products) - skipped")
        return
    mpath, lpath = month_path(cache_dir, pil, ym), listing_path(cache_dir, pil, ym)
    recs, days = st["recs"], st["days"]
    had, req0 = len(recs), fetcher.requests
    issued_of = {}             # id -> archive "entered" time, for ids listed this run
    listed_today = {}          # today's listing: used this run, deliberately not recorded
    list_gaps = text_gaps = since_flush = 0
    dirty_listing = dirty_recs = False
    capped = False
    try:
        for day in st["todo_days"]:
            iso = day.isoformat()
            try:
                rows = parse_listing(fetcher.get(LIST_URL.format(pil=pil, date=iso)), pil, day)
            except (FetchError, ValueError, KeyError, TypeError) as err:
                list_gaps += 1
                stats.list_failed.append((pil, iso))
                print(f"  could not list {pil} {iso}: {err}", file=sys.stderr)
                continue
            issued_of.update(rows)
            ids = [pid for pid, _ in rows]
            if day < today:
                days[iso] = ids
                dirty_listing = True
            else:
                listed_today[iso] = ids
        # Flush the listing before spending the (much larger) text budget: if the
        # run dies in the text phase, the listing work is not repeated.
        if dirty_listing:
            write_listing(lpath, pil, ym, days)
            dirty_listing = False
        want, seen = [], set(recs)
        for d in sorted(list(days) + list(listed_today)):
            for pid in days.get(d) or listed_today.get(d) or ():
                if pid not in seen:
                    seen.add(pid)
                    want.append(pid)
        for pid in want:
            try:
                text = fetcher.get(TEXT_URL.format(pid=pid)).decode("utf-8", errors="replace")
                if not text.strip():
                    raise FetchError("empty body")
            except FetchError as err:
                text_gaps += 1
                stats.text_failed.append((pil, pid))
                print(f"  could not fetch {pid}: {err}", file=sys.stderr)
                continue
            # Ids listed on an earlier run have no `entered` in memory; the leading
            # 12 digits of the id are the same instant.
            recs[pid] = {"product_id": pid, "issued": issued_of.get(pid) or issued_from_id(pid), "text": text}
            stats.fetched += 1
            dirty_recs = True
            since_flush += 1
            if since_flush >= FLUSH_EVERY:
                write_month(mpath, recs)
                dirty_recs, since_flush = False, 0
    except CapReached:
        capped = True
    finally:
        # Reached on cap, on abort, on Ctrl-C and on a normal exit alike: whatever
        # was fetched is on disk before the exception continues.
        if dirty_listing:
            write_listing(lpath, pil, ym, days)
        # A month with no products still gets its (empty) file, so "file exists"
        # always means "this month was looked at".
        if dirty_recs or not os.path.exists(mpath):
            write_month(mpath, recs)
    print(f"{ym} {pil}  listed {len(listed_ids(days)) + len(listed_ids(listed_today))} products, "
          f"cached {had} -> {len(recs)}, {fetcher.requests - req0} requests"
          + (f", {list_gaps} day(s) unlisted" if list_gaps else "")
          + (f", {text_gaps} product(s) failed" if text_gaps else "")
          + (", STOPPED at request cap" if capped else ""), flush=True)
    if capped:
        raise CapReached()


def issued_from_id(pid: str) -> str:
    """YYYYMMDDHHMM-... -> 'YYYY-MM-DDTHH:MM:00Z'. Fallback only, for products whose
    listing was recorded on an earlier run."""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})-", pid)
    if not m:
        raise FetchError(f"cannot derive an issue time from product id {pid!r}")
    return "{}-{}-{}T{}:{}:00Z".format(*m.groups())


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def disk_report(cache_dir: str, pils, months, today: dt.date):
    """Per (pil, year): months, listed, cached, missing, unlisted days, bytes - read
    from disk, so it is true whether or not this run fetched anything."""
    rows = defaultdict(lambda: {"months": 0, "listed": 0, "cached": 0, "missing": 0, "unlisted": 0, "bytes": 0})
    for pil in pils:
        for ym in months:
            st = month_state(cache_dir, pil, ym, today)
            r = rows[(pil, int(ym[:4]))]
            r["months"] += 1
            ids = listed_ids(st["days"])
            r["listed"] += len(ids)
            r["cached"] += len(ids & set(st["recs"]))
            r["missing"] += len(st["missing"])
            r["unlisted"] += len([d for d in final_days(ym, today) if d.isoformat() not in st["days"]])
            for p in (month_path(cache_dir, pil, ym), listing_path(cache_dir, pil, ym)):
                if os.path.exists(p):
                    r["bytes"] += os.path.getsize(p)
    return rows


def print_report(rows):
    print()
    print(f"{'PIL':7s} {'year':>4s} {'months':>6s} {'listed':>7s} {'cached':>7s} {'missing':>7s} "
          f"{'unlisted days':>13s} {'MB':>7s}")
    tot = defaultdict(int)
    for (pil, year) in sorted(rows):
        r = rows[(pil, year)]
        flag = "  <-- gaps" if r["missing"] or r["unlisted"] else ""
        print(f"{pil:7s} {year:4d} {r['months']:6d} {r['listed']:7d} {r['cached']:7d} {r['missing']:7d} "
              f"{r['unlisted']:13d} {r['bytes'] / 1e6:7.2f}{flag}")
        for k in r:
            tot[k] += r[k]
    print(f"{'total':12s} {tot['months']:6d} {tot['listed']:7d} {tot['cached']:7d} {tot['missing']:7d} "
          f"{tot['unlisted']:13d} {tot['bytes'] / 1e6:7.2f}")
    if tot["unlisted"]:
        print("'unlisted days' are days never listed (so their products are not even counted in 'listed'); "
              "'missing' are listed products not yet cached.")


def dry_run(cache_dir: str, pils, months, today: dt.date, delay: float, relist: bool):
    """No network. Prices the run from what the cache already holds."""
    n_complete = n_open = list_req = text_req = 0
    est_days = est_prod = 0
    for ym in months:
        for pil in pils:
            st = month_state(cache_dir, pil, ym, today, relist)
            if st["complete"]:
                n_complete += 1
                continue
            n_open += 1
            list_req += len(st["todo_days"])
            text_req += len(st["missing"])
            est_days += len(st["todo_days"])
            print(f"{ym} {pil}  would fetch: {len(st['todo_days'])} day listing(s), "
                  f"{len(st['missing'])} known product(s) missing, {len(st['recs'])} cached")
    est_prod = int(est_days * EST_PRODUCTS_PER_DAY)
    total = list_req + text_req + est_prod
    secs = total * (delay + EST_LATENCY_S)
    print()
    print(f"{n_complete} PIL-month(s) complete (zero requests), {n_open} would be worked on.")
    print(f"requests: {list_req} listings + {text_req} known products + ~{est_prod} products in "
          f"not-yet-listed days (est. {EST_PRODUCTS_PER_DAY}/day) = ~{total}")
    print(f"at --delay {delay:g}s plus ~{EST_LATENCY_S}s round trip: ~{secs / 3600:.1f} h")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_ym(s: str) -> str:
    m = _YM_RE.match(s)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise argparse.ArgumentTypeError(f"{s!r} is not YYYY-MM")
    return s


def parse_pils(s: str):
    out = []
    for p in s.upper().split(","):
        p = p.strip()
        if p not in PILS:
            raise argparse.ArgumentTypeError(f"unknown PIL {p!r}; this tool fetches {', '.join(PILS)}")
        if p not in out:
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pil", type=parse_pils, default=list(DEFAULT_PILS), metavar="HSFAT1,HSFEP1",
                    help=f"comma-separated products (default {','.join(DEFAULT_PILS)}; "
                         f"HSFEPI is accepted as the Pacific fallback)")
    ap.add_argument("--start", type=parse_ym, default=DEFAULT_START, metavar="YYYY-MM",
                    help=f"first month (default {DEFAULT_START})")
    ap.add_argument("--end", type=parse_ym, default=None, metavar="YYYY-MM",
                    help="last month (default: the current month)")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_S, metavar="SECONDS",
                    help=f"pause between requests (default {DEFAULT_DELAY_S})")
    ap.add_argument("--max-requests", type=int, default=None, metavar="N",
                    help="stop cleanly after N requests (listings + products), to run in chunks")
    ap.add_argument("--dry-run", action="store_true",
                    help="no network: read the cache and report what a run would fetch")
    ap.add_argument("--relist", action="store_true",
                    help="ignore recorded listings and list every day again")
    ap.add_argument("--cache-dir", default=CACHE_DIR, metavar="DIR", help=argparse.SUPPRESS)
    args = ap.parse_args()

    today = today_utc()
    this_month = today.strftime("%Y-%m")
    end = args.end or this_month
    if end > this_month:
        end = this_month
    if args.start > end:
        ap.error(f"--start {args.start} is after --end {end}")
    if args.delay < 0 or (args.max_requests is not None and args.max_requests < 0):
        ap.error("--delay and --max-requests must not be negative")
    months = list(month_range(args.start, end))

    print(f"{', '.join(args.pil)}  {args.start}..{end}  ({len(months)} months)  cache {os.path.relpath(args.cache_dir, ROOT)}"
          + ("  [dry run: no network]" if args.dry_run else ""))
    if args.dry_run:
        dry_run(args.cache_dir, args.pil, months, today, args.delay, args.relist)
        print_report(disk_report(args.cache_dir, args.pil, months, today))
        return 0

    fetcher = Fetcher(args.delay, args.max_requests)
    stats = RunStats()
    t0 = time.monotonic()
    try:
        for ym in months:
            for pil in args.pil:
                fetch_month(fetcher, args.cache_dir, pil, ym, today, args.relist, stats)
    except CapReached:
        print(f"stopped at --max-requests {args.max_requests}; re-run to continue where this left off")
    except RunAborted as err:
        stats.aborted = str(err)
        print(f"ABORTED: {err}", file=sys.stderr)
    except KeyboardInterrupt:
        stats.aborted = "interrupted"
        print("interrupted - everything fetched so far is on disk", file=sys.stderr)

    elapsed = time.monotonic() - t0
    print()
    print(f"run: {fetcher.requests} requests ({fetcher.attempts} attempts, {fetcher.retries} retries, "
          f"{fetcher.failed} failed), {stats.fetched} products fetched, {fetcher.bytes / 1e6:.2f} MB received, "
          f"{stats.skipped_complete} PIL-months already complete, {elapsed:.0f} s")
    print_report(disk_report(args.cache_dir, args.pil, months, today))

    if stats.list_failed:
        by_month = defaultdict(list)
        for pil, iso in stats.list_failed:
            by_month[(pil, iso[:7])].append(iso[8:])
        print("\nCOULD NOT LIST:", file=sys.stderr)
        for (pil, ym), ds in sorted(by_month.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            print(f"  {pil} {ym}: day(s) {','.join(ds)}", file=sys.stderr)
    if stats.text_failed:
        print(f"\n{len(stats.text_failed)} listed product(s) could not be fetched (retried on the next run), e.g. "
              f"{stats.text_failed[0][1]}", file=sys.stderr)
    if stats.list_failed or stats.aborted:
        return 1
    if stats.text_failed:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
