#!/usr/bin/env python3
"""Fetch and cache OPC High Seas Forecast text products from the Iowa State IEM archive.

Why this exists: the hurricane-force archive records each storm's HF segment and
almost nothing before it, so the deepening that precedes hurricane-force winds is
not measurable from the archive itself. OPC published that missing phase 4x daily
in the High Seas Forecast (analysed low position + central pressure). This script
is stage 1 of the backfill: it only gets the raw product text onto disk, once. It
does NOT parse, deduplicate or choose between products - tools/parse_hsf.py does
that - so a cache record is exactly what the archive served.

Source: the Iowa State IEM AFOS bulk endpoint behind its public AFOS form
    https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py
        ?pil=<PIL>&sdate=<from>&edate=<until>&limit=100&order=asc&fmt=zip
One request returns up to 100 whole products. The whole 2002-now record of both
Pacific/Atlantic products is therefore ~800 requests, not the ~100 000 that a
list-then-fetch-each walk of the per-product API needs - the reason this tool
exists in this form, since the archive is a free university service.

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
Every product the archive holds is kept: amended re-issues (-RRA, -CCA ...), the
near-duplicate transmissions a few minutes apart, and early products that bundle
several bulletins in one transmission (HSFAT1 in 2002 averages ~63 KB per
product, ~10x later years). They are cached as transmitted; telling them apart
is the parser's job.

Why the zip format, not the plain-text one: fmt=text frames each product with
SOH/ETX but carries NO product id and NO issue time - and the WMO header time
inside the text is not the archive's entry time (in 2015 it differs from it by
up to ~50 minutes for 40% of products). Without the entry time there is nothing
to put in `issued` and nothing to move the cursor on. fmt=zip carries the same
bytes, one member per product, named <PIL>_<YYYYMMDDHHMM>.txt: that minute is
`issued`, and is exactly the leading 12 digits of the archive's own product id.
The rest of the id is rebuilt from the product's own WMO header line
("FZNT01 KWBC 100501 RRA" -> KWBC-FZNT01-HSFAT1-RRA); checked on 3 months of
real data it matched the archive's id for all but one product in ~1000 (the
archive filed it without the -CCB its header carries). Member text is
byte-identical to what the per-product API serves.

Paging is by cursor, not by day. A page is asked for from the cursor to the end
of the span, oldest first; the next cursor is the entry minute of the last
product returned. `sdate` is inclusive and takes a minute (2006-12-10T04:23Z), so
the next page repeats only the products filed in that last minute; they are
recognised and dropped. A page of fewer than 100 products means the span is
exhausted - that, not a probe, is how a finished span is known - and a full page
continues. `edate` is exclusive (sdate == edate returns nothing), so the span ends
at the first of the month after --end, or tomorrow for the current month.

Resumable, and that is the point. Where to resume is read from the cache: the
cursor starts at the newest product in the last month of the contiguous run of
COMPLETE month files that begins at --start. Re-running over a finished span
therefore costs ONE short page per PIL that confirms nothing is newer, and the
current month tops up the same way. Months are buffered and written once the
cursor has left them, and a file is only ever replaced whole (temp file +
rename), never appended to. A month with no products still gets an empty file, so
"file exists" means "looked at".

The one thing a file's existence cannot say is "and it is finished". When a run
stops mid-month (--max-requests, an unrecoverable page, Ctrl-C) the buffered
products are flushed so nothing fetched is lost, and that month gets a
<YYYY-MM>.partial marker beside it; the contiguous run ends there, so the next run
resumes inside it even if later months already exist (a smaller earlier run).
The marker is removed when the cursor leaves the month. It is bookkeeping, not a
cache record, and does not match *.jsonl.gz.

What reading the cache instead of keeping a per-day listing costs: a month damaged
or emptied in the MIDDLE of an otherwise complete cache is not noticed. --rescan
walks from --start regardless (~800 requests; products already held are
recognised and kept) and fills it. A file truncated at its end is completed by an
ordinary run.

Things that are easy to get wrong, and are handled explicitly:

* Same-minute products can share an id. The archive holds two different
  transmissions both filed at 2024-01-01T10:30 under one id (they differ only in
  the LDM sequence number on line 1), while its per-product API serves just one of
  them. Both are kept: a record is a duplicate only if id AND text match.
* Truncated or corrupt pages. The zip's own directory and per-member CRC are the
  framing check (a cut-off body fails to open), plus: every member name must match
  the PIL, and a page may not exceed the 100-product limit. Any of these is
  treated like a network error: retried with backoff, never half-trusted. An empty
  span is a valid empty zip (or the text "ERROR: Could not Find: <PIL>"); nothing
  else is accepted as empty.
* The egress proxy in the build container resets connections intermittently
  (ConnectionResetError during the TLS handshake). Every network error is retried
  (waits of 2, 4, 8, 16 s). A page that still fails is a gap: that PIL stops
  there - the cursor cannot skip a page - and the next PIL continues. Only
  FETCH_ABORT_AFTER consecutive exhausted requests (network plainly down) end the
  run. A 4xx other than 408/429 is a refusal, not a glitch, and is not repeated.
* Requests are serialised with a pause between them and counted against
  --max-requests, so a run can be done in chunks.
* Gaps stay visible. The closing table is read back from disk, per year: products,
  mean product size, months not yet fetched, and months that look thin (fewer than
  ~3 products per day, against the ~4.5 normal).

Exit status: 0 on success (including a run stopped by --max-requests, which is
progress); 1 if a span could not be fetched to its end, or the run was aborted by
the network; 2 if every fetch succeeded but some product had no recognisable WMO
header (cached anyway, under a placeholder id). A re-run retries the gaps.

Usage:
    python3 tools/fetch_hsf.py --dry-run                              # read the cache, no network: what a run would cost
    python3 tools/fetch_hsf.py --pil HSFAT1 --start 2006-12 --end 2006-12
    python3 tools/fetch_hsf.py --max-requests 200                     # a chunk of the full 2002-01..now run
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import gzip
import http.client
import io
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data", "hsf_cache")

PAGE_URL = ("https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py"
            "?pil={pil}&sdate={sdate}&edate={edate}&limit={limit}&order=asc&fmt=zip")
PAGE_LIMIT = 100               # the endpoint's maximum

# The client is named honestly; the archive operator can see who is asking and why.
USER_AGENT = "awips-tools hf-low-archive (+https://github.com/jkrek17/awips-tools) python-urllib"

# HSFEPI is accepted so the parser can fall back to it when HSFEP1 is missing for a
# synoptic time. It is never merged with HSFEP1 here.
PILS = ("HSFAT1", "HSFEP1", "HSFEPI")
DEFAULT_PILS = ("HSFAT1", "HSFEP1")
DEFAULT_START = "2002-01"

# Pages are up to several MB each and the whole run is ~800 of them, so the pause
# costs minutes; there is no reason to lean on a free public service harder.
DEFAULT_DELAY_S = 1.0
FETCH_TIMEOUT_S = 120          # a 2002 page is ~6 MB
# Pauses before retries 1..4. Four waits means up to five attempts on one request.
BACKOFF_S = (2, 4, 8, 16)
# 408/429 are the server asking us to slow down, not refusing; everything else in
# 4xx is a refusal and repeating it only adds load.
RETRYABLE_4XX = (408, 429)
# Consecutive requests that exhausted every retry before the run gives up. A proxy
# that resets one connection in ten never gets near this; a dead one gets there in
# a few minutes instead of burning minutes of backoff per page for hours.
FETCH_ABORT_AFTER = 5

# A month with fewer products per day than this looks like a gap (4 synoptic
# issues a day, plus amendments, is the norm; ~4.5 measured).
THIN_PER_DAY = 3.0

# Only used to price a --dry-run. Mean product text size measured from one page per
# PIL-year, 2002-2026: 3.6-7.4 KB everywhere EXCEPT HSFAT1 in 2002, where products
# bundle many bulletins (44-63 KB mean, one product of 4 MB). A size projection
# that missed that would be out by a factor of three.
EST_PRODUCTS_PER_DAY = 4.5
EST_KB_DEFAULT = 5.0
EST_KB_BY_PIL_YEAR = {("HSFAT1", 2002): 10.5}

_YM_RE = re.compile(r"^(\d{4})-(\d{2})$")
# "FZNT01 KWBC 100501 RRA": TTAAii, originating centre, DDHHMM, optional BBB amendment.
_WMO_RE = re.compile(r"^([A-Z]{4}\d{2}) ([A-Z]{4}) \d{6}(?: ([A-Z]{3}))?[ \t]*\r?$", re.M)
_NAME_RE = re.compile(r"^([A-Z0-9]+)_(\d{12})\.txt$")
_NOT_FOUND = re.compile(rb"^\s*ERROR: Could not Find: \w+\s*$")


class CapReached(Exception):
    """--max-requests spent. Not an error: the run stops cleanly and can be resumed."""


class RunAborted(Exception):
    """The network is down for good (FETCH_ABORT_AFTER exhausted requests in a row)."""


class FetchError(Exception):
    """One request failed for good (retries exhausted, or a refusal)."""


class BadBody(ValueError):
    """A 200 response that is not a complete, well-formed page. Retried like a
    network error: the cause is almost always a cut-off transfer."""


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

    def get(self, url: str, parse=None):
        """Body bytes, or parse(body) if given. parse raising BadBody counts as a
        transient failure and is retried with the rest."""
        if self.max_requests is not None and self.requests >= self.max_requests:
            raise CapReached()
        self.requests += 1
        last_err = None
        for attempt in range(len(BACKOFF_S) + 1):
            try:
                body = self._once(url)
                self.bytes += len(body)
                out = parse(body) if parse else body
                self._consecutive_failed = 0
                return out
            except urllib.error.HTTPError as err:
                if 400 <= err.code < 500 and err.code not in RETRYABLE_4XX:
                    self._consecutive_failed = 0          # the server answered; the network is fine
                    raise FetchError(f"HTTP {err.code} {err.reason}") from err
                last_err = err
            # URLError wraps the TLS-handshake reset; a reset after the response has
            # started (or a short body) surfaces as ConnectionError / HTTPException
            # instead, so all of them are the same transient failure.
            except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError,
                    http.client.HTTPException, ssl.SSLError, BadBody, OSError) as err:
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


def product_id(pil: str, ts: str, text: str):
    """Archive-style id from the entry minute (zip member name) and the product's own
    WMO header. Returns (id, ok); ok False means no header was found and a
    placeholder id was used (the product is still cached)."""
    m = _WMO_RE.search(text[:600])
    if not m:
        return f"{ts}-NOHDR-NOHDR-{pil}", False
    return f"{ts}-{m.group(2)}-{m.group(1)}-{pil}" + (f"-{m.group(3)}" if m.group(3) else ""), True


def parse_page(body: bytes, pil: str):
    """Page body -> [(product_id, issued, text, header_ok)] in served (time) order.
    Raises BadBody for anything that is not a complete page."""
    if not body.startswith(b"PK"):
        if _NOT_FOUND.match(body[:200]) and len(body) < 200:
            return []
        raise BadBody(f"not a zip archive ({len(body)} bytes: {body[:60]!r})")
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
        bad = z.testzip()
        if bad is not None:
            raise BadBody(f"CRC mismatch in member {bad}")
        infos = z.infolist()
        if len(infos) > PAGE_LIMIT:
            raise BadBody(f"{len(infos)} products on a page limited to {PAGE_LIMIT}")
        out = []
        for info in infos:
            m = _NAME_RE.match(info.filename)
            if not m or m.group(1) != pil:
                raise BadBody(f"unexpected member name {info.filename!r} in a {pil} page")
            ts = m.group(2)
            text = z.read(info).decode("utf-8", errors="replace")
            pid, ok = product_id(pil, ts, text)
            issued = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:]}:00Z"
            out.append((pid, issued, text, ok))
        return out
    except (zipfile.BadZipFile, zlib.error, EOFError) as err:
        raise BadBody(f"damaged zip: {err}") from err



# ---------------------------------------------------------------------------
# Cache files
# ---------------------------------------------------------------------------

def month_path(cache_dir: str, pil: str, ym: str) -> str:
    return os.path.join(cache_dir, pil, f"{ym}.jsonl.gz")


def partial_path(cache_dir: str, pil: str, ym: str) -> str:
    return os.path.join(cache_dir, pil, f"{ym}.partial")


def clear_partial(cache_dir: str, pil: str, ym: str):
    try:
        os.remove(partial_path(cache_dir, pil, ym))
    except FileNotFoundError:
        pass


def atomic_write(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def read_month(path: str) -> list:
    """Records of a month file in file order; [] if absent. Reads as far as the file
    is intact and warns about the rest, so a damaged file is topped up, not fatal."""
    recs = []
    if not os.path.exists(path):
        return recs
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    recs.append({"product_id": r["product_id"], "issued": r["issued"], "text": r["text"]})
                except (ValueError, KeyError):
                    print(f"  warning: {path} line {lineno} unreadable - dropped, will be re-fetched",
                          file=sys.stderr)
    except (EOFError, OSError) as err:
        print(f"  warning: {path} damaged after {len(recs)} records ({err}) - the rest will be re-fetched",
              file=sys.stderr)
    return recs


def write_month(path: str, recs: list):
    # Stable sort: two transmissions with the same minute and id stay in the order
    # the archive served them.
    ordered = sorted(recs, key=lambda r: (r["issued"], r["product_id"]))
    body = "".join(json.dumps({"product_id": r["product_id"], "issued": r["issued"], "text": r["text"]},
                              ensure_ascii=False, separators=(",", ":")) + "\n" for r in ordered)
    # mtime=0 so identical content gives an identical file; a re-run that changes
    # nothing does not churn the cache.
    atomic_write(path, gzip.compress(body.encode("utf-8"), compresslevel=9, mtime=0))


# ---------------------------------------------------------------------------
# Span logic
# ---------------------------------------------------------------------------

def today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def month_range(start: str, end: str):
    y, m = int(start[:4]), int(start[5:])
    ey, em = int(end[:4]), int(end[5:])
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def month_start(ym: str) -> dt.date:
    return dt.date(int(ym[:4]), int(ym[5:]), 1)


def span_end(last_ym: str, today: dt.date) -> dt.date:
    """Exclusive `edate`: the first day after the last requested month, but never past
    tomorrow - the current month tops up through today's products."""
    y, m = int(last_ym[:4]), int(last_ym[5:])
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return min(nxt, today + dt.timedelta(days=1))


