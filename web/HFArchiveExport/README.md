# HF Archive Export

A small Google Apps Script web app bound to the "HF Lows" spreadsheet - the
hand-maintained archive of hurricane-force extratropical low events behind
the published climatology site. It exists to solve one specific problem:

**The problem.** The spreadsheet lives in a NOAA Google Workspace. Workspace
policy allows sharing it "anyone in NOAA," but it can **not** be made
link-readable to the public. That rules out the usual trick of publishing a
tab as CSV via File > Share > Publish to web and just curling the URL: there
is no such URL that works for a non-NOAA requester. The site is built and
published from a plain Linux box that holds no Google credentials and has no
way to authenticate as a NOAA user, so it cannot open the sheet directly
either.

**The fix.** Apps Script lets a web app run with permissions distinct from
the permissions of whoever calls it: deploy this script to **execute as the
user who deployed it** (the sheet's owner, who already has access) and to be
**accessible to anyone**. The deployed `/exec` URL then runs with the
owner's read access no matter who requests it, reads the two tabs, and
re-serves them as plain CSV text. The restricted sheet itself never changes
its sharing; only this narrow, read-only, two-tabs-and-nothing-else output
is reachable from outside NOAA. A shared token is required on every request
so the URL isn't immediately useful to anyone who happens to see it in a
log or a browser history - see **Security** below for exactly what that
does and does not protect.

This endpoint is a thin exporter and stays that way on purpose:
`tools/build_hf_lows.py` is the one place that normalizes categories,
resolves duplicate/ambiguous IDs, and runs QC over the archive. `Code.gs`
does not re-implement any of that - it hands back rows close to verbatim,
the same way a manual "File > Download > CSV" of each tab would, so there is
exactly one hand-ported set of rules to keep in sync, not two.

## Files

- `Code.gs` - server side: `doGet()` entry point, token check, loose tab-name
  matching, CSV rendering, `setup()` and `runSelfTest()`.
- `appsscript.json` - manifest. `webapp.access` is `ANYONE_ANONYMOUS` and
  `webapp.executeAs` is `USER_DEPLOYING`; see **Security** for exactly what
  that combination means.
- `.clasp.json` (not checked in with content here - create it as part of
  deployment, see below) - clasp project binding, script ID only, no
  credentials.

## Deploying with clasp

```bash
npm install -g @google/clasp
clasp login                       # one-time browser OAuth, as the sheet owner
cd web/HFArchiveExport
clasp create --type webapp --title "HF Archive Export" \
  --parentId 1ncqcxbCokCRmf6npv4tXAODLWZlYEzYtMrEigHdkTe4
# clasp create writes .clasp.json for you, bound to the spreadsheet above.
clasp push                        # push Code.gs/appsscript.json
```

Then, once, from the Apps Script editor (`clasp open`):

1. Select the `setup` function in the function dropdown and click Run.
   Approve the authorization prompt (this is what grants the script the
   owner's read access to the sheet).
2. Open View > Logs (or Executions) and copy the logged token. It is a
   random string stored in this script's Script Properties under
   `EXPORT_TOKEN` - it is never written into source, so it isn't sitting in
   git history or in `clasp push` output.
3. Put that token into the publishing box's config (an environment variable
   or a local, non-committed file - not into any file in this repo).

Then cut the actual web app deployment:

```bash
clasp deploy -d "HF archive export"     # creates/updates a versioned deployment
```

`clasp deploy` prints the deployment's web app URL
(`https://script.google.com/macros/s/<deployment id>/exec`); that, plus the
token from `setup()`, is what the publishing script needs. `clasp push`
alone only updates the `@HEAD` version live in the editor - the `/exec` URL
serves the last `clasp deploy`, so re-run `clasp deploy` (or
`clasp redeploy <deploymentId>`) after every future `clasp push` to put
changes live.

## Request / response contract

Base URL is whatever `clasp deploy` printed, e.g.
`https://script.google.com/macros/s/AKfycb.../exec`.

| Request | Response |
| --- | --- |
| `?token=<token>&tab=atl` | 200, `Content-Type: text/csv`, the "HF Data - Atl" tab as CSV (header row included) |
| `?token=<token>&tab=pac` | 200, `Content-Type: text/csv`, the "HF Data - Pac" tab as CSV |
| `?token=<token>&tab=list` | 200, `Content-Type: text/plain`, newline-separated actual tab names - a setup/debugging aid, not part of normal publishing |
| missing/wrong `token`, `EXPORT_TOKEN` unset, missing/unknown `tab`, no matching sheet, or any unhandled exception | 200, `Content-Type: text/plain`, body starting with the fixed prefix `HFArchiveExport error: ` |

So the two URLs the publishing script actually calls are:

```
https://script.google.com/macros/s/<deployment id>/exec?token=<token>&tab=atl
https://script.google.com/macros/s/<deployment id>/exec?token=<token>&tab=pac
```

**Apps Script cannot set an HTTP status code.** `ContentService` responses
always come back as HTTP 200, success or failure, so the publishing script
cannot distinguish them by status - it has to sniff the body. That is why
every error response here is plain prose beginning with the fixed
`HFArchiveExport error: ` prefix and never resembles CSV (no header row
shaped like `ID,date,Latitude,...`, no data rows), so a check as simple as
"does the body start with `HFArchiveExport error:` " reliably tells success
from failure. If NOAA's egress or Google's edge ever returns a real non-200
(a network failure before Apps Script even runs, an auth wall, etc.), the
publishing script will see that as an HTTP-level failure the normal way;
only *this script's own* error conditions are conveyed via body content.

Tab matching is loose on purpose (see `findSheet_` in `Code.gs`): the tab
name is lowercased, non-alphanumerics collapsed to spaces, and matched by
substring against `atl` / `pac`. Renaming "HF Data - Atl" to "Atlantic" (or
"HF-Data_ATL", or anything else containing "atl") keeps working without a
code change. `tab=list` returns the sheet's actual tab names verbatim so a
rename that breaks the match is easy to diagnose.

## Security

Read this before putting anything new in the spreadsheet.

- **What this exposes.** Anyone who has both the deployment URL and the
  current token can fetch the full, current contents of the "HF Data - Atl"
  and "HF Data - Pac" tabs, in full, as many times as they like. The
  published climatology site already re-publishes the same rows (derived
  through `build_hf_lows.py`), so this endpoint does not expose data the
  site doesn't already make public - but it does mean **nothing should ever
  be added to those two tabs that isn't fit to publish**, including scratch
  columns, internal notes in a cell, or an ID scheme that encodes something
  sensitive. Other tabs in the same spreadsheet are not read by this script
  and are not exposed by it, but keep in mind the deploy runs with the
  owner's full read access to the file it's bound to - only this code's own
  restraint (reading exactly `SPREADSHEET_ID`'s two named tabs) limits what
  it can see.
- **What the token is, and isn't.** The token is obfuscation against casual
  discovery, not authentication. It is a static, unexpiring bearer value
  passed in a URL query string - it will end up in web server logs, shell
  history, and possibly browser history on whatever machine runs the
  publishing script. It stops a stranger from finding this endpoint by
  guessing URLs or scanning Apps Script's `/macros/s/` namespace; it does
  **not** stand up to the token itself leaking. Treat a leaked token as
  equivalent to the data itself being public, and rotate it (below) if that
  happens.
- **What `ANYONE_ANONYMOUS` / `USER_DEPLOYING` means.** `executeAs:
  USER_DEPLOYING` runs every request with the permissions of whoever ran
  `clasp deploy` (the sheet owner) - that's what lets a caller with no NOAA
  credentials read a NOAA-restricted sheet at all. `access:
  ANYONE_ANONYMOUS` means Google itself performs no authentication on the
  request; every caller, NOAA or not, signed in or not, reaches `doGet()`
  and is gated only by the token check inside it. Together they are what
  make this whole approach work, and together they are exactly why the
  token check must never be skipped or bypassed.
- **If NOAA Workspace policy blocks `ANYONE_ANONYMOUS` deployments** (some
  Workspace configurations do, since it is the broadest web app access
  level), this whole approach is blocked at the deploy step and there is no
  Apps Script workaround: an org policy that disallows anonymous web apps
  is enforced before your own `doGet()` code ever runs. The fallback is
  manual: from the Sheets UI, download each of the two tabs as CSV
  (File > Download > Comma-separated values, per tab) and place them where
  `tools/build_hf_lows.py` expects its inputs, then run the publishing
  script with `--no-fetch` so it builds from those local files instead of
  trying to reach this endpoint.

### Rotating the token

1. In the Apps Script editor for this project, select `setup` and click Run
   again. It overwrites `EXPORT_TOKEN` with a freshly generated value and
   logs it - the old token stops working immediately, since there's only
   ever one token stored.
2. Copy the new token from the log (View > Logs / Executions) into the
   publishing box's config, replacing the old one.
3. No redeploy is required - Script Properties are read live on every
   request, not baked into a deployment.
