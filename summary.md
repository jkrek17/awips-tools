# Marine wind verification

Through 20261013 12 UTC. Scores pooled over the period and leads +24 to +120 h unless shown by lead.
MAE25: mean absolute error (kt) where forecast or truth is 25+ kt. CSI: hits / (hits + false alarms + misses).
Brier skill: the blend's member chances against the period's base rate (1 perfect, 0 no skill).

## North Atlantic, last 7 days (2 days)

| method | MAE25 vs analysis | CSI34 | CSI48 | CSI64 | MAE25 vs buoys | CSI34 ships+buoys |
|---|---|---|---|---|---|---|
| blend | 3.28 | 0.460 | 0.000 | - | 6.45 | 0.050 |
| deterministic | 3.14 | 0.470 | 0.000 | - | 6.27 | 0.067 |
| blend_eq | 3.23 | 0.456 | - | - | 6.29 | 0.071 |
| mean3 | 3.29 | 0.443 | - | - | 7.24 | 0.054 |
| gfs | 5.03 | 0.364 | 0.000 | 0.000 | 7.11 | 0.091 |
| ecmwf | 4.29 | 0.306 | 0.000 | 0.000 | 7.60 | 0.118 |
| aifs | 3.38 | 0.404 | - | - | 7.80 | 0.071 |

Brier skill of the chances vs the analysis: P34 0.44, P48 -, P64 -

## North Atlantic, last 30 days (2 days)

| method | MAE25 vs analysis | CSI34 | CSI48 | CSI64 | MAE25 vs buoys | CSI34 ships+buoys |
|---|---|---|---|---|---|---|
| blend | 3.28 | 0.460 | 0.000 | - | 6.45 | 0.050 |
| deterministic | 3.14 | 0.470 | 0.000 | - | 6.27 | 0.067 |
| blend_eq | 3.23 | 0.456 | - | - | 6.29 | 0.071 |
| mean3 | 3.29 | 0.443 | - | - | 7.24 | 0.054 |
| gfs | 5.03 | 0.364 | 0.000 | 0.000 | 7.11 | 0.091 |
| ecmwf | 4.29 | 0.306 | 0.000 | 0.000 | 7.60 | 0.118 |
| aifs | 3.38 | 0.404 | - | - | 7.80 | 0.071 |

Brier skill of the chances vs the analysis: P34 0.44, P48 -, P64 -

## North Atlantic, all (2 days)

| method | MAE25 vs analysis | CSI34 | CSI48 | CSI64 | MAE25 vs buoys | CSI34 ships+buoys |
|---|---|---|---|---|---|---|
| blend | 3.28 | 0.460 | 0.000 | - | 6.45 | 0.050 |
| deterministic | 3.14 | 0.470 | 0.000 | - | 6.27 | 0.067 |
| blend_eq | 3.23 | 0.456 | - | - | 6.29 | 0.071 |
| mean3 | 3.29 | 0.443 | - | - | 7.24 | 0.054 |
| gfs | 5.03 | 0.364 | 0.000 | 0.000 | 7.11 | 0.091 |
| ecmwf | 4.29 | 0.306 | 0.000 | 0.000 | 7.60 | 0.118 |
| aifs | 3.38 | 0.404 | - | - | 7.80 | 0.071 |

Brier skill of the chances vs the analysis: P34 0.44, P48 -, P64 -

## North Pacific, last 7 days (2 days)

| method | MAE25 vs analysis | CSI34 | CSI48 | CSI64 | MAE25 vs buoys | CSI34 ships+buoys |
|---|---|---|---|---|---|---|
| blend | 6.09 | 0.216 | 0.058 | - | 6.40 | - |
| deterministic | 6.87 | 0.186 | 0.064 | - | 6.51 | - |
| blend_eq | 6.86 | 0.188 | 0.079 | - | 6.52 | - |
| mean3 | 6.72 | 0.198 | 0.054 | - | 4.84 | - |
| gfs | 9.22 | 0.158 | 0.090 | 0.000 | 12.88 | - |
| ecmwf | 7.42 | 0.159 | 0.062 | 0.000 | 5.07 | 0.000 |
| aifs | 7.42 | 0.125 | 0.000 | - | 3.32 | - |

Brier skill of the chances vs the analysis: P34 0.26, P48 0.10, P64 -

## North Pacific, last 30 days (2 days)

| method | MAE25 vs analysis | CSI34 | CSI48 | CSI64 | MAE25 vs buoys | CSI34 ships+buoys |
|---|---|---|---|---|---|---|
| blend | 6.09 | 0.216 | 0.058 | - | 6.40 | - |
| deterministic | 6.87 | 0.186 | 0.064 | - | 6.51 | - |
| blend_eq | 6.86 | 0.188 | 0.079 | - | 6.52 | - |
| mean3 | 6.72 | 0.198 | 0.054 | - | 4.84 | - |
| gfs | 9.22 | 0.158 | 0.090 | 0.000 | 12.88 | - |
| ecmwf | 7.42 | 0.159 | 0.062 | 0.000 | 5.07 | 0.000 |
| aifs | 7.42 | 0.125 | 0.000 | - | 3.32 | - |

Brier skill of the chances vs the analysis: P34 0.26, P48 0.10, P64 -

## North Pacific, all (2 days)

| method | MAE25 vs analysis | CSI34 | CSI48 | CSI64 | MAE25 vs buoys | CSI34 ships+buoys |
|---|---|---|---|---|---|---|
| blend | 6.09 | 0.216 | 0.058 | - | 6.40 | - |
| deterministic | 6.87 | 0.186 | 0.064 | - | 6.51 | - |
| blend_eq | 6.86 | 0.188 | 0.079 | - | 6.52 | - |
| mean3 | 6.72 | 0.198 | 0.054 | - | 4.84 | - |
| gfs | 9.22 | 0.158 | 0.090 | 0.000 | 12.88 | - |
| ecmwf | 7.42 | 0.159 | 0.062 | 0.000 | 5.07 | 0.000 |
| aifs | 7.42 | 0.125 | 0.000 | - | 3.32 | - |

Brier skill of the chances vs the analysis: P34 0.26, P48 0.10, P64 -

