from datetime import datetime, timezone
import json


def safe_get(data, *keys, default=None):
    """Safely traverse nested dictionaries."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return default
    return data if data is not None else default


def generate_html(data):
    system = data.get("system", {})
    core = data.get("core_metrics", {})
    uptime = data.get("uptime_seconds")
    top_processes = data.get("top_processes")
    features = data.get("features")

    status = safe_get(data, "health", "status", default=None)
    diagnosis = safe_get(data, "health", "diagnosis", default=[])

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Linux Health Monitor Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            background: #0f1115;
            color: #e6e6e6;
        }}
        .card {{
            background: #1a1d24;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 8px;
        }}
        .good {{ color: #4caf50; }}
        .warn {{ color: #ff9800; }}
        .bad {{ color: #f44336; }}
        pre {{
            background: #111;
            padding: 10px;
            border-radius: 6px;
            overflow-x: auto;
        }}
    </style>
</head>

<body>

<h1>Linux Health Monitor</h1>
<p>Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
<div class="card">
    <h2>System</h2>
    <pre>{json.dumps(system, indent=2)}</pre>
</div>

<div class="card">
    <h2>Core Metrics</h2>
    <pre>{json.dumps(core, indent=2)}</pre>
</div>
"""


    if uptime is not None:
        html += f"""
<div class="card">
    <h2>Uptime</h2>
    <pre>{uptime} seconds</pre>
</div>
"""


    if status:
        css_class = {
            "HEALTHY": "good",
            "WARNING": "warn",
            "CRITICAL": "bad"
        }.get(status, "warn")

        html += f"""
<div class="card">
    <h2>Health</h2>
    <p class="{css_class}">{status}</p>
    <pre>{json.dumps(diagnosis, indent=2)}</pre>
</div>
"""


    if top_processes:
        html += f"""
<div class="card">
    <h2>Top Processes</h2>
    <pre>{json.dumps(top_processes, indent=2)}</pre>
</div>
"""


    if features:
        html += f"""
<div class="card">
    <h2>Features</h2>
    <pre>{json.dumps(features, indent=2)}</pre>
</div>
"""

    html += """
</body>
</html>
"""

    return html