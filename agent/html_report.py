from datetime import datetime, timezone
#imported by name: generate_html uses a local named 'html' for the document
from html import escape
import json


def esc(value):
    """
    Escapes a value for inclusion in HTML.

    Everything rendered here is untrusted: process names come from the kernel,
    container and unit names from the host, and app-check fields from whatever
    a remote endpoint returned. The report is meant to be served over HTTP, so
    an unescaped '<' is both a rendering bug and an injection vector.
    """
    return escape(str(value), quote=True)


def format_uptime(seconds):
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def format_bytes(num):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} PB"


def format_network(network):
    network = dict(network)
    if isinstance(network.get("bytes_sent"), (int, float)):
        network["bytes_sent"] = format_bytes(network["bytes_sent"])
    if isinstance(network.get("bytes_received"), (int, float)):
        network["bytes_received"] = format_bytes(network["bytes_received"])
    return network


def format_memory(memory):
    memory = dict(memory)
    if isinstance(memory.get("available"), (int, float)):
        memory["available"] = format_bytes(memory["available"])
    return memory


def format_disk(disk):
    disk = dict(disk)
    if isinstance(disk.get("root_free"), (int, float)):
        disk["root_free"] = format_bytes(disk["root_free"])
    return disk


def format_filesystems(filesystems):
    formatted = []
    for filesystem in filesystems or []:
        filesystem = dict(filesystem)
        if isinstance(filesystem.get("free"), (int, float)):
            filesystem["free"] = format_bytes(filesystem["free"])
        if isinstance(filesystem.get("used_percent"), (int, float)):
            filesystem["used_percent"] = f"{filesystem['used_percent']}%"
        formatted.append(filesystem)
    return formatted


def format_pressure(pressure):
    pressure = dict(pressure or {})
    for key in ("swap_in_bytes_per_sec", "swap_out_bytes_per_sec"):
        if isinstance(pressure.get(key), (int, float)):
            pressure[key] = f"{format_bytes(pressure[key])}/s"
    if isinstance(pressure.get("iowait_percent"), (int, float)):
        pressure["iowait_percent"] = f"{pressure['iowait_percent']}%"
    return pressure


def format_disk_details(features):
    features = dict(features)
    disk_details = dict(features.get("disk_details", {}))
    data = disk_details.get("data", [])
    for item in data:
        if isinstance(item.get("size_bytes"), (int, float)):
            item["size_bytes"] = format_bytes(item["size_bytes"])
    disk_details["data"] = data
    features["disk_details"] = disk_details
    return features


def render_card(title, content):
    return f"""
<div class="card">
    <h2>{esc(title)}</h2>
    <pre>{esc(content)}</pre>
</div>
"""


def render_services(services):
    if not services.get("success"):
        return f'<p class="muted">{esc(services.get("reason", "unavailable"))}</p>'
    rows = "".join(
        f'<li>{esc(s["service"])}: <span class="mono">{esc(s.get("status", "unknown"))}</span></li>'
        for s in services.get("data") or []
    )
    return f"<ul>{rows}</ul>" if rows else '<p class="muted">No services checked</p>'


def render_containers(containers_feature):
    if not containers_feature.get("success"):
        return f'<p class="muted">{esc(containers_feature.get("reason", "unavailable"))}</p>'
    runtime = esc(containers_feature.get("container_runtime", "unknown"))
    containers = containers_feature.get("running_containers", [])
    if not containers:
        return f'<p class="muted">No containers running <span class="mono">({runtime})</span></p>'
    rows = "".join(f"<li>{esc(c)}</li>" for c in containers)
    return (
        f'<p>{len(containers)} running <span class="muted mono">({runtime})</span></p>'
        f"<ul>{rows}</ul>"
    )


