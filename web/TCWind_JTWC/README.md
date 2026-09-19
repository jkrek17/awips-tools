# TCWind_JTWC — web app

**EXPERIMENTAL. NOT OPERATIONALLY VETTED.**

Three pages served from one Apps Script deployment, sharing the wind-field
math with the GFE procedure `GFE/procedures/TCWind_JTWC.py`. See the repository
root `README.md` for what the project is and why it is built this way.

| `?page=` | file | what it is for |
|---|---|---|
| `live` (default) | `Index.html` | the five live JTWC bulletins, parsed, on a map, with the GTCM fit diagnostics |
| `archive` | `Archive.html` | 220 best-track storms across three basins, replayed through the same code |
| `findings` | `Findings.html` | what the verification shows, and what it does not |

## Files

| file | role |
|---|---|
| `Code.gs` | server: bulletin fetch and cache, `doGet()` routing, the archive/findings data endpoints, and the server-side parser |
| `Vortex.html` | **the** client-side GTCM vortex + JTWC parser. Included by every page |
| `Theme.html` | **the** design system: tokens, both themes, typography. Included by every page |
| `Help.html` | **the** shared glossary: hover/tap term tooltips plus a drop-in glossary `<details>` block. Included by all three pages |
| `Index.html`, `Archive.html`, `Findings.html` | the three pages |
| `BestTrackData.gs` | generated archive payload, ~2 MB. Never hand-edit — regenerate with `tests/tcwind_jtwc/prep_besttrack_data.py` |
| `appsscript.json` | manifest. `webapp.access` is `DOMAIN` |
| `.clasp.json` | clasp binding (script ID only, no credentials) |

## One copy of everything

`Vortex.html` and `Theme.html` exist because duplicated logic has caused four
separate bugs in this project: a second `resolveRmax()` using `<=` where the
tool used `<`, a second `parseJTWC()`, a second `r34` calculation in the
verification, and a second colour palette. Three of them shipped wrong numbers
or wrong rendering.

`Help.html` follows the same rule for a smaller thing: the glossary. Before it
existed, adding a tooltip meant writing the same term/definition pair on
whichever page needed it next, which is exactly how the palette and
`resolveRmax()` drifted the first time. One `TERMS` list, one `linkify()`
function, one drop-in `<details>` block - see the comment at the top of
`Help.html` for how a page uses it.

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

## Before pushing

```bash
python3 tests/tcwind_jtwc/validate_pages.py web/TCWind_JTWC/*.html
python3 tests/tcwind_jtwc/compare_py_js.py
```

`validate_pages.py` catches truncated files and unbalanced tags. It exists
because a hand-rolled check once passed a half-written page: it extracted
script blocks with a regex needing a closing `</script>`, found none in the
truncated file, and `node --check` trivially passed on an empty string.

`compare_py_js.py` drives the Python and both JavaScript ports on identical
inputs. Tolerances are 0.5 kt, 1 nm, 1 degree; actual divergence is around
4e-06 kt. If you change the vortex or the parser on either side, this is the
test that catches it.

In the Apps Script editor after deploying: `runSelfTest()`, `runDataSelfTest()`,
`parserFingerprint()`.

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
