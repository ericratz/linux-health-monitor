#system_metrics.py
"""
Metric collection built on /proc, /sys and core userland commands.

No third-party dependencies: every value here comes from a file the kernel
exports or from a command that ships with a base install. Where a source can
be absent (thermal sensors, an unreadable /proc entry, a missing binary) the
collector degrades instead of raising, so the same code runs on a minimized
Ubuntu host, a RHEL host, WSL2 and inside a container.

/proc is preferred over parsing top/free/mpstat because its layout is a stable
kernel interface, while those tools reformat their output between versions.
df/du/ps are used where they are the natural tool for the job.
"""
import glob
import os
import time

from agent.shell import run_command

#/proc/diskstats and the kernel's stat fields always report 512-byte sectors,
#regardless of the device's real hardware sector size.
SECTOR_SIZE = 512

CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")

#Thermal zone / hwmon names that indicate a CPU sensor, best first.
CPU_SENSOR_HINTS = ("x86_pkg_temp", "coretemp", "k10temp", "cpu", "acpitz")

#Virtual and non-physical block devices to exclude from disk IO totals.
VIRTUAL_DISK_PREFIXES = ("loop", "ram", "zram", "dm-", "md", "sr", "fd")

#Filesystem types whose usage is not an operational concern: RAM-backed,
#kernel-synthetic, or remote (a hung remote server would stall df). Read-only
#images are filtered separately, by mount option rather than by type.
EXCLUDED_FS_TYPES = frozenset({
    "tmpfs", "devtmpfs", "devfs", "ramfs", "rootfs", "overlay", "squashfs",
    "proc", "sysfs", "cgroup", "cgroup2", "debugfs", "tracefs", "efivarfs",
    "pstore", "securityfs", "configfs", "fusectl", "mqueue", "hugetlbfs",
    "autofs", "binfmt_misc", "bpf", "nsfs", "devpts",
    #remote and host-passthrough
    "nfs", "nfs4", "cifs", "smbfs", "9p", "drvfs", "fuse", "vboxsf",
})


def _read_file(path):
    """
    Reads a file, returning None if it is missing or unreadable.
    """
    try:
        with open(path) as f:
            return f.read()
    except (OSError, ValueError):
        return None


def _read_proc_stat_fields():
    """
    Returns the raw jiffy counters from the aggregate cpu line of /proc/stat:
    [user, nice, system, idle, iowait, irq, softirq, steal, ...]
    """
    content = _read_file("/proc/stat")
    if not content:
        return None
    for line in content.splitlines():
        if not line.startswith("cpu "):
            continue
        try:
            values = [int(v) for v in line.split()[1:]]
        except ValueError:
            return None
        return values if len(values) >= 5 else None
    return None


def _read_proc_stat_cpu():
    """
    Returns (busy_jiffies, total_jiffies) from the aggregate cpu line of
    /proc/stat, or None if unavailable.

    iowait is counted as idle rather than busy, matching how CPU utilization
    is conventionally reported: a blocked-on-disk core is not doing work.
    Because that hides I/O stalls from the CPU number, iowait is reported
    separately as pressure.
    """
    values = _read_proc_stat_fields()
    if not values:
        return None
    total = sum(values)
    idle = values[3] + values[4]
    return total - idle, total


def _read_vmstat():
    """
    Parses /proc/vmstat into a dict of counter name -> value.
    """
    content = _read_file("/proc/vmstat")
    if not content:
        return {}
    counters = {}
    for line in content.splitlines():
        name, _, value = line.partition(" ")
        try:
            counters[name] = int(value)
        except ValueError:
            continue
    return counters


def _runnable_count():
    """
    Returns the number of currently runnable entities from /proc/loadavg.

    Field 4 is "runnable/total"; the runnable half is an instantaneous count,
    where load average is a decayed one.
    """
    content = _read_file("/proc/loadavg")
    if not content:
        return None
    fields = content.split()
    if len(fields) < 4:
        return None
    runnable, _, _ = fields[3].partition("/")
    try:
        return int(runnable)
    except ValueError:
        return None


def _read_meminfo():
    """
    Parses /proc/meminfo into a dict of field name -> bytes.
    """
    content = _read_file("/proc/meminfo")
    if not content:
        return {}
    info = {}
    for line in content.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if not parts:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        #values are in kB unless the unit column says otherwise
        if len(parts) > 1 and parts[1].lower() == "kb":
            value *= 1024
        info[name] = value
    return info


