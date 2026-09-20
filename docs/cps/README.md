# Cyclone Phase Space article (GitHub Pages)

The repository's GitHub Pages site is served from the `docs/` folder on
`main`, which already hosts another page at the site root. This article
therefore lives at `docs/cps/` and publishes at

    https://jkrek17.github.io/awips-tools/cps/

once this directory is on `main`. Nothing needs to change in the Pages
settings.

Regenerate every figure (from the repo root, needs numpy, matplotlib,
Pillow):

```
python3 docs/cps/figures/make_figures.py
```

This overwrites the six files in `docs/cps/figures/` (five PNGs computed
from `D2D/derivedParameters/functions/cps_HartCPS.py` and `cps/hart.py` on
synthetic fields, plus `fig6_cave_typhoon.jpg`, a crop and resize of a
real CAVE screenshot). It prints Figure 4's tilt check and Figure 5's
timings.
