"""Cekirdek kullanici ve organizasyon baglamina giris modelleri."""

import secrets

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .base import TimestampMixin, db


class PersonnelCategory(TimestampMixin, db.Model):
    """Performans raporları ve personel kartları için kategori sözlüğü."""

    __tablename__ = "personnel_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True, index=True)
    code = db.Column(db.String(80), nullable=False, unique=True, index=True)
    description = db.Column(db.String(255), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=100, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    users = db.relationship(
        "User",
        back_populates="performance_category",
        lazy="dynamic",
    )

    @property
    def label(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<PersonnelCategory {self.name}>"


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    sicil_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    ad = db.Column(db.String(120), nullable=False)
    soyad = db.Column(db.String(120), nullable=False)
    full_name_cache = db.Column(db.String(255), nullable=True, index=True)
    # BYS360_V55_MIGRATION_COMPAT_FULL_NAME_COLUMN: DB uyumu için gerçek kolon, public property korunur.
    _full_name_compat = db.Column("full_name", db.String(255), nullable=True, index=True)
    profile_photo_path = db.Column(db.String(255), nullable=True)
    profile_photo_updated_at = db.Column(db.DateTime, nullable=True)

    # BYS360_CIC_V4_0_SMART_CELEBRATIONS: KVKK uyumlu kutlama tarihleri.
    birth_date = db.Column(db.Date, nullable=True, index=True)
    hire_date = db.Column(db.Date, nullable=True, index=True)
    celebration_opt_out = db.Column(db.Boolean, nullable=False, default=False, index=True)

    unvan = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(50), nullable=False, default="personel", index=True)
    role_label = db.Column(db.String(100), nullable=True)

    # BYS360_PERSONNEL_CATEGORY_MODEL_FIELD: Toplantı kararları kapsamındaki personel/grup kategorisi.
    personnel_category = db.Column(db.String(80), nullable=True, default="Diğer", index=True)
    performance_category_id = db.Column(
        db.Integer,
        db.ForeignKey("personnel_categories.id"),
        nullable=True,
        index=True,
    )

    birim = db.Column(db.String(255), nullable=True, index=True)
    ust_birim = db.Column(db.String(255), nullable=True, index=True)
    yonetici_sicil = db.Column(db.String(50), nullable=True, index=True)
    ikinci_yonetici_sicil = db.Column(db.String(50), nullable=True, index=True)
    ucuncu_yonetici_sicil = db.Column(db.String(50), nullable=True, index=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    captcha_required = db.Column(db.Boolean, default=False, nullable=False)
    must_change_password = db.Column(db.Boolean, default=True, nullable=False)
    must_set_security_question = db.Column(db.Boolean, default=True, nullable=False)
    security_question = db.Column(db.String(255), nullable=True)
    security_answer_hash = db.Column(db.String(255), nullable=True)
    is_first_login = db.Column(db.Boolean, default=True, nullable=False)

    # BYS360_P13B_SESSION_STAMP: parola sifirlama (forgot-password) baska bir
    # cihazda oturum acik kalan kullaniciyi disariya cikarmiyordu (Phase 13B,
    # confirmed - reset sonrasi eski oturum yetkili sayfalara erismeye devam
    # ediyordu). get_id() bu degeri session cerezine gomer; user_loader ile
    # DB'deki guncel degerle eslesmeyen oturumlar otomatik gecersiz sayilir.
    security_stamp = db.Column(db.String(64), nullable=False, default=lambda: secrets.token_hex(16))

    organization_unit_id = db.Column(
        db.Integer,
        db.ForeignKey("organization_units.id"),
        nullable=True,
        index=True,
    )
    # eski deneme kalintisi: department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))

    # Kurumsal bag: personel -> organizasyon birimi
    organization_unit = db.relationship(
        "OrganizationUnit",
        foreign_keys=[organization_unit_id],
        back_populates="users",
    )

    performance_category = db.relationship(
        "PersonnelCategory",
        foreign_keys=[performance_category_id],
        back_populates="users",
    )

    evaluations_as_employee = db.relationship(
        "PerformanceEvaluation",
        foreign_keys="PerformanceEvaluation.employee_id",
        back_populates="employee",
        lazy="dynamic",
    )
    evaluations_as_level_1 = db.relationship(
        "PerformanceEvaluation",
        foreign_keys="PerformanceEvaluation.level_1_evaluator_id",
        back_populates="level_1_evaluator",
        lazy="dynamic",
    )
    evaluations_as_level_2 = db.relationship(
        "PerformanceEvaluation",
        foreign_keys="PerformanceEvaluation.level_2_evaluator_id",
        back_populates="level_2_evaluator",
        lazy="dynamic",
    )
    evaluations_as_level_3 = db.relationship(
        "PerformanceEvaluation",
        foreign_keys="PerformanceEvaluation.level_3_evaluator_id",
        back_populates="level_3_evaluator",
        lazy="dynamic",
    )

    evaluation_assignments = db.relationship(
        "EvaluationAssignment",
        foreign_keys="EvaluationAssignment.evaluator_id",
        back_populates="evaluator",
        lazy="dynamic",
    )
    assigned_for_employee = db.relationship(
        "EvaluationAssignment",
        foreign_keys="EvaluationAssignment.employee_id",
        back_populates="employee",
        lazy="dynamic",
    )

    org_assignment_history = db.relationship(
        "EmployeeOrgAssignmentHistory",
        foreign_keys="EmployeeOrgAssignmentHistory.employee_id",
        back_populates="employee",
        lazy="dynamic",
    )

    snapshots_as_employee = db.relationship(
        "PerformanceResultSnapshot",
        foreign_keys="PerformanceResultSnapshot.employee_id",
        back_populates="employee",
        lazy="dynamic",
    )

    snapshots_published = db.relationship(
        "PerformanceResultSnapshot",
        foreign_keys="PerformanceResultSnapshot.published_by_user_id",
        back_populates="published_by",
        lazy="dynamic",
    )

    import_batches_created = db.relationship(
        "PerformanceImportBatch",
        foreign_keys="PerformanceImportBatch.created_by_user_id",
        back_populates="created_by",
        lazy="dynamic",
    )
    created_message_threads = db.relationship(
        "MessageThread",
        foreign_keys="MessageThread.created_by_user_id",
        back_populates="created_by",
        lazy="dynamic",
    )
    coverage_logs_created = db.relationship(
        "AssignmentCoverageLog",
        foreign_keys="AssignmentCoverageLog.created_by_user_id",
        back_populates="created_by",
        lazy="dynamic",
    )

    sent_messages = db.relationship(
        "Message",
        foreign_keys="Message.sender_user_id",
        back_populates="sender",
        lazy="dynamic",
        overlaps="sender",
    )

    notifications = db.relationship(
        "Notification",
        foreign_keys="Notification.user_id",
        back_populates="user",
        lazy="dynamic",
        overlaps="user",
    )

    created_surveys = db.relationship(
        "Survey",
        foreign_keys="Survey.created_by_user_id",
        back_populates="created_by",
        lazy="dynamic",
        overlaps="created_by",
    )

    survey_responses = db.relationship(
        "SurveyResponse",
        foreign_keys="SurveyResponse.user_id",
        back_populates="user",
        lazy="dynamic",
        overlaps="user",
    )

    leave_balances = db.relationship(
        "LeaveBalance",
        foreign_keys="LeaveBalance.user_id",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    leave_requests = db.relationship(
        "PersonnelLeave",
        foreign_keys="PersonnelLeave.user_id",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    approved_leave_requests = db.relationship(
        "PersonnelLeave",
        foreign_keys="PersonnelLeave.approved_by_id",
        lazy="dynamic",
    )
    attendance_exceptions = db.relationship(
        "AttendanceException",
        foreign_keys="AttendanceException.user_id",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    approved_attendance_exceptions = db.relationship(
        "AttendanceException",
        foreign_keys="AttendanceException.approved_by_id",
        lazy="dynamic",
    )
    delegations_given = db.relationship(
        "DelegationAssignment",
        foreign_keys="DelegationAssignment.delegator_user_id",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    delegations_received = db.relationship(
        "DelegationAssignment",
        foreign_keys="DelegationAssignment.delegate_user_id",
        lazy="dynamic",
    )
    approved_delegations = db.relationship(
        "DelegationAssignment",
        foreign_keys="DelegationAssignment.approved_by_id",
        lazy="dynamic",
    )


    @property
    def full_name(self):
        cached = (self.full_name_cache or "").strip()
        if cached:
            return cached
        compat = (self._full_name_compat or "").strip()
        if compat:
            return compat
        return f"{self.ad or ''} {self.soyad or ''}".strip()

    def set_password(self, raw_password: str):
        self.password_hash = generate_password_hash(raw_password or "")

    def check_password(self, raw_password: str) -> bool:
        try:
            return check_password_hash(self.password_hash or "", raw_password or "")
        except (ValueError, TypeError):
            return False

    def set_security_answer(self, answer: str):
        self.security_answer_hash = generate_password_hash((answer or "").strip().lower())

    def check_security_answer(self, answer: str) -> bool:
        try:
            return check_password_hash(
                self.security_answer_hash or "",
                (answer or "").strip().lower(),
            )
        except (ValueError, TypeError):
            return False

    def rotate_security_stamp(self) -> None:
        """Parola sifirlama/degistirme sonrasi diger tum oturumlari gecersiz kilar."""
        self.security_stamp = secrets.token_hex(16)

    def get_id(self):
        # BYS360_P13B_SESSION_STAMP: Flask-Login varsayilani yalnizca id
        # dondururdu; stamp'i cerezin icine gomerek DB'deki guncel degerle
        # eslesmeyen (ör. parola sifirlanmis) oturumlarin user_loader
        # tarafindan reddedilmesini saglar.
        return f"{self.id}:{self.security_stamp}"

    def __repr__(self):
        role_name = (self.role_label or self.role or "-").strip()
        unit_name = (self.birim or self.ust_birim or "birimsiz").strip()
        return f"<User sicil={self.sicil_no} name={self.full_name} role={role_name} unit={unit_name}>"
    @property
    def has_profile_photo(self) -> bool:
        return bool((self.profile_photo_path or "").strip())

    @property
    def profile_photo_url(self) -> str:
        # BYS360_PORTAL_PROFILE_PHOTO_FIX_V2_17_73
        # Profil fotoğrafı farklı yükleme yardımcılarından gelebilir.
        # Portal, üst bar ve personel kartlarında kırık görsel oluşmaması için
        # legacy ve yeni yollar tek merkezden güvenli biçimde normalize edilir.
        from pathlib import Path

        from flask import current_app, url_for

        default_avatar = url_for("static", filename="img/default-avatar.svg")
        raw = (self.profile_photo_path or "").strip().replace("\\", "/")
        if not raw:
            return default_avatar

        lowered = raw.lower()
        if lowered.startswith(("http://", "https://", "data:")):
            return raw

        raw = raw.lstrip("/")
        if raw.startswith("static/"):
            raw = raw[len("static/"):]

        version = ""
        try:
            if self.profile_photo_updated_at:
                version = str(int(self.profile_photo_updated_at.timestamp()))
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/models/core_models.py:327")
            version = ""

        def _url(endpoint: str, **values) -> str:
            if version:
                values["v"] = version
            return url_for(endpoint, **values)

        def _static_exists(relative_name: str) -> bool:
            try:
                return (Path(current_app.root_path) / "static" / relative_name).is_file()
            except Exception:
                __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/models/core_models.py:338")
                return False

        # B2-F06: yüklenen fotoğraflar /static yerine oturum isteyen route'tan sunulur;
        # route özel depoyu ve eski static konumunu sırayla okur.
        if raw.startswith(("uploads/", "profile_photos/")):
            return _url("main.bys360_profile_photo_file", filename=Path(raw).name)

        if _static_exists(raw):
            return _url("static", filename=raw)

        return default_avatar


class UserMenuPermission(TimestampMixin, db.Model):
    __tablename__ = "user_menu_permissions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    menu_key = db.Column(db.String(100), nullable=False, index=True)
    is_visible = db.Column(db.Boolean, default=True, nullable=False)
    source_type = db.Column(db.String(30), nullable=False, default="user_override")

    user = db.relationship(
        "User",
        backref=db.backref("menu_permissions", lazy="dynamic", cascade="all, delete-orphan"),
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "menu_key", name="uq_user_menu_permission_user_menu"),
    )

    def __repr__(self):
        return f"<UserMenuPermission user_id={self.user_id} key={self.menu_key} visible={self.is_visible} source={self.source_type}>"