def _is_physical_disk(name):
    """
    True for whole physical disks, excluding partitions and virtual devices.

    Partitions are identified by the kernel's own 'partition' attribute rather
    than by a trailing digit, so nvme0n1 (a disk) is not confused with
    nvme0n1p1 (a partition).
    """
    if name.startswith(VIRTUAL_DISK_PREFIXES):
        return False
    if not os.path.isdir(f"/sys/class/block/{name}"):
        return False
    return not os.path.exists(f"/sys/class/block/{name}/partition")


def _read_diskstats():
    """
    Returns (sectors_read, sectors_written) summed over physical disks,
    or None if /proc/diskstats is unavailable.
    """
    content = _read_file("/proc/diskstats")
    if not content:
        return None
    reads = writes = 0
    for line in content.splitlines():
        fields = line.split()
        #major minor name reads merged sectors_read ms writes merged sectors_written ...
        if len(fields) < 10:
            continue
        name = fields[2]
        if not _is_physical_disk(name):
            continue
        try:
            reads += int(fields[5])
            writes += int(fields[9])
        except ValueError:
            continue
    return reads, writes


def _proc_pid_stat(pid):
    """
    Reads /proc/<pid>/stat and returns (comm, fields) where fields[0] is the
    process state, or None if the process vanished mid-read.

    The comm field is wrapped in parentheses and may itself contain spaces or
    parentheses, so it is sliced out on the outermost pair before splitting
    the remainder. fields is 0-indexed from stat field 3, so documented field
    N lives at fields[N - 3].
    """
    content = _read_file(f"/proc/{pid}/stat")
    if not content:
        return None
    open_paren = content.find("(")
    close_paren = content.rfind(")")
    if open_paren == -1 or close_paren < open_paren:
        return None
    comm = content[open_paren + 1:close_paren]
    fields = content[close_paren + 1:].split()
    #a real stat line has 40+ fields; anything shorter than the CPU times we
    #read (field 15 -> index 12) is malformed
    if len(fields) < 13:
        return None
    return comm, fields


def _proc_pid_rss(pid):
    """
    Returns a process's resident set size in bytes, from /proc/<pid>/statm.

    statm is the authoritative source: the kernel documents the rss field in
    /proc/<pid>/stat as inaccurate and points here instead.
    """
    content = _read_file(f"/proc/{pid}/statm")
    if not content:
        return 0
    fields = content.split()
    if len(fields) < 2:
        return 0
    try:
        #size resident shared text lib data dt
        return int(fields[1]) * PAGE_SIZE
    except ValueError:
        return 0


def _pid_list():
    """
    Returns the currently visible PIDs.
    """
    try:
        return [int(name) for name in os.listdir("/proc") if name.isdigit()]
    except OSError:
        return []


def _sample_processes(include_memory=False):
    """
    Snapshots every readable process as pid -> (comm, cpu_jiffies, rss_bytes).

    Memory is only read when asked for: CPU needs two samples to form a delta,
    but memory is a level, so the opening sample can skip a file read per
    process.
    """
    sample = {}
    for pid in _pid_list():
        parsed = _proc_pid_stat(pid)
        if not parsed:
            continue
        comm, fields = parsed
        try:
            #utime (14) + stime (15)
            cpu_jiffies = int(fields[11]) + int(fields[12])
        except ValueError:
            continue
        rss_bytes = _proc_pid_rss(pid) if include_memory else 0
        sample[pid] = (comm, cpu_jiffies, rss_bytes)
    return sample


def get_cpu_snapshot(interval=0.3, limit=5):
    """
    Samples CPU, per-process CPU, disk IO and pressure, sleeps once, then
    returns (cpu_percent, top_processes, disk_io, pressure). The single sleep
    covers all four.

    Per-process CPU is a true delta over the interval, so it reflects current
    activity rather than the process's lifetime average that `ps %cpu` reports.
    """
    stat_start = _read_proc_stat_fields()
    disk_start = _read_diskstats()
    vmstat_start = _read_vmstat()
    proc_start = _sample_processes()

    time.sleep(interval)

    stat_end = _read_proc_stat_fields()
    disk_end = _read_diskstats()
    vmstat_end = _read_vmstat()
    proc_end = _sample_processes(include_memory=True)

    cpu = _cpu_percent(_busy_total(stat_start), _busy_total(stat_end))
    disk_io = _disk_io_rate(disk_start, disk_end, interval)
    top = _top_processes(proc_start, proc_end, interval, limit)
    pressure = _pressure(stat_start, stat_end, vmstat_start, vmstat_end, interval)
    return cpu, top, disk_io, pressure


