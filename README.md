# Linux Health Monitor Agent v2.2

A lightweight, environment-aware system observability tool that collects system metrics and provides structured health reporting, diagnosis, and recommended remediation actions. Designed for portability and safe execution across: Linux, WSL2, Docker containers, and CI/CD environments.

It performs the following:

1. Collects system metrics (CPU, memory, disk, load, network, uptime)

2. Detects execution environment (Linux, WSL2, Docker, CI)

3. Performs optional system feature checks (systemd services, docker cli, log/disk usage inspection)

4. Generates health analysis (status, alerts, and recommended actions)

5. Outputs structured JSON for automation or logging

*note that some features are not available in all environments.
---

## Additional Features

- CLI Modes (-s for simple output, default for uptime and health check, and -a for full report)

- HTML output report (--html <file>.html) (not supported in Docker)

## Output from Docker:
```json
{
  "timestamp": "2026-05-02T03:51:03+00:00",
  "system": {
    "os": "Linux",
    "distro": "Debian GNU/Linux 13 (trixie)",
    "kernel": "6.6.87.2-microsoft-standard-WSL2",
    "hostname": "44eca254f227",
    "environment": "Docker"
  },
  "core_metrics": {
    "cpu": 18.4,
    "memory": {
      "used_percent": 51.6,
      "available_mb": 2840.0,
      "swap_used_percent": 0.0
    },
    "disk": {
      "root_used_percent": 0.2,
      "root_free_gb": 953.8
    },
    "load": {
      "1min": 0.46,
      "5min": 0.18,
      "15min": 0.08
    },
    "network": {
      "bytes_sent": "42.0 B",
      "bytes_received": "388.0 B"
    }
  },
  "uptime_seconds": 113587,
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
python -m agent.monitor (-s for simple, -a for all, and --html <file>.html for html-readable output)
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

- Installs dependencies

- pytest validation

- Validates CLI modes

- Verifies HTML report generation

- Docker build verification

- Pushes image to GitHub Container Registry

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

format.py
build_view(data, mode)

html_report.py
safe_get(data, *keys, default=None)
generate_html(data)

monitor.py
class HealthMonitor
__init__
collect_metrics()
analyze(metrics)
report()
parse_args()
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
get_log_directory_usage(path="/var/log")
get_log_file_usage_feature()
get_network_io()
get_system_uptime()

utils.py
get_timestamp()
run_command(command)
safe_run(name, fn, fallback=None)
format_bytes(num)
```