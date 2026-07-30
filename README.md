# Linux Health Monitor Agent v3.2

A lightweight, environment-aware system observability tool that collects system metrics and generates structured health reports with automated diagnosis and remediation guidance. Designed for safe, portable execution across Linux, WSL2, Docker, and CI/CD environments.

**No runtime dependencies.** Every metric comes from `/proc`, `/sys`, or a core userland command, so `python3 -m agent.monitor` runs on a stock interpreter with nothing installed.

---

## What It Does

1. Collects core system metrics — CPU, memory, every filesystem, load, disk I/O, network, uptime, process counts, and I/O pressure
2. Detects the execution environment and **distro family** — so one build behaves correctly on Debian- and RHEL-family hosts
3. Checks system features — services, failed units, containers (Docker *or* Podman), listening ports, log disk usage, and CPU temperature
4. Checks host posture — journal errors, clock synchronization, SELinux/AppArmor mode, firewall, virtual IP ownership, and pending reboots
5. Checks application endpoints — configurable HTTP health checks with status, latency, and parsed JSON body
6. Evaluates health — threshold-based status (HEALTHY / WARNING / CRITICAL) with alerts, diagnosis, and suggested commands
7. Outputs structured JSON for automation or an HTML report for human review

> Every optional feature degrades rather than failing: no sensors, no `ss`, no container runtime, no `systemctl`, or an unreachable endpoint each become a reported reason instead of a traceback.

**Nothing is ever executed on your behalf.** Commands that would change system state (`kill`, `renice`, `systemctl restart`, package installs) are only ever emitted as *suggested commands* for a person to read and choose to run.

---

## Data Sources

The agent reads the kernel's own interfaces instead of going through an abstraction layer. `/proc` is preferred where it is the stable source; commands are used where they are the natural tool.

| Metric | Source | Why |
|---|---|---|
| CPU % total | `/proc/stat` (2-sample delta) | stable format; `top`/`mpstat` output shifts between versions and `sysstat` is often absent |
| Per-process CPU | `/proc/<pid>/stat` (delta) | a true interval delta, unlike `ps %cpu`'s lifetime average |
| Per-process memory | `/proc/<pid>/statm` | the kernel documents `stat`'s `rss` field as inaccurate |
| Memory / swap | `/proc/meminfo` | most stable; `free`'s column layout varies |
| Disk usage | `df -P -B1 /` | `-P` forces portable single-line columns |
| **All filesystems** | `df -P -B1` + `/proc/mounts` | only `/` was measured before, hiding a full `/var`; includes tmpfs (`/tmp`, `/dev/shm`), which is sized and breaks services when full |
| Disk I/O | `/proc/diskstats` (delta) | no `sysstat` dependency |
| **I/O pressure** | `/proc/stat` iowait, `/proc/vmstat`, `/proc/loadavg` | `vmstat`'s signal without the `sysstat` package |
| Top dirs by size | `du -B1 -s` | handles hardlinks and sparse files; partial output kept on permission errors |
| Load average | `/proc/loadavg` | stdlib `os.getloadavg()` as fallback |
| Network I/O | `/proc/net/dev` | summed across all interfaces |
| Listening ports | `ss -tulnp` | process names require root; ports still listed without it |
| Uptime | `/proc/uptime` | |
| Processes / zombies / **blocked** | `/proc/<pid>/stat` | state `D` is what `ps aux \| awk '$8=="D"'` looks for |
| CPU temperature | `/sys/class/thermal`, then `/sys/class/hwmon` | `lm-sensors` is absent on minimized installs |
| CPU cores | `nproc` | honours cgroup and affinity limits |
| **Journal errors** | `journalctl -p err -o json` | one interface for both families; JSON counts *entries*, not lines |
| **Clock sync** | `timedatectl show` | answers the same way whether chrony, ntpd or timesyncd owns the clock |
| **SELinux / AppArmor** | `/sys/fs/selinux`, `/sys/module/apparmor` | `getenforce` and `aa-status` are separate packages |
| **Firewall** | `systemctl is-active` | unit state is family-neutral; the CLI is only used for extra detail |
| **Pending reboot** | flag file (Debian) / `dnf needs-restarting` (RHEL) | no shared interface exists, so this is real family dispatch |
| Distro family | `/etc/os-release` `ID`, `ID_LIKE` | picks `apt` vs `dnf` and the right reboot indicator |

---

## Cross-distro portability

The guiding rule: **prefer the interface both families share; dispatch only
where they genuinely diverge.** systemd, journald, `/proc` and `/sys` are common
layers, which is why log, service, clock and access-control checks go through
them rather than through each family's own tool.

