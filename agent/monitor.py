#monitor.py
from agent.system_metrics import get_cpu_usage, get_memory_usage, get_disk_usage, get_load_usage, get_network_io, get_system_uptime, get_log_file_usage_feature
from agent.processes import get_top_processes
from agent.snapshot import build_snapshot, get_system_identity
from agent.analysis import compute_health_status, generate_alerts, generate_diagnosis, generate_recommendations
from agent.environment import detect_environment
from agent.services import get_system_services, get_docker_status
from agent.utils import get_timestamp
import json

"""
Linux Health Monitor Agent

A lightweight, environment-aware system observability tool that collects
system metrics and provides structured health reporting, diagnosis, and
recommended remediation actions.

Features:
- CPU, memory, disk, load monitoring
- Process inspection
- Service and Docker awareness (graceful degradation)
- Environment detection (Linux, WSL2, Docker, CI)
- Automated health status, alerts, diagnosis, and actions

Designed for portability and safe execution across:
Linux, WSL2, Docker containers, and CI/CD environments.
"""

class HealthMonitor:
    def __init__(self):
        self.env = detect_environment()

    def collect_metrics(self):
        return {
            "cpu": get_cpu_usage(),
            "memory": get_memory_usage(),
            "disk": get_disk_usage(),
            "load": get_load_usage(),
        }

    def analyze(self, metrics):
        ctx = build_snapshot(
            metrics["cpu"],
            metrics["memory"],
            metrics["disk"],
            metrics["load"]
        )

        return {
            "status": compute_health_status(ctx),
            "alerts": generate_alerts(ctx),
            "diagnosis": generate_diagnosis(ctx),
            "actions": generate_recommendations(ctx, self.env),
        }

    def report(self):
        metrics = self.collect_metrics()
        analysis = self.analyze(metrics)

        return {
            "timestamp": get_timestamp(),
            "system": get_system_identity(),
            "uptime_seconds": get_system_uptime(),

            "core_metrics": {
                **metrics,
                "network": get_network_io(),
            },

            "top_processes": get_top_processes(),

            "health": analysis,

            "features": {
            "services": get_system_services(self.env),
            "docker": get_docker_status(),
            "disk_details": get_log_file_usage_feature(),
            },
        }


def main():
    monitor = HealthMonitor()
    data = monitor.report()

    print(json.dumps(data, indent=2))

    if data["health"]["status"] == "WARNING":
        exit(1)
    elif data["health"]["status"] == "CRITICAL":
        exit(2)

    exit(0)


if __name__ == "__main__":
    main()