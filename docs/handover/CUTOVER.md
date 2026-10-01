# BYS360 Cutover

Audience: an operator using the maintained
[cutover_bys360_candidate.ps1](../../scripts/windows/cutover_bys360_candidate.ps1), only
after [CANDIDATE_PREPARATION.md](CANDIDATE_PREPARATION.md)'s process has produced a valid
`CANDIDATE_READY.json`. Review the script's actual parameters for the chosen source
revision; this document is not authorization to execute production operations.

## Why cutover is intentionally short

Every slow, failure-prone, or exploratory step — extracting the release package, resolving
Python interpreters, installing dependencies, rehearsing the database migration against a
disposable shadow database, boot-testing the candidate application — already happened
during candidate preparation, against a tree that was never live-serving. By the time
cutover runs, none of that is unknown or unproven anymore. Cutover's job is narrow and
mechanical: **swap which tree is live, apply the already-rehearsed migration for real, and
verify the result** — not build, not download, not shadow-test anything. This is the direct
structural fix for the failure mode that motivated this whole redesign: the historical
monolithic script stopped the live task and deleted the live tree before fully proving the
new dependency set was installable at all (the historical account cites
`scripts/windows/deploy_bys360_ec4e56b_production_v4.ps1`; that filename is retained as
provenance, but the file is not present in the current repository).
Keeping cutover short means the live service's downtime window is short too — by design,
not by accident.

## The hard gate: cutover refuses to run without a valid, matching `CANDIDATE_READY.json`

Cutover's first real action is to load and verify `CANDIDATE_READY.json` from the
candidate directory it is pointed at. If that file is missing, malformed, or any of its
bound fields (source SHA, package SHA256, dependency-lock hash, migration head — see
`CANDIDATE_PREPARATION.md`) do not match what cutover independently observes about the
release package and the candidate directory on disk, cutover must fail closed immediately,
before touching the live service in any way. There is deliberately no flag to bypass this
check — a candidate that was never proven ready is never an acceptable cutover target,
regardless of operator urgency. This mirrors the fail-closed pattern already established in
the historical script (`Set-StrictMode -Version Latest`, `$ErrorActionPreference = 'Stop'`,
every phase wrapped so a failure anywhere stops the run and writes a receipt naming the
phase/reason, never silently proceeding to a later phase).

## The cutover flow (phase summary)

The following sequence summarizes the cutover design. The maintained
[cutover_bys360_candidate.ps1](../../scripts/windows/cutover_bys360_candidate.ps1) defines
the executable phases, function names, and log messages for the chosen source revision.
Check those definitions before operational use; this summary does not establish that a
cutover has been validated on the production host.

1. **Verify receipt** — load and validate `CANDIDATE_READY.json` as described above (the
   hard gate).