| Concern | Debian family | RHEL family | How the monitor handles it |
|---|---|---|---|
| Log inspection | `/var/log/syslog` | `/var/log/messages` *(may not exist)* | journald — the difference disappears |
| Access control | AppArmor | SELinux | reads `/sys` for whichever is present |
| Firewall | `ufw` | `firewalld` | systemd unit state |
| Package query | `dpkg`, `apt` | `rpm`, `dnf` | only in suggested commands |
| Pending reboot | `/var/run/reboot-required` | `dnf needs-restarting` | family dispatch on `os_family` |
| `dmesg` unprivileged | yes (`dmesg_restrict=0`) | **no** (`=1`) | degrades with a reason |
| Journal read group | `adm` | `systemd-journal` | degrades to the user journal |
| Login history | `last` **absent** on Ubuntu 26.04 | `last` present | journald if needed |
| Time daemon | varies | varies | **detected, not assumed** — chrony is common on both |

Commands deliberately avoided, because they are absent on minimized installs of
one or both families, or differ incompatibly:

| Avoided | Used instead |
|---|---|
| `netstat` | `ss` (net-tools is not installed) |
| `dig` | `socket.getaddrinfo` (needs `bind-utils`/`dnsutils`) |
| `ping` | TCP connect (absent on node1; ICMP is often filtered) |
| `nc -zv` | `socket.connect_ex` (`nmap-ncat` and `netcat-openbsd` differ) |
| `mpstat`, `iostat`, `pidstat` | `/proc/stat`, `/proc/diskstats`, `/proc/vmstat` |
| `getenforce`, `aa-status` | `/sys/fs/selinux`, `/sys/module/apparmor` |
| `last` | journald |
| `ifup`/`ifdown` | `ip link` (no `ifupdown` on RHEL) |
| `crontab` | systemd timers |

## Deployment: host, not container

**The production path is a systemd timer on the host.** `systemctl`, `journalctl`, `ss -tulnp`, and host-scope process and disk views do not work meaningfully inside a container — a containerized agent reports on the container, not the machine you care about.

See [systemd/README.md](systemd/README.md) for installation, per-host configuration, and the rootless-Podman and privilege caveats.

The Docker image is retained **only as a CI smoke-test artifact**, verifying the graceful-degradation paths. It is not the production deployment.

---

## CLI Usage

```bash
python3 -m agent.monitor              #default: core metrics + uptime + health
python3 -m agent.monitor -s           #simple: core metrics only
python3 -m agent.monitor -a           #all: includes processes, features, app checks
python3 -m agent.monitor -H           #human-readable: formats bytes, percents, time, and load
python3 -m agent.monitor --no-exit-code  #always exit 0 (useful in CI pipelines)
python3 -m agent.monitor --html report.html  #write HTML report to reports/report.html
```

Flags can be combined: `python3 -m agent.monitor -a -H --no-exit-code`

**Exit codes** (without `--no-exit-code`): `0` HEALTHY · `1` WARNING · `2` CRITICAL

