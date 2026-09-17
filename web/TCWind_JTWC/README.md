# TCWind_JTWC — web app

**EXPERIMENTAL. NOT OPERATIONALLY VETTED.**

Four pages served from one Apps Script deployment, sharing the wind-field
math with the GFE procedure `GFE/procedures/TCWind_JTWC.py`. See the repository
root `README.md` for what the project is and why it is built this way.

| `?page=` | file | what it is for |
|---|---|---|
| `live` (default) | `Index.html` | the five live JTWC bulletins, parsed, on a map, with the GTCM fit diagnostics |
| `archive` | `Archive.html` | 220 best-track storms across three basins, replayed through the same code |
| `findings` | `Findings.html` | what the verification shows, and what it does not |
| `lab` | `Lab.html` | **research only.** Scores two candidate extratropical-transition terms against best track. Not linked from the other three, and nothing it exercises is in the tool |

## Files

| file | role |
|---|---|
| `Code.gs` | server: bulletin fetch and cache, `doGet()` routing, the archive/findings data endpoints, and the server-side parser |
| `Vortex.html` | **the** client-side GTCM vortex + JTWC parser. Included by every page |
| `Theme.html` | **the** design system: tokens, both themes, typography. Included by every page |
| `Index.html`, `Archive.html`, `Findings.html` | the three forecaster-facing pages |
| `Lab.html` | the research page. Reads `getEtRecords()`; exercises the default-off `opts` on `fitGTCM`/`vortexFieldGTCM` |
| `BestTrackData.gs` | generated archive payload, ~2 MB. Never hand-edit — regenerate with `tests/tcwind_jtwc/prep_besttrack_data.py` |
| `appsscript.json` | manifest. `webapp.access` is `DOMAIN` |
| `.clasp.json` | clasp binding (script ID only, no credentials) |

## One copy of everything

`Vortex.html` and `Theme.html` exist because duplicated logic has caused four
separate bugs in this project: a second `resolveRmax()` using `<=` where the
tool used `<`, a second `parseJTWC()`, a second `r34` calculation in the
verification, and a second colour palette. Three of them shipped wrong numbers
or wrong rendering.

**No page may define its own copy of anything in `Vortex.html`** — not
`resolveRmax`, `fitGTCM`, `gtcmProfile`, `gtcmUV`, `parseJTWC`, or
`willoughbyRmax`. Include it:

```html
<?!= HtmlService.createHtmlOutputFromFile('Vortex').getContent(); ?>
<?!= HtmlService.createHtmlOutputFromFile('Theme').getContent(); ?>
```

(`<?!=` rather than `<?=` because this is our own trusted markup, not user data.)

`Code.gs` is the one legitimate exception: Apps Script cannot include an HTML
file's script block server-side, so it keeps its own `parseJTWC()`.
`parserFingerprint()` and `checkParserParity()` exist to detect that copy
drifting from the canonical one.

## The experimental terms, and why the default path is sacred

`Vortex.html` carries two terms that are **not in the Users Guide and not in
the Python**: an extratropical-transition prior on eqs. (5)/(6), and a
wavenumber-2 elongation. They are reachable only by passing an `opts` object to
`fitGTCM()` or `vortexFieldGTCM()`. `Lab.html` is the only caller that does.

The asymmetry is deliberate. `GFE/procedures/TCWind_JTWC.py` is the reference
implementation and `compare_py_js.py` holds the two ports to 0.5 kt, so
anything default-on has to exist in the Python first. These are default-off
precisely so they can be measured before that cost is paid.

That makes one invariant load-bearing above all others:

> With no opts - or with empty or zeroed opts - the field must be exactly what
> it was before these terms existed.

`compare_py_js.py` cannot catch a violation on its own: it knows nothing about
`opts`, and its tolerance would swallow a small systematic shift anyway. So
`tests/tcwind_jtwc/verify_experiments.js` compares **bit patterns**, across
three spellings of "no experiment" (absent, `{}`, and explicitly zeroed) on
eight storm-times covering every `freeParams` branch, both hemispheres, zero
motion and the fast-and-weakening case - about 59,000 values.

Two notes for anyone extending this:

* Guard every option with `if (o.x)` rather than multiplying by an identity.
  `rmc * 1.0` happens to be exact, but the invariant above is that the default
  path executes the *same arithmetic*, not arithmetic that agrees.
* The elongation needed no new profile code. `gtcmProfile` is scale-covariant
  in radius - `gtcmProfile(r/s, rm, ri)` is identically
  `gtcmProfile(r, rm*s, ri*s)` - so elongating the vortex is a per-azimuth
  radius scale, and one shared radial profile array still serves every azimuth.
  `verify_experiments.js` checks that identity, because if it ever stops
  holding the shared array is wrong.

## Before pushing

```bash
python3 tests/tcwind_jtwc/validate_pages.py web/TCWind_JTWC/*.html
python3 tests/tcwind_jtwc/compare_py_js.py
node    tests/tcwind_jtwc/verify_experiments.js
```

`validate_pages.py` catches truncated files and unbalanced tags. It exists
because a hand-rolled check once passed a half-written page: it extracted
script blocks with a regex needing a closing `</script>`, found none in the
truncated file, and `node --check` trivially passed on an empty string.

`compare_py_js.py` drives the Python and both JavaScript ports on identical
inputs. Tolerances are 0.5 kt, 1 nm, 1 degree; actual divergence is around
4e-06 kt. If you change the vortex or the parser on either side, this is the
test that catches it.

`verify_experiments.js` is what stops an experimental term leaking into the
field every forecaster sees. Run it on any change to `Vortex.html`, not just
changes to the experiments.

In the Apps Script editor after deploying: `runSelfTest()`, `runDataSelfTest()`,
`parserFingerprint()`. Check `?page=lab` loads and scores; it is the only page
that calls `getEtRecords()`, whose payload is ~230 KB on one round trip.

## Deploying

Full detail in `.claude/skills/clasp/SKILL.md`, including the headless OAuth
flow if you are deploying from a container rather than a workstation.

```bash
npm install -g @google/clasp
clasp login
cd web/TCWind_JTWC
clasp push                    # updates @HEAD, which the /dev URL serves
clasp list-deployments        # find the existing deployment id
clasp deploy -i <that id> -d "what changed"
```

**`clasp deploy` without `-i` creates a new deployment with a new URL**,
leaving everyone holding the old link on the old build. Always redeploy in
place unless you specifically want a separate deployment.

`clasp push` alone does not change what the `/exec` URL serves — that keeps
showing the last versioned deployment until `clasp deploy` runs. Pushing first
and checking `@HEAD` on the `/dev` URL is the safe order.
