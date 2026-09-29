# BYS360 Pre-push Migration Review — 2026-09-29

Branch `fix/schema-runtime-ddl-wave1` (local only, no upstream). Base `ebd5ff08` is the default-branch docs head, **not
production**. The deployed production application is `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9`
(tag `bys360-prod-2026.09.28-67f2a29d`); nothing in this review touched production.

Scope: the two migrations added by this remediation program, `w1c5a7d2e9b4` and `w2d8e1f4a6c3`. This is a read/test
review: no migration, model or application file was changed while preparing it.

## 0. Branch identity and history sanitization

| | Before | After |
|---|---|---|
| HEAD | `66cff8f3e4d04c2eeafa97e452410fb80416346e` | `b3ef3012f240a78c653a70ac17d980d1dafdd41a` |
| Final tree | `436b69c4c1e618b3abb9a1463f4698963e390a2d` | `436b69c4c1e618b3abb9a1463f4698963e390a2d` (identical) |
| Commits since `ebd5ff08` | 30, linear, unsigned | 30, linear, unsigned |

Two local-only rewrites, both approved by the owner on 2026-09-29, removed a personal Windows 8.3 short directory name:

1. **Commit message** of the File Center test commit: the name was replaced by "a Windows 8.3 short
   temporary-directory path".
2. **Test-file content** of 7 intermediate commits: the same commit had also added the name to a docstring in
   `tests/behavior/test_file_center_anonymous_guest_access_contract.py`, which a later commit replaced by the neutral
   `ABCDEF~1`. Only that one docstring phrase changed in those 7 commits; no code line changed.

Every commit keeps its subject, author, committer and dates. The final tree is byte-identical, so the tree tested by the
full broad suite (`435c2e64`, the tree of the last code commit) exists unchanged in the new history.

| Old SHA | New SHA | Tree | Subject |
|---|---|---|---|
| `2957532f` | `d9451d01` | docstring phrase only | test: compare resolved paths in file center isolation checks |
| `3a910441` | `77316b70` | docstring phrase only | docs: extend authorization matrix review to messaging and notifications |
| `9c896b65` | `9b8b2fa3` | docstring phrase only | fix: inspect before altering in the period center provisioners |
| `73fc2c52` | `5002d200` | docstring phrase only | fix: answer missing faz2 surveys and bulletins with a redirect, not a 500 |
| `c7b314d0` | `b9cbd332` | docstring phrase only | fix: return 404 for a missing period on the faz8 scope check |
| `78b7c010` | `ce8edefc` | docstring phrase only | docs: record overnight 01:45 checkpoint |
| `eff84e80` | `65321446` | docstring phrase only | test: exercise runtime-schema provisioning in the postgres gate |
| `0f8930d3` | `d73a095b` | identical | test: keep the personal account name out of the file center test |
| `ec724139` | `412d7da0` | identical | docs: record migration-only probe and provisioner evidence |
| `265f8754` | `d6fc8e7a` | identical (`435c2e64`, fully tested) | test: mark new fixture passwords as test values for the secret gate |
| `66cff8f3` | `b3ef3012` | identical (`436b69c4`) | docs: record overnight final state |

Commits before `2957532f` kept their SHAs. After the rewrite, scans of all 30 commit messages, all author and committer
identities, and the added lines of **every individual commit** found 0 personal names, 0 user-profile paths and
0 host names. The remaining hits are neutral fixtures: `example.gov.tr` e-mail addresses, fabricated IP addresses in
the health-check test, `...Test1!` fixture passwords and `ABCDEF~1`.

## 1. Verdicts

| Migration | Verdict | Reason |
|---|---|---|
| `w1c5a7d2e9b4` | **SAFE** | Additive and conditional. Types match the runtime DDL that created these columns before the branch. It is a no-op where the columns exist. |
| `w2d8e1f4a6c3` | **SAFE** for upgrading production | Additive and create-if-absent. On the production-shaped fixture it made 0 schema changes and left all rows byte-identical. On a fresh install it reproduces the ORM exactly, but some fresh-install shapes are unproven against production (§7). |

Destructive production operations: **none**.

## 2. `w1c5a7d2e9b4_adopt_user_and_period_runtime_columns`

