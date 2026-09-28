"""BYS360 Performans Süreç Akışı Motoru veri modelleri.

Faz 2 yalnızca veri modeli altyapısını tanımlar. Bu dosya mevcut akışa
otomatik bağlanmaz; sonraki fazlarda servis ve ekranlar bu modelleri kullanır.
"""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class PerformanceProcessFlow(db.Model):
    """Bir personelin bir dönem değerlendirmesine ait ana süreç kaydı."""

    __tablename__ = "performance_process_flows"

    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    period_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, nullable=True, index=True)
    current_owner_id = db.Column(db.Integer, nullable=True, index=True)
    current_owner_label = db.Column(db.String(255), nullable=True)
    current_step_key = db.Column(db.String(80), nullable=False, default="created")
    current_status = db.Column(db.String(80), nullable=False, default="created", index=True)
    final_score = db.Column(db.Numeric(6, 2), nullable=True)
    is_low_score = db.Column(db.Boolean, nullable=False, default=False, index=True)
    president_approval_required = db.Column(db.Boolean, nullable=False, default=False, index=True)
    president_approval_status = db.Column(db.String(50), nullable=False, default="not_required", index=True)
    is_finalized = db.Column(db.Boolean, nullable=False, default=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_action_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    rule_version = db.Column(db.String(120), nullable=False, default="phase2_process_engine_v1")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    steps = db.relationship("PerformanceProcessFlowStep", backref="flow", lazy="dynamic")


class PerformanceProcessFlowStep(db.Model):
    """Süreç akışındaki tek bir işlem/adım kaydı."""

    __tablename__ = "performance_process_flow_steps"

    id = db.Column(db.Integer, primary_key=True)
    flow_id = db.Column(db.Integer, db.ForeignKey("performance_process_flows.id"), nullable=False, index=True)
    evaluation_id = db.Column(db.Integer, nullable=False, index=True)
    step_order = db.Column(db.Integer, nullable=False, default=0)
    step_key = db.Column(db.String(80), nullable=False, index=True)
    step_title = db.Column(db.String(255), nullable=False)
    step_status = db.Column(db.String(80), nullable=False, default="created", index=True)
    actor_id = db.Column(db.Integer, nullable=True, index=True)
    actor_label = db.Column(db.String(255), nullable=True)
    owner_id = db.Column(db.Integer, nullable=True, index=True)
    owner_label = db.Column(db.String(255), nullable=True)
    action_summary = db.Column(db.String(500), nullable=True)
    action_note = db.Column(db.Text, nullable=True)
    score_snapshot = db.Column(db.Numeric(6, 2), nullable=True)
    occurred_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    rule_version = db.Column(db.String(120), nullable=False, default="phase2_process_engine_v1")


class PerformanceScoringHistory(db.Model):
    """Her puanlama işlemine ait tarihçe kaydı."""

    __tablename__ = "performance_scoring_history"

    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, nullable=False, index=True)
    period_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, nullable=True, index=True)
    scorer_id = db.Column(db.Integer, nullable=True, index=True)
    scorer_label = db.Column(db.String(255), nullable=True)
    scorer_level = db.Column(db.String(50), nullable=True, index=True)
    raw_score = db.Column(db.Numeric(8, 3), nullable=True)
    score_100 = db.Column(db.Numeric(6, 2), nullable=True)
    general_comment = db.Column(db.Text, nullable=True)
    action_key = db.Column(db.String(80), nullable=False, default="score_saved")
    next_owner_id = db.Column(db.Integer, nullable=True, index=True)
    next_owner_label = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    rule_version = db.Column(db.String(120), nullable=False, default="phase2_process_engine_v1")


