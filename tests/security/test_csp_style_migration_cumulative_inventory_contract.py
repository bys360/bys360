"""BYS360 CSP inline-style migration — cumulative, wave-agnostic repo-wide
inventory contract.

WHY THIS FILE EXISTS: `test_csp_style2a_repo_wide_contract.py` originally
carried its own repo-wide "active total == 1235 - N" / "<style> block total
== 272" locks. Those assumed Style-2A was the last wave that would ever
touch a `style="..."` attribute anywhere in the repo. When Style-2B
legitimately removed 58 more static style attributes from 8 *other*
templates, those locks failed — not because anything was wrong, but
because they were never designed to accommodate a second wave. See that
file's own docstring for the full incident writeup.

This file is the replacement: a single, wave-agnostic, manifest-driven
cumulative contract. Every wave registers itself in
`STYLE_MIGRATION_WAVES` with the templates it touched and how many fully-
static attributes it removed from them. The expected repo-wide total is
always ``INITIAL_ACTIVE_STYLE_TOTAL - sum(wave.removed_static for wave)``.
Adding a Style-2C, Style-2D, ... wave later means adding one manifest
entry here — nothing else in this file changes.

FORWARD-COMPATIBILITY FOLLOW-UP (Style-3A, same class of bug as the
Style-2A/2B incident above, fixed the same way): this file originally also
hardcoded a single, wave-agnostic-in-name-only "`style_block_total` always
equals `INITIAL_STYLE_BLOCK_TOTAL`" lock in `test_cumulative_style_block_
total_is_unchanged`. That was true for Style-2A/2B (both attribute-only
waves that never removed a `<style>` BLOCK, only `style="..."` attributes)
but is false in general — Style-3A is the first wave whose entire purpose
is removing `<style>` blocks (10 of them, by design: see
`test_csp_style3a_duplicate_block_extraction_contract.py`). Exactly like
`CUMULATIVE_REMOVED_STATIC` above, block removal is now a per-wave manifest
field (`removed_blocks`) summed into `CUMULATIVE_REMOVED_BLOCKS`, and the
expected total is ``INITIAL_STYLE_BLOCK_TOTAL - CUMULATIVE_REMOVED_BLOCKS``
(renamed to `test_cumulative_style_block_total_matches_manifest` to match
the naming of its active-attribute sibling). Style-2A/2B's entries simply
carry `removed_blocks: 0`, so their expected total is unaffected.

FORWARD-COMPATIBILITY FOLLOW-UP 2 (orphan template deletion, a new wave
CLASS this manifest did not originally support): `STYLE_MIGRATION_WAVES`
above assumes a wave EDITS a template in place (the file still exists
afterward, now with zero static attrs/blocks) — that assumption is baked
into `test_every_wave_target_template_has_zero_active_style_attribute` and
`test_every_block_removal_wave_target_template_has_zero_style_blocks`,
which both `.read_text()` every listed template. A wave that instead
DELETES a template entirely (its whole rendering surface was dead code —
see the "BYS360 Executive Mail Orphan Alt Sistemi" cleanup: a route module,
`app/communication/executive_mail_center_routes.py`, proven absent from
`sys.modules`/`route_manifest.py`/the real `url_map` after `create_app()`,
whose only 6 templates therefore had zero reachable renderer) would make
those two tests raise `FileNotFoundError`, not a clean assertion failure.
`DELETED_TEMPLATE_WAVES` below is a separate, parallel manifest for exactly
this wave class: same `removed_static`/`removed_blocks` shape, folded into
the SAME `CUMULATIVE_REMOVED_STATIC`/`CUMULATIVE_REMOVED_BLOCKS` sums (so
`EXPECTED_ACTIVE_STYLE_TOTAL`/`EXPECTED_STYLE_BLOCK_TOTAL` account for both
wave classes uniformly), but checked by its own
`test_every_deleted_wave_target_template_is_genuinely_absent_from_worktree`
(asserts the file is GONE, the inverse of the edit-in-place check) and its
own `test_deleted_wave_removed_static_and_removed_blocks_match_pre_deletion_
git_ref` (independently re-derives `removed_static`/`removed_blocks` from
the fixed git ref immediately before the deletion commit, so the recorded
numbers are never just trusted). `INITIAL_ACTIVE_STYLE_TOTAL` /
`INITIAL_DYNAMIC_STYLE_TOTAL` / `INITIAL_STYLE_BLOCK_TOTAL` and the
`STYLE_MIGRATION_WAVES` entries above are untouched by this follow-up —
they are historical fact about waves that already landed, not affected by
a later, unrelated wave deleting different, always-dead templates.

FORWARD-COMPATIBILITY FOLLOW-UP 3 (Style-3B, an ordinary edit-in-place wave
— back to the original `STYLE_MIGRATION_WAVES` shape, no new manifest
needed): a new `"style3b_low_risk"` entry was added with `removed_static=0`,
`removed_blocks=2` for its 2 templates (`performance/meeting_development.
html`, `performance/meeting_p3_reminders.html`, both genuinely `ACTIVE` —
independently re-verified with a real, isolated `create_app()` before this
wave touched anything). Note this wave was originally scoped to 4 templates
across 2 groups; the second group (`executive_summary/daily_weather_mail_
tasks.html` + `communication/daily_weather_mail_settings.html`) was dropped
entirely after the same pre-implementation re-verification proved both of
those templates are ORPHAN (see
`tests/security/test_csp_style3b_low_risk_duplicate_extraction_contract.py`'s
own module docstring for the full evidence) — neither was touched in any
way, so this ledger has no entry for them. `INITIAL_*` constants and the
`style2a`/`style2b`/`style3a`/`DELETED_TEMPLATE_WAVES` entries above are
unaffected.

FORWARD-COMPATIBILITY FOLLOW-UP 4 (BYS360 Daily Weather/Mail Orphan
Template Temizliği, a DELETED_TEMPLATE_WAVES-class wave): a new
`"daily_weather_mail_cleanup"` entry was added recording the deletion of
the exact 2 templates dropped from Style-3B's scope above (both
independently re-confirmed ORPHAN, not just assumed) plus 2 more
(`daily_mail_tasks_premium.html`, `daily_mail_tasks_v1_4.html`, already
correctly identified as orphan by Wave 8's own original contract).
`removed_static=20`/`removed_blocks=4` are the sum of each of the 4
templates' independently-measured, identical per-template contribution (5
static attrs + 1 block each) — see
`tests/security/test_csp_wave8_weather_mail_contract.py` and
`tests/security/test_csp_wave8_executive_summary_mail_contract.py`'s own
module docstrings for the full per-template evidence and the correction of
a previously-incorrect "CANLI" (live) claim for one of the four. `INITIAL_*`
constants and all prior wave entries are unaffected.

FORWARD-COMPATIBILITY FOLLOW-UP 5 (BYS360 Executive Summary Artık
Servis/Template Temizliği, a DELETED_TEMPLATE_WAVES-class wave): the prior
"dead route module" wave (`app/dashboard/executive_summary_routes.py`
removal, commit `c5a6a61b`) had deliberately left `app/services/
executive_summary_service.py` and `app/templates/dashboard/executive_
summary.html` untouched as an explicitly out-of-scope residual candidate
(neither had any OTHER consumer even then). This follow-up wave
independently re-verified both are still ORPHAN_CONFIRMED with a real,
isolated `create_app()` (985 routes, byte-identical endpoint SHA before and
after) and a repo-wide consumer grep (zero application/CLI/test consumers
of `app.services.executive_summary_service` beyond the file's own
self-referential log strings; zero `render_template`/`include`/`extends`
reference to `dashboard/executive_summary.html` anywhere — the live
`/dashboard/yonetici-ozeti` route, registered from the unrelated
`app/executive_summary/` package, renders a completely different template,
`executive_summary/yonetici_ozeti.html`). The deleted template also
referenced a nonexistent `url_for('main.executive_summary_send_mail')`
endpoint, which would have raised a `BuildError` had it ever actually been
rendered — further evidence it had no live renderer to begin with. Added a
new `"executive_summary_dashboard_cleanup"` entry: `removed_static=3`,
`removed_blocks=1`, independently re-derived from the fixed pre-deletion
git ref (see `DELETED_TEMPLATE_WAVES_PRE_DELETION_REF`). The deleted
service `.py` file carried no template markup, so it contributes 0 to this
style/CSP ledger. `INITIAL_*` constants and all prior wave entries are
unaffected.

FORWARD-COMPATIBILITY FOLLOW-UP 6 (BYS360 Workflow Orphan Presentation
Subsystem Temizliği, düzeltilmiş Alternatif A+ -- the first DELETED_
TEMPLATE_WAVES-class wave to remove a DYNAMIC style="..." attribute, not
just static ones): every prior deleted-template wave happened to leave
`dynamic_total` untouched, which let `test_cumulative_dynamic_style_total_
is_unchanged` get away with a flat `inventory.dynamic_total ==
INITIAL_DYNAMIC_STYLE_TOTAL` lock -- exactly the same class of "wave-
agnostic-in-name-only" bug the original `CUMULATIVE_REMOVED_STATIC`/
`CUMULATIVE_REMOVED_BLOCKS` follow-ups above already fixed once each for
static attributes and blocks. This wave's `"workflow_orphan_presentation_
cleanup"` entry below deletes the two `executive_dashboard.html` copies,
each carrying one dynamic `style="width: {{ ... }}%"` progress-bar
attribute (2 total) -- so a THIRD manifest field, `removed_dynamic`, was
added to `_DeletedWaveManifestEntry` (defaulting to `0` on every prior
entry, none of which ever touched a dynamic attribute), summed into a new
`CUMULATIVE_REMOVED_DYNAMIC`, and the test renamed/rewired to `test_
cumulative_dynamic_style_total_matches_manifest` with expected total
``INITIAL_DYNAMIC_STYLE_TOTAL - CUMULATIVE_REMOVED_DYNAMIC`` -- same
pattern as its two siblings. `STYLE_MIGRATION_WAVES` (the edit-in-place
manifest) is NOT given a `removed_dynamic` field: no edit-in-place wave has
ever removed a dynamic attribute either, and none is expected to (dynamic
attributes are, by definition, driven by live Jinja context, not dead
markup an edit-in-place wave would touch) -- if that ever changes, it gets
its own follow-up then. `INITIAL_*` constants and all prior wave entries
(including their `removed_dynamic: 0` additions) are otherwise unaffected.

FORWARD-COMPATIBILITY FOLLOW-UP 7 (BYS360 Orphan Template + Dead Helper
Micro-Cleanup, a DELETED_TEMPLATE_WAVES-class wave): `app/templates/
weights.html` independently re-confirmed ORPHAN_CONFIRMED by 1 coordinator +
3 cross-checking agents (zero route/render_template/include/menu/dynamic-
loader consumer anywhere, plus a live create_app()/url_map probe showing none
of its 4 referenced `main.performance_weight_*` endpoints are registered) and
deleted outright — see
`tests/security/test_weights_orphan_template_and_dead_safe_url_for_cleanup_contract.py`
for the full evidence chain. Unlike `duplicate_template_orphan_cleanup_wave1`
(whose 9 templates all independently measured zero style/CSP contribution),
`weights.html` carried one incidental fully-static
`style="min-width:250px;"` attribute (on a `<th>` column header, unrelated to
the deletion rationale) and one `<style>` block (page-local CSS for the
deleted table/card layout). New `"weights_orphan_template_cleanup"` entry:
`removed_static=1`, `removed_blocks=1`, `removed_dynamic=0` — independently
re-derived from the fixed pre-deletion git ref (HEAD of this wave's own
investigation, `2838761cdc37d3c987ca6eb1ae1d2d0d0d9a1fff`) by the same
`test_deleted_wave_removed_static_and_removed_blocks_match_pre_deletion_git_ref`
test below, never just trusted. This is the first deleted-template wave since
`duplicate_template_orphan_cleanup_wave1` to change
`EXPECTED_ACTIVE_STYLE_TOTAL`/`EXPECTED_STYLE_BLOCK_TOTAL` away from
1035/225 (now 1034/224) — the other test files that hardcode those repo-wide
totals as their own "unchanged by my wave" lock needed the same
1-attribute/1-block adjustment (see this wave's own commit for the full
file list). `app/templates/weight_create.html` and `app/templates/
weight_edit.html` are explicitly OUT of scope for this wave (same orphan
family, flagged as follow-up tech debt, not touched) and are NOT in this
manifest entry. `template_safety.py::safe_url_for` — this same wave's OTHER
cleanup target, a dead Jinja-shadowed Python helper — carried no template
markup, so it contributes 0 to this style/CSP ledger. `INITIAL_*` constants
and all prior wave entries are unaffected.

FORWARD-COMPATIBILITY FOLLOW-UP 9 (BYS360 Settings Center V2): adds four
brand-new templates (app/templates/settings_center/_shell.html, home.html,
module.html, plus a shared partial) backing new /settings-center/* pages.
Unlike a typical feature landing new markup, this wave's CSS was authored
directly as an external stylesheet (app/static/css/settings_center.css,
linked via a normal <link rel="stylesheet">, the same pattern already used
by app/templates/settings_center/_shell.html's faz4_support_account_mobile.
css reference) rather than an inline <style> block, and its few spot-style
needs (a link styled as a card, a couple of spacing tweaks) use named
classes instead of style="..." attributes. Measured with the same canonical
helper this file already uses for everything else
(count_static_style_attrs_in_text / the <style>-tag regex): every file in
this wave contributes 0 static, 0 blocks, 0 dynamic. `INITIAL_*` constants,
`STYLE_MIGRATION_WAVES`, and `DELETED_TEMPLATE_WAVES` above are entirely
unaffected by this wave, and no manifest entry is needed since there is
nothing to account for.

FORWARD-COMPATIBILITY FOLLOW-UP 10 (BYS360 Settings Center V2, orphan-auth-
key closure, a DELETED_TEMPLATE_WAVES-class wave): app/about/routes.py was
confirmed dead code as part of resolving the "about_bys360" ORPHAN_AUTH_KEY
-- its @main_bp.route("/about-bys360") decorator never executed because the
module was never imported anywhere in app/ (repo-wide grep, zero hits), so
it never contributed a real runtime endpoint. Deleted along with its
handler (app/main_handlers/about_handlers.py) and its sole template
(app/templates/about_bys360.html, which independently carried 0 static
style="..." attributes and exactly 1 <style> block -- see the
"about_bys360_dead_route_cleanup" DELETED_TEMPLATE_WAVES entry below).
Totals drop from 1032/222/64 (FOLLOW-UP 9's end state) to 1032/221/64.

FORWARD-COMPATIBILITY FOLLOW-UP 8 (BYS360 Weight Template Orphan-Family
Closure, a DELETED_TEMPLATE_WAVES-class wave): the two siblings explicitly
left out of FOLLOW-UP 7's scope, `app/templates/weight_create.html` and
`app/templates/weight_edit.html`, were independently re-investigated fresh
by a dedicated 1-coordinator + 3-agent pass (not assumed from
`weights.html`'s fate) and both reached `ORPHAN_CONFIRMED`: zero
`render_template`/`safe_render`/`{% include/extends %}`/menu/dynamic-loader
consumer anywhere, and a live `create_app()`/`url_map` probe (985 routes)
confirms neither `main.performance_weight_create` nor
`main.performance_weight_edit` is registered. `weight_edit.html`'s agent
initially reported the more conservative `ORPHAN_HIGH_CONFIDENCE` (its
Explore-type tooling had no code-execution access to run its own live
probe); the coordinator closed that gap directly with an independent probe
before upgrading it. See
`tests/security/test_weights_orphan_template_and_dead_safe_url_for_cleanup_contract.py`
(the same file FOLLOW-UP 7 uses) for the full evidence chain — both were
folded into that file's existing `DELETED_SIBLING_ORPHANS` deletion
contract rather than a new duplicate test file. Each template independently
carried one fully-static `style="..."` attribute and one `<style>` block
(measured the same canonical-helper way, not guessed). New
`"weight_create_edit_orphan_cleanup"` entry: `removed_static=2`,
`removed_blocks=2`, `removed_dynamic=0` (1+1 per template) —
independently re-derived from the fixed pre-deletion git ref (tip of
FOLLOW-UP 7's own wave, `46b468a40b00e7d0a492b5f7b511349c83a7444d`) by the
same `test_deleted_wave_removed_static_and_removed_blocks_match_pre_deletion_
git_ref` test below. This changes `EXPECTED_ACTIVE_STYLE_TOTAL`/
`EXPECTED_STYLE_BLOCK_TOTAL` from 1034/224 (FOLLOW-UP 7's end state) to
1032/222 — the other test files that hardcode those repo-wide totals as
their own "unchanged by my wave" lock need the same 2-attribute/2-block
adjustment (see this wave's own commit for the full file list). `INITIAL_*`
constants and all prior wave entries are unaffected.

CANONICAL METHODOLOGY: all counting goes through the single shared helper
`tests/security/_bys360_style_inventory.py` (real `html.parser.HTMLParser`
based tokenization, not a naive regex) so this file, the per-wave files,
and any future wave's contract test can never silently disagree about what
counts as a real `style="..."` attribute. See that module's docstring for
why a naive regex is unsafe here (JS `<script>` template-literal strings
containing literal `style="..."` text as DATA, not a real attribute; and
`{% if x %}style="..."{% endif %}` bare-Jinja-mid-tag fragments that a raw
`HTMLParser` loses sync on and silently drops).

SCOPE: exactly `app/templates` + `app/modules/*/templates` +
`app/workflow/templates` (Flask/Jinja render roots). `app/static` (PWA
offline HTML, served as static files, never Jinja-rendered) and anything
under `scripts/` (not part of the Flask app at all) are deliberately
excluded — mixing them in previously caused scope-consistency bugs (see
`_bys360_style_inventory.py` and `test_csp_style2a_repo_wide_contract.py`
docstrings for the specific files/line numbers that were affected).

INITIAL BASELINE EVIDENCE: `INITIAL_ACTIVE_STYLE_TOTAL` /
`INITIAL_DYNAMIC_STYLE_TOTAL` / `INITIAL_STYLE_BLOCK_TOTAL` are measured
directly (canonical helper, `compute_inventory_at_git_ref`) against git
commit `dab2c1de08024bd330f4c15eeffc089dbbcd8b2e` — the immediate parent of
`649f4530...` (the squashed "Style-1 + Style-2A" checkpoint), i.e. the
repo state before ANY inline-style migration wave touched anything.
`test_initial_baseline_constants_match_historical_git_ref` re-derives them
from that commit at test-run time (not from a cached number) so this
baseline can never silently drift from its own evidence. That test skips
only if the `git` binary itself is unavailable (an environment limitation,
not a correctness gap) — it is NOT gated on there being any uncommitted
diff, so it runs identically on a clean, fully-committed worktree.

NO SKIP-ON-CLEAN-WORKTREE ANYWHERE IN THIS FILE: every test here compares
the *current on-disk worktree* against fixed manifest arithmetic. None of
it depends on `git status`/`git diff` having anything pending, so it
behaves identically before and after this wave's own commit lands.
"""
from __future__ import annotations

