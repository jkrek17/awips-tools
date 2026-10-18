# Daily CPS archive audit, before the recompute

Code version at audit time: `05a681c` (git rev-parse --short HEAD). Data: `a copy of realtime/data as committed at a62c9ac, before the recompute`. Written by `archive_audit.py`.

211 storm-cycles in 26 cycles (2026092412 to 2026101712); 187 tracked (status ok), 19 lost, 5 merged.

Code version recorded in meta.json: `not recorded` 211.

Fix commit `6ca06b4`. Tracks whose last committed track.csv is from it or a commit descending from it: 128 of 187 (git log --ancestry-path; uncommitted files count as not after).

## Rule flags

- Terrain floor (min MSLP at or below 952 hPa, or a fix at exactly 950.0 hPa): 19 storm-cycles, 2 of them with a 950.0 hPa fix (2 fixes).
- Fixed reach (track_end "no minimum within ..." or mentioning reach): 62 storm-cycles; 7 of them moving faster than 60 km/h over the last step, where the speed-scaled reach is wider than the fixed one.
- Written before the fix (no code_version, last committed track.csv neither from the fix commit nor from one descending from it): 59 tracks; among them 5 with the terrain flag and 16 with the reach flag (2 fast). A flag on a track written after the fix is not a symptom: it is a deep low or an ordinary end of track under the current rules.

## End reasons

| End reason | Storm-cycles |
|---|---|
| outside a closed low | 76 |
| no minimum within reach | 62 |
| ran to the last hour | 39 |
| lost | 19 |
| merged into another track | 6 |
| merged | 5 |
| FHR1 reached | 2 |
| ran out of frames | 2 |

## Flagged storm-cycles

