# BYS360 Live Installation — Host Prerequisites

Audience: a system administrator with no prior BYS360 knowledge, no GitHub access, and no
tribal knowledge, who has been handed the FULL release ZIP and the production secrets/
configuration values out of band (paper, password manager, or a separate secure channel —
never inside the ZIP itself).

Scope note: this document describes what a fresh production host needs **before** any
candidate/cutover script is ever run. It does not describe how the candidate/cutover/
rollback scripts themselves work — see [CANDIDATE_PREPARATION.md](CANDIDATE_PREPARATION.md),
[CUTOVER.md](CUTOVER.md), and [ROLLBACK.md](ROLLBACK.md) for those. The maintained scripts
are present in the repository:
[prepare_bys360_candidate.ps1](../../scripts/windows/prepare_bys360_candidate.ps1),
[cutover_bys360_candidate.ps1](../../scripts/windows/cutover_bys360_candidate.ps1), and
[rollback_bys360_candidate.ps1](../../scripts/windows/rollback_bys360_candidate.ps1).
Use their actual parameter lists and prerequisite checks for the chosen source revision;
file availability is not production validation or authorization to execute them.

## 1. Operating system and identity

- Windows Server (the same edition and patch level as the currently-live host). The
  historical deployment tooling (`scripts/windows/deploy_bys360_ec4e56b_production_v4.ps1`,
  a retained historical filename, not a file present in the current repository)
  hard-codes an expected `$env:COMPUTERNAME` of `CATAB-BYS360` and a public hostname of
  `bys360.canakkaletarihialan.gov.tr`. Any new host must be identified explicitly to
  whichever script replaces that identity check; do not assume the same computer name is
  reusable on different hardware.
- The operator account used to run PowerShell deployment scripts must run **elevated**
  (Administrator). The historical script fails closed (`PRECHECK_FAILED`) if the session is
  not elevated. The maintained candidate/cutover/rollback scripts contain
  `Test-HostPrerequisites`; review those checks and the approved target identity before use.

## 2. Python 3.12 — exact interpreter resolution, no bare `python`/`py` on PATH

Do not rely on a bare `python` or `py` command being on the production host's `PATH`. This
is not a theoretical concern: a real production cutover attempt on this host failed
specifically because `python` was not on `PATH` (historically attributed to the V1→V2
hotfix note in `deploy_bys360_ec4e56b_production_v4.ps1`; that file is not present in the
current repository). The load-bearing lesson, which the maintained
candidate/cutover tooling is built to preserve, is:

- Resolve **absolute** interpreter paths once, early, before any mutation of
  `C:\bys360\project` — never call a bare `python`/`py` inside a phase that does real work.
- Two distinct interpreters matter and must not be confused:
  - The **current/live venv's own interpreter**
    (`C:\bys360\project\.venv\Scripts\python.exe`) — has Alembic/Flask/etc. already
    installed, and is the only thing that can safely run a staged-package Alembic-head
    check before a new venv exists.
  - A **bare Python 3.12.x base interpreter**, used only to bootstrap a brand-new venv
    (for the candidate, and historically for the shadow-rehearsal database check too).
    The historical script derives this from the current venv's own
    `sys._base_executable`, falling back — resolution only, never invoked directly for
    real work — to `py -3.12 -c "import sys; print(sys.executable)"` if that derivation is
    unavailable.
- Python 3.12 is not currently expressed as a formal `python_requires` pin inside
  `requirements.txt` in this repository; the 3.12 requirement is an **operational fact**
  about how the existing venv was built (confirmed here by its bytecode cache directories
  using the `cpython-312` tag) and about what the historical deploy script explicitly
  checks for (`Python 3\.12\.` version-string match) before accepting a base interpreter.
  Verify the candidate-preparation script pins/validates the same version before trusting a
  host with a different Python 3.12.x patch release, or a different minor version
  entirely, to build a working candidate.

## 3. PostgreSQL 15

- PostgreSQL 15 server, running as a Windows service (the historical script checks for a
  service literally named `postgresql-x64-15`, falling back to the first service whose name
  starts with `postgresql*`).
- Client tools (`pg_dump.exe`, `pg_restore.exe`, `psql.exe`) installed at a known path —
  historically `C:\Program Files\PostgreSQL\15\bin`. Candidate preparation's shadow-DB
  rehearsal and cutover's live backup/migration both depend on these three binaries being
  present at whatever path the new scripts are configured to look for.
- Two distinct PostgreSQL roles matter and must not be confused:
  - An **application role** (historically `bys_user`) — this is the role the running
    application actually authenticates as via `DATABASE_URL`. It deliberately does **not**
    have `CREATEDB`. Do not grant it that privilege; the shadow-rehearsal design depends on
    the application role being unable to create/drop databases, so that the rehearsal
    genuinely proves what the live migration will do under the real, limited application
    privileges.
  - An **admin role** (historically `postgres`) — used only for the two lifecycle
    operations the application role cannot do itself: `CREATE DATABASE` / `DROP DATABASE`
    for the disposable shadow database used during candidate verification. The admin
    password is never a script parameter (it would leak into shell history and process
    listings) — it is prompted for interactively, once, exactly when the shadow-rehearsal
    phase begins, and is never written to any log or receipt.

