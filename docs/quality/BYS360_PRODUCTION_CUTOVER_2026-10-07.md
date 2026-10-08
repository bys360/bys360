# BYS360 Production Cutover — 2026-10-07

**Type:** sanitized repository evidence record.
**Scope:** human-controlled production cutover from `a5bd8a38…` to `cdae2795…`.

This record contains technical results only. It intentionally contains no credentials,
connection strings, passwords, secret values, personal data or production filesystem paths.

## 1. Production identity

| Field | Value |
|---|---|
| Production SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` |
| Production tag | `bys360-prod-2026.10.07-cdae2795` |
| Tag object SHA | `aa7b77ca21fe0a10ab9fd7f9cc5104743b4d1311` |
| Source branch | `assistant-v2-full` |
| Source PR | #47 — `fix: adopt exact historical production interim-notes schema` |
| Tested PR head | `d529020641f8d4fd7da160b77d2ccab9e586c661` |
| Production merge tree | `723da65df61f40eefefc12c853ae6177ad6dedb9` |
| Tested head tree | `723da65df61f40eefefc12c853ae6177ad6dedb9` — identical to production merge tree |
| Previous production | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` |
| Deployment date | 2026-10-07 |
| Alembic before | `w2d8e1f4a6c3` |
| Alembic after | `x1f3a9c5e7b2` |

## 2. CI and pre-release evidence

| Check | Result |
|---|---|
| GitHub Actions `Run tests` — run `37619199191` | SUCCESS |
| GitHub Actions `BYS360 Quality Assurance Gate V1` — run `37619199193` | SUCCESS |
| PostgreSQL 15 historical-schema rehearsal | PASS |
| Unknown/partial schema fail-closed tests | PASS |
| Migration/behavior regression | 323 PASS |
| Release/security regression | 126 PASS; one pre-existing Windows symlink-capability environment skip |
| Ruff / mypy / compile / dependency checks | PASS |

No PostgreSQL migration rehearsal was skipped and no gate/threshold was lowered for the
production schema-drift fix.

## 3. Release package identity

| Field | Value |
|---|---|
| Release package | `BYS360_FULL_cdae2795.zip` |
| Release package SHA-256 | `48d2572b3630e5c33bbf3cd337e9a9cf39f6b33d9d47aa3d7d17a54ec065f339` |
| Build reproducibility | Two independent clean builds byte-identical |
| ZIP size | 61,683,831 bytes |
| Package file count | 2,288 |
| Embedded source SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` |
| Wheelhouse | 59 Windows AMD64 / CPython 3.12 wheels |
| Wheelhouse identity | `c372cc2512055ef4f48648769bd09ee2e28b194b556a81eb242cdaf7722d4a70` |
| Secret scans | 0 findings |
| Builder verification | PASS |
| Offline dependency resolution/install | PASS |

## 4. Candidate preparation and shadow rehearsal

| Check | Result |
|---|---|
| Exact package hash verification | PASS |
| Candidate receipt binding | PASS |
| Fresh production backup before shadow restore | PASS |
| Disposable PostgreSQL shadow restore | PASS |
| Shadow migration `w2d8e1f4a6c3` → `x1f3a9c5e7b2` | PASS |
| Historical `performance_interim_notes` adoption | PASS |
| Schema contract | PASS |
| Candidate health | HTTP 200 |

The recognized historical `performance_interim_notes` production variant is adopted without
table DDL/DML, alias merging, value normalization or column widening/narrowing. Unknown or partial
catalog signatures remain fail-closed.

## 5. Production cutover result

| Check | Result |
|---|---|
| Fresh final pre-cutover PostgreSQL backup | PASS — 1,810,456 bytes |
| Persistent state preservation | PASS |
| Scheduled Task stop | PASS |
| Port 80 stale-listener check | PASS |
| Application tree promotion | PASS |
| Persistent state restore | PASS |
| Promoted-tree identity | PASS |
| Live migration `w2d8e1f4a6c3` → `x1f3a9c5e7b2` | PASS |
| Live schema contract | PASS — error count 0 |
| File Center | 19/19 |
| Service start | PASS |
| Fresh process binding | PASS |
| Local `/healthz` | HTTP 200 |
| `/versionz` release identity | PASS |
| `/readyz` | PASS |
| Public `/healthz` | HTTP 200 |
| Smoke checks | PASS |
| Post-deploy security gate | PASS — critical 0 |

### Smoke route evidence

| Probe | Count |
|---|---:|
| File Center routes | 44 |
| Portal routes | 22 |
| File Center guest endpoints | 4 |
| File Center chunk endpoints | 7 |
| Total Flask routes | 996 |

`/versionz` confirmed:

- `source_sha = cdae27953adcbdd8270fe78dcd52351725d3aecd`
- `migration_head = x1f3a9c5e7b2`

## 6. Independent post-cutover verification

After the deployment script completed successfully:

- Scheduled Task `BYS360 Live Waitress 80` reported **Running**.
- Public `https://bys360.canakkaletarihialan.gov.tr/healthz` returned **HTTP 200**.

These checks were performed separately from the cutover script's own final gates.

## 7. Rollback evidence

- Rollback was not required.
- The previous application tree was preserved.
- A fresh pre-cutover PostgreSQL backup was preserved.
- This cutover advances the live DB from `w2d8e1f4a6c3` to `x1f3a9c5e7b2`.
- Therefore an application-tree-only rollback is **not** represented as a complete database
  rollback. The rollback script does not automatically perform an Alembic downgrade; DB recovery
  remains an explicit human-controlled decision.

## 8. Scope note

This record proves the technical deployment/cutover gates above. It does not claim that every
business workflow was manually re-executed after deployment. Business-level user acceptance is
tracked separately from the technical production cutover evidence.

Canonical current production identity: [`SOURCE_OF_TRUTH.md`](../../SOURCE_OF_TRUTH.md).
