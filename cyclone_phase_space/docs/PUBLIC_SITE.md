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
2. Generate a deploy key on your own machine:

   ```
   ssh-keygen -t ed25519 -N "" -C "site-publish" -f site_publish_key
   ```

3. In the public repository: Settings > Deploy keys > Add deploy key,
   paste `site_publish_key.pub`, tick "Allow write access".
4. In this repository: Settings > Secrets and variables > Actions:
   - New repository secret `WEB_DEPLOY_KEY` with the contents of the
     private file `site_publish_key`.
   - New repository variable `PUBLIC_SITE_REPO` with the value
     `jkrek17/web`.
   Delete the local key files afterwards.
5. Run Actions > "Publish public site" > Run workflow once. It assembles
   the site and force-pushes it as the single commit of the public
   repository's `main` branch.
6. In the public repository: Settings > Pages > Source "Deploy from a
   branch", branch `main`, folder `/ (root)`. The map is then at
   `https://jkrek17.github.io/web/`.
7. Make this repository private whenever you want. Two consequences:
   the article at `jkrek17.github.io/awips-tools/cps/` stops being served
   (Pages needs a public repository on a free account), so move the
   article to the public site first or accept the gap; and the `cps-live`
   branch becomes private, which is fine because the public site carries
   its own copy of the data.

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
