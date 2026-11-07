# High Seas Forecast text from grids

`writer.py` turns wind, pressure and seas grids into a first-guess OPC High Seas Forecast
(the FZPN01 / FZNT01 layout). It takes plain numpy arrays and knows nothing about where they
came from, so the same code serves:

- the marine wind page (`build_hsf.py`, run by the "Marine wind data" job each new cycle,
  published under `latest/hsf/` and shown at `/high-seas/`), and
- later, a GFE formatter fed from the forecaster's own Wind and WaveHeight grids.

| File | What it does |
| --- | --- |
| `writer.py` | Areas, phrases, wind and seas ranges, lows, complex lows, paragraphs, warnings |
| `issued.py` | Fetches the issued product from the IEM text archive and turns its areas into shapes |
| `areas.py` | Forecast area outlines, point-in-polygon, mask outlines for maps (numpy only) |
| `build_hsf.py` | Reads one of the page's boxes (`manifest.json` + `fFFF.bin`), adds GFS-Wave seas, writes `pac.*` (HSFEP1) or `atl.*` (HSFAT1, north of 31N to 67N and west of 35W) |

## Each run
`build_hsf.py` writes one draft per wind grid: Core Lifted (`pac.*`, `atl.*`), GFS, ECMWF,
AIFS (`pac-gfs.*` ...) from the box, and NDFD (`pac-ndfd.*`) from the newest NDFD oceanic
snapshot covering the synopsis to 48 h (`nwp/nwp/ndfd.py`). All share the 3-model mean
pressure and GFS-Wave seas. With `--prev` it also scores the previous run's drafts against
the forecast the desk issued for their synopsis (`compare-pac.json`): warned area at gale,
storm and hurricane force for each, issued, draft and both. The page shows it under
"Compare with issued".

## Rules (Jason, Oct 2026)
- Describe an area as a lat/lon box first, then quadrants or semicircles round the low
  (radii in 60 nm steps), then "within X nm of a line". A non-box form must describe the
  area clearly better.
- Fit the grid's own area: warning-level winds in their own tight core, lesser winds in
  ALSO / ELSEWHERE with a lower range. The top tier's range comes from the grid peak rounded
  up to 5 kt (capped at its category); each lower range then tops out where the one above
  starts, so the ranges run on without gaps: "55 TO 70", "40 TO 55", "25 TO 40" (Jason 11-07),
  never below "20 TO 30". The desk's habits, from 848 issued HSFEP1 and HSFAT1 each (Oct 2025 - Nov 2026, Jason
  11-07 "learn from the real forecasts"): a warning carries its own categories only, with no
  20 TO 30 area (gale one range, storm core + gale, hurricane force core + storm + gale); under a
  storm core the gale area reads 25 TO 40; storm ranges top out at 40 TO 55. Areas below gale
  (the synopsis section) keep their 20 TO 30 range. Rules.warn_tiers_only and Rules.storm_cap
  switch these. A few pixels of storm
  force are enough for a storm warning. A small gale core (under a quarter of the area round
  it and under ~12 sq deg) is written as one area with the wider range ("WINDS 25 TO 40 KT"),
  not as a separate little box beside the big one (Jason 10-30).
- Seas: when the high end is more than double the low end, say where they peak, the desk's
  wording: "SEAS 3 TO 8 M...HIGHEST NEAR 35N175W." (Jason 10-30; the desk does this on 65% of
  ranges over 2.5x in 2025-26).
- Warning areas are drawn below their level: gale around 30 kt, storm around 39 kt (the page's
  storm hazard line), hurricane force around 60 kt. Winter 2025-26 Pacific against ASCAT with the
  60 nm ring billed: gale at 30 kt covers 94% of real gale water at 43% of the desk's area; storm
  at 39 kt on Core Lifted (held-out weeks) covers 66% of storm water, at 44 kt 48%.
- Synopsis, 24 and 48 h, plus an in-between step each time a low's warning category goes up
  (none to gale, gale to storm, storm to hurricane force).
  Complex lows: "COMPLEX LOW WITH MAIN CENTER ..." only.
- Each low keeps its own paragraph: a low that was briefly part of another low's complex does not
  carry its own winds into that paragraph later. Within a category, lows at the synopsis come
  before NEW ones. A low that goes away near another reads "LOW ABSORBED BY LOW 53N144W DESCRIBED
  BELOW", with "INLAND AND CONDITIONS" when it was last seen over land (no GFS-Wave seas there).
  Test: `python3 marine_wind/hsf/tests/test_low_paragraphs.py`.
- Lows outside the area (Jason 11-07; checked against the issued HSFEP1 12Z 7 Nov): lows over open ocean anywhere in the box are tracked, not
  only those within 3 degrees of the area, so a system crossing 180W (or 35W) keeps one paragraph.
  Its low is named the desk's way, "LOW W OF AREA 51N173E 1002 MB" (E / N / S / NW ... OF AREA in
  either basin). NEW means the low formed after the synopsis, not that its winds just reached the
  area. A wind area beyond 900 nm of every low joins the low holding most of the same connected
  wind area instead of becoming a paragraph with no low; a weak low outside the area keeps only
  winds within 300 nm of it when they are a small part of another system's wind area. A complex
  low's main centre is its deepest centre inside the area, and every other centre lies within
  600 nm of it (no chains). Stray wind goes to the nearest system sharing its wind area. A track may skip one 6 h step. Quadrants
  pay for open ocean outside the area too, so a low west of 180W gets quadrants facing into the
  area or a box, not "WITHIN 840 NM S QUADRANT".
  Test: `python3 marine_wind/hsf/tests/test_western_boundary.py`.

## Valid times
The desk issues every 6 h, the synopsis valid 4.5 h before it is due (00Z due 0430Z, 06Z due
1030Z, 12Z due 1630Z, 18Z due 2230Z). The page build cuts the two boxes at every page lead, 6 h apart
(`STEPS` in `pipeline/build.py`), so cycle C writes the draft whose synopsis is C+6 h:
the 00Z run, on the page about 07-08Z, drafts the 06Z forecast due 1030Z. In-between steps
are 6 h apart.

## Try it
    MARINE_DOMAIN=npac python3 build_hsf.py --box path/to/latest/npac --basin pac --out /tmp/hsf
    MARINE_DOMAIN=natl python3 build_hsf.py --box path/to/latest --basin atl --out /tmp/hsf

The Atlantic text follows the same rules: the archive (HSFAT1, winter 2025-26) uses the same
area forms, ranges and step words as the Pacific.

Research, archive scoring and plots: the project's `hsf/` folder (not in this repo).
