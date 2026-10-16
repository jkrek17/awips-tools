"""Merge page_scores.py output into the verification page's tables and write the page's data.

    python3 page_data.py --tables DIR --add NEW_DIR [NEW_DIR ...]   # merge new day files into DIR/*.csv
    python3 page_data.py --tables DIR --json OUT                   # write OUT/*.json for the page

DIR holds scores.csv.gz, chances.csv.gz and storm.csv.gz (gzipped: a year and a half of scores
is about 50 MB as plain text); a (valid, basin) pair in the new files
replaces the same pair already there. The page reads, per basin, one columnar file per truth
source (OUT/BASIN_REFEREE.json), OUT/BASIN_chances.json, OUT/BASIN_storm.json and OUT/index.json.
"""
import argparse, csv, datetime as dt, glob, gzip, io, json, os

import page_scores as ps

TABLES = {"scores": ps.SCORE_FIELDS, "chances": ps.CHANCE_FIELDS, "storm": None}
KEYS = {"scores": ("valid", "basin", "lead", "method", "referee"), "chances": ("valid", "basin", "lead", "referee", "thr"),
        "storm": ("valid", "basin", "lead", "referee", "product")}


def read(path):
    if not os.path.exists(path):
        return []
    with (gzip.open(path, "rt", newline="") if path.endswith(".gz") else open(path, newline="")) as f:
        return list(csv.DictReader(f))


def merge(tables, new_dirs):
    for name in TABLES:
        files = [f for d in new_dirs for f in sorted(glob.glob(os.path.join(d, "**", name + "_*.csv"), recursive=True))]
        if not files:
            continue
        new = [r for f in files for r in read(f)]
        pairs = {(r["valid"], r["basin"]) for r in new}
        path = os.path.join(tables, name + ".csv.gz")
        rows = [r for r in read(path) if (r["valid"], r["basin"]) not in pairs] + new
        rows.sort(key=lambda r: tuple(int(r[k]) if k in ("lead", "thr") else r[k] for k in KEYS[name]))
        fields = TABLES[name] or list(csv.DictReader(open(files[0])).fieldnames)
        with gzip.open(path, "wt", newline="") as f:
            w = csv.DictWriter(f, fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print("%s: %d rows (%d days added or replaced)" % (path, len(rows), len(pairs)))


def num(v):
    if v in ("", None):
        return None
    x = float(v)
    return int(x) if x.is_integer() else round(x, 2)


def columnar(rows, cols, cats):
    """{col: [values]}; category columns become indexes into cats[col]."""
    out = {}
    for c in cols:
        if c in cats:
            idx = {v: i for i, v in enumerate(cats[c])}
            out[c] = [idx[r[c]] for r in rows]
        elif c == "valid":
            out[c] = [int(r[c]) for r in rows]
        else:
            out[c] = [num(r[c]) for r in rows]
    return out


def write_json(tables, out):
    os.makedirs(out, exist_ok=True)
    scores, chances, storm = (read(os.path.join(tables, n + ".csv.gz")) for n in TABLES)
    refs = ps.GRID_REFS + ["ascat", "buoys", "ships+buoys"]
    idx = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "methods": ps.METHODS,
           "referees": refs, "leads": ps.STEPS, "basins": {}}
    for basin in sorted(ps.HOUR):
        sb = [r for r in scores if r["basin"] == basin]
        if not sb:
            continue
        days = sorted({r["valid"] for r in sb})
        idx["basins"][basin] = {"hour": ps.HOUR[basin], "first": days[0], "last": days[-1], "days": len(days),
                                "referees": [x for x in refs if any(r["referee"] == x for r in sb)]}
        drop = {"basin", "hour", "referee"}
        for ref in refs:
            rr = [r for r in sb if r["referee"] == ref]
            if not rr:
                continue
            cols = [c for c in ps.SCORE_FIELDS if c not in drop and (ref in ps.GRID_REFS + ["ascat"] or not c.startswith(("t3", "t4", "t6", "pk_")))]
            json.dump({"cols": cols, "methods": ps.METHODS, **columnar(rr, cols, {"method": ps.METHODS})},
                      open(os.path.join(out, "%s_%s.json" % (basin, ref.replace("+", "_"))), "w"), separators=(",", ":"))
        cb = [r for r in chances if r["basin"] == basin]
        cols = [c for c in ps.CHANCE_FIELDS if c not in {"basin", "hour"}]
        json.dump({"cols": cols, "referees": refs, **columnar(cb, cols, {"referee": refs})},
                  open(os.path.join(out, "%s_chances.json" % basin), "w"), separators=(",", ":"))
        st = [r for r in storm if r["basin"] == basin]
        if st:
            prods = sorted({r["product"] for r in st})
            cols = ["valid", "lead", "referee", "product", "hit", "miss", "fa", "cn", "err_km", "dp_hpa"]
            json.dump({"cols": cols, "referees": ["ascat", "analysis"], "products": prods,
                       **columnar(st, cols, {"referee": ["ascat", "analysis"], "product": prods})},
                      open(os.path.join(out, "%s_storm.json" % basin), "w"), separators=(",", ":"))
    json.dump(idx, open(os.path.join(out, "index.json"), "w"), indent=1)
    print("page data in", out, {b: v["days"] for b, v in idx["basins"].items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", required=True)
    ap.add_argument("--add", nargs="*")
    ap.add_argument("--json")
    a = ap.parse_args()
    os.makedirs(a.tables, exist_ok=True)
    if a.add:
        merge(a.tables, a.add)
    if a.json:
        write_json(a.tables, a.json)


if __name__ == "__main__":
    main()