A configured service that is stopped or absent, and a configured endpoint that does not answer, are each a WARNING — see [systemd/README.md](systemd/README.md#exit-codes-and-alerting).

---

## Configuration

All configuration is environment variables, so one build serves any host.

### Thresholds

| Variable | Default | Meaning |
|---|---|---|
| `HEALTH_CPU_WARN` | 70 | CPU % warning threshold |
| `HEALTH_CPU_CRIT` | 85 | CPU % critical threshold |
| `HEALTH_MEM_WARN` | 70 | Memory % warning threshold |
| `HEALTH_MEM_CRIT` | 85 | Memory % critical threshold |
| `HEALTH_DISK_WARN` | 80 | Disk % warning threshold |
| `HEALTH_DISK_CRIT` | 90 | Disk % critical threshold |

```bash
HEALTH_CPU_CRIT=60 python3 -m agent.monitor
```

### Features

| Variable | Default | Meaning |
|---|---|---|
| `HEALTH_SERVICES` | `nginx,docker` | Comma-separated systemd units to check |
| `HEALTH_CONTAINER_USER` | *(unset)* | Owner of a rootless container runtime |
| `HEALTH_APP_ENDPOINTS` | *(unset)* | `name=url` pairs; unset omits the feature |
| `HEALTH_APP_TIMEOUT` | 2 | Per-endpoint timeout in seconds |
| `HEALTH_APP_CRITICAL` | *(unset)* | Endpoint names that count toward the health status; unset scores this host's own endpoints plus the VIP |
| `HEALTH_REPORT_MODE` | `0640` | Octal file mode for the written HTML report |
| `HEALTH_VIP` | *(unset)* | Virtual IP(s) to check against this host's own interfaces; unset omits the feature |
| `HEALTH_JOURNAL_WINDOW` | `-1h` | How far back to count journal errors (`journalctl --since` syntax) |
| `HEALTH_SELF_UNIT` | `health-monitor.service` | This monitor's own unit, excluded from the failed-unit count |

### Virtual IP ownership

For an active/passive pair, `HEALTH_VIP` answers which node currently holds the
floating address — the one thing an HTTP check against that address cannot tell
you, since a successful GET proves someone answered, not who.

```bash
HEALTH_VIP=192.168.71.250 python3 -m agent.monitor -a
```

Set the same value on every node in the pair: each reports `held: true|false`
for itself, and split-brain is two reports that both say `held`. Never affects
the health status — holding nothing is correct for the backup node.

### Application endpoint checks

Generic by design — the agent knows how to GET a URL, time it, and parse the response, but nothing about what any endpoint means.

```bash
HEALTH_APP_ENDPOINTS="api=http://127.0.0.1:8000/health,slo=http://127.0.0.1:8000/slo" \
  python3 -m agent.monitor -a
```

JSON object form is also accepted, for URLs containing a comma:

```bash
HEALTH_APP_ENDPOINTS='{"api": "http://127.0.0.1:8000/health"}' python3 -m agent.monitor -a
```

Each check records HTTP status, latency, and the parsed JSON body (or raw text for non-JSON). A non-2xx response still captures the body — that is exactly what a degraded service returns. Pointing a host at *several* hosts' endpoints turns its report into a fleet-wide dashboard.

---

## Example Output

```bash
HEALTH_APP_ENDPOINTS="api=http://127.0.0.1:8000/health" python3 -m agent.monitor -a -H
```

```json
{
  "timestamp": "2026-07-29T22:06:58+00:00",
  "system": {
    "os": "Linux",
    "distro": "Ubuntu 26.04 LTS",
    "kernel": "6.18.33.2-microsoft-standard-WSL2",
    "hostname": "node1",
    "cpu_cores": 8,
    "environment": "Linux"
  },
  "core_metrics": {
    "cpu": "3.3%",
    "memory": {
      "used_percent": "32.08%",
      "available": "3.89 GB",
      "swap_used_percent": "0.0%"
    },
    "disk": {
      "root_used_percent": "0.44%",
      "root_free": "951.47 GB"
    },
    "load": {
      "1min": "4.4%",
      "5min": "3.6%",
      "15min": "2.6%"
    },
    "disk_io": {
      "read_bytes_per_sec": "0.00 B/s",
      "write_bytes_per_sec": "0.00 B/s"
    },
    "processes": {
      "total": 61,
      "zombies": 0
    },
    "network": {
      "bytes_sent": "61.10 MB",
      "bytes_received": "288.91 MB"
    }
  },
  "uptime": "15h 17m 8s",
  "health": {
    "status": "HEALTHY",
    "alerts": [],
    "diagnosis": ["No issues detected"],
    "actions": []
  },
  "top_processes": [
    {
      "pid": 95758,
      "name": "python3",
      "cpu_percent": "10.0%",
      "memory_percent": "5.38%"
    }
  ],
  "features": {
    "containers": {
      "feature": "containers",
      "success": true,
      "container_runtime": "podman",
      "running_containers": ["brp-api"],
      "count": 1
    },
    "app_checks": {
      "feature": "app_checks",
      "success": true,
      "count": 1,
      "healthy": 1,
      "data": [
        {
          "name": "api",
          "url": "http://127.0.0.1:8000/health",
          "http_status": 200,
          "success": true,
          "latency_ms": 1.0,
          "data": {"status": "ok", "service": "brp-api"}
        }
      ]
    }
  }
}
```

---

## Architecture

```
agent/
├── monitor.py          — CLI entry point; orchestrates collection, analysis, and output
├── system_metrics.py   — collects system measurements from /proc, /sys, df, du
├── system_context.py   — detects environment; checks services, containers, ports
├── app_checks.py       — HTTP health checks against configured endpoints
├── health_analysis.py  — evaluates metrics against configurable thresholds
├── html_report.py      — formats and renders the HTML report
└── shell.py            — subprocess wrapper with timeout and graceful failure
systemd/                — production deployment: oneshot service + timer
```

---

## Requirements

- Python 3.12+ — **no third-party packages**
- A container runtime (optional): Docker or Podman
- Root (optional): enables `ss` process names, the system journal, and unit state

## Running

```bash
python3 -m agent.monitor
```

## Docker (CI smoke test only)

```bash
docker build -t linux-health-monitor .
docker run linux-health-monitor -a
```

Inside a container, `systemctl`-based features report themselves unavailable by design. See [Deployment](#deployment-host-not-container).

## Testing

```bash
pytest
```

Parser-level tests feed captured fixture text rather than the live host, so a format regression is caught deterministically instead of only on the machine that produces the odd layout. Cross-distro parity is verified by running `python3 -m agent.monitor --all` on hosts from different families and diffing the result — that exercises the parsers against different `procps` versions, which is the real portability test.

## CI/CD

GitHub Actions pipelines run on every push and pull request to `main`:

- **CI** — runs pytest, validates all CLI modes and flags
- **CD** — builds and pushes a Docker image to GitHub Container Registry (`ghcr.io`) tagged with `latest` and the commit SHA
