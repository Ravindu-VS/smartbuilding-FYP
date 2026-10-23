# Model card: occupancy_co2_temporal v1

- **Task**: room occupancy (occupied = 1) from indoor environmental readings
- **Model**: mlp (MLPClassifier)
- **Features (4, in this order)**: CO2, CO2_d5, CO2_d15, CO2_std15
- **Training data**: UCI Occupancy Detection (Candanedo & Feldheim 2016), CC BY 4.0, provenance public_real;
  rows 10808 from 2015-02-02 14:19:00 to 2015-02-10 09:33:00 (protocol B train+validation (datatest + datatraining))
- **Selection**: highest validation F1 using CO2 level and trends only
- **Seed**: 42; trained 2026-10-23T09:22:47Z at commit cbd03a3

## Held-out results (threshold 0.5)

| split | n | accuracy | precision | recall | f1 | balanced_accuracy | roc_auc |
|---|---|---|---|---|---|---|---|
| B_test | 9752 | 0.633 | 0.335 | 0.758 | 0.465 | 0.679 | 0.741 |
| A_test1 | 2665 | 0.928 | 0.888 | 0.918 | 0.903 | 0.926 | 0.974 |
| A_test2 | 9752 | 0.627 | 0.331 | 0.756 | 0.460 | 0.674 | 0.752 |

B_test = 11-18 Feb 2015, a week after all training data. A_* = original paper split (A_test1 precedes the training
days; reported for comparison only).

## Limitations

- One office in Mons, Belgium, in February (heating season), 1-minute data, a few occupants; labels from photographs.
  Not validated in a tropical, air-conditioned building or in the project's real room (no labelled data there yet).
- Light is a strong cue in this dataset because occupants switched the lights; in an automated building the
  controller switches them, so light-based features feed back the controller's own actions (see `occupancy_co2_temporal`).
- Synthetic-domain results are reported separately in docs/results/occupancy.md.
