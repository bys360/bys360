# PR #70: second security review fixes (R05d)

Starting revision: `475baa4e8b8f0e365f7ef84a7a67e7591d58294e`.
Branch verified through GitHub: `claude/lucid-hawking-u4gpp0`.
Base: `assistant-v2-full`. The PR remains draft; merging is the owner's decision.

## Changes and failure evidence

| Finding | RED evidence | Change |
| --- | --- | --- |
| MEDIUM: assistant authority parsing/enabling | The live menu rejects a newline list that the guard accepts; empty/unknown/malformed lists disagree. Non-admin module saves change `ai_agent.enabled`. | One `visible_roles_for_value` parser serves settings, matrix, live menu and write guards. Missing configuration retains install defaults; explicitly blank, unknown or malformed configuration grants no roles. The settings consumer has no manager bypass of an explicit role list. Module save/rollback protect `assistant.enabled`, `active`, and `ai_agent.enabled`, `active`, `widget_enabled`, `panel_enabled`. |
| LOW-A: whitespace administrator classification | Reset-all deletes admins with tabs, newlines and nonbreaking spaces despite Python treating them as admins. | Classify IDs with the guard's Python role normalizer; use the same IDs for FK cleanup and deletion. No SQL `trim(role)` assumption. Import, deletion, demotion and deactivation are also covered; malformed interior tokens gain no admin authority. |
| LOW-B: concurrent permission revocation/demotion | Two PostgreSQL transactions revoke admin2's `settings` access and demote admin1; both succeed, leaving no usable admin. | Both operations lock active admins in ID order and use the same critical-access calculation. Demotion/deactivation must leave an admin with both critical keys. Pending demotions/deactivations in a bulk transaction are excluded after locking, before considering remaining admins. |
| LOW-C: V10 alias/exact mismatch | An unchanged V10 form with conflicting exact/alias rows either writes an unintended change or refuses a non-admin. A newer alias can reopen a disabled exact runtime master. | Display, role/account access queries and live menu share manual exact > manual alias > seed exact > seed alias priority, with newest ID as tie-breaker. Master denial overrides shortcuts. Diff uses the displayed effective value. Manual writes persist across seeding and audit only real changes; protected columns remain real-admin only. |

The initial 24-test RED run on the old code produced 14 failures and 10 passing controls.
Additional enabling-flag tests failed twice before their fix; the runtime alias test failed
before its fix. A separate reviewer found a pending-state regression during implementation:
two preloaded bulk-operation tests reproduced it, and the final guard closes it.

The resumed independent review also found dotted/underscore alias-only denial and
account-level exact-denial precedence defects. Six alias/seed cases and two account
cases reproduced these before correction. Stored NULL role lists and NULL/blank/invalid
activation flags were also tested RED. A shared strict activation parser prevents a
non-admin matrix save from reopening an explicitly disabled assistant. Missing settings
still retain installation defaults. The final focused suite contains 50 tests.

## PostgreSQL acceptance evidence

A disposable PostgreSQL 15 cluster was created under `C:\bys360\codex-pr70-pg`, listening
only on `127.0.0.1:55470`, with synthetic data in `codex_pr70_test`. No migration was applied.
The cluster was stopped after the tests.

Final explicit invocation:

```powershell
$env:BYS360_R05C_PG_URL = 'postgresql+psycopg2://codex_pr70@127.0.0.1:55470/codex_pr70_test'
python -m pytest tests/postgresql/test_r05d_admin_access_race.py tests/security/test_r05c_settings_authority_and_admin_continuity_contract.py -k postgresql -q -s
```

Result: **5 passed**, including the pre-existing mutual-demotion test and its unlocked
sensitivity control. New race results:

- Revocation first (resumed validation): backend PIDs `30980` / `45828`; revocation allowed, demotion refused
  with `last_admin_with_access`.
- Demotion first (resumed validation): backend PIDs `22308` / `27252`; demotion allowed, revocation refused
  with `last_admin_with_access`.
