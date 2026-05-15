#health_analysis.py
import os

def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (ValueError, TypeError):
        return float(default)

def _thresholds():
    return {
        "cpu_warn":  _env_float("HEALTH_CPU_WARN",  70),
        "cpu_crit":  _env_float("HEALTH_CPU_CRIT",  85),
        "mem_warn":  _env_float("HEALTH_MEM_WARN",  70),
        "mem_crit":  _env_float("HEALTH_MEM_CRIT",  85),
        "disk_warn": _env_float("HEALTH_DISK_WARN", 80),
        "disk_crit": _env_float("HEALTH_DISK_CRIT", 90),
    }

def build_snapshot(cpu, memory, disk, load):
    return {
        "cpu": cpu,
        "mem_used": memory["used_percent"],
        "disk_used": disk["root_used_percent"],
        "load": load
    }

def generate_health_status(ctx):
    t = _thresholds()
    cpu, mem, disk = ctx["cpu"], ctx["mem_used"], ctx["disk_used"]
    if cpu > t["cpu_crit"] or mem > t["mem_crit"] or disk > t["disk_crit"]:
        return "CRITICAL"
    if cpu > t["cpu_warn"] or mem > t["mem_warn"] or disk > t["disk_warn"]:
        return "WARNING"
    return "HEALTHY"


def generate_alerts(ctx):
    t = _thresholds()
    alerts = []
    if ctx["cpu"] > t["cpu_warn"]:
        alerts.append("High CPU usage")
    if ctx["mem_used"] > t["mem_warn"]:
        alerts.append("High memory usage")
    if ctx["disk_used"] > t["disk_warn"]:
        alerts.append("High disk usage")
    return alerts


def generate_diagnostics(ctx):
    t = _thresholds()
    notes = []
    if ctx["load"]["1min"] > 0.5 and ctx["load"]["1min"] > ctx["cpu"]:
        notes.append("High load but lower CPU -> possible I/O wait or blocked processes")
    if ctx["cpu"] > t["cpu_warn"]:
        notes.append("CPU is high -> check top processes (ps/top)")
    if ctx["disk_used"] > t["disk_warn"]:
        notes.append("Disk usage high -> check /var/log or large files (du)")
    if ctx["mem_used"] > t["mem_warn"]:
        notes.append("Memory high -> possible memory leak or heavy process")
    if not notes:
        notes.append("No issues detected")
    return notes


def generate_recommendations(ctx, env):
    t = _thresholds()
    actions = []
    if ctx["cpu"] > t["cpu_warn"]:
        actions.append("Run: ps aux --sort=-%cpu")
    if ctx["disk_used"] > t["disk_warn"]:
        actions.append("Run: du -sh /var/log/*")
    if ctx["mem_used"] > t["mem_warn"]:
        actions.append("Run: ps aux --sort=-%mem")
    if actions and env == "Linux":
        actions.append("Check logs: journalctl -u <service>")
    return actions
