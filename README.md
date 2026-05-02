# Linux Health Monitor Agent v2.1

A lightweight, environment-aware system observability tool that collects system metrics and provides structured health reporting, diagnosis, and recommended remediation actions. Designed for portability and safe execution across: Linux, WSL2, Docker containers, and CI/CD environments.

It performs the following:

1. Collects system metrics (CPU, memory, disk, load, network, uptime)

2. Detects execution environment (Linux, WSL2, Docker, CI)

3. Performs optional system feature checks (systemd services, docker cli, log/disk usage inspection)

4. Generates health analysis (status, alerts, and recommended actions)

5. Outputs structured JSON for automation or logging

---

## Features:
- CPU, memory, disk, load monitoring

- Process inspection (top CPU/memory consumers)

- Service inspection (systemd)

- Docker inspection (CLI)

- Environment detection (Linux, WSL2, Docker, CI)

- Log/disk usage analysis

- Automated health status, alerts, diagnosis, and actions

*note that some features are not available in all environments.

## Output from Docker:
```json
{
  "timestamp": "2026-05-01T23:45:27+00:00",
  "system": {
    "os": "Linux",
    "distro": "Debian GNU/Linux 13 (trixie)",
    "kernel": "6.6.87.2-microsoft-standard-WSL2",
    "hostname": "92e422183e45",
    "environment": "Docker"
  },
  "uptime_seconds": 98850,
  "core_metrics": {
    "cpu": 0.8,
    "memory": {
      "used_percent": 48.7,
      "available_mb": 3008.6,
      "swap_used_percent": 0.0
    },
    "disk": {
      "root_used_percent": 0.2,
      "root_free_gb": 953.8
    },
    "load": {
      "1min": 0.31,
      "5min": 0.23,
      "15min": 0.18
    },
    "network": {
      "bytes_sent": "42.0 B",
      "bytes_received": "498.0 B"
    }
  },
  "top_processes": [
    {
      "pid": 1,
      "name": "python",
      "cpu_percent": 0.0,
      "memory_percent": 0.23
    }
  ],
  "health": {
    "status": "HEALTHY",
    "alerts": [],
    "diagnosis": [
      "No issues detected"
    ],
    "actions": []
  },
  "features": {
    "services": {
      "feature": "services",
      "success": false,
      "reason": "systemctl not available in Docker",
      "data": null
    },
    "docker": {
      "feature": "docker",
      "success": false,
      "reason": "docker CLI not available in environment",
      "data": null
    },
    "disk_details": {
      "feature": "disk_details",
      "success": true,
      "data": [
        {
          "name": "dpkg.log",
          "size": "119.5 KB"
        },
        {
          "name": "apt",
          "size": "4.0 KB"
        },
        {
          "name": "alternatives.log",
          "size": "3.5 KB"
        },
        {
          "name": "wtmp",
          "size": "0.0 B"
        },
        {
          "name": "btmp",
          "size": "0.0 B"
        }
      ]
    }
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

## Docker build image:
```bash
docker build -t linux-health-monitor .
docker run linux-health-monitor
```

## Testing
pytest

## CI/CD
Github Actions pipeline includes:

-pytest validation

-Docker build verification

-Execution sanity check

## Architecture
```bash
__init__.py

analysis.py
compute_health_status(ctx)
generate_alerts(ctx)
generate_diagnosis(ctx)
generate_recommendations(ctx,env)

environment.py
detect_environment()
is_docker()
get_environment_summary(env)

monitor.py
class HealthMonitor
__init__
collect_metrics()
analyze(metrics)
report()
main()

processes.py
get_top_processes(limit=5)

services.py
get_system_services(env)
check_service_status(name)
get_docker_status()

snapshot.py
get_system_identity()
build_snapshot(cpu, memory, disk, load)

system_metrics.py
get_cpu_usage()
get_load_usage()
get_memory_usage()
get_disk_usage()
get_log_directory_usage()
get_log_file_usage_feature()
get_network_io()
get_system_uptime()

utils.py
get_timestamp()
run_command(command)
safe_run(name, fn, fallback=None)
format_bytes(num)
```