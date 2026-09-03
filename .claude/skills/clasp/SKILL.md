---
name: clasp
description: Deploy the TCWind_JTWC Apps Script web app with clasp from a cloud container - install, the non-interactive OAuth dance, push, and redeploy in place so the /exec URL is preserved. Use when asked to deploy, push to Google, publish the web app, or update the Apps Script project.
---

# Deploying TCWind_JTWC with clasp

The web app lives in `web/TCWind_JTWC/` and is bound to script
`1CQgCmEB7Xpj0Sqi_hjD1LSPIoMX4gOWoIzupRs_gUvSdFZk2viIZaH9i` via `.clasp.json`.

**Before touching any of this, tell the user what the OAuth grant covers and let
them choose.** clasp requests `cloud-platform` (full Google Cloud access) and
`drive.file` alongside the three `script.*` scopes it actually needs, and the
refresh token lands in `~/.clasprc.json` inside an ephemeral container. Doing it
on their own machine takes two commands and keeps the token there. They may
still say proceed - that is their call, not a reason to refuse - but they should
make it knowing the scope list.

## 1. Install

Not preinstalled. `npm install -g @google/clasp` (~30 s, lands in
`/opt/node22/bin/clasp`).

## 2. Log in without a browser

`clasp login` wants to open a browser and listen on localhost:8888. Neither
works here, so use `--no-localhost`, which prints a URL and waits on **stdin**
for the redirect URL pasted back.

The catch: it blocks on stdin, and a plain background job gets EOF immediately
and dies. Hold the FIFO open with a long-running writer:

```bash
S=/path/to/scratchpad
rm -f $S/claspin; mkfifo $S/claspin
( sleep 3000 > $S/claspin ) &          # holds the FIFO open - load-bearing
cd web/TCWind_JTWC
nohup clasp login --no-localhost < $S/claspin > $S/clasp_login.txt 2>&1 &
sleep 8
sed -e 's/\x1b\[[0-9;]*[A-Za-z]//g' $S/clasp_login.txt \
  | grep -o 'https://accounts.google.com[^ ]*' | head -1
```

Give that URL to the user. Their browser will fail to load
`http://localhost:8888/?code=...` - that is expected, nothing is listening.
They paste the whole failed URL back. Feed it in:

```bash
printf '%s\n' '<the pasted redirect URL>' > $S/claspin
sleep 12
sed -e 's/\x1b\[[0-9;]*[A-Za-z]//g' $S/clasp_login.txt | tail -4   # "You are logged in as ..."
ls -la ~/.clasprc.json
```

Things that will bite:
- **The URL embeds a PKCE challenge tied to that specific process.** If the
  container restarts before the code comes back, the process dies and the URL
  is dead with it. Generate a fresh one; do not reuse.
- Strip ANSI escapes before grepping - clasp writes a spinner and colour codes
  into the log and the URL is wrapped across lines without it.
- The user must authorise as the account owning the script, or the push fails
  on permissions rather than on anything in the code.

## 3. Push

```bash
cd web/TCWind_JTWC
clasp status          # confirm the file list first
clasp push --force
```

Nine tracked files: `appsscript.json`, `Code.gs`, `BestTrackData.gs`,
`Index.html`, `Archive.html`, `Findings.html`, `Vortex.html`, `Theme.html`,
`Help.html`. `.clasp.json` and `README.md` are untracked and stay local.

`Vortex.html` (shared vortex + parser JS), `Theme.html` (design tokens) and
`Help.html` (shared glossary tooltips) are
included by the pages that need them via
`HtmlService.createHtmlOutputFromFile(...)`. If any fails to upload, every
page breaks rather than degrading - so check the push list, do not assume.

`BestTrackData.gs` is ~2 MB and **generated**. Never hand-edit it; regenerate
with `tests/tcwind_jtwc/prep_besttrack_data.py`.

## 4. Deploy - redeploy in place, do not create a new one

This is the step that is easy to get wrong and hard to undo.

```bash
clasp list-deployments
# -> AKfycbx...Drx0XfG6Fbzj9HCx2C9RC @NN - <description>   <- the /exec URL binds to THIS id
clasp deploy -i <that deployment id> -d "<what changed>"
```

`clasp deploy` **without `-i` creates a new deployment with a new URL**, leaving
everyone holding the old link on the old build. Always pass `-i` with the
existing id unless the user explicitly wants a separate deployment.

`clasp push` only updates `@HEAD`, which the `/dev` URL serves. The `/exec` URL
keeps serving the last versioned deployment until `clasp deploy` runs. Pushing
first and checking `@HEAD` before deploying is the safe order.

## 5. Verify

Web app URL: `https://script.google.com/macros/s/<deploymentId>/exec`, plus
`?page=archive` and `?page=findings`.

In the Apps Script editor, `Code.gs` provides:
- `runSelfTest()` - parser against the built-in fixture
- `runDataSelfTest()` - archive and findings datasets load and have the
  expected shape
- `parserFingerprint()` / `checkParserParity()` - whether the server-side
  `parseJTWC()` has drifted from the canonical one in `Vortex.html`. Apps
  Script cannot include an HTML file's script server-side, so that duplicate
  is deliberate and this is how it is policed.

Locally, before any push:

```bash
python3 tests/tcwind_jtwc/validate_pages.py web/TCWind_JTWC/*.html
python3 tests/tcwind_jtwc/test_parser_golden.py
python3 tests/tcwind_jtwc/compare_py_js.py
```

`validate_pages.py` exists because a hand-rolled check once passed a
half-written file: it extracted script blocks with a regex needing a closing
`</script>`, found none in a truncated file, and `node --check` trivially
passed on an empty string. It now fails loudly when no blocks are found.

## 6. Access

`appsscript.json` has `webapp.access: DOMAIN` - anyone at noaa.gov. Widening or
narrowing that is the user's decision, not a default to change while doing
something else.