import re
import subprocess
from typing import TypedDict

import pytest

from tests.security._bys360_style_inventory import (
    REPO_ROOT,
    compute_inventory_at_git_ref,
    compute_inventory_from_worktree,
    count_static_style_attrs_in_text,
)

# ---------------------------------------------------------------------------
# Canonical pre-migration baseline (evidence: see module docstring above and
# test_initial_baseline_constants_match_historical_git_ref below).
# ---------------------------------------------------------------------------

INITIAL_BASELINE_GIT_REF = "dab2c1de08024bd330f4c15eeffc089dbbcd8b2e"
INITIAL_ACTIVE_STYLE_TOTAL = 1166
INITIAL_DYNAMIC_STYLE_TOTAL = 66
INITIAL_STYLE_BLOCK_TOTAL = 270

# ---------------------------------------------------------------------------
# Wave manifest. Each wave: the templates it targeted, and the number of
# fully-static `style="..."` attributes it removed from them (evidence for
# each wave's own number lives in that wave's own local contract test file,
# e.g. test_csp_style2a_repo_wide_contract.py::TARGET_TEMPLATES /
# test_csp_style2b_target_templates_contract.py::TARGET_TEMPLATES).
# ---------------------------------------------------------------------------

class _WaveManifestEntry(TypedDict):
    templates: tuple[str, ...]
    removed_static: int
    removed_blocks: int


