# Deployment (host, via systemd)

The production path is a **systemd timer on the host**, not a container.
`systemctl`, `journalctl`, `ss -tulnp` and host-scope process/disk views do not
work meaningfully from inside a namespace, so a containerized agent reports on
the container rather than on the machine you care about. The Docker image is
retained only as a CI smoke-test artifact.

The same two unit files work on both Ubuntu (Debian family) and Rocky (RHEL
family) — systemd is the common layer.

## Install

```bash
sudo mkdir -p /opt/linux-health-monitor
sudo cp -r agent /opt/linux-health-monitor/
sudo mkdir -p /opt/linux-health-monitor/reports
sudo cp systemd/health-monitor.service systemd/health-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now health-monitor.timer
```

Verify:

```bash
systemctl start health-monitor.service && systemctl status health-monitor.service
```

```bash
systemctl list-timers health-monitor.timer
```

The report lands at `/opt/linux-health-monitor/reports/report.html`.

On node2, also install the drop-in:

```bash
sudo mkdir -p /etc/systemd/system/health-monitor.service.d
sudo install -m 644 systemd/node2.conf /etc/systemd/system/health-monitor.service.d/node2.conf
sudo systemctl daemon-reload
```

Note what this install does **not** do: it never copies `systemd/` into `/opt`.
The checkout stays wherever you cloned it (`~/linux-health-monitor`), and every
command in this file is run from there.

## Upgrading

**The unit file is a separate installed copy from the code.** Pulling the repo
updates `/opt/linux-health-monitor`; it does not touch
`/etc/systemd/system/health-monitor.service`. Updating one without the other
gives you new code running under old configuration — and nothing about that
state looks broken, because the service still starts, still runs on schedule and
still writes a report. It just quietly ignores every setting you added.

So an upgrade is always **both** copies, then a reload. **Run these from your
repo checkout** (`~/linux-health-monitor`), not from `/opt`: the install is a
copy, so `/opt/linux-health-monitor` holds only `agent/` and `reports/` — there
is no `systemd/` directory there, and `git pull` cannot reach it.

```bash
sudo cp -r agent /opt/linux-health-monitor/
sudo install -m 644 systemd/health-monitor.service systemd/health-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart health-monitor.service
```

Then confirm the *running* unit is the one you just shipped, rather than
trusting that the copy landed:

```bash
systemctl show health-monitor.service -p ExecStart -p Environment --no-pager
```

`--no-pager` matters here: `systemctl show` without it hands long values to a
pager, and the wrapped output is easy to misread.

Note the `install` rather than `cp` for the unit: it overwrites in place with a
fixed mode. That is safe **only because no host hand-edits the unit** — per-host
values live in drop-ins under
`/etc/systemd/system/health-monitor.service.d/`, which the overwrite leaves
alone and which re-apply on reload. Editing the unit on a node instead means the
next upgrade silently reverts it.

Verify a drop-in is still winning after an upgrade:

```bash
systemctl show health-monitor.service -p Environment -p ProtectHome --no-pager
```

**Check for drop-ins you did not install.** Drop-ins apply in lexicographic
filename order and the last one wins, so a leftover `override.conf` — the name
`systemctl edit` generates — silently beats `node2.conf` and every value it
sets. `systemctl show` cannot reveal this: it reports the merged result, so a
stale file looks exactly like a correct one. Ask which files contributed:

```bash
systemctl cat health-monitor.service --no-pager
```

That lists the unit and each drop-in with its path, in the order applied. Any
file there that is not `node2.conf` predates this scheme and should be removed
rather than merged, since its values are the ones the repo now owns.

## Per-host configuration

All configuration is `Environment=` lines in the `.service` file — nothing is
compiled in, so the same build serves any host.

| Variable | Purpose |
|---|---|
| `HEALTH_SERVICES` | Comma-separated units to check. Differs per host — see below. |
| `HEALTH_CONTAINER_USER` | Owner of a **rootless** container runtime (node2). |
| `HEALTH_APP_ENDPOINTS` | `name=url` pairs for HTTP checks. Unset = feature omitted. |
| `HEALTH_APP_TIMEOUT` | Per-endpoint timeout in seconds (default 2). |
| `HEALTH_APP_CRITICAL` | Endpoint names that count toward the health status. Unset = this host's own endpoints plus the VIP. |
| `HEALTH_VIP` | Virtual IP(s) to check against this host's own interfaces. Unset = feature omitted. |
| `HEALTH_JOURNAL_WINDOW` | How far back to count journal errors (code default `-1h`; the unit ships `-15min`). |
| `HEALTH_SELF_UNIT` | This monitor's own unit, excluded from the failed count (default `health-monitor.service`). |
| `HEALTH_REPORT_MODE` | Octal file mode for the written report (default `0640`). |
| `HEALTH_{CPU,MEM,DISK}_{WARN,CRIT}` | Alert thresholds, in percent. Disk thresholds apply to *every* filesystem. |

