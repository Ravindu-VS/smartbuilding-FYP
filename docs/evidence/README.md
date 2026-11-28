# Evidence

Recorded outputs behind the DevOps/MLOps claims (28 Nov 2026, development workspace). Nothing here is typed by hand
except the headers and notes.

| Capability | File | What it shows |
|---|---|---|
| Fresh clone | [fresh-clone.txt](fresh-clone.txt) | Clean clone → build → up with new secrets and empty volumes: healthy, model trained and promoted, data flowing, 0 dashboard query failures |
| Docker Compose | [compose-ps.txt](compose-ps.txt) | 12 services, all healthy (Grafana excluded here: not downloadable in this workspace; CI runs it) |
| Data flow | [data-flow.txt](data-flow.txt) | Board → MQTT (auth) → edge brain and ingestion → PostgreSQL → ML API predictions, with provenance |
| Prometheus + alerts | [prometheus.txt](prometheus.txt) | Targets up, firing alerts, promtool and amtool checks |
| Grafana dashboards | [dashboards-check.txt](dashboards-check.txt) | All 78 dashboard queries run against Prometheus: 0 failures |
| Logs | [logs.txt](logs.txt) | Structured JSON lines from the edge brain, ingestion, ML API and trainer |
| MLflow / registry | [mlops-registry.txt](mlops-registry.txt) | Versions, gate decisions, manual promotion, runs with data version and git commit |
| Recovery | [recovery-test.txt](recovery-test.txt) | Crash → restart in 7 s; 100 s outage → alert fired, no reading lost |
| Backup / restore | [restore-test.txt](restore-test.txt) | Dropped table and registry rows restored |
| Kubernetes | [kubernetes.txt](kubernetes.txt) | k3s: all objects, ingress, in-cluster data flow, 673/673 requests through a pod kill and a rolling restart |
| Terraform | [terraform.txt](terraform.txt) | `fmt` + `init` + `validate` with the azurerm provider (not applied) |
| CI/CD | GitHub → Actions | The first runs appear after the push (this workspace cannot run GitHub Actions) |

Workspace notes, so the numbers are read correctly:
* Docker Hub was unreachable here, so the stack ran on locally built images of the same software: Ubuntu 24.04
  packages and the official release binaries. The repository's defaults are the official images, which CI uses.
* Kubernetes ran on k3s with two workspace-only settings, explained in kubernetes.txt.
* The physical-room panels show the board simulator here (`source="simulated_board"`). The real board's readings
  appear as `physical` when it feeds the broker.
* Commit ids inside these files (for example `ecfd5d5`, `4c3b236`) are from the development workspace's history.
  The work reached GitHub as one squashed commit, because the PC relay that pushes can only add, commit and push.
