# BYS360 Database Migration — Shadow Rehearsal and Live Migration

Maintained implementation: [prepare_bys360_candidate.ps1](../../scripts/windows/prepare_bys360_candidate.ps1)
(`Test-CandidateMigrationHead`, `Test-ShadowSchemaContract`) and
[cutover_bys360_candidate.ps1](../../scripts/windows/cutover_bys360_candidate.ps1).
These are verified repository paths, not production validation. Current production
identity is recorded in [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md); dated observations
and revision values below remain historical evidence.

## Why shadow rehearsal exists

A real production cutover attempt on this application previously failed **at the live
migration step itself** — twice, for two different reasons (a PostgreSQL privilege gap on
`CREATEDB`, and later a `SECRET_KEY` validation error triggered by running the migration
from a staging directory whose `.env` resolution path didn't match production's). Both
failures happened safely — the live service was not yet stopped, the live tree not yet
replaced — precisely because the historical script's design put the shadow rehearsal
**before** any live-affecting step. The historical account cites
`scripts/windows/deploy_bys360_ec4e56b_production_v4.ps1`'s V3 and V4 hotfix notes; that
filename is retained as provenance, but the file is not present in the current repository.
The maintained
candidate/cutover model keeps the same principle: prove the migration works, against a real
copy of production data, under the real application role's real privileges, entirely
outside the live database, before the live database is ever touched.

## How shadow rehearsal proves a migration safe

1. **Admin-only shadow DB CREATE/DROP.** A disposable shadow database is created and later
   dropped using the PostgreSQL **admin** role (interactively authenticated, password never
   logged or written to any receipt — see `LIVE_INSTALLATION.md`). This is the only part of
   the rehearsal that uses admin privileges, and it exists only because `CREATE DATABASE` /
   `DROP DATABASE` are operations the application's own role is deliberately not granted
   (see below for why that matters).
2. **App-role-only restore.** The pre-cutover backup of the live database is restored into
   the shadow database using `pg_restore` as the **application role**, not admin, with
   `--no-owner --no-privileges`. This flag pair was added after direct testing found that a
   representative production dump contains postgres-owned functions/triggers, and restoring
   as the application role without it produces `pg_restore` exit code 1 (`ERROR: must be
   member of role postgres`) on the `ALTER FUNCTION ... OWNER TO postgres` statements in the
   dump. With `--no-owner --no-privileges`, the restore completes with **exit code 0**,
   identical table/row content, and the postgres-owned functions/triggers remain present
   and functionally usable — just now owned by the connecting application role instead of
   `postgres`, a disclosed, expected, rehearsal-only ownership difference. **The restore
   step must assert `exit_code == 0` strictly — do not accept a nonzero exit code just
   because tables appear to exist afterward** (an earlier version of this tooling did
   exactly that leniently, and it was tightened specifically because a nonzero exit can mask
   a genuine partial-restore problem).
3. **Migration as the real application role.** `flask db upgrade` is run against the shadow
   database using the **same application role and the same full production runtime
   configuration** the live application actually uses (via the production `.env` values
   injected into the shadow child process's environment — see `SECRETS_AND_PERSISTENCE.md`
   for exactly how and why this never involves copying a plaintext `.env` file anywhere). If
   the application role genuinely lacks a privilege the migration needs, this is exactly
   where that surfaces — safely, against disposable data.
4. **Target-revision + File Center 19/19 verification.** After the shadow migration, the
   rehearsal queries the shadow database's Alembic revision and confirms it matches the
   expected target, and separately confirms the expected count of File Center tables exist
   (19 — see below for how this number was verified). A mismatch on either check fails the
   rehearsal closed, and the shadow database is dropped regardless of outcome (success or
   failure) so no disposable state lingers.
5. **A fail-closed target check runs immediately before the shadow `flask db upgrade`
   invocation**, parsing the runtime `DATABASE_URL` actually in effect for that child
   process and refusing to proceed unless it resolves to the expected shadow database name
   and explicitly **not** the live database's name — logging only host/port/db/user, with
   the password always shown as `WITHHELD`. This exists specifically so that a
   configuration/environment-variable mistake in the rehearsal machinery itself cannot
   accidentally point the "shadow" migration at the real live database.

## The live migration step reuses the exact same code path — not a different one