def fmt_cursor(c: dt.datetime) -> str:
    return c.strftime("%Y-%m-%dT%H:%MZ")


def start_cursor(cache_dir: str, pil: str, months, rescan: bool):
    """Where to resume: the newest product of the last month in the contiguous run of
    complete month files that starts at the first requested month (a month marked
    .partial ends the run and is the one resumed). No such file -> the start
    of the span. Returns (datetime, ym of the last file counted as done or None)."""
    first = dt.datetime.combine(month_start(months[0]), dt.time())
    if rescan:
        return first, None
    last = None
    for ym in months:
        if not os.path.exists(month_path(cache_dir, pil, ym)):
            break
        last = ym
        if os.path.exists(partial_path(cache_dir, pil, ym)):
            break                      # stopped mid-month: resume inside it
    if last is None:
        return first, None
    recs = read_month(month_path(cache_dir, pil, last))
    if not recs:
        return dt.datetime.combine(month_start(last), dt.time()), last
    newest = max(r["issued"] for r in recs)
    return dt.datetime.strptime(newest, "%Y-%m-%dT%H:%M:%SZ"), last


class RunStats:
    def __init__(self):
        self.span_failed = []      # (pil, cursor string) - spans that stopped short
        self.fetched = 0           # products written this run
        self.pages = 0
        self.no_header = 0         # products cached under a placeholder id
        self.dup_dropped = 0       # cursor-overlap repeats recognised and dropped
        self.capped = False
        self.aborted = None


