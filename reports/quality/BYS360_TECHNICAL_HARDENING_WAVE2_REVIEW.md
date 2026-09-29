# BYS360 Technical Hardening Wave 2 Review — 2026-09-29

- **Branch:** `fix/technical-hardening-wave2`
- **Base:** `assistant-v2-full` at `40b93c146bb15c7877b88e3cc9b3b9bc591b30f8`
- **Scope:** authorization defects, regression protection, and review-only findings.
- **Unchanged:** no migration, no schema change, and no new business rule.

The production identity is separate from this branch and is unchanged:

| Item | Value |
|---|---|
| Source SHA | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` |
| Tag | `bys360-prod-2026.09.29-a5bd8a38` |
| Migration head | `w2d8e1f4a6c3` |

Nothing on this branch is deployed.

Default roles (`app/admin/routes.py` `ROLE_CHOICES`): `admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`,
`mali_musavir`, `birim_sorumlusu`, `koordinator`, `personel`.

## 1. Fixed technical defects

Every fix applies a rule the codebase already enforces on a neighbouring path of the same object. Typically the read
path checked a scope that the write path skipped. **BUSINESS POLICY INVENTED: NO.**

| # | Severity | Component | Defect | Rule reused | Regression test |
|---|---|---|---|---|---|
| 1 | HIGH | `POST /communication/faz3/support/<id>` | Any `support_all` menu holder could post to any ticket and notify its creator and assignee. By default that includes `koordinator`, which is not a Faz 3 manager. | The read rule of the same route (`support_detail_payload`): manager, creator or assignee | `test_communication_phase3_support_message_scope_contract.py` |
| 2 | HIGH | `POST /support/<id>/status`, `POST /support/<id>/assign` | A manager outside the ticket's unit could close a private ticket. The same manager could also assign it to themselves and then read it as its assignee. | `_can_operate_ticket` (Phase 13B private-ticket unit scope), already used by `/support/<id>` and `/support/<id>/comment` | `test_support_private_ticket_write_scope_contract.py` (5) |
| 3 | HIGH | Faz 3 support detail/assign/status, queue and detail pages | (a) Faz 3 ignored the Phase 13B private-ticket unit scope. (b) The queue and ticket pages answered 500 as soon as one ticket was visible. | The same Phase 13B rule, now in one shared helper | `test_communication_phase3_support_message_scope_contract.py` (9, shared with #1) |
| 4 | MEDIUM | Authorization matrix and anonymous access | The static matrix counted the `ai_agent` blueprint hook as a login guard. The hook lets anonymous requests through, so a new unguarded `ai_agent` route would have passed. | The explicit public-endpoint list | `test_anonymous_route_runtime_contract.py` (3) |
| 5 | LOW | `POST /ai/feedback/<id>` | A missing AI request log, or a `feedback_type` longer than 30, produced a 500 on PostgreSQL. SQLite stored an orphan row instead. | The route's existing `AIResourceNotFound` → 404 and `AIInputError` → 400 mapping | `test_ai_feedback_input_contract.py` (3) |

### RED → GREEN proof

The proof ran on a scratch export of `e3f83248`, not on the worktree. For each case the fix was removed and its test
run, then the fix was restored and the test run again. For the two lock tests (§2), a negative control removes the
guard they lock.

| Case | What was removed | Fix removed | Fix restored |
|---|---|---|---|
| 1 | Access check in `add_support_message` | 2 failed, 7 passed | 9 passed |
| 2 | The two `_can_operate_ticket` checks added to `support_status` and `support_assign` | 2 failed, 3 passed | 5 passed |
| 3a | `can_view_private_support_ticket` in `_can_access_ticket` | 2 failed, 7 passed | 9 passed |
| 3b | SLA snapshot reverted to `ticket.messages.filter(...)` | 2 failed, 7 passed | 9 passed |
| 4 | Negative control: `@login_required` removed from `/ai-agent/health` | 1 failed, 2 passed | 3 passed |
| 5 | `app/services/ai/audit.py` reverted to base | 2 failed, 1 passed | 3 passed |
| lock | HR: `user_id` scope filter removed from `_asset_in_scope` and `_review_in_scope` | 2 failed, 2 passed | 4 passed |
| lock | Archive: `can_manage_archive` made true for every logged-in user | 2 failed, 1 passed | 3 passed |

### Fix 1 — Faz 3 support message authorization (`app/services/communication_phase3_service.py`)

**Endpoint:** `GET|POST /communication/faz3/support/<ticket_id>`. The route needs the `support_all` menu.

**Previous behaviour**
- The GET branch showed a ticket only to a Faz 3 manager, its creator or its assignee (`support_detail_payload`).
- The POST branch called `add_support_message` before that check, and `add_support_message` had no check of its own.
- Faz 3 managers (`MANAGER_ROLES`) are `admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`, `mali_musavir` and
  `birim_sorumlusu`.

**Proven incorrect behaviour:** a `koordinator` who is neither creator nor assignee could not read ticket T. The same
user could still add a message to T, and the creator and assignee were notified.

**New behaviour**
- `add_support_message` applies `_can_access_ticket`, the rule the read path uses.
- A refused post raises `CommunicationPhase3Error`, which the route already flashes, and nothing is stored.
- Creator and assignee keep access. Managers keep access within the private-ticket scope (Fix 3).

**Roles that lose access:** any non-manager holding `support_all`, which by default means `koordinator`. They can no
longer post to tickets they did not create and are not assigned to.

### Fix 2 — `/support` status and assignment on private tickets (`app/support/routes.py`)

**Endpoints:** `POST /support/<ticket_id>/status` and `POST /support/<ticket_id>/assign`.

**Previous behaviour:** only `_can_use_all_support_view()` was checked, the all-tickets permission.
- `GET /support/<id>` and `POST /support/<id>/comment` already used `_can_operate_ticket`.
- For users other than the creator and assignee, `_can_operate_ticket` adds the Phase 13B private-ticket unit scope
  (`_can_view_private_scope`).

**Proven incorrect behaviour**
- A `birim_sorumlusu` of unit B closed a private ticket of unit A.
- The same user assigned that ticket to themselves and could then open it as its assignee.

**New behaviour:** both routes call `_can_operate_ticket` after loading the ticket and answer 403 when it fails.
- Same-unit managers and the admin family keep access.
- Tickets that are not private are unaffected.

### Fix 3 — Faz 3 private-ticket scope and the Faz 3 support 500 (`communication_phase3_service.py`, `support_ticket_access.py`, `phase3_routes.py`)

**(a) Private-ticket scope**

**Endpoints:**
- `GET|POST /communication/faz3/support/<id>`
- `POST /communication/faz3/support/<id>/assign`
- `POST /communication/faz3/support/<id>/status`

**Previous behaviour:** any Faz 3 manager, `birim_sorumlusu` included, could read, answer, assign or close a private
ticket of another unit. `/support/<id>` already refuses this under Phase 13B.

**New behaviour**
- `_can_access_ticket` allows the creator and the assignee. It also allows a Faz 3 manager, but only when that manager
  passes `can_view_private_support_ticket`.
- `assign_support_ticket` and `update_support_status` take a keyword-only `actor_user`. The Faz 3 routes pass it, and
  the check applies whenever it is given.
- Existing callers that do not pass `actor_user` behave as before.

**Shared helper:** the Phase 13B rule moved from `app/support/routes.py` into the new
`app/services/support_ticket_access.py` (`can_view_private_support_ticket`). `/support` and Faz 3 now call the same
function. The helper body is the same code as before, so `/support` behaviour does not change.

`app/route_support.py` was deliberately not edited. `test_route_support_safe_url_for_is_untouched` pins that file.

**(b) Faz 3 support 500**

**Endpoints:** `/communication/faz3/support/queue` and `/communication/faz3/support/<id>`. Both answered 500 as soon as
one ticket was visible.

**Cause:** `_sla_snapshot_for_ticket` called `.filter()` on `SupportTicket.messages`. That relationship is a plain list
(ordered by `created_at`), not a dynamic query.

**New behaviour:** the first non-internal message is taken from the list, with the same ordering and the same result.

**Regression test:** `test_manager_can_open_the_queue_and_a_ticket`.

### Fix 4 — Anonymous-route contract and authorization matrix (tests and `scripts/quality/bys360_authorization_matrix.py`)

**Runtime behaviour:** no production code changed.

**Defect in the protection:** the static matrix treated the `ai_agent` blueprint's `before_request` as a login guard.
That hook lets anonymous requests through, so `tests/security/test_authorization_matrix_contract.py` would have
accepted a new `ai_agent` route with no `@login_required`.

**Matrix script changes**
- The blueprint-guard assumption for `ai_agent` was removed. Each route is now judged by its own decorators and body.
  - A body check of `current_user.is_authenticated` is recognised.
  - `can_manage_ai_knowledge()` is listed in `AUTHENTICATED_BY_HELPER`; it returns `False` for anonymous users.
- `ai_agent.ai_agent_public_healthz` is reclassified `PUBLIC_INTENTIONAL`. It returns status, service, version, mode
  and bridge flags only.
- `summary.fixed_2026_09_28` became `summary.fixed_by_review_date`, which is parsed from the `FIXED <date>:` notes.
- View locations are now repo-relative, or `site-packages/...` for installed packages. The previous output contained
  a machine-specific absolute path.

**New runtime contract** (`test_anonymous_route_runtime_contract.py`)
- One anonymous request goes to every registered rule (994 rules).
- Every endpoint outside an explicit 20-endpoint allowlist must answer 401/403 or redirect to `/login`.
- No rule may answer 5xx.
- Runtime is about 8 s.

**Result at HEAD:** 795 login redirects, 108 × 403, 71 × 401, 19 × 200 and 1 × 400. The 200s and the 400 are all on
the allowlist; the 400 is `mobile_login` with an empty body. There were no 5xx.

### Fix 5 — `POST /ai/feedback/<ai_request_log_id>` input validation (`app/services/ai/audit.py`)

**Previous behaviour:** `log_ai_feedback` inserted without checking that the AI request log exists, and without
checking `feedback_type` against its `String(30)` column.
- On PostgreSQL, the FK or length violation surfaced at flush as the route's generic 500.
- On SQLite, which does not enforce FKs, a row pointing at no request log was stored.

**New behaviour**
- A missing log raises `AIResourceNotFound`, answered as 404.
- An oversized type raises `AIInputError`, answered as 400.
- In both cases nothing is stored.
- Valid feedback is unchanged.

**Still open:** the ownership question (may any user attach feedback to any log?) is a human decision (§6). The matrix
keeps this route `NEEDS_REVIEW`.

## 2. Test coverage improvements

| Test file | Tests | What it locks |
|---|---|---|
| `tests/security/test_communication_phase3_support_message_scope_contract.py` | 9 | Fixes 1 and 3 |
| `tests/security/test_support_private_ticket_write_scope_contract.py` | 5 | Fix 2 |
| `tests/security/test_anonymous_route_runtime_contract.py` | 3 | Fix 4: every route vs. the anonymous allowlist, no 5xx, allowlist names real endpoints |
| `tests/security/test_ai_feedback_input_contract.py` | 3 | Fix 5 |
| `tests/integration/test_hr_personnel_operations_object_scope_contract.py` | 4 | An IK `birim_sorumlusu` cannot return or delete a Finans employee's asset, delete their checklist, or complete their request task. Behaviour was already correct; the routes were untested and ranked HIGH (§4). |
| `tests/security/test_performance_archive_write_authorization_contract.py` | 3 | `personel` and `birim_sorumlusu` get 403 on `/performans/gecmis-karne-arsivi/{yeni,excel,excel-sablon}` and store nothing; `admin` gets 200. Behaviour was already correct; untested and ranked HIGH. |

In total: 27 new tests in 6 files. Matrix routes without a test reference went from 440 to 431.

## 3. NEEDS_REVIEW routes (46 at base, 40 at HEAD)

Categories:
- **A** — TECHNICAL_DEFECT
- **B** — TEST_GAP
- **C** — DOCUMENTATION_GAP
- **D** — HUMAN_POLICY_REQUIRED
- **E** — FALSE_POSITIVE / already protected

No route was B or C only.

| Category | Routes | Guard in code | Outcome |
|---|---|---|---|
| A | `communication_phase3_support_detail`, `_assign`, `_status`; `support_assign` | menu `support_all` + `is_manager` / `_can_use_all_support_view` | Fixed (Fixes 1–3) → `OBJECT_GATED` |
| A | `ai_feedback` | `login_required` | Error behaviour fixed (Fix 5); ownership → D, stays `NEEDS_REVIEW` |
| D | 15 popup announcement rules (`announcement_popup_manage/new/edit/toggle/report/report_csv/target_count`, both `/announcements/manage/...` and `/announcements/popup/...`) | menu `announcements` only | §6 H1 |
| D | `communication_phase1_bulletin_detail`, `communication_phase2_bulletin_history` | menu `announcements` (+ `is_manager` for content on Faz 1) | §6 H2 |
| D | `communication_phase4_survey_analytics` | menu `surveys` | §6 H4 |
| D | `communication_phase4_submit_review` | menu | §6 H9 |
| D | `ai_decision_performance_category_groups_for_period` | `login_required` | Always 400: AI policy undefined (§6 H8) |
| E | `communication_phase1_bulletin_publish`; Faz 2 `bulletin_edit/archive`, `survey_archive/close/duplicate/edit/publish/reopen`, `survey_template_edit`; `communication_phase3_survey_remind`; `communication_phase4_governance_decide` | menu + inline `is_manager(current_user)` | Role-gated in code; the ownership question is §6 H5 |
| E | `feedback_campaign_close`, `feedback_results_export` | `manager_required` + `_require_role_family` (+ `_can_export_feedback_now`) | Role-gated; export matches the list page scope |
| E | Legacy `survey_publish/unpublish/close/archive/restore` | menu + `_manager_allowed()` | Role-gated; §6 H5 |
| E | `portal_press_news_publish`, `portal_press_news_archive` | `_portal_press_news_admin_only_allowed` inline | Admin roles only → reclassified `ROLE_GATED` |

`support_status` was `ROLE_GATED` at base, not `NEEDS_REVIEW`. It carried the same defect as `support_assign` and was
fixed with it (Fix 2).

Summary by count: A 5, D 20, E 21. Base had 46; 6 moved out (4 fixed, 2 portal), leaving 40.

## 4. Routes without a test reference — risk ranking

- **Input:** 437 non-public routes with `test_files == 0` in the matrix at the time of ranking.
- **Score:**
  - mutation method +3
  - destructive verb +2
  - object id +2
  - each sensitive area +2 (HR/personnel, performance/AI evaluation, survey/feedback, file access, messages)
  - upload/download/export +2
  - login-only with an object id +2
  - admin/manager decorator +1
- **Tiers:** CRITICAL ≥ 11, HIGH 8–10, MEDIUM 5–7, LOW ≤ 4.

**Result:** CRITICAL 0, HIGH 7, MEDIUM 89, LOW 341.

| HIGH route | Class | Outcome |
|---|---|---|
| `POST /hr-management/personnel-operations/assets/<id>/delete` | OBJECT_GATED | Test added (§2) |
| `POST /hr-management/personnel-operations/assets/<id>/return` | OBJECT_GATED | Test added |
| `POST /hr-management/personnel-operations/checklists/<id>/delete` | OBJECT_GATED | Test added |
| `POST /hr-management/personnel-operations/request-task/<id>/complete` | OBJECT_GATED | Test added |
| `GET POST /performans/gecmis-karne-arsivi/excel` | ROLE_GATED | Test added, with `/yeni` and `/excel-sablon` |
| `POST /admin/ai-redaction-rules/<id>/toggle` | ROLE_GATED | Covered by the `/admin/*` path guard contract; no test added |
| `GET /ai/decision-support/performance/archive/user/<id>` | OBJECT_GATED | Faz 7 archive, schema DEFERRED (§7); no test added |

**MEDIUM routes (89):**

| Area | Routes |
|---|---|
| `/performance` | 27 |
| `/hr-management` | 23 |
| `/performans` | 12 |
| `/file-center` | 5 |
| `/communication` | 4 |
| `/admin` | 4 |
| `/feedback` | 4 |
| other | 10 |

The main score drivers were mutation (77), admin/manager decorator (46), object id (31) and HR (29). These routes are
role- or object-gated in the matrix, and no defect was found in the ones reviewed. They are left for later waves rather
than covered by shallow tests.

## 5. No-change findings (reviewed, no defect proven)

- **`/ai-agent/healthz`:** public by design. It returns status, service, version, mode and bridge flags only. It is now
  classified `PUBLIC_INTENTIONAL` and listed in the runtime allowlist.
- **Popup acknowledge/dismiss:** protected by a one-time runtime token and a SameSite=Lax session cookie.
- **File Center guest links:**
  - SHA-256 token, with expiry and a maximum download count.
  - Rate limits of 20/hour for download and 10/hour for upload.
- **Support attachment download:** checks `_can_view_ticket`, the ticket page's rule, and looks up the attachment by
  both its own id and the ticket id.
- **Survey take/submit:** limited to the respondent's assignment.
- **`hierarchy_governance`:** its `before_request` is `@login_required`.
- **HR personnel operations:** asset, checklist, document and task actions filter by the caller's scope user ids.
  Locked by the new test.
- **Feedback export:** uses the same campaign scope as the results page.
- **Exception text:** no reviewed handler returns an unexpected exception's text to the client. The `str(exc)` responses
  found return domain errors with fixed messages (`AIInputError`, `CommunicationPhase3Error`).
- **Missing records, anonymous:** no 5xx on any of the 994 rules.
- **Missing records, authenticated:** see §7.

## 6. Human decision required

Each item below needs a decision that the repository cannot prove. No runtime behaviour was changed for any of them.
Item numbers refer to `BYS360_PRE_PUSH_AUTHORIZATION_REVIEW.md` §3 where one exists.

| ID | Exact question | Affected routes/files | Evidence | Why code must not decide |
|---|---|---|---|---|
| H1 (3.1, HIGH) | Who may create, edit, toggle and read reports of popup announcements? | `app/communication/announcement_popup_routes.py`, 15 rules | Only menu `announcements` is checked, and static defaults grant it to `personel`. Bulletins (`is_manager`) and portal (`can_publish_announcement`) exclude employees. | Which roles publish institution-wide popups is institutional policy |
| H2 (3.7) | May every `announcements` holder see draft bulletins? | Faz 1 bulletin list and detail, Faz 2 bulletin history | Faz 1 detail shows the full draft and all read receipts. Faz 2 history shows draft titles. | Draft visibility is an editorial policy |
| H3 | Who may see the title and metadata of private support tickets? | `/support/all`, the Faz 3 queue, `POST /communication/faz4/export` (support export type) | Fixes 2 and 3 protect the ticket body and actions. The listing and export still show titles of other units' private tickets. | The Phase 13B scope covers opening a ticket; nothing says whether titles are also private |
| H4 (3.8) | Should employees see Faz 4 survey analytics, drafts included? | `communication_phase4_survey_analytics` | Menu `surveys` only, which employees hold | Employee access policy |
| H5 | May any manager edit, publish, close or archive another manager's bulletin, survey or feedback campaign? | Category E routes in §3 | The role gate is enforced; there is no creator or unit check anywhere in these modules | Ownership rules are organisational |
| H6 | Anonymous surveys accept several submissions from the same user even when `allow_multiple_submissions=False` | `GET /surveys/<id>/take`, `POST /surveys/<id>/submit` (`app/communication/surveys_routes.py`) | The single-response check is skipped when `is_anonymous` (`if not survey.allow_multiple_submissions and not survey.is_anonymous`), and no per-user record is kept | Anonymity versus single response is a policy trade-off |
| H7 (3.10) | Should a failed per-user menu override lookup fail open (static defaults) or closed? | `app/services/settings/effective_menu_parts/bys360_context.py` `_safe_query_all` | The failure is swallowed silently | Availability versus access policy |
| H8 (3.6) | The AI decision scope of `birim_sorumlusu`, `baskan_yardimcisi` and `mali_musavir`; and the undefined AI policy `performance/category_group_decision_support` | `app/services/ai_decision/*`; the category-groups route (always 400) | The AI role sets give these roles `own_scope`. The category route's GET creates recommendations with `commit=True` once a policy exists. | AI authority is policy |
| H9 | May the author of a Faz 4 report submit it for review and then decide on it? Who may decide governance reviews? | `communication_phase4_submit_review`, `communication_phase4_governance_decide` | There is no self-approval check | Segregation-of-duties rule |
| H10 (3.9) | Should the Faz 8 scope check require AI center access? | `GET /ai/decision-support/performance/periods/<id>/scope-check` | `login_required` only; it returns aggregate period metadata and counts, while Faz 3/4 AI decision routes call `assert_center_access` | Employee access policy |
| H11 | May any user attach feedback to any AI request log? | `ai_feedback` | Only the new row id is returned (low impact) | Ownership policy |

Schema items 3.2–3.5 of the pre-push review remain open and are listed in §7.

## 7. Schema / database

This section is repository and ephemeral-database evidence only. There was no production access.

### Auxiliary run on PostgreSQL 16 — this is NOT the PostgreSQL 15 gate

PostgreSQL 15 could not be installed in the review container. The same gate script was run against a local, empty
PostgreSQL 16 cluster, with the required major overridden at runtime; no file was changed.

The script's step names contain "POSTGRES15"; the server was 16. **The authoritative PostgreSQL 15 result is the CI job
on the pull request.**

| Step | Result on PG 16 |
|---|---|
| Empty DB guard | PASS |
| Revisions | 79 revisions, 10 roots, 1 head (`w2d8e1f4a6c3`), no cycles |
| Empty → head | PASS |
| Head match | PASS |
| Second upgrade (no-op) | PASS |
| Schema introspection | PASS (9 tables) |
| Column introspection | PASS (37 columns) |
| ORM parity | PASS (164 tables, 2061 columns) |
| Runtime schema | PASS: 15 groups provisioned and verified; second provision is a no-op |

The same migration-built PG 16 database was then used for an authenticated GET probe of 670 routes, with missing ids,
as `admin`, `personel`, `birim_sorumlusu` and `koordinator`.
- Only 2 routes answered 500, for all four roles:
  - `/ai/decision-support/performance/archive/summary`
  - `/ai/decision-support/performance/archive/user/<id>`
- Both read production-only columns of `performance_archived_results`.
- On SQLite (`create_all`) the admin probe showed 3 more 500s, on `performance_president_card_review`. They do not occur
  on the migration-built schema.

### Deferred (needs production evidence)

These items are not changed:
- Faz 7 archive columns (pre-push review 3.2); the two 500s above.
- `performance_interim_notes` shapes (3.3).
- `scoring_history` production columns.
- `meeting_p4` extra recommendation columns (3.4).
- `feedback_action_plans` columns.
- `message_*` server-default differences.
- The known 12 column type/nullability differences.
- ORM indexes that no migration creates.
- Two possibly dead portal models.
- Setup actions that create schema from the web (3.5).

There is no migration on this branch, and the migration head is still `w2d8e1f4a6c3`.

## 8. Maintainability findings (report only)

- **Duplicated manager role sets.** `MANAGER_ROLES` is defined 18 times under `app/`, with at least two different
  memberships.
  - Faz 1–5 communication services: admin family + `birim_sorumlusu`.
  - `feedback_service` and `role_matrix_ui_service`: also `koordinator`.

  Fix 1 exists because two paths of one route used different notions of "may handle a ticket". A single role-set
  module would remove this class of defect, but changing it is a policy-bearing refactor and is not done here.
- **Duplicated private-ticket scope.** It was duplicated between `/support` and Faz 3. It is now one helper,
  `app/services/support_ticket_access.py`.
- **Unused modules.** `communication_required_service.py` and `communication_family_service.py` are not imported
  anywhere. They are referenced only as strings in `app/refactor/*` specs.
- **Mobile roles.** The mobile API `_GLOBAL_ROLES` (`app/api/mobile/shared.py`) includes roles that are not in
  `ROLE_CHOICES`.
- **Menu override failure.** It is swallowed silently (`_safe_query_all`); see H7.
- **Machine-specific matrix path.** The authorization matrix used to emit a machine-specific absolute path. Fixed in
  `e3f83248`.

## 9. Quality results

**Environment:** Linux, Python 3.12.3, run in scratch copies. The CI commands of `.github/workflows/bys360-ci.yml` were
used unchanged.
- The pytest steps ran on the code HEAD `e3f83248`. The only later commit adds this document.
- The fast gates ran on `8bd3f91a`.

### Pytest

| Step | Base `40b93c14` | HEAD `e3f83248` |
|---|---|---|
| Step 1: `pytest tests/quality -m ci_safe` | 1200 collected: 985 passed, 0 failed, 133 skipped, 82 deselected | 1200 collected: 985 passed, 0 failed, 133 skipped, 82 deselected |
| Step 2: long CI list (integration, architecture, security, critical, services, migrations, release, communication, behavior, mobile, performance, …) | 6366 collected: 6358 passed, 0 failed, 8 skipped | 6393 collected: 6385 passed, 0 failed, 8 skipped |

The Step 2 difference is +27 passed, which is exactly the 27 new tests.

### Other gates

| Gate | Result |
|---|---|
| Coverage ratchet | PASS. 45.77% at base, 46.09% at HEAD; threshold 27.12%. |
| `git diff --check` (base..HEAD) | clean |
| Ruff full select (`app config.py wsgi.py run.py scripts tests`) | All checks passed |
| Ruff sanity (`E9,F63,F7,F82`) | All checks passed |
| `compileall` | OK |
| mypy (`app tests scripts`) | 0 errors |
| pip-audit (`requirements.txt`, unchanged) | No known vulnerabilities found |
| Secret/repo gate | ok. 0 findings; 475 warnings (464 at base). The +11 are test password constants in the new tests; this document adds none. |
| Safe-release audit | ok, 0 findings |
| Ops audit (CI mode) | 0 syntax errors, 0 print calls, 2083 broad `except` (limit 2300) |
| Quality9 CI gate | ok, 0 findings |
| Score100 quality gate (Python part) | PASS |
| Migration integrity gate | PASS on PostgreSQL **16**, auxiliary only (§7) |
| PostgreSQL 15 migration integrity gate | Runs in the pull request's CI; not run here |
