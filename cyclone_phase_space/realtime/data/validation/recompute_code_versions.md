# Recompute of the daily archive: runs and code versions

All 26 cycles were recomputed on 2026-10-18 with `collect_daily.py --cycle <cycle> --force`, two at a time, oldest first. Each run used a per-cycle watch list holding the seeds recorded in that cycle's archived meta.json files (see archive_before_after.md). The GRIB cache was deleted after each run. Cycles whose FSU archive page is gone (all before 2026101412) ran with --no-fsu, and their FSU matches were restored offline afterwards by restore_fsu_matches.py. The four newest cycles ran with the FSU step.

## Collector code

The meta.json stamp (code_version) is `git rev-parse --short HEAD` at the start of the run, plus -dirty when tracked files outside data/ and watch.json had uncommitted changes. Other work was being committed to the same checkout during the recompute, so HEAD moved from cf3f24f to 7b65306 while the runs went on. None of those commits touched the collector code. `git log -p cf3f24f..05a681c` over collect_daily.py, gfs_cps.py, track_cps.py, D2D/derivedParameters/functions/cps_HartCPS.py, article/figures/diagram_style.py, realtime/requirements.txt and nwp/ is empty: no commit, empty diff. The -dirty stamps come from uncommitted edits to other files (export_web.py, README.md and the article's live page, committed later as 4d645b0, 7d2d589 and af87d1d). The files of the collector were last modified on disk before the recompute began: cps_HartCPS.py, diagram_style.py and track_cps.py at 2026-10-17 23:30 UTC, gfs_cps.py and nwp at 23:53, collect_daily.py at 23:59 (the code_version change, committed unchanged as cf3f24f at 00:00:07). The first run started at 00:00:41. Every cycle was therefore computed with the collector code of cf3f24f, whatever its stamp says.

## Per cycle

| Cycle | Started (UTC) | Minutes | GRIB source (frames) | FSU step | Result | Storm-cycles | code_version in meta.json |
|---|---|---|---|---|---|---|---|
| 2026092412 | 00:00 | 6.1 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 9 | cf3f24f |
| 2026092418 | 00:00 | 6.1 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 9 | cf3f24f |
| 2026092512 | 00:06 | 6.3 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | cf3f24f-dirty |
| 2026092612 | 00:06 | 6.4 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | cf3f24f-dirty |
| 2026092712 | 00:13 | 6.0 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | 4d645b0-dirty |
| 2026092812 | 00:13 | 5.9 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 6 | 4d645b0-dirty |
| 2026092912 | 00:19 | 6.1 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 6 | 4d645b0-dirty |
| 2026093012 | 00:19 | 6.0 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 6 | 4d645b0-dirty |
| 2026100112 | 00:25 | 5.9 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 7 | 4d645b0-dirty |
| 2026100200 | 00:25 | 5.9 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 6 | 4d645b0-dirty |
| 2026100212 | 00:31 | 5.6 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 6 | af87d1d |
| 2026100312 | 00:31 | 5.7 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | af87d1d |
| 2026100412 | 00:36 | 5.7 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | a85cc99 |
| 2026100512 | 00:36 | 5.6 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | a85cc99 |
| 2026100612 | 00:42 | 5.3 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | a85cc99 |
| 2026100712 | 00:42 | 5.8 | AWS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | a85cc99 |
| 2026100812 | 00:47 | 5.7 | NOMADS (34) | no (page gone; restored offline) | ok, attempt 1 | 10 | a85cc99 |
| 2026100912 | 00:48 | 5.7 | NOMADS (34) | no (page gone; restored offline) | ok, attempt 1 | 10 | a85cc99 |
| 2026101012 | 00:53 | 4.9 | NOMADS (34) | no (page gone; restored offline) | ok, attempt 1 | 7 | a85cc99 |
| 2026101112 | 00:53 | 5.5 | NOMADS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | a85cc99 |
| 2026101212 | 00:58 | 5.6 | NOMADS (34) | no (page gone; restored offline) | ok, attempt 1 | 7 | a85cc99 |
| 2026101312 | 00:59 | 5.6 | NOMADS (34) | no (page gone; restored offline) | ok, attempt 1 | 8 | a85cc99 |
| 2026101412 | 01:03 | 5.7 | NOMADS (34) | yes | ok, attempt 1 | 10 | a85cc99 |
| 2026101512 | 01:05 | 5.1 | NOMADS (34) | yes | ok, attempt 1 | 9 | a85cc99 |
| 2026101612 | 01:09 | 5.4 | NOMADS (34) | yes | ok, attempt 1 | 10 | 7b65306 |
| 2026101712 | 01:10 | 5.5 | NOMADS (34) | yes | ok, attempt 1 | 13 | 7b65306 |

## Re-run of 24 September 2026 after the rise-cap fix

The recompute above ended the eastern Pacific hurricane's tracks at
+6 h (2026092412, AUTO_260924_06) and at 0 h (2026092418,
AUTO_260924_01), because GFS fills the eye by 14 to 15 hPa in 6 h and
the flat 12 hPa rise cap refused the real center. Commit d1848fc made
the allowed rise grow with the depth of the last fix
(`track_cps.max_rise`), and the two cycles were re-run with the same
frozen seeds and the FSU step off, the matches restored offline as
before. Stamps: 2026092412 carries 047e914 and 2026092418 e957235
(commits that touch only the README, the article and the validation
scripts after d1848fc). The hurricane now runs to +198 h and +126 h;
the other storms of the two cycles are unchanged.
