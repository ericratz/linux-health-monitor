Linux Health Monitor
A Docker/Python script that collects Linux server metrics and outputs a JSON health report.
Demonstrates SRE/DevOps concepts like automation, containerization, and CI/CD.

Features:
-Resource usage monitoring
-System info gathering
-User info gathering
-Health check with alerts and exit codes
-JSON output for automation
-Docker provided protability

Output:
{
  "timestamp": "2026-04-27T22:56:45+00:00",
  "system": {
    "os": "Linux",
    "distro": "Debian GNU/Linux 13 (trixie)",
    "kernel": "6.6.87.2-microsoft-standard-WSL2",
    "hostname": "a6841634dd74",
    "environment": "Docker"
  },
  "uptime_seconds": 4493,
  "cpu_usage_percent": 23.3,
  "memory": {
    "used_percent": 42.6,
    "available_mb": 3368.2,
    "swap_used_percent": 0.0
  },
  "disk": {
    "root_used_percent": 0.2,
    "root_free_gb": 953.8
  },
  "network": {
    "bytes_sent": "42.0 B",
    "bytes_received": "452.0 B"
  },
  "status": "HEALTHY",
  "alerts": []
}

Requirements:
-Python 3.12+
-Docker

Docker build image:
docker build -t linux-health-monitor .
docker run linux-health-monitor