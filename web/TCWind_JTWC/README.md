# JTWC TC Wind - web preview

*** EXPERIMENTAL. NOT OPERATIONALLY VETTED. ***

A small Google Apps Script web app that mirrors the GFE procedure
`GFE/procedures/TCWind_JTWC.py`: it fetches the five NW Pacific JTWC
tropical cyclone warnings from the NWS Telecommunications Gateway,
parses them, and shows the reported radii plus an analytic vortex wind
field on a Leaflet map. It's a preview/QC aid for the GFE tool, not a
gridded product and not verified against observations.

The JTWC parser in `Code.gs` (`parseJTWC()`) is a line-for-line port of
`parseJTWC()` in the Python tool. If you change one, change the other,
and re-run `runSelfTest()` in the Apps Script editor.

## Files

- `Code.gs` - server side: fetches/caches the bulletins, `doGet()` entry
  point, the JTWC text parser.
- `Index.html` - client side: Leaflet map, vortex math (ported from
  `buildVortex()` in the Python tool), timeline slider, paste-to-parse
  fallback.
- `appsscript.json` - manifest. Web app access is currently `MYSELF`;
  widen `webapp.access` (e.g. `DOMAIN` or `ANYONE_ANONYMOUS`) and
  redeploy if this should be shared more broadly.
- `.clasp.json` - clasp project binding (script ID only, no
  credentials).

## Deploying with clasp

```bash
npm install -g @google/clasp
clasp login                 # one-time browser OAuth
cd web/TCWind_JTWC
clasp push                  # push Code.gs/Index.html/appsscript.json
clasp deploy -d "description"   # create/update a versioned web app deployment
```

`clasp push` updates the `@HEAD` version (live in the Apps Script
editor immediately); `clasp deploy` cuts an immutable versioned
deployment, which is what the `/exec` web app URL actually serves.
Re-run `clasp deploy` (or `clasp redeploy <deploymentId>`) after future
pushes to update the live web app.
