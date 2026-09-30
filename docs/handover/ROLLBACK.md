# BYS360 Rollback

Audience: an operator who needs to reverse a cutover, running
[rollback_bys360_candidate.ps1](../../scripts/windows/rollback_bys360_candidate.ps1).
The maintained script is present in the repository. Review its actual parameters and
compatibility checks for the chosen source revision; this document is not authorization
to execute a rollback.

## The critical distinction: pre-migration vs. post-migration rollback

Cutover (see `CUTOVER.md`) moves the live application tree **before** running the live
database migration (step 8: move current to `previous\`, step 12: live migration). This
ordering means rollback is not one uniform operation — it is two genuinely different
situations depending on how far cutover got before it failed, or how far a live release has
progressed before an operator decides to reverse it.

### PRE-MIGRATION rollback — trivial

If cutover failed, or is being reversed, at any point **before** step 12 (live migration)
actually ran and committed: the database was never touched. Rollback here is exactly what
it sounds like — swap the app tree back:

- Move (or confirm-and-leave, if the promote step never happened) the tree back from
  `C:\bys360\previous\<timestamp_SHA>\` to `C:\bys360\project\`.
- Restart the Scheduled Task.
- Verify local/public health.

There is no schema-compatibility question to reason about at all, because the schema never
changed. This is the safe, low-stakes case, and it is the case a fail-closed cutover design
is specifically built to leave you in as often as possible — every gate in `CUTOVER.md`
before step 12 exists partly so that a failure discovered there is still this trivial case.

### POST-MIGRATION rollback — requires real verification, not a blanket assumption

If the live migration (step 12) already ran and committed before the failure (for example,
a later step like the security/log scan fails, or an operator decides post-hoc to reverse a
release that is now running against a migrated schema): **rolling back the application tree
alone is safe only if the rolled-back code is actually proven compatible with the
already-advanced database schema.** Do not assert this as a blanket guarantee for every
future release — it is a property that must be checked per release, not assumed from a
past release's evidence.

Concretely, before performing a post-migration app-tree-only rollback:

1. **Diff the previous and candidate source trees for real** — run
   `git diff <previous_source_sha>..<candidate_source_sha> --stat` (or the equivalent
   against the actual retained source, not a guess) and read what changed, specifically
   outside `docs/`, `migrations/versions/`, and `tests/`. If application code that reads or
   writes the affected tables changed in a way that depends on the new schema (a new
   required column with no default, a renamed/dropped column or table the old code still
   references, a new NOT NULL constraint the old code doesn't populate), the old code is
   **not** safe to run against the new schema, full stop — a code-only rollback here would
   just move the failure into the running application instead of fixing it.
2. **Check whether the migration was purely additive.** A migration that only creates new
   tables/columns and does not alter or drop anything the previous code path relies on is
   the best case for post-migration rollback safety — the previous code simply never
   references the new objects. This is not automatic, though: verify it by reading the
   actual migration script(s) between the two revisions, not by assuming "it's probably
   fine."
3. **Only if both of the above check out**, perform the app-tree-only rollback: move
   `C:\bys360\project\` aside, restore `C:\bys360\previous\<timestamp_SHA>\` in its place,
   restart the task, verify health. The database is left at its already-migrated revision —
   this is expected and correct in this scenario, not an error.

For the one concrete historical data point available in this repository (the `cb2e57c` →
`ec4e56b` release this handover set was written alongside): `git diff cb2e57c..ec4e56b
--stat` showed exactly 7 changed files, all under `docs/handover/`, `migrations/versions/`,
or `tests/migrations/` — `app/`, `config.py`, `wsgi.py`, `run_server.py`, and
`requirements.txt` were byte-identical between the two commits, and the migration itself
was purely additive (adopting File Center's existing 19 tables into Alembic's ownership,
not creating or altering application-visible behavior). That specific pair of commits is
therefore a case where post-migration app-tree-only rollback would have been safe — **this
fact is specific to that one release pair and must not be extrapolated to any other
release** without repeating the same diff-and-read exercise against the actual commits
involved.

## Alembic downgrade is never run automatically

Nothing in this deployment model runs `flask db downgrade` (or any equivalent) as part of
rollback, ever. This is a deliberate design decision, not an oversight: an automatic schema
downgrade against a live, possibly-already-written-to database is a destructive operation
with its own failure modes (data loss on a downgrade that drops a column with data already
written to it, foreign-key or constraint violations if dependent data was created after the
upgrade), and reversing it correctly requires human judgment about what has actually
happened in the intervening window — judgment a script cannot supply. If a database-level
downgrade is genuinely necessary, it is a manual, deliberate, human-reviewed operation,
performed with the pre-cutover backup as the actual safety net (see `DISASTER_RECOVERY.md`
for restoring from that backup), not an automated Alembic downgrade against live data.

## DB backups are never deleted by rollback

The pre-cutover `pg_dump` backup written to `C:\bys360\backups\` during cutover step 4 is
never deleted by rollback, by design, regardless of which rollback path is taken or how
many times a release is retried. Retention/cleanup of old backups, if ever needed, is a
separate, deliberate operator decision — not something either cutover or rollback performs
automatically.

## What success and failure look like here

- **Success (pre-migration case)**: the previous tree is back at `C:\bys360\project\`, the
  task is running, health checks return 200, and the database's Alembic revision is
  unchanged from before cutover began.
- **Success (post-migration case)**: same application-tree-level outcome, but the database
  remains at the already-migrated revision, and this was a deliberate, verified decision
  (per the diff-and-check procedure above), not a default assumption.
- **Failure**: if the previous tree cannot be found at `C:\bys360\previous\<timestamp_SHA>\`
  (for example, if this is the very first cutover ever performed on this host and no
  "previous" exists yet), rollback has nothing to swap to — recovery must fall back to the
  retained release ZIP for the last-known-good source SHA (see `DISASTER_RECOVERY.md`). Do
  not attempt to fabricate a "previous" tree from partial state.
