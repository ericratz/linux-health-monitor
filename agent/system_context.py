#system_context.py
from agent.system_metrics import get_directory_usage
import os
import subprocess
import platform
import psutil

def run_command(command):
    """
    Runs a shell command and returns the result.
    """
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

def detect_environment():
    """
    Detects the execution environment.
    """
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

def get_system_identity(env):
    """
    Collects system identity information.
    """
    return {
        "os": platform.system(),
        "distro": (
            platform.freedesktop_os_release().get("PRETTY_NAME", "Unknown")
            if hasattr(platform, "freedesktop_os_release")
            else "Unknown"
        ),
        "kernel": platform.release(),
        "hostname": platform.node(),
        "cpu_cores": psutil.cpu_count(logical=True),
        "environment": env
    }

def is_docker():
    """
    Checks if the code is running inside a container (Docker, Podman, LXC, Kubernetes).
    """
    if os.path.exists("/.dockerenv"):
        return True
    try:
        content = open("/proc/1/cgroup").read()
        if any(x in content for x in ("docker", "kubepods", "containerd", "lxc")):
            return True
    except Exception:
        pass
    return os.getenv("container", "").lower() in {"docker", "containerd", "podman"}


def get_service_statuses(env):
    """
    Returns key system service statuses based on the environment.
    """
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
            get_service_status("nginx"),
            get_service_status("docker")
        ]
    }


def get_service_status(name):
    """
    Check the status of a specific service.
    """
    result = run_command(["systemctl", "is-active", name])
    if not result["success"]:
        return {
            "service": name,
            "status": "unknown",
            "error": result["stderr"]
        }
    return {
        "service": name,
        "status": result["stdout"].strip()
    }

def get_docker_containers():
    """
    Returns a list of running Docker containers.
    """
    result = run_command(["docker", "ps", "--format", "{{.Names}}"])
    if not result["success"]:
        return {
            "feature": "docker",
            "success": False,
            "reason": "docker CLI not available in environment",
            "data": None
        }
    containers = [c for c in result["stdout"].splitlines() if c]
    return {
        "feature": "docker",
        "success": True,
        "running_containers": containers,
        "count": len(containers)
    }

def get_failed_services(env):
    if env in ["Docker", "CI", "WSL2", "GitHub Actions"]:
        return {"success": False, "reason": f"systemctl not available in {env}"}
    result = run_command(["systemctl", "--failed", "--no-legend", "--plain"])
    if not result["success"]:
        return {"success": False, "reason": result["stderr"] or "systemctl unavailable"}
    failed = [line.split()[0] for line in result["stdout"].splitlines() if line.strip()]
    return {"success": True, "count": len(failed), "services": failed}


def get_disk_details():
    """
    Returns details about the disk usage, including the largest files in a specified directory.
    """
    try:
        return {
            "feature": "disk_details",
            "success": True,
            "data": get_directory_usage()
        }
    except PermissionError:
        return {
            "feature": "disk_details",
            "success": False,
            "error": "permission denied",
            "data": None
        }