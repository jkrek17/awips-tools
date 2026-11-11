# High Seas Editor (`/hsf-editor/`)

A page for writing the OPC High Seas Forecast (HSFAT1 or HSFEP1) by hand. It is separate from the
model-written draft on `/high-seas/` and never reads it.

- **Starting text:** the last issued product for the basin, from the IEM text archive (it sends CORS
  headers, so the browser can read it; ocean.weather.gov does not), cut from `SYNOPSIS VALID` to
  `.FORECASTER`, with the three valid-time lines moved on 6 hours. If the archive cannot be reached, the page asks for the
  issued product to be pasted in.
- **Live map:** every area the text describes, drawn as you type (`hsf-read.js`), coloured by the top
  wind of its range; one forecast time at a time, and the map follows the paragraph the cursor is in.
  Click an area to select its paragraph. Each warning block's main low is drawn as a track through
  its forecast hours, so a mistyped position shows as a jump.
- **Slips read as meant:** a misspelled QUADRANT or SEMICIRCLE, `LINE FROM a AND b`, `FROM 128W AND
  170W`, `AMD`, `MM`, a missing `NM`, `54O`, `60M` are drawn the way they were meant, and each is still
  listed as "Mapped as ..." so it gets fixed in the text.
- **Checks:** every check of Jason's Apps Script "OPC High Seas Forecast Validator", with the fixes
  of 11 Nov 2026, plus coordinates out of range, seas in KT, and the map's own notes: an area it could
  not read, one that falls outside the forecast waters, or one with no latitude (or longitude) limits
  (`hsf-check.js`). Checks across forecast times: a low moving over 70 KT between steps, deepening 15 MB
  or filling 12 MB in 6 h, forecast hours out of order, a gap between a range and the ELSEWHERE range
  below it, and seas low for the winds (under 2.5 / 4 / 5 M with gale / storm / hurricane force). On
  1200 issued products per basin these fire on about 6% of products, mostly on real slips. Click a
  check to select the text.
- **How to:** a short guide to the page behind the header button.
- **New version:** the page checks every 10 minutes (and when the tab comes back) whether a newer copy
  is published and offers a reload; the draft is kept.
- **Copy:** Warnings box, Synopsis box (no header lines) and all, rejoined and wrapped at 66
  characters as the Apps Script's "Show Text to Send" does.
- **Wrap as you type:** the paragraph being edited rewraps at 66 characters (the send width) on every
  edit, with a faint rule at column 66; header and valid-time lines are left alone.
- **Draft:** kept in the browser (localStorage), one per basin.

## Files

| File | What it is |
| --- | --- |
| `hsf-read.js` | HSF text to map areas (browser and node). The JavaScript successor of `marine_wind/hsf/issued.py`'s reader, widened for quadrant lists, EXCEPT, Greenland, Bering Sea, Gulf of St Lawrence, coast and tropical cyclone wording |
| `hsf-check.js` | The checks and the send text (browser and node) |
| `app.js`, `index.html` | The page; the map is MapLibre from `../globe-kit/` with its land outline |
| `lib/polygon-clipping.min.js` | polygon-clipping 0.15.7 (MIT), for unions, intersections and EXCEPT |
| `tests/test_editor.js` | Offline tests on the issued products of 1630 UTC 11 Nov 2026 (`tests/fixtures/`) |
| `tests/coverage.js` | How much of the last N issued products the reader can draw (needs network) |

## Reader coverage

On the last 400 issued products of each basin (late summer to 11 Nov 2026):

| | Areas mapped | Forecast times with every area mapped |
| --- | --- | --- |
| Atlantic, `issued.py` | 80% | 63% |
| Atlantic, `hsf-read.js` | 96.6% | 89.7% |
| Pacific, `issued.py` | 82% | 67% |
| Pacific, `hsf-read.js` | 96.6% | 88.4% |

Where both readers draw an area, 90% of the shapes agree (overlap over 0.9 of their union). Most of
what is still not drawn is real slips in the issued text (`60M`, `3746W`, `54O NM`, `AMD`, a missing
`NM`), which the page lists as map notes, plus rare wording: lines run to the Alaska coast or
peninsula, Bristol Bay, Cook Inlet. Named outer coasts are drawn from a 0.5 deg sketch: California,
Oregon, Washington, Vancouver Island, British Columbia, Alaska, the Alaska Peninsula, Nova Scotia,
Newfoundland, Labrador; Greenland from Natural Earth; Hecate Strait as a box. Run `node tests/coverage.js 400 30` to see the commonest misses.

Shape rules: quadrant = bearing +-45 deg about the named direction, semicircle +-90; `<dirs> OF A
LINE` = the ground the line sweeps when moved 40 deg toward that side (the desk's lines run to a coast
or the area edge); `E OF GREENLAND` / `W OF GREENLAND` split at 43.5W; the Bering Sea is the water north
of the Aleutian chain and west of Alaska. Land is drawn over the areas, so a box that runs onto a coast
shows only its water. An ELSEWHERE area is drawn outside the areas given before it in the same
paragraph. A lone `BETWEEN 128W AND 170W` (or `FROM 40N TO 50N`) is drawn edge to edge and listed as a warning.

## Try it locally

Serve a folder holding `hsf-editor/` (this folder), `globe-kit/` and `fonts/` side by side, and open
`/hsf-editor/?basin=atl` or `?basin=pac`. `?test=1` exposes the page state to a headless check.
