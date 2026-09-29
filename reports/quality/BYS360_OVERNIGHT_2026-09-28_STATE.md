# BYS360 Overnight Remediation State — 2026-09-28 / 2026-09-29

CURRENT TIME — Europe/Istanbul: 2026-09-29 03:55 (final)
CURRENT BRANCH: fix/schema-runtime-ddl-wave1 (local only, no upstream)
CURRENT HEAD: 265f8754fee38ee56f64168ed744a0831be66f05 (tested tree; + this docs-only state commit)
START SHA: b26a2e18722731b968a377187d93c9545ef4b92f
BASE (default-branch docs head, NOT production): ebd5ff08bbd64ba9db51ac86e6e1d1e5c311c76b
DEPLOYED PRODUCTION APP (unchanged, not touched): 67f2a29dc29c7977dbbf5b16b0629daa630e9ef9 (tag bys360-prod-2026.09.28-67f2a29d)
NOTE: a usage-limit pause happened around 00:00; work resumed at 01:02 from a clean tree at 3a910441.

## CURRENT PHASE
COMPLETE — ready for human review. Nothing pushed, no PR, no deploy.

## COMPLETED WORK (28 local commits b26a2e18..265f8754)
Schema / runtime DDL
- dc65b634 migration w2d8e1f4a6c3 (29 ORM tables, special_scenario_type, low-score events ORM shape) + PG gate ORM parity
- 19d56b07 / 2ccc09e0 / ca6ced98 request-time DDL removed (faz10 guidance, mobile push tokens, v2_1_8/v2_1_9)
- 9c896b65 PostgreSQL self-deadlock fixed in the period-center provisioners
- eff84e80 PG gate runs runtime-schema provision/check/provision (negative control: RUNTIME_SCHEMA_TIMEOUT)
Authorization
- 9f50cae3 /health/deep no longer leaks dependency exception text
- 41e11e8e AI evaluation summaries scoped with can_view_evaluation (cross-unit IDOR)
- 57a1b08d AI recommendation JSON endpoints gated like the admin review queue
- 859a3198 faz2 survey manager read views require is_manager (employee read free-text answers)
- 72c1a213 HR leave/attendance/delegation status+delete scoped to the caller (cross-unit modify/delete)
- 0bbb053a authorization matrix + anonymous-route contract (996 routes, 110 manually reviewed)
Robustness / tests / docs
- 73fc2c52 faz2 missing survey/bulletin -> redirect instead of 500; c7b314d0 faz8 missing period -> 404
- 2957532f File Center isolation assertion compares resolved paths (12 Windows baseline failures fixed, test-only)
- 65666c53 critical silent fallback inventory; 063725c8 / ec724139 schema inventory and evidence docs

## TEST RESULTS (final tree 265f8754)
- FULL BROAD CI SUITE: 6363 passed, 3 skipped, 0 failed (1:40:15) — start of night: 6299 passed / 12 failed
- CI-safe quality: 1117 passed, 1 skipped; architecture + security: green after hygiene fix
- Ruff (both CI commands) PASS; mypy PASS; secret gate PASS (0 findings); git diff --check PASS
- PG15 gate on 265f8754: empty->head, head match, second upgrade, ORM parity (164/2061), runtime schema (15 groups) PASS
- schema contract PASS (26 tables / 336 columns)
- migration-only GET probe: 565 routes, 0 routes with DDL, status distribution identical to production-shaped DB

## KNOWN FAILURES
- none

## BASELINE FAILURES
- none remaining (the 12 File Center Windows temp-path failures are fixed test-only)

## MIGRATIONS ADDED
- w2d8e1f4a6c3_adopt_orm_tables_missing_from_migrations (down_revision w1c5a7d2e9b4), additive/conditional, downgrade no-op

## NEEDS HUMAN DECISION
- HIGH: popup announcement management gated only by menu 'announcements' (static defaults grant it to 'personel')
- Faz 7 archive raw SQL ghost column performance_archived_results.user_id (left unchanged on user instruction)
- performance_development_recommendations: meeting_p4 conflicting second shape
- performance_interim_notes: three runtime creators, alias columns
- admin setup actions creating tables via web (meeting_p2/p3/p4 run, /support/setup)
- 12 column nullability/type differences in 6 tables vs ORM
- birim_sorumlusu not in the AI decision manager-scope roles
- draft bulletin titles visible to 'announcements' menu holders; faz4 survey analytics / faz8 scope-check open to employees
- AI policies performance/decision_support and category_group_decision_support undefined (routes always 400)
- menu override fallback drops per-user deny overrides when user_menu_permissions cannot be read
- commit 2957532f message contains the personal Windows 8.3 account name — reword before any push (history rewrite = human decision)

## NEXT ACTION
Human review of the 28 local commits; decide the NEEDS HUMAN DECISION list; before deploying anything containing these
commits run the read-only `flask runtime-schema check` on production (provision in a maintenance window if MISSING).

## SAFE RESUME COMMAND
cd C:\bys360\worktrees\schema-runtime-ddl-wave1 && git status --short && git branch --show-current && git rev-parse HEAD
then read this file and continue from NEXT ACTION.
