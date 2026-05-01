from monitor import report


def test_report_structure():
    data = report()

    required_keys = [
        "timestamp",
        "system",
        "core_metrics",
        "top_processes",
        "status",
        "alerts",
        "diagnosis",
        "recommended_actions",
        "services",
        "docker",
        "disk_details",
        "network",
    ]

    for key in required_keys:
        assert key in data

    cm = data["core_metrics"]
    assert "cpu" in cm
    assert "memory" in cm
    assert "disk" in cm
    assert "load" in cm


def test_status_values():
    data = report()
    assert data["status"] in {"HEALTHY", "WARNING", "CRITICAL"}


def test_core_metrics_types():
    data = report()
    cm = data["core_metrics"]

    assert isinstance(cm["cpu"], (int, float))
    assert isinstance(cm["memory"], dict)
    assert isinstance(cm["disk"], dict)