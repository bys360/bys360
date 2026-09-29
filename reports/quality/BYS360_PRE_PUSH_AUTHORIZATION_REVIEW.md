# BYS360 Pre-push Authorization Review — 2026-09-29

Branch `fix/schema-runtime-ddl-wave1` (local only). This review covers the five authorization fixes made on
2026-09-28/29, the human policy decisions they surfaced, the authorization matrix and its contract test, and the File
Center test fix. No authorization behaviour was changed while preparing this review.

Default roles (`app/admin/routes.py` `ROLE_CHOICES`): `admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`,
`mali_musavir`, `birim_sorumlusu`, `koordinator`, `personel`.

## 1. Summary

| # | Finding | Old behaviour | Existing policy reused | New behaviour | Affected roles | Regression test | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | `/health/deep` leaked infrastructure details | Public JSON echoed DB/Redis exception text (host, port, DB user) | The public health contract: report failure, never raise | Message is `unavailable`; the detail goes to the server log | None (public endpoint); monitoring loses the exception text | `test_health_deep_no_exception_leak_contract.py` (3) | SAFE |
| 2 | AI evaluation summary IDOR | Any role passing the AI feature gate could summarise **any** evaluation by ID, including other units and unpublished ones | `can_view_evaluation` (AI decision permission guard) | Feature gate plus object scope | Loses: `grup_baskani`/`koordinator` outside their unit; `baskan_yardimcisi`, `mali_musavir`, `birim_sorumlusu` except where they are an evaluator | `test_ai_performance_evaluation_object_scope_contract.py` (11) | SAFE (see decision 6) |
| 3 | AI recommendation JSON endpoints open to everyone | Login only: any user could list recommendations and change their status | Admin review queue gate: `admin_required` + menu `ai_center` | Same gate | Loses: `personel`, `koordinator`, `birim_sorumlusu`; admin-family roles unless they have `ai_center` (default: only `admin` has it) | `test_ai_recommendation_endpoints_authorization_contract.py` (5) | SAFE |
| 4 | Faz 2 survey manager pages open to employees | Menu `surveys` only: employees read other people's free-text answers | `communication_phase2_service.is_manager`, already required by every Faz 2 survey write action | Non-managers are redirected to the survey list | Loses: `personel`, `koordinator` | `test_communication_survey_manager_views_authorization_contract.py` (7) | SAFE |
| 5 | Cross-unit HR changes | Any manager could approve, reject or delete any leave, attendance or delegation record by ID | `build_user_scope_context(current_user, "all")`, the population the HR list pages show | Change allowed only when the record's person is in the caller's scope | Managers lose out-of-scope records; admin-family roles lose records owned by other `admin` accounts (those are not listed either) | `test_hr_leave_attendance_object_scope_contract.py` (8) | SAFE |

**BUSINESS POLICY INVENTED: NO.** Each fix applies a rule that already exists in the codebase. Fix 2 has a side effect
that follows from the existing AI-decision role sets and needs a human decision (item 6): `baskan_yardimcisi`,
`mali_musavir` and `birim_sorumlusu` pass the AI feature gate, but have no scope in the AI decision role sets.

### RED → GREEN proof on the final code (2026-09-29)

A scratch copy of the final tree was used, not the worktree. Each fix was removed from that copy and its regression test
run; the fix was then restored and the test run again.

| Fix | Fix removed | Fix restored |
|---|---|---|
| 1 health | 2 failed, 1 passed | 3 passed |
| 2 AI summaries | 4 failed, 7 passed | 11 passed |
| 3 AI recommendations | 3 failed, 2 passed | 5 passed |
| 4 Faz 2 surveys | 2 failed, 5 passed | 7 passed |
| 5 HR scope | 6 failed, 2 passed | 8 passed |

## 2. Fix details

### Fix 1 — `/health/deep` infrastructure leak (`app/core/healthcheck.py`)

- **Endpoint:** `GET /health/deep`. It is public by design and classified `PUBLIC_INTENTIONAL`.
- **Previous behaviour:** when the database or Redis was down, `checks.db.message` / `checks.redis.message` held
  `"<ExceptionClass>: <message>"`. For PostgreSQL that text includes host, port and database user; for Redis, host and
  port.
- **Proven incorrect behaviour:** an anonymous request made during an outage got that text. The test injects fabricated
  errors and asserts that none of the host, port, user or exception-class fragments appear in the response.