The unit ships with node1's values live and is **copied verbatim to every
host**. node2's three differences live in `systemd/node2.conf`, installed as a
drop-in — never as an edit to the unit. See [Upgrading](#upgrading) for why.

### Unit names differ per host

`HEALTH_SERVICES` is per-host because the units genuinely differ — including the
SSH daemon, whose unit is `ssh` on Debian but `sshd` on RHEL:

```
# node1 — Debian family, Docker
Environment=HEALTH_SERVICES=nginx,docker,keepalived,prometheus,ssh
```

```
# node2 — RHEL family, rootless Podman
Environment=HEALTH_SERVICES=nginx,keepalived,prometheus,sshd,firewalld
```

A unit that is not installed reports `not-installed` rather than `inactive`, so
the report distinguishes "never installed" from "installed but stopped".

**Both are a WARNING.** Naming a unit that does not exist is not harmless: it
means the host is not built the way `HEALTH_SERVICES` says it is, which is
either a deployment that has not happened or a unit name that is wrong for this
distro — `ssh` on a RHEL host, for instance. If a service genuinely runs as a
container rather than a unit, take it out of the list and let the container
check and `HEALTH_APP_ENDPOINTS` cover it.

### Fleet dashboard

Point each node's `HEALTH_APP_ENDPOINTS` at **both** nodes so either node's
report shows the whole fleet's application health side by side. The same line
goes on both nodes — `fleet-slo` is `127.0.0.1` so each node reports its own SLO
view, and `vip` shows who is currently answering on the floating address:

```
Environment=HEALTH_APP_ENDPOINTS=node1-health=http://192.168.71.251:8000/health,node2-health=http://192.168.71.252:8000/health,fleet-slo=http://127.0.0.1:8000/slo,vip=http://192.168.71.250/health
```

OS metrics remain node-local — each report describes the host it ran on.
Aggregating OS metrics across both nodes would need a collector; that is
deliberately out of scope.

**A peer's outage is not this node's WARNING.** Every configured endpoint is
*reported*, but only the ones describing this host are *scored*: loopback, one
of its own addresses, or the VIP. The exit code is per-node and drives systemd
unit state, so if a peer's failure failed this node's unit too, a failover
would leave both units `failed` and the cheapest signal in the fleet could no
longer say which node to look at.

The VIP is scored on every node deliberately, whoever holds it: "the VIP does
not answer" is worth all of them reporting. `HEALTH_APP_CRITICAL` overrides the
whole computation with an explicit list when you want something else — a
hostname the monitor cannot resolve to a local address is treated as a peer, so
name it there if it is really yours.

### Serving the report

Give `--html` an absolute path inside a web root and the report is written
straight there, no copy step:

```
ExecStart=/usr/bin/python3 -m agent.monitor --all --html /var/www/health/report.html
```

The parent directory is created if missing. On an SELinux host it also needs an
httpd content label or nginx returns 403 — check with `ls -Zd /var/www/health`.

⚠️ **The report is an internal document.** It enumerates listening ports with
process names, running containers, internal addressing, MAC addresses and disk
contents. That is a reconnaissance summary of the host, so whatever serves it
should restrict access — bind it to the management network, or put auth or an
IP allow-list in front of it. Do not publish it on a public VIP unguarded.

An allow-list governs *network* reach only; it does nothing about a local
account reading the file. So the report is written `0640`, not the `0644` a
default umask produces. Override with `HEALTH_REPORT_MODE` (octal), which falls
back to `0640` if it cannot be parsed — a typo must not silently widen it.

`0640` means a web server cannot read the file unless it is in the owning
group, and the report is rewritten every run, so a one-off `chgrp` will not
survive. Make the *directory* setgid and new files inherit its group:

```bash
sudo install -d -o root -g nginx -m 2750 /var/www/health
```

Use `www-data` instead of `nginx` on the Debian side. Verify with
`stat -c '%U %G %a' /var/www/health/report.html` after a run — group should be
the web server's, mode `640`.

### Who holds the VIP

`HEALTH_VIP` takes the same value on both nodes and is checked against the
host's own interfaces (`ip -o addr`), so each node answers **for itself**:

```
Environment=HEALTH_VIP=192.168.71.250
```

This is the one fact no HTTP check can establish. A GET against the VIP proves
*someone* answered, not *who* — and during a failover both nodes can answer in
turn. The report gives a definite per-node `held: true|false`, and **split-brain
is two reports that both say `held`**, which is why the value is identical on
both nodes.

It deliberately never affects the health status: holding nothing is the correct
state for the backup node, and a node cannot tell from here whether its peer
also holds the address.

## Three gotchas

**SELinux and `NoNewPrivileges`.** The unit deliberately does *not* set
`NoNewPrivileges=yes`. On a RHEL host, `podman` transitions into the
`container_runtime_t` SELinux domain, and `NoNewPrivileges` forbids that class
of transition — so podman runs in the service's own unconfined domain instead,
and every run logs a denial:

```
avc: denied { nnp_transition } scontext=...:unconfined_service_t
     tcontext=...:container_runtime_t tclass=process2 permissive=0
```

Measured on Rocky 10, this fired on every 2-minute run. `podman ps` still
executed, so the container check kept returning data — the cost is an audit log
full of denials that would hide a real one, plus podman running less confined
than its own policy intends.

Verify after a run — note that `-ts recent` spans ten minutes and will show
pre-fix history, so timestamp the window yourself:

```bash
STAMP=$(date '+%H:%M:%S'); sudo systemctl start health-monitor.service; sleep 3; sudo ausearch -m avc -ts today "$STAMP"
```

`<no matches>` is what you want, and `systemctl show health-monitor.service
--property=NoNewPrivileges` should report `no`.

The same unit is silently fine on AppArmor and denied on SELinux — which is
exactly why the `security_module` check reports which module is enforcing.

**Rootless Podman (node2).** Containers belong to the user that started them,
so root's `podman ps` queries root's own empty store and reports nothing. Set
`HEALTH_CONTAINER_USER` to the owning user — and then also comment out
`ProtectHome=yes`, since `su -` needs the target user's home to build their
login session.

Both settings live in `systemd/node2.conf`, so they survive an upgrade.

This has a second consequence that is easy to "fix" wrongly. On node2 the
application runs as a **rootless Quadlet under `systemctl --user`**. This
monitor runs as root and queries the *system* manager, which has never heard of
that unit — so adding it to `HEALTH_SERVICES` makes the report say
`not-installed` forever. That is worse than leaving it out, because it reads as
"the app is not deployed". Application liveness on node2 comes from the
container check (`HEALTH_CONTAINER_USER`) and from `HEALTH_APP_ENDPOINTS`,
never from the service list.

**Privilege.** The service runs as root so that `ss -tulnp` process names, the
system journal and unit state are all readable. Running unprivileged works and
simply yields fewer fields — every collector degrades rather than failing.
Specifically, an unprivileged run sees only the *user* journal (so the error
count is lower than reality), no socket process names, and no AppArmor profile
count. Reading the system journal otherwise needs group `adm` on Debian or
`systemd-journal` on RHEL.

## Exit codes and alerting

`0` HEALTHY · `1` WARNING · `2` CRITICAL. These are all a **WARNING** even when
every resource threshold is fine, so the timer's exit status is a usable
alerting signal on its own:

- a failed systemd unit, or an unsynchronized clock
- a unit in `HEALTH_SERVICES` that is stopped, failed, masked or **not
  installed** — `systemctl --failed` cannot see any of these, because it lists
  only units that started and then broke
- an endpoint in `HEALTH_APP_ENDPOINTS` that does not answer **and describes
  this host** — loopback, one of its own addresses, or the VIP

A unit caught mid-restart (`activating`, `deactivating`) does not alarm, and
neither does a check that could not read a state at all — an unavailable
collector is not evidence of a fault.

Journal error *volume* deliberately does not affect the exit code — it is too
noisy for that — but it does appear in the alerts, diagnosis and report. Nor
does VIP ownership: holding nothing is correct for the backup node.

**Sizing the service list matters now.** Before this, `HEALTH_SERVICES` was
reporting-only, so an over-broad list cost nothing. It now drives the exit code,
which means a list naming units this host will never run keeps the unit
permanently `failed` and drowns the signal.

The unit therefore does **not** pass `--no-exit-code`; that flag exists for CI,
where a warning about the runner is not a build failure. Alert on:

```bash
systemctl is-failed health-monitor.service
```

Two consequences of a real exit code, both intended:

- **A WARNING leaves the unit in `failed`** until the next healthy run. That is
  the signal working. It also means `systemctl --failed` lists the monitor —
  so `get_failed_services()` excludes its own unit from the count. Without that
  exclusion, exit 1 → unit `failed` → next run counts a failed unit → WARNING →
  exit 1, a false alarm that outlives whatever started it. The unit is still
  reported under `excluded`, so a genuinely broken monitor stays visible; set
  `HEALTH_SELF_UNIT` if you renamed it.
- **systemd logs each failed run at `err` priority**, so the journal error count
  picks it up and the diagnosis may say "mostly from health-monitor.service".
  Harmless — journal volume never affects the exit code — and honest: those
  entries mean the monitor is warning. It ages out with
  `HEALTH_JOURNAL_WINDOW`.