STYLE_MIGRATION_WAVES: dict[str, _WaveManifestEntry] = {
    "style2a": {
        "templates": (
            "app/templates/support/help_admin_list.html",
            "app/templates/support/detail.html",
            "app/templates/support/new.html",
            "app/templates/notifications_list.html",
            "app/templates/hr_attendance.html",
            "app/templates/hr_personnel_dashboard.html",
            "app/templates/file_center/index.html",
            "app/templates/admin_analysis_excel_preview.html",
        ),
        "removed_static": 40,
        "removed_blocks": 0,
    },
    "style2b": {
        "templates": (
            "app/templates/communication/phase1_bulletin_form.html",
            "app/templates/feedback/quick_feedback.html",
            "app/templates/feedback_executive_summary_dashboard.html",
            "app/templates/assignment_recommendations.html",
            "app/templates/hr_personnel_lifecycle_center.html",
            "app/templates/admin_ai_center.html",
            "app/templates/feedback_meeting_detail.html",
            "app/templates/performance_v2_phase1.html",
        ),
        "removed_static": 58,
        "removed_blocks": 0,
    },
    "style3a": {
        "templates": (
            "app/templates/errors/400.html",
            "app/templates/errors/401.html",
            "app/templates/errors/404.html",
            "app/templates/errors/405.html",
            "app/templates/errors/500.html",
            "app/templates/strategic_performance/ai_kpi_analysis.html",
            "app/templates/strategic_performance/competency_library.html",
            "app/templates/strategic_performance/kpi_dashboard.html",
            "app/templates/strategic_performance/self_review_form.html",
            "app/templates/strategic_performance/target_list.html",
        ),
        "removed_static": 0,
        "removed_blocks": 10,
    },
    "style3b_low_risk": {
        "templates": (
            "app/templates/performance/meeting_development.html",
            "app/templates/performance/meeting_p3_reminders.html",
        ),
        "removed_static": 0,
        "removed_blocks": 2,
    },
    # Style-3C: active meeting-family duplicate <style> block extraction, 8
    # templates, all raw-byte-identical 387-line blocks extracted to
    # app/static/css/meeting_development_c_shared.css. See
    # tests/security/test_csp_style3c_meeting_family_group_a_contract.py for
    # the full byte-parity/runtime-activity/HTTP evidence.
    "style3c_meeting_family_group_a": {
        "templates": (
            "app/templates/performance/meeting_development_faz3.html",
            "app/templates/performance/meeting_development_faz4.html",
            "app/templates/performance/meeting_development_scenarios.html",
            "app/templates/performance/meeting_final_closure.html",
            "app/templates/performance/meeting_p0_completion.html",
            "app/templates/performance/meeting_p1_scope.html",
            "app/templates/performance/meeting_p2_archive_notes.html",
            "app/templates/performance/meeting_rule_enforcement.html",
        ),
        "removed_static": 0,
        "removed_blocks": 8,
    },
    # FORWARD-COMPATIBILITY FOLLOW-UP 11 (BYS360 UX pilot, Destek -> Yeni Talep
    # Aç): support/new.html's single page-level <style> block was moved into
    # the scoped external stylesheet app/static/css/bys360_components.css.
    # 0 static attributes (style2a already removed the template's last 3),
    # 1 block. The template is therefore claimed a second time -- see
    # DISJOINT_RECLAIMS below for why that is not a double count.
    # Evidence: tests/behavior/test_pilot_support_new_ux_contract.py (K2).
    "ux_pilot_support_new": {
        "templates": (
            "app/templates/support/new.html",
        ),
        "removed_static": 0,
        "removed_blocks": 1,
    },
    # FORWARD-COMPATIBILITY FOLLOW-UP 12 (BYS360 UX wave 2, Destek ->
    # Taleplerim / Bana Atananlar / Tüm Talepler): support/list.html's single
    # page-level <style> block was moved into the scoped external stylesheet
    # app/static/css/bys360_components.css. 0 static attributes (the template
    # never had any), 1 block. First claim of this template -- no reclaim.
    # Evidence: tests/behavior/test_ux_wave2_support_list_contract.py.
    "ux_wave2_support_list": {
        "templates": (
            "app/templates/support/list.html",
        ),
        "removed_static": 0,
        "removed_blocks": 1,
    },
}

