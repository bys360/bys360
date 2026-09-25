from __future__ import annotations

# BYS360_CANLI_SAGLAMLASTIRMA_FAZ1_6_LOW_SCORE_MODEL
import logging

from app.core.datetime_utils import utc_now

from .base import TimestampMixin, db

logger = logging.getLogger(__name__)
"""BYS360 70 altı performans sonuçları için Başkan onaylı süreç zinciri modelleri.

# BYS360_PHASE6_6_SECOND_LOW_SCORE_PROCESS

# BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN

# BYS360_PHASE6_3_DIRECT_TO_PRESIDENT_APPROVAL

Bu modeller puan kaydından bağımsız bir idari süreç izi tutar. Amaç: 70 altı
sonuçların Başkan onayı ve personel geçmiş/süreç kaydı
oluşmadan kesinleşmesini engellemektir.
"""


class PerformanceLowScoreProcess(TimestampMixin, db.Model):
    # BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V5
    # BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V4
    # BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V3
    # BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_V2 | 70 altı yayın kesinleşmesi Başkan onayı, iade ve süreç kayıt şartlarını dikkate alır.
    # BYS360_PHASE6_6_SECOND_LOW_SCORE_PROCESS_V2 | Yayın kesinleşmesi iade ve Başkan/Üst Onay durumunu dikkate alır.
    __tablename__ = "performance_low_score_processes"

    id = db.Column(db.Integer, primary_key=True)
    period_id = db.Column(db.Integer, db.ForeignKey("performance_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey("performance_evaluations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    calendar_year = db.Column(db.Integer, nullable=False, index=True)
    sequence_no = db.Column(db.Integer, nullable=False, default=1, index=True)
    final_total_100 = db.Column(db.Float, nullable=False, default=0.0)

    process_type = db.Column(db.String(80), nullable=False, default="first_low_score_warning", index=True)
    status = db.Column(db.String(80), nullable=False, default="president_approval_pending", index=True)
    rule_version = db.Column(db.String(120), nullable=False, default="2026-05-02-low-score-president-screen-v1")
    low_score_detected_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)

    current_stage_key = db.Column(db.String(80), nullable=True, index=True)
    current_owner_label = db.Column(db.String(160), nullable=True)

    hr_checked_at = db.Column(db.DateTime, nullable=True)
    hr_checked_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    hr_check_note = db.Column(db.Text, nullable=True)

    president_approved_at = db.Column(db.DateTime, nullable=True)
    president_approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    president_approval_note = db.Column(db.Text, nullable=True)

    # BYS360_PHASE6_4_PRESIDENT_APPROVAL_SCREEN: Başkan/Üst Onay ekranı iade ve süreç notu alanları
    president_rejected_at = db.Column(db.DateTime, nullable=True)
    president_rejected_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    president_rejection_note = db.Column(db.Text, nullable=True)
    process_note = db.Column(db.Text, nullable=True)
    process_note_updated_at = db.Column(db.DateTime, nullable=True)
    process_note_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    warning_recorded_at = db.Column(db.DateTime, nullable=True)
    warning_recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    warning_note = db.Column(db.Text, nullable=True)

    administrative_process_started_at = db.Column(db.DateTime, nullable=True)
    administrative_process_started_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    administrative_process_note = db.Column(db.Text, nullable=True)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    period = db.relationship("PerformancePeriod", foreign_keys=[period_id])
    evaluation = db.relationship("PerformanceEvaluation", foreign_keys=[evaluation_id], backref=db.backref("low_score_process", uselist=False, lazy="joined"))
    employee = db.relationship("User", foreign_keys=[employee_id])
    hr_checked_by = db.relationship("User", foreign_keys=[hr_checked_by_id])
    president_approved_by = db.relationship("User", foreign_keys=[president_approved_by_id])
    president_rejected_by = db.relationship("User", foreign_keys=[president_rejected_by_id])
    process_note_by = db.relationship("User", foreign_keys=[process_note_by_id])
    warning_recorded_by = db.relationship("User", foreign_keys=[warning_recorded_by_id])
    administrative_process_started_by = db.relationship("User", foreign_keys=[administrative_process_started_by_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    updated_by = db.relationship("User", foreign_keys=[updated_by_user_id])

    events = db.relationship(
        "PerformanceLowScoreProcessEvent",
        back_populates="process",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="PerformanceLowScoreProcessEvent.sort_order.asc(), PerformanceLowScoreProcessEvent.id.asc()",
    )

    __table_args__ = (
        db.Index("ix_low_score_process_employee_year", "employee_id", "calendar_year"),
        db.Index("ix_low_score_process_period_status", "period_id", "status"),
    )


    # BYS360_PHASE6_FINAL_POLICY_CONTRACT_V3
    # Başkan/Üst Onay odaklı 70 altı yayın kesinleşme politikası. İK/Admin ara onay kapısı değildir.
    # Aşağıdaki dört property bu politikanın tek yetkili tanımıdır; sınıf dışında
    # property() ile yeniden bağlanmaz.
    # İade edilmiş kayıt kesinleşmez/yayınlanmaz.
    # Başkan/Üst Onay olmadan düşük performans kesinleşmez.
    # İlk 70 altında uyarı kaydı olmadan yayın kesinleşmez.
    # İkinci 70 altında idari süreç başlamadan yayın kesinleşmez.
    @property
    def is_finalized_for_publish(self) -> bool:
        # Yayın kesinleşmesi iade durumunu engelliyor.
        if self.is_president_rejected:
            return False
        # Yayın kesinleşmesi Başkan/Üst Onay şartını dikkate alıyor.
        if not self.is_president_approved:
            return False
        # İkinci 70 altı için idari süreç kaydı kesinleşme şartı.
        if self.is_second_or_later:
            return bool(getattr(self, "administrative_process_started_at", None) or getattr(self, "administrative_process_started_by_id", None))
        # İlk 70 altı için uyarı kaydı kesinleşme şartı.
        return bool(getattr(self, "warning_recorded_at", None) or getattr(self, "warning_recorded_by_id", None))

    @property
    def is_second_or_later(self) -> bool:
        try:
            return int(getattr(self, "sequence_no", 1) or 1) >= 2
        except Exception:
            logger.exception("Performans modulu kritik isleminde hata olustu", exc_info=True)
            return False

    @property
    def is_hr_checked(self) -> bool:
        return bool(self.hr_checked_at)

    @property
    def is_president_approved(self) -> bool:
        return bool(getattr(self, "president_approved_at", None) or getattr(self, "president_approved_by_id", None))

    @property
    def is_president_rejected(self) -> bool:
        return bool(
            getattr(self, "president_rejected_at", None)
            or getattr(self, "president_rejected_by_id", None)
            or getattr(self, "president_rejection_note", None)
        )


class PerformanceLowScoreProcessEvent(TimestampMixin, db.Model):
    __tablename__ = "performance_low_score_process_events"

    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.Integer, db.ForeignKey("performance_low_score_processes.id", ondelete="CASCADE"), nullable=False, index=True)
    step_key = db.Column(db.String(80), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(40), nullable=False, default="pending", index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    note = db.Column(db.Text, nullable=True)

    process = db.relationship("PerformanceLowScoreProcess", back_populates="events")
    actor = db.relationship("User", foreign_keys=[actor_user_id])

    __table_args__ = (
        db.UniqueConstraint("process_id", "step_key", name="uq_low_score_process_step"),
    )

    @property
    @property
    def is_finalized_for_publish(self):
        # Yayın kesinleşmesi Başkan/Üst Onay şartını dikkate alıyor. is_president_approved
        # İlk 70 altı için uyarı kaydı kesinleşme şartı. warning_recorded_at
        # İkinci 70 altı için idari süreç kaydı kesinleşme şartı. administrative_process_started_at
        # BYS360_PHASE6_7_FINAL_GATE_ALIGNMENT_FORCE_POLICY
        # Yayın kesinleşmesi iade durumunu engelliyor.
        if self.is_president_rejected:
            return False
        # Yayın kesinleşmesi Başkan/Üst Onay şartını dikkate alıyor.
        if not self.is_president_approved:
            return False
        # İlk 70 altı için uyarı kaydı kesinleşme şartı.
        if not self.is_second_or_later:
            return bool(getattr(self, "warning_recorded_at", None))
        # İkinci 70 altı için idari süreç kaydı kesinleşme şartı.
        return bool(getattr(self, "administrative_process_started_at", None))
    def __repr__(self):
        return f"<PerformanceLowScoreProcessEvent process={self.process_id} step={self.step_key} status={self.status}>"
