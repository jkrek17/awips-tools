# Scatterometer data (marine_wind/scat)

Builds the data for the scatterometer page (`/scatterometer/`, `marine_wind/scatterometer_page/`): the latest NOAA STAR
passes (OSCAT-3 and Metop-B/C coastal ultra-high-resolution ASCAT), NESDIS Metop-B open-ocean ASCAT (about 1 h after the pass) and Remote Sensing Systems (RSS) open-ocean ASCAT over the two OPC basins, put on the 0.25 degree grid
beside the marine wind page's Best Wind and warning lines for the same time, with per-pass scores. The page opens on a
mosaic: for each 00Z and 12Z of the last 7 days (14 per basin) and each basin, the passes whose middle is in the 12 h
[V - 6 h, V + 6 h) stitched into one map (where swaths overlap RSS ASCAT wins over NESDIS Metop-B, which wins over STAR ASCAT, which wins over OSCAT-3, then the pass nearest the time),
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

`.github/workflows/scatterometer.yml` runs it hourly (minute 50) and after every "Marine wind data" run, and force-pushes `data/` and `cache/` as the single
commit of the orphan branch `scatterometer-data`; `site_publish.yml` serves `data/` at `/scatterometer/data/`. Nothing
here is committed to main.

- `--live` is a checkout of `marine-wind-live` holding `latest/global/` (manifest.json, fSSS/best.gz, fSSS/warn.gz).
  `git --work-tree=DIR checkout origin/marine-wind-live -- latest/global && git reset -q`.
- `--state` is the previous state (the `scatterometer-data` branch checked out; empty or missing is fine).
- `--days N` lists STAR for today and N days back (0-8). Only passes not already in `cache/seen.json` are downloaded; a pass
  whose file count has grown (late chunks) is redone. About 9 MB per file, 50 files a day; the first run on an empty state
  with the default `--days 1` reads about 1 GB, an hourly run a few files.
- The readers are `nwp/nwp/star.py` (`passes(day)`, `points(url)`) `nwp/nwp/rss_ascat.py` (`day(sat, date)`) and `nwp/nwp/nesdis_ascat.py` (`day(date, box)`).
- RSS ASCAT: STAR's ASCAT is a coastal product (about 9-12% of a basin per 12 h); RSS has full swaths over the open ocean in
  daily 0.25 degree Metop-B and -C maps, but posts them about 2 days late (lately about 5). Every run asks for each day of the
  window that is not done (`cache/rss.json`; a day not yet posted at most once in 55 min, until 10 days old, at most 16 files a
  run of 1-3 MB). A day is used when both satellites are there, or one is and the day is 7 or more days old. Its cells inside an
  OPC box on water become pseudo-passes (one per satellite, node, basin and nearest synoptic hour, labelled "RSS Metop-B" or
  "RSS Metop-C", ids `<earliest cell>-rss_metopb_AS`), which go through the same pipeline as STAR passes and win the overlap
  against them. RSS cell centres sit at x.125 degrees; each cell goes to the page cell at its north-west corner (a half-cell
  shift, one RSS cell per page cell). Winds are RSS's equivalent-neutral 10 m wind in knots, used as STAR's are (no conversion).
  The mosaics that gain RSS cells are rebuilt; recent ones have STAR's coastal ASCAT only. The page splits the coverage into RSS
  and STAR ASCAT and says how many of the week's mosaics have RSS (`sats.RSS` and `summary.*.with_rss`).
- NESDIS Metop-B ASCAT, near real time: NOAA AOML's daily 0.25 degree Metop-B map (one growing time step per UTC day) read
  through NOAA ERDDAP (dataset `noaa_aoml_8c7c_16cc_8cde`; Metop-C is not there), about 1 h after the pass. Every run asks for
  today, yesterday and any day of the window that is not final (2 days old and fetched after it ended) and not covered by RSS
  Metop-B (`cache/nesdis.json`): 3 requests a day (Atlantic one, Pacific two across the date line), 6 when nothing is old,
  2-5 MB of csv each. The cells go through the same splitting as RSS (`split_passes`) into pseudo-passes labelled "Metop-B
  (NESDIS)", ids `<synoptic hour>-nesdis_metopb_AS` (stable while the day fills). A pass with more cells than last run is
  replaced under the same id (scored again, its mosaics rebuilt). Priority in the stitch: RSS > NESDIS > STAR ASCAT >
  OSCAT-3, so when RSS posts the day it takes over. Against RSS Metop-B cell for cell: speed bias 0.0 kt, SD 1.0 kt.
  `sats.NESDIS` and `summary.*.with_nesdis`; the page shows the NESDIS, RSS and STAR coastal shares of each mosaic.

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
  STAR's ASCAT covers about 5% of a basin in 6 h and 10-20% in 12 h (RSS ASCAT, where it has arrived, much more). The page
  therefore scores on ASCAT only unless OSCAT-3 is switched on, and the summary pools a week of 12 h mosaics to give ASCAT
  enough cells at storm force.
