# Deployment

The system runs on a single-node K3s cluster on `server1`, deployed by
Argo CD from this repository. The cluster reconciles to what is committed
here: a change made by hand in the cluster is reverted on the next sync,
which is what makes the repository the record of what is running.

## Topology

| Component | How it runs | Reached at |
|---|---|---|
| Serving API | Deployment, 1 replica, non-root, read-only rootfs | NodePort `30800` |
| MLflow (registry + tracking) | Deployment + 5 Gi PVC, `Recreate` strategy | NodePort `30500` |
| Drift evaluation | CronJob, weekly, writes to a 2 Gi PVC | — |
| Prometheus / Grafana / Alertmanager | `kube-prometheus-stack` | `30900` / `30300` / `30930` |
| Argo CD | `argocd` namespace | port-forward |

The API mounts the evaluation volume **read-only**: it reports verdicts, it
never writes them.

## Why K3s and not the existing CRC

`server1` already hosts a CRC (OpenShift Local) VM for a separate demo. It
was not reused: its cluster certificates expire about 30 days after the VM
is stopped and it had been stopped for five weeks, so recovering it would
have meant `crc delete` and a rebuild, putting an unrelated project at
risk. K3s also costs ~500 MiB against CRC's ~12 GiB, leaving that VM's
headroom intact.

## Installation

K3s is installed so that nothing already on the host moves:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="\
  --https-listen-port 6444 \
  --disable traefik \
  --disable servicelb \
  --write-kubeconfig-mode 644" sh -
```

- `--https-listen-port 6444` — `6443` is an nginx stream proxy for the CRC VM.
- `--disable traefik` — nginx owns `:80` and `:443` for other sites on this host.
- `--disable servicelb` — services are reached by NodePort.

Then Argo CD, the monitoring stack, and the application:

```bash
kubectl create namespace argocd calibration-drift
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  --set grafana.service.type=NodePort --set grafana.service.nodePort=30300 \
  --set prometheus.service.type=NodePort --set prometheus.service.nodePort=30900
kubectl apply -f deploy/argocd/application.yaml
```

## Operating it

```bash
export MLFLOW_TRACKING_URI=http://<node>:30500

uv run python -m drift.train                  # register a candidate (pending)
uv run python -m drift.cli status             # what is approved, by whom, why
uv run python -m drift.cli approve 2 --actor you --reason "..."
uv run python -m drift.cli rollback --actor you --reason "..."

# run an evaluation immediately rather than waiting for the schedule
kubectl -n calibration-drift create job manual --from=cronjob/calibration-drift-evaluate
```

A newly approved model is picked up on pod start:
`kubectl -n calibration-drift rollout restart deploy/calibration-drift`.

## What this deployment taught us

Five faults that only appeared once it ran on real infrastructure. Each is
fixed in the chart, and each is the kind of thing a passing test suite does
not catch:

1. **`/ready` and `/metrics` returned 500 with the registry unreachable.**
   Unit tests always had a working MLflow. A readiness probe that errors
   instead of answering `false` makes Kubernetes behave wrongly, and a
   `/metrics` that 500s breaks scraping. Both now degrade.
2. **MLflow was OOMKilled at a 1 Gi limit.** It holds ~300–400 MiB per
   worker. The symptoms were probe timeouts, flapping readiness and a
   NodePort that was never programmed — none of which say "memory".
3. **MLflow 3.6.0 server against a 3.16.1 client** returned 500 on registry
   writes. Version skew between the process that trains and the registry
   that records it is a traceability hazard, not just a compatibility one.
4. **`--allowed-hosts` replaces MLflow's default allowlist**, so the
   kubelet's probe (Host = pod IP) was rejected by its own DNS-rebinding
   protection and the pod restart-looped while starting cleanly.
5. **The NetworkPolicy denied every external caller.** Restricting ingress
   to pod sources blocks NodePort traffic. The egress restriction is the
   control worth keeping; the service port should accept its own callers.

## Known limitations

- **MLflow is backed by SQLite on a single RWO volume.** It is deliberately
  single-replica with a `Recreate` strategy. Postgres is the answer at real
  volume; this is adequate for one instrument and one operator, and is the
  first thing to change if it is not.
- **No Vault or External Secrets Operator**, contrary to the original plan.
  There is currently nothing to put in them: MLflow runs without
  authentication and no API key is configured. Installing a secrets
  manager to hold zero secrets is ceremony, not a control. The correct
  sequence is to enable MLflow authentication first and then manage that
  credential — at which point it becomes worth doing, and it is the next
  security task.
- **MLflow and the API are exposed by NodePort with no authentication**,
  reachable by anyone on the LAN or the Tailnet. Acceptable for a
  single-operator homelab; not acceptable anywhere else. An ingress with
  authentication is the fix.
- **A newly approved model needs a pod restart.** The serving state is
  cached at startup rather than watched.
- **Single node.** No availability story; the node is a single point of
  failure and the PVCs are `local-path`.
