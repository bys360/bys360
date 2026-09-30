# BYS360 Technical Hardening Wave 3 Review — 2026-09-30

**Scope**
- Branch: `fix/technical-hardening-wave3`, fast-forward of worker branch `fix/wave3-security-reliability`.
- Base: `assistant-v2-full` at `38e76d236ebd37a53e5f13a99cdcd0fa83195f30`.
- Changes: runtime authorization and reliability fixes, each backed by a rule that already exists in the codebase.
- Not changed: migrations, schema and business policy.

**Production identity (unchanged)**

| Item | Value |
|---|---|
| Source SHA | `a5bd8a389f2a978e2a07bb30d58a622bddea82df` |
| Tag | `bys360-prod-2026.09.29-a5bd8a38` |
| Migration head | `w2d8e1f4a6c3` |

**How the wave ran:** a coordinator and one specialist agent, in cost-conscious mode. A container restart ended the first specialist run; the work it had committed survived, and it was pushed as a checkpoint.

## 1. Fixed defects

For each fix, a regression test failed on the old code (RED) and passed after the fix (GREEN). GREEN counts include neighbouring tests. After every route change, the anonymous-route, authorization-matrix and architecture contracts gave 546 passed.

| ID | Severity | Route / component | Defect | Existing rule reused | Commit | RED → GREEN |
|---|---|---|---|---|---|---|
| W3-01 / W3-01b | HIGH | `POST /api/mobile/kpi/target-management/<id>/progress` | Any mobile user could overwrite ownerless targets of any unit, and institution targets. The first fix was stricter than the web; W3-01b corrects it. | Web SP-1D edit rule (`sp1d_target_management_service.get_target_for_edit`): owner, or same `owner_unit_id` | 3c60c0d6, 1a1b3943 | 2F/4P → 27P; 2F/8P → 81P |
| W3-02 | HIGH | `POST /api/mobile/performance/tasks/<id>/score-form`, `/score-action` | A `baskan` or `baskan_yardimcisi` who was not the evaluator could save scores or withdraw a completed evaluation. | Web scoring rule (`performance_v2_phase3_assignment`): admin or evaluator | 8e6b365a | 2F/5P → 290P |
| W3-03 | MEDIUM | `POST /api/mobile/surveys/<id>/submit` and detail `can_submit` | A mobile global role outside the survey audience could add a response with no assignment, skewing results. | Web `survey_submit`: an assignment is required for everyone, admin included; `can_submit` changes with it | 7a5f2ecd, 1d079811 | 4F/9P → 69P |
| W3-04 | HIGH | `GET /api/mobile/support/tickets/<id>`, `POST .../reply` | Mobile global roles outside the admin family could read and reply to another unit's private ticket, internal notes included. | `can_view_private_support_ticket`, the Phase 13B rule shared by `/support/*` and Faz 3 | 63dc48da | 4F/6P → 71P |
| W3-05 | HIGH | `POST /performance/feedback-aftercare/actions/<id>/update` | The update was saved before the permission check, so any logged-in user could overwrite any action plan. | `_can_edit_meeting`, which the sibling aftercare routes check before writing | a56a3e53 | 2F/4P → 76P |
| W3-06 | LOW-MED | 8 POST routes under `/hr-management/personnel-operations/` | A non-numeric `user_id` gave a 500; reproduced on PostgreSQL 16. | `_safe_int` from the same file | 40feedb0 | 16F/8P → 338P+2S |
| W3-07 | HIGH | `POST /api/mobile/personnel/create`, `/personnel/add` | An HR creator (`ik`) could create an `admin` account, whose first-login password is the configured default. | Web `/personnel/add` is `admin_required`, so only the admin family grants admin-family roles | 0141bb35 | 6F/3P → 38P |
| W3-08 | HIGH | same | The W3-07 residual: HR could still grant admin aliases (`super_admin`, `system_admin`, `sistem_yoneticisi`, `administrator`, `president`). | Same rule. Code evidence that these are admin-level: `routes_president_scorecard_v2.py:47`, `feedback_aftercare_phase7.py:19`, `account_communication_helpers.py:1057` | f73f3318 | 7F/21P (with W3-09) → 606P incl. contracts |
| W3-09 | MEDIUM | `GET /api/mobile/support/tickets` (list) | Mobile global roles saw a 180-character description snippet of other units' private tickets. | `can_view_private_support_ticket`; the creator always sees their own ticket; titles stay listed (H3) | 5f642e10 | see W3-08 |

**Test-only commit.** `e2f7c665` renames six new test password constants to the `...Test1!` convention. Without it, the CI secret gate reports 6 findings.

**Negative controls**
- W3-03: re-applying a submit-only edit makes the consistency lock fail (2F).
- W3-01b: removing the NULL-unit guard makes the "user without a unit" test fail.

## 2. Verified unfixed defects (VERIFIED_TECHNICAL_DEBT)

No proven CRITICAL or HIGH defect is left unfixed.

- **MEDIUM — mobile messaging writes always return 500.**
  - Affects v1/v2 send and create-thread.
  - The delegates look up `_bys360_legacy_*` handlers that are never registered.
  - `test_h1f_mobile_notification_exception_leak_contract.py` pins the 500.
  - Fixing it means re-wiring the handlers, which is larger than a small fix.
