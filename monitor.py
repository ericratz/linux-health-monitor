from datetime import datetime, timezone
import os
import sys
import time
import json
import psutil
import platform
import subprocess

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
#utilities
def get_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_command(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3
        )
        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Command timed out",
            "returncode": -1,
            "success": False
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
            "success": False
        }
    

def safe_run(name, fn, fallback=None):
    try:
        return {
            "feature": name,
            "success": True,
            "data": fn()
        }
    except Exception as e:
        return {
            "feature": name,
            "success": False,
            "error": str(e),
            "fallback": fallback
        }


def detect_environment():
    if os.getenv("CI") == "true":
        return "CI"
    if os.getenv("GITHUB_ACTIONS") == "true":
        return "GitHub Actions"
    if is_docker():
        return "Docker"
    release = platform.release().lower()
    if "microsoft" in release or "wsl" in release:
        return "WSL2"
    return "Linux"


def is_docker():
    # 1. Strong signal: /.dockerenv
    if os.path.exists("/.dockerenv"):
        return True

    # 2. Strong signal: cgroup with container-like path
    try:
        with open("/proc/1/cgroup", "rt") as f:
            for line in f:
                if any(x in line for x in ["docker/", "kubepods/", "containerd/"]):
                    return True
    except Exception:
        pass

    # 3. Weak signal: env var (only trust if explicitly set)
    if os.getenv("container", "").lower() in ["docker", "containerd"]:
        return True

    return False


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


def safe_docker():
    result = run_command(["docker", "ps"])

    if not result["success"]:
        return {
            "feature": "docker",
            "success": False,
            "error": result["stderr"],
            "data": "docker unavailable or not mounted"
        }

    return {
        "feature": "docker",
        "success": True,
        "data": result["stdout"]
    }


def get_uptime_seconds():
    return int(time.time() - psutil.boot_time())


#metrics
def get_cpu():
    return psutil.cpu_percent(interval=0.5)


def get_load():
    load1, load5, load15 = os.getloadavg()
    return {
        "1min": load1,
        "5min": load5,
        "15min": load15
    }


def top_processes(limit=5):
    procs = []

    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            info = p.info

            procs.append({
                "pid": info["pid"],
                "name": info["name"],
                "cpu_percent": round(info["cpu_percent"], 1),
                "memory_percent": round(info["memory_percent"], 1)
            })

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return sorted(procs, key=lambda x: x['cpu_percent'], reverse=True)[:limit]


def get_memory():
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "used_percent": round(memory.percent, 1),
        "available_mb": round(memory.available / 1024 / 1024, 1),
        "swap_used_percent": round(swap.percent, 1)
    }


def get_disk():
    disk = psutil.disk_usage("/")
    return {
        "root_used_percent": round(disk.percent, 1),
        "root_free_gb": round(disk.free / 1024 / 1024 / 1024, 1)
    }


def disk_usage_details(path="/var/log"):
    usage = []
    for entry in os.scandir(path):
        try:
            size = os.stat(entry.path).st_size
            usage.append((entry.name, size))
        except:
            continue
    return sorted(usage, key=lambda x: x[1], reverse=True)[:5]


def safe_disk_details():
    try:
        return {
            "feature": "disk_details",
            "success": True,
            "data": disk_usage_details()
        }
    except PermissionError:
        return {
            "feature": "disk_details",
            "success": False,
            "error": "permission denied",
            "data": None
        }


def get_network():
    net = psutil.net_io_counters()
    return {
        "bytes_sent": format_bytes(net.bytes_sent),
        "bytes_received": format_bytes(net.bytes_recv)
    }


def safe_services(env):
    if env in ["Docker", "CI", "WSL2"]:
        return {
            "feature": "services",
            "success": False,
            "reason": f"systemctl not available in {env}",
            "data": None
        }

    return {
        "feature": "services",
        "success": True,
        "data": [
            check_service("nginx"),
            check_service("docker")
        ]
    }


def check_service(name):
    result = run_command(["systemctl", "is-active", name])

    if not result["success"]:
        return {
            "service": name,
            "status": "unknown",
            "error": result["stderr"]
        }

    return {
        "service": name,
        "status": result["stdout"]  # active, inactive, failed
    }


def health_status(ctx):
    cpu = ctx["cpu"]
    mem = ctx["mem_used"]
    disk = ctx["disk_used"]

    if cpu > 85 or mem > 85 or disk > 90:
        return "CRITICAL"
    elif cpu > 70 or mem > 70 or disk > 80:
        return "WARNING"
    return "HEALTHY"


def build_alerts(ctx):
    alerts = []

    if ctx["cpu"] > 70:
        alerts.append("High CPU usage")
    if ctx["mem_used"] > 70:
        alerts.append("High memory usage")
    if ctx["disk_used"] > 80:
        alerts.append("High disk usage")
    return alerts

    
def build_diagnosis(ctx):
    notes = []

    if ctx["load"]["1min"] > ctx["cpu"]:
        notes.append("High load but lower CPU → possible I/O wait or blocked processes")

    if ctx["cpu"] > 80:
        notes.append("CPU is high → check top processes (ps/top)")

    if ctx["disk_used"] > 85:
        notes.append("Disk usage high → check /var/log or large files (du)")

    if ctx["mem_used"] > 80:
        notes.append("Memory high → possible memory leak or high usage process")

    return notes


def build_actions(ctx, env):
    actions = []

    if ctx["cpu"] > 80:
        actions.append("Run: ps aux --sort=-%cpu")

    if ctx["disk_used"] > 85:
        actions.append("Run: du -sh /var/log/*")

    if ctx["mem_used"] > 80:
        actions.append("Run: ps aux --sort=-%mem")

    if env == "Linux":
        actions.append("Check logs: journalctl -u <service>")

    return actions


def build_context(cpu, memory, disk, load):
    return {
        "cpu": cpu,
        "mem_used": memory["used_percent"],
        "disk_used": disk["root_used_percent"],
        "load": load
    }

#reporting
def report():
    env = detect_environment()
    cpu = get_cpu()
    memory = get_memory()
    disk = get_disk()
    load = get_load()
    context = build_context(cpu, memory, disk, load)
    
    return {
        "timestamp": get_timestamp(),
        "system": system_identity(),

        "core_metrics": {
            "cpu": cpu,
            "memory": memory,
            "disk": disk,
            "load": load
        },

        "top_processes": top_processes(),
        "status": health_status(context),
        "alerts": build_alerts(context),
        "diagnosis": build_diagnosis(context),
        "recommended_actions": build_actions(context, env),
        #safe features that may not work in all environments
        "services": safe_services(env),
        "docker": safe_docker(),
        "disk_details": safe_disk_details(),
        "network": get_network(),

        
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