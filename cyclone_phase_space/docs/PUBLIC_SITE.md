# Public site from a private repository

The live map is published to a separate public repository so that this
repository can be private. The public repository holds only the built
site: the map page, the newest cycle's data and the storm diagrams. No
source, tests, figure scripts or collection code go there.

## Layout of the public repository (branch main, served by Pages at the root)

```
index.html, style.css, app.js, basemap.js, basemap/   the map page
data/latest/     index.json, legend.json, history.json, frames/f{hhh}/...
data/storms/<cycle>/<NAME>/   phase.png, compare.png, meta.json, track.csv
.nojekyll
```

The page finds its data at `data/latest/` when served this way, falls
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
   branch", branch `main`, folder `/ (root)`. The map is then at
   `https://jkrek17.github.io/web/`.
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
