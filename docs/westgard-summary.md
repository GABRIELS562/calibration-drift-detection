# Westgard summary

Reference: batch 1. Control statistic: batch mean of each sensor's steady-state response (`f1`) per gas, in reference within-gas SD. Reject on 1_3s or 2_2s; warn on 4_1s or 10x. Worst chart shown per sensor.

| batch | rejected | warned | reject triggers | warn triggers |
|---|---|---|---|---|
| 2 | 0/16 | 0/16 | — | — |
| 3 | 0/16 | 0/16 | — | — |
| 4 | 0/16 | 0/16 | — | — |
| 5 | 0/16 | 4/16 | — | s01 (aceta z=-1.5 4_1s), s02 (aceta z=-1.5 4_1s), s09 (aceta z=-1.7 4_1s), s10 (aceta z=-1.8 4_1s) |
| 6 | 4/16 | 5/16 | s07 (tolue z=+3.2 1_3s), s08 (tolue z=+3.9 1_3s), s15 (tolue z=+3.8 1_3s), s16 (tolue z=+3.4 1_3s) | s01 (aceto z=-1.8 4_1s), s02 (aceto z=-1.9 4_1s), s06 (ammon z=-1.3 4_1s), s09 (aceto z=-2.0 4_1s), s10 (aceto z=-2.2 4_1s) |
| 7 | 5/16 | 2/16 | s01 (tolue z=-3.1 1_3s), s08 (tolue z=+2.1 2_2s), s09 (tolue z=-2.6 2_2s), s10 (tolue z=-3.1 1_3s+2_2s), s15 (tolue z=+2.0 2_2s) | s02 (aceta z=-2.0 4_1s), s06 (ammon z=-1.5 4_1s) |
| 8 | 4/16 | 1/16 | s01 (tolue z=-3.3 1_3s+2_2s), s02 (tolue z=-3.0 2_2s), s09 (tolue z=-3.0 2_2s), s10 (tolue z=-3.3 1_3s+2_2s) | s06 (ammon z=-1.5 4_1s) |
| 9 | 4/16 | 4/16 | s01 (tolue z=-3.0 2_2s+4_1s), s02 (tolue z=-2.8 2_2s+4_1s), s09 (tolue z=-3.0 2_2s+4_1s), s10 (tolue z=-3.3 1_3s+2_2s+4_1s) | s05 (ammon z=-1.2 4_1s), s06 (ammon z=-1.4 4_1s), s11 (ammon z=-2.1 4_1s), s12 (ammon z=-2.1 4_1s) |
| 10 | 4/16 | 2/16 | s01 (tolue z=-2.7 2_2s+4_1s), s02 (tolue z=-2.6 2_2s+4_1s), s09 (tolue z=-2.7 2_2s+4_1s), s10 (tolue z=-3.1 1_3s+2_2s+4_1s) | s11 (ammon z=-1.4 4_1s), s12 (ammon z=-1.3 4_1s) |
