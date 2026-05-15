# Linux Health Monitor Agent v2.4

A lightweight, environment-aware system observability tool that collects system metrics and generates structured health reports with automated diagnosis and remediation guidance. Designed for safe, portable execution across Linux, WSL2, Docker, and CI/CD environments.

---

## What It Does

1. Collects core system metrics — CPU, memory, disk, load, disk I/O, network, uptime, and process count
2. Detects the execution environment — Linux, WSL2, Docker, CI/GitHub Actions
3. Checks system features — running services, failed services, Docker containers, log disk usage, and CPU temperature
4. Evaluates health — threshold-based status (HEALTHY / WARNING / CRITICAL) with alerts, diagnosis, and recommended actions
5. Outputs structured JSON for automation or an HTML report for human review

> Some features gracefully degrade when unavailable (e.g. systemctl in Docker, CPU temperature in WSL2).

---

## CLI Usage

```bash
python -m agent.monitor              # default: core metrics + uptime + health
python -m agent.monitor -s           # simple: core metrics only
python -m agent.monitor -a           # all: includes processes, services, disk details
python -m agent.monitor -H           # human-readable: formats bytes, percents, time, and load
python -m agent.monitor --no-exit-code  # always exit 0 (useful in CI pipelines)
python -m agent.monitor --html report.html  # write HTML report to reports/report.html
```

Flags can be combined: `python -m agent.monitor -a -H --no-exit-code`

**Exit codes** (without `--no-exit-code`): `0` HEALTHY · `1` WARNING · `2` CRITICAL

---

## Configurable Thresholds

Health thresholds can be overridden via environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `HEALTH_CPU_WARN` | 70 | CPU % warning threshold |
| `HEALTH_CPU_CRIT` | 85 | CPU % critical threshold |
| `HEALTH_MEM_WARN` | 70 | Memory % warning threshold |
| `HEALTH_MEM_CRIT` | 85 | Memory % critical threshold |
| `HEALTH_DISK_WARN` | 80 | Disk % warning threshold |
| `HEALTH_DISK_CRIT` | 90 | Disk % critical threshold |

```bash
HEALTH_CPU_CRIT=60 python -m agent.monitor
```

---

## Example Output

```bash
docker run linux-health-monitor -a -H
```

```json
{
  "timestamp": "2026-05-15T01:07:43+00:00",
  "system": {
    "os": "Linux",
    "distro": "Debian GNU/Linux 13 (trixie)",
    "kernel": "6.6.114.1-microsoft-standard-WSL2",
    "hostname": "b02edfe32c60",
    "cpu_cores": 8,
    "environment": "Docker"
  },
  "core_metrics": {
    "cpu": "2.1%",
    "memory": {
      "used_percent": "31.4%",
      "available": "3.93 GB",
      "swap_used_percent": "0.0%"
    },
    "disk": {
      "root_used_percent": "2.0%",
      "root_free": "936.36 GB"
    },
    "load": {
      "1min": "2.8%",
      "5min": "2.4%",
      "15min": "2.1%"
    },
    "disk_io": {
      "read_bytes_per_sec": "0.00 B/s",
      "write_bytes_per_sec": "0.00 B/s"
    },
    "processes": {
      "total": 3,
      "zombies": 0
    },
    "network": {
      "bytes_sent": "42.00 B",
      "bytes_received": "388.00 B"
    }
  },
  "uptime": "1d 18h 52m 6s",
  "health": {
    "status": "HEALTHY",
    "alerts": [],
    "diagnosis": ["No issues detected"],
    "actions": []
  },
  "top_processes": [
    {
      "pid": 1,
      "name": "python",
      "cpu_percent": "3.3%",
      "memory_percent": "0.25%"
    }
  ]
}
```

---

## Architecture

```
agent/
├── monitor.py          — CLI entry point; orchestrates collection, analysis, and output
├── system_metrics.py   — collects all system measurements (CPU, memory, disk, processes, etc.)
├── system_context.py   — detects environment and checks system features (services, Docker, etc.)
├── health_analysis.py  — evaluates metrics against configurable thresholds
└── html_report.py      — formats and renders the HTML report
```

---

## Requirements

- Python 3.12+
- `psutil`
- Docker (optional)

## Running

```bash
pip install -r requirements.txt
python -m agent.monitor
```

## Docker

```bash
docker build -t linux-health-monitor .
docker run linux-health-monitor
docker run linux-health-monitor -a -H
```

## Testing

```bash
pytest
```

## CI/CD

GitHub Actions pipelines run on every push and pull request to `main`:

- **CI** — installs dependencies, runs pytest, validates all CLI modes and flags
- **CD** — builds and pushes a Docker image to GitHub Container Registry (`ghcr.io`) tagged with `latest` and the commit SHA
