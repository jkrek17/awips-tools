# Cyclone Phase Space article (GitHub Pages)

The repository's GitHub Pages site is served from the `docs/` folder on
`main`, which already hosts another page at the site root. This article's
source lives at `cyclone_phase_space/article/`; the Pages workflow
(`.github/workflows/pages.yml`) stages a copy of it to `docs/cps/` on every
build, so it publishes at

    https://jkrek17.github.io/awips-tools/cps/

`docs/cps/` itself is gitignored and never committed - it is generated at
build time.

Regenerate every figure (from the repo root, needs numpy, matplotlib,
Pillow):

```
python3 cyclone_phase_space/article/figures/make_figures.py
```

This overwrites the six files in `cyclone_phase_space/article/figures/`
(five PNGs computed from
`cyclone_phase_space/D2D/derivedParameters/functions/cps_HartCPS.py` and
`cyclone_phase_space/cps/hart.py` on synthetic fields, plus
`fig6_cave_typhoon.jpg`, a crop and resize of a real CAVE screenshot). It
prints Figure 4's tilt check and Figure 5's timings.
