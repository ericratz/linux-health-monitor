# Linux Health Monitor Agent v2.3

A lightweight, environment-aware system observability tool that collects system metrics and provides structured health reporting, diagnosis, and recommended remediation actions. Designed for portability and safe execution across: Linux, WSL2, Docker containers, and CI/CD environments.

It performs the following:

1. Collects system metrics (CPU, memory, disk, load, network, uptime)

2. Detects execution environment (Linux, WSL2, Docker, CI)

3. Performs optional system feature checks (systemd services, docker CLI, log/disk usage inspection)

4. Generates health analysis (status, alerts, and recommended actions)

5. Outputs structured JSON for automation or logging

*note that some features are not available in all environments.
---

## Additional Features

- CLI Modes (-s for simple output, default for uptime and health check, and -a for all features)

- HTML output human-readable report (`--html <file>.html`) (not supported in Docker)

## Output from Docker:
```json
ericratz@W530:~/linux-health-monitor$ docker run linux-agent-monitor
{
  "timestamp": "2026-05-15T02:26:40+00:00",
  "system": {
    "os": "Linux",
    "distro": "Debian GNU/Linux 13 (trixie)",
    "kernel": "6.6.114.1-microsoft-standard-WSL2",
    "hostname": "59d2e0b6bd82",
    "cpu_cores": 8,
    "environment": "Docker"
  },
  "core_metrics": {
    "cpu": 4.1,
    "memory": {
      "used_percent": 31.5,
      "available": 4215689216,
      "swap_used_percent": 0.0
    },
    "disk": {
      "root_used_percent": 2.0,
      "root_free": 1005406380032
    },
    "load": {
      "1min": 0.66,
      "5min": 0.2,
      "15min": 0.09
    },
    "disk_io": {
      "read_bytes_per_sec": 191146,
      "write_bytes_per_sec": 13653
    },
    "processes": {
      "total": 1,
      "zombies": 0
    },
    "network": {
      "bytes_sent": 42,
      "bytes_received": 538
    }
  },
  "uptime_seconds": 159063,
  "health": {
    "status": "HEALTHY",
    "diagnosis": [
      "No issues detected"
    ]
  }
}
```

## Requirements:
-Python 3.12+

-Docker (optional)

psutil

## How to run:
```bash
python -m agent.monitor
```
(-s for simple, -a for all, and --html <file>.html for HTML output)

## Docker build image:
```bash
docker build -t linux-health-monitor .
docker run linux-health-monitor
```

## Testing
pytest

## CI/CD
Github Actions pipeline includes:

- Installs dependencies

- pytest validation

- Validates CLI modes

- Verifies HTML report generation

- Docker build verification

- Pushes image to GitHub Container Registry