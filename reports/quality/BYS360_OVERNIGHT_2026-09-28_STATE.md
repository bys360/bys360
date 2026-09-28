# BYS360 Overnight Remediation State — 2026-09-28 / 2026-09-29

CURRENT TIME — Europe/Istanbul: 2026-09-28 23:40 (midnight checkpoint)
CURRENT BRANCH: fix/schema-runtime-ddl-wave1 (local only, no upstream)
CURRENT HEAD: 789295be (+ this state-file checkpoint commit)
START SHA: b26a2e18722731b968a377187d93c9545ef4b92f
BASE (default-branch docs head, NOT production): ebd5ff08bbd64ba9db51ac86e6e1d1e5c311c76b
DEPLOYED PRODUCTION APP (unchanged, not touched): 67f2a29dc29c7977dbbf5b16b0629daa630e9ef9 (tag bys360-prod-2026.09.28-67f2a29d)

## CURRENT PHASE
Phase 2 (authorization / IDOR) largely done -> Phase 3 (critical silent fallbacks)

## COMPLETED WORK (local commits since start)
Phase 1 — schema / runtime DDL
- dc65b634 fix: adopt orm tables missing from migrations (migration w2d8e1f4a6c3; PG gate POSTGRES15_ORM_PARITY)
- 19d56b07 fix: remove development guidance request-time ddl
- 2ccc09e0 fix: remove mobile push token request-time ddl
- ca6ced98 fix: remove period center request-time column ddl
- da8d881d docs: record overnight schema checkpoint
- 484a5e56 test: provision runtime schema in the mobile role token gate
- 063725c8 docs: record closed schema reproducibility gaps
Phase 2 — authorization
- 9f50cae3 fix: stop public health probe leaking dependency errors (/health/deep)
- 41e11e8e fix: scope ai evaluation summaries to the evaluation's viewers (cross-unit IDOR)
- 57a1b08d fix: gate ai recommendation endpoints like the admin review queue (any employee read/changed)
- 859a3198 fix: require a manager for the faz2 survey manager read views (employee read survey free-text answers)
- 0bbb053a test: add authorization matrix and anonymous-route contract
  (reports/quality/BYS360_AUTHORIZATION_MATRIX_V1.json: 996 routes, 68 manually reviewed)

## CURRENT TASK
Phase 3 — reports/quality/BYS360_CRITICAL_SILENT_FALLBACKS_V1.json

## MODIFIED FILES (uncommitted)
- none after this checkpoint commit

## TEST RESULTS
- every fix: RED on committed code, GREEN after, adjacent suites green
- CI-safe quality checkpoint (after Phase 1 + first Phase 2 fixes): 1113 passed, 1 skipped
- tests/architecture: 540 passed (after inventory regeneration)
- adjacent: AI 571 passed; communication 112 passed; period center 343 passed; phase10 133 passed; push 36 passed
- PG15: empty->head PASS, second upgrade PASS, ORM parity PASS (164 tables / 2061 columns), legacy prod-shaped PASS,
  non-empty phase-6 events preserved PASS, schema contract PASS

## KNOWN FAILURES
- none new

## BASELINE FAILURES
- 12 x tests/behavior/test_file_center_anonymous_guest_access_contract.py (Windows 8.3 temp path; fail identically on ebd5ff08)

## MIGRATIONS ADDED
- w2d8e1f4a6c3_adopt_orm_tables_missing_from_migrations (down_revision w1c5a7d2e9b4), additive/conditional, downgrade no-op

## NEEDS HUMAN DECISION
- performance_development_recommendations: meeting_p4 defines a conflicting second shape
- performance_interim_notes: three runtime creators, alias columns, no migration/ORM
- admin setup actions creating tables via web (meeting_p2/p3/p4 run, /support/setup)
- 12 column shape differences (nullability/type) in 6 tables vs ORM
- birim_sorumlusu is not in the AI decision manager-scope roles (non-evaluator unit heads cannot use AI evaluation summaries)
- draft bulletin titles visible to every 'announcements' menu holder (faz1 list, faz2 history)
- faz4 survey analytics and faz8 period scope-check reachable by employees (aggregate data)
- AI policies performance/decision_support and category_group_decision_support are undefined -> those routes always 400

## NEXT ACTION
Phase 3: inventory broad-except fallbacks in performance/personnel/approval/authorization paths; fix only
DATA_CORRECTNESS_RISK / AUTHORIZATION_RISK with clear expected behavior. Final full broad suite ~05:00.

## SAFE RESUME COMMAND
cd C:\bys360\worktrees\schema-runtime-ddl-wave1 && git status --short && git branch --show-current && git rev-parse HEAD
then read this file and continue from NEXT ACTION.