class MonthBuffer:
    """Months of one PIL being assembled. A month is loaded from disk the first time a
    product for it arrives, and written when the cursor has left it."""

    def __init__(self, cache_dir: str, pil: str):
        self.cache_dir, self.pil = cache_dir, pil
        self.recs = {}             # ym -> list of records
        self.keys = {}             # ym -> set of (product_id, text)
        self.touched = set()       # months with something new this run

    def _load(self, ym):
        if ym not in self.recs:
            self.recs[ym] = read_month(month_path(self.cache_dir, self.pil, ym))
            self.keys[ym] = {(r["product_id"], r["text"]) for r in self.recs[ym]}

    def add(self, pid, issued, text) -> bool:
        ym = issued[:7]
        self._load(ym)
        # A repeat only if id AND text match: two different transmissions can share
        # an id when they were filed in the same minute.
        if (pid, text) in self.keys[ym]:
            return False
        self.keys[ym].add((pid, text))
        self.recs[ym].append({"product_id": pid, "issued": issued, "text": text})
        self.touched.add(ym)
        return True

    def flush(self, before: str | None, months, finished: bool, partial_ym: str | None = None):
        """Write buffered months that are final (strictly before `before`, or all if
        None) and clear their .partial markers. With `finished`, also give every
        requested month that has no file an empty one, so 'file exists' keeps
        meaning 'looked at'. `partial_ym` is the month a stopped run was in: it is
        written (nothing fetched is lost) but marked, so the next run resumes in it."""
        for ym in sorted(self.recs):
            if before is not None and ym >= before:
                continue
            path = month_path(self.cache_dir, self.pil, ym)
            if ym == partial_ym:
                atomic_write(partial_path(self.cache_dir, self.pil, ym), b"")   # marker first: a crash
                write_month(path, self.recs[ym])                                # between the two is safe
            else:
                if ym in self.touched or not os.path.exists(path):
                    write_month(path, self.recs[ym])
                clear_partial(self.cache_dir, self.pil, ym)
            self.touched.discard(ym)
            del self.recs[ym], self.keys[ym]
        for ym in months:
            if (before is None or ym < before) and ym != partial_ym:
                if finished or before is not None:
                    clear_partial(self.cache_dir, self.pil, ym)
                path = month_path(self.cache_dir, self.pil, ym)
                if (finished or before is not None) and not os.path.exists(path):
                    write_month(path, [])