- **New behaviour:** status code (503), `status: degraded` and `ok: false` are unchanged. The message is `unavailable`.
  `logger.exception` records the full error on the server.
- **Roles:** none. Object scope: not applicable.

### Fix 2 — AI evaluation summaries (`app/services/ai/query_adapters.py`)

- **Endpoints:**
  - `GET /ai/performance/evaluation/<id>/summary`
  - `GET /ai/performance/evaluation/<id>/consistency`
  - `GET /ai/decision-support/performance/evaluation/<id>`

  All three go through `get_performance_evaluation_payload`. The decision-support route currently returns 400 before
  reaching the payload because its AI policy is undefined.
- **Previous behaviour:** only the feature gate `ensure_ai_access("performance", "summary"|"consistency")` applied, with
  default allowed roles `admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`, `mali_musavir`, `birim_sorumlusu` and
  `koordinator` (configurable). There was no object check.
- **Proven incorrect behaviour:** a unit manager obtained the AI summary of another unit's evaluation, and of an
  unpublished one.
- **Policy reused:** `app.services.ai_decision.permission_guard.can_view_evaluation`.
- **New behaviour:** the feature gate is unchanged. Then:
  - Full-scope roles (`admin`, `baskan`, `system_admin`, `ust_yonetim`, …) and HR/performance-authority roles (`ik`,
    `performans_yetkilisi`, …) see every evaluation.
  - The level 1–3 evaluators of that evaluation see it.
  - Manager-scope roles (`grup_baskani`, `koordinator`, `amir`, `yonetici`, `birim_amiri`, `mudur`) see evaluations of
    employees in the same `birim` or `ust_birim`.
  - Employees see their own evaluation only once it is published to them.
  - Everyone else gets 403.
- **Retain:** `admin` and `baskan` (all evaluations); evaluators; unit managers within their unit.
- **Lose:** `grup_baskani` and `koordinator` lose evaluations outside their unit unless they are the evaluator.
  `baskan_yardimcisi`, `mali_musavir` and `birim_sorumlusu` are `own_scope` in the AI-decision role sets, so they keep
  only evaluations where they are an evaluator.
- **Object scope changed:** yes; an object check was added.

### Fix 3 — AI recommendation JSON endpoints (`app/ai/routes.py`)

- **Endpoints:**
  - `POST /ai/recommendations/<id>/status`
  - `POST /ai/recommendations/<id>/apply`
  - `POST /ai/recommendations/bulk-apply`
  - `GET /ai/recommendations/list`
- **Previous behaviour:** `login_required` only.
- **Proven incorrect behaviour:** a `personel` user listed recommendations and changed their review status.
- **Policy reused:** the admin review queue `GET /admin/ai-recommendations`, which is gated by `login_required` +
  `admin_required` + `menu_key_required("ai_center")`.
- **New behaviour:** the same three decorators. `admin_required` means `admin`, `baskan`, `baskan_yardimcisi`,
  `grup_baskani` or `mali_musavir`. In the default role matrix only `admin` holds `ai_center` (measured with a fresh app
  and no overrides).
- **Retain:** `admin`, and admin-family roles that are granted `ai_center`.
- **Lose:** everyone else.
- **UI impact:** no template or script calls these JSON endpoints; the admin page posts to its own admin route.
- **Object scope changed:** no. This is a role gate only.

### Fix 4 — Faz 2 survey manager pages (`app/communication/phase2_routes.py`)

- **Endpoints:**
  - `GET /communication/faz2/surveys`
  - `GET /communication/faz2/surveys/<id>`
  - `GET /communication/faz2/surveys/<id>/results`
- **Previous behaviour:** `login_required` + menu `surveys`, which all 8 default roles hold.
- **Proven incorrect behaviour:** a `personel` user opened the results page, including free-text answers.
- **Policy reused:** `communication_phase2_service.is_manager` (`admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`,
  `mali_musavir`, `birim_sorumlusu`). The module's write actions already require it: new, edit, duplicate, archive,
  reopen, publish, close and template writes.
- **New behaviour:** non-managers get the flash "Bu işlem için yönetici yetkisi gerekir." and are redirected to
  `main.surveys_list`, where employees still answer surveys.
- **Lose:** `personel` and `koordinator`. `koordinator` is not in the communication manager set, which is already true
  for the write actions.
