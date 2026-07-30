# Deployment (host, via systemd)

The production path for v3.0 is a **systemd timer on the host**, not a container.
`systemctl`, `journalctl`, `ss -tulnp` and host-scope process/disk views do not
work meaningfully from inside a namespace, so a containerized agent reports on
the container rather than on the machine you care about. The Docker image is
retained only as a CI smoke-test artifact.

The same two unit files work on both Ubuntu (Debian family) and Rocky (RHEL
family) — systemd is the common layer.

## Install

```bash
sudo mkdir -p /opt/linux-health-monitor
sudo cp -r agent /opt/linux-health-monitor/
sudo mkdir -p /opt/linux-health-monitor/reports
sudo cp systemd/health-monitor.service systemd/health-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now health-monitor.timer
```

Verify:

```bash
systemctl start health-monitor.service && systemctl status health-monitor.service
```

```bash
systemctl list-timers health-monitor.timer
```

The report lands at `/opt/linux-health-monitor/reports/report.html`.

## Per-host configuration

All configuration is `Environment=` lines in the `.service` file — nothing is
compiled in, so the same build serves any host.

| Variable | Purpose |
|---|---|
| `HEALTH_SERVICES` | Comma-separated units to check. Differs per host — see below. |
| `HEALTH_CONTAINER_USER` | Owner of a **rootless** container runtime (node2). |
| `HEALTH_APP_ENDPOINTS` | `name=url` pairs for HTTP checks. Unset = feature omitted. |
| `HEALTH_APP_TIMEOUT` | Per-endpoint timeout in seconds (default 2). |
| `HEALTH_JOURNAL_WINDOW` | How far back to count journal errors (default `-1h`). |
| `HEALTH_{CPU,MEM,DISK}_{WARN,CRIT}` | Alert thresholds, in percent. Disk thresholds apply to *every* filesystem. |

### Unit names differ per host

`HEALTH_SERVICES` is per-host because the units genuinely differ — including the
SSH daemon, whose unit is `ssh` on Debian but `sshd` on RHEL:

```
# Debian family (Docker host)
Environment=HEALTH_SERVICES=docker,chronyd,ssh
```

```
# RHEL family (rootless Podman host)
Environment=HEALTH_SERVICES=chronyd,sshd,firewalld
```

A unit that is not installed reports `not-installed` rather than `inactive`, so
naming one that does not exist yet (nginx before the platform is deployed) is
harmless and self-explanatory in the report.

### Fleet dashboard

Point each node's `HEALTH_APP_ENDPOINTS` at **both** nodes so either node's
report shows the whole fleet's application health side by side:

```
Environment=HEALTH_APP_ENDPOINTS=node1-health=http://192.168.71.251:8000/health,node2-health=http://192.168.71.252:8000/health,fleet-slo=http://192.168.71.251:8000/slo
```

OS metrics remain node-local — each report describes the host it ran on.
Aggregating OS metrics across both nodes would need a collector; that is
deliberately out of scope.

## Two gotchas

**Rootless Podman (node2).** Containers belong to the user that started them,
so root's `podman ps` queries root's own empty store and reports nothing. Set
`HEALTH_CONTAINER_USER` to the owning user — and then comment out both
`NoNewPrivileges=yes` and `ProtectHome=yes`, because `su` is setuid (blocked by
the former) and needs the target user's home (hidden by the latter).

**Privilege.** The service runs as root so that `ss -tulnp` process names, the
system journal and unit state are all readable. Running unprivileged works and
simply yields fewer fields — every collector degrades rather than failing.
Specifically, an unprivileged run sees only the *user* journal (so the error
count is lower than reality), no socket process names, and no AppArmor profile
count. Reading the system journal otherwise needs group `adm` on Debian or
`systemd-journal` on RHEL.

## Exit codes and alerting

`0` HEALTHY · `1` WARNING · `2` CRITICAL. A **failed systemd unit or an
unsynchronized clock is a WARNING** even when every resource threshold is fine,
so the timer's exit status is a usable alerting signal on its own. Journal error
*volume* deliberately does not affect the exit code — it is too noisy for that —
but it does appear in the alerts, diagnosis and report.
