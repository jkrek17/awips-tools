# Cyclone Phase Space article (GitHub Pages)

Enable Pages: repo Settings -> Pages -> Build and deployment -> Source:
"Deploy from a branch" -> Branch: this branch
(`claude/cyclone-phase-space-modern-9yw344`), folder `/docs` -> Save.
The site publishes at `https://<owner>.github.io/<repo>/` within a
few minutes; `.nojekyll` here skips Jekyll processing.

Regenerate every figure (from the repo root, needs numpy, matplotlib,
Pillow):

```
python3 docs/figures/make_figures.py
```

This overwrites the six files in `docs/figures/` (five PNGs computed
from `D2D/derivedParameters/functions/HartCPS.py` and `CycloneCore.py`
on synthetic fields, plus `fig6_cave_typhoon.jpg`, a crop/resize of a
real CAVE screenshot). It prints Figure 4's tilt/dipole check and
Figure 5's timings; re-run `git diff --stat docs/figures` to confirm
what changed before committing.
