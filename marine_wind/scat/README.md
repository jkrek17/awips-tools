# Scatterometer data (marine_wind/scat)

Builds the data for the scatterometer page (`/scatterometer/`, `marine_wind/scatterometer_page/`): the latest NOAA STAR
passes (OSCAT-3 and Metop-B/C coastal ultra-high-resolution ASCAT) over the two OPC basins, put on the 0.25 degree grid
beside the marine wind page's Best Wind and warning lines for the same time, with per-pass scores. The page opens on a
mosaic: for each 00Z and 12Z of the last 7 days (14 per basin) and each basin, the passes whose middle is in the 12 h
[V - 6 h, V + 6 h) stitched into one map (where swaths overlap ASCAT wins over OSCAT-3, then the pass nearest the time),
with Best Wind and warning lines of the whole basin at V. Each observed cell is scored against the forecast hour nearest its
own pass (valid V - 6, V or V + 6), not against V; a lead counts for a mosaic when the passes that have it hold 80% of the
observed cells. `data/mosaic/<basin>-<YYYYMMDDHH>.bin`, rebuilt when its passes change or gain a lead. On top of the
mosaic tab sits a 7-day summary (`summary` in `index.json`, computed here, the page only formats it): per basin and lead,
grid area against seen area, line catch, the share of line cells that were seen and reached the threshold, and the week's
8 highest ASCAT peaks (one per mosaic, clickable). It is ASCAT only by default: OSCAT-3 reads low at high winds, so the
page keeps it off unless `#oscat=1` (or the button) turns it on, and the headline scores are `score_ascat`.
Format and lead rules: the docstring of `build.py`.

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
- OSCAT-3 reads low at high winds against ASCAT (about 5 kt low at 34-48 kt, 15-20 kt low above 48 kt, 13 Oct-7 Nov 2026), and
  STAR's ASCAT covers about 5% of a basin in 6 h and 10-20% in 12 h. The page therefore scores on ASCAT only unless OSCAT-3 is
  switched on, and the summary pools a week of 12 h mosaics to give ASCAT enough cells at storm force.
