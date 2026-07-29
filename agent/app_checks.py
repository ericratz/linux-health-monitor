#app_checks.py
"""
Application-level HTTP health checks.

Generic by design: the agent knows how to GET a URL, time it and parse the
response, but nothing about what any particular endpoint means. The endpoint
list is host configuration, so the same build monitors any HTTP service.

Configure with HEALTH_APP_ENDPOINTS, either as a comma-separated list:

    HEALTH_APP_ENDPOINTS="node1=http://192.168.71.251:8000/health,slo=http://192.168.71.251:8000/slo"

or as a JSON object when a URL contains a comma:

    HEALTH_APP_ENDPOINTS='{"node1": "http://192.168.71.251:8000/health"}'

Unset means the feature reports itself as not configured, matching how the
other optional features degrade.
"""
import json
import os
import time
import urllib.error
import urllib.request

ENDPOINTS_ENV = "HEALTH_APP_ENDPOINTS"
TIMEOUT_ENV = "HEALTH_APP_TIMEOUT"
DEFAULT_TIMEOUT = 2.0

#A body large enough to be a page rather than a status document is truncated
#rather than folded whole into the report.
MAX_BODY_CHARS = 2000


def _endpoint_timeout():
    try:
        return float(os.getenv(TIMEOUT_ENV, DEFAULT_TIMEOUT))
    except (ValueError, TypeError):
        return DEFAULT_TIMEOUT


def parse_endpoints(raw):
    """
    Parses the endpoint configuration into an ordered list of (name, url).

    Accepts JSON or name=url pairs; a bare URL is named after itself so a
    minimal config still works.
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    if raw.startswith("{"):
        try:
            decoded = json.loads(raw)
        except ValueError:
            return []
        if not isinstance(decoded, dict):
            return []
        return [(str(name), str(url)) for name, url in decoded.items()]

    endpoints = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, url = item.partition("=")
        if sep and url.strip():
            endpoints.append((name.strip(), url.strip()))
        else:
            endpoints.append((item, item))
    return endpoints


def check_endpoint(name, url, timeout=None):
    """
    GETs one endpoint and returns its status, latency and decoded body.

    Any failure is a result rather than an exception: an unreachable peer is
    exactly the condition this check exists to report.
    """
    if timeout is None:
        timeout = _endpoint_timeout()

    result = {"name": name, "url": url}
    started = time.monotonic()

    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BODY_CHARS + 1).decode("utf-8", errors="replace")
            result["http_status"] = response.status
            result["success"] = 200 <= response.status < 300
    except urllib.error.HTTPError as e:
        #the server answered, just not with a success code - still a data point
        body = ""
        try:
            body = e.read(MAX_BODY_CHARS + 1).decode("utf-8", errors="replace")
        except Exception:
            pass
        result["http_status"] = e.code
        result["success"] = False
    except Exception as e:
        result["success"] = False
        result["error"] = str(e) or e.__class__.__name__
        result["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
        return result

    result["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
    _attach_body(result, body)
    return result


def _attach_body(result, body):
    """
    Folds a JSON body into the result as structured data, else keeps raw text.
    """
    truncated = len(body) > MAX_BODY_CHARS
    body = body[:MAX_BODY_CHARS]
    stripped = body.strip()
    if stripped and not truncated:
        try:
            result["data"] = json.loads(stripped)
            return
        except ValueError:
            pass
    result["body"] = stripped
    if truncated:
        result["truncated"] = True


def get_app_checks():
    """
    Runs every configured endpoint check.
    """
    endpoints = parse_endpoints(os.getenv(ENDPOINTS_ENV))
    if not endpoints:
        return {
            "feature": "app_checks",
            "success": False,
            "reason": f"no endpoints configured (set {ENDPOINTS_ENV})",
            "data": None
        }

    timeout = _endpoint_timeout()
    checks = [check_endpoint(name, url, timeout) for name, url in endpoints]
    healthy = sum(1 for c in checks if c.get("success"))
    return {
        "feature": "app_checks",
        "success": True,
        "count": len(checks),
        "healthy": healthy,
        "data": checks
    }