- **Object scope changed:** no.

### Fix 5 — HR leave / attendance / delegation changes (`app/institutional/hr_leave_attendance_routes.py`)

- **Endpoints:** `POST /hr-management/leave/<id>/status|delete`, `/attendance/<id>/status|delete`,
  `/delegations/<id>/status|delete`. Each is gated by `login_required` + `manager_required` +
  menu `hr_leave_tracking`.
- **Previous behaviour:** any manager-family user could change or delete any record by ID.
- **Proven incorrect behaviour:** a unit manager approved and deleted another unit's records.
- **Policy reused:** `build_user_scope_context(current_user, "all")` (`get_manager_scope_users`). The HR list pages filter
  with the same scope.
- **New behaviour:** the action runs only when the record's `user_id`, `delegator_user_id` or `delegate_user_id` is in the
  caller's scope. Otherwise the user sees "Bu kayıt yetki kapsamınız dışında." and nothing changes.

  | Role | Scope |
  |---|---|
  | `admin`, `baskan`, `baskan_yardimcisi` | all users except role `admin`, plus self |
  | `grup_baskani`, `mali_musavir` | users whose `birim` or `ust_birim` equals the caller's `birim`, plus self |
  | `koordinator`, `birim_sorumlusu` | direct reports (`yonetici_sicil` / `ikinci_yonetici_sicil`) and the same `birim`, plus self |
- **Object scope changed:** yes; an object check was added.

## 3. Human decisions (not resolved here — no policy is recommended)

### 3.1 Popup announcements — special report (HIGHEST PRIORITY)

**Routes.** All are in `app/communication/announcement_popup_routes.py`. Each management route also answers under an
`/announcements/manage/...` alias.