class PerformancePresidentApproval(db.Model):
    """70 altı nihai sonuçlar için Başkan onayı kaydı."""

    __tablename__ = "performance_president_approvals"

    id = db.Column(db.Integer, primary_key=True)
    flow_id = db.Column(db.Integer, db.ForeignKey("performance_process_flows.id"), nullable=True, index=True)
    evaluation_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    period_id = db.Column(db.Integer, nullable=True, index=True)
    employee_id = db.Column(db.Integer, nullable=True, index=True)
    final_score = db.Column(db.Numeric(6, 2), nullable=True)
    status = db.Column(db.String(50), nullable=False, default="pending", index=True)
    president_user_id = db.Column(db.Integer, nullable=True, index=True)
    requested_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)
    decision_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    # No rule_version column: this table's schema is owned by migration
    # 6f2b8c4d1a90 (the approval version marker there is process_version), and
    # the verified production table has no rule_version either. Mapping it made
    # every ORM read of this entity fail on both schemas.


class PerformanceProcessNotification(db.Model):
    """Performans süreç motorunun üreteceği bildirim köprü kaydı."""

    __tablename__ = "performance_process_notifications"

    id = db.Column(db.Integer, primary_key=True)
    flow_id = db.Column(db.Integer, db.ForeignKey("performance_process_flows.id"), nullable=True, index=True)
    evaluation_id = db.Column(db.Integer, nullable=True, index=True)
    recipient_id = db.Column(db.Integer, nullable=False, index=True)
    notification_type = db.Column(db.String(80), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=True)
    target_url = db.Column(db.String(500), nullable=True)
    delivery_status = db.Column(db.String(50), nullable=False, default="pending", index=True)
    source_event_key = db.Column(db.String(120), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    read_at = db.Column(db.DateTime, nullable=True)
    rule_version = db.Column(db.String(120), nullable=False, default="phase2_process_engine_v1")

    # Faz 5 uyum sutunlari: eskiden calisma zamaninda ALTER TABLE ile eklenirdi,
    # artik Alembic tarafindan sahiplenilir (bkz. migrations/versions/f5e19f9107d7_*.py).
    recipient_user_id = db.Column(db.Integer, nullable=True)
    recipient_name = db.Column(db.String(255), nullable=True)
    notification_status = db.Column(db.String(80), nullable=True, default="bekliyor")
    priority = db.Column(db.String(40), nullable=True, default="normal")
    action_url = db.Column(db.String(500), nullable=True)
    source_table = db.Column(db.String(120), nullable=True)
    source_id = db.Column(db.Integer, nullable=True)
    flow_status_snapshot = db.Column(db.String(120), nullable=True)
    actor_user_id = db.Column(db.Integer, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    process_version = db.Column(db.String(120), nullable=True)
    app_notification_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)


class PerformanceFeedbackPipelineFlow(db.Model):
    """Geri bildirim görüşme hattının P0 -> Final ana süreç kaydı."""

    __tablename__ = "performance_feedback_pipeline_flows"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False, default="Geri Bildirim Süreç Hattı")
    employee_id = db.Column(db.Integer, nullable=True, index=True)
    period_id = db.Column(db.Integer, nullable=True, index=True)
    current_step_key = db.Column(db.String(80), nullable=False, default="aftercare", index=True)
    current_status = db.Column(db.String(80), nullable=False, default="in_progress", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_by_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    rule_version = db.Column(db.String(120), nullable=False, default="feedback_state_machine_v1")

    feedback_steps = db.relationship("PerformanceFeedbackPipelineStep", backref="feedback_flow", lazy="dynamic")


class PerformanceFeedbackPipelineStep(db.Model):
    """Geri bildirim süreç hattındaki tek bir adımın durum kaydı."""

    __tablename__ = "performance_feedback_pipeline_steps"

    id = db.Column(db.Integer, primary_key=True)
    flow_id = db.Column(db.Integer, db.ForeignKey("performance_feedback_pipeline_flows.id"), nullable=False, index=True)
    step_key = db.Column(db.String(80), nullable=False, index=True)
    step_order = db.Column(db.Integer, nullable=False, default=0)
    step_title = db.Column(db.String(255), nullable=False)
    phase_label = db.Column(db.String(40), nullable=False)
    step_status = db.Column(db.String(80), nullable=False, default="not_started", index=True)
    actor_id = db.Column(db.Integer, nullable=True, index=True)
    action_note = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    rule_version = db.Column(db.String(120), nullable=False, default="feedback_state_machine_v1")
