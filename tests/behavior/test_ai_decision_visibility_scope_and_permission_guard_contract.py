"""BYS360_PHASE5_COVERAGE_WAVE4_AGENT1_AI_DECISION_VISIBILITY_PERMISSION_CONTRACT

Behavioral contract for the two modules that gate the AI Karar Destek
(Decision Support) Faz 3 surface:

    app/services/ai_decision/visibility_scope.py
        normalize_role_name, role_group_for, build_ai_decision_scope,
        same_scope_label, user_matches_scope, build_safe_scope_payload

    app/services/ai_decision/permission_guard.py
        AIDecisionPermissionDenied, get_ai_decision_scope_for_user,
        build_ai_decision_visibility_context, assert_center_access,
        can_view_evaluation, assert_evaluation_access,
        filter_evaluations_for_user, build_evaluation_visibility_payload

No prior test in this repo references either module or any of these
function names -- this file is the first coverage for both. Wave 2's
tests/behavior/test_visibility_guard_evaluation_access_contract.py covers a
different module entirely (app/services/performance/visibility_guard.py)
and is unrelated to this scope.

Predominantly pure-function: real functions are called directly against
``SimpleNamespace`` fake users/evaluations -- no mocking of the functions
under test. One DB-backed fixture proves ``filter_evaluations_for_user``
genuinely restricts a real SQLAlchemy query; its shape follows the proven
mandatory pattern from tests/behavior/test_admin_ops_user_actions_destructive_operations_contract.py
(Config class attributes patched BEFORE create_app(), StaticPool + pysqlite
dual-connection isolation-level fix) using its own dedicated tmp DB
directory (C:\\bys360_pytest_tmp_agent1_aidecision) so it shares no state
with any other wave/agent.

Defect-D boundary note: ``role_group_for("Grup Başkanı")`` is verified below
to resolve to "manager_scope", not "global". Tracing the real code: this
input normalizes to "grup_baskani", an EXACT member of ``_MANAGER_SCOPE_ROLES``
matched at the third exact-set check in ``role_group_for`` -- long before any
substring-fallback branch is reached. This module's own role-group
resolution is independently verified correct for this exact input, on a
code path distinct and unrelated to Defect D's module
(app/services/hierarchy_rulebook_service.py, out of scope here).

``filter_evaluations_for_user``'s ``if not scope_clauses:`` branch (line
~116) is dead code for any non-global caller with a real user id --
``scope_clauses`` always starts with ``[evaluator_clause]`` -- so it is not
exercised here; forcing it would require editing production code, which is
out of scope for this file.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

from app.services.ai_decision.permission_guard import (
    AIDecisionPermissionDenied,
    assert_center_access,
    assert_evaluation_access,
    build_ai_decision_visibility_context,
    build_evaluation_visibility_payload,
    can_view_evaluation,
    filter_evaluations_for_user,
    get_ai_decision_scope_for_user,
)
from app.services.ai_decision.visibility_scope import (
    build_ai_decision_scope,
    build_safe_scope_payload,
    normalize_role_name,
    role_group_for,
    same_scope_label,
    user_matches_scope,
)

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent1_aidecision")


# ---------------------------------------------------------------------------
# 1. normalize_role_name / role_group_for -- pure string normalization
# ---------------------------------------------------------------------------


def test_normalize_role_name_turkish_diacritics_and_punctuation():
    assert normalize_role_name("Grup Başkanı") == "grup_baskani"
    assert normalize_role_name("  Koordinatör  ") == "koordinator"
    assert normalize_role_name("") == "personel"
    assert normalize_role_name(None) == "personel"


@pytest.mark.parametrize(
    "role,expected_group",
    [
        ("admin", "global"),
        # B1-F1 (approved policy, 2026-10-09): the technical role and ik / performans_yetkilisi
        # get no institution-wide evaluation scope by role name (decision 2 and the base policy).
        ("sistem_yoneticisi", "own_scope"),
        ("baskan", "global"),
        ("Başkan", "global"),
        ("performans_yetkilisi", "own_scope"),
        ("ik", "own_scope"),
        ("performans_admin", "performance_authority"),
        ("grup_baskani", "manager_scope"),
        ("koordinator", "manager_scope"),
        ("personel", "own_scope"),
        ("temizlik_personeli", "own_scope"),
    ],
)
def test_role_group_for_exact_and_fallback_matrix(role, expected_group):
    assert role_group_for(role) == expected_group
    assert role_group_for(SimpleNamespace(role=role)) == expected_group


def test_role_group_for_defect_d_boundary_grup_baskani_is_manager_not_global():
    # Mandatory Defect-D collision guard (see module docstring): this exact
    # string is an EXACT match in _MANAGER_SCOPE_ROLES, resolved before any
    # substring fallback is ever reached. Verified independently of Defect D.
    assert role_group_for("Grup Başkanı") == "manager_scope"
    assert role_group_for(SimpleNamespace(role="Grup Başkanı")) == "manager_scope"


# BYS360 DEFECT AQ: role_group_for'un eski substring-fallback bloğu
# (tam rol kodu eşleşmese bile metinde "baskan"/"admin"/"grup" gibi alt
# dizeler geçtiğinde kapsam veren kısım) tamamen kaldırıldı -- kanonik rol
# kodu olmayan HER girdi artık güvenli varsayılan "own_scope"a düşer. Bu iki
# test önceki (kaldırılan) fallback davranışını değil, düzeltilmiş,
# güvenli-varsayılan davranışı kilitler.
def test_role_group_for_non_canonical_lookalike_falls_back_to_own_scope_not_manager():
    synthetic_role = "grup_lideri_baskanvekili"
    assert role_group_for(synthetic_role) == "own_scope"


def test_role_group_for_baskanligi_uzmani_lookalike_denied_global_scope():
    # phase6's is_president_user kendi yorumu: "kurum adı veya 'Başkanlığı'
    # metni yetki vermez." Aynı ilke burada da geçerli olmalı: "Başkanlığı
    # Uzmanı" (Başkan değil, sıradan bir uzman unvanı) "baskan" alt dizesini
    # içerir ama kanonik hiçbir kümenin tam üyesi değildir -- artık "global"
    # değil, "own_scope" döner.
    assert role_group_for("Başkanlığı Uzmanı") == "own_scope"
    assert role_group_for(SimpleNamespace(role="Başkanlığı Uzmanı")) == "own_scope"


def test_role_group_for_free_form_display_text_with_privileged_substrings_denied():
    # Serbest metin unvan/görev alanları (ör. "Sistem Destek ve Bakım
    # Uzmanı" -- ne admin ne başkan) kanonik kümelerin dışındadır ve artık
    # yalnızca güvenli varsayılana düşer, alt dize eşleşmesiyle
    # yükseltilmez.
    assert role_group_for("Sistem Destek ve Bakım Uzmanı") == "own_scope"
    assert role_group_for("Grup Koordinasyon Ofisi Asistanı") == "own_scope"


def test_role_group_for_unknown_or_malformed_role_denied():
    assert role_group_for("") == "own_scope"
    assert role_group_for(None) == "own_scope"
    assert role_group_for(SimpleNamespace(role=None)) == "own_scope"
    assert role_group_for(SimpleNamespace()) == "own_scope"


# ---------------------------------------------------------------------------
# 2. build_ai_decision_scope -- the full authorization matrix
# ---------------------------------------------------------------------------


def _user(role, *, user_id=1, birim=None, ust_birim=None, personnel_category=None, **extra):
    return SimpleNamespace(
        id=user_id,
        role=role,
        birim=birim,
        ust_birim=ust_birim,
        personnel_category=personnel_category,
        **extra,
    )


def test_build_ai_decision_scope_global_roles_admin_and_baskan():
    for role in ("admin", "baskan"):
        scope = build_ai_decision_scope(_user(role))
        assert scope.role_group == "global"
        assert scope.can_open_center is True
        assert scope.can_view_global_summary is True
        assert scope.can_view_person_level_detail is True
        assert scope.can_view_unit_scope is True
        assert scope.can_view_category_scope is True
        assert scope.can_view_own_summary is True
        assert scope.denied_reason is None
        assert scope.is_global is True
        assert scope.is_restricted is False


def test_build_ai_decision_scope_performance_authority_has_identical_flags_to_global():
    # Mandatory: performance_authority gets the SAME full access flags as global -- a real
    # and easy-to-miss distinction from manager_scope, which does NOT get
    # can_view_global_summary. B1-F1 (2026-10-09): ik and performans_yetkilisi left this group
    # (they are own_scope now); performans_admin and personel_destek remain in it.
    admin_scope = build_ai_decision_scope(_user("admin", user_id=10))
    perf_scope = build_ai_decision_scope(_user("performans_admin", user_id=20))
    ik_scope = build_ai_decision_scope(_user("personel_destek", user_id=30))

    flag_fields = (
        "can_open_center",
        "can_view_global_summary",
        "can_view_person_level_detail",
        "can_view_unit_scope",
        "can_view_category_scope",
        "can_view_own_summary",
    )
    admin_flags = tuple(getattr(admin_scope, f) for f in flag_fields)
    perf_flags = tuple(getattr(perf_scope, f) for f in flag_fields)
    ik_flags = tuple(getattr(ik_scope, f) for f in flag_fields)

    assert admin_flags == perf_flags == ik_flags == (True, True, True, True, True, True)
    assert perf_scope.role_group == "performance_authority"
    assert ik_scope.role_group == "performance_authority"


def test_build_ai_decision_scope_manager_scope_populates_unit_and_category_and_hides_global():
    manager = _user(
        "grup_baskani",
        user_id=5,
        birim="Satış",
        ust_birim="Ticari Direktörlük",
        personnel_category="Yönetici",
    )
    scope = build_ai_decision_scope(manager)

    assert scope.role_group == "manager_scope"
    assert scope.can_open_center is True
    assert scope.can_view_global_summary is False
    assert scope.can_view_person_level_detail is True
    assert scope.can_view_unit_scope is True
    assert scope.can_view_category_scope is True
    assert scope.can_view_own_summary is True
    assert scope.allowed_unit_names == ("Satış",)
    assert scope.allowed_upper_unit_names == ("Ticari Direktörlük",)
    assert scope.allowed_category_labels == ("Yönetici",)
    assert scope.is_global is False
    assert scope.is_restricted is True


def test_build_ai_decision_scope_personnel_is_own_scope_only():
    personnel = _user("personel", user_id=7, birim="Muhasebe", personnel_category="Beyaz Yaka")
    scope = build_ai_decision_scope(personnel)

    assert scope.role_group == "own_scope"
    assert scope.can_open_center is False
    assert scope.can_view_global_summary is False
    assert scope.can_view_person_level_detail is False
    assert scope.can_view_unit_scope is False
    assert scope.can_view_category_scope is True
    assert scope.can_view_own_summary is True
    assert scope.denied_reason == "Karar Destek Merkezi yönetici ve yetkili kullanıcı görünürlüğündedir."


def test_build_ai_decision_scope_anonymous_none_user_is_denied():
    scope = build_ai_decision_scope(None)
    assert scope.role == "anonymous"
    assert scope.role_group == "denied"
    assert scope.can_open_center is False
    assert scope.can_view_global_summary is False
    assert scope.denied_reason == "Oturum bilgisi bulunamadı."


def test_build_ai_decision_scope_unauthenticated_flag_is_denied():
    scope = build_ai_decision_scope(SimpleNamespace(is_authenticated=False, role="admin"))
    assert scope.role == "anonymous"
    assert scope.can_open_center is False
    assert scope.denied_reason == "Oturum bilgisi bulunamadı."


# ---------------------------------------------------------------------------
# 3. same_scope_label / user_matches_scope
# ---------------------------------------------------------------------------


def test_same_scope_label_normalizes_and_rejects_empty():
    assert same_scope_label("Satış", "  satış ") is True
    assert same_scope_label("", "") is False
    assert same_scope_label(None, None) is False


def test_user_matches_scope_own_scope_self_only():
    personnel = _user("personel", user_id=7)
    scope = build_ai_decision_scope(personnel)
    assert user_matches_scope(scope, personnel) is True
    stranger = _user("personel", user_id=99)
    assert user_matches_scope(scope, stranger) is False


def test_user_matches_scope_manager_unit_and_upper_unit_and_category():
    manager = _user(
        "grup_baskani",
        user_id=5,
        birim="Satış",
        ust_birim="Ticari Direktörlük",
        personnel_category="Yönetici",
    )
    scope = build_ai_decision_scope(manager)

    same_unit_colleague = _user("personel", user_id=101, birim="Satış", ust_birim="Diğer", personnel_category="Diğer")
    same_upper_unit_colleague = _user("personel", user_id=102, birim="Başka", ust_birim="Ticari Direktörlük", personnel_category="Diğer")
    unrelated = _user("personel", user_id=103, birim="Muhasebe", ust_birim="Mali İşler", personnel_category="Farklı")

    assert user_matches_scope(scope, same_unit_colleague) is True
    assert user_matches_scope(scope, same_upper_unit_colleague) is True
    assert user_matches_scope(scope, unrelated) is False


# ---------------------------------------------------------------------------
# 4. build_safe_scope_payload -- must be a straight passthrough, no leak
# ---------------------------------------------------------------------------


def test_build_safe_scope_payload_is_a_passthrough_not_an_expansion():
    manager = _user(
        "grup_baskani",
        user_id=5,
        birim="Satış",
        ust_birim="Ticari Direktörlük",
        personnel_category="Yönetici",
    )
    scope = build_ai_decision_scope(manager)
    base_dict = scope.to_dict()

    with_menu = build_safe_scope_payload(scope, include_menu_keys=True)
    without_menu = build_safe_scope_payload(scope, include_menu_keys=False)

    # Every key/value already present in to_dict() is carried through
    # unchanged -- the safe payload never re-derives or widens scope data.
    for key, value in base_dict.items():
        assert with_menu[key] == value
        assert without_menu[key] == value

    assert set(with_menu.keys()) - set(base_dict.keys()) == {"menu_keys", "visibility_rules"}
    assert set(without_menu.keys()) - set(base_dict.keys()) == {"visibility_rules"}
    assert isinstance(with_menu["visibility_rules"], list) and len(with_menu["visibility_rules"]) == 4


# ---------------------------------------------------------------------------
# 5. assert_center_access
# ---------------------------------------------------------------------------


def test_assert_center_access_allows_global_and_manager():
    admin_scope = assert_center_access(_user("admin"))
    assert admin_scope.can_open_center is True

    manager_scope = assert_center_access(_user("grup_baskani"))
    assert manager_scope.can_open_center is True


def test_assert_center_access_denies_personnel_with_exact_reason():
    with pytest.raises(AIDecisionPermissionDenied) as exc_info:
        assert_center_access(_user("personel"))
    assert exc_info.value.message == "Karar Destek Merkezi yönetici ve yetkili kullanıcı görünürlüğündedir."


def test_assert_center_access_denies_anonymous_with_exact_reason():
    with pytest.raises(AIDecisionPermissionDenied) as exc_info:
        assert_center_access(None)
    assert exc_info.value.message == "Oturum bilgisi bulunamadı."


# ---------------------------------------------------------------------------
# 6. can_view_evaluation / assert_evaluation_access
# ---------------------------------------------------------------------------


def _evaluation(*, employee, level_1=None, level_2=None, level_3=None, published=False, eval_id=1):
    return SimpleNamespace(
        id=eval_id,
        period_id=1,
        employee_id=getattr(employee, "id", None),
        employee=employee,
        level_1_evaluator_id=level_1,
        level_2_evaluator_id=level_2,
        level_3_evaluator_id=level_3,
        is_published_to_employee=published,
    )


def test_can_view_evaluation_global_role_sees_everything():
    admin = _user("admin", user_id=1)
    employee = _user("personel", user_id=50, birim="X")
    evaluation = _evaluation(employee=employee, eval_id=900)
    assert can_view_evaluation(admin, evaluation) is True


def test_can_view_evaluation_assigned_evaluator_overrides_role_and_scope():
    # Evaluator access does NOT depend on role_group at all -- checked before
    # scope/employee matching. A plain "personel" who is the assigned
    # evaluator of a wholly unrelated employee still gets access.
    evaluator = _user("personel", user_id=42, birim="Farklı Birim", personnel_category="Farklı Kategori")
    unrelated_employee = _user("personel", user_id=999, birim="Uzak Birim", personnel_category="Uzak Kategori")
    evaluation = _evaluation(employee=unrelated_employee, level_2=42, eval_id=901)
    assert can_view_evaluation(evaluator, evaluation) is True


def test_can_view_evaluation_own_published_evaluation_is_visible():
    personnel = _user("personel", user_id=7, birim="Muhasebe")
    evaluation = _evaluation(employee=personnel, published=True, eval_id=902)
    assert can_view_evaluation(personnel, evaluation) is True


def test_can_view_evaluation_own_unpublished_evaluation_is_not_visible():
    personnel = _user("personel", user_id=7, birim="Muhasebe")
    evaluation = _evaluation(employee=personnel, published=False, eval_id=903)
    assert can_view_evaluation(personnel, evaluation) is False


def test_can_view_evaluation_allow_own_published_false_gates_own_published_view():
    # Proves the allow_own_published parameter genuinely gates access, even
    # for an evaluation that IS published.
    personnel = _user("personel", user_id=7, birim="Muhasebe")
    evaluation = _evaluation(employee=personnel, published=True, eval_id=904)
    assert can_view_evaluation(personnel, evaluation, allow_own_published=False) is False


def test_can_view_evaluation_colleague_not_evaluator_not_in_scope_is_denied():
    personnel = _user("personel", user_id=7, birim="Muhasebe", personnel_category="Beyaz Yaka")
    colleague = _user("personel", user_id=8, birim="Üretim", personnel_category="Mavi Yaka")
    evaluation = _evaluation(employee=colleague, eval_id=905)
    assert can_view_evaluation(personnel, evaluation) is False


def test_can_view_evaluation_manager_sees_person_level_detail_for_in_scope_employee():
    manager = _user("grup_baskani", user_id=5, birim="Satış", ust_birim="Ticari", personnel_category="Yönetici")
    employee_in_scope = _user("personel", user_id=60, birim="Satış", personnel_category="Diğer")
    evaluation = _evaluation(employee=employee_in_scope, eval_id=906)
    assert can_view_evaluation(manager, evaluation) is True


def test_can_view_evaluation_fails_closed_without_user_id():
    no_id_user = SimpleNamespace(role="personel")
    employee = _user("personel", user_id=7)
    evaluation = _evaluation(employee=employee, eval_id=907)
    assert can_view_evaluation(no_id_user, evaluation) is False


def test_can_view_evaluation_none_evaluation_is_denied_for_non_global():
    personnel = _user("personel", user_id=7)
    assert can_view_evaluation(personnel, None) is False


def test_assert_evaluation_access_raises_permission_denied_not_other_exception():
    personnel = _user("personel", user_id=7, birim="Muhasebe", personnel_category="Beyaz Yaka")
    colleague = _user("personel", user_id=8, birim="Üretim", personnel_category="Mavi Yaka")
    evaluation = _evaluation(employee=colleague, eval_id=908)
    with pytest.raises(AIDecisionPermissionDenied) as exc_info:
        assert_evaluation_access(personnel, evaluation)
    assert exc_info.value.message == "Bu performans karar destek kaydına erişim yetkiniz bulunmamaktadır."


def test_assert_evaluation_access_returns_scope_on_success():
    evaluator = _user("personel", user_id=42)
    unrelated_employee = _user("personel", user_id=999, birim="Uzak")
    evaluation = _evaluation(employee=unrelated_employee, level_1=42, eval_id=909)
    scope = assert_evaluation_access(evaluator, evaluation)
    assert scope.user_id == 42
    assert scope.role_group == "own_scope"


# ---------------------------------------------------------------------------
# 7. thin wrapper coverage: get_ai_decision_scope_for_user,
#    build_ai_decision_visibility_context, build_evaluation_visibility_payload
# ---------------------------------------------------------------------------


def test_get_ai_decision_scope_for_user_delegates_to_build_ai_decision_scope():
    admin = _user("admin")
    assert get_ai_decision_scope_for_user(admin) == build_ai_decision_scope(admin)


def test_build_ai_decision_visibility_context_shape():
    ctx = build_ai_decision_visibility_context(_user("personel"))
    assert ctx["ok"] is True
    assert ctx["data"]["scope"]["role_group"] == "own_scope"
    assert "access_message" in ctx["data"]


def test_build_evaluation_visibility_payload_allowed_and_denied_messages():
    evaluator = _user("personel", user_id=42)
    unrelated_employee = _user("personel", user_id=999, birim="Uzak", ust_birim="Uzak Üst", personnel_category="Uzak")
    allowed_evaluation = _evaluation(employee=unrelated_employee, level_3=42, eval_id=910)
    allowed_payload = build_evaluation_visibility_payload(evaluator, allowed_evaluation)
    assert allowed_payload["data"]["allowed"] is True
    assert allowed_payload["data"]["message"] == "Erişim yetkisi uygundur."
    assert allowed_payload["data"]["evaluation"]["employee_scope"]["birim"] == "Uzak"

    personnel = _user("personel", user_id=7, birim="Muhasebe", personnel_category="Beyaz Yaka")
    colleague = _user("personel", user_id=8, birim="Üretim", personnel_category="Mavi Yaka")
    denied_evaluation = _evaluation(employee=colleague, eval_id=911)
    denied_payload = build_evaluation_visibility_payload(personnel, denied_evaluation)
    assert denied_payload["data"]["allowed"] is False
    assert denied_payload["data"]["message"] == "Bu performans karar destek kaydına erişim yetkiniz bulunmamaktadır."


# ---------------------------------------------------------------------------
# 8. filter_evaluations_for_user -- fake-query negative/bypass cases
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self):
        self.filter_calls = []

    def filter(self, clause):
        self.filter_calls.append(clause)
        return self


def test_filter_evaluations_for_user_global_role_returns_query_unchanged():
    query = _FakeQuery()
    admin = _user("admin", user_id=1)
    result = filter_evaluations_for_user(query, admin, EvaluationModel=None, UserModel=None)
    assert result is query
    assert query.filter_calls == []


def test_filter_evaluations_for_user_missing_user_id_fails_closed():
    query = _FakeQuery()
    no_id_user = SimpleNamespace(role="personel")
    result = filter_evaluations_for_user(query, no_id_user, EvaluationModel=None, UserModel=None)
    assert result is query
    assert query.filter_calls == [False]


# ---------------------------------------------------------------------------
# 9. filter_evaluations_for_user -- real DB positive scope-restriction proof
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-ai-decision-visibility-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "ai-decision-first-login-test-pw")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"agent1_aidecision_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # Config.SQLALCHEMY_DATABASE_URI is a class attribute frozen the first
    # time config.py is imported in this pytest process, and Flask-SQLAlchemy
    # 3.x lazily binds+caches the per-app Engine on first db.engine/db.session
    # touch during create_app()'s own bootstrap -- so it must be patched onto
    # Config BEFORE create_app() is called, not onto flask_app.config after.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )

    from app.extensions import db

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()

    return flask_app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


def test_filter_evaluations_for_user_manager_scope_restricts_real_query(app):
    from app.extensions import db
    from app.models import PerformanceEvaluation, PerformancePeriod, User

    with app.app_context():
        period = PerformancePeriod(
            title="2026 Yıl Sonu",
            period_type="yillik",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        db.session.add(period)
        db.session.flush()

        manager = User(
            sicil_no="AID000001",
            email="manager-aid@bys360.test",
            ad="Manager",
            soyad="One",
            role="grup_baskani",
            birim="Satış",
            ust_birim="Ticari Direktörlük",
            personnel_category="YonetimKademesi",
        )
        manager.set_password("AiDecisionTest1!")

        emp_same_birim = User(
            sicil_no="AID000002", email="emp-a-aid@bys360.test", ad="EmpA", soyad="Same",
            role="personel", birim="Satış", ust_birim="Farklı", personnel_category="FarkliKategori1",
        )
        emp_same_ust_birim = User(
            sicil_no="AID000003", email="emp-b-aid@bys360.test", ad="EmpB", soyad="UstBirim",
            role="personel", birim="Başka Birim", ust_birim="Ticari Direktörlük", personnel_category="FarkliKategori2",
        )
        emp_out_of_scope = User(
            sicil_no="AID000004", email="emp-c-aid@bys360.test", ad="EmpC", soyad="Out",
            role="personel", birim="Muhasebe", ust_birim="Mali İşler", personnel_category="FarkliKategori3",
        )
        emp_evaluator_override = User(
            sicil_no="AID000005", email="emp-d-aid@bys360.test", ad="EmpD", soyad="Override",
            role="personel", birim="Uzak Birim", ust_birim="Uzak Üst Birim", personnel_category="FarkliKategori4",
        )
        for emp in (emp_same_birim, emp_same_ust_birim, emp_out_of_scope, emp_evaluator_override):
            emp.set_password("AiDecisionTest1!")

        db.session.add_all([manager, emp_same_birim, emp_same_ust_birim, emp_out_of_scope, emp_evaluator_override])
        db.session.flush()

        eval_a = PerformanceEvaluation(period_id=period.id, employee_id=emp_same_birim.id)
        eval_b = PerformanceEvaluation(period_id=period.id, employee_id=emp_same_ust_birim.id)
        eval_c = PerformanceEvaluation(period_id=period.id, employee_id=emp_out_of_scope.id)
        eval_d = PerformanceEvaluation(
            period_id=period.id,
            employee_id=emp_evaluator_override.id,
            level_1_evaluator_id=manager.id,
        )
        db.session.add_all([eval_a, eval_b, eval_c, eval_d])
        db.session.commit()

        result_ids = {
            row.id
            for row in filter_evaluations_for_user(
                PerformanceEvaluation.query, manager, PerformanceEvaluation, User
            ).all()
        }

        # In-scope via matching birim, matching ust_birim, and the
        # evaluator-id override are all included; the wholly unrelated
        # colleague (no unit/category/evaluator match) is excluded.
        assert result_ids == {eval_a.id, eval_b.id, eval_d.id}
        assert eval_c.id not in result_ids