| Cycle | Storm | Min MSLP (hPa) | 950.0 fixes | Hours | Last step (km/h) | Flags | Track end | Provenance |
|---|---|---|---|---|---|---|---|---|
| 2026092412 | AUTO_260924_04 | 977.7 | 0 | 6-54 | 18 | reach | no minimum within 600 km of 85.3,-110.8 at or below 1009 hPa and within 1080 km of the last fix at +66 h | before fix |
| 2026092412 | AUTO_260924_06 | 950.0 | 1 | 0-120 | 20 | terrain, reach | no minimum within 600 km of 27.9,-109.6 at or below 989 hPa and within 1080 km of the last fix at +132 h | before fix |
| 2026092412 | GREENLAND | 959.1 | 0 | 6-174 | 15 | reach | no minimum within 600 km of 85.9,119.4 at or below 999 hPa and within 1080 km of the last fix at +186 h | before fix |
| 2026092418 | AUTO_260924_01 | 953.4 | 0 | 0-126 | 28 | reach | no minimum within 600 km of 28.2,-108.1 at or below 1005 hPa and within 1080 km of the last fix at +138 h | before fix |
| 2026092418 | AUTO_260924_02 | 964.3 | 0 | 0-90 | 22 | reach | no minimum within 600 km of 55.6,-156.5 at or below 1003 hPa and within 1080 km of the last fix at +102 h | before fix |
| 2026092418 | AUTO_260924_04 | 978.5 | 0 | 0-48 | 19 | reach | no minimum within 600 km of 85.6,-113.5 at or below 1008 hPa and within 1080 km of the last fix at +60 h | before fix |
| 2026092512 | AUTO_260924_01 | 950.6 | 0 | 0-96 | 29 | terrain, reach | no minimum within 600 km of 29.3,-109.1 at or below 998 hPa and within 1080 km of the last fix at +108 h | before fix |
| 2026092512 | AUTO_260924_04 | 982.3 | 0 | 0-30 | 15 | reach | no minimum within 600 km of 85.8,-119.6 at or below 1007 hPa and within 1080 km of the last fix at +42 h | before fix |
| 2026092512 | GREENLAND | 972.0 | 0 | 0-96 | 30 | reach | no minimum within 600 km of 68.1,-11.1 at or below 1027 hPa and within 1080 km of the last fix at +108 h | before fix |
| 2026092612 | AUTO_260924_01 | 951.6 | 0 | 0-84 | 18 | terrain | outside a closed low at +90, +96 h (1006 hPa at +96 h) | before fix |
| 2026092612 | AUTO_260924_04 | 991.9 | 0 | 0-0 |  | reach | no minimum within 600 km of 84.5,-123.1 at or below 1004 hPa and within 1080 km of the last fix at +12 h | before fix |
| 2026092712 | AUTO_260926_01 | 955.2 | 0 | 0-6 | 15 | reach | no minimum within 600 km of 26.8,130.6 at or below 967 hPa and within 1080 km of the last fix at +18 h | before fix |
| 2026092812 | AUTO_260924_01 | 963.3 | 0 | 0-12 | 17 | reach | no minimum within 600 km of 25.7,-112.0 at or below 978 hPa and within 1080 km of the last fix at +24 h | before fix |
| 2026092912 | AUTO_260924_01 | 990.3 | 0 | 0-90 | 87 | reach fast | no minimum within 600 km of 49.3,-115.6 at or below 1028 hPa and within 1080 km of the last fix at +102 h | before fix |
| 2026092912 | AUTO_260929_01 | 950.0 | 1 | 0-96 | 5 | terrain | outside a closed low at +102, +108 h (1004 hPa at +108 h) | before fix |
| 2026092912 | AUTO_260929_02 | 979.1 | 0 | 0-6 | 22 | reach | no minimum within 600 km of 85.5,-159.0 at or below 993 hPa and within 1080 km of the last fix at +18 h | before fix |
| 2026093012 | AUTO_260929_01 | 951.7 | 0 | 0-72 | 35 | terrain | outside a closed low at +78, +84 h (1003 hPa at +84 h) | before fix |
| 2026093012 | AUTO_260930_01 | 959.4 | 0 | 0-60 | 62 | reach fast | no minimum within 600 km of 79.0,135.8 at or below 988 hPa and within 1080 km of the last fix at +72 h | before fix |
| 2026100112 | AUTO_261001_02 | 975.0 | 0 | 0-132 | 39 | reach | no minimum within 600 km of 72.3,-51.7 at or below 1029 hPa and within 1080 km of the last fix at +144 h | before fix |
| 2026100200 | AUTO_260929_01 | 973.8 | 0 | 0-48 | 24 | reach | no minimum within 600 km of 65.8,-22.5 at or below 990 hPa and within 1080 km of the last fix at +60 h | after fix |
| 2026100200 | AUTO_261001_01 | 951.0 | 0 | 0-198 | 17 | terrain |  | after fix |
| 2026100200 | WPAC | 925.2 | 0 | 0-198 | 42 | terrain |  | after fix |
| 2026100212 | AUTO_260929_01 | 978.8 | 0 | 0-24 | 60 | reach fast | no minimum within 601 km of 59.8,-30.7 at or below 991 hPa and within 1082 km of the last fix at +36 h | after fix |
| 2026100212 | WPAC | 926.4 | 0 | 0-192 | 40 | terrain |  | after fix |
| 2026100312 | AUTO_260929_01 | 970.4 | 0 | 0-180 | 47 | reach | no minimum within 600 km of 75.2,27.9 at or below 1020 hPa and within 1080 km of the last fix at +192 h | after fix |
| 2026100312 | AUTO_261003_01 | 966.2 | 0 | 0-108 | 5 | reach | no minimum within 600 km of 60.5,-146.0 at or below 1029 hPa and within 1080 km of the last fix at +120 h | after fix |
| 2026100312 | AUTO_261003_02 | 977.3 | 0 | 0-24 | 15 | reach | no minimum within 600 km of 57.1,-179.0 at or below 995 hPa and within 1080 km of the last fix at +36 h | after fix |
| 2026100312 | WPAC | 939.2 | 0 | 0-198 | 19 | terrain |  | after fix |
| 2026100412 | AUTO_261001_02 | 996.7 | 0 | 0-48 | 10 | reach | no minimum within 600 km of 64.0,-59.4 at or below 1026 hPa and within 1080 km of the last fix at +60 h | after fix |
| 2026100412 | AUTO_261003_01 | 973.2 | 0 | 0-78 | 7 | reach | no minimum within 600 km of 60.3,-146.3 at or below 1029 hPa and within 1080 km of the last fix at +90 h | after fix |
| 2026100412 | WPAC | 933.5 | 0 | 0-198 | 44 | terrain |  | after fix |
| 2026100512 | AUTO_260929_01 | 964.8 | 0 | 0-180 | 25 | reach | no minimum within 600 km of 75.5,58.0 at or below 1015 hPa and within 1080 km of the last fix at +192 h | after fix |
| 2026100512 | AUTO_261003_01 | 986.4 | 0 | 0-60 | 3 | reach | no minimum within 600 km of 59.8,-147.5 at or below 1029 hPa and within 1080 km of the last fix at +72 h | after fix |
| 2026100512 | WPAC | 949.4 | 0 | 0-186 | 32 | terrain, reach | no minimum within 600 km of 51.6,-170.8 at or below 1002 hPa and within 1080 km of the last fix at +198 h | after fix |
| 2026100612 | AUTO_261001_02 | 1014.1 | 0 | 0-0 |  | reach | no minimum within 600 km of 62.5,-56.4 at or below 1026 hPa and within 1080 km of the last fix at +12 h | after fix |
| 2026100612 | AUTO_261003_01 | 995.9 | 0 | 0-60 | 7 | reach | no minimum within 600 km of 58.7,-140.9 at or below 1029 hPa and within 1080 km of the last fix at +72 h | after fix |
| 2026100612 | AUTO_261006_01 | 977.2 | 0 | 0-30 | 34 | reach | no minimum within 600 km of 54.7,-56.6 at or below 995 hPa and within 1080 km of the last fix at +42 h | after fix |
| 2026100612 | EPAC | 976.5 | 0 | 0-156 | 44 | reach | no minimum within 600 km of 37.1,-179.5 at or below 1025 hPa and within 1080 km of the last fix at +168 h | after fix |
| 2026100612 | WPAC | 964.0 | 0 | 0-42 | 77 | reach fast | no minimum within 768 km of 56.8,-175.4 at or below 984 hPa and within 1383 km of the last fix at +54 h | after fix |
| 2026100712 | AUTO_261003_01 | 1013.3 | 0 | 0-24 | 70 | reach fast | no minimum within 699 km of 53.6,-147.2 at or below 1030 hPa and within 1259 km of the last fix at +36 h | after fix |
| 2026100712 | AUTO_261006_01 | 978.1 | 0 | 0-12 | 46 | reach | no minimum within 600 km of 52.9,-50.0 at or below 1005 hPa and within 1080 km of the last fix at +24 h | after fix |
| 2026100712 | AUTO_261007_01 | 955.6 | 0 | 0-42 | 46 | reach | no minimum within 600 km of 64.4,167.7 at or below 975 hPa and within 1080 km of the last fix at +54 h | after fix |
| 2026100712 | EPAC | 947.5 | 0 | 0-198 | 8 | terrain |  | after fix |
| 2026100712 | WPAC | 970.7 | 0 | 0-0 |  | reach | no minimum within 600 km of 46.2,162.2 at or below 983 hPa and within 1080 km of the last fix at +12 h | after fix |
| 2026100812 | AUTO_261007_01 | 972.4 | 0 | 0-0 |  | reach | no minimum within 600 km of 55.6,156.0 at or below 984 hPa and within 1080 km of the last fix at +12 h | after fix |
| 2026100812 | AUTO_261008_01 | 943.9 | 0 | 0-120 | 17 | terrain | outside a closed low at +126, +132 h (1004 hPa at +132 h) | after fix |
| 2026100812 | AUTO_261008_02 | 947.4 | 0 | 0-12 | 48 | terrain, reach | no minimum within 600 km of 63.6,176.8 at or below 965 hPa and within 1080 km of the last fix at +24 h | after fix |
| 2026100812 | AUTO_261008_03 | 967.7 | 0 | 0-36 | 32 | reach | no minimum within 600 km of 31.2,-86.5 at or below 983 hPa and within 1080 km of the last fix at +48 h | after fix |
| 2026100812 | EPAC | 950.4 | 0 | 0-198 | 8 | terrain |  | after fix |
| 2026100912 | AUTO_261008_01 | 963.6 | 0 | 0-120 | 0 | reach | no minimum within 600 km of 61.5,-170.3 at or below 1019 hPa and within 1080 km of the last fix at +132 h | after fix |
| 2026100912 | AUTO_261008_03 | 966.7 | 0 | 0-12 | 33 | reach | no minimum within 600 km of 31.8,-85.9 at or below 986 hPa and within 1080 km of the last fix at +24 h | after fix |
| 2026100912 | AUTO_261009_02 | 963.9 | 0 | 0-24 | 6 | reach | no minimum within 600 km of 17.9,-105.2 at or below 976 hPa and within 1080 km of the last fix at +36 h | after fix |
| 2026101012 | AUTO_261001_01 | 987.8 | 0 | 0-90 | 41 | reach | no minimum within 600 km of 36.8,-122.5 at or below 1030 hPa and within 1080 km of the last fix at +102 h | after fix |
| 2026101012 | AUTO_261008_01 | 975.6 | 0 | 0-102 | 19 | reach | no minimum within 600 km of 57.6,-168.0 at or below 1022 hPa and within 1080 km of the last fix at +114 h | after fix |
| 2026101012 | AUTO_261009_01 | 947.3 | 0 | 0-162 | 83 | terrain, reach fast | no minimum within 827 km of 44.2,-162.4 at or below 1017 hPa and within 1489 km of the last fix at +174 h | after fix |
| 2026101012 | AUTO_261009_02 | 950.1 | 0 | 0-6 | 5 | terrain, reach | no minimum within 600 km of 17.8,-104.6 at or below 963 hPa and within 1080 km of the last fix at +18 h | after fix |
| 2026101112 | AUTO_261008_01 | 982.6 | 0 | 0-78 | 33 | reach | no minimum within 600 km of 54.4,-168.9 at or below 1021 hPa and within 1080 km of the last fix at +90 h | after fix |
| 2026101112 | AUTO_261009_01 | 966.7 | 0 | 0-144 | 35 | reach | no minimum within 600 km of 44.1,-162.2 at or below 1023 hPa and within 1080 km of the last fix at +156 h | after fix |
| 2026101212 | AUTO_261008_01 | 990.9 | 0 | 0-48 | 62 | reach fast | no minimum within 621 km of 54.1,-168.3 at or below 1018 hPa and within 1118 km of the last fix at +60 h | after fix |
| 2026101312 | AUTO_261008_01 | 998.2 | 0 | 0-24 | 1 | reach | no minimum within 600 km of 61.4,-167.9 at or below 1018 hPa and within 1080 km of the last fix at +36 h | after fix |
| 2026101312 | AUTO_261011_01 | 972.1 | 0 | 0-18 | 37 | reach | no minimum within 600 km of 57.2,-35.2 at or below 990 hPa and within 1080 km of the last fix at +30 h | after fix |
| 2026101312 | AUTO_261013_01 | 966.9 | 0 | 0-60 | 20 | reach | no minimum within 600 km of 82.5,42.0 at or below 989 hPa and within 1080 km of the last fix at +72 h | after fix |
| 2026101312 | AUTO_261013_02 | 978.3 | 0 | 0-0 |  | reach | no minimum within 600 km of 47.4,-40.4 at or below 990 hPa and within 1080 km of the last fix at +12 h | after fix |
| 2026101412 | AUTO_261014_01 | 927.8 | 0 | 0-126 | 25 | terrain | outside a closed low at +132, +144 h (994 hPa at +144 h) | after fix |
| 2026101512 | AUTO_261014_01 | 955.3 | 0 | 0-96 | 25 | reach | no minimum within 600 km of 70.7,85.9 at or below 1007 hPa and within 1080 km of the last fix at +108 h | after fix |
| 2026101512 | AUTO_261014_02 | 974.7 | 0 | 0-96 | 4 | reach | no minimum within 600 km of 57.7,-136.9 at or below 1030 hPa and within 1080 km of the last fix at +108 h | after fix |
| 2026101512 | AUTO_261014_03 | 992.5 | 0 | 0-36 | 17 | reach | no minimum within 600 km of 75.8,149.8 at or below 1005 hPa and within 1080 km of the last fix at +48 h | after fix |
| 2026101512 | AUTO_261015_01 | 971.0 | 0 | 0-102 | 18 | reach | no minimum within 600 km of 53.0,-176.6 at or below 1013 hPa and within 1080 km of the last fix at +114 h | after fix |
| 2026101612 | AUTO_261014_03 | 984.4 | 0 | 0-102 | 34 | reach | no minimum within 600 km of 86.5,-115.2 at or below 1002 hPa and within 1080 km of the last fix at +114 h | after fix |
| 2026101612 | AUTO_261016_01 | 956.6 | 0 | 0-36 | 16 | reach | no minimum within 600 km of 18.3,-105.0 at or below 972 hPa and within 1080 km of the last fix at +48 h | after fix |
| 2026101612 | AUTO_261016_02 | 966.9 | 0 | 0-90 | 28 | reach | no minimum within 600 km of 74.3,7.0 at or below 1019 hPa and within 1080 km of the last fix at +102 h | after fix |
| 2026101712 | AUTO_261014_01 | 977.1 | 0 | 0-150 | 8 | reach | no minimum within 600 km of 85.4,177.4 at or below 1015 hPa and within 1080 km of the last fix at +162 h | after fix |
| 2026101712 | AUTO_261014_03 | 984.9 | 0 | 0-72 | 17 | reach | no minimum within 600 km of 84.8,-125.3 at or below 1000 hPa and within 1080 km of the last fix at +84 h | after fix |
| 2026101712 | AUTO_261017_01 | 926.3 | 0 | 0-168 | 19 | terrain, reach | no minimum within 600 km of 23.0,115.7 at or below 993 hPa and within 1080 km of the last fix at +180 h | after fix |

