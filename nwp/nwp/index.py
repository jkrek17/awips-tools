"""Index readers: NCEP .idx and ECMWF .index. Each is read once per URL and kept
in a small thread-safe LRU, so several field groups from one file share a read."""
from __future__ import annotations

import json
import threading
from collections import OrderedDict

from .http import get

MAXURLS = 256
_cache = OrderedDict()
_lock = threading.Lock()


def _cached(url, parse):
    with _lock:
        if url in _cache:
            _cache.move_to_end(url)
            return _cache[url]
    r = get(url)
    if r is None:
        return None
    val = parse(r.text)
    with _lock:
        _cache[url] = val
        _cache.move_to_end(url)
        while len(_cache) > MAXURLS:
            _cache.popitem(last=False)
    return val


def forget(url=None):
    """Drop one cached index, or all of them."""
    with _lock:
        _cache.pop(url, None) if url else _cache.clear()


def _ncep_parse(text):
    lines = [l.split(":") for l in text.splitlines() if l.strip()]
    recs = []
    for i, f in enumerate(lines):
        end = int(lines[i + 1][1]) - 1 if i + 1 < len(lines) else None
        recs.append((f[3] + ":" + f[4], int(f[1]), end))
    idx = {}
    for key, a, b in recs:
        idx.setdefault(key, (a, b))
    return tuple(recs), idx


def ncep_records(url):
    """url: the data file. [(key, start, end), ...] in file order, or None. key is
    'VAR:level'; end is None for the last record (open range)."""
    got = _cached(url + ".idx", _ncep_parse)
    return None if got is None else list(got[0])


def ncep_index(url):
    """{key: (start, end)}, first record winning, or None when the file has no index."""
    got = _cached(url + ".idx", _ncep_parse)
    return None if got is None else dict(got[1])


def ec_records(base):
    """base: the file URL without extension. The .index JSON records, or None."""
    got = _cached(base + ".index",
                  lambda t: tuple(json.loads(l) for l in t.splitlines() if l.strip().startswith("{")))
    return None if got is None else list(got)


def span(rec):
    """Byte range of an ECMWF index record."""
    return rec["_offset"], rec["_offset"] + rec["_length"] - 1
