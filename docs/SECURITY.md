# Security

What is protected, how, and what is still open. This is a student research prototype, not a certified system.

## Secrets

| Secret | Kept in | Never in |
|---|---|---|
| Wi-Fi and MQTT credentials of the board | `firmware/esp32_smart_building/secrets.h` (git-ignored, template `secrets.example.h`) | git, logs |
| Container stack passwords and tokens | `.env` (git-ignored, template `.env.example`), random per install | git, images, compose file, logs |
| Kubernetes | `secretGenerator` from git-ignored `overlays/*/secrets.env` and `mqtt.env` → Secrets | manifests |
| Azure | Key Vault (RBAC; the VM reads with its managed identity); GitHub OIDC federation for CI (no client secret) | Terraform state, tfvars in git |
| CI | GitHub Secrets (`AZURE_*`, `VM_SSH_KEY`, `MLFLOW_TRACKING_*`); the stack job generates throw-away secrets and masks them | workflow files |

Further protections:
* `.dockerignore` keeps `.env`, `secrets.h`, `.git` and Terraform state out of build contexts.
* Logs redact secret-looking keys (`sbops/logs.py`); a test checks that MQTT credentials are never logged.
* The evidence files were scanned for the live `.env` values before commit.

## Network exposure

| Port | Service | Default exposure |
|---|---|---|
| 1883 | MQTT (Mosquitto) | Compose: 127.0.0.1 (`MQTT_BIND` for the LAN); Pi: home/campus LAN only |
| 8883 | MQTT over TLS | cloud VM only, NSG allows the edge's public IP only |
| 8001 | edge brain + dashboard | Pi LAN; Compose 127.0.0.1 (`BIND_ADDR`) |
| 8080, 5000, 9090, 9093, 3000 | ML API, MLflow, Prometheus, Alertmanager, Grafana | 127.0.0.1; in the cloud behind a TLS reverse proxy on 443, reachable from your IP only |
| 5432 | PostgreSQL | 127.0.0.1 (Compose), cluster-internal (Kubernetes) |
| 22 | SSH (cloud VM) | your IP only, keys only, fail2ban |

**Firewall rules.**
* *Azure NSG (Terraform):* allows 22 and 443 from `admin_cidr` and 8883 from `edge_cidr`, and explicitly denies
  everything else from the Internet.
* *On the Pi:*
  ```
  ufw default deny incoming
  ufw allow from <LAN>/24 to any port 1883,8001 proto tcp
  ufw allow from <LAN>/24 to any port 22 proto tcp
  ```

**Segmentation.**
* *Compose:* three networks (`edge`, `backend`, `monitoring`). PostgreSQL and MLflow are not on the `edge`
  network, so the MQTT side cannot reach them directly.
* *Kubernetes:* default-deny ingress NetworkPolicies, then explicit allows:
  * PostgreSQL ← MLflow and ingestion
  * MLflow ← trainer, ML API and the ingress controller
  * ML API ← ingestion and the ingress controller
  * MQTT ← the bridge

## Authentication and authorization

**MQTT.** Anonymous access is off. There are three users with an ACL (`infrastructure/mosquitto/acl`):
* `device`: publishes its telemetry, status and acks; reads commands.
* `ingest`: read-only.
* `edge`: full access under `sb/v1/#`.

The edge brain validates every message's schema, room, `msg_id` and value ranges before using it (same code in
ingestion).

**Other services.**

| Service | Access control |
|---|---|
| Grafana | Admin password from `.env`; sign-up and anonymous access off |
| PostgreSQL | One role per service (`mlflow`, `ingest`) owning only its own database; `grafana_ro` read-only; `PUBLIC` revoked |
| ML API | `POST /model/reload` needs `X-Admin-Token` (compared in constant time) and is disabled while unset |
| Edge brain | Model promote/rollback need `ADMIN_TOKEN` when set |
| MLflow | Allowed-hosts list against DNS rebinding; no built-in login, so it is reached only through localhost, the cluster or the TLS proxy with your IP. Add MLflow's basic-auth app or an OAuth proxy before exposing it more widely. |

## TLS strategy

| Link | Protection |
|---|---|
| Board ↔ Pi | MQTT on the local network without TLS (the firmware uses a plain `WiFiClient`). The firmware sends `MQTT_USERNAME`/`MQTT_PASSWORD` from `secrets.h` (empty by default): give the board the `device` user and set `allow_anonymous false` with the same `acl` file on the Pi's Mosquitto. `WiFiClientSecure` with the Pi's CA certificate is the next step if the LAN is shared. |
| Pi → cloud | Mosquitto bridge over TLS 8883 (`infrastructure/mosquitto/bridge-to-cloud.conf.example`, `tls-listener.conf.example`). Certificates: Let's Encrypt for a DNS name, or a private CA. |
| Browser → cloud UIs | TLS reverse proxy on 443 (Caddy or Traefik with Let's Encrypt), source-restricted by the NSG. Kubernetes: add a `tls:` section to the Ingress with cert-manager. |
| Inside the cloud host or cluster | Plain HTTP on private networks |

## Containers and supply chain

**Container hardening.**
* Non-root users (uid 10001) in every image built here.
* Kubernetes: `runAsNonRoot`, no privilege escalation, capabilities dropped, seccomp RuntimeDefault, read-only root
  filesystem where the app allows it, and resource limits.

**Supply chain.**
* Dependencies are pinned (`requirements/*.txt`, image tags, workflow action versions).
* Images are scanned with Trivy in CI (report).
* Dockerfiles are linted with hadolint.
* Models are stored in skops format, so loading one cannot run arbitrary code (unlike pickle). Only two reviewed
  scikit-learn tree types are trusted.
* MLflow and the trainer have telemetry disabled.

## Open items

* MLflow has no login of its own; keep it private as described above.
* Board ↔ Pi MQTT runs without TLS on the LAN. Check that the Pi's Mosquitto has `allow_anonymous false`; the container stack enforces it, but the Pi's own config was not changed in this work.
* The Trivy scan reports but does not block; decide a policy, for example blocking on fixed CRITICAL findings.
* The Raspberry Pi's own hardening (unattended upgrades, SSH keys only, ufw) is documented above but not automated.