## 4. The Windows Scheduled Task — "BYS360 Live Waitress 80"

- The live application runs under a Windows Scheduled Task named
  **`BYS360 Live Waitress 80`**, serving on port 80 via Waitress
  (`WAITRESS_THREADS` is a configurable env var; see `.env.example`).
- This document's tooling **cuts over an existing task**; it does not create one from
  scratch. If you are standing up a genuinely new host, the Scheduled Task itself (its
  triggers, its "run whether user is logged on or not" setting, its principal/run level)
  must be created and verified separately, before the first candidate cutover is ever
  attempted against it. The historical script warns (non-fatally) if the task's `RunLevel`
  is not `Highest` — this is a pre-existing, previously-documented gap in the installer, not
  something the candidate/cutover tooling fixes; verify manually whether it matters for
  your environment.
- `run_server.py` reconfigures stdout/stderr to UTF-8 before printing anything, specifically
  because a Scheduled-Task-redirected console defaults to the system ANSI codepage on
  Windows, which cannot encode the Turkish characters used in this application's own
  startup messages — an unhandled `UnicodeEncodeError` here has, on this exact host, killed
  the process before Waitress ever bound the port. Do not "simplify" this away when
  reviewing or re-implementing startup code.

## 5. Required directory layout

```
C:\bys360\
    project\                 current active application (live) — the ONLY tree the
                              Scheduled Task actually serves from
    candidate\<SOURCE_SHA>\   fully prepared next application (never live-serving;
                              built and verified entirely before cutover touches
                              anything live)
    previous\<timestamp_SHA>\ previous app tree, retained after a cutover for rollback
    storage\                 persistent external storage — File Center and other
                              on-disk artifacts; NEVER touched by candidate prep or
                              cutover
    local_storage\           persistent local/on-host storage — same rule: never
                              touched by candidate prep or cutover
    backups\                 pg_dump backups (pre-cutover, and any ad hoc backups)
    logs\                    live application log file(s), e.g.
                              bys360_live_waitress_80.log
    releases\                retained FULL release ZIPs (current and previous), used
                              for release-artifact-based recovery, not filesystem
                              copies
    deploy_logs\              per-run deployment logs and receipts, one directory per
                              run, timestamped
```

Everything under `storage\`, `local_storage\`, and the PostgreSQL database itself is
**persistent, external application state** — see `SECRETS_AND_PERSISTENCE.md` for the full
contract. None of it lives inside `project\`, `candidate\`, or `previous\`, and none of it
is ever recreated, overwritten, or deleted by a candidate build or a cutover.

## 6. What must be supplied externally vs. what comes from the package

| Must be supplied externally (never in the release ZIP) | Comes from the release package |
|---|---|
| The real `.env` file (production `DATABASE_URL`, `SECRET_KEY`, mail/SMTP credentials, third-party API tokens — see `SECRETS_AND_PERSISTENCE.md`) | `app/`, `migrations/`, `requirements.txt`, `wsgi.py`, `run_server.py`, `config.py`, `DEPLOYMENT.md` (the release builder's own `REQUIRED_PACKAGE_PATH_PREFIXES` gate refuses to accept a package missing any of these) |
| The production PostgreSQL role credentials (application role, and — only when a candidate is being verified — the interactively-supplied admin role password) | `.env.example` / `.env.docker.example` — templates only, every value blank; **never** a real `.env` (the release builder's `ALLOWED_ENV_TEMPLATE_BASENAMES` allowlist is `{.env.example, .env.docker.example}` — nothing else matching an `.env*` name pattern is ever permitted into a package; there is currently no `.env.production.example` in this repository) |
| The `instance/` directory's actual runtime contents, if any exist on the current live host | The application source tree itself (Python code, templates, static assets, Alembic migration scripts) |
| PostgreSQL 15 server + client tools, installed and licensed for this host | [requirements.lock](../../requirements.lock) and the offline wheelhouse bundle built with [build_bys360_wheelhouse.py](../../scripts/release/build_bys360_wheelhouse.py). The generated `build/wheelhouse/` bundle must be supplied with the release; it is not a tracked repository directory. |
| The Windows Scheduled Task "BYS360 Live Waitress 80" itself (pre-existing; this tooling cuts over an existing task, it does not create one) | — |

## 7. Confirming this document's own claims

The migration head and File Center table count cited across this handover set were verified
directly in this worktree/session, not copied from another document without checking (see
`DATABASE_MIGRATION.md` for the exact commands and full output). Re-run those same
verification commands against the actual host before treating any specific revision ID or
table count as current — schema state changes over time, and this document describes the
mechanism, not a permanently-fixed number.