def fetch_pil(fetcher: Fetcher, cache_dir: str, pil: str, months, today: dt.date,
              rescan: bool, stats: RunStats):
    cursor, done_ym = start_cursor(cache_dir, pil, months, rescan)
    edate = span_end(months[-1], today)
    buf = MonthBuffer(cache_dir, pil)
    req0, new0 = fetcher.requests, stats.fetched
    print(f"{pil}  {months[0]}..{months[-1]}  " + ("rescanning" if rescan else "resuming") + f" from {fmt_cursor(cursor)}"
          + ("" if rescan else f" (cache holds the run up to {done_ym})" if done_ym else " (nothing cached)"), flush=True)
    finished = False
    page_no = 0
    try:
        while True:
            url = PAGE_URL.format(pil=pil, sdate=fmt_cursor(cursor), edate=edate.isoformat(), limit=PAGE_LIMIT)
            try:
                page = fetcher.get(url, lambda b: parse_page(b, pil))
            except FetchError as err:
                stats.span_failed.append((pil, fmt_cursor(cursor)))
                print(f"  could not fetch {pil} from {fmt_cursor(cursor)}: {err}", file=sys.stderr)
                break
            stats.pages += 1
            page_no += 1
            new = 0
            for pid, issued, text, ok in page:
                if buf.add(pid, issued, text):
                    new += 1
                    stats.fetched += 1
                    if not ok:
                        stats.no_header += 1
                else:
                    stats.dup_dropped += 1
            if len(page) < PAGE_LIMIT:
                finished = True
                break
            last = dt.datetime.strptime(page[-1][1], "%Y-%m-%dT%H:%M:%SZ")
            # Every product in a full page shares this minute only if >=100 products
            # were filed in it - not credible, but a cursor that cannot move would
            # loop forever, so step past it rather than trust that.
            if last <= cursor and new == 0:
                print(f"  warning: page of {PAGE_LIMIT} did not move the cursor past "
                      f"{fmt_cursor(cursor)}; stepping one minute", file=sys.stderr)
                last = cursor + dt.timedelta(minutes=1)
            cursor = last
            # Months strictly before the cursor's month can receive nothing more.
            buf.flush(cursor.strftime("%Y-%m"), months, finished=False)
            print(f"  page {page_no}: {len(page)} products ({new} new) to {fmt_cursor(cursor)}", flush=True)
    except CapReached:
        stats.capped = True
    finally:
        # Reached on cap, abort, Ctrl-C and normal exit alike: whatever was fetched is
        # on disk before the exception continues. Only a span that ran to its short
        # page may give the months after the last product their empty files; one
        # that stopped marks the month it was in as partial.
        buf.flush(None, months, finished, partial_ym=None if finished else cursor.strftime("%Y-%m"))
    print(f"{pil}  {fetcher.requests - req0} requests, {stats.fetched - new0} new products"
          + ("" if finished else ", span NOT finished"), flush=True)
    if stats.capped:
        raise CapReached()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def disk_report(cache_dir: str, pils, months):
    """Per (pil, year), read back from disk so it is true whether or not this run
    fetched anything. Product text size is measured on the serialised line, which
    is the text plus a few JSON escapes (within a few percent)."""
    rows = defaultdict(lambda: {"months": 0, "missing": 0, "thin": 0, "products": 0, "chars": 0, "bytes": 0})
    for pil in pils:
        for ym in months:
            r = rows[(pil, int(ym[:4]))]
            r["months"] += 1
            path = month_path(cache_dir, pil, ym)
            if not os.path.exists(path):
                r["missing"] += 1
                continue
            n = chars = 0
            try:
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            n += 1
                            chars += len(line)
            except (EOFError, OSError):
                pass
            r["products"] += n
            r["chars"] += chars
            r["bytes"] += os.path.getsize(path)
            days = calendar.monthrange(int(ym[:4]), int(ym[5:]))[1]
            if n < THIN_PER_DAY * days and ym < today_utc().strftime("%Y-%m"):
                r["thin"] += 1
    return rows