def _busy_total(values):
    """
    Collapses raw /proc/stat counters into (busy, total).
    """
    if not values:
        return None
    total = sum(values)
    return total - (values[3] + values[4]), total


def _pressure(stat_start, stat_end, vmstat_start, vmstat_end, interval):
    """
    Returns the signals that explain a high load average with low CPU.

    iowait is the discriminator: load counts processes waiting on disk, but CPU
    percentage does not, so I/O-bound hosts look idle by CPU alone. Swap
    traffic and major faults distinguish memory pressure from plain slow disk.
    """
    pressure = {
        "iowait_percent": None,
        "runnable": _runnable_count(),
        "swap_in_bytes_per_sec": None,
        "swap_out_bytes_per_sec": None,
        "major_faults_per_sec": None,
    }

    if stat_start and stat_end:
        total_delta = sum(stat_end) - sum(stat_start)
        iowait_delta = stat_end[4] - stat_start[4]
        if total_delta > 0:
            share = max(0.0, min(100.0, iowait_delta / total_delta * 100))
            pressure["iowait_percent"] = round(share, 1)

    if vmstat_start and vmstat_end and interval > 0:
        def rate(name, scale=1):
            if name not in vmstat_start or name not in vmstat_end:
                return None
            delta = max(0, vmstat_end[name] - vmstat_start[name])
            return int(delta * scale / interval)

        pressure["swap_in_bytes_per_sec"] = rate("pswpin", PAGE_SIZE)
        pressure["swap_out_bytes_per_sec"] = rate("pswpout", PAGE_SIZE)
        pressure["major_faults_per_sec"] = rate("pgmajfault")

    return pressure


def _cpu_percent(start, end):
    """
    Converts two /proc/stat samples into a busy percentage.
    """
    if not start or not end:
        return 0.0
    busy_delta = end[0] - start[0]
    total_delta = end[1] - start[1]
    if total_delta <= 0:
        return 0.0
    return round(max(0.0, min(100.0, busy_delta / total_delta * 100)), 1)


def _disk_io_rate(start, end, interval):
    """
    Converts two /proc/diskstats samples into bytes/sec.
    """
    if not start or not end or interval <= 0:
        return None
    return {
        "read_bytes_per_sec": max(0, int((end[0] - start[0]) * SECTOR_SIZE / interval)),
        "write_bytes_per_sec": max(0, int((end[1] - start[1]) * SECTOR_SIZE / interval)),
    }


def _top_processes(start, end, interval, limit):
    """
    Ranks processes by CPU delta between two samples, then by memory.
    """
    mem_total = _read_meminfo().get("MemTotal", 0)
    procs = []
    for pid, (comm, cpu_end, rss) in end.items():
        previous = start.get(pid)
        #processes that appeared mid-interval have no baseline to subtract
        cpu_start = previous[1] if previous else cpu_end
        cpu_seconds = max(0, cpu_end - cpu_start) / CLK_TCK
        cpu_percent = cpu_seconds / interval * 100 if interval > 0 else 0.0
        mem_percent = rss / mem_total * 100 if mem_total else 0.0
        procs.append({
            "pid": pid,
            "name": comm,
            "cpu_percent": round(cpu_percent, 2),
            "memory_percent": round(mem_percent, 2),
        })
    procs.sort(key=lambda p: (p["cpu_percent"], p["memory_percent"]), reverse=True)
    return procs[:limit]


def get_process_summary():
    """
    Counts visible processes, zombies and blocked processes from
    /proc/<pid>/stat.

    'blocked' is state D, uninterruptible sleep: processes stuck in a kernel
    call, almost always waiting on I/O. This is what `ps aux | awk '$8=="D"'`
    hunts for when load is high but CPU is idle.
    """
    total = 0
    zombies = 0
    blocked = 0
    for pid in _pid_list():
        parsed = _proc_pid_stat(pid)
        if not parsed:
            continue
        total += 1
        state = parsed[1][0]
        if state == "Z":
            zombies += 1
        elif state == "D":
            blocked += 1
    return {"total": total, "zombies": zombies, "blocked": blocked}


def _sensor_rank(label):
    """
    Sorts sensor labels so CPU sensors are preferred over ambient ones.
    """
    for rank, hint in enumerate(CPU_SENSOR_HINTS):
        if hint in label.lower():
            return rank
    return len(CPU_SENSOR_HINTS)


