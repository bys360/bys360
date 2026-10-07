# performance_interim_notes historical production adoption

Baseline: `7ee82ad824441a13f71fa16b1e56507c4ed3e777`. This analysis uses repository
history and the operator-supplied read-only catalog signature. No production
connection, rows, migration, deployment, service restart or cutover is used.

## Root cause and provenance

The production table is a historical hybrid, not the table created by the current
canonical migration. Its earlier base retains `employee_id`, `title`, `note`,
scorecard/activity flags and `note_text` NOT NULL, `note_type` and
`visibility_level` VARCHAR(40), assignment/evaluation link columns, older defaults,
and extra indexes. The later aliases have nullable definitions. Consequently the
old adoption guard rejects it rather than silently repairing it.

Git establishes the additive mechanism:

- `d8b50c4c` already contains the runtime helper. Its CREATE IF NOT EXISTS does not
  replace an existing table; `_safe_add_column` returns immediately for a present
  name. It therefore keeps old lengths, defaults, nullability and link columns,
  adds missing aliases, and creates the two employee/period indexes.
- `0f174ca0` adds a read-only complete-schema fast path. It does not change the
  meaning of the old column definitions or normalize their stored values.
- The old mobile fallback in `performance_routes.py` has 18 differently defined
  columns (VARCHAR(80), nullable text/employee fields). Its six-column retrofit
  also only adds missing columns. It cannot be the original production creator.
- The meeting P2 creator has 12 columns, NOT NULL employee_user_id/note_body,
  and no note_type default. Its BOOLEAN DEFAULT 1 is invalid on PostgreSQL. It
  cannot explain the PostgreSQL production base or its FALSE scoring default.
- `d1a0e5c7b934` adds nullable development_guidance_id and converted_to_guidance
  only if a note table already exists. This explains the two migration-era links.
- `23bb4f46` removes request-time ownership and introduces `x1f3a9c5e7b2`, but its
  catalog fixtures omit the stricter historical base. `a151a242` makes the
  readiness/read paths transaction-neutral. Both boundaries remain intact.

The observed column order is consistent with an older 19-column base, nine
later aliases, and two guidance columns. Git contains no original DDL for the
older assignment/evaluation indexes or the stricter production base. Therefore
its original creator, exact execution order and dates cannot honestly be
attributed to a tracked commit. This provenance limit does not require guessed
DDL: the supplied complete signature is adopted only after exact catalog proof.

## Semantic review

| Fields | Existing behavior and adoption decision |
| --- | --- |
| title / note_title | Manager and mobile prefer title; the manager reader ignores empty strings. Keep both distinct. |
| note / note_text / note_body / content / description | Manager/feedback prefer nonempty note_text then note_body then note. Mobile COALESCE prefers note (including empty strings). Evaluation/scorecard selects note_body by column existence. Keep every value independently; no backfill or normalization. |
| employee_id / employee_user_id | Writers mirror the selected user ID. Manager uses COALESCE; evaluation/feedback use employee_id when present. Mobile scope checks either ID but displays employee_id first. Historical differences are not remapped. |
| created_by / created_by_id | Writers mirror author IDs; manager author lookup chooses created_by_id by column presence; mobile scope checks both. Preserve each author field and manager_id. |
| visibility_level / visibility_scope | Writers explicitly set manager_scope. P2 displays visibility_scope; other inspected reads enforce their existing user/manager scope rather than combining these strings. Do not equate or rewrite them. |
| remind_in_evaluation / remind_during_scoring | Defaults differ (TRUE versus FALSE). Mobile COALESCE chooses scoring first; evaluation deliberately does not filter reminders because manager writes both FALSE. Preserve the difference. |
| include_in_scorecard / visible_on_scorecard | Writers mirror new values. SQL scorecard filtering uses include_in_scorecard when present; a FALSE primary field does not fall back to a TRUE alias. Preserve this precedence. |
| is_active / active | SQL reads select/filter is_active when present; the alias does not override it. Preserve both flags. |
| assignment_id | Historical optional link. No inspected direct note writer/reader requires it; no FK exists. Preserve it without inventing assignments. |
| evaluation_id | Historical optional link. Period cleanup deletes notes through period_id OR matching evaluation IDs. Preserve that relationship. |
| development_guidance_id | Nullable link added by d1a0; no inspected note business path dereferences it. Preserve it. |
| converted_to_guidance | Independent nullable flag added by d1a0; no inspected note business path consumes it. Preserve NULL/FALSE/TRUE separately. |

