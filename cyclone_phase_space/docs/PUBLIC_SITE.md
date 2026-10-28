# Public site from a private repository

The live map is published to a separate public repository so that this
repository can be private. The public repository holds only the built
site: the map page, the newest cycle's data and the storm diagrams. No
source, tests, figure scripts or collection code go there.

## Layout of the public repository (branch main, served by Pages at the root)

```
index.html       the projects index, rebuilt on each publish (tools/build_site_index.py)
cyclone/         the map page: index.html, style.css, app.js, storms.js, card.js, space3d.js, fonts/
globe-kit/       MapLibre and the shared globe look and script the map pages load (globe_kit/)
cyclone/data/latest/   index.json, legend.json, history.json, frames/f{hhh}/...
cyclone/data/storms/<cycle>/<NAME>/   phase.png, compare.png, meta.json, track.csv
article/         the article and its figures
forecasters/     the plain-language guide
.nojekyll
phillies/        kept: published by jkrek17/codex, copied forward on each push
lsr/             kept: published by jkrek17/lsrMap (lsr/ = main, lsr/next/ = test branch)
wind/            kept: published by jkrek17/wind-particles (forecast map, data rebuilt every 6 h)
```

Each publish replaces the whole branch, so every top-level folder this
site does not write (anything not in `OWN_FOLDERS` in the workflow) is
copied forward from the current public `main` before the push. Another
project only has to push its own folder to the public repository; it
needs no change here.

The root page lists every top-level folder that has an `index.html`,
with any `index.html` one level down (`lsr/next/`) under its parent. Each
entry takes the page's `<title>` and `<meta name="description">`, so a
project fixes its own entry by fixing those; a title starting
`[test: name]` gets a test tag. A new folder appears on the next publish.

The map finds its data at `data/latest/` beside it when served this way, falls
back to the `cps-live` branch of this repository if that is public, and
accepts `?data=<url>` for tests.

## One-time setup

1. Create the public repository (for example `jkrek17/web`), empty, public.
2. Create a fine-grained personal access token: GitHub > Settings >
   Developer settings > Personal access tokens > Fine-grained tokens >
   Generate new token. Resource owner: your account. Repository access:
   "Only select repositories", pick `web`. Permissions: Repository
   permissions > Contents > Read and write (Metadata read is added
   automatically). Expiration: as long as GitHub allows (one year); note
   the date, since publishing stops when it expires and you generate a
   new one the same way.
3. In this repository (`awips-tools`): Settings > Secrets and variables >
   Actions:
   - New repository secret `WEB_TOKEN` with the token.
   - New repository variable `PUBLIC_SITE_REPO` with the value
     `jkrek17/web`.
4. Run Actions > "Publish public site" > Run workflow once. It assembles
   the site and force-pushes it as the single commit of the public
   repository's `main` branch.
5. In the public repository: Settings > Pages > Source "Deploy from a
   branch", branch `main`, folder `/ (root)`. The projects index is then
   at `https://jkrek17.github.io/web/`.

## The cyclone phase space site (its own repository)

The live map, the article and the forecasters' guide are published on a
site of their own, with no link to the projects site, so they can be
shared on their own: `cyclone_publish.yml` pushes them to the public
repository `jkrek17/cyclone` (the map at the root, loading the globe
kit as `globe-kit/`, its data under `data/`, the article at `article/`
with the interactive 3-D phase space at `article/figures/`, and the
guide at `forecasters/`; the pages link to each other with relative
links). It runs after every live export and daily collection, on a push
that changes the pages, and by hand. One-time setup:

1. Create the public repository `jkrek17/cyclone` (empty or with a
   README; the first publish replaces its `main`).
2. Create a fine-grained token as in step 2 above, with repository
   access to `cyclone` only and Contents: Read and write.
3. In `awips-tools`: Settings > Secrets and variables > Actions > New
   repository secret `CYCLONE_TOKEN` with the token. (A repository
   variable `CYCLONE_SITE_REPO` overrides the repository name; it is
   not needed for `jkrek17/cyclone`.)
4. Run Actions > "Publish cyclone site" > Run workflow once.
5. In `jkrek17/cyclone`: Settings > Pages > Source "Deploy from a
   branch", branch `main`, folder `/ (root)`. The map is then at
   `https://jkrek17.github.io/cyclone/`, the article at
   `https://jkrek17.github.io/cyclone/article/` and the guide at
   `https://jkrek17.github.io/cyclone/forecasters/`.

The projects site no longer carries these pages: `site_publish.yml`
owns the `cyclone/`, `article/` and `forecasters/` folders without
writing them, so they drop off `jkrek17/web` at its next publish and the
old `/web/cyclone/` links stop working.
6. Make this repository private whenever you want. Two consequences:
   the article at `jkrek17.github.io/awips-tools/cps/` stops being served
   (Pages needs a public repository on a free account), so move the
   article to the public site first or accept the gap; and the `cps-live`
   branch becomes private, which is fine because the public site carries
   its own copy of the data.

A deploy key (an SSH key pair attached to the public repository) works
the same way if preferred: it never expires and reaches one repository
only. The workflow as shipped uses the token.

## What runs afterwards

- `CPS live map data` (every 6 h) exports the newest cycle to the
  `cps-live` branch, with the daily collection's storm diagrams beside it.
- `CPS daily collection` (20 UTC) follows the watched storms and commits
  their tracks and diagrams to `main`.
- `Publish public site` runs after each of those and on any push that
  changes the page, and skips quietly until the secret and variable exist.

## Moving the article later

Add the article directory to the assembled site under `cps/` in
`.github/workflows/site_publish.yml` (one `cp -r` line), change the
page's `ARTICLE_URL` constant to `../cps/`, and re-run the publish.