2. **Verify live identity** — confirm this host is actually the expected production host
   (hostname match, matching the historical script's own `PRECHECK` step) and that the
   currently-live `C:\bys360\project\` tree's source SHA matches what the receipt expects as
   the "previous" state, so cutover never runs twice against a tree it has already replaced.
3. **Verify DB revision** — query the live database's current Alembic revision and confirm
   it matches the expected pre-migration revision (fail closed on mismatch, matching the
   historical script's `AllowDbRevisionMismatch`-gated pattern for the one legitimate
   recovery/rerun exception).
4. **Final backup** — `pg_dump` the live database to `C:\bys360\backups\`, verified non-empty
   before proceeding (see `DATABASE_MIGRATION.md` and `DISASTER_RECOVERY.md` — this backup
   is never deleted by any part of this process, including rollback).
5. **Preserve `.env`/instance** — read the live `.env` file's contents and the live
   `instance\` directory's contents into memory/a safe temporary holding location before
   anything is moved, so they can be restored onto the promoted candidate tree afterward
   (see `SECRETS_AND_PERSISTENCE.md` for why these are never copied as files sitting inside
   the release package or the candidate directory itself).
6. **Stop task** — `Stop-ScheduledTask` on "BYS360 Live Waitress 80". This is the first
   moment cutover actually affects the live-serving state, and it happens only after every
   prior gate has passed.
7. **Confirm port down** — actively verify nothing is still listening on port 80 before
   proceeding (a task reporting "stopped" is not proof the process has actually released the
   port; the historical script's own post-start check — waiting up to 40 seconds for port 80
   to open — is the mirror image of this check).
8. **Move current to `previous\`** — move (not copy, not delete) the current
   `C:\bys360\project\` tree to `C:\bys360\previous\<timestamp_SHA>\`, guarded by an
   explicit safe-deletion/safe-move target check (the historical script's
   `Assert-SafeDeletionTarget` — refusing to act unless the resolved path exactly equals the
   expected `ProjectRoot`, is at least 3 path segments deep, is not a drive root or the
   `C:\bys360` root itself, and ends in `\project` — is the direct model for this guard, and
   should be present in whatever function performs this move in the actual script).
9. **Promote candidate** — move (not copy) `C:\bys360\candidate\<SOURCE_SHA>\` into
   `C:\bys360\project\`.
10. **Restore `.env`/instance** — write the preserved `.env` contents and `instance\`
    contents back onto the now-promoted tree. This is the only point at which the live
    secrets ever touch the new tree's filesystem, and only because they were already on this
    host, preserved from the tree that was just moved aside — never introduced from the
    release package.
11. **Verify identity** — re-confirm the promoted tree's source SHA matches the receipt's
    expected value, now that it is sitting at `C:\bys360\project\`.
12. **Live migration** — run `flask db upgrade` against the real, live database, as the real
    application role, using the exact same migration code path the shadow rehearsal already
    proved works during candidate preparation (not a different code path — see
    `DATABASE_MIGRATION.md`).
13. **Verify revision** — confirm the live database's Alembic revision now matches the
    expected target revision.
14. **File Center 19/19** — confirm the expected count of File Center tables exist
    post-migration (19, as independently verified in this worktree — see
    `DATABASE_MIGRATION.md` for the exact count and how it was checked). A count that
    doesn't match must fail closed here, before the application is ever started, matching
    the historical script's own `LIVE_MIGRATION_FAILED` behavior on a File-Center-table
    mismatch.
15. **Start task** — `Start-ScheduledTask` on "BYS360 Live Waitress 80".
16. **Local health 200** — poll `http://127.0.0.1/healthz` with the correct `Host` and
    `X-Forwarded-Proto` headers until it returns `200` (bounded wait, not infinite).
17. **Public health 200** — issue the equivalent check against
    `https://bys360.canakkaletarihialan.gov.tr/healthz` from the host itself. Environments
    where outbound/LB access from the host is not expected to work need an explicit,
    deliberate opt-out for this step (the historical script's `-SkipPublicHealthCheck`
    switch is the model — an explicit flag, never a silent skip).
18. **Smoke** — read-only functional checks: confirm the `file_center` and `portal`
    blueprints are actually registered in the running application, and that File Center's
    guest/chunk endpoints are present in the URL map. No guest links or other
    state-mutating side effects are created by this step.
19. **Security/log scan** — scan the fresh startup log for real ERROR/CRITICAL records
    (using a level-aware pattern, not a bare substring match on the words "error"/
    "critical" — a bare substring match would false-positive on benign text like
    "0 critical findings"; see `Test-LogForRealErrors` in the historical script for the
    exact pattern set, including the pipe-delimited `| ERROR |` / `| CRITICAL |` format used
    by this application's own logging formatter). Expect the pre-existing, harmless
    "guarded exception" log lines about `role_menu_defaults`/`user_menu_permissions` **only**
    on a genuinely fresh/empty database — see `DATABASE_MIGRATION.md` for why those specific
    lines are not a migration defect. A real, unexpected ERROR/CRITICAL hit here should be
    investigated, not waved through.
20. **Receipt** — write a success receipt naming the source SHA, package hash, DB revision
    before/after, File Center table count, health-check results, and security-scan result,
    into `C:\bys360\deploy_logs\`, mirroring the historical script's own receipt shape
    (`$Script:Receipt` in `deploy_bys360_ec4e56b_production_v4.ps1`, a historical filename
    not present in the current repository). The maintained cutover script contains its
    own `$Script:Receipt` record.

## When live is actually stopped, and for how long

The live Scheduled Task is stopped only starting at step 6 and is expected to be running
again by step 15 — every step before 6 and after 15 operates without the service being
down. By design, everything that could plausibly take a long time or fail unpredictably
(dependency install, migration rehearsal, health boot testing) already happened during
candidate preparation, before step 1 of this flow even begins. The downtime window this
flow produces should therefore be dominated by steps 6–15 only: stop task, move two
directory trees, restore two small files, run one already-rehearsed migration, start task,
wait for the port to open. This is the direct improvement over the historical model, where
the live tree could sit deleted for an unbounded, failure-dependent amount of time while
later phases (venv build, migration) were still being attempted.

## What constitutes success vs. failure here

- **Success**: all 20 steps complete, ending in a success receipt. The live application is
  now running the candidate's source SHA, the database is at the expected target revision
  with 19/19 File Center tables, and both local and public health checks returned 200.
- **Failure**: any step fails closed, producing a failure receipt that names the exact
  phase and reason (matching the historical script's `FAILURE_RECEIPT.txt` shape — Phase,
  Timestamp, Reason, Log path, Deploy log dir, and an explicit statement that no further
  phases ran). **Read `DISASTER_RECOVERY.md` before retrying** — which phase failed
  determines what state the system is actually in and whether a bare retry is even safe;
  this document does not repeat that guidance here.
