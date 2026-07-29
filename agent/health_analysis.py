#health_analysis.py
"""
Threshold evaluation, diagnosis and recommended actions.

Recommendations are strings a human reads and chooses to run. Nothing here
executes anything, and nothing that changes system state belongs in this
process: the monitor's job is to say what it sees and name the command that
would investigate or fix it.
"""
import os

#Above this, iowait is high enough that the CPU number alone is misleading.
IOWAIT_WARN = 10.0


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


def _filesystems(ctx):
    """
    Returns the reported filesystems, newest callers only.
    """
    return ctx.get("filesystems") or []


def _worst_disk(ctx):
    """
    Returns the highest usage across root and every other filesystem.

    Root alone is not enough: a full /var takes the host down while / still
    looks healthy.
    """
    worst = ctx.get("disk_used", 0)
    for filesystem in _filesystems(ctx):
        used = filesystem.get("used_percent")
        if isinstance(used, (int, float)):
            worst = max(worst, used)
    return worst


def _pressure(ctx):
    return ctx.get("pressure") or {}


def generate_health_status(ctx):
    """
    Returns HEALTHY, WARNING or CRITICAL.

    Resource thresholds decide CRITICAL. A failed unit or an unsynchronized
    clock is at least a WARNING regardless of resource use: a host with a dead
    service is not healthy just because its CPU is idle.
    """
    t = _thresholds()
    cpu, mem = ctx["cpu"], ctx["mem_used"]
    disk = _worst_disk(ctx)
    if cpu > t["cpu_crit"] or mem > t["mem_crit"] or disk > t["disk_crit"]:
        return "CRITICAL"
    if cpu > t["cpu_warn"] or mem > t["mem_warn"] or disk > t["disk_warn"]:
        return "WARNING"
    if ctx.get("failed_services") or ctx.get("time_desynchronized"):
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

    #name the mount, since "disk is full" is not actionable on its own
    for filesystem in _filesystems(ctx):
        used = filesystem.get("used_percent")
        mount = filesystem.get("mount")
        if not isinstance(used, (int, float)) or mount == "/":
            continue
        if used > t["disk_warn"]:
            alerts.append(f"High disk usage on {mount} ({used}%)")

    pressure = _pressure(ctx)
    iowait = pressure.get("iowait_percent")
    if isinstance(iowait, (int, float)) and iowait > IOWAIT_WARN:
        alerts.append(f"High I/O wait ({iowait}%)")
    if pressure.get("swap_out_bytes_per_sec"):
        alerts.append("Swapping out to disk")

    #host posture: these are problems even when every resource looks fine
    failed = ctx.get("failed_services")
    if failed:
        alerts.append(f"{failed} failed systemd unit(s)")
    if ctx.get("time_desynchronized"):
        alerts.append("Clock not synchronized")
    journal_errors = ctx.get("journal_errors") or {}
    if journal_errors.get("count"):
        window = journal_errors.get("window", "recently")
        alerts.append(f"{journal_errors['count']} journal error(s) since {window}")
    if ctx.get("reboot_required"):
        alerts.append("Reboot required")
    return alerts