| Action | Route | Methods | Gate |
|---|---|---|---|
| List / manage | `/announcements/popup/manage`, `/announcements/popup`, `/announcements/manage` | GET | `login_required`, `menu_key_required("announcements")` |
| Create | `/announcements/popup/new` | GET, POST | same |
| Edit (any announcement, not only one's own) | `/announcements/popup/<id>/edit` | GET, POST | same |
| Deactivate / activate | `/announcements/popup/<id>/toggle` | POST | same |
| Target audience count | `/announcements/popup/<id>/target-count` | GET | same |
| Read report | `/announcements/popup/<id>/report` | GET | same |
| Export read report (CSV) | `/announcements/popup/<id>/report.csv` | GET | same |
| End user: pending popups | `/announcements/popup/runtime/pending` | GET | `login_required` |
| End user: acknowledge / dismiss (own record) | `/announcements/popup/<id>/acknowledge`, `/dismiss` | POST | `login_required`, CSRF-exempt |
| Media | `/announcements/popup/media/<path>` | GET | `login_required` |

No role check exists in these routes or in `app/services/announcement_popup_service.py`; the service only computes the
target audience.

**Who can reach management.** Measured with a fresh app, the default role matrix and no user overrides:

- the `announcements` menu is granted to all 8 default roles, including `personel`;
- `GET /announcements/popup/manage`, `/announcements/popup/new` and `/announcements/manage` returned **200 for every
  role**, `personel` included.

So create, edit, deactivate, read-report and CSV-export permissions all belong to every holder of the `announcements`
menu, which by default is everyone. The CSV contains, for each targeted user: user ID, full name, sicil no, e-mail,
role, unit, status, first/last shown, read time, dismiss time, show count, **IP address and browser**.

**Related policies.**

- **Bulletins (Faz 1):** the list sits under the same `announcements` menu, but create and publish require `is_manager`
  (`admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`, `mali_musavir`, `birim_sorumlusu`).
- **Portal announcements:** `can_publish_announcement` (`admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`,
  `mali_musavir`, `koordinator`, `birim_sorumlusu`).
- **The `announcements` menu key** serves both reading (bulletin list, acknowledgements) and popup management, so the
  menu alone cannot separate readers from publishers.

**Technical risk.** Any employee can:

- show a login popup to the whole institution;
- edit or switch off other people's popups;
- download read reports with colleagues' e-mail, IP and browser data.

**Options.**

- (a) Keep the current behaviour.
- (b) Require the bulletin `is_manager` set.
- (c) Require the portal `can_publish_announcement` set.
- (d) Admin only.
- (e) A separate menu key for popup management, so the role matrix decides.
- Separately, decide whether the read-report export must be narrower than create/edit.

**Decision question for the owner:** Who may create, edit, deactivate and export read reports for login popup
announcements? Today it is every holder of the `announcements` menu, which by default includes every employee. The
export contains every targeted user's e-mail, IP address and browser. Should it stay that way, or be limited to a
publisher set (bulletin managers, portal announcement publishers, admins only, or a new dedicated menu key)?

### 3.2 Faz 7 archive raw SQL (non-ORM columns)

- **CURRENT BEHAVIOR:** `GET /ai/decision-support/performance/archive/summary` and `/archive/user/<id>` read
  `performance_archived_results` columns `user_id`, `personnel_id`, `registry_no`, `personnel_name`, `period_year`,
  `period_title`, `score_value`, `score_label`, `general_comment` and `visibility_status`. Production has them (live
  validation, names only). The ORM and migrations do not, so both routes return 500 on a migration-built database. The
  person route is object-gated (`can_view_archive_detail`).
- **EXISTING RELATED POLICY:** ORM model `PerformanceArchivedResult` (`employee_id`, `result_year`, `period_label`,
  `score`, …); an earlier owner instruction to leave Faz 7 unchanged.
- **TECHNICAL RISK:** two column sets for the same data. A fresh install or disaster recovery from migrations breaks
  Faz 7.
- **OPTIONS:**
  - record the production column types read-only, then adopt them into the ORM and a migration;
  - move the Faz 7 SQL to the ORM columns, which needs a field mapping decision;
  - document and leave as is.
- **NO RECOMMENDED POLICY.**

### 3.3 `performance_interim_notes` shape

- **CURRENT BEHAVIOR:** Alembic creates the table, and three runtime creators define different shapes with alias
  columns:
  - mobile `_v2853_ensure_interim_notes_table`;
  - `interim_notes_runtime.ensure_interim_notes_table`, with the `_safe_add_column` repair;
  - `meeting_p2_archive_notes.ensure_interim_notes_table`.

  `performance_interim_notes_live` is a separate runtime-schema group.
- **EXISTING RELATED POLICY:** none recorded.
- **TECHNICAL RISK:** the shape depends on which path ran first, so it cannot be adopted into a migration without the
  production shape.
- **OPTIONS:** choose a canonical shape (read-only production check) and adopt it; make the runtime creators check-only;
  or keep them.
- **NO RECOMMENDED POLICY.**

### 3.4 `meeting_p4` extra recommendation columns

- **CURRENT BEHAVIOR:** `meeting_p4_development_guidance.ensure_recommendation_table` defines a second, conflicting
  shape for `performance_development_recommendations`. It is reachable from the manager-gated Faz 10 apply action.
- **EXISTING RELATED POLICY:** Alembic `29fee38a97e1` owns the canonical 46-column shape (runtime-schema group
  `performance.development_recommendations`).
- **TECHNICAL RISK:** extra columns may exist in production and diverge from both the ORM and Alembic.
- **OPTIONS:** adopt the extra columns; make the meeting_p4 creator check-only; or keep both.
- **NO RECOMMENDED POLICY.**

### 3.5 Setup actions that create schema from the web

- **CURRENT BEHAVIOR:**
  - `POST /support/setup` (`admin_required` + menu `support_index`) runs `__table__.create(checkfirst=True)` for the
    support tables, which Alembic `a3d8f1c9b6e2` already owns.
  - The meeting-development P2/P3/P4 apply actions (`manager_required`, 7 roles including `koordinator` and
    `birim_sorumlusu`) create or alter tables at runtime: archive notes, interim notes, reminder queue, overdue
    snapshots and recommendations.
- **EXISTING RELATED POLICY:** this branch moved all GET-time DDL to the operator CLI `flask runtime-schema provision`.
  POST setup actions were left unchanged.
- **TECHNICAL RISK:** non-DBA users change the schema; PostgreSQL lock waits; shapes diverge.
- **OPTIONS:** keep; restrict to admin; convert to check-only and use CLI provisioning.
- **NO RECOMMENDED POLICY.**

### 3.6 AI decision scope of `birim_sorumlusu` (and `baskan_yardimcisi`, `mali_musavir`)

- **CURRENT BEHAVIOR:** these roles pass the AI feature gate and `MANAGER_FAMILY_ROLES`, but none of the AI-decision
  role sets includes them, so they are `own_scope`. After fix 2 they get AI evaluation summaries only where they are an
  evaluator.
- **EXISTING RELATED POLICY:**
  - AI decision role sets in `app/services/ai_decision/visibility_scope.py`: full scope (`admin`, `baskan`,
    `ust_yonetim`, …), HR/performance authority, and manager scope (`grup_baskani`, `koordinator`, `amir`, …);
  - `route_support.MANAGER_FAMILY_ROLES`.
- **TECHNICAL RISK:** two role vocabularies disagree. That means either over-restriction (for example, the vice
  president) or, if widened, broader access to evaluation data.
- **OPTIONS:**
  - add the three roles to the manager scope;
  - add `baskan_yardimcisi` to full scope;
  - keep the current behaviour.
- **NO RECOMMENDED POLICY.**

### 3.7 Draft bulletin title visibility

- **CURRENT BEHAVIOR:**
  - `GET /communication/faz1/bulletins` (menu `announcements`) lists up to 50 bulletins, including drafts, to every
    menu holder;
  - `GET /communication/faz2/bulletins/<id>/history` has no manager check.
- **EXISTING RELATED POLICY:** creating and publishing bulletins requires `is_manager`.
- **TECHNICAL RISK:** unpublished titles and metadata are visible to employees.
- **OPTIONS:** show drafts to managers only; keep.
- **NO RECOMMENDED POLICY.**

### 3.8 Employee access to Faz 4 survey analytics

- **CURRENT BEHAVIOR:** `GET /communication/faz4/surveys/analytics` (menu `surveys`, held by every role) shows
  per-survey completion metrics, including drafts.
- **EXISTING RELATED POLICY:** Faz 2 results are now manager-only; the `survey_results` menu is not granted to
  `personel`.
- **TECHNICAL RISK:** aggregate participation data is visible to employees.
- **OPTIONS:** require `is_manager` or the `survey_results` menu; keep.
- **NO RECOMMENDED POLICY.**

### 3.9 Employee access to the Faz 8 scope check

- **CURRENT BEHAVIOR:** `GET /ai/decision-support/performance/periods/<id>/scope-check` is `login_required` only. It
  returns aggregate period metadata and counts, with no person data.
- **EXISTING RELATED POLICY:** Faz 3/4 AI decision routes call `assert_center_access`, which denies `own_scope` roles.
- **TECHNICAL RISK:** low. The metadata exposure is minor, but the gating is inconsistent.
- **OPTIONS:** add `assert_center_access`; keep.
- **NO RECOMMENDED POLICY.**

### 3.10 Per-user menu permission lookup failure

- **CURRENT BEHAVIOR:** `_load_user_override_state` uses `_safe_query_all`, which returns an empty list **without
  logging** on a database error. The effective menu then falls back to role and unit defaults:
  - per-user **deny** overrides disappear (fail-open);
  - per-user **grant** overrides disappear (fail-closed).
- **EXISTING RELATED POLICY:** `menu_key_required` treats the effective menu map as the final authority. No written rule
  covers failures.
- **TECHNICAL RISK:** during a database fault on `user_menu_permissions`, a user explicitly denied a menu regains it
  through the role default.
- **OPTIONS:**
  - fail closed (deny all menus when overrides are unreadable);
  - keep the fallback but log it;
  - fail closed only for request types that change data.
- **NO RECOMMENDED POLICY.**

**Other open policy questions** (recorded in the matrix):

- any manager can change or publish any feedback campaign;
- the AI policies `performance/decision_support` and `category_group_decision_support` are undefined, so those routes
  always return 400;
- 46 routes remain `NEEDS_REVIEW`.

## 4. Authorization matrix verification (`reports/quality/BYS360_AUTHORIZATION_MATRIX_V1.json`)

**Counts** (recomputed from the rows; they match the summary):

| Classification | Routes |
|---|---:|
| PUBLIC_INTENTIONAL | 23 |
| AUTHENTICATED_ONLY | 182 |
| ROLE_GATED | 593 |
| OBJECT_GATED | 152 |
| NEEDS_REVIEW | 46 |
| **Total registered** | **996** |

110 routes were reviewed by hand; 260 routes take an object parameter.

**What the contract test checks** (`tests/security/test_authorization_matrix_contract.py`). It builds the real app and
enumerates the **registered** `url_map` (996 rules), so it does not grep source text for routes. For each registered
view it decides "authenticated" by statically inspecting the resolved view function: the decorator chain via
`inspect.unwrap` and wrapper names, the body source, known app and blueprint guards, and `MANUAL_REVIEW`. It sends no
HTTP request. Two parts are heuristic:

- "Intentionally public" is an endpoint-name regex (`login|password|guest|share|public|metrics|manifest|…`), not an
  explicit allowlist. A new unauthenticated route with a public-sounding name would pass unnoticed.
- A route counts as authenticated if its blueprint is `ai_agent` or `hierarchy_governance` (assumed `before_request`
  guards), or if its body contains the text `current_user.is_authenticated`.

**Empirical check.** Every registered rule except `static` (995) was requested anonymously against a fresh app.

- 976 were blocked: 797 redirected to login, 108 returned 403, 71 returned 401.
- 19 answered: the 18 reachable matrix-public endpoints, plus **`/ai-agent/healthz`**.
- The 4 remaining public entries redirect to login or return 401 by design: `/`, `/logout`, `/setup-admin` once a user
  exists, and `/api/mobile/auth/refresh` without a token.

**Finding (REVIEW, not a vulnerability).** `/ai-agent/healthz` answers anonymously with 200, but the matrix classifies it
`AUTHENTICATED_ONLY`. The generator assumes the `ai_agent` blueprint guard authenticates. In fact
`_bys360_ag2b_ai_agent_before_request` lets anonymous requests through; the other `ai_agent` routes are protected by
their own `@login_required`. The endpoint is documented in code as a deliberate public smoke check. Its anonymous
payload has status, service, version, mode and bridge booleans, with no hosts, users or errors. Consequence: the
contract test would not catch a **new** `ai_agent` route that forgets `@login_required`. Suggested follow-up, not done
here because it changes test tooling:

- mark `ai_agent.ai_agent_public_healthz` `PUBLIC_INTENTIONAL` in `MANUAL_REVIEW`;
- drop the blueprint-guard assumption;
- add a runtime anonymous-probe contract with an explicit public allowlist.

**Intentional public endpoints (23, all confirmed intentional):**

- page entry and session: `/` (redirects to login), `/login`, `/logout`, `/forgot-password`;
- health and readiness: `/health`, `/health/deep` (fixed), `/healthz`, `/readyz`, `/versionz`;
- static and PWA: `static`, `/manifest.webmanifest` (two endpoints), `/bys360-sw.js`, `/service-worker.js`,
  `/offline`, `/pwa/csrf-refresh`;
- mobile protocol: `/api/mobile/auth/login`, `/api/mobile/auth/refresh`, `/api/mobile/health`;
- token-gated guest links: `/guest/files/<token>`, `/guest/upload/<token>`;
- other: `/kunye` (institutional imprint), `/setup-admin` (404 unless explicitly permitted; redirects once any user
  exists).

No authentication was forced onto these protocol endpoints.

## 5. File Center test fix review

- **Production code changed: NO.** The commit changed only
  `tests/behavior/test_file_center_anonymous_guest_access_contract.py`, and no File Center application file changed
  anywhere on the branch.
- **Change:** the two isolation assertions changed from `str(path).startswith(_TMP_STORAGE_ROOT)` to
  `Path(path).resolve().is_relative_to(Path(_TMP_STORAGE_ROOT).resolve())`. The test still writes and reads the real
  file, so the containment property it checks is the same.
- **Measured on Windows (Python 3.12)** with the same expression:

  | Case | Expected | New check | Old prefix check |
  |---|---|---|---|
  | child, long form (the application's view) | inside | inside | **outside** (the original failure) |
  | child, 8.3 short form | inside | inside | outside |
  | root itself | inside | inside | inside |
  | sibling directory sharing the prefix | outside | outside | **inside** (the old check was weaker) |
  | `..` traversal out of the root | outside | outside | **inside** (the old check was weaker) |
  | unrelated absolute path | outside | outside | outside |
  | other drive | outside | outside | outside |

  A symlink escaping the root could not be tested: the account lacks the Windows symlink privilege. `resolve()` follows
  symlinks, so such a path resolves outside the root and fails the check.
- **POSIX:** both sides go through `resolve()`, and `is_relative_to` compares path components, so POSIX behaviour is
  the same comparison. This was not executed on POSIX in this session.
- **Security assertion weakened: NO.** It is strictly stronger than the prefix check.
