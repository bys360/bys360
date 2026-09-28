# BYS360 Overnight Remediation State — 2026-09-28 / 2026-09-29

CURRENT TIME — Europe/Istanbul: 2026-09-28 22:28
CURRENT BRANCH: fix/schema-runtime-ddl-wave1 (local only, no upstream)
CURRENT HEAD: ca6ced980eff100caffd25f5bd2faafc2fea6e5b (+ this state-file checkpoint commit)
START SHA: b26a2e18722731b968a377187d93c9545ef4b92f
BASE (default-branch docs head, NOT production): ebd5ff08bbd64ba9db51ac86e6e1d1e5c311c76b
DEPLOYED PRODUCTION APP (unchanged, not touched): 67f2a29dc29c7977dbbf5b16b0629daa630e9ef9 (tag bys360-prod-2026.09.28-67f2a29d)

## CURRENT PHASE
Phase 1 complete -> Phase 2 (authorization / IDOR)

## COMPLETED WORK
- dc65b634 fix: adopt orm tables missing from migrations
  - migration w2d8e1f4a6c3: 29 ORM tables + performance_periods.special_scenario_type + ORM shape of empty phase-6 low-score events table
  - PG gate: new POSTGRES15_ORM_PARITY step (164 tables / 2061 columns); negative control at w1c5a7d2e9b4 = 29 tables missing
- 19d56b07 fix: remove development guidance request-time ddl (faz10 GET + scorecard guidance)
- 2ccc09e0 fix: remove mobile push token request-time ddl
- ca6ced98 fix: remove period center request-time column ddl (v2_1_8 / v2_1_9)
- inventory: overnight_2026_09_28 section + per-item overnight_status

## CURRENT TASK
Phase 2 — reports/quality/BYS360_AUTHORIZATION_MATRIX_V1.json

## MODIFIED FILES (uncommitted)
- none after this checkpoint commit

## TEST RESULTS
- PG15 (disposable cluster 127.0.0.1:55439): empty->head PASS, second upgrade no-op PASS, ORM parity PASS,
  prod-shaped legacy upgrade (rows) 0 changes PASS, non-empty phase-6 events preserved PASS, schema contract PASS (26 tables/336 columns)
- migration + gate + release tests: 179 passed / 1 skipped; gate unit tests 50 passed (with migration tests)
- runtime schema contract: 21 passed (RED proven on committed code for each new test)
- adjacent: phase10 133 passed; push tokens 36 passed; period center 343 passed; v2_1_8/9 exception tests 113 passed

## KNOWN FAILURES
- none new

## BASELINE FAILURES
- 12 x tests/behavior/test_file_center_anonymous_guest_access_contract.py (Windows 8.3 temp path; fail identically on ebd5ff08)

## MIGRATIONS ADDED
- w2d8e1f4a6c3_adopt_orm_tables_missing_from_migrations (down_revision w1c5a7d2e9b4), additive/conditional, downgrade no-op

## NEEDS HUMAN DECISION (Phase 1)
- performance_development_recommendations: meeting_p4 defines a conflicting second shape
- performance_interim_notes: three runtime creators, alias columns, no migration/ORM
- admin setup actions creating tables via web (meeting_p2/p3/p4 run, /support/setup)
- 12 column shape differences (nullability/type) in 6 tables vs ORM

## NEXT ACTION
Phase 2: build route inventory -> classify -> actively test priority areas for IDOR.

## SAFE RESUME COMMAND
cd C:\bys360\worktrees\schema-runtime-ddl-wave1 && git status --short && git branch --show-current && git rev-parse HEAD
then read this file and continue from NEXT ACTION.
