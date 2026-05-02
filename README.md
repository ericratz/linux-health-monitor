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
ericratz@W530:~/linux-health-monitor$ docker run linux-health-monitor
{
  "timestamp": "2026-05-02T22:51:56+00:00",
  "system": {
    "os": "Linux",
    "distro": "Debian GNU/Linux 13 (trixie)",
    "kernel": "6.6.87.2-microsoft-standard-WSL2",
    "hostname": "1db012265ab4",
    "environment": "Docker"
  },
  "core_metrics": {
    "cpu": 25.4,
    "memory": {
      "used_percent": 51.9,
      "available": 2957676544,
      "swap_used_percent": 0.0
    },
    "disk": {
      "root_used_percent": 0.2,
      "root_free": 1024091586560
    },
    "load": {
      "1min": 0.09,
      "5min": 0.12,
      "15min": 0.15
    },
    "network": {
      "bytes_sent": 42,
      "bytes_received": 648
    }
  },
  "uptime_seconds": 150527,
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

## Architecture
```bash
__init__.py - package

health_analysis.py - logic
generate_health_status(ctx)
generate_alerts(ctx)
generate_diagnostics(ctx)
generate_recommendations(ctx,env)

html_report.py - presentation
format_uptime(seconds)
format_bytes(num)
format_network(network)
format_memory(memory)
format_disk(disk)
format_disk_details(features)
render_card(title, content)
format_core(core)
generate_html(data)

monitor.py - orchestration
class HealthMonitor
__init__(self)
collect_core_metrics(self)
run_health_analysis(self, metrics)
report(self)
parse_args()
write_output(view, html_file=None)
build_view(data, mode)
main()

system_context.py - environment
run_command(command)
detect_environment()
get_system_identity(env)
is_docker()
get_service_statuses(env)
get_service_status(name)
get_docker_containers()
get_disk_details()

system_metrics.py - collection
get_cpu_usage()
get_load_average()
get_memory_usage()
get_disk_usage()
get_directory_usage(path="/var/log")
get_network_io()
get_system_uptime()
get_top_processes(limit=5)
```