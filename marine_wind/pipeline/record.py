"""The forecast record: what the page job computed at leads +24..+120 (build.py --record), kept as
GitHub Actions artifacts `forecast-record-YYYYMMDDHH-fLLL` so the verification reads it instead
of downloading and rebuilding the forecasts. Global grid; one fLLL.npz (every field, extras
prefixed "extra_") plus fLLL.json (cycle, step, stats, commit) per lead.

load_or_build(cycle, step) -> (vals, stats, extra), as build.step_values returns: the local
cache (RECORD_CACHE, default ~/.cache/forecast-record), else the artifact (needs GITHUB_TOKEN or
GH_TOKEN), else a rebuild. A non-global MARINE_DOMAIN gets the record cropped to its box."""
import io
import json
import os
import shutil
import zipfile

import numpy as np

EXTRAS = ("gefs_mean", "ens_mean", "aifsens_mean")
REPO = "jkrek17/awips-tools"


def _name(step):
    return "f%03d" % step


def save(dir, cycle, step, vals, stats, extra):
    """Write dir/fLLL.npz and dir/fLLL.json, every grid in its own dtype so a load is exact."""
    os.makedirs(dir, exist_ok=True)
    arrays = {k: np.asarray(v) for k, v in vals.items()}
    ex = {k: np.asarray(v) for k, v in (extra or {}).items() if v is not None}
    arrays.update({"extra_" + k: v for k, v in ex.items()})
    base = os.path.join(dir, _name(step))
    np.savez_compressed(base + ".npz", **arrays)
    try:
        from domain import KEY
    except Exception:
        KEY = "glob"
    meta = dict(cycle=cycle, step=step, stats=stats, commit=os.environ.get("GITHUB_SHA", ""), domain=KEY,
                fields=list(vals), extras=list(ex))
    with open(base + ".json", "w") as f:
        json.dump(meta, f)


def load(dir, cycle, step):
    """(vals, stats, extra) from a saved record; extra has all of EXTRAS, None where missing."""
    base = os.path.join(dir, _name(step))
    meta = json.load(open(base + ".json"))
    if meta.get("cycle") != cycle or meta.get("step") != step:
        raise ValueError("record %s is for %s +%s" % (base, meta.get("cycle"), meta.get("step")))
    with np.load(base + ".npz") as z:
        vals = {k: z[k] for k in meta["fields"]}
        extra = {k: (z["extra_" + k] if k in meta["extras"] else None) for k in EXTRAS}
    return vals, meta["stats"], extra


def _crop(vals, stats, extra):
    """The global record cut to the current MARINE_DOMAIN's box (rows IY, columns IX), with the
    ensemble lows moved to the box's row/column and the ones off it or near its edge dropped."""
    import domain
    if domain.GLOBAL:
        return vals, stats, extra
    gx = (domain.IX - 720) % 1440   # domain.IX counts from 0E; the global record's columns start at 180W
    cut = lambda a: None if a is None else a[domain.IY][:, gx]
    col = {int(c): i for i, c in enumerate(gx)}
    lows = []
    for l in stats.get("lows", []):
        r, c = l["r"] - domain.IY.start, col.get(l["c"])
        if c is not None and 3 <= r < domain.NY - 3 and 3 <= c < domain.NX - 3:
            lows.append(dict(l, r=r, c=c))
    return {k: cut(v) for k, v in vals.items()}, dict(stats, lows=lows), {k: cut(v) for k, v in extra.items()}


def _artifact(cache, cycle, step):
    """Download the record artifact for one lead into cache; False when there is none."""
    import requests
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return False
    repo = os.environ.get("GITHUB_REPOSITORY") or REPO
    name = "forecast-record-%s-f%03d" % (cycle, step)
    head = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    r = requests.get("https://api.github.com/repos/%s/actions/artifacts" % repo,
                     params={"name": name, "per_page": 5}, headers=head, timeout=60)
    r.raise_for_status()
    live = [a for a in r.json().get("artifacts", []) if not a.get("expired")]
    if not live:
        return False
    best = max(live, key=lambda a: a.get("created_at") or "")
    z = requests.get(best["archive_download_url"], headers=head, timeout=300, allow_redirects=True)
    z.raise_for_status()
    os.makedirs(cache, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        have = {os.path.basename(n): n for n in zf.namelist()}
        for n in (_name(step) + ".npz", _name(step) + ".json"):
            with open(os.path.join(cache, "%s-%s" % (cycle, n)), "wb") as f:
                f.write(zf.read(have[n]))
    return True


def load_or_build(cycle, step):
    """build.step_values(ymd, hh, step) for cycle YYYYMMDDHH, from the record when there is one."""
    cache = os.environ.get("RECORD_CACHE") or os.path.expanduser("~/.cache/forecast-record")
    # each lead is cached under cycle-fLLL.* ; load() reads dir/fLLL.*, so keep one dir per cycle
    d = os.path.join(cache, cycle)
    source = None
    try:
        if os.path.exists(os.path.join(d, _name(step) + ".npz")):
            source = "cache"
        else:
            tmp = os.path.join(cache, "dl-%s-%d" % (cycle, os.getpid()))
            try:
                if _artifact(tmp, cycle, step):
                    os.makedirs(d, exist_ok=True)
                    for ext in (".json", ".npz"):   # npz last: its presence marks a complete record
                        os.replace(os.path.join(tmp, "%s-%s%s" % (cycle, _name(step), ext)), os.path.join(d, _name(step) + ext))
                    source = "artifact"
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if source:
            out = _crop(*load(d, cycle, step))
            print("forecast %s +%dh from the record (%s)" % (cycle, step, source), flush=True)
            return out
    except Exception as e:
        print("forecast record %s +%dh unusable (%s: %s)" % (cycle, step, type(e).__name__, e), flush=True)
    import build
    print("forecast %s +%dh rebuilt" % (cycle, step), flush=True)
    return build.step_values(cycle[:8], cycle[8:], step)