Cutover's live migration step (`CUTOVER.md`, step 12) runs `flask db upgrade` through the
same application entry point, against the promoted candidate tree's own `migrations/`
directory, as the real application role — mechanically the same invocation shape the
shadow rehearsal already exercised during candidate preparation, just pointed at the real
database instead of the disposable shadow one. This is a deliberate design property, not
incidental: the entire value of shadow rehearsal depends on it actually being a rehearsal
of what will happen live, not a superficially similar but different mechanism. If a future
change to the candidate/cutover scripts ever causes live migration to diverge from the
shadow-rehearsal code path (different flags, different environment injection, different
Python entry point), the rehearsal stops proving what it claims to prove — that divergence
would be a design regression worth flagging, not a minor implementation detail.

## Three distinct revisions — do not conflate them

This document (and every other handover document) uses three explicitly different terms,
because a past internal report mixed two of them together and became self-contradictory.
Always name which one you mean:

- **`PRODUCTION_CURRENT_DB_REVISION`** — the Alembic revision the live production database
  is actually stamped at *right now*, before any cutover this document describes has run.
  As of this document's writing, that is `e0efcd07abf7` (operator-attested — this session has
  no live production access; see `CANDIDATE_PREPARATION.md`/`CUTOVER.md` for how cutover
  itself re-verifies this value against the real live database before doing anything).
- **`FILE_CENTER_MIGRATION_REVISION`** — the specific migration that adopted File Center's 19
  tables into Alembic ownership, `10858a18e9ac`
  (`migrations/versions/10858a18e9ac_adopt_file_center_schema_into_alembic_.py`). This is a
  fixed historical waypoint in the chain, not a moving target — it stays `10858a18e9ac`
  regardless of what gets added after it.
- **`RELEASE_TARGET_DB_REVISION`** — the single Alembic head the release currently being
  prepared will migrate the live database to. This is **not hard-coded anywhere in the
  candidate/cutover tooling** (`prepare_bys360_candidate.ps1`'s `Test-CandidateMigrationHead`
  resolves it dynamically from the candidate's own `migrations/` tree via Alembic's
  `ScriptDirectory.get_heads()`, asserts there is exactly one, and binds it into
  `CANDIDATE_READY.json`'s `MIGRATION_HEAD` field) — it is whatever the actual chain
  resolves to at candidate-preparation time. Do not assume it equals
  `FILE_CENTER_MIGRATION_REVISION`; treat the next section as instructions for how to check,
  not as a permanent value.

## The current release target — verified directly, not assumed

It was re-verified directly against this worktree's actual `migrations/` directory, using
the exact command a future operator is expected to run (the same one
`Test-CandidateMigrationHead` runs programmatically):

```
cd C:\bys360\project
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:FLASK_APP = "wsgi.py"
& "C:\bys360\project\.venv\Scripts\python.exe" -m flask db heads
```

**Actual observed result (2026-08-25, against the `phase5-critical-lint-clean` worktree at
commit `ec4e56bd9bab2ce59e9543fc647f55dffd37d94b` plus the schema-contract-drift-closure
migration described below, run against a fresh in-memory SQLite database since no
`DATABASE_URL` was configured in this environment — `config.py` falls back to
`sqlite:///:memory:` when `DATABASE_URL` is unset, which is why this command is safe to run
without touching any real database):**

```
c51c29032d4f (head)
```

Exit code `0`, single head, no ambiguity. `c51c29032d4f`
(`migrations/versions/c51c29032d4f_close_performance_and_messaging_schema_.py`, `down_revision
= 10858a18e9ac`) closes a real, independently-verified schema-contract gap:
`app/bootstrap/schema_contract.py` requires 15 columns across `performance_evaluations`
(10), `personnel_leaves` (1), `attendance_exceptions` (1), and `message_threads` (3) that no
earlier migration in this chain ever created — they existed on real/legacy databases only via
a raw-SQL self-heal path (`app/schema_guard_patches.py`,
`app/schema_guard_core_maintenances.py`) that is explicitly disabled by default in
production (`AUTO_REPAIR_SCHEMA=False`). A database built purely via `flask db upgrade` from
empty previously reached head and then failed `STRICT_SCHEMA_CHECK` at boot (the default for
`APP_ENV` in `{production, staging}`) with `RuntimeError: Şema doğrulama başarısız`, listing
all 15 as missing. `c51c29032d4f` adds exactly those columns, matching the real SQLAlchemy
model definitions and the legacy self-heal SQL's types/defaults/nullability exactly (verified
column-by-column, not assumed), is idempotent against a database that already has some or all
of them (guarded `ADD COLUMN IF NOT EXISTS`-equivalent checks via `sa.inspect`), backfills the
three `NOT NULL` columns to the same default value the legacy self-heal path already used
(`'taslak_1_amir'` / `'partial'`), and never drops data — its downgrade is an intentional
no-op, matching this project's established convention for adopted columns that may carry real
institutional data.

