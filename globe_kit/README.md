# Globe kit

The shared parts of the site's globe pages, published at `/globe-kit/` beside
them: the marine wind page (`marine_wind/page/`, at `/marine-wind/`) and the
cyclone phase space page (`cyclone_phase_space/article/live/`, at `/cyclone/`).
The look is the site's `/ndfd/` globe page: a dark console of glass cards over a
full-window MapLibre GL globe.

| File | What it is |
| --- | --- |
| `lib/maplibre-gl.js`, `lib/maplibre-gl.css` | MapLibre GL JS 5.24.0, the same build `/ndfd/` uses |
| `globe-kit.css` | The look: colours, top bar, layers panel, legend card, timeline, readout, notes, dialogs and sheets, MapLibre controls, phone layout |
| `globe-kit.js` | `window.GlobeKit`: the globe map over the Esri ocean basemap, a 2D overlay canvas that skips the far side of the globe, the graticule and its labels, the land outline, the timeline rail, icons, time and position formats, the panel toggle and the status note |
| `land.json` | Natural Earth 50m land, public domain |

## A new page

1. Copy the page skeleton from `marine_wind/page/index.html`: the top bar,
   `#panel`, `.legend`, `.notes`, `#timeline`, `#helpDialog` and `#fatal`,
   with `#map` and `#overlay` first. Load `../globe-kit/lib/maplibre-gl.css`,
   `../globe-kit/globe-kit.css`, the page's own `style.css`, then
   `../globe-kit/lib/maplibre-gl.js`, `../globe-kit/globe-kit.js` and the
   page's scripts.
2. In the page's script: `GlobeKit.createMap({start, credits})`, then
   `GlobeKit.overlay(map, canvas)` for text; add the page's layers on the
   map's `load` event. `GlobeKit.timeline(validTimes)` draws the rail.
3. Add the page's folder and its `index.html` link stamping to
   `.github/workflows/site_publish.yml`, as for the two pages there.

To try a page locally, serve a folder holding the page folder and
`globe-kit/` side by side (the pages load `../globe-kit/`), with the page's
data where the page looks for it.