def print_report(rows):
    print()
    print(f"{'PIL':7s} {'year':>4s} {'months':>6s} {'unfetched':>9s} {'thin':>4s} {'products':>8s} "
          f"{'KB/product':>10s} {'disk MB':>8s}")
    tot = defaultdict(int)
    for (pil, year) in sorted(rows):
        r = rows[(pil, year)]
        kb = f"{r['chars'] / r['products'] / 1024:10.1f}" if r["products"] else f"{'-':>10s}"
        flag = "  <-- gaps" if r["missing"] or r["thin"] else ""
        print(f"{pil:7s} {year:4d} {r['months']:6d} {r['missing']:9d} {r['thin']:4d} {r['products']:8d} "
              f"{kb} {r['bytes'] / 1e6:8.2f}{flag}")
        for k in r:
            tot[k] += r[k]
    kb = f"{tot['chars'] / tot['products'] / 1024:10.1f}" if tot["products"] else f"{'-':>10s}"
    print(f"{'total':12s} {tot['months']:6d} {tot['missing']:9d} {tot['thin']:4d} {tot['products']:8d} "
          f"{kb} {tot['bytes'] / 1e6:8.2f}")
    print("'unfetched' months have no file yet; 'thin' months hold under "
          f"{THIN_PER_DAY:g} products/day (a real gap, or a quiet product).")


