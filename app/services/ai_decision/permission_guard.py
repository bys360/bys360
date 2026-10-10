
"""BYS360 AI Karar Destek Faz 3 route ve veri erişim koruması.

Bu servis, Karar Destek Merkezi uçlarında menü görünürlüğü ile backend veri
kapsamının aynı şekilde çalışmasını sağlar. Yetkisiz kullanıcı beyaz sayfaya
veya teknik hataya düşmez; kurumsal Türkçe erişim mesajı üretilir.

BYS360_AI_DECISION_FAZ3_PERMISSION_GUARD
"""
from __future__ import annotations

from typing import Any

from app.services.ai_decision.visibility_scope import (
    AIDecisionVisibilityScope,
    build_ai_decision_scope,
    build_safe_scope_payload,
    normalize_role_name,
    user_matches_scope,
)

# B1-F1 decision 2: the technical roles keep the module health checks (marker, module settings,
# fixed principle texts; no personal data) although they no longer open the centre's data.
_TECHNICAL_HEALTH_ROLES = {"sistem_yoneticisi", "system_admin"}


class AIDecisionPermissionDenied(PermissionError):
    """Karar destek görünürlüğü kapsam dışı olduğunda yükseltilir."""

    def __init__(self, message: str = "Bu sayfaya erişim yetkiniz bulunmamaktadır.") -> None:
        super().__init__(message)
        self.message = message


def get_ai_decision_scope_for_user(user: Any) -> AIDecisionVisibilityScope:
    return build_ai_decision_scope(user)


def build_ai_decision_visibility_context(user: Any) -> dict[str, Any]:
    scope = get_ai_decision_scope_for_user(user)
    return {
        "ok": True,
        "data": {
            "scope": build_safe_scope_payload(scope),
            "access_message": "Karar destek görünürlüğü kapsamı başarıyla hesaplandı.",
        },
    }


def assert_center_access(user: Any) -> AIDecisionVisibilityScope:
    scope = get_ai_decision_scope_for_user(user)
    if not scope.can_open_center:
        raise AIDecisionPermissionDenied(scope.denied_reason or "Bu sayfaya erişim yetkiniz bulunmamaktadır.")
    return scope


def assert_health_access(user: Any) -> AIDecisionVisibilityScope:
    """Health endpoints only: centre access, or a technical role read from the stored role."""
    scope = get_ai_decision_scope_for_user(user)
    if scope.can_open_center:
        return scope
    if (
        user is not None
        and getattr(user, "is_authenticated", True)
        and normalize_role_name(getattr(user, "role", None)) in _TECHNICAL_HEALTH_ROLES
    ):
        return scope
    raise AIDecisionPermissionDenied(scope.denied_reason or "Bu sayfaya erişim yetkiniz bulunmamaktadır.")


def can_view_evaluation(user: Any, evaluation: Any, *, allow_own_published: bool = True) -> bool:
    """Kullanıcının tek bir performans değerlendirmesini görüp göremeyeceğini kontrol eder."""
    scope = get_ai_decision_scope_for_user(user)
    if scope.can_view_global_summary:
        return True

    user_id = getattr(user, "id", None)
    if not user_id or evaluation is None:
        return False

    evaluator_ids = {
        getattr(evaluation, "level_1_evaluator_id", None),
        getattr(evaluation, "level_2_evaluator_id", None),
        getattr(evaluation, "level_3_evaluator_id", None),
    }
    if user_id in evaluator_ids:
        return True

    employee = getattr(evaluation, "employee", None)
    if employee is not None and user_matches_scope(scope, employee):
        if getattr(employee, "id", None) == user_id:
            return bool(allow_own_published and getattr(evaluation, "is_published_to_employee", False))
        return bool(scope.can_view_person_level_detail)

    return False


def assert_evaluation_access(user: Any, evaluation: Any, *, allow_own_published: bool = True) -> AIDecisionVisibilityScope:
    scope = get_ai_decision_scope_for_user(user)
    if not can_view_evaluation(user, evaluation, allow_own_published=allow_own_published):
        raise AIDecisionPermissionDenied("Bu performans karar destek kaydına erişim yetkiniz bulunmamaktadır.")
    return scope


def filter_evaluations_for_user(query: Any, user: Any, EvaluationModel: Any, UserModel: Any) -> Any:
    """SQLAlchemy sorgusunu kullanıcının görünürlük kapsamına göre daraltır."""
    scope = get_ai_decision_scope_for_user(user)
    if scope.can_view_global_summary:
        return query

    user_id = getattr(user, "id", None)
    if not user_id:
        return query.filter(False)

    # Değerlendirici, kendi görevleri üzerinden personel ayrıntısını görür.
    evaluator_clause = (
        (EvaluationModel.level_1_evaluator_id == user_id)
        | (EvaluationModel.level_2_evaluator_id == user_id)
        | (EvaluationModel.level_3_evaluator_id == user_id)
    )

    query = query.join(UserModel, EvaluationModel.employee_id == UserModel.id)

    scope_clauses = [evaluator_clause]
    if scope.can_view_own_summary:
        scope_clauses.append(EvaluationModel.employee_id == user_id)
    if scope.can_view_unit_scope:
        if scope.allowed_unit_names:
            scope_clauses.append(UserModel.birim.in_(list(scope.allowed_unit_names)))
        if scope.allowed_upper_unit_names:
            scope_clauses.append(UserModel.ust_birim.in_(list(scope.allowed_upper_unit_names)))
    if scope.can_view_category_scope and scope.allowed_category_labels:
        scope_clauses.append(UserModel.personnel_category.in_(list(scope.allowed_category_labels)))

    if not scope_clauses:
        return query.filter(False)

    combined = scope_clauses[0]
    for clause in scope_clauses[1:]:
        combined = combined | clause
    return query.filter(combined)


def build_evaluation_visibility_payload(user: Any, evaluation: Any) -> dict[str, Any]:
    scope = get_ai_decision_scope_for_user(user)
    allowed = can_view_evaluation(user, evaluation)
    employee = getattr(evaluation, "employee", None)
    return {
        "ok": True,
        "data": {
            "allowed": allowed,
            "message": "Erişim yetkisi uygundur." if allowed else "Bu performans karar destek kaydına erişim yetkiniz bulunmamaktadır.",
            "scope": build_safe_scope_payload(scope),
            "evaluation": {
                "id": getattr(evaluation, "id", None),
                "period_id": getattr(evaluation, "period_id", None),
                "employee_id": getattr(evaluation, "employee_id", None),
                "employee_scope": {
                    "birim": getattr(employee, "birim", None) if employee else None,
                    "ust_birim": getattr(employee, "ust_birim", None) if employee else None,
                    "kategori": getattr(employee, "personnel_category", None) if employee else None,
                },
            },
        },
    }
