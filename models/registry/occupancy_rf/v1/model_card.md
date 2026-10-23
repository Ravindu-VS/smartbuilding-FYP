# Model card: occupancy_rf v1

- **Task**: room occupancy (occupied = 1) from indoor environmental readings
- **Model**: random_forest (RandomForestClassifier)
- **Features (5, in this order)**: Temperature, Humidity, Light, CO2, HumidityRatio
- **Training data**: UCI Occupancy Detection (Candanedo & Feldheim 2016), CC BY 4.0, provenance public_real;
  rows 10808 from 2015-02-02 14:19:00 to 2015-02-10 09:33:00 (protocol B train+validation (datatest + datatraining))
- **Selection**: random forest on the project's original five inputs
- **Seed**: 42; trained 2026-10-23T09:22:46Z at commit cbd03a3

## Held-out results (threshold 0.5)

| split | n | accuracy | precision | recall | f1 | balanced_accuracy | roc_auc |
|---|---|---|---|---|---|---|---|
| B_test | 9752 | 0.989 | 0.952 | 0.996 | 0.973 | 0.991 | 0.997 |
| A_test1 | 2665 | 0.936 | 0.946 | 0.873 | 0.909 | 0.923 | 0.986 |
| A_test2 | 9752 | 0.979 | 0.970 | 0.931 | 0.950 | 0.962 | 0.996 |

B_test = 11-18 Feb 2015, a week after all training data. A_* = original paper split (A_test1 precedes the training
days; reported for comparison only).

## Limitations

- One office in Mons, Belgium, in February (heating season), 1-minute data, a few occupants; labels from photographs.
  Not validated in a tropical, air-conditioned building or in the project's real room (no labelled data there yet).
- Light is a strong cue in this dataset because occupants switched the lights; in an automated building the
  controller switches them, so light-based features feed back the controller's own actions (see `occupancy_co2_temporal`).
- Synthetic-domain results are reported separately in docs/results/occupancy.md.
