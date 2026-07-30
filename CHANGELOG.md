# Changelog

## v3.0

Replaces the `psutil` abstraction with direct reads of `/proc`, `/sys` and core
userland commands; adds application-level HTTP checks, host posture checks, and
distro-family awareness so one build behaves correctly on Debian- and
RHEL-family hosts.

The agent has **no runtime dependencies and requires no new packages**. Where a
check would normally need a tool a minimized install omits, it reads the
interface that tool reads instead — `getenforce` reads `/sys/fs/selinux`,
`aa-status` reads `/sys/module/apparmor`, `iostat` reads `/proc/diskstats`.

### Breaking

- **`features.docker` is now `features.containers`.** The check probes Docker
  then Podman and reports which one answered in a new `container_runtime` field.
  Calling the key `docker` on a Podman host was simply untrue. The field is
  named `container_runtime` rather than `runtime` because it describes the
  runtime found *on the host*, not the environment the monitor is running in —
  `system.environment` is what answers that.
- **`requirements.txt` no longer installs `psutil`.** It lists only `pytest`,
  for tests. Nothing is needed to run the agent.
- **A failed systemd unit or an unsynchronized clock now yields `WARNING`**
  (exit code 1) even when every resource threshold is fine. A host with a dead
  service is not healthy because its CPU is idle. **This changes exit codes**
  for such hosts. Journal error *volume* deliberately does not affect the exit
  code: it is too noisy to gate alerting on.
- `get_cpu_snapshot()` returns four elements: `(cpu, top_processes, disk_io,
  pressure)`.
- `get_process_summary()` gained a `blocked` key.
- `get_system_identity()` gained an `os_family` key.
- `run_health_analysis()` accepts optional `features` and `os_family`, so a
  diagnosis can cite the journal, clock or a pending reboot.

### Added

- `agent/shell.py` — the `run_command` wrapper, relocated so both metric and
  context collection can share it without a circular import. Takes a `timeout`
  argument (`du` on a large `/var/log` needs more than 3s), and provides
  `have(cmd)`, a cached PATH probe so a check can skip cleanly rather than
  shelling out to something absent.
- `agent/app_checks.py` — configurable HTTP endpoint checks recording status,
  latency, and parsed JSON body (raw text for non-JSON; a non-2xx response
  still captures its body). Configured via `HEALTH_APP_ENDPOINTS` as `name=url`
  pairs or a JSON object; unset means the feature reports itself absent.
- `agent/host_checks.py` with five checks:
  - `journal_errors` — error-priority entries in a configurable window
    (`HEALTH_JOURNAL_WINDOW`, default `-1h`), tallied per unit. Uses journald
    rather than `/var/log/syslog` vs `/var/log/messages`, which erases that
    family difference entirely — a minimized RHEL host may have neither file.
    Entries are counted from JSON output, not by counting lines: a multi-line
    message is one entry but many lines, which inflated a naive count ~5x.
  - `time_sync` — whether the clock is synchronized and which daemon owns it.
    Skew between HA peers breaks certificate validation and cross-node log
    correlation. The daemon is detected, not assumed per family: chrony is
    common on both.
  - `security_module` — SELinux or AppArmor and its mode, the usual reason a
    container or port that works on Debian fails on RHEL.
  - `firewall` — which firewall is running, via systemd unit state.
  - `reboot_required` — Debian flag file or `dnf needs-restarting`.
- `features.listening_ports` — sockets via `ss -tulnp`, with process names when
  running as root and ports only when not.
- `core_metrics.filesystems` — usage for *every* writable filesystem, worst
  first. Only `/` was measured before, so a full `/var` or `/boot` was
  invisible while the report showed a healthy root. Disk thresholds now apply
  to all of them.
- `core_metrics.pressure` — `iowait_percent`, `runnable`, swap in/out bytes per
  second, and major faults per second, from the two `/proc/stat` samples already
  being taken plus `/proc/vmstat`. This is `vmstat`'s signal without `sysstat`.