| Item | Finding |
|---|---|
| revision / down_revision | `w1c5a7d2e9b4` / `v1a2d3e4f5b6` (the production Alembic head) |
| Objects added | 6 columns; no tables, indexes or constraints |
| Columns | `users.birth_date DATE NULL`, `users.hire_date DATE NULL`, `users.celebration_opt_out BOOLEAN NOT NULL DEFAULT false`, `performance_periods.evaluation_start_date DATE NULL`, `performance_periods.evaluation_end_date DATE NULL`, `performance_periods.evaluation_due_days INTEGER NULL` |
| Conditional logic | A column is added only if its table exists and the column is absent (`sa.inspect(bind)`) |
| Downgrade | No-op by design: the columns hold institutional data and predate the revision |
| Additive | Yes |
| Existing rows modified | Only where `celebration_opt_out` is absent: existing `users` rows receive `false` from the server default, which equals the ORM default. All pre-existing column values are unchanged (checksum-verified, §5). |
| Non-empty production-shaped table | Untouched: the columns already exist, so the migration does nothing |
| Data loss possible | No |
| Runtime-DDL match | Identical to the pre-branch runtime DDL (`ebd5ff08`): `ALTER TABLE users ADD COLUMN ... BOOLEAN NOT NULL DEFAULT FALSE` (cic_context) and `ADD COLUMN IF NOT EXISTS ... DATE NULL / INTEGER NULL` (schema_guard_patches) |
| ORM differences | The ORM declares `index=True` on 5 of these columns. Their production presence is unverified, so the migration does not create them (§6). The ORM has no server default for `celebration_opt_out`; the migration keeps the runtime DDL's `DEFAULT FALSE`. |
| Tests | `tests/migrations/test_w1c5a7d2e9b4_*` (4 tests) |

## 3. `w2d8e1f4a6c3_adopt_orm_tables_missing_from_migrations`

| Item | Finding |
|---|---|
| revision / down_revision | `w2d8e1f4a6c3` / `w1c5a7d2e9b4` |
| Objects added | 29 tables; `performance_periods.special_scenario_type VARCHAR(60) NULL`; conditional adoption of the low-score events table |
| Conditional logic | (a) Each table is created only if it is absent from `get_table_names()`. (b) `special_scenario_type` is added only if absent. (c) Events adoption runs only if `process_id` is absent **and** `SELECT COUNT(*)` returns 0. Otherwise it logs a warning and changes nothing. |
| Downgrade | No-op by design: the tables may hold institutional data |
| Additive | Yes. The only SQL executed is `SELECT COUNT(*)`. |
| Existing rows modified | Never. Tables are created empty; events columns are added only to an empty table. |
| Non-empty production-shaped table | Untouched (§5 E and F) |
| Data loss possible | No. The whole upgrade runs in one PostgreSQL transaction (`context.begin_transaction()`, transactional DDL), so any failure rolls back everything, including the version stamp. |
| Tests | `tests/migrations/test_w2d8e1f4a6c3_*` (5 tests); PG gate ORM-parity and runtime-schema steps |

### 3.1 The 29 adopted tables

All 29 are rendered statically from the ORM (`CreateTableOp.from_table` / `CreateIndexOp.from_index`). On PostgreSQL 15
their migration shape equals ORM `create_all` exactly: columns, types, lengths, precision, nullability, defaults, PK,
FKs with `ON DELETE` actions, unique and check constraints, index names, columns and uniqueness. **0 differences in 29
tables.**

Production evidence (2026-09-28 read-only live validation,
`docs/quality/BYS360_LIVE_READONLY_VALIDATION_2026-09-28.md`): all 164 ORM tables exist in production, including these
29. Because each table is created only if absent, W2 does nothing to them in production.

