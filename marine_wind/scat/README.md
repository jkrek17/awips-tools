# Scatterometer data (marine_wind/scat)

Builds the data for the scatterometer page (`/scatterometer/`, `marine_wind/scatterometer_page/`): the latest NOAA STAR
passes (OSCAT-3 and Metop-B/C coastal ultra-high-resolution ASCAT) over the two OPC basins, put on the 0.25 degree grid
beside the marine wind page's Best Wind and warning lines for the same time, with per-pass scores.

    python3 build.py --live DIR --state DIR --out DIR [--days 1] [--workers 5] [--changed-file F]
    python3 test_build.py                      # offline

`.github/workflows/scatterometer.yml` runs it hourly (minute 50) and force-pushes `data/` and `cache/` as the single
commit of the orphan branch `scatterometer-data`; `site_publish.yml` serves `data/` at `/scatterometer/data/`. Nothing
here is committed to main.

- `--live` is a checkout of `marine-wind-live` holding `latest/global/` (manifest.json, fSSS/best.gz, fSSS/warn.gz).
  `git --work-tree=DIR checkout origin/marine-wind-live -- latest/global && git reset -q`.
- `--state` is the previous state (the `scatterometer-data` branch checked out; empty or missing is fine).
- `--days N` lists STAR for today and N days back (0-8). Only passes not already in `cache/seen.json` are downloaded; a pass
  whose file count has grown (late chunks) is redone. About 9 MB per file, 50 files a day; the first run on an empty state
  with the default `--days 1` reads about 1 GB, an hourly run a few files.
- The reader is `nwp/nwp/star.py` (`passes(day)`, `points(url)`).

Format of `data/index.json` and `data/pass/<id>-<basin>.bin`, how passes, leads and scores are defined: the docstring of
`build.py`. `cycle` in the index and `fc.*.cycle` are `YYYYMMDDHH` of the marine wind run; times are `YYYY-MM-DDTHH:MMZ`.

Things to know

- `f24` and `f48` use the cached marine wind runs; when the cache lacks the cycle (it starts empty and keeps 4 days of full
  cycles, then steps 24 and 48 up to 10 days) they come from the marine wind job's `forecast-record-*` artifacts (about
  90 MB each, `GITHUB_TOKEN` needed, at most `--record-max` 40 downloads a run). Passes already published get the lead filled
  in on a later run. `latest` always comes from the cache, so it exists only from the first run on.
- OSCAT-3 file names carry the time the file was made, not the pass time, whenever STAR posts a batch of older orbits (a
  dozen files stamped within seconds). Those passes get a start time from their orbit number (about 100 min per orbit, fitted
  to the files with a good stamp). Pass brackets are [start, last file's start + 10 min (UHR chunk) or 55 min (OSCAT-3 half
  orbit)], tighter than the whole gap to the next file.
- Winds are the 10 m wind as served (equivalent-neutral not confirmed). Cell means at 0.25 degree; flagged (likely rain) cells
  are kept, drawn faded, and left out of every score.
- OSCAT-3 has not been checked against ASCAT: read its scores as a guide.