- **MEDIUM — `POST /communication/faz5/preferences/digest` always returns 500.**
  - `create_digest_job` uses `Notification.is_hidden`, `SurveyAssignment.user_id` and `SurveyAssignment.status`, none of which exist.
  - A fix needs a decision on what the digest counts.
- **LOW — order-dependent test failure.** `tests/integration/test_mobile_support_ticket_db_transactions.py` fails with `UNIQUE users.email` when it runs after certain file-database security test modules. It passes alone and in CI order.
- **LOW — misleading waiting count on mobile surveys.** The "Yanıt Bekleyen" metric counts every visible active survey for global roles, including surveys they can no longer answer after W3-03.

## 3. Unverified risks

- **Other roles HR can grant.** HR creators can still grant non-admin-level global roles (`ik`, `personel_yonetimi`, `performans_yetkilisi`). This is lateral, not vertical; the policy question is §4.
- **Mobile vs web assignment matching.** `_mobile_survey_assignment_for_user` and `matching_assignment_for_user` handle `role_label`, `ust_birim`, unit id and letter case differently.
- **Internal notes on mobile.** For non-private tickets, mobile shows internal notes to every mobile global role. Not compared with the web.
- **Dead route.** v1 create-thread does not check that recipients exist. This matters only once messaging is re-wired.
- **Unexplained import error.** One "partially initialized module 'config'" import error was logged during the POST probe. No 500 was recorded.

## 4. Human decision required (new; Wave 2 H1–H11 still open)

- **"Global role" differs between web and mobile.** Web `_is_global_role` substring-matches admin, sistem, baskan, performans and ik, so `grup_baskani` counts as global. Mobile `_has_global_scope` uses the explicit `_GLOBAL_ROLES` set.
- **SP-1D same-unit edits are broad.** Any user in a target's unit can edit colleagues' personal targets. This now applies to mobile progress writes as well.
- **Private ticket titles in the mobile list (H3).** Titles remain listed.
- **Mobile global roles vs web `support_all` for non-private tickets.**
- **Personnel create.** Which non-admin-level roles may HR creators grant on mobile?

## 5. Production evidence / migration

- PRODUCTION_EVIDENCE_REQUIRED: none new. The Wave 2 §7 items remain.
- MIGRATION_REVIEW_REQUIRED: none. No migration file changed; the head is `w2d8e1f4a6c3`.

## 6. Low-risk deferred

- The assigned user of a ticket has no access on mobile. This is narrower than the web and exposes nothing.

## 7. Checked, no change needed

- **Mobile:**
  - notification read and read-all are owner-only;
  - message send is limited to thread participants;
  - in-period notes are limited to self, global roles or the evaluator.
- **Feedback:**
  - request detail and schedule views are admin or the employee's managers only;
  - follow-up quick-update checks access before writing.
- **Admin-only actions:** personnel-support approve and return, hierarchy edit, task clear and unpublish are all correctly gated.
- **Web KPI target edit:** checks scope on view and on save.
- **Files and records:** file center, support attachments and every HR personnel-operations write are scope-checked.
- **POST 500 probe:**
  - 431 POST routes, 51 skipped by a denylist, sent empty and garbage forms.
  - Ran on PostgreSQL 16 copies of the migration-built database, as admin and as `birim_sorumlusu`.
  - Only the W3-06 routes and the Faz 5 digest returned 500.

## 8. Quality results (local, Linux, Python 3.12.3, scratch clones)

**Full pytest steps (one run, code at 5f642e10)**
- Step 1 (`tests/quality -m ci_safe`): 1200 collected. 985 passed, 0 failed, 133 skipped, 82 deselected — identical to the baseline.
- Step 2 (the long CI list): stopped by the environment's background time limit at 43%, with 0 failures up to that point. It was not restarted (cost limit: one full run).
- The complete Step 2, the coverage ratchet and the PostgreSQL 15 gate come from the pull request's CI on the same code.

**Targeted checks**
- Every fix: RED/GREEN as listed in §1.
- Anonymous-route, authorization-matrix and architecture contracts: 546 passed after each route change, and 606 passed with the final mobile fixes.

**Gates on e2f7c665 (a later commit changes only test password constants)**

| Gate | Result |
|---|---|
| `git diff --check` | clean |
| Ruff full select | All checks passed |
| Ruff sanity | All checks passed |
| compileall | OK |
| mypy (`app tests scripts`) | 0 errors |
| Secret gate | ok. 0 findings; 489 warnings (475 at base; the +14 are test password constants) |
| Safe-release audit | ok, 0 findings |
| Ops audit | 0 syntax errors, 0 print calls, 2083 broad `except` (limit 2300) |
| Quality9 | ok, 0 findings |
| pip-audit | not rerun: `requirements.txt` is unchanged since Wave 2 (0 known vulnerabilities) |
| Migrations | none changed |

**Auxiliary database:** PostgreSQL 16 was used for probing only. It is NOT the PostgreSQL 15 gate.
