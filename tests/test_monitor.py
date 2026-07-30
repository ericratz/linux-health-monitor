import os

from agent.monitor import HealthMonitor, write_output
from agent.html_report import generate_html, humanize_view


VIEW = {
    "timestamp": "2026-07-30T00:00:00+00:00",
    "system": {"hostname": "node1"},
    "core_metrics": {"cpu": 1.0},
    "health": {"status": "HEALTHY", "diagnosis": []},
}


def test_report_is_not_world_readable_by_default(tmp_path, monkeypatch):
    #the report is a host inventory - ports with process names, containers,
    #addressing, MACs. A network allow-list does not stop a local account
    #reading the file, and 0644 is what a default umask would have produced.
    monkeypatch.delenv("HEALTH_REPORT_MODE", raising=False)
    target = tmp_path / "web" / "report.html"
    write_output(VIEW, str(target))
    assert oct(os.stat(target).st_mode)[-3:] == "640"


def test_report_mode_is_configurable(tmp_path, monkeypatch):
    #group-readable is what a web server needs; the deployer chooses
    monkeypatch.setenv("HEALTH_REPORT_MODE", "644")
    target = tmp_path / "report.html"
    write_output(VIEW, str(target))
    assert oct(os.stat(target).st_mode)[-3:] == "644"


def test_unparseable_report_mode_falls_back(tmp_path, monkeypatch):
    #a typo must not silently widen the mode
    monkeypatch.setenv("HEALTH_REPORT_MODE", "not-a-mode")
    target = tmp_path / "report.html"
    write_output(VIEW, str(target))
    assert oct(os.stat(target).st_mode)[-3:] == "640"


def test_absolute_html_path_creates_its_parent(tmp_path):
    #so the report can be written straight into a web root
    target = tmp_path / "var" / "www" / "health" / "report.html"
    write_output(VIEW, str(target))
    assert target.exists()


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


def test_humanize_view_formats_bytes():
    monitor = HealthMonitor()
    data = monitor.report()
    view = {
        "core_metrics": data["core_metrics"],
        "features": data.get("features", {}),
    }
    humanized = humanize_view(view)
    net = humanized["core_metrics"]["network"]
    assert isinstance(net["bytes_sent"], str)
    assert isinstance(net["bytes_received"], str)
    mem = humanized["core_metrics"]["memory"]
    assert isinstance(mem["available"], str)


def test_html_has_percent_signs():
    monitor = HealthMonitor()
    data = monitor.report()
    html = generate_html(data)
    assert "%" in html


def test_cpu_snapshot_returns_cpu_and_processes():
    from agent.system_metrics import get_cpu_snapshot
    cpu, procs, disk_io, pressure = get_cpu_snapshot(interval=0.1)
    assert isinstance(pressure, dict)
    assert isinstance(cpu, (int, float))
    assert isinstance(procs, list)
    if procs:
        assert "pid" in procs[0]
        assert "cpu_percent" in procs[0]
        assert "memory_percent" in procs[0]
    if disk_io is not None:
        assert "read_bytes_per_sec" in disk_io
        assert "write_bytes_per_sec" in disk_io


def test_process_summary():
    from agent.system_metrics import get_process_summary
    result = get_process_summary()
    assert "total" in result
    assert "zombies" in result
    assert result["total"] > 0
    assert result["zombies"] >= 0


def test_cpu_temperature_structure():
    from agent.system_metrics import get_cpu_temperature
    result = get_cpu_temperature()
    assert "success" in result
    if result["success"]:
        assert "celsius" in result
        assert "source" in result
    else:
        assert "reason" in result


def test_threshold_env_vars(monkeypatch):
    monkeypatch.setenv("HEALTH_CPU_CRIT", "50")
    monitor = HealthMonitor()
    fake_metrics = {
        "cpu": 60,
        "memory": {"used_percent": 10},
        "disk": {"root_used_percent": 10},
        "load": {"1min": 0.1},
    }
    result = monitor.run_health_analysis(fake_metrics)
    assert result["status"] == "CRITICAL"


def test_directory_usage_returns_sizes():
    from agent.system_metrics import get_directory_usage
    import os
    result = get_directory_usage(os.path.dirname(os.path.abspath(__file__)))
    assert isinstance(result, list)
    for entry in result:
        assert "name" in entry
        assert "size_bytes" in entry
        assert entry["size_bytes"] >= 0