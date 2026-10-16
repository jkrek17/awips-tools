"""Cycle probing and the opt-in build-window wait."""
from __future__ import annotations

import datetime as dt
import time

from . import index
from .http import _session, exists


def cycle_list(now=None, every=6, n=8):
    """Candidate cycles 'YYYYMMDDHH', newest first, at multiples of `every` hours."""
    now = now or dt.datetime.now(dt.timezone.utc)
    t = now.replace(hour=now.hour // every * every, minute=0, second=0, microsecond=0)
    return [(t - dt.timedelta(hours=every * i)).strftime("%Y%m%d%H") for i in range(n)]


def newest_cycle(candidates, urls):
    """First cycle (candidates are newest first) whose files all exist, else None.
    urls(cycle) -> list of URLs that must be posted."""
    for c in candidates:
        if all(exists(u) for u in urls(c)):
            return c
    return None


def wait_for_quiet(url, every=30, timeout=1800, sleep=time.sleep, clock=time.time):
    """Opt-in, for research and backfills (never the live job): wait until the
    index at `url` stops changing, i.e. Content-Length and ETag are the same on two
    checks `every` seconds apart. True when quiet, False on timeout."""
    def sig():
        try:
            r = _session.head(url, timeout=60)
        except Exception:
            return None
        if r.status_code != 200:
            return None
        return r.headers.get("Content-Length"), r.headers.get("ETag")

    end, last = clock() + timeout, None
    while True:
        cur = sig()
        if cur is not None and cur == last:
            index.forget(url)
            return True
        last = cur
        if clock() + every > end:
            return False
        sleep(every)
