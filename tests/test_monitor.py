#test_monitor.py
from agent.monitor import HealthMonitor


def test_report_structure():
    monitor = HealthMonitor()
    data = monitor.report()

    required_keys = [
        "timestamp",
        "system",
        "uptime_seconds",
        "core_metrics",
        "top_processes",
        "health",
        "features",
    ]

    for key in required_keys:
        assert key in data

    cm = data["core_metrics"]
    assert "cpu" in cm
    assert "memory" in cm
    assert "disk" in cm
    assert "load" in cm

    health = data["health"]
    assert "status" in health
    assert "alerts" in health
    assert "diagnosis" in health
    assert "actions" in health


def test_status_values():
    monitor = HealthMonitor()
    data = monitor.report()
    assert data["health"]["status"] in {"HEALTHY", "WARNING", "CRITICAL"}


def test_core_metrics_types():
    monitor = HealthMonitor()
    data = monitor.report()
    cm = data["core_metrics"]

    assert isinstance(cm["cpu"], (int, float))
    assert isinstance(cm["memory"], dict)
    assert isinstance(cm["disk"], dict)
    assert isinstance(cm["load"], dict)