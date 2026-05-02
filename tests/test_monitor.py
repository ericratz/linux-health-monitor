from agent.monitor import HealthMonitor
from agent.html_report import generate_html


def test_report_structure():
    monitor = HealthMonitor()
    data = monitor.report()

    #keys present
    required_keys = [
        "timestamp",
        "system",
        "core_metrics",
        "top_processes",
        "health",
    ]

    for key in required_keys:
        assert key in data

    #core metrics present
    cm = data["core_metrics"]
    assert "cpu" in cm
    assert "memory" in cm
    assert "disk" in cm
    assert "load" in cm
    assert "network" in cm


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
    assert isinstance(cm["network"], dict)


def test_html_generation(tmp_path):
    monitor = HealthMonitor()
    data = monitor.report()

    html = generate_html(data)

    file = tmp_path / "report.html"
    file.write_text(html)

    assert file.exists()
    assert "<html>" in html.lower()