There is no ORM model for this table: the comment in performance_models.py is
historical documentation, not a db.create_all definition. The separate
performance_interim_notes_live table remains owned by its existing runtime-schema
group; it is not merged into this table. Readiness now inspects only. Generic
safe-user cleanup does not gain new FK behavior because adoption adds no FK.

Both direct writers satisfy the old NOT NULL columns: manager supplies note_text;
mobile leaves it at the existing empty-string default. The manager writer uses
an enum whose values fit 40 characters. The mobile writer previously sliced to
80 and could raise a PostgreSQL length error. It now reflects the VARCHAR limit:
on 40-column tables it returns HTTP 400 before INSERT for longer input, without
truncation. Canonical 80-column tables retain their existing 80-character behavior.
An unsupported reflected length fails closed with HTTP 503. No request executes
DDL or takes ownership of a readiness transaction.

The AI interim-feedback query still references absent personnel_id/category/
summary and falls back to an empty list. Preserving evaluation_id does not make
that query succeed. Adding those missing fields could expose notes through a
different scope contract and is outside this adoption. PostgreSQL query errors
can leave the caller's transaction failed; that existing AI behavior is not
presented as fixed by this change.

## Exact migration contract and proof

`HISTORICAL_PRODUCTION_30_VARIANT` is PostgreSQL-only. It requires all 30 columns
in evidence order with exact PostgreSQL types (including int4 width and timestamp
timezone), VARCHAR lengths, nullability and semantic constant defaults; no
identity/generated columns; the owned serial ID default; the sole named primary
key; and all 13 indexes including its backing index. Index uniqueness, columns,
order, method, predicates, expressions, INCLUDE fields, validity/readiness,
operator classes, collations and storage options are checked. Missing or added
objects fail before any mutation. This branch never retries a looser matcher.
The existing legacy branch and its guard rules are not expanded.

Adoption returns empty missing-column/index lists. It performs no table DDL,
row DML, renames, widening, narrowing, alias merging or default changes. Only
Alembic's revision marker advances. Downgrade and repeated adoption are no-ops.

The existing mandatory PostgreSQL 15 integrity gate now uses independently
transcribed fixture DDL and synthetic rows (not migration-generated metadata).
It stamps an isolated controlled fixture at w2d8e1f4a6c3, runs Alembic's actual
executor to the repository head, records executed statements, and compares the
entire catalog plus all row values before/after/repeat/downgrade. Every overlapping
field has a deliberately different value; a second row includes NULLs, empty
strings and opposing booleans. A real service rehearsal proves note_body and
employee precedence, a 40-character Unicode mobile insert, and a 41-character
HTTP 400 response with no writes. Eighteen altered PostgreSQL signatures are
refused with unchanged rows/catalogs. Existing absent, canonical, runtime, mobile,
P2, optional d1a0 and interrupted-transaction cases remain covered.

Local validation used native PostgreSQL 15 on a separate loopback-only disposable
cluster. The complete integrity gate passed empty-to-head, second-upgrade no-op,
164-table/2061-column ORM parity, 15 runtime-schema groups and all 28 adoption
rehearsals. Ruff, mypy (including a separate migration-file check), dependency
audit, pip check, Quality9, the unchanged ops-audit threshold, and repository /
changed-file secret gates passed. Release/security regression passed 126 tests;
one pre-existing symlink-capability test could not run because Windows denied
symlink creation, including an elevated retry. No PostgreSQL test was skipped,
and no test, threshold or guard was relaxed for this fix.
The combined migration, real-DB-gate unit, mobile authorization, request ownership,
transaction, readiness and architecture regression passed all 323 tests with
no failures or skips.

The new release must still undergo the separately authorized candidate/shadow
rehearsal over RDP. This local proof does not authorize production cutover. The
old 7ee82ad8 FULL package remains unapproved and untouched.
