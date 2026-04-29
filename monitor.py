from datetime import datetime, timezone
import os
import sys
import time
import json
import psutil
import platform

"""
Linux Health Monitor
Collects system metrics and outputs a structured JSON report.
Designed for portability across Linux, WSL2, and Docker environments.
"""
#utilities
def get_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def detect_environment():
    if os.getenv("CI") == "true":
        return "CI"
    if os.getenv("GITHUB_ACTIONS") == "true":
        return "GitHub Actions"
    release = platform.release().lower()
    if "microsoft" in release or "wsl" in release:
        return "WSL2"
    if os.path.exists("/.dockerenv"):
        return "Docker"
    return "Linux"


def format_bytes(num):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


#system info
def system_identity():
    return {
        "os": platform.system(),
        "distro": (
            platform.freedesktop_os_release().get("PRETTY_NAME", "Unknown")
            if hasattr(platform, "freedesktop_os_release")
            else "Unknown"
        ),
        "kernel": platform.release(),
        "hostname": platform.node(),
        "environment": detect_environment()
    }


def get_uptime_seconds():
    return int(time.time() - psutil.boot_time())


#metrics
def get_cpu():
    return psutil.cpu_percent(interval=0.5)


def get_memory():
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "used_percent": memory.percent,
        "available_mb": round(memory.available / 1024 / 1024, 1),
        "swap_used_percent": swap.percent
    }


def get_disk():
    disk = psutil.disk_usage("/")
    return {
        "root_used_percent": disk.percent,
        "root_free_gb": round(disk.free / 1024 / 1024 / 1024, 1)
    }


def get_network():
    net = psutil.net_io_counters()
    return {
        "bytes_sent": format_bytes(net.bytes_sent),
        "bytes_received": format_bytes(net.bytes_recv)
    }


def health_status(cpu, mem, disk):
    if cpu > 85 or mem > 85 or disk > 90:
        return "CRITICAL"
    elif cpu > 70 or mem > 70 or disk > 80:
        return "WARNING"
    return "HEALTHY"


def build_alerts(cpu, mem, disk):
    alerts = []
    if cpu > 70:
        alerts.append("High CPU usage")
    if mem > 70:
        alerts.append("High memory usage")
    if disk > 80:
        alerts.append("High disk usage")
    return alerts

#reporting
def report():
    cpu = get_cpu()
    memory = get_memory()
    disk = get_disk()
    status = health_status(
        cpu,
        memory["used_percent"],
        disk["root_used_percent"]
    )
    return {
        "timestamp": get_timestamp(),
        "system": system_identity(),
        "uptime_seconds": get_uptime_seconds(),
        "cpu_usage_percent": cpu,
        "memory": memory,
        "disk": disk,
        "network": get_network(),
        "status": status,
        "alerts": build_alerts(
            cpu,
            memory["used_percent"],
            disk["root_used_percent"]
        )
    }


def main():
    data = report()
    print(json.dumps(data, indent=2))
    if data["status"] == "WARNING":
        sys.exit(1)
    elif data["status"] == "CRITICAL":
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()