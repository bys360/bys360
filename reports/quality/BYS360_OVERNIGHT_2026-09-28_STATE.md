# BYS360 Overnight Remediation State — 2026-09-28 / 2026-09-29

CURRENT TIME — Europe/Istanbul: 2026-09-29 01:45 (interim checkpoint before 02:30)
CURRENT BRANCH: fix/schema-runtime-ddl-wave1 (local only, no upstream)
CURRENT HEAD: c7b314d0 (+ this state-file checkpoint commit)
START SHA: b26a2e18722731b968a377187d93c9545ef4b92f
BASE (default-branch docs head, NOT production): ebd5ff08bbd64ba9db51ac86e6e1d1e5c311c76b
DEPLOYED PRODUCTION APP (unchanged, not touched): 67f2a29dc29c7977dbbf5b16b0629daa630e9ef9 (tag bys360-prod-2026.09.28-67f2a29d)
NOTE: a usage-limit pause happened around 00:00; work resumed at 01:02 from a clean tree at 3a910441.

## CURRENT PHASE
Phase 4 (behavioral / PostgreSQL coverage) -> final gates

## COMPLETED WORK (local commits since start)
Phase 1 — schema / runtime DDL
- dc65b634 fix: adopt orm tables missing from migrations (w2d8e1f4a6c3; PG gate POSTGRES15_ORM_PARITY)
- 19d56b07 fix: remove development guidance request-time ddl
- 2ccc09e0 fix: remove mobile push token request-time ddl
- ca6ced98 fix: remove period center request-time column ddl
- 9c896b65 fix: inspect before altering in the period center provisioners (PostgreSQL self-deadlock)
- 484a5e56 / 063725c8 / da8d881d: gate fixture, schema inventory, checkpoint docs
Phase 2 — authorization
- 9f50cae3 fix: stop public health probe leaking dependency errors
- 41e11e8e fix: scope ai evaluation summaries to the evaluation's viewers
- 57a1b08d fix: gate ai recommendation endpoints like the admin review queue
- 859a3198 fix: require a manager for the faz2 survey manager read views
- 72c1a213 (+cc924324) fix: scope hr leave, attendance and delegation changes to the caller
- 0bbb053a / eb1a13ee / 3a910441: authorization matrix + anonymous-route contract (996 routes, 110 reviewed)
Phase 3 — silent fallbacks
- 65666c53 docs: inventory critical silent fallbacks (1860 broad handlers; no fail-open gate)
Phase 4/5 — behavior and robustness
- 2957532f test: compare resolved paths in file center isolation checks (12 baseline failures fixed, test-only)
- 73fc2c52 fix: answer missing faz2 surveys and bulletins with a redirect, not a 500
- c7b314d0 fix: return 404 for a missing period on the faz8 scope check

## KEY EVIDENCE (PG15 disposable cluster 127.0.0.1:55439)
- migration-only DB (flask db upgrade + flask runtime-schema provision): 565 GET routes, 0 routes with DDL (pass 1 and 2),
  status distribution identical to the production-shaped DB, 0 routes worse
- runtime-schema provision/check/provision: all 15 groups, exit 0 (after 9c896b65)
- ORM parity after empty->head: 164 tables / 2061 columns

## CURRENT TASK
Add runtime-schema provision/check to the PostgreSQL gate (would have caught the provisioner deadlock).

## MODIFIED FILES (uncommitted)
- none after this checkpoint commit

## KNOWN FAILURES
- none new

## BASELINE FAILURES
- the 12 File Center Windows 8.3 temp-path failures are fixed test-only (2957532f)

## PROBE NOTES
- 12 AI decision-support routes 500 only inside the sequential probe: harness artifact (one outer app context keeps
  flask_login's g._login_user across requests -> DetachedInstanceError); 200 in isolation
- /ai/decision-support/performance/archive/* 500: Faz 7 raw SQL uses performance_archived_results.user_id (known;
  user instructed not to change Faz 7 during live-evidence remediation) -> NEEDS HUMAN DECISION

## MIGRATIONS ADDED
- w2d8e1f4a6c3_adopt_orm_tables_missing_from_migrations (down_revision w1c5a7d2e9b4), additive/conditional, downgrade no-op

## NEEDS HUMAN DECISION
- HIGH: popup announcement management (new/edit/toggle/per-user read report) gated only by menu 'announcements',
  which static defaults grant to 'personel'
- Faz 7 archive raw SQL ghost column (performance_archived_results.user_id)
- performance_development_recommendations: meeting_p4 defines a conflicting second shape
- performance_interim_notes: three runtime creators, alias columns, no migration/ORM
- admin setup actions creating tables via web (meeting_p2/p3/p4 run, /support/setup)
- 12 column shape differences (nullability/type) in 6 tables vs ORM
- birim_sorumlusu not in AI decision manager-scope roles
- draft bulletin titles visible to every 'announcements' menu holder
- faz4 survey analytics / faz8 period scope-check reachable by employees (aggregate data)
- AI policies performance/decision_support and category_group_decision_support undefined -> routes always 400
- menu override fallback (user_menu_permissions query failure drops deny overrides)

## NEXT ACTION
Gate step for runtime-schema provision; then CI-safe + architecture checkpoint; final full broad suite ~04:30; gates; report.

## SAFE RESUME COMMAND
cd C:\bys360\worktrees\schema-runtime-ddl-wave1 && git status --short && git branch --show-current && git rev-parse HEAD
then read this file and continue from NEXT ACTION.