def generate_diagnostics(ctx):
    t = _thresholds()
    pressure = _pressure(ctx)
    iowait = pressure.get("iowait_percent")
    blocked = (ctx.get("processes") or {}).get("blocked")
    notes = []

    #iowait is what distinguishes a genuinely busy host from a stalled one:
    #load counts processes waiting on disk, but CPU percentage does not
    if isinstance(iowait, (int, float)) and iowait > IOWAIT_WARN:
        note = f"I/O wait is {iowait}% -> the host is disk-bound, not CPU-bound"
        if blocked:
            note += f"; {blocked} process(es) blocked in uninterruptible sleep"
        notes.append(note)
    elif ctx["load"]["1min"] > 0.5 and ctx["load"]["1min"] > ctx["cpu"]:
        notes.append("High load but lower CPU -> possible I/O wait or blocked processes")

    if pressure.get("swap_out_bytes_per_sec"):
        notes.append(
            "Swapping out -> memory pressure; the slowdown is RAM, not disk size"
        )

    if ctx["cpu"] > t["cpu_warn"]:
        notes.append("CPU is high -> check top processes (ps/top)")

    for filesystem in _filesystems(ctx):
        used = filesystem.get("used_percent")
        if isinstance(used, (int, float)) and used > t["disk_warn"]:
            notes.append(
                f"{filesystem.get('mount')} is {used}% full -> find the largest "
                "directories on that filesystem"
            )
    if not any("full" in note for note in notes) and ctx["disk_used"] > t["disk_warn"]:
        notes.append("Disk usage high -> check /var/log or large files (du)")

    if ctx["mem_used"] > t["mem_warn"]:
        notes.append("Memory high -> possible memory leak or heavy process")

    #posture problems must reach the diagnosis, or a host with a dead service
    #reads as "No issues detected" while the actions list says otherwise
    failed = ctx.get("failed_services")
    if failed:
        notes.append(
            f"{failed} systemd unit(s) failed -> identify them before looking further"
        )
    journal_errors = ctx.get("journal_errors") or {}
    if journal_errors.get("count"):
        units = ", ".join(
            entry["unit"] for entry in (journal_errors.get("by_unit") or [])[:3]
        )
        note = f"{journal_errors['count']} error(s) in the journal"
        if units:
            note += f" -> mostly from {units}"
        notes.append(note)
    if ctx.get("time_desynchronized"):
        notes.append(
            "Clock is not synchronized -> certificate checks and cross-node log "
            "correlation are unreliable until it is"
        )
    if ctx.get("reboot_required"):
        notes.append("A reboot is pending -> running kernel/libraries are outdated")

    if not notes:
        notes.append("No issues detected")
    return notes


def generate_recommendations(ctx, env, os_family="unknown"):
    """
    Returns commands a human can choose to run, correct for this distro family.

    Read-only investigation first; anything that changes state is named but left
    for a person to decide on.
    """
    t = _thresholds()
    pressure = _pressure(ctx)
    actions = []

    if ctx["cpu"] > t["cpu_warn"]:
        actions.append("Run: ps aux --sort=-%cpu | head")
    if ctx["mem_used"] > t["mem_warn"]:
        actions.append("Run: ps aux --sort=-%mem | head")

    #-x keeps du on one filesystem, so it does not wander into other mounts
    for filesystem in _filesystems(ctx):
        used = filesystem.get("used_percent")
        mount = filesystem.get("mount")
        if isinstance(used, (int, float)) and used > t["disk_warn"]:
            actions.append(
                f"Run: du -xh --max-depth=1 {mount} | sort -h | tail -20"
            )
    if not actions and ctx["disk_used"] > t["disk_warn"]:
        actions.append("Run: du -xh --max-depth=1 / | sort -h | tail -20")

    iowait = pressure.get("iowait_percent")
    if isinstance(iowait, (int, float)) and iowait > IOWAIT_WARN:
        #dependency-free: sysstat (iostat) is absent on a minimized install
        actions.append("Run: ps -eo state,pid,comm | awk '$1 ~ /^D/'")
        actions.append("Run: cat /proc/diskstats  (or iostat -xz 1 5 if sysstat installed)")

    if (ctx.get("failed_services") or 0) > 0:
        actions.append("Run: systemctl --failed")

    journal_errors = ctx.get("journal_errors") or {}
    if journal_errors.get("count"):
        window = journal_errors.get("window", "-1h")
        actions.append(f"Run: journalctl -p err --since {window}")
        for entry in journal_errors.get("by_unit") or []:
            unit = entry.get("unit")
            if unit and unit != "kernel":
                actions.append(f"Run: journalctl -u {unit} -p err --since {window}")

    if ctx.get("time_desynchronized"):
        actions.append("Run: timedatectl status  (clock skew breaks certs and log correlation)")

    if ctx.get("reboot_required"):
        if os_family == "debian":
            actions.append("Reboot pending: cat /var/run/reboot-required.pkgs")
        else:
            actions.append("Reboot pending: dnf needs-restarting -r")

    #the journal is the same on both families; the log file path is not.
    #skip the generic hint when a specific unit was already named above.
    already_specific = any("journalctl -u " in action for action in actions)
    if actions and not already_specific and env not in ("Docker", "CI", "GitHub Actions"):
        actions.append("Check logs: journalctl -u <service> -b --no-pager")
    return actions
