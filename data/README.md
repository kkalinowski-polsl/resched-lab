# Input data of the production case

`zautomatyzowany2.csv` – automated gear-wheel line (variant "automated", Polish: *zautomatyzowany*).

- Source: Kampa, A., K. Kalinowski, M. Stawowiak, M. Jarzyńska, M. Olender-Skóra, G. Gołda, W. Banaś, et al. 2026. "Digital Twin Methodology for Flexible Manufacturing System Design: Integration of VSM, Discrete-Event Simulation and Production Scheduling for Gear Wheel Production." *Applied Sciences* 16 (15): 7521. https://doi.org/10.3390/app16157521 (open access, CC BY 4.0). The values are processing times of the automated system reported in that article.
- Licence of this file: CC BY 4.0 (attribution: Kampa et al. 2026).
- Format: semicolon-separated, decimal comma, UTF-8 with BOM. Columns: `Job` – customer order (z1–z10); `liczba sztuk` – order quantity (units); `Op1`–`op6` – processing time per unit [s] at the stages CNC turning (2 machines), gear hobbing (2), broaching, deburring, washing and inspection (1 machine each). Set-up times are included in the processing times.
- Use in the workbench (`resched_lab.instance.load_gear_line`): every unit is a job with six operations – 10 orders, 104 jobs, 624 operations; times rounded to 1 s. Release times, due dates, weights and hard/soft due-date types are not part of the source data; they are generated with seed 2026 by `generate_order_attributes` (Supplementary material of the article, Table S2).

The illustrative job shop of E1 (5 machines, 10 jobs) is defined in `resched_lab/instance.py`.