**Candidate preparation now also runs an explicit schema-contract gate** (`prepare_bys360_
candidate.ps1`'s `Test-ShadowSchemaContract`, added alongside `c51c29032d4f`) that imports and
calls the application's own `app.bootstrap.schema_contract.get_expected_schema()` /
`app.bootstrap.schema_validation.validate_required_schema()` against the freshly-migrated
shadow database — not a reimplementation, the actual functions `create_app()` runs at boot —
and fails candidate preparation closed if anything is missing. This exists specifically so
this class of drift (a column the contract expects but no migration creates) is caught during
candidate preparation, before a live cutover, for this migration chain and any future one.

**Re-run this exact command against whatever source tree and commit is actually being
deployed before trusting this number** — `RELEASE_TARGET_DB_REVISION` is expected to change
as new migrations are added over time, and this document's job is to show you how to check,
not to be the permanent source of truth.

`flask db current` against that same fresh database correctly returned nothing (no revision
stamped yet) — expected behavior for a database that has never been migrated, not an error.

### The "guarded exception" log lines are expected on a fresh/empty database

Running `flask db heads` (or any command that triggers `create_app()`, since Flask-Migrate
commands go through the normal app factory) against a fresh/empty database produces several
`ERROR`-level log lines like:

```
[...] ERROR in menu_profile_access: BYS360 V6B guarded exception | file=app/services/settings/menu_profile_access.py | line=190
...
sqlite3.OperationalError: no such table: user_menu_permissions
```

and an equivalent one for `role_menu_defaults`. **This is pre-existing, intentional
defensive-guard behavior in the application's own menu/permission bootstrap code, triggered
at `create_app()` time whenever those two tables don't exist yet — it is not a migration
defect, and it is not specific to the candidate/cutover tooling.** It appears because the
app factory tries to build an effective menu-permission context as part of normal startup,
and gracefully logs (rather than crashing on) the case where the relevant tables aren't
present yet. On a real production database that has already been migrated at least once,
these tables exist and this log noise does not appear. When verifying a *fresh* database
(for example, immediately after `flask db upgrade` on a brand-new environment, before any
role/menu data has been seeded), expect to see these lines and do not treat them as a
migration failure signal on their own — but do treat any *other*, unexplained ERROR/CRITICAL
line as worth investigating (see the log-scan pattern discussion in `CUTOVER.md` step 19).

## File Center table count — verified directly, not assumed

The historical script's `FILE_CENTER_TABLES` receipt field and its `19/19` verification
refer to the tables defined by `app/models/file_center_models.py`. Verified directly in this
session by reading that file's own `__tablename__` declarations (19 distinct tables,
matching the historical script's hard-coded expectation of 19):

```
file_storage_folders, file_storage_items, file_transfers, file_transfer_items,
file_transfer_recipients, file_share_links, file_requests, file_request_uploads,
file_download_logs, file_access_logs, file_quota_usage, file_security_scans,
file_audit_logs, file_quota_policies, file_upload_sessions, file_upload_chunks,
file_center_mail_logs, file_center_role_permissions, file_center_settings
```

This matches the count already used consistently elsewhere in this repository's existing
handover documentation (`BYS360_FINAL_HANDOVER_AND_SUSTAINABILITY.md`,
`BYS360_FEATURE_COVERAGE_MATRIX.md`) — no discrepancy found. The migration named
`migrations/versions/10858a18e9ac_adopt_file_center_schema_into_alembic_.py` is what brings
these 19 tables under Alembic's ownership (they existed as application tables before that
migration; the migration is an ownership adoption, not a from-scratch creation, per the
historical script's own description: "adopts File Center's 19 tables into Alembic
ownership").

## What constitutes success and failure here

- **Success**: shadow rehearsal reaches the target revision with 19/19 File Center tables
  present, using `exit_code=0` throughout (restore, migration); the shadow database is
  dropped cleanly afterward regardless. Live migration (during cutover) reaches the same
  target revision with the same 19/19 count, using the identical code path already proven
  in rehearsal.
- **Failure**: any nonzero exit code from restore or migration, any revision mismatch, or
  any File-Center-table-count mismatch fails the relevant phase closed. A shadow-rehearsal
  failure leaves the live database completely untouched (see `CANDIDATE_PREPARATION.md`). A
  live-migration failure during cutover is a different, more serious situation — see
  `DISASTER_RECOVERY.md` for what state the database is actually in afterward and when NOT
  to retry.