def _thermal_zone_readings():
    """
    Reads /sys/class/thermal/thermal_zone*/temp as (label, celsius) pairs.
    """
    readings = []
    for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        raw = _read_file(os.path.join(zone, "temp"))
        if raw is None:
            continue
        try:
            celsius = int(raw.strip()) / 1000
        except ValueError:
            continue
        label = (_read_file(os.path.join(zone, "type")) or os.path.basename(zone)).strip()
        readings.append((label, celsius))
    return readings


def _hwmon_readings():
    """
    Reads /sys/class/hwmon/hwmon*/temp*_input as (label, celsius) pairs.

    This is where coretemp/k10temp surface on physical hardware when the
    thermal_zone interface does not expose the package temperature.
    """
    readings = []
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = (_read_file(os.path.join(hwmon, "name")) or os.path.basename(hwmon)).strip()
        for temp_input in sorted(glob.glob(os.path.join(hwmon, "temp*_input"))):
            raw = _read_file(temp_input)
            if raw is None:
                continue
            try:
                celsius = int(raw.strip()) / 1000
            except ValueError:
                continue
            readings.append((name, celsius))
    return readings


def get_cpu_temperature():
    """
    Returns the CPU temperature from /sys, preferring a CPU-specific sensor.

    lm-sensors is deliberately not used: it is absent on minimized installs,
    while /sys is always present when the hardware exposes a sensor at all.
    """
    readings = _thermal_zone_readings() or _hwmon_readings()
    if not readings:
        return {"success": False, "reason": "no sensors available"}

    best = min(readings, key=lambda item: _sensor_rank(item[0]))
    source = best[0]
    #average every reading from the winning sensor (e.g. per-core coretemp)
    matched = [celsius for label, celsius in readings if label == source]
    return {
        "success": True,
        "celsius": round(sum(matched) / len(matched), 1),
        "source": source,
    }


def get_load_average():
    """
    Returns the system load average over 1, 5, and 15 minutes.
    """
    content = _read_file("/proc/loadavg")
    if content:
        parts = content.split()
        if len(parts) >= 3:
            try:
                load1, load5, load15 = (float(p) for p in parts[:3])
                return {
                    "1min": round(load1, 2),
                    "5min": round(load5, 2),
                    "15min": round(load15, 2),
                }
            except ValueError:
                pass
    load1, load5, load15 = os.getloadavg()
    return {
        "1min": round(load1, 2),
        "5min": round(load5, 2),
        "15min": round(load15, 2)
    }


def get_memory_usage():
    """
    Returns the current system memory and swap usage from /proc/meminfo.

    'Used' is derived from MemAvailable, the kernel's own estimate of what a
    new workload could claim, so cache and reclaimable slab are not counted
    against the host the way a naive total-minus-free would.
    """
    info = _read_meminfo()
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable")
    if available is None:
        #pre-3.14 kernels: approximate the same idea from what is there
        available = info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0)
    used_percent = (total - available) / total * 100 if total else 0.0

    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used_percent = (swap_total - swap_free) / swap_total * 100 if swap_total else 0.0

    return {
        "used_percent": round(used_percent, 2),
        "available": available,
        "swap_used_percent": round(swap_used_percent, 2)
    }


def get_disk_usage(path="/"):
    """
    Returns the current disk usage for the root partition via df.

    -P forces the portable one-line-per-filesystem layout (a long device name
    otherwise wraps onto its own line) and -B1 reports plain bytes.
    Percentage is used/(used+available), which excludes root-reserved blocks
    an unprivileged writer cannot claim - the same basis df's Capacity uses.
    """
    result = run_command(["df", "-P", "-B1", path])
    lines = result["stdout"].splitlines()
    if len(lines) < 2:
        return {"root_used_percent": 0.0, "root_free": 0}

    #Filesystem 1-blocks Used Available Capacity Mounted-on
    fields = lines[1].split()
    if len(fields) < 5:
        return {"root_used_percent": 0.0, "root_free": 0}
    try:
        used = int(fields[2])
        available = int(fields[3])
    except ValueError:
        return {"root_used_percent": 0.0, "root_free": 0}

    usable = used + available
    return {
        "root_used_percent": round(used / usable * 100, 2) if usable else 0.0,
        "root_free": available
    }


def _read_mounts():
    """
    Returns mountpoint -> (fstype, options set) from /proc/mounts.
    """
    content = _read_file("/proc/mounts")
    if not content:
        return {}
    mounts = {}
    for line in content.splitlines():
        #device mountpoint fstype options dump pass
        fields = line.split()
        if len(fields) < 4:
            continue
        #the kernel octal-escapes spaces in mountpoints
        mountpoint = fields[1].replace("\\040", " ")
        mounts[mountpoint] = (fields[2], set(fields[3].split(",")))
    return mounts