# A template may be claimed by a second edit-in-place wave ONLY when the two
# waves removed disjoint kinds of debt from it: the earlier wave removed
# static attributes and no blocks, the later wave removed blocks and no static
# attributes. Each entry is (earlier wave, later wave). The duplicate-claim
# guard below allows exactly these pairs and nothing else, and
# test_disjoint_reclaims_never_count_the_same_removal_kind_twice proves the
# disjointness from the manifest numbers themselves.
DISJOINT_RECLAIMS: dict[str, tuple[str, str]] = {
    "app/templates/support/new.html": ("style2a", "ux_pilot_support_new"),
}

class _DeletedWaveManifestEntry(TypedDict):
    templates: tuple[str, ...]
    removed_static: int
    removed_blocks: int
    removed_dynamic: int


# Waves that DELETED their templates entirely (as opposed to editing them in
# place) -- see the "FORWARD-COMPATIBILITY FOLLOW-UP 2" docstring section
# above for why this is a separate manifest from STYLE_MIGRATION_WAVES.
# removed_static=8 / removed_blocks=6 are independently re-derived from a
# fixed pre-deletion git ref by
# test_deleted_wave_removed_static_and_removed_blocks_match_pre_deletion_git_ref
# below -- never just trusted. `removed_dynamic` (FORWARD-COMPATIBILITY
# FOLLOW-UP 6, see below) defaults to 0 for every wave here except
# `workflow_orphan_presentation_cleanup` -- no prior deleted-template wave
# ever removed a dynamic `style="...{{ }}..."` attribute.
DELETED_TEMPLATE_WAVES: dict[str, _DeletedWaveManifestEntry] = {
    "orphan_mail_cleanup": {
        "templates": (
            "app/templates/executive_summary/executive_mail_center.html",
            "app/templates/executive_summary/executive_mail_tasks.html",
            "app/templates/executive_summary/executive_mail_recipients.html",
            "app/templates/executive_summary/executive_mail_logs.html",
            "app/templates/executive_summary/executive_mail_scheduled_jobs.html",
            "app/templates/executive_summary/executive_mail_test.html",
        ),
        "removed_static": 8,
        "removed_blocks": 6,
        "removed_dynamic": 0,
    },
    # BYS360 Daily Weather/Mail Orphan Template Temizliği: 4 template, hepsi
    # ORPHAN_CONFIRMED (hiçbir gerçek route render etmiyor -- iki tanesi
    # zaten Wave 8'in kendi zamanında doğru tespit edilmişti, diğer iki
    # tanesi (communication/daily_weather_mail_settings.html ve executive_
    # summary/daily_weather_mail_tasks.html) Wave 8'in test dosyasındaki
    # YANLIŞ "CANLI" iddiasının düzeltilmesiyle birlikte yeniden doğrulandı
    # -- bkz. tests/security/test_csp_wave8_weather_mail_contract.py'nin
    # kendi düzeltme notu. removed_static=20/removed_blocks=4 dört
    # template'in her birinin ayrı ayrı ölçülen katkısının (5 statik attr +
    # 1 blok her birinde, hepsi byte-birebir aynı) toplamıdır.
    "daily_weather_mail_cleanup": {
        "templates": (
            "app/templates/communication/daily_weather_mail_settings.html",
            "app/templates/executive_summary/daily_weather_mail_tasks.html",
            "app/templates/executive_summary/daily_mail_tasks_premium.html",
            "app/templates/executive_summary/daily_mail_tasks_v1_4.html",
        ),
        "removed_static": 20,
        "removed_blocks": 4,
        "removed_dynamic": 0,
    },
    # BYS360 Executive Summary Artık Servis/Template Temizliği: residual
    # orphan left explicitly out-of-scope by the prior dead-route-module
    # wave, independently re-confirmed ORPHAN_CONFIRMED (see FORWARD-
    # COMPATIBILITY FOLLOW-UP 5 above for the full evidence). removed_static=3/
    # removed_blocks=1 are this single template's own static style="..."
    # attribute count (3: execv3-actions hero spacer, execv3-schedule status
    # line, execv3-note test-mail banner) and <style> block count (1).
    "executive_summary_dashboard_cleanup": {
        "templates": (
            "app/templates/dashboard/executive_summary.html",
        ),
        "removed_static": 3,
        "removed_blocks": 1,
        "removed_dynamic": 0,
    },
    # BYS360 Workflow Orphan Presentation Subsystem Temizliği (düzeltilmiş
    # Alternatif A+, FORWARD-COMPATIBILITY FOLLOW-UP 6 -- see module
    # docstring): 14 templates across TWO byte-mostly-identical trees
    # (app/templates/workflow/*.html and app/workflow/templates/workflow/
    # *.html, 7 filenames each), both independently re-confirmed
    # ORPHAN_CONFIRMED -- the whole `app/workflow/` presentation/route
    # package (`routes.py`, `dashboard_upgrade_routes.py`) was never
    # imported at startup (see the separate read-only "BYS360 Workflow Alt
    # Sistemi" audit and this wave's own
    # test_workflow_orphan_presentation_subsystem_cleanup_contract.py for
    # the full evidence, including a reproduced 985->997 same-process
    # import-contamination proof). removed_static=2/removed_blocks=14/
    # removed_dynamic=2 are independently re-derived from the fixed
    # pre-deletion git ref below: every one of the 14 files carries exactly
    # one <style> block; only the two `president_approvals.html` copies each
    # carry one static style="..." attribute (2 total); only the two
    # `executive_dashboard.html` copies each carry one DYNAMIC
    # style="width: {{ ... }}%" progress-bar attribute (2 total) -- the
    # FIRST deleted-template wave to ever remove a dynamic attribute, hence
    # the new `removed_dynamic` manifest field (see FORWARD-COMPATIBILITY
    # FOLLOW-UP 6 above).
    "workflow_orphan_presentation_cleanup": {
        "templates": (
            "app/templates/workflow/dashboard.html",
            "app/templates/workflow/delays.html",
            "app/templates/workflow/executive_dashboard.html",
            "app/templates/workflow/modules.html",
            "app/templates/workflow/notifications.html",
            "app/templates/workflow/president_approvals.html",
            "app/templates/workflow/timeline.html",
            "app/workflow/templates/workflow/dashboard.html",
            "app/workflow/templates/workflow/delays.html",
            "app/workflow/templates/workflow/executive_dashboard.html",
            "app/workflow/templates/workflow/modules.html",
            "app/workflow/templates/workflow/notifications.html",
            "app/workflow/templates/workflow/president_approvals.html",
            "app/workflow/templates/workflow/timeline.html",
        ),
        "removed_static": 2,
        "removed_blocks": 14,
        "removed_dynamic": 2,
    },
    # BYS360 Duplicate Template Dalga 1: 4 raw-byte-identical duplicate groups
    # (9 templates total), every one independently re-confirmed
    # ORPHAN_CONFIRMED (zero render_template/safe_render/Jinja include-extends-
    # import-from/macro-import/dynamic-name/menu-registry/test consumers
    # anywhere in the repo -- only incidental mentions in static historical
    # JSON inventory snapshots and one zip archive report, neither a real
    # dependency). See
    # tests/security/test_duplicate_template_orphan_cleanup_wave1_contract.py
    # for the full per-file evidence. All 9 templates independently measured
    # 0 static/dynamic style attributes, 0 <style> blocks, 0 inline handlers,
    # 0 javascript: URLs each -- removed_static/removed_blocks/removed_dynamic
    # are all 0, this wave has zero style/CSP inventory impact.
    "duplicate_template_orphan_cleanup_wave1": {
        "templates": (
            "app/templates/portal/_press_news_home_hero_v3a.html",
            "app/templates/portal/_press_news_home_hero_v3a.safe_v1.html",
            "app/templates/portal/_press_news_home_hero_v3a.safe_v1a.html",
            "app/templates/_action_suggestion_macros.html",
            "app/templates/action_suggestion_macros.html",
            "app/templates/_decision_support_macros.html",
            "app/templates/decision_support_macros.html",
            "app/templates/_performance_workspace_macros.html",
            "app/templates/performance_workspace_macros.html",
        ),
        "removed_static": 0,
        "removed_blocks": 0,
        "removed_dynamic": 0,
    },
    # BYS360 Orphan Template + Dead Helper Micro-Cleanup: see FORWARD-
    # COMPATIBILITY FOLLOW-UP 7 in the module docstring above for the full
    # evidence chain and per-file rationale.
    "weights_orphan_template_cleanup": {
        "templates": (
            "app/templates/weights.html",
        ),
        "removed_static": 1,
        "removed_blocks": 1,
        "removed_dynamic": 0,
    },
    # BYS360 Weight Template Orphan-Family Closure: see FORWARD-
    # COMPATIBILITY FOLLOW-UP 8 in the module docstring above for the full
    # evidence chain and per-file rationale.
    "weight_create_edit_orphan_cleanup": {
        "templates": (
            "app/templates/weight_create.html",
            "app/templates/weight_edit.html",
        ),
        "removed_static": 2,
        "removed_blocks": 2,
        "removed_dynamic": 0,
    },
    # BYS360 Settings Center V2 orphan-auth-key closure: app/about/routes.py
    # was confirmed dead code (its @main_bp.route("/about-bys360") decorator
    # never executed -- the module was never imported anywhere in app/, so
    # it never contributed a real runtime endpoint) and deleted, along with
    # its sole template. Independently re-derived from the pre-deletion git
    # ref below: 0 static, 1 <style> block, 0 dynamic.
    "about_bys360_dead_route_cleanup": {
        "templates": (
            "app/templates/about_bys360.html",
        ),
        "removed_static": 0,
        "removed_blocks": 1,
        "removed_dynamic": 0,
    },
}

