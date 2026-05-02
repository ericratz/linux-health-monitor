#environment.py
import os
import platform

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
    #docker env check
    if os.path.exists("/.dockerenv"):
        return True

    #cgroup check
    try:
        with open("/proc/1/cgroup", "rt") as f:
            for line in f:
                if any(x in line for x in ["docker/", "kubepods/", "containerd/"]):
                    return True
    except Exception:
        pass

    #env var check
    if os.getenv("container", "").lower() in ["docker", "containerd"]:
        return True

    return False

def get_environment_summary(env):
    return {
        "environment": env,
        "is_containerized": env == "Docker",
        "limitations": (
            [
                "systemd unavailable",
                "restricted process visibility",
                "no docker CLI access"
            ] if env == "Docker" else []
        )
    }