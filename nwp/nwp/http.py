"""HTTP helpers: one pooled session, GET with the S3 retry rules, HEAD exists."""
from __future__ import annotations

import random
import time

import requests
from requests.adapters import HTTPAdapter

_session = requests.Session()
for _scheme in ("https://", "http://"):
    _session.mount(_scheme, HTTPAdapter(pool_connections=32, pool_maxsize=32))


def get(url, rng=None, tries=8):
    """GET (optionally a byte range); None on 403/404. S3 answers 503 SlowDown
    when a freshly posted file gets many range requests at once (everyone is
    pulling the new run), so 503 is retried quickly and often; anything else
    backs off exponentially."""
    headers = {"Range": "bytes=%d-%s" % (rng[0], "" if rng[1] is None else rng[1])} if rng else None
    fails = slow = 0
    while fails < tries and slow < 60:
        try:
            r = _session.get(url, headers=headers, timeout=180)
            if r.status_code in (200, 206):
                return r
            if r.status_code in (403, 404):
                return None
            if r.status_code == 503:
                slow += 1
                time.sleep(0.5 + 1.5 * random.random())
                continue
        except requests.RequestException:
            pass
        fails += 1
        time.sleep(min(2 ** fails, 60) * (0.5 + random.random()))
    raise RuntimeError("failed: " + url)


def exists(url):
    try:
        return _session.head(url, timeout=60).status_code == 200
    except requests.RequestException:
        return False