# The fixed commit immediately BEFORE each deleted-template wave's own
# deletion commit -- the repo state at which point that wave's templates
# still existed on disk.
DELETED_TEMPLATE_WAVES_PRE_DELETION_REF = {
    "orphan_mail_cleanup": "297c8da746a59d84e5f3f9536b92e824ce5bd70a",
    "daily_weather_mail_cleanup": "1d20cdeffdd1f20fe24c3f5414fa5d7ba498df47",
    "executive_summary_dashboard_cleanup": "c5a6a61b47caf2d39ca812b74f7fd22f329629c4",
    "workflow_orphan_presentation_cleanup": "88d148c61f11fe9cc8d323cd8cdce1d80a146dfe",
    "duplicate_template_orphan_cleanup_wave1": "d4ee2043931b37cef6df2ceef898094e0eebb04d",
    "weights_orphan_template_cleanup": "2838761cdc37d3c987ca6eb1ae1d2d0d0d9a1fff",
    "weight_create_edit_orphan_cleanup": "46b468a40b00e7d0a492b5f7b511349c83a7444d",
    "about_bys360_dead_route_cleanup": "9be1b80cc87f809cd0abefcd4121d85b37cd3487",
}

# FORWARD-COMPATIBILITY FOLLOW-UP 9 (see module docstring above): Settings
# Center V2's four new templates are independently verified below
# (test_settings_center_v2_templates_contribute_zero_style_debt) to
# contribute 0 static/0 blocks/0 dynamic, so no manifest entry or formula
# change is needed here -- INITIAL_*/CUMULATIVE_REMOVED_*/EXPECTED_* below
# are entirely unaffected by this wave.
_BYS360_SETTINGS_CENTER_V2_TEMPLATES: tuple[str, ...] = (
    "app/templates/settings_center/_shell.html",
    "app/templates/settings_center/home.html",
    "app/templates/settings_center/module.html",
)

