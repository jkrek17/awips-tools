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
| `areas.py` | Forecast area outlines, point-in-polygon, mask outlines for maps (numpy only) |
| `build_hsf.py` | Reads one of the page's boxes (`manifest.json` + `fFFF.bin`), adds GFS-Wave seas, writes `pac.*` (HSFEP1) or `atl.*` (HSFAT1, north of 31N to 67N and west of 35W) |

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
- Synopsis, 24 and 48 h, plus one in-between step when a low's warning level goes up.
  Complex lows: "COMPLEX LOW WITH MAIN CENTER ..." only.

## Valid times on the page
The page holds leads every 12 h, so cycle C writes the draft whose synopsis is C+12 h (the
06Z run gives the 2230Z issuance's 18Z synopsis). In-between steps are 12 h apart.
`write_product` accepts 6 h steps unchanged if the page ever carries them.

## Try it
    MARINE_DOMAIN=npac python3 build_hsf.py --box path/to/latest/npac --basin pac --out /tmp/hsf
    MARINE_DOMAIN=natl python3 build_hsf.py --box path/to/latest --basin atl --out /tmp/hsf

The Atlantic text follows the same rules: the archive (HSFAT1, winter 2025-26) uses the same
area forms, ranges and step words as the Pacific.

Research, archive scoring and plots: the project's `hsf/` folder (not in this repo).
