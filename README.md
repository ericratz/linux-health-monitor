# Linux Health Monitor Agent v2.0

A lightweight, environment-aware system observability tool that collects system metrics and provides structured health reporting, diagnosis, and recommended remediation actions. Designed for portability and safe execution across: Linux, WSL2, Docker containers, and CI/CD environments.

It performs the following:

1. Collects system metrics

2. Detects execution environment

3. Attempts optional system inspections (systemd services, docker cli, disk usage inspection)

4. Applies health logic (status, alert, diagnostics)

5. Outputs structured JSON for automation or logging

---

## Features:
- CPU, memory, disk, load monitoring

- Process inspection

- Service and Docker awareness (graceful degradation)

- Environment detection (Linux, WSL2, Docker, CI)

- Automated health status, alerts, diagnosis, and actions

*note that some features are not available in all environments.

---

## Output from Docker:
```json
{
  "timestamp": "2026-05-01T18:16:09+00:00",
  "system": {
    "os": "Linux",
    "distro": "Debian GNU/Linux 13 (trixie)",
    "kernel": "6.6.87.2-microsoft-standard-WSL2",
    "hostname": "1ef4522106c7",
    "environment": "Docker"
  },
  "core_metrics": {
    "cpu": 10.6,
    "memory": {
      "used_percent": 41.2,
      "available_mb": 3448.0,
      "swap_used_percent": 0.0
    },
    "disk": {
      "root_used_percent": 0.2,
      "root_free_gb": 953.8
    },
    "load": {
      "1min": 0.220703125,
      "5min": 0.07080078125,
      "15min": 0.06689453125
    }
  },
  "top_processes": [
    {
      "pid": 1,
      "name": "python",
      "cpu_percent": 0.0,
      "memory_percent": 0.2
    }
  ],
  "status": "HEALTHY",
  "alerts": [],
  "diagnosis": [],
  "recommended_actions": [],
  "services": {
    "feature": "services",
    "success": false,
    "reason": "systemctl not available in Docker",
    "data": null
  },
  "docker": {
    "feature": "docker",
    "success": false,
    "error": "[Errno 2] No such file or directory: 'docker'",
    "data": "docker unavailable or not mounted"
  },
  "disk_details": {
    "feature": "disk_details",
    "success": true,
    "data": [
      [
        "dpkg.log",
        122366
      ],
      [
        "apt",
        4096
      ],
      [
        "alternatives.log",
        3632
      ],
      [
        "wtmp",
        0
      ],
      [
        "btmp",
        0
      ]
    ]
  },
  "network": {
    "bytes_sent": "42.0 B",
    "bytes_received": "538.0 B"
  }
}
```
---

## Requirements:
-Python 3.12+


-Docker

---

## How to run:
python monitor.py

---

## Docker build image:
```bash
docker build -t linux-health-monitor .
docker run linux-health-monitor
```

---

## CI/CD
-Uses Github Actions

-pytest for validation

-Docker build verification

-Execution sanity check