_STYLE_TAG_RE = re.compile(r"<style\b", re.IGNORECASE)
# Simple raw-text dynamic-attribute matcher for git-show re-derivation only
# (canonical live-worktree dynamic counting stays the HTMLParser-based
# `compute_inventory_from_worktree`/`compute_inventory_at_git_ref` in
# `_bys360_style_inventory.py` -- this is a defense-in-depth cross-check
# against a fixed historical git ref's raw text, same spirit as
# `count_static_style_attrs_in_text` being used for the same purpose above).
_DYNAMIC_STYLE_ATTR_RE = re.compile(r'style="[^"]*\{\{[^"]*\}\}[^"]*"')

CUMULATIVE_REMOVED_STATIC = sum(w["removed_static"] for w in STYLE_MIGRATION_WAVES.values()) + sum(
    w["removed_static"] for w in DELETED_TEMPLATE_WAVES.values()
)
EXPECTED_ACTIVE_STYLE_TOTAL = INITIAL_ACTIVE_STYLE_TOTAL - CUMULATIVE_REMOVED_STATIC

CUMULATIVE_REMOVED_BLOCKS = sum(w["removed_blocks"] for w in STYLE_MIGRATION_WAVES.values()) + sum(
    w["removed_blocks"] for w in DELETED_TEMPLATE_WAVES.values()
)
EXPECTED_STYLE_BLOCK_TOTAL = INITIAL_STYLE_BLOCK_TOTAL - CUMULATIVE_REMOVED_BLOCKS

# FORWARD-COMPATIBILITY FOLLOW-UP 6 (see module docstring): only
# DELETED_TEMPLATE_WAVES entries carry `removed_dynamic` -- STYLE_MIGRATION_
# WAVES (edit-in-place) has never needed one.
CUMULATIVE_REMOVED_DYNAMIC = sum(w["removed_dynamic"] for w in DELETED_TEMPLATE_WAVES.values())
EXPECTED_DYNAMIC_STYLE_TOTAL = INITIAL_DYNAMIC_STYLE_TOTAL - CUMULATIVE_REMOVED_DYNAMIC


def test_no_template_is_claimed_by_more_than_one_wave() -> None:
    """A template counted as "removed" by two waves would silently
    double-count -- this would never be caught by the arithmetic alone.
    Covers both wave classes (edited-in-place and deleted-entirely) since
    both feed the same cumulative sums above."""
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    all_waves: dict[str, _WaveManifestEntry | _DeletedWaveManifestEntry] = {
        **STYLE_MIGRATION_WAVES,
        **DELETED_TEMPLATE_WAVES,
    }
    for wave_name, wave in all_waves.items():
        for template in wave["templates"]:
            if template in seen:
                if DISJOINT_RECLAIMS.get(template) == (seen[template], wave_name):
                    continue
                duplicates.append((template, seen[template], wave_name))
            else:
                seen[template] = wave_name
    assert duplicates == [], f"Template(s) claimed by more than one wave: {duplicates!r}"


def test_disjoint_reclaims_never_count_the_same_removal_kind_twice() -> None:
    """Every DISJOINT_RECLAIMS exception must name two existing edit-in-place
    waves that both list the template, the earlier with removed_blocks == 0 and
    the later with removed_static == 0, so no attribute or block is ever
    counted twice."""
    assert DISJOINT_RECLAIMS, "DISJOINT_RECLAIMS should only exist while it has entries"
    for template, (earlier, later) in DISJOINT_RECLAIMS.items():
        assert earlier in STYLE_MIGRATION_WAVES and later in STYLE_MIGRATION_WAVES, (template, earlier, later)
        assert template in STYLE_MIGRATION_WAVES[earlier]["templates"], (template, earlier)
        assert template in STYLE_MIGRATION_WAVES[later]["templates"], (template, later)
        assert list(STYLE_MIGRATION_WAVES).index(earlier) < list(STYLE_MIGRATION_WAVES).index(later)
        assert STYLE_MIGRATION_WAVES[earlier]["removed_blocks"] == 0, (template, earlier)
        assert STYLE_MIGRATION_WAVES[later]["removed_static"] == 0, (template, later)


def test_disjoint_reclaims_is_pinned_to_the_single_reviewed_exception() -> None:
    """The owner approved the reclaim exception for exactly one template and
    one wave pair (PR #75 review). Any other template or wave pair must be
    reviewed and added here explicitly; it cannot ride on this exception."""
    assert DISJOINT_RECLAIMS == {
        "app/templates/support/new.html": ("style2a", "ux_pilot_support_new"),
    }
    assert STYLE_MIGRATION_WAVES["ux_pilot_support_new"]["templates"] == ("app/templates/support/new.html",)


@pytest.mark.parametrize(
    "relative_path",
    sorted({t for w in DELETED_TEMPLATE_WAVES.values() for t in w["templates"]}),
)
def test_every_deleted_wave_target_template_is_genuinely_absent_from_worktree(relative_path: str) -> None:
    """Every template claimed as fully deleted by a DELETED_TEMPLATE_WAVES
    entry must genuinely be gone from the current worktree -- protects
    against the manifest claiming a deletion that never actually happened
    (which would silently make EXPECTED_ACTIVE_STYLE_TOTAL/EXPECTED_STYLE_
    BLOCK_TOTAL wrong while this file's own arithmetic-only tests kept
    passing by coincidence)."""
    assert not (REPO_ROOT / relative_path).exists(), (
        f"{relative_path} is recorded as deleted in DELETED_TEMPLATE_WAVES but "
        "still exists on disk."
    )