def _is_reportable_filesystem(mountpoint, mounts):
    """
    True if a filesystem's usage is an operational concern.

    Read-only is the key test, not the filesystem type: a squashfs snap image
    sits at 100% forever by design, while a genuinely full /var is read-write
    and must still be reported. Type is only used to drop kernel-synthetic and
    remote filesystems, the latter because a hung server would stall df.
    """
    info = mounts.get(mountpoint)
    if info is None:
        #not in /proc/mounts: keep it rather than silently hiding a real mount
        return True
    fstype, options = info
    if "ro" in options:
        return False
    #fuse.snapfuse, fuse.sshfs etc. carry the transport after the dot
    return fstype.split(".")[0] not in EXCLUDED_FS_TYPES


def get_filesystems():
    """
    Returns usage for every real filesystem, worst first.

    Monitoring only / hides the classic outage where /var or /boot fills while
    the root filesystem still looks fine.
    """
    #-P portable columns (a long device name otherwise wraps), -B1 for bytes
    result = run_command(["df", "-P", "-B1"], timeout=10)
    mounts = _read_mounts()

    filesystems = []
    seen = set()
    for line in result["stdout"].splitlines()[1:]:
        #Filesystem 1-blocks Used Available Capacity Mounted-on
        fields = line.split()
        if len(fields) < 6:
            continue
        mountpoint = " ".join(fields[5:])
        if not _is_reportable_filesystem(mountpoint, mounts):
            continue
        try:
            used = int(fields[2])
            available = int(fields[3])
        except ValueError:
            continue
        usable = used + available
        #a zero-capacity mount carries no signal
        if usable <= 0:
            continue
        #bind mounts report the same device twice
        key = (fields[0], mountpoint)
        if key in seen:
            continue
        seen.add(key)
        filesystems.append({
            "mount": mountpoint,
            "device": fields[0],
            "used_percent": round(used / usable * 100, 2),
            "free": available,
        })

    filesystems.sort(key=lambda fs: fs["used_percent"], reverse=True)
    return filesystems


def _entry_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def get_directory_usage(path="/var/log"):
    """
    Returns the top 5 entries in a directory by total size, largest first.

    du does the walking (it handles hardlinks and sparse files correctly and
    stays fast on a spinning disk); unreadable subtrees make du exit non-zero
    but it still reports what it could measure, so partial output is kept.
    Falls back to walking in Python if du is unavailable.
    """
    entries = sorted(glob.glob(os.path.join(path, "*")))
    if not entries:
        return []

    #a slow disk with a large /var/log needs more headroom than the default
    result = run_command(["du", "-B1", "-s", "--"] + entries, timeout=30)
    usage = []
    for line in result["stdout"].splitlines():
        size, _, entry_path = line.partition("\t")
        if not entry_path:
            continue
        try:
            usage.append({"name": os.path.basename(entry_path.strip()), "size_bytes": int(size)})
        except ValueError:
            continue

    if not usage:
        for entry_path in entries:
            try:
                usage.append({
                    "name": os.path.basename(entry_path),
                    "size_bytes": _entry_size(entry_path),
                })
            except (PermissionError, FileNotFoundError, OSError):
                continue

    return sorted(usage, key=lambda x: x["size_bytes"], reverse=True)[:5]


def get_network_io():
    """
    Returns total network I/O statistics from /proc/net/dev, summed over every
    interface (loopback included, so intra-host traffic is still visible).
    """
    content = _read_file("/proc/net/dev")
    if not content:
        return {"bytes_sent": 0, "bytes_received": 0}

    sent = received = 0
    #two header lines, then "iface: rx_bytes ... tx_bytes ..."
    for line in content.splitlines()[2:]:
        _, sep, stats = line.partition(":")
        if not sep:
            continue
        fields = stats.split()
        if len(fields) < 10:
            continue
        try:
            received += int(fields[0])
            sent += int(fields[8])
        except ValueError:
            continue
    return {
        "bytes_sent": sent,
        "bytes_received": received
    }


def get_system_uptime():
    """
    Returns the system uptime in seconds since last boot.
    """
    content = _read_file("/proc/uptime")
    if content:
        try:
            return int(float(content.split()[0]))
        except (ValueError, IndexError):
            pass
    return 0