def est_kb(pil: str, year: int):
    return EST_KB_BY_PIL_YEAR.get((pil, year), EST_KB_DEFAULT)


def dry_run(cache_dir: str, pils, months, today: dt.date, delay: float, rescan: bool):
    """No network. Prices the run from the cache: where each PIL would resume, and
    how many pages and MB the rest of the span is."""
    total_pages = 0
    total_mb = 0.0
    for pil in pils:
        cursor, done_ym = start_cursor(cache_dir, pil, months, rescan)
        edate = span_end(months[-1], today)
        days = max(0.0, (dt.datetime.combine(edate, dt.time()) - cursor).total_seconds() / 86400)
        n = days * EST_PRODUCTS_PER_DAY
        pages = max(1, -(-int(n) // PAGE_LIMIT) if n else 1)
        mb = 0.0
        d = cursor.date()
        while d < edate:                       # integrate size by year
            ye = min(edate, dt.date(d.year + 1, 1, 1))
            mb += (ye - d).days * EST_PRODUCTS_PER_DAY * est_kb(pil, d.year) / 1024
            d = ye
        total_pages += pages
        total_mb += mb
        print(f"{pil}  " + ("rescans" if rescan else "resumes") + f" from {fmt_cursor(cursor)} "
              + ("" if rescan else f"(cache holds the run up to {done_ym})" if done_ym else "(nothing cached)")
              + f": {days:.0f} days left, ~{int(n)} products, ~{pages} page request(s), ~{mb:.0f} MB")
    secs = total_pages * (delay + 1.0)
    print()
    print(f"~{total_pages} requests, ~{total_mb:.0f} MB transferred; at --delay {delay:g}s "
          f"(+~1 s per page to transfer): ~{secs / 60:.0f} min")


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
                    help=f"pause between requests (default {DEFAULT_DELAY_S:g})")
    ap.add_argument("--max-requests", type=int, default=None, metavar="N",
                    help="stop cleanly after N page requests, to run in chunks")
    ap.add_argument("--dry-run", action="store_true",
                    help="no network: read the cache and report what a run would cost")
    ap.add_argument("--rescan", action="store_true",
                    help="walk from --start instead of resuming from the cache (fills holes; "
                         "products already cached are recognised and kept)")
    ap.add_argument("--cache-dir", default=CACHE_DIR, metavar="DIR", help=argparse.SUPPRESS)
    args = ap.parse_args()

    today = today_utc()
    this_month = today.strftime("%Y-%m")
    end = min(args.end or this_month, this_month)
    if args.start > end:
        ap.error(f"--start {args.start} is after --end {end}")
    if args.delay < 0 or (args.max_requests is not None and args.max_requests < 0):
        ap.error("--delay and --max-requests must not be negative")
    months = list(month_range(args.start, end))

    print(f"{', '.join(args.pil)}  {args.start}..{end}  ({len(months)} months)  cache {os.path.relpath(args.cache_dir, ROOT)}"
          + ("  [dry run: no network]" if args.dry_run else ""))
    if args.dry_run:
        dry_run(args.cache_dir, args.pil, months, today, args.delay, args.rescan)
        print_report(disk_report(args.cache_dir, args.pil, months))
        return 0

    fetcher = Fetcher(args.delay, args.max_requests)
    stats = RunStats()
    t0 = time.monotonic()
    try:
        for pil in args.pil:
            fetch_pil(fetcher, args.cache_dir, pil, months, today, args.rescan, stats)
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
          f"{fetcher.failed} failed), {stats.fetched} new products, {stats.dup_dropped} repeats dropped, "
          f"{fetcher.bytes / 1e6:.2f} MB received, {elapsed:.0f} s")
    print_report(disk_report(args.cache_dir, args.pil, months))

    if stats.span_failed:
        print("\nSPAN STOPPED SHORT (re-run to retry):", file=sys.stderr)
        for pil, cur in stats.span_failed:
            print(f"  {pil} from {cur}", file=sys.stderr)
    if stats.no_header:
        print(f"\n{stats.no_header} product(s) had no recognisable WMO header line; cached under a "
              f"'NOHDR' placeholder id", file=sys.stderr)
    if stats.span_failed or stats.aborted:
        return 1
    if stats.no_header:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