def test_deleted_wave_removed_static_and_removed_blocks_match_pre_deletion_git_ref() -> None:
    """Independently re-derives DELETED_TEMPLATE_WAVES' removed_static/
    removed_blocks/removed_dynamic numbers from the fixed historical ref
    immediately BEFORE each wave's own deletion commit, where the templates
    still existed on disk -- never just trusts the manifest's own recorded
    numbers."""
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI not available in this environment.")

    for wave_name, wave in DELETED_TEMPLATE_WAVES.items():
        pre_ref = DELETED_TEMPLATE_WAVES_PRE_DELETION_REF[wave_name]
        total_static = 0
        total_blocks = 0
        total_dynamic = 0
        for relative_path in wave["templates"]:
            result = subprocess.run(
                ["git", "show", f"{pre_ref}:{relative_path}"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                pytest.skip(f"'git show {pre_ref}:{relative_path}' failed; environment limitation.")
            total_static += count_static_style_attrs_in_text(result.stdout, relative_path)
            total_blocks += len(_STYLE_TAG_RE.findall(result.stdout))
            total_dynamic += len(_DYNAMIC_STYLE_ATTR_RE.findall(result.stdout))

        assert total_static == wave["removed_static"], (
            f"{wave_name}: independently-derived static style attribute count at "
            f"{pre_ref} is {total_static}; manifest says removed_static="
            f"{wave['removed_static']}."
        )
        assert total_blocks == wave["removed_blocks"], (
            f"{wave_name}: independently-derived <style> block count at {pre_ref} "
            f"is {total_blocks}; manifest says removed_blocks={wave['removed_blocks']}."
        )
        assert total_dynamic == wave["removed_dynamic"], (
            f"{wave_name}: independently-derived dynamic style attribute count at "
            f"{pre_ref} is {total_dynamic}; manifest says removed_dynamic="
            f"{wave['removed_dynamic']}."
        )


def test_settings_center_v2_templates_contribute_zero_style_debt() -> None:
    """FORWARD-COMPATIBILITY FOLLOW-UP 9 (see module docstring): Settings
    Center V2's new templates use an external stylesheet
    (app/static/css/settings_center.css) and named classes instead of
    inline style="..."/<style> content, so they must independently measure
    to exactly 0 static, 0 blocks, 0 dynamic -- never just trusted. If this
    ever fails, someone added inline style content to one of these
    templates, which would silently raise the repo-wide debt ceiling; fix
    the template (move it to the external stylesheet) rather than updating
    EXPECTED_ACTIVE_STYLE_TOTAL/EXPECTED_STYLE_BLOCK_TOTAL above."""
    for relative_path in _BYS360_SETTINGS_CENTER_V2_TEMPLATES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        static = count_static_style_attrs_in_text(text, relative_path)
        blocks = len(_STYLE_TAG_RE.findall(text))
        dynamic = len(_DYNAMIC_STYLE_ATTR_RE.findall(text))
        assert (static, blocks, dynamic) == (0, 0, 0), (
            f"{relative_path}: expected 0 static/0 blocks/0 dynamic, found "
            f"{static} static/{blocks} blocks/{dynamic} dynamic."
        )


# style3b_low_risk is a BLOCK-only wave (removed_static=0 -- see its manifest
# entry) whose 2 target templates each carry ONE pre-existing, fully-static
# `style="margin-top:16px;"` attribute on a `<section class="bys-rem-card">`
# that has nothing to do with the extracted <style> block and was never in
# this wave's scope. Confirmed identical, byte-for-byte, at the wave's own
# pre-wave git ref (f37a3132ed88921e8389970a6210489111f18c8a) -- i.e.
# genuinely pre-existing, not introduced by this wave. Same precedent as
# Style-3A's own PROGRESS_BAR_TEMPLATES exception in
# test_csp_style3a_duplicate_block_extraction_contract.py (a wave's target
# template can carry an unrelated, out-of-scope style="..." the wave never
# claimed to remove).
KNOWN_PRE_EXISTING_STATIC_ATTR_TEMPLATES = frozenset(
    {
        "app/templates/performance/meeting_development.html",
        "app/templates/performance/meeting_p3_reminders.html",
    }
)

# style3c_meeting_family_group_a is also a BLOCK-only wave (removed_static=0)
# whose 8 target templates each carry TWO pre-existing, fully-static, byte-
# identical `style="margin-top:16px;"` attributes on `<section class="bys-md-
# card">` elements that have nothing to do with the extracted <style> block
# and were never in this wave's scope. Confirmed identical, byte-for-byte, at
# the wave's own pre-wave git ref (7a605b228ab27f0b7048391ff9a672b9e9ee5d33)
# -- i.e. genuinely pre-existing, not introduced by this wave. Same precedent
# as style3b_low_risk's own KNOWN_PRE_EXISTING_STATIC_ATTR_TEMPLATES above
# (a wave's target template can carry an unrelated, out-of-scope style="..."
# the wave never claimed to remove) -- kept as a SEPARATE set/companion test
# below because the expected per-template count here is 2, not 1.
KNOWN_PRE_EXISTING_TWO_STATIC_ATTR_TEMPLATES = frozenset(
    {
        "app/templates/performance/meeting_development_faz3.html",
        "app/templates/performance/meeting_development_faz4.html",
        "app/templates/performance/meeting_development_scenarios.html",
        "app/templates/performance/meeting_final_closure.html",
        "app/templates/performance/meeting_p0_completion.html",
        "app/templates/performance/meeting_p1_scope.html",
        "app/templates/performance/meeting_p2_archive_notes.html",
        "app/templates/performance/meeting_rule_enforcement.html",
    }
)


@pytest.mark.parametrize(
    "relative_path",
    sorted(
        {t for w in STYLE_MIGRATION_WAVES.values() for t in w["templates"]}
        - KNOWN_PRE_EXISTING_STATIC_ATTR_TEMPLATES
        - KNOWN_PRE_EXISTING_TWO_STATIC_ATTR_TEMPLATES
    ),
)
def test_every_wave_target_template_has_zero_active_style_attribute(relative_path: str) -> None:
    """Every template EVER claimed by ANY completed wave must still have
    zero fully-static `style="..."` attributes -- protects against a LATER
    wave accidentally reintroducing one into an already-migrated file.
    Excludes KNOWN_PRE_EXISTING_STATIC_ATTR_TEMPLATES (see that constant's
    own comment for the documented, evidence-based reason)."""
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    count = count_static_style_attrs_in_text(text, relative_path)
    assert count == 0, (
        f"{relative_path} has {count} static style=\"...\" attribute(s) remaining; "
        "this template was already claimed as fully migrated by a completed wave."
    )


@pytest.mark.parametrize("relative_path", sorted(KNOWN_PRE_EXISTING_STATIC_ATTR_TEMPLATES))
def test_known_pre_existing_static_attr_template_has_exactly_the_documented_one_attribute(
    relative_path: str,
) -> None:
    """Companion check for the exception above: proves the excluded count is
    EXACTLY 1 (not silently growing), and that its value is byte-identical
    to the one independently confirmed at the wave's own pre-wave git ref --
    so this exception can never silently mask a REAL regression."""
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    count = count_static_style_attrs_in_text(text, relative_path)
    assert count == 1, (
        f"{relative_path}: expected exactly 1 pre-existing static style=\"...\" "
        f"attribute (the documented bys-rem-card one), found {count}."
    )
    assert 'class="bys-rem-card" style="margin-top:16px;"' in text, (
        f"{relative_path}: the documented pre-existing style=\"margin-top:16px;\" "
        "attribute on class=\"bys-rem-card\" was not found byte-for-byte."
    )


@pytest.mark.parametrize("relative_path", sorted(KNOWN_PRE_EXISTING_TWO_STATIC_ATTR_TEMPLATES))
def test_known_pre_existing_two_static_attr_template_has_exactly_the_documented_two_attributes(
    relative_path: str,
) -> None:
    """Companion check for KNOWN_PRE_EXISTING_TWO_STATIC_ATTR_TEMPLATES above:
    proves the excluded count is EXACTLY 2 (not silently growing), and that
    both occurrences are byte-identical to the ones independently confirmed
    at the wave's own pre-wave git ref -- so this exception can never
    silently mask a REAL regression."""
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    count = count_static_style_attrs_in_text(text, relative_path)
    assert count == 2, (
        f"{relative_path}: expected exactly 2 pre-existing static style=\"...\" "
        f"attributes (the documented bys-md-card ones), found {count}."
    )
    occurrences = text.count('class="bys-md-card" style="margin-top:16px;"')
    assert occurrences == 2, (
        f"{relative_path}: expected exactly 2 byte-identical occurrences of "
        f"'class=\"bys-md-card\" style=\"margin-top:16px;\"', found {occurrences}."
    )


@pytest.mark.parametrize(
    "relative_path",
    sorted(
        {
            t
            for w in STYLE_MIGRATION_WAVES.values()
            if w["removed_blocks"] > 0
            for t in w["templates"]
        }
    ),
)
def test_every_block_removal_wave_target_template_has_zero_style_blocks(relative_path: str) -> None:
    """Every template EVER claimed by a wave that removed `<style>` BLOCKS
    (not just attributes -- `removed_blocks > 0`) must still have zero
    `<style>` blocks -- the block-removal analog of the active-attribute
    check above, protecting against a LATER wave accidentally reintroducing
    a block into an already-migrated file. Style-2A/2B never removed a
    block (`removed_blocks: 0`), so this currently only covers Style-3A's
    10 templates; Style-3A's own dedicated contract file
    (test_csp_style3a_duplicate_block_extraction_contract.py) already
    covers this per-template, per-group, in far more depth (byte-parity,
    link-tag shape, live render/HTTP proof, etc.) -- this is a deliberately
    short cross-check, valuable specifically because THIS file is the one
    place that reasons about ALL waves cumulatively."""
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    count = len(_STYLE_TAG_RE.findall(text))
    assert count == 0, (
        f"{relative_path} has {count} <style> block(s) remaining; this template was "
        "already claimed as fully block-migrated by a completed wave."
    )


def test_cumulative_active_static_style_total_matches_manifest() -> None:
    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL, (
        f"Repo-wide active (static) style attribute total is "
        f"{inventory.active_static_total}; expected "
        f"{INITIAL_ACTIVE_STYLE_TOTAL} - {CUMULATIVE_REMOVED_STATIC} "
        f"(cumulative across waves {sorted(STYLE_MIGRATION_WAVES)}) = "
        f"{EXPECTED_ACTIVE_STYLE_TOTAL}."
    )


def test_cumulative_dynamic_style_total_matches_manifest() -> None:
    """Renamed from test_cumulative_dynamic_style_total_is_unchanged (see
    FORWARD-COMPATIBILITY FOLLOW-UP 6 in the module docstring): a flat
    "always equals INITIAL_DYNAMIC_STYLE_TOTAL" lock held for every wave
    until workflow_orphan_presentation_cleanup, the first DELETED_TEMPLATE_
    WAVES entry to legitimately remove a dynamic attribute (by deleting the
    dead template that carried it)."""
    inventory = compute_inventory_from_worktree()
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL, (
        f"Repo-wide Jinja-dynamic style attribute total is {inventory.dynamic_total}; "
        f"expected {INITIAL_DYNAMIC_STYLE_TOTAL} - {CUMULATIVE_REMOVED_DYNAMIC} "
        f"(cumulative across deleted-template waves) = {EXPECTED_DYNAMIC_STYLE_TOTAL}. "
        "No edit-in-place wave may add/remove a dynamic style attribute; only a "
        "deleted-template wave's own manifest-declared removed_dynamic may."
    )


def test_cumulative_style_block_total_matches_manifest() -> None:
    inventory = compute_inventory_from_worktree()
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL, (
        f"Repo-wide <style> block total is {inventory.style_block_total}; expected "
        f"{INITIAL_STYLE_BLOCK_TOTAL} - {CUMULATIVE_REMOVED_BLOCKS} "
        f"(cumulative across waves {sorted(STYLE_MIGRATION_WAVES)}) = "
        f"{EXPECTED_STYLE_BLOCK_TOTAL}."
    )


def test_cumulative_inline_handler_total_is_zero() -> None:
    inventory = compute_inventory_from_worktree()
    assert inventory.inline_handler_total == 0, (
        f"Repo-wide inline event-handler (on*=) total is "
        f"{inventory.inline_handler_total}; expected 0."
    )


def test_cumulative_javascript_url_total_is_zero() -> None:
    inventory = compute_inventory_from_worktree()
    assert inventory.javascript_url_total == 0, (
        f"Repo-wide javascript: URL total is {inventory.javascript_url_total}; expected 0."
    )


def test_initial_baseline_constants_match_historical_git_ref() -> None:
    """Re-derives INITIAL_ACTIVE_STYLE_TOTAL / INITIAL_DYNAMIC_STYLE_TOTAL /
    INITIAL_STYLE_BLOCK_TOTAL directly from the fixed historical commit they
    claim to come from, so the baseline can never silently drift from its
    own evidence. Skips ONLY if the `git` binary itself is unavailable (an
    environment limitation) -- NOT based on whether there is any pending
    diff, so this runs identically on a clean, fully-committed worktree."""
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=False, timeout=10)
    except OSError:
        pytest.skip("git CLI not available in this environment.")

    verify = subprocess.run(
        ["git", "cat-file", "-e", INITIAL_BASELINE_GIT_REF],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if verify.returncode != 0:
        pytest.skip(
            f"Historical ref {INITIAL_BASELINE_GIT_REF} not present in this checkout "
            "(e.g. a shallow clone) -- environment limitation, not a correctness gap."
        )

    inventory = compute_inventory_at_git_ref(INITIAL_BASELINE_GIT_REF)
    assert inventory.active_static_total == INITIAL_ACTIVE_STYLE_TOTAL, (
        f"Historical active total at {INITIAL_BASELINE_GIT_REF} is "
        f"{inventory.active_static_total}, constant says {INITIAL_ACTIVE_STYLE_TOTAL}."
    )
    assert inventory.dynamic_total == INITIAL_DYNAMIC_STYLE_TOTAL, (
        f"Historical dynamic total at {INITIAL_BASELINE_GIT_REF} is "
        f"{inventory.dynamic_total}, constant says {INITIAL_DYNAMIC_STYLE_TOTAL}."
    )
    assert inventory.style_block_total == INITIAL_STYLE_BLOCK_TOTAL, (
        f"Historical style-block total at {INITIAL_BASELINE_GIT_REF} is "
        f"{inventory.style_block_total}, constant says {INITIAL_STYLE_BLOCK_TOTAL}."
    )


def test_style_inventory_scope_roots_are_exactly_the_flask_jinja_template_roots() -> None:
    """Locks the canonical scope itself: app/templates + app/modules/*/
    templates + app/workflow/templates, nothing more, nothing less
    (in particular: NOT app/static, NOT scripts/)."""
    from tests.security._bys360_style_inventory import STYLE_ATTR_SCOPE_ROOTS

    relative_roots = sorted(
        str(root.relative_to(REPO_ROOT)).replace("\\", "/") for root in STYLE_ATTR_SCOPE_ROOTS
    )
    assert "app/templates" in relative_roots
    assert "app/workflow/templates" in relative_roots
    assert any(r.startswith("app/modules/") and r.endswith("/templates") for r in relative_roots)
    assert not any(r.startswith("app/static") for r in relative_roots)
    assert not any(r.startswith("scripts") for r in relative_roots)