## Per cycle

| Cycle | Storm-cycles | Tracked | Terrain flag | Reach flag | Reach flag, fast |
|---|---|---|---|---|---|
| 2026092412 | 9 | 8 | 1 | 3 | 0 |
| 2026092418 | 9 | 8 | 0 | 3 | 0 |
| 2026092512 | 8 | 7 | 1 | 3 | 0 |
| 2026092612 | 8 | 8 | 1 | 1 | 0 |
| 2026092712 | 8 | 7 | 0 | 1 | 0 |
| 2026092812 | 6 | 4 | 0 | 1 | 0 |
| 2026092912 | 6 | 6 | 1 | 2 | 1 |
| 2026093012 | 6 | 5 | 1 | 1 | 1 |
| 2026100112 | 7 | 6 | 0 | 1 | 0 |
| 2026100200 | 6 | 6 | 2 | 1 | 0 |
| 2026100212 | 6 | 6 | 1 | 1 | 1 |
| 2026100312 | 8 | 8 | 1 | 3 | 0 |
| 2026100412 | 8 | 7 | 1 | 2 | 0 |
| 2026100512 | 8 | 8 | 1 | 3 | 0 |
| 2026100612 | 8 | 8 | 0 | 5 | 1 |
| 2026100712 | 8 | 8 | 1 | 4 | 1 |
| 2026100812 | 10 | 9 | 3 | 3 | 0 |
| 2026100912 | 10 | 7 | 0 | 3 | 0 |
| 2026101012 | 7 | 7 | 2 | 4 | 1 |
| 2026101112 | 8 | 6 | 0 | 2 | 0 |
| 2026101212 | 7 | 6 | 0 | 1 | 1 |
| 2026101312 | 8 | 7 | 0 | 4 | 0 |
| 2026101412 | 10 | 7 | 1 | 0 | 0 |
| 2026101512 | 9 | 7 | 0 | 4 | 0 |
| 2026101612 | 10 | 10 | 0 | 3 | 0 |
| 2026101712 | 13 | 11 | 1 | 3 | 0 |
