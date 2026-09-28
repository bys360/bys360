# BYS360 Production Cutover — 2026-09-28

**Type:** sanitized repository evidence record.
**Scope:** the human-controlled production cutover from `1ea5c5dc…` to `67f2a29d…`, and its independent verification.

The cutover was executed on the production host by the human operator, using the approved candidate-preparation and cutover tooling. This record contains results only. It holds no credentials, connection strings, secret values, personal data or server-specific filesystem paths.

## 1. Production identity

| Field | Value |
|---|---|
| Production SHA | `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9` |
| Production tag | `bys360-prod-2026.09.28-67f2a29d` (annotated; tag object `572d5de0bd6f5a527c340c4a558c35e43b2317bc`) |
| Source branch | `assistant-v2-full` (PR #13 merge commit; tree `ded33c2a6b3361076cc1b9e1be80518e579ccf04`, identical to the tested PR head `1cdd75f5…`) |
| Previous production | `1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6` (tag `bys360-prod-2026.09.23-1ea5c5dc`, unchanged) |
| Deployment date | 2026-09-28 |
| Alembic before | `v1a2d3e4f5b6` |
| Alembic after | `v1a2d3e4f5b6` |
| CI on the tested tree | `36395443907` (quality-gate) SUCCESS; `36395443908` (score100-quality-gate) SUCCESS |

## 2. Package identity

| Field | Value |
|---|---|
| Release package | `BYS360_FULL_LIVE_2026-09-28_67f2a29d.zip` (FULL build, builder schema version 3) |
| Release package SHA-256 | `36bc8150b7521e15de9d398fa9ee0bc67c0c657699abd759b0e9d04c90d27a79` |
| Package file count | 2275 |
| Embedded source SHA | `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9` (`RELEASE_SOURCE_SHA.txt`) |
| Dependencies | `requirements.lock` plus an offline wheelhouse of 59 wheels (CPython 3.12, win_amd64) |
| Pre-delivery checks | Builder `--verify` PASS; secret scan of the extracted package: 0 findings; clean-room smoke PASS (offline install, compile, app factory, Alembic head) |

## 3. Pre-cutover candidate preparation

| Check | Result |
|---|---|
| Candidate preparation | PASS |
| Shadow rehearsal | PASS |
| Shadow schema contract | PASS |
| Shadow File Center | 19/19 |
| Candidate health (non-live port) | 200 |

## 4. Production cutover result

| Check | Result |
|---|---|
| Deploy exit | 0 |
| Migration result | PASS. The database was already at `v1a2d3e4f5b6`, so no revision change occurred. |
| Production schema contract | PASS |
| Production File Center | 19/19 |
| Service start | PASS |
| Process binding | PASS |
| Local health | 200 |
| Release identity | PASS |
| Readiness | PASS |
| Public health | 200 |
| Smoke | PASS |
| Security critical | 0 |

### Application route smoke evidence

| Probe | Count |
|---|---|
| File Center routes | 44 |
| Portal routes | 22 |
| File Center guest endpoints | 4 |
| File Center chunk endpoints | 7 |
| Total Flask routes in the smoke probe | 996 |

Clarification: `/versionz` reported `route_count = 6`. That field counts entries in the runtime route manifest, not the full Flask `url_map`. The cutover smoke probe counted 996 Flask routes independently, the same number the pre-delivery clean-room smoke found for this package.

## 5. Post-cutover independent verification

- Loopback `/versionz` confirmed the running source SHA `67f2a29dc29c7977dbbf5b16b0629daa630e9ef9` and migration head `v1a2d3e4f5b6`.
- `/readyz` returned `ready`, with `schema_error_count = 0`.
- Public `/healthz` returned 200 over HTTPS.
- The production database revision was `v1a2d3e4f5b6` both before and after the cutover.

## 6. Rollback evidence retained

- Rollback was not required.
- The deployment tooling retained the previous application tree (`1ea5c5dc…`) and took a pre-cutover database backup. Both were preserved successfully.
- Because no migration revision change occurred, a rollback would take the tooling's pre-migration path: restore the previous tree only, with no database downgrade. The previous release also stays reachable through its immutable tag, `bys360-prod-2026.09.23-1ea5c5dc`.

## 7. Remaining nonblocking follow-ups

None of these is a deployment failure. None is fixed in this record.

- **Live attribution settings** (`kunye.developer_label`, `kunye.developer_name`, and the missing co-developer rows) still need a separate, human-approved update through the application's settings screen.
- **README:** the module list still omits "Dosya Merkezi" (File Center).
- **Schema recovery limitation:** repository migrations alone do not reconstruct the whole historical live schema. Disaster recovery requires the approved database backup and restore procedure (`docs/quality/BYS360_SCHEMA_RECOVERY_LIMITATION.md`).
- **Schema inventory:** it still misclassifies `performance_president_approvals` as having no migration, because that migration names the table through a constant. The PostgreSQL gate's critical-column check covers the table in the meantime.
- **AI Faz 8:** the single-period check still returns 500 instead of 404 for a period id that does not exist.
- **P0-01 historical audit evidence:** a policy follow-up remains open. The audit trail contains matching rows, but exploitation is **not** proven.

Related records:
- Pre-cutover live validation snapshot (describes the previous production `1ea5c5dc…`): `docs/quality/BYS360_LIVE_READONLY_VALIDATION_2026-09-28.md`.
- Current production identity: `SOURCE_OF_TRUTH.md`.