| Table | Cols | NOT NULL | Server defaults | FKs | Unique | Check | Indexes | FK targets (ON DELETE) |
|---|---|---|---|---|---|---|---|---|
| `feedback_action_plans` | 14 | 6 | 0 | 4 | 0 | 0 | 6 | feedback_campaigns, organization_units, users |
| `feedback_answers` | 8 | 5 | 0 | 3 | 0 | 0 | 2 | feedback_question_options, feedback_questions, feedback_submissions |
| `feedback_campaign_assignments` | 6 | 5 | 0 | 1 | 0 | 0 | 3 | feedback_campaigns |
| `feedback_campaigns` | 17 | 11 | 0 | 2 | 0 | 0 | 9 | organization_units, users |
| `feedback_pulse_entries` | 10 | 8 | 0 | 2 | 1 | 0 | 4 | organization_units, users |
| `feedback_question_options` | 8 | 7 | 0 | 1 | 0 | 0 | 1 | feedback_questions |
| `feedback_questions` | 9 | 9 | 0 | 1 | 0 | 0 | 2 | feedback_campaigns |
| `feedback_submissions` | 9 | 6 | 0 | 3 | 0 | 0 | 6 | feedback_campaigns, organization_units, users |
| `message_comments` | 8 | 7 | 0 | 2 | 0 | 0 | 3 | messages (CASCADE), users (CASCADE) |
| `message_reactions` | 6 | 6 | 0 | 2 | 1 | 0 | 3 | messages (CASCADE), users (CASCADE) |
| `message_typing_states` | 8 | 7 | 0 | 2 | 1 | 0 | 4 | message_threads (CASCADE), users (CASCADE) |
| `performance_archived_results` | 12 | 8 | 0 | 2 | 0 | 1 | 8 | users (CASCADE / SET NULL) |
| `performance_evaluation_history` | 11 | 5 | 0 | 2 | 0 | 0 | 6 | performance_evaluations (CASCADE), users (SET NULL) |
| `performance_feedback_pipeline_flows` | 11 | 8 | 0 | 0 | 0 | 0 | 6 | - |
| `performance_feedback_pipeline_steps` | 13 | 10 | 0 | 1 | 0 | 0 | 4 | performance_feedback_pipeline_flows |
| `performance_low_score_processes` | 35 | 13 | 0 | 11 | 0 | 0 | 19 (1 unique) | performance_evaluations, performance_periods, users (CASCADE / SET NULL) |
| `performance_scoring_history` | 15 | 5 | 0 | 0 | 0 | 0 | 7 | - |
| `portal_activity_logs` | 8 | 5 | 0 | 1 | 0 | 0 | 4 | users (SET NULL) |
| `portal_comment_reactions` | 6 | 6 | 0 | 2 | 1 | 0 | 3 | portal_post_comments (CASCADE), users (CASCADE) |
| `portal_group_members` | 9 | 7 | 0 | 3 | 1 | 0 | 5 | portal_groups (CASCADE), users (CASCADE / SET NULL) |
| `portal_moderation_logs` | 7 | 4 | 0 | 2 | 0 | 0 | 3 | portal_posts (SET NULL), users (SET NULL) |
| `portal_pinned_posts` | 9 | 6 | 0 | 2 | 0 | 0 | 4 | portal_posts (CASCADE), users (SET NULL) |
| `portal_post_attachments` | 9 | 6 | 0 | 2 | 0 | 0 | 2 | portal_posts (CASCADE), users (SET NULL) |
| `portal_post_audiences` | 6 | 6 | 0 | 1 | 0 | 0 | 3 | portal_posts (CASCADE) |
| `portal_post_reactions` | 6 | 6 | 0 | 2 | 1 | 0 | 3 | portal_posts (CASCADE), users (CASCADE) |
| `portal_post_reports` | 10 | 6 | 0 | 3 | 0 | 0 | 4 | portal_posts (CASCADE), users (SET NULL) |
| `portal_profiles` | 10 | 6 | 0 | 1 | 0 | 0 | 2 (1 unique) | users (CASCADE) |
| `portal_saved_posts` | 5 | 5 | 0 | 2 | 1 | 0 | 2 | portal_posts (CASCADE), users (CASCADE) |
| `publication_issues` | 26 | 16 | 0 | 2 | 0 | 0 | 14 (1 unique) | users (SET NULL) |
| **Total** | **311** | **205** | **0** | **62** | **7** | **1** | **142 (3 unique)** | + 29 primary keys |

Creation order satisfies every FK: parents such as `feedback_campaigns` and `performance_feedback_pipeline_flows` come
before their children, and every other FK target already exists from earlier revisions.

### 3.2 `performance_periods.special_scenario_type`

`VARCHAR(60) NULL`, added only if absent. Production presence is proven by the live validation. The ORM declares
`index=True`; that index is not created (production index presence unverified, §6).

### 3.3 Low-score events adoption (`performance_low_score_process_events`)

Phase-6 migration `9a5e1f4c2d60` created this table with low-score summary columns. All of those columns are nullable,
and `v58a1c2d3e4f` added a nullable `sort_order`. The ORM shape has `process_id`, `step_key`, `title`, `status`,
`sort_order`, `actor_user_id` and `note`.

