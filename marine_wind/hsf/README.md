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
  ALSO / ELSEWHERE with a lower range. Each range tops out at its category (gale 45, storm
  60, under gale 30); the top is the grid peak rounded up to 5 kt. A few pixels of storm
  force are enough for a storm warning.
- Warning areas are drawn 4 kt below their level (gale around 30 kt). Winter 2025-26 Pacific
  test against ASCAT: drawn at 30 kt the draft caught 94% of real gale force with half the
  desk's area; drawn at 34 kt, 76%.
- Synopsis, 24 and 48 h, plus an in-between step each time a low's warning category goes up
  (none to gale, gale to storm, storm to hurricane force).
  Complex lows: "COMPLEX LOW WITH MAIN CENTER ..." only.

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
