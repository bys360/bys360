# BYS360 Campaign 1B — Agent 3: Dependency Audit Closure Findings

Date: 2026-07-24
Worktree: `C:\bys360\worktrees\phase5-critical-lint-clean` (branch `phase5-critical-lint-clean-v1`, HEAD `9816259`)
Canonical runner: `C:\bys360\project\.venv\Scripts\python.exe` (pip 26.1.2, pip-audit 2.7.0, Python 3.12.10)

## Final classification: BLOCKED

`pip-audit` cannot be run reliably to completion in this environment, in any of the
tested modes. This is an environment defect, not a network outage and not a
`requirements.txt` structure problem. No vulnerability data was produced, so this
is reported as BLOCKED, not PASS, per the "never call a timeout a PASS" rule.

## Root cause (confirmed with process-tree evidence, not just theory)

`C:\bys360\project\.venv\pyvenv.cfg` shows the venv's **base interpreter** is the
Windows Store / UWP "App Execution Alias" Python 3.12:

```
home = C:\Users\<KULLANICI>\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0
executable = ...WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe
command = ...WindowsApps\...\python.exe -m venv C:\bys360\project\.venv
```

Any code path that needs to bootstrap a *new* ephemeral venv (CPython's own `venv`
module does this deliberately via `sys._base_executable` to avoid nested venvs)
therefore shells out to the Store Python, not to the fast, already-populated
`C:\bys360\project\.venv`. Live process-tree capture (`Get-CimInstance
Win32_Process`) while `pip-audit -r requirements.txt --no-deps` was running showed
the exact 4-level cascade, reproducing Campaign 1's original finding verbatim:

```
PID 4012  C:\bys360\project\.venv\Scripts\python.exe  -m pip_audit -r requirements.txt --no-deps ...
 └─ PID 2884  ...WindowsApps\...\python3.12.exe        -m pip_audit -r requirements.txt --no-deps ...   (same argv, re-exec'd under Store Python)
     └─ PID 10344 C:\Users\...\Temp\tmpfsmxt6mb\Scripts\python.exe  -m pip install --no-input --dry-run --report ... -r requirements.txt   (pip-audit's ephemeral resolver venv)
         └─ PID 30740 ...WindowsApps\...\python3.12.exe -m pip install --no-input --dry-run --report ... -r requirements.txt   (same argv, re-exec'd again)
```

The innermost process (PID 30740) is the one that stalls: it opened exactly one
outbound HTTPS connection (IPv6, port 443) and accumulated real but very slow CPU
time — matching Campaign 1's "single IPv6 host, ~1.8s CPU over 20+ min" signature.
The Store/UWP Python runs under a restrictive AppContainer sandbox, which is the
most likely explanation for why ordinary PyPI I/O (proven fast from this same
machine via `curl`, both IPv4 and IPv6, ~0.2–0.4s per request) becomes a
multi-minute-plus stall once it happens inside that sandboxed interpreter.

Ruled out:
- **Network/DNS reachability**: `curl -4`/`curl -6` to `pypi.org` and to the exact
  `pypi.org/pypi/<pkg>/<ver>/json` endpoints pip-audit uses returned HTTP 200 in
  0.2–0.4s for every package tested (Flask, cryptography, gevent, pandas, numpy,
  Pillow, psycopg2-binary). No proxy or custom index is configured (`pip config
  list` is empty; no `pip.conf`/`pip.ini`; no `PIP_*`/proxy env vars set).
- **`requirements.txt` shape**: all 27 entries are exact `==` pins, no git/URL/
  local-path requirements, nothing that would force resolver backtracking.
  (`requirements-dev.txt` has one range, `pytest>=8,<9`, but Campaign 1's stalled
  run only targeted `requirements.txt`, and our step-2 test that stalled used no
  requirements file at all — so the range is not the cause.)
- **Resolver backtracking specifically**: `--no-deps` (which skips pip's
  dependency-resolution/backtracking step) still triggers the identical ephemeral
  venv + `pip install --dry-run --report` cascade and still stalls, so the delay
  is not backtracking — pip-audit unconditionally builds an ephemeral resolver
  venv for `-r` mode regardless of `--no-deps`.

## Methods tried, in order, with exact commands/timings

1. **Diagnosis** (network, config, requirements shape) — see above. No blocker found; all fast/clean.
2. **Env-mode audit (no `-r`, scans installed packages directly)**:
   `pip_audit --format json -o reports/quality/pip_audit_result_campaign1b.json`
   Time-boxed 300s via `timeout 300`. Result: killed at exit code 124 after
   exactly 300s, zero bytes of output, no partial file. Live process check
   confirmed it spawned a child at the WindowsApps Store Python path within
   seconds, before any localhost/PyPI connection existed for the parent PID.
3. **`--no-deps` against `requirements.txt`**:
   `pip_audit -r requirements.txt --no-deps --format json -o reports/quality/pip_audit_result_campaign1b.json`
   Time-boxed 240s via `timeout 240`. Result: killed at exit code 124 after
   exactly 240s, zero output file. Live process-tree capture during a repeat run
   produced the 4-level cascade documented above.
4. **Alternative official tool**: checked `pip show safety` and `pip show
   osv-scanner` in the canonical venv — neither is installed
   (`WARNING: Package(s) not found`), and `where safety` / `where osv-scanner`
   found nothing on PATH. Per instructions, no new tool was installed. `pip-audit
   --help` was checked for an offline/local-only mode; `-l/--local` only filters
   *output* to locally-installed deps within `-r` mode and does not skip the
   ephemeral-venv resolution step, so it would not avoid the stall.
5. Total command wait time across all attempts: ~9 min of hard timeouts
   (300s + 240s) plus diagnostics, within the 25-minute overall budget; each
   individual attempt stayed within the 8-minute per-command cap.

## Evidence files created (all new, under `reports/quality/`, nothing overwritten)

- `reports/quality/BYS360_CAMPAIGN1B_DEPENDENCY_AUDIT_FINDINGS.md` (this file)

No `pip_audit_result_campaign1b.json` was created — both attempts to produce it
timed out before any output was written, so no such file exists. Fabricating an
empty/placeholder JSON claiming a completed scan would misrepresent a BLOCKED
result as a PASS, which is explicitly prohibited.

## Confirmation: zero dependency-file changes

`git status --short requirements.txt requirements-dev.txt` and
`git diff --stat requirements.txt requirements-dev.txt` both returned empty —
neither file was read-modified, upgraded, or pinned differently. No new package
was installed into the canonical venv.

## Recommendation for a future campaign (not acted on here — out of scope)

The actionable fix is environmental, not a dependency change: rebuild
`C:\bys360\project\.venv` from a non-Store Python (e.g. the `Python314` install
already on this machine at
`C:\Users\...\AppData\Local\Programs\Python\Python314\python.exe`, or any
python.org/official installer build), so that `sys._base_executable` no longer
resolves into the WindowsApps AppContainer sandbox. That is a change to the
protected canonical venv and was correctly out of scope for this agent.