| Situation | W2 behaviour | Evidence |
|---|---|---|
| `process_id` present (production: ORM shape proven by live validation) | nothing | §5 E: 0 schema changes, row preserved |
| phase-6 shape, **non-empty** | nothing; warning `... left unchanged for manual review` | §5 F: schema and row checksum identical |
| phase-6 shape, **empty** (fresh install) | adds 6 columns (`process_id`, `step_key`, `title`, `status` NOT NULL; `actor_user_id`, `note` NULL), FKs `..._process_id_fkey` (CASCADE) and `..._actor_user_id_fkey` (SET NULL), `uq_low_score_process_step`, and 4 indexes | §5 F2: indexes and constraints equal the ORM; an ORM-shaped insert succeeds |

NOT NULL columns are added only to an empty table. If a row appeared between the count and the ALTER, PostgreSQL would
reject the ALTER and the whole upgrade would roll back, so no data can be lost. On SQLite, `batch_alter_table` rebuilds
the table (copy, drop, rename); it does so only on the empty table. Production runs PostgreSQL, where batch mode issues
plain `ALTER TABLE`.

Fresh-install residue after adoption: 9 phase-6 columns remain, all nullable, so ORM inserts do not need them.
`created_at`, `updated_at` and `sort_order` stay nullable where the ORM says NOT NULL. W2 deliberately does not tighten
existing columns.

## 4. Negative checks (static, both files)

| Pattern | w1c5a7d2e9b4 | w2d8e1f4a6c3 |
|---|---|---|
| DROP TABLE / drop_table | 0 | 0 |
| DROP COLUMN / drop_column | 0 | 0 |
| ALTER TYPE / alter_column / type_ change | 0 | 0 |
| TRUNCATE / DELETE / UPDATE / INSERT / bulk_insert | 0 | 0 |
| rename | 0 | 0 |
| drop_constraint / drop_index | 0 | 0 |
| raw SQL executed | none | `SELECT COUNT(*)` only |
| server_default | 1 (`celebration_opt_out DEFAULT false`, matches the pre-branch runtime DDL) | 0 |
| nullable tightening of an existing column | none | none (NOT NULL only on new tables, or on events columns added to an empty table) |
| destructive constraint change | none | none |

## 5. PostgreSQL 15 verification (disposable local cluster, 15.16; production not accessed)

Gate: `scripts/quality/bys360_postgres_migration_integrity_gate.py` on a new empty database, run on the final tree.
The extra checks used a local scratch harness that is not committed.

| Check | Result | Evidence |
|---|---|---|
| Empty-DB guard | PASS | `EMPTY_DB_GUARD=PASS` |
| A. empty → head (`flask db upgrade`) | **PASS** | 79 revisions, head `w2d8e1f4a6c3` |
| B. second upgrade | **PASS (no-op)** | 0 `Running upgrade` steps |
| C. single head | **PASS** | `flask db heads` → `w2d8e1f4a6c3 (head)` only |
| C. ORM parity | **PASS** | 164 tables, 2061 columns present |
| C. critical tables / columns | **PASS** | 9 tables, 37 columns |
| C. shape vs ORM `create_all` | **PASS** | 29 W2 tables: 0 differences; W1/W2 columns identical except the documented `celebration_opt_out` default |
| D. runtime-schema check → provision → check → provision | **PASS** | first check exit 1 (12 groups MISSING); provision OK; check exit 0; second provision: all 15 groups `already present` |
| E. production-shaped fixture → upgrade | **PASS** | see below |
| F. non-empty phase-6 events → upgrade | **PASS** | events columns, indexes and constraints unchanged; row checksum identical; warning logged; 29 tables created; second upgrade no-op |
| F2. empty phase-6 events → upgrade | **PASS** | indexes and constraints equal the ORM; 9 residual columns all nullable; ORM-shaped insert succeeded |
| W1. rows without the W1 columns → upgrade | **PASS** | pre-existing column values checksum-identical; new values `NULL, NULL, false` |
| G. schema contract | **PASS** | 26 tables, 336 columns, 0 errors |

