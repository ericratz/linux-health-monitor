from agent.monitor import HealthMonitor
from agent.html_report import generate_html


def test_report_structure():
    monitor = HealthMonitor()
    data = monitor.report()
    required_keys = {
        "timestamp",
        "system",
        "core_metrics",
        "top_processes",
        "health",
    }
    assert required_keys.issubset(data.keys())
    cm = data["core_metrics"]
    assert {"cpu", "memory", "disk", "load", "network"}.issubset(cm.keys())


def test_core_metrics_types():
    monitor = HealthMonitor()
    data = monitor.report()
    cm = data["core_metrics"]
    assert isinstance(cm["cpu"], (int, float))
    assert isinstance(cm["memory"], dict)
    assert isinstance(cm["disk"], dict)
    assert isinstance(cm["load"], dict)
    assert isinstance(cm["network"], dict)
    assert isinstance(cm["memory"]["available"], (int, float))
    assert isinstance(cm["disk"]["root_free"], (int, float))
    assert isinstance(cm["network"]["bytes_sent"], (int, float))
    assert isinstance(cm["network"]["bytes_received"], (int, float))


def test_health_status_enum():
    monitor = HealthMonitor()
    data = monitor.report()
    assert data["health"]["status"] in {"HEALTHY", "WARNING", "CRITICAL"}


def test_health_status_logic_critical():
    monitor = HealthMonitor()
    fake_metrics = {
        "cpu": 95,
        "memory": {"used_percent": 50},
        "disk": {"root_used_percent": 50},
        "load": {"1min": 0.5},
    }
    result = monitor.run_health_analysis(fake_metrics)
    assert result["status"] == "CRITICAL"


def test_health_status_logic_warning():
    monitor = HealthMonitor()
    fake_metrics = {
        "cpu": 75,
        "memory": {"used_percent": 50},
        "disk": {"root_used_percent": 50},
        "load": {"1min": 0.5},
    }
    result = monitor.run_health_analysis(fake_metrics)
    assert result["status"] == "WARNING"


def test_health_status_logic_healthy():
    monitor = HealthMonitor()
    fake_metrics = {
        "cpu": 10,
        "memory": {"used_percent": 10},
        "disk": {"root_used_percent": 10},
        "load": {"1min": 0.1},
    }
    result = monitor.run_health_analysis(fake_metrics)
    assert result["status"] == "HEALTHY"


def test_html_generation_basic_structure(tmp_path):
    monitor = HealthMonitor()
    data = monitor.report()
    html = generate_html(data)
    file = tmp_path / "report.html"
    file.write_text(html)
    assert file.exists()
    html_lower = html.lower()
    assert "<html" in html_lower
    assert "linux health monitor" in html_lower
    assert "system" in html_lower
    assert "core metrics" in html_lower
    assert "health" in html_lower


def test_full_pipeline_runs():
    monitor = HealthMonitor()
    data = monitor.report()
    html = generate_html(data)
    assert isinstance(data, dict)
    assert isinstance(html, str)
    assert len(html) > 0