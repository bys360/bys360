# BYS360 Candidate Preparation

Audience: an operator using the maintained
[prepare_bys360_candidate.ps1](../../scripts/windows/prepare_bys360_candidate.ps1), after
[LIVE_INSTALLATION.md](LIVE_INSTALLATION.md)'s prerequisites are satisfied. Review the
script's actual parameters for the chosen source revision; this document is not
authorization to execute production operations.

## Why this phase exists

The deployment model this document describes replaces a single monolithic script that
stopped the live Scheduled Task and deleted the live application tree **before** it had
fully proven the new dependency set was even installable — a real production run reached
that far and failed mid-venv-build with the service already down and the old tree already
gone (the historical account cites
`scripts/windows/deploy_bys360_ec4e56b_production_v4.ps1`; that filename is preserved as
provenance, but the file is not present in the current repository). Candidate preparation's
entire purpose is to do **all** of the
risky, slow, failure-prone work — extraction, dependency install, database-migration
rehearsal, health boot — against a tree that is never live-serving, so that by the time
cutover touches the live service at all, everything it depends on has already been proven
to work on this exact host.

## What "never touches the live service" means concretely

Candidate preparation:

- Extracts the release ZIP into `C:\bys360\candidate\<SOURCE_SHA>\`, not into
  `C:\bys360\project\`.
- Builds a brand-new virtual environment inside the candidate directory, not by touching
  `C:\bys360\project\.venv\`.
- Rehearses the database migration against a **disposable shadow database**, not the live
  database — the live database is not written to during this phase, by design (see
  `DATABASE_MIGRATION.md` for exactly how the shadow rehearsal works and why it uses the
  application's own limited-privilege role for everything except shadow-DB CREATE/DROP).
- Boots the candidate application on a **non-live port**, never binding port 80, so no
  request that would otherwise reach the live Waitress instance can ever be routed to the
  candidate by accident.
- Never calls `Stop-ScheduledTask` on "BYS360 Live Waitress 80", never touches
  `C:\bys360\storage`, `C:\bys360\local_storage`, or the live `.env`/`instance\` in place.

If any step of preparation fails, the live service is completely unaffected — there is
nothing to roll back, because nothing live was ever touched. This is the core design
improvement over the historical model, where a mid-process failure could leave the service
already stopped and the old tree already gone.

## Offline dependency install — no PyPI access required

Candidate preparation installs Python dependencies with:

```
pip install --no-index --find-links wheelhouse -r requirements.lock
```

- `--no-index` refuses to consult PyPI (or any index) at all.
- `--find-links wheelhouse` points pip at the pre-built offline wheel bundle
  (`build/wheelhouse/`, produced ahead of time by
  [scripts/release/build_bys360_wheelhouse.py](../../scripts/release/build_bys360_wheelhouse.py))
  shipped alongside the release. `build/wheelhouse/` is generated output, not a tracked
  repository directory.
- [requirements.lock](../../requirements.lock) pins every dependency,
  direct and transitive, to an exact version — this is deliberately a stricter artifact than
  the repository's own `requirements.txt` (24 top-level pins as of this writing; the lock
  file is expected to enumerate the full resolved dependency graph).

The practical implication for an operator: **if candidate preparation fails at the
dependency-install step, the fix is never "let it reach the internet."** The production host
is expected to have zero PyPy/PyPI network access during this phase, by design, matching
the offline/air-gapped operating reality of a municipal production host. A missing wheel
means the wheelhouse bundle itself is incomplete for this host's Python/platform
combination and needs to be rebuilt on a machine that does have network access — it is not
something to work around locally on production.

## `CANDIDATE_READY.json` — what it means and what it binds

Candidate preparation's successful output is `CANDIDATE_READY.json` inside the candidate
directory. The maintained preparation script writes that receipt; the maintained
[cutover script](../../scripts/windows/cutover_bys360_candidate.ps1) validates it through
`Assert-ValidCandidateReceipt` before promotion. Treat it as the candidate-readiness record
(see [CUTOVER.md](CUTOVER.md)). At minimum it
must bind together:

- **Source SHA** — the exact git commit the candidate was built from, matching the release
  package's own manifest `source_sha` (see `RELEASE_VERIFICATION.md` for how the package
  manifest itself is verified before this point).
- **Package SHA256** — the release ZIP's own hash, so cutover can confirm the candidate was
  built from the exact package that was hash-verified, not a different or tampered one.
- **Candidate directory** — the absolute path under `C:\bys360\candidate\<SOURCE_SHA>\`
  that cutover is expected to promote; this closes off any ambiguity about which of
  possibly several prepared-but-not-yet-cut-over candidates is the one being promoted.
- **Dependency-lock hash** — a hash of `requirements.lock` (or equivalent), so a candidate
  built from a stale or hand-edited lock file cannot silently pass as ready.
- **Migration head** — the Alembic head revision the candidate's own `migrations/` tree
  resolves to, confirmed during preparation exactly the way `DATABASE_MIGRATION.md`
  describes verifying it manually (`flask db heads`), so cutover can assert the live
  migration is moving to the same target the candidate was actually rehearsed against.

Preparation also runs an explicit **schema-contract check** against the freshly-migrated
shadow database — not a table-count heuristic, but the application's own
`app.bootstrap.schema_contract.get_expected_schema()` /
`app.bootstrap.schema_validation.validate_required_schema()`, the exact functions
`create_app()` runs at boot when `STRICT_SCHEMA_CHECK` is on. This exists because reaching
the correct Alembic head is necessary but not sufficient — a migration chain can resolve to
the right revision while still leaving individual columns the application's runtime contract
requires. See `DATABASE_MIGRATION.md` for the concrete gap this closed and how it was found.

If any of these fields is missing, malformed, or does not match what cutover independently
observes about the live host and the release package at cutover time, cutover must fail
closed rather than proceed on a partial or stale receipt.

## What "candidate health boot on a non-live port + `/healthz`" proves

Before `CANDIDATE_READY.json` is written, preparation is expected to actually start the
candidate application process (using the candidate's own freshly-built venv) bound to a
non-live port, and issue a real HTTP request to its `/healthz` endpoint, expecting `200`.
This proves — on this exact host, with this exact dependency set, this exact database
migration state, and this exact configuration-loading path — that the application actually
starts and serves a request, not merely that `pip install` succeeded and the Python syntax
is valid. The historical script's own post-cutover local health check
(`http://127.0.0.1:$AppPort/healthz` with the correct `Host`/`X-Forwarded-Proto` headers) is
the direct model for this — candidate preparation's contribution is proving the same thing
is possible **before** the live service is ever stopped, not only after.

