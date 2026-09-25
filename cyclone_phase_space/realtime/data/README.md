# Daily CPS collection

Written by `../collect_daily.py`, run every day at 20 UTC by the
`CPS daily collection` workflow (`.github/workflows/cps_daily.yml`) on the
12 UTC GFS run, which commits this folder and `../watch.json` to main. See
`../README.md`, "Daily collection", for how it works and how to add a
storm. Experimental; not operationally vetted.

    data/
      log.csv                 one row per cycle and storm: cycle, storm, fsu_number, status
      <cycle>/                GFS cycle, YYYYMMDDHH (12 UTC runs)
        summary.md            table of the storms of the run
        <NAME>/               one storm of watch.json
          meta.json           seed used, start and end hours and positions, onset and
                              completion hours (standard and Hart bands), class
                              sequence, FSU cyclone number and position (or null)
          track.csv           track table, as track_<NAME>.csv of gfs_cps.py --track
          phase.png           phase diagrams, as phase_<NAME>.png, downscaled to 1600 px
          fsu_phase1.png      FSU N.phase1.zoom.png (B against -V_T^L), when matched
          fsu_phase2.png      FSU N.phase2.zoom.png (-V_T^U against -V_T^L), when matched
          fsu_track.png       FSU N.track.png, when matched
          compare.png         the two FSU diagrams (top) above phase.png (bottom), 2048 px wide

Statuses in `log.csv` and `meta.json`: `ok` (tracked), `lost` (no closed
low within 400 km of the seed; the storm was marked inactive in
`watch.json` and its folder holds only `meta.json`), `error` (the frame at
the seed hour could not be fetched; the storm stays active). A
`fsu_number` is blank when no FSU cyclone was within 400 km of the
storm's first fix or the FSU page could not be read.

Track columns, the diagram layout and the onset and completion
definitions are described in `../README.md`, "Storm-following phase
diagrams". FSU's diagrams are from
http://moe.met.fsu.edu/cyclonephase/gfs/fcst/archive/ and remain theirs;
they are kept here only for side-by-side comparison.