def render_app_checks(app_checks):
    """Renders the configured HTTP endpoint checks as a status table."""
    if not app_checks.get("success"):
        return f'<p class="muted">{esc(app_checks.get("reason", "unavailable"))}</p>'
    checks = app_checks.get("data") or []
    if not checks:
        return '<p class="muted">No endpoints checked</p>'

    rows = ""
    for check in checks:
        ok = check.get("success")
        css_class = "good" if ok else "bad"
        if ok:
            state = str(check.get("http_status", "up"))
        else:
            state = check.get("error") or f'HTTP {check.get("http_status", "error")}'
        latency = check.get("latency_ms")
        latency_text = f"{latency} ms" if latency is not None else ""
        detail = check.get("data") if isinstance(check.get("data"), dict) else None
        summary = ""
        if detail:
            #surface the endpoint's own status field when it exposes one
            for key in ("status", "state", "health"):
                if key in detail:
                    summary = str(detail[key])
                    break
        rows += (
            f"<tr><td>{esc(check.get('name'))}</td>"
            f'<td class="{css_class}">{esc(state)}</td>'
            f"<td>{esc(summary)}</td>"
            f"<td>{esc(latency_text)}</td></tr>"
        )

    header = (
        f'<p>{app_checks.get("healthy", 0)}/{app_checks.get("count", 0)} healthy</p>'
    )
    return (
        f"{header}<table><thead><tr><th>Endpoint</th><th>Status</th>"
        f"<th>Reported</th><th>Latency</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def render_disk_details(disk_details):
    if not disk_details.get("success"):
        return f'<p class="muted">{esc(disk_details.get("error", "unavailable"))}</p>'
    data = disk_details.get("data") or []
    if not data:
        return '<p class="muted">No data</p>'
    rows = "".join(
        f"<tr><td>{esc(item['name'])}</td><td>{esc(item['size_bytes'])}</td></tr>"
        for item in data
    )
    return f'<table><tbody>{rows}</tbody></table>'


def render_failed_services(failed):
    if not failed.get("success"):
        return f'<p class="muted">{esc(failed.get("reason", "unavailable"))}</p>'
    #the monitor's own unit is excluded from the count, but saying so keeps a
    #genuinely broken monitor from erasing itself from its own report
    excluded = failed.get("excluded") or []
    note = "".join(
        f'<p class="muted">{esc(unit)} failed (excluded from the count)</p>'
        for unit in excluded
    )
    if failed["count"] == 0:
        return note or '<p class="muted">None</p>'
    rows = "".join(f'<li class="bad">{esc(s)}</li>' for s in failed["services"])
    return f"<ul>{rows}</ul>{note}"


def render_filesystems(filesystems, warn=80, crit=90):
    """Renders every filesystem as a table, worst first, colour-coded."""
    if not filesystems:
        return '<p class="muted">No filesystems reported</p>'
    rows = ""
    for filesystem in filesystems:
        used = filesystem.get("used_percent")
        css_class = ""
        if isinstance(used, (int, float)):
            css_class = "bad" if used > crit else "warn" if used > warn else "good"
        used_text = f"{used}%" if isinstance(used, (int, float)) else esc(used)
        free = filesystem.get("free")
        free_text = format_bytes(free) if isinstance(free, (int, float)) else esc(free)
        rows += (
            f"<tr><td><span class=\"mono\">{esc(filesystem.get('mount'))}</span></td>"
            f'<td class="{css_class}">{esc(used_text)}</td>'
            f"<td>{esc(free_text)} free</td>"
            f"<td>{esc(filesystem.get('device') or '')}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Mount</th><th>Used</th><th>Free</th>"
        f"<th>Device</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def render_journal_errors(journal):
    if not journal.get("success"):
        return f'<p class="muted">{esc(journal.get("reason", "unavailable"))}</p>'
    count = journal.get("count", 0)
    window = esc(journal.get("window", ""))
    if not count:
        return f'<p class="good">No errors since {window}</p>'
    capped = " (capped)" if journal.get("capped") else ""
    units = "".join(
        f'<li>{esc(entry.get("unit"))}: <span class="mono">{esc(entry.get("count"))}</span></li>'
        for entry in journal.get("by_unit") or []
    )
    samples = "".join(
        f'<li><span class="muted">{esc(sample.get("unit"))}</span> '
        f'{esc(sample.get("message"))}</li>'
        for sample in journal.get("data") or []
    )
    return (
        f'<p class="bad">{esc(count)}{capped} error(s) since {window}</p>'
        f"{f'<ul>{units}</ul>' if units else ''}"
        f"{f'<ul>{samples}</ul>' if samples else ''}"
    )


def render_time_sync(time_sync):
    if not time_sync.get("success"):
        return f'<p class="muted">{esc(time_sync.get("reason", "unavailable"))}</p>'
    synced = time_sync.get("synchronized")
    css_class = "good" if synced else "bad"
    label = "synchronized" if synced else "NOT synchronized"
    service = time_sync.get("service") or "no active time daemon"
    return (
        f'<p class="{css_class}">{label}</p>'
        f'<p class="muted">{esc(service)} &middot; {esc(time_sync.get("timezone") or "")}</p>'
    )


def render_security_module(module):
    if not module.get("success"):
        return f'<p class="muted">{esc(module.get("reason", "unavailable"))}</p>'
    mode = module.get("mode")
    css_class = "good" if mode == "enforcing" else "warn"
    profiles = module.get("profiles_loaded")
    detail = f' <span class="muted">({esc(profiles)} profiles)</span>' if profiles else ""
    return (
        f'<p><span class="mono">{esc(module.get("module"))}</span>: '
        f'<span class="{css_class}">{esc(mode)}</span>{detail}</p>'
    )


def render_firewall(firewall):
    if not firewall.get("success"):
        return f'<p class="muted">{esc(firewall.get("reason", "unavailable"))}</p>'
    active = firewall.get("active")
    if not active:
        #not an error, but worth seeing on a host that should have one
        return '<p class="warn">No active firewall</p>'
    detail = firewall.get("detail")
    suffix = f' <span class="muted">({esc(detail)})</span>' if detail else ""
    return f'<p class="good">{esc(active)} active</p>{suffix}'


def render_vip(vip):
    if not vip.get("success"):
        return f'<p class="muted">{esc(vip.get("reason", "unavailable"))}</p>'
    items = []
    for entry in vip.get("data") or []:
        address = f'<span class="mono">{esc(entry.get("address"))}</span>'
        if entry.get("held"):
            interface = esc(entry.get("interface") or "?")
            state = f'<span class="good">held</span> on {interface}'
        else:
            #the backup node correctly holds nothing: neutral, not a fault
            state = '<span class="muted">not held</span>'
        items.append(f"<li>{address} &rarr; {state}</li>")
    if not items:
        return '<p class="muted">None configured</p>'
    return f"<ul>{''.join(items)}</ul>"


def render_reboot_required(reboot):
    if not reboot.get("success"):
        return f'<p class="muted">{esc(reboot.get("reason", "unavailable"))}</p>'
    if not reboot.get("reboot_required"):
        return '<p class="good">No</p>'
    packages = reboot.get("data") or []
    listed = "".join(f"<li>{esc(name)}</li>" for name in packages[:10])
    return f'<p class="warn">Yes</p>{f"<ul>{listed}</ul>" if listed else ""}'


def render_listening_ports(ports_feature):
    if not ports_feature.get("success"):
        return f'<p class="muted">{esc(ports_feature.get("reason", "unavailable"))}</p>'
    ports = ports_feature.get("data") or []
    if not ports:
        return '<p class="muted">Nothing listening</p>'
    rows = "".join(
        f"<tr><td><span class=\"mono\">{esc(p['port'])}/{esc(p['protocol'])}</span></td>"
        f"<td>{esc(p.get('address') or '')}</td>"
        f"<td>{esc(p.get('process') or '-')}</td></tr>"
        for p in ports
    )
    return (
        f'<table><thead><tr><th>Port</th><th>Address</th><th>Process</th></tr>'
        f"</thead><tbody>{rows}</tbody></table>"
    )


def render_cpu_temp(temp):
    if not temp.get("success"):
        return f'<p class="muted">{esc(temp.get("reason", "unavailable"))}</p>'
    return f'<p>{esc(temp["celsius"])}°C <span class="muted">({esc(temp["source"])})</span></p>'


def render_features_card(features):
    services_html = render_services(features.get("services") or {})
    failed_html = render_failed_services(features.get("failed_services") or {})
    containers_html = render_containers(features.get("containers") or {})
    disk_html = render_disk_details((features.get("disk_details") or {}).copy())
    temp_html = render_cpu_temp(features.get("cpu_temperature") or {})
    app_html = render_app_checks(features.get("app_checks") or {})
    ports_html = render_listening_ports(features.get("listening_ports") or {})
    journal_html = render_journal_errors(features.get("journal_errors") or {})
    time_html = render_time_sync(features.get("time_sync") or {})
    lsm_html = render_security_module(features.get("security_module") or {})
    firewall_html = render_firewall(features.get("firewall") or {})
    vip_html = render_vip(features.get("vip") or {})
    reboot_html = render_reboot_required(features.get("reboot_required") or {})
    return f"""
<div class="card">
    <h2>Application Endpoints</h2>
    {app_html}
</div>
<div class="card">
    <h2>Journal Errors</h2>
    {journal_html}
</div>
<div class="card">
    <h2>Host Posture</h2>
    <h3>Time Synchronization</h3>
    {time_html}
    <h3>Access Control</h3>
    {lsm_html}
    <h3>Firewall</h3>
    {firewall_html}
    <h3>Virtual IP</h3>
    {vip_html}
    <h3>Reboot Required</h3>
    {reboot_html}
</div>
<div class="card">
    <h2>Features</h2>
    <h3>Services</h3>
    {services_html}
    <h3>Failed Services</h3>
    {failed_html}
    <h3>Containers</h3>
    {containers_html}
    <h3>Listening Ports</h3>
    {ports_html}
    <h3>Disk Usage <span class="muted">(/var/log)</span></h3>
    {disk_html}
    <h3>CPU Temperature</h3>
    {temp_html}
</div>
"""


def format_percents(core):
    core = dict(core)
    if isinstance(core.get("cpu"), (int, float)):
        core["cpu"] = f"{core['cpu']}%"
    memory = dict(core.get("memory", {}))
    for key in ("used_percent", "swap_used_percent"):
        if isinstance(memory.get(key), (int, float)):
            memory[key] = f"{memory[key]}%"
    core["memory"] = memory
    disk = dict(core.get("disk", {}))
    if isinstance(disk.get("root_used_percent"), (int, float)):
        disk["root_used_percent"] = f"{disk['root_used_percent']}%"
    core["disk"] = disk
    return core


def format_process_percents(procs):
    result = []
    for p in procs:
        p = dict(p)
        if isinstance(p.get("cpu_percent"), (int, float)):
            p["cpu_percent"] = f"{p['cpu_percent']}%"
        if isinstance(p.get("memory_percent"), (int, float)):
            p["memory_percent"] = f"{p['memory_percent']}%"
        result.append(p)
    return result


def format_core(core):
    core = dict(core)
    core["memory"] = format_memory(core.get("memory", {}))
    core["disk"] = format_disk(core.get("disk", {}))
    core["network"] = format_network(core.get("network", {}))
    return core


def humanize_view(view):
    """Format bytes, percentages, time, and normalized load for human-readable JSON output (-H)."""
    view = dict(view)
    cores = view.get("system", {}).get("cpu_cores") or 1
    if "core_metrics" in view:
        core = format_percents(dict(view["core_metrics"]))
        core["memory"] = format_memory(core.get("memory", {}))
        core["disk"] = format_disk(core.get("disk", {}))
        core["network"] = format_network(core.get("network", {}))
        load = dict(core.get("load", {}))
        for key in ("1min", "5min", "15min"):
            if isinstance(load.get(key), (int, float)):
                load[key] = f"{round(load[key] / cores * 100, 1)}%"
        core["load"] = load
        if core.get("disk_io"):
            dio = dict(core["disk_io"])
            for key in ("read_bytes_per_sec", "write_bytes_per_sec"):
                if isinstance(dio.get(key), (int, float)):
                    dio[key] = f"{format_bytes(dio[key])}/s"
            core["disk_io"] = dio
        if core.get("filesystems"):
            core["filesystems"] = format_filesystems(core["filesystems"])
        if core.get("pressure"):
            core["pressure"] = format_pressure(core["pressure"])
        view["core_metrics"] = core
    if "uptime_seconds" in view:
        view["uptime"] = format_uptime(view.pop("uptime_seconds"))
    if view.get("top_processes"):
        view["top_processes"] = format_process_percents(view["top_processes"])
    if view.get("features"):
        view["features"] = format_disk_details(view["features"])
    return view


def generate_html(data):
    system = data.get("system", {})
    core = format_percents(format_core(data.get("core_metrics", {})))
    #filesystems read far better as a table than inside a JSON dump
    filesystems = data.get("core_metrics", {}).get("filesystems")
    core.pop("filesystems", None)
    if core.get("pressure"):
        core["pressure"] = format_pressure(core["pressure"])
    uptime = data.get("uptime_seconds")
    if uptime is not None:
        uptime = format_uptime(uptime)
    _raw_procs = data.get("top_processes")
    top_processes = format_process_percents(_raw_procs) if _raw_procs else None
    features = format_disk_details(data.get("features", {}))
    status = data.get("health", {}).get("status")
    diagnosis = data.get("health", {}).get("diagnosis", [])
    alerts = data.get("health", {}).get("alerts", [])
    actions = data.get("health", {}).get("actions", [])

    #the hostname matters once reports from several nodes are served together
    hostname = system.get("hostname")
    host_label = f" &middot; <strong>{esc(hostname)}</strong>" if hostname else ""
    agent_version = data.get("agent_version")
    version_label = f" &middot; agent v{esc(agent_version)}" if agent_version else ""

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
        .muted {{ color: #888; font-size: 0.9em; }}
        .mono {{ font-family: monospace; }}
        pre {{
            background: #111;
            padding: 10px;
            border-radius: 6px;
            overflow-x: auto;
        }}
        h3 {{
            margin: 14px 0 6px;
            font-size: 0.95em;
            color: #aaa;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        ul {{ margin: 4px 0 0 18px; padding: 0; }}
        li {{ margin: 2px 0; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 4px; }}
        td {{ padding: 4px 12px 4px 0; font-size: 0.95em; }}
        td:last-child {{ color: #aaa; text-align: right; }}
        th {{
            padding: 4px 12px 4px 0;
            font-size: 0.8em;
            color: #888;
            text-align: left;
            font-weight: normal;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            border-bottom: 1px solid #2a2e37;
        }}
        th:last-child {{ text-align: right; }}
    </style>
</head>

<body>

<h1>Linux Health Monitor</h1>
<p>Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
{host_label}<span class="muted">{version_label}</span></p>
"""

    html += render_card("System", json.dumps(system, indent=2))
    html += render_card("Core Metrics", json.dumps(core, indent=2))

    if filesystems:
        html += f"""
<div class="card">
    <h2>Filesystems</h2>
    {render_filesystems(filesystems)}
</div>
"""

    if uptime is not None:
        html += f"""
<div class="card">
    <h2>Uptime</h2>
    <p>{uptime}</p>
</div>
"""

    if status:
        css_class = {
            "HEALTHY": "good",
            "WARNING": "warn",
            "CRITICAL": "bad"
        }.get(status, "warn")
        diag_items = "".join(f"<li>{esc(d)}</li>" for d in diagnosis)
        #alerts are what actually drove the status. Without them a report can
        #read "WARNING" over a diagnosis that explains nothing, which leaves
        #the one question the reader has - why - answerable only from the JSON.
        alert_items = "".join(f'<li class="warn">{esc(a)}</li>' for a in alerts)
        alert_block = f"""
    <h3>Alerts</h3>
    <ul>{alert_items}</ul>""" if alert_items else ""
        #suggested commands, never executed: a person decides whether to run them
        action_items = "".join(f'<li class="mono">{esc(a)}</li>' for a in actions)
        action_block = f"""
    <h3>Suggested Commands <span class="muted">(not run automatically)</span></h3>
    <ul>{action_items}</ul>""" if action_items else ""

        html += f"""
<div class="card">
    <h2>Health</h2>
    <p class="{css_class}" style="font-size:1.2em; font-weight:bold; margin:0 0 8px">{esc(status)}</p>
    <ul>{diag_items}</ul>{alert_block}{action_block}
</div>
"""

    if top_processes:
        html += render_card("Top Processes", json.dumps(top_processes, indent=2))

    if features:
        html += render_features_card(features)

    html += """
</body>
</html>
"""

    return html