- `processes.blocked` — count of state `D` (uninterruptible sleep), the
  processes `ps aux | awk '$8=="D"'` hunts for when load is high but CPU is idle.
- `os_family` — derived from `/etc/os-release` `ID` then `ID_LIKE` (Rocky
  declares `ID_LIKE="rhel centos fedora"`). Picks `apt` vs `dnf` and the correct
  reboot indicator.
- `get_cpu_cores()` via `nproc`, replacing `psutil.cpu_count`.
- `HEALTH_SERVICES` — the units to check are now configurable; the interesting
  units differ per host (`docker.service` vs. a rootless Quadlet unit).
- `HEALTH_CONTAINER_USER` — inspect a rootless container runtime owned by
  another user, which root's own `podman ps` cannot see.
- `systemd/` — a oneshot `.service` and a 2-minute `.timer`, the production
  deployment path, with per-host configuration as `Environment=` lines.
  `NoNewPrivileges` is deliberately unset: on SELinux hosts it denies `podman`'s
  transition into `container_runtime_t`, so podman runs in the service's
  unconfined domain and every run logs an `nnp_transition` AVC denial. The
  container check still returned data, so the cost is a flooded audit log and a
  less-confined podman rather than a broken feature. Measured on Rocky 10, and
  confirmed clear once the flag was removed.
- HTML report gains **Filesystems**, **Application Endpoints**, **Journal
  Errors** and **Host Posture** cards, and renders the suggested commands,
  which previously existed only in the JSON.
- `--version` flag and an `agent_version` field in the report.

### Changed

- **CPU %** from a two-sample `/proc/stat` delta. `iowait` counts as idle: a
  core blocked on disk is not doing work. Because that hides I/O stalls from the
  CPU number, `iowait` is reported separately as pressure.
- **Per-process CPU** from a `/proc/<pid>/stat` delta over the sampling
  interval, reusing the single existing sleep. This is a true interval
  measurement, where `ps %cpu` reports a lifetime average that keeps showing a
  long-idle process as busy.
- **Per-process memory** from `/proc/<pid>/statm`, not `/proc/<pid>/stat`. The
  kernel documents the latter's `rss` field as inaccurate and points to `statm`;
  the two disagreed by up to a few hundred KB per process in practice. Only the
  closing sample reads it, since memory is a level rather than a delta.
- **Memory** from `/proc/meminfo`, deriving "used" from `MemAvailable` so cache
  and reclaimable slab are not counted against the host. Falls back to
  `MemFree + Buffers + Cached` on kernels predating `MemAvailable`.
- **Disk usage** from `df -P -B1 /`. The percentage is `used/(used+available)`,
  excluding root-reserved blocks an unprivileged writer cannot claim — the same
  basis `df`'s own Capacity column uses.
- **Disk I/O** from a `/proc/diskstats` delta, counting whole physical disks
  only. Partitions are identified by the kernel's `partition` attribute rather
  than a trailing digit, so `nvme0n1` is not confused with `nvme0n1p1`. Loop
  and RAM devices are excluded: a read from a loop-mounted squashfs also causes
  a read on the backing disk, so counting both double-counts it.
- **Filesystem exclusion is by mount option, not filesystem type.** Read-only is
  the test that separates a snap image sitting at 100% forever from a genuinely
  full `/var`. Type is only used to drop kernel-synthetic and remote
  filesystems, the latter because a hung remote server would stall `df`.
  **tmpfs mounts are reported**, despite being RAM-backed: they are sized and
  can fill, and when they do, services fail. On a stock Ubuntu host `/tmp` and
  `/dev/shm` are tmpfs at ~1.7 GB each, so on a 4 GB node they are both a real
  outage surface and a meaningful share of total RAM. `devtmpfs` (`/dev`) and
  `ramfs` stay excluded: the former only holds device nodes, and the latter has
  no size limit to measure against.
- **CPU temperature** from `/sys/class/thermal`, falling back to
  `/sys/class/hwmon` where `coretemp`/`k10temp` surface on physical hardware.
  CPU sensors are preferred over ambient ones, and multiple readings from the
  winning sensor are averaged. `lm-sensors` is deliberately not used.
- **Top directory sizes** via `du -B1 -s`, keeping partial output when a
  subtree is unreadable.
- **Network I/O** from `/proc/net/dev`, summed across all interfaces.
- **Load average** from `/proc/loadavg`, with `os.getloadavg()` as fallback.
- **Diagnosis is I/O aware.** `iowait` replaces the old load-versus-CPU guess:
  load counts processes waiting on disk while CPU percentage does not, so an
  I/O-stalled host used to look idle. Swap-out traffic is distinguished from a
  merely slow disk.
- **Alerts and diagnosis now cover host posture.** Failed units, journal error
  volume, clock skew and pending reboots reach the alerts and diagnosis, not
  just the action list — otherwise a host with four real problems could report
  "No issues detected" while the suggested commands named all four.
- **Recommendations are family-correct** and scoped: `du -xh` stays on one
  filesystem, journal commands name the specific failing unit, and the reboot
  hint matches the family. Nothing is ever executed; commands that would change
  system state are only ever emitted as strings for a person to choose to run.
- **Service status uses `systemctl show` instead of `is-active`**, so a unit that
  is *not installed* reports `not-installed` rather than `inactive`. `is-active`
  returns "inactive" for both, which reads as "installed but stopped" and is
  actively misleading for `docker` on a Podman host or `nginx` before the
  platform is deployed. A masked unit reports `masked`, and a failed one carries
  its `SubState` as `detail`. This also fixes the older behaviour where a merely
  stopped unit became `unknown`, since `is-active` exits non-zero for it.

### Fixed

- **HTML injection / rendering.** Report values were interpolated unescaped.
  Every value is untrusted — process names come from the kernel, unit and
  container names from the host, and app-check fields from whatever a remote
  endpoint returned — and the report is meant to be served over HTTP. This was
  also a visible bug: an error like
  `<urlopen error [Errno 111] Connection refused>` was parsed as an unknown tag
  and silently swallowed, blanking the cell an operator most needs to read.

### Notes

- Metric values were verified by same-instant comparison against `psutil` on the
  same host: memory available, network counters, disk free, I/O write bytes, and
  per-process RSS matched **exactly**; load and process count matched;
  percentages agreed to rounding. Aggregate disk *read* bytes differ by exactly
  the loop-device total, per the deliberate change above. Existing collectors
  kept their return shapes, so `health_analysis.py` needed no changes to keep
  working — it was extended for the new signals, not rewritten.
- Deliberately *not* used, with the dependency-free equivalent preferred
  instead: `netstat` (absent; use `ss`), `dig` (absent; use `getaddrinfo`),
  `ping` (absent on node1; use a TCP connect), `nc -zv` (flag differences
  between `nmap-ncat` and `netcat-openbsd`), `mpstat`/`iostat`/`pidstat`
  (`sysstat` absent on both nodes), `last` (absent on Ubuntu 26.04),
  `ifup`/`ifdown` (not present on RHEL), `getenforce`/`aa-status` (separate
  packages; read `/sys` instead).
- `dmesg` is readable unprivileged on Debian (`kernel.dmesg_restrict=0`) but not
  on RHEL, where it defaults to `1`. Reading the *system* journal likewise needs
  group membership: `adm` on Debian, `systemd-journal` on RHEL. An unprivileged
  run sees only the user journal, so its error count is lower than reality.
- System identity keeps using `platform` (`platform.node()`,
  `platform.freedesktop_os_release()`, `platform.release()`). These are stdlib
  and read the same `uname` and `/etc/os-release` sources the equivalent
  commands do, with no subprocess cost.
- **Not yet verified on RHEL.** All parsing has been exercised against
  Debian-family output only; the RHEL-family behaviour above is reasoned from
  documented defaults. Running `--all` on both nodes and diffing the report
  structure is the real portability test.