- Each overlap used separate connections/transactions and bounded thread joins; no deadlock.
- The old-code revocation-first run failed with PIDs `23580` / `33616`, both operations
  allowed and no remaining administrator with usable critical access.

The new PostgreSQL tests are an explicit acceptance suite, outside the default CI selection.
Missing PostgreSQL is an assertion failure, not a SQLite substitute or a skip. Existing R05c
CI skips are unchanged; these same PostgreSQL contracts were actually run locally above.

## Independent review

A separate security-review agent inspected the full final diff and relevant caller paths,
including runtime alias handling and pending transaction state. Final code-review decision:
**APPROVE**, no additional HIGH/MEDIUM or concrete LOW findings in this scope.
The reviewer changed no files and did not run tests; execution evidence is supplied separately.
This is an independent agent code review, not a GitHub human approval.
The resumed final reviewer independently rechecked every changed file and relevant caller
after both of its additional LOW findings were fixed, and returned APPROVE. It found no
weakening of the three changed pre-existing test contracts.

Pre-existing test changes were checked explicitly:

- The blank-role-list contract now asserts no access; the separate missing-setting default
  control remains. This strengthens the authority boundary rather than removing an assertion.
- The R05c positive full-form save posts the existing `ai_agent` activation values, so it
  actually requests an unchanged authority state. Existing assertions are retained; the new
  tests separately prove that unauthorized activation/deactivation and rollback are refused.
- B1F1 uses `Path.as_posix()` for cross-platform path comparison. Its literal-key and
  constant-reference allowlists, scanned files and exact assertions are unchanged.

## Local validation

- Final focused R05d suite: **50 passed**. Together with the old assistant role matrix,
  role-label and live menu apply-key contracts: **90 passed**, zero failures.
- Runtime fallback and broad-except ratchet controls: **27 passed**.
- `mypy app tests scripts --ignore-missing-imports --no-error-summary`: passed.
- `compileall` and `git diff --check`: passed.
- Secret gate: zero findings.
- Quality9: zero findings, 2063 app broad exceptions.
- Ops audit: 2064 broad exceptions, within the unchanged 2064 ceiling.
- Dependency audit of `requirements.txt`: no known vulnerabilities. The installed
  pip-audit subprocess helper deadlocks on Windows by reading stdout/stderr sequentially.
  A task-only runner outside the repository drains both pipes with `communicate`, preserving
  resolver arguments, advisory checks, findings and failure exits. No installed package,
  repository configuration or audit threshold was changed. Exact GitHub CI runs its original
  dependency-audit command on Linux.
- The exact full CI Ruff command passes with pinned Ruff 0.16.0 outside the sandbox.
  The sandbox initially prevented Git ignore discovery and scanned the already ignored
  archive tree. No Ruff settings, exclusions or thresholds were changed in the repository.

## Checkpoint requested by owner

Decision: **NO-GO / DRAFT**. The owner explicitly requested saving the approved changes
before usage runs out, without waiting for CI. No known failing test or unresolved
HIGH/MEDIUM finding blocks this checkpoint; full acceptance is still incomplete.

- Final CI-safe quality selection: **1125 passed, 1 existing skip, 82 deselected**.
- Final focused acceptance: **90 passed**, including all 50 R05d cases.
- Final runtime/ratchet controls: **27 passed**.
- Completed PostgreSQL acceptance rerun: **5 passed**, with the overlap proof above.
- Prior completed broader batches: 201 passed and 150 passed; the prior 334-test prefix
  also completed. These do not substitute for a completed broad run on the final code.
- The final broad 29-file run and the resumed 9-file security batch were interrupted
  at the owner's checkpoint request, around 31% and 74% respectively. No failing test
  was observed before interruption. Partial progress is not a PASS result.
- The two required GitHub checks must be checked on the pushed checkpoint SHA. Old-head
  success is not evidence for the new head. Do not merge while these are pending.

Local evidence and file selections are preserved in `C:\bys360\codex-pr70-evidence`.
The final commit SHA, remote verification and full resume commands are in the external
checkpoint handoff file and PR description. No production, release, deploy, secret,
migration, unrelated PR, force-push or merge action is authorized by this evidence.
