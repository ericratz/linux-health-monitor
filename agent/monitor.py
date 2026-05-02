#monitor.py - main code driver
from agent.system_metrics import (
    get_cpu_usage,
    get_memory_usage,
    get_disk_usage,
    get_load_average,
    get_network_io,
    get_system_uptime,
    get_top_processes
)

from agent.health_analysis import (
    generate_health_status,
    generate_alerts,
    generate_diagnostics,
    generate_recommendations,
    
)
from agent.system_context import (
    detect_environment,
    get_service_statuses,
    get_docker_containers,
    get_system_identity,
    get_disk_details
)
from agent.html_report import generate_html
from datetime import datetime, timezone
import argparse
import json
import os

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

    def collect_core_metrics(self):
        """
        Collects CPU, memory, disk, and load metrics.
        """
        return {
            "cpu": get_cpu_usage(),
            "memory": get_memory_usage(),
            "disk": get_disk_usage(),
            "load": get_load_average(),
        }

    def run_health_analysis(self, metrics):
        """
        Generates a health report from relevant metrics.
        """
        mem = metrics["memory"]["used_percent"]
        disk = metrics["disk"]["root_used_percent"]
        ctx = {
            "cpu": metrics["cpu"],
            "mem_used": mem,
            "disk_used": disk,
            "load": metrics["load"],
        }
        return {
            "status": generate_health_status(ctx),
            "alerts": generate_alerts(ctx),
            "diagnosis": generate_diagnostics(ctx),
            "actions": generate_recommendations(ctx, self.env),
        }

    def report(self):
        """
        Generates a comprehensive system health report into a dictionary.
        """
        metrics = self.collect_core_metrics()
        analysis = self.run_health_analysis(metrics)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "system": get_system_identity(self.env),
            "uptime_seconds": get_system_uptime(),
            "core_metrics": {
                **metrics,
                "network": get_network_io(),
            },
            "top_processes": get_top_processes(),
            "health": analysis,
            "features": {
            "services": get_service_statuses(self.env),
            "docker": get_docker_containers(),
            "disk_details": get_disk_details(),
            },
        }


def parse_args():
    """
    Parses command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Linux Health Monitor")
    parser.add_argument("-s", "--simple", action="store_true")
    parser.add_argument("-a", "--all", action="store_true")
    parser.add_argument("--html", metavar="FILE", help="Write HTML report")
    return parser.parse_args()

def write_output(view, html_file=None):
    """
    Outputs as JSON or HTML file.
    """
    try:
        if html_file:
            html = generate_html(view)
            os.makedirs("reports", exist_ok=True)
            output_path = os.path.join("reports", html_file)
            with open(output_path, "w") as f:
                f.write(html)
        else:
            print(json.dumps(view, indent=2))
    except Exception as e:
        print("HTML generation failed:", e)
        raise

def build_view(data, mode):
    """
    Builds a mode-specific view of the system's current state.
    """
    base = {
        "timestamp": data["timestamp"],
        "system": data["system"],
        "core_metrics": data["core_metrics"],
    }
    #simple mode
    if mode == "simple":
        return base
    #default mode
    base.update(
        {
            "uptime_seconds": data.get("uptime_seconds"),
            "health": {
                "status": data["health"]["status"],
                "diagnosis": data["health"]["diagnosis"],
            },
        }
    )
    #all mode
    if mode == "all":
        base.update(
            {
                "top_processes": data.get("top_processes"),
                "health": data["health"],
                "features": data.get("features"),
            }
        )
    return base

def main():
    """
    Main code driver.
    """
    #handle args
    args = parse_args()

    #initialize monitor
    monitor = HealthMonitor()

    #collect data
    data = monitor.report()

    #select mode
    if args.simple:
        mode = "simple"
    elif args.all:
        mode = "all"
    else:
        mode = "default"

    #build view
    view = build_view(data, mode)

    #write output
    write_output(view, args.html)

    #exit with appropriate code
    status = data["health"]["status"]

    if status == "WARNING":
        exit(1)
    elif status == "CRITICAL":
        exit(2)    
    exit(0)


if __name__ == "__main__":
    main()