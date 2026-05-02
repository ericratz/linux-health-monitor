#snapshot.py
import platform
from agent.environment import detect_environment

#system info
def get_system_identity():
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

def build_snapshot(cpu, memory, disk, load):
    return {
        "cpu": cpu,
        "mem_used": memory["used_percent"],
        "disk_used": disk["root_used_percent"],
        "load": load
    }