A candidate that fails its own health boot must not produce a `CANDIDATE_READY.json` at
all, and cutover's hard gate (see `CUTOVER.md`) means there is nothing for an operator to
override here short of investigating and re-running preparation — there is deliberately no
"skip the health check and cut over anyway" flag, matching the fail-closed design pattern
used throughout the historical script (`Set-StrictMode -Version Latest`,
`$ErrorActionPreference = 'Stop'`, a failure receipt naming the phase/reason on every exit
path).

## What success and failure look like here

- **Success**: `CANDIDATE_READY.json` exists under
  `C:\bys360\candidate\<SOURCE_SHA>\`, its fields match the release package and the host's
  actual dependency-lock hash, and the candidate's own health boot returned `200` from
  `/healthz`. The live service was never touched; it is still running the previous release
  throughout.
- **Failure**: no `CANDIDATE_READY.json` is written (or an existing one from a prior,
  now-invalid attempt must not be trusted — verify its `source_sha`/hash fields against the
  current release package before assuming it is still valid). The live service remains
  completely unaffected regardless of which preparation step failed — there is no partial,
  live-visible state to clean up. Re-run preparation after fixing the underlying cause
  (missing wheel, migration rehearsal failure, health-boot failure); do not attempt cutover
  against a candidate directory that never produced a valid ready receipt.