**E. Production-shaped fixture.** The database was built at `v1a2d3e4f5b6`, the production Alembic head. The W1
columns were added with the exact pre-branch runtime DDL. `special_scenario_type` was added as `VARCHAR(60)`, and the
events table was given the ORM shape proven in production. Of the 29 tables, 26 were created through the ORM, and the 3
`message_*` tables through the repository's raw schema-guard repair DDL (server defaults plus the extra
`ix_message_comments_created_at` index). `performance_archived_results` also got the 10 extra Faz 7 columns that exist
in production; their names come from the live validation, and their types are fixture-only. Rows were inserted into 22
tables. After `flask db upgrade`, which ran `v1a2d3e4f5b6 → w1c5a7d2e9b4 → w2d8e1f4a6c3`:

- 0 column, index or constraint changes in any table;
- row checksums (`md5` of every row of every table) identical;
- a second upgrade ran nothing.

## 6. Differences from the ORM that the migrations intentionally keep

| Object | Migration | ORM | Why |
|---|---|---|---|
| `ix_users_birth_date`, `ix_users_hire_date`, `ix_users_celebration_opt_out`, `ix_performance_periods_evaluation_start_date`, `ix_performance_periods_evaluation_end_date`, `ix_performance_periods_special_scenario_type` | not created | `index=True` | Production presence unverified. Creating them risks a name clash or a long lock on `users`. This affects performance only, not correctness. |
| `users.celebration_opt_out` default | `DEFAULT false` | Python default only | Same as the runtime DDL that created the production column |
| events table on a fresh install | 9 nullable phase-6 columns; 3 nullable timestamp/order columns | ORM only | W2 never drops or tightens existing columns |

## 7. Unproven schema assumptions (INSUFFICIENT_EVIDENCE)

None of these affects upgrading production, because W2 never alters an existing table. They matter only when a
database is rebuilt from migrations (fresh install or disaster recovery). For recovery the documented rule still
applies: restore from backup (`docs/quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md`).

1. **Production shape of 26 adopted tables beyond presence.** Presence is proven. Column types, nullability, defaults,
   index names and FK names are not recorded in the repository. The migration reproduces the ORM, and the application
   reads and writes through the ORM.
2. **`message_comments`, `message_reactions`, `message_typing_states`.** Two repository sources disagree. The ORM (and
   W2) has no server defaults. The raw repair DDL in `app/schema_guard_core_maintenances.py` has `DEFAULT NOW()` /
   `DEFAULT FALSE` and an extra `ix_message_comments_created_at` index. Which source created the production tables is
   unknown.
3. **`performance_archived_results`.** Production has 10 extra columns that the ORM lacks. Faz 7 raw SQL
   (`app/ai/decision_support_faz7_routes.py`) reads them: `user_id`, `personnel_id`, `registry_no`, `personnel_name`,
   `period_year`, `period_title`, `score_value`, `score_label`, `general_comment`, `visibility_status`. Their types are
   unknown, so the two Faz 7 archive routes fail on a migration-built database. This is human decision item 2.
   `development_guidance_integration` also reads `year` and `period_id` (guarded, returns an empty list).
4. **`performance_scoring_history`.** Several raw readers use columns absent from the ORM: `action_at`, `scorer_name`,
   `manager_level`, `score_value`, `action_status`, `event_key`, `next_stage`, `next_owner_user_id`,
   `next_owner_name`, `scorer_user_id`. Most readers check the column list first. `process_engine_phase4_flow` does not.
   Whether production has these columns is unknown.
5. **`feedback_action_plans`.** AI integration readers use `user_id`, `period_id`, `evaluation_id` and `action_title`,
   which are absent from the ORM. The readers are guarded; production presence is unknown.
6. **Indexes of §6.** Production presence is unknown.

Raw SQL that **is** compatible with the W2 shape:

- the pipeline flow/step INSERTs, which supply every NOT NULL column;
- the dashboard counters, which check the column list first;
- `performance_evaluation_history` `SELECT *` with column-checked filters;
- `performance_low_score_processes` reads.

## 8. Pre-deploy notes

- The deploy's `flask db upgrade` would run `v1a2d3e4f5b6 → w1c5a7d2e9b4 → w2d8e1f4a6c3`. Both steps are expected to
  change nothing in production (§5 E).
- Before deploying anything that contains this branch, run the read-only `flask runtime-schema check` on production.
  If a group is MISSING, run `flask runtime-schema provision` in a maintenance window.
- The pre-deploy database backup rule is unchanged.
