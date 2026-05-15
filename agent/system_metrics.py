#system_metrics.py
import os
import psutil
import time

def get_cpu_snapshot(interval=0.3, limit=5):
    """
    Primes CPU counters and disk IO, sleeps once, then returns
    (cpu_percent, top_processes, disk_io). Single sleep covers all three.
    """
    psutil.cpu_percent(interval=None)
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except Exception:
            continue
    disk_start = psutil.disk_io_counters()
    time.sleep(interval)
    cpu = psutil.cpu_percent(interval=None)
    disk_end = psutil.disk_io_counters()
    if disk_start and disk_end:
        disk_io = {
            "read_bytes_per_sec": int((disk_end.read_bytes - disk_start.read_bytes) / interval),
            "write_bytes_per_sec": int((disk_end.write_bytes - disk_start.write_bytes) / interval),
        }
    else:
        disk_io = None
    procs = []
    for p in psutil.process_iter(['pid', 'name']):
        try:
            procs.append({
                "pid": p.pid,
                "name": p.name(),
                "cpu_percent": round(p.cpu_percent(None), 2),
                "memory_percent": round(p.memory_percent(), 2),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    top = sorted(procs, key=lambda x: (x['cpu_percent'], x['memory_percent']), reverse=True)[:limit]
    return cpu, top, disk_io


def get_process_summary():
    total = 0
    zombies = 0
    for p in psutil.process_iter(['status']):
        try:
            total += 1
            if p.info['status'] == psutil.STATUS_ZOMBIE:
                zombies += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {"total": total, "zombies": zombies}


def get_cpu_temperature():
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return {"success": False, "reason": "no sensors available"}
        for source in ("coretemp", "k10temp", "acpitz"):
            if source in temps:
                readings = temps[source]
                avg = round(sum(t.current for t in readings) / len(readings), 1)
                return {"success": True, "celsius": avg, "source": source}
        source, readings = next(iter(temps.items()))
        avg = round(sum(t.current for t in readings) / len(readings), 1)
        return {"success": True, "celsius": avg, "source": source}
    except AttributeError:
        return {"success": False, "reason": "not supported on this platform"}
    except Exception as e:
        return {"success": False, "reason": str(e)}


def get_load_average():
    """
    Returns the system load average over 1, 5, and 15 minutes.
    """
    load1, load5, load15 = os.getloadavg()
    return {
        "1min": round(load1, 2),
        "5min": round(load5, 2),
        "15min": round(load15, 2)
    }

def get_memory_usage():
    """
    Returns the current system memory and swap usage.
    """
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "used_percent": round(memory.percent, 2),
        "available": memory.available,
        "swap_used_percent": round(swap.percent, 2)
    }


def get_disk_usage():
    """
    Returns the current disk usage for the root partition.
    """
    disk = psutil.disk_usage("/")
    return {
        "root_used_percent": round(disk.percent, 2),
        "root_free": disk.free
    }

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
    Scans a directory and returns the top 5 entries by total size (recursive for subdirs).
    """
    usage = []
    for entry in os.scandir(path):
        try:
            usage.append({"name": entry.name, "size_bytes": _entry_size(entry.path)})
        except (PermissionError, FileNotFoundError):
            continue
    return sorted(usage, key=lambda x: x["size_bytes"], reverse=True)[:5]

def get_network_io():
    """
    Returns total network I/O statistics.
    """
    net = psutil.net_io_counters()
    return {
        "bytes_sent": net.bytes_sent,
        "bytes_received": net.bytes_recv
    }

def get_system_uptime():
    """
    Returns the system uptime in seconds since last boot.
    """
    return int(time.time() - psutil.boot_time())


