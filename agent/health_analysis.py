#health_analysis.py
def build_snapshot(cpu, memory, disk, load):
    """
    Builds a snapshot of the system's current state.
    """
    return {
        "cpu": cpu,
        "mem_used": memory["used_percent"],
        "disk_used": disk["root_used_percent"],
        "load": load
    }

def generate_health_status(ctx):
    """
    Evaluates system metrics and returns a health status.
    """
    cpu = ctx["cpu"]
    mem = ctx["mem_used"]
    disk = ctx["disk_used"]

    if cpu > 85 or mem > 85 or disk > 90:
        return "CRITICAL"
    elif cpu > 70 or mem > 70 or disk > 80:
        return "WARNING"
    return "HEALTHY"


def generate_alerts(ctx):
    """
    Generates alert messages for high system usage.
    """
    alerts = []

    if ctx["cpu"] > 70:
        alerts.append("High CPU usage")
    if ctx["mem_used"] > 70:
        alerts.append("High memory usage")
    if ctx["disk_used"] > 80:
        alerts.append("High disk usage")
    return alerts

    
def generate_diagnostics(ctx):
    """
    Generates possible causes for system issues.
    """
    notes = []

    if ctx["load"]["1min"] > ctx["cpu"]:
        notes.append("High load but lower CPU -> possible I/O wait or blocked processes")

    if ctx["cpu"] > 80:
        notes.append("CPU is high -> check top processes (ps/top)")

    if ctx["disk_used"] > 85:
        notes.append("Disk usage high -> check /var/log or large files (du)")

    if ctx["mem_used"] > 80:
        notes.append("Memory high -> possible memory leak or heavy process")

    if not notes:
        notes.append("No issues detected")

    return notes


def generate_recommendations(ctx, env):
    """
    Generates recommended actions to address system issues.
    """
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