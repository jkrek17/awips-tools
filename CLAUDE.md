# awips-tools

AWIPS/GFE procedures for marine forecasting, a JTWC tropical cyclone wind
field tool with an Apps Script web app, and a static archive site for
hurricane force extratropical lows. `README.md` says what each part is and
why it is built that way; this file is only what you cannot infer from the code.

## Generated files - never hand-edit

| Path | Regenerate with |
|---|---|
| `docs/data/` | `python3 tools/build_hf_lows.py` (coastlines/currents: `tools/build_coastlines.py`, `tools/build_currents.py`) |
| `flat/` | `python3 tools/publish.py --no-fetch --deploy flat --flat --yes`, then `rm -f flat/.awips-publish-manifest.json` and copy `docs/data/hf-lows.js`, `hf-lows.json`, `qc-report.txt` into `flat/` so the trees stay byte-identical. CI fails if `flat/` drifts from `docs/`. |
| `web/TCWind_JTWC/BestTrackData.gs` | `python3 tests/tcwind_jtwc/prep_besttrack_data.py` |
| `tests/tcwind_jtwc/data/gtcm_findings.json` | `python3 tests/tcwind_jtwc/verify_gtcm.py` (slow; only when the vortex changes) |

A PreToolUse hook refuses edits to these. Change the source and regenerate.

## Single-source modules

- `web/TCWind_JTWC/Vortex.html` is the only client-side definition of
  `resolveRmax`, `fitGTCM`, `gtcmProfile`, `gtcmUV`, `parseJTWC`,
  `willoughbyRmax`. `Theme.html` is the only design system. No page may
  define its own copy; include them with `<?!= ... ?>`. Duplicates have
  shipped wrong numbers four times.
- `Code.gs` keeps its own server-side `parseJTWC()` because Apps Script
  cannot include an HTML script block. `parserFingerprint()` and
  `checkParserParity()` detect it drifting; run them after deploy.
- `GFE/procedures/TCWind_JTWC.py` is the Python reference for the same math.
  `tests/tcwind_jtwc/compare_py_js.py` is what catches the ports diverging.

## Before every push

```bash
python3 tests/tcwind_jtwc/test_parser_golden.py                 # parser vs fixtures
python3 tests/tcwind_jtwc/compare_py_js.py                      # Python vs both JS ports
python3 tests/tcwind_jtwc/validate_pages.py web/TCWind_JTWC/*.html
html-validate docs                                              # what Pages CI runs, pinned 11.15.0
```

All four are hermetic. The SessionStart hook installs numpy and html-validate
in web sessions so they run. `validate_pages.py` exists because a regex check
once passed a truncated page; do not replace it with `node --check`.

Not runnable here: anything under `GFE/` needs a live AWIPS/GFE. Review those
by reading, say so in the summary, and point at `VALIDATION.md` for the
manual scenarios.

## Secrets

`tools/publish.local.json` holds the HF export URL and token. `~/.clasprc.json`
holds a Google refresh token. Never read either into context or commit them.

## Dangerous commands

- `clasp deploy` must carry `-i <existing deployment id>`. Without it a new
  deployment with a new URL is created and everyone keeps the old link. Full
  procedure in `.claude/skills/clasp/SKILL.md`.
- `tools/publish.py --deploy` writes to a web root. Never run it with a real
  target from here; `--deploy flat --flat` is the only in-repo use.

## Commits

One imperative subject line, no body unless the why is non-obvious, optional
area prefix (`CI:`, `publish.py:`). Work on a branch and merge into `main`;
never commit to `main` directly. Every push to `main` touching `docs/`,
`flat/` or `data/hf_lows/` deploys the Pages preview.

## Conventions

- The TC tool is EXPERIMENTAL and NOT OPERATIONALLY VETTED. Keep that
  disclaimer on every user-facing page and README section about it.
- Vanilla HTML/CSS/JS only under `docs/`. No framework, no CDN, no `fetch()`;
  data ships as `window.HF_*` assignments so `file://` works.
- `tests/tcwind_jtwc/README.md` and `VALIDATION.md` are partly stale. Trust
  the root README and the code over them.
