from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from sqlalchemy import func, or_

from app.extensions import db
from app.models import User
from app.models.performance_archive_models import PerformanceArchivedResult

"""BYS360 Faz 7.5 — Geçmiş Karne Arşivi yönetici görünürlüğü servisleri.

Tek merkez sözleşmesi:
- Manuel giriş ve Excel import aynı ``performance_archived_results`` tablosuna yazar.
- Excel import canlı değerlendirme sonuçlarını değiştirmez.
- Personel yalnızca kendi geçmiş karne arşivini görür.
- Yönetici yalnızca ``phase3_allowed_employee_ids`` ile hesaplanan yetki kapsamındaki geçmişi görür.
- Başkan/Admin ve yetkili performans/personel yönetimi rolleri genel arşiv yönetimi alır.
"""

logger = logging.getLogger(__name__)

# BYS360_PHASE7_4_PERFORMANCE_ARCHIVE_PERSONNEL_VISIBILITY_SERVICE
# BYS360_PHASE7_5_PERFORMANCE_ARCHIVE_MANAGER_VISIBILITY_SERVICE

try:
    from app.services.performance.phase3_backend_route_guard import phase3_allowed_employee_ids
except Exception:  # pragma: no cover - overlay sırası bozulursa güvenli dar kapsam.
    logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
    def phase3_allowed_employee_ids(user: Any) -> set[int]:
        user_id = getattr(user, "id", None)
        try:
            return {int(user_id)} if user_id is not None else set()
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            return set()


# B1-F1 (approved least-privilege policy, 2026-10-09): performans_yetkilisi,
# personel_yonetimi and ik (with their spellings) no longer manage or view the whole
# archive by role name; without another scope they see only their own history.
MANUAL_ENTRY_ROLES = {
    "admin",
    "super_admin",
    "system_admin",
    "sistem_yoneticisi",
    "sistem_yöneticisi",
    "baskan",
    "başkan",
    "baskan_yardimcisi",
    "başkan_yardımcısı",
}

GENERAL_VIEW_ROLES = MANUAL_ENTRY_ROLES | {
    "grup_baskani",
    "grup_başkanı",
    "mali_musavir",
    "mali_müşavir",
    "koordinator",
    "koordinatör",
    "birim_sorumlusu",
}

# Faz 7.5 yönetici görünürlüğü sözleşmesi:
# Bu roller geçmiş karne arşivinde yalnızca phase3_allowed_employee_ids ile
# hesaplanan kendi yetki kapsamlarını görür. Boş kapsam herkese açılmaz.
MANAGER_ARCHIVE_ROLES = {
    "grup_baskani",
    "grup_başkanı",
    "mali_musavir",
    "mali_müşavir",
    "koordinator",
    "koordinatör",
    "birim_sorumlusu",
    "birim_yoneticisi",
    "birim_yöneticisi",
    "yonetici",
    "yönetici",
    "amir",
}

# Faz 7.4 kesin personel görünürlüğü sözleşmesi:
# Standart personel ve rolü belirsiz dar kullanıcı yalnızca kendi geçmiş karne arşivini görür.
# Bu liste bilinçli olarak yönetici/performans yetkilisi rollerini içermez.
PERSONNEL_ONLY_ROLES = {
    "personel",
    "standart",
    "standart_kullanici",
    "standart_kullanıcı",
    "kullanici",
    "kullanıcı",
    "user",
    "employee",
    "calisan",
    "çalışan",
}

HEADER_ALIASES = {
    "sicil_no": {"sicil", "sicil no", "sicil_no", "sicil numarası", "sicil numarasi", "personel sicil", "personel sicil no"},
    "employee_id": {"personel id", "personel_id", "employee_id", "user_id", "kullanıcı id", "kullanici id"},
    "personel": {"personel", "ad soyad", "ad_soyad", "isim", "personel adı", "personel adi", "adı soyadı", "adi soyadi"},
    "result_year": {"yıl", "yil", "year", "sonuç yılı", "sonuc yili", "performans yılı", "performans yili"},
    "period_label": {"dönem", "donem", "period", "period_label", "dönem adı", "donem adi", "karne dönemi"},
    "score": {"puan", "score", "not", "sonuç", "sonuc", "performans puanı", "performans puani", "başarı puanı", "basari puani"},
    "description": {"açıklama", "aciklama", "description", "not açıklaması", "not aciklamasi", "görüş", "gorus", "kanaat"},
    "source_document": {"kaynak belge", "kaynak", "source", "source_document", "belge", "dosya", "cetvel", "kaynak dosya"},
}

TEMPLATE_HEADERS = [
    "Sicil No",
    "Personel ID",
    "Personel",
    "Yıl",
    "Dönem",
    "Puan",
    "Açıklama",
    "Kaynak Belge",
]


def normalize_role(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def normalize_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    # Türkçe karakterleri başlık eşleşmesinde sadeleştir.
    return (
        text.replace("İ", "i")
        .replace("I", "i")
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def canonical_header(value: Any) -> str | None:
    value_norm = normalize_header(value)
    for canonical, aliases in HEADER_ALIASES.items():
        if value_norm in {normalize_header(item) for item in aliases}:
            return canonical
    return None


def display_name(user: Any) -> str:
    if not user:
        return "-"
    value = getattr(user, "full_name", None) or getattr(user, "full_name_cache", None)
    if value:
        return str(value)
    ad = str(getattr(user, "ad", "") or "").strip()
    soyad = str(getattr(user, "soyad", "") or "").strip()
    return f"{ad} {soyad}".strip() or str(getattr(user, "email", "") or "-")


def can_manage_archive(user: Any) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_superuser", False)):
        return True
    return normalize_role(getattr(user, "role", "")) in MANUAL_ENTRY_ROLES


def can_open_archive(user: Any) -> bool:
    return bool(user and getattr(user, "is_authenticated", False))


def is_general_archive_role(user: Any) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_superuser", False)):
        return True
    return normalize_role(getattr(user, "role", "")) in GENERAL_VIEW_ROLES


def user_id_or_none(user: Any) -> int | None:
    try:
        user_id = int(getattr(user, "id", 0) or 0)
        return user_id if user_id > 0 else None
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return None


def is_personnel_only_archive_user(user: Any) -> bool:
    """Faz 7.4 personel görünürlüğü ana kapısı.

    Standart personel, rolü boş/belirsiz kullanıcı veya yönetici/yetkili rolü taşımayan
    kullanıcı yalnızca kendi geçmiş karne arşivini görebilir. Bu fonksiyonun amacı,
    personelin yanlışlıkla ``phase3_allowed_employee_ids`` üzerinden başka kişilere
    genişlemesini engellemektir.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_superuser", False)):
        return False
    role = normalize_role(getattr(user, "role", ""))
    if role in PERSONNEL_ONLY_ROLES:
        return True
    # Bilinmeyen veya boş rol güvenli tarafta kalır: yalnızca kendi geçmişi.
    return role not in GENERAL_VIEW_ROLES


def is_manager_archive_user(user: Any) -> bool:
    """Faz 7.5 yönetici görünürlüğü ana kapısı.

    Grup Başkanı, Koordinatör, Birim Sorumlusu gibi yönetici rolleri arşivde
    genel listeye açılmaz; yalnızca merkezi yetki kapsamı filtresiyle gelen
    personellerin geçmiş kayıtlarını görür.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_superuser", False)):
        return False
    if can_manage_archive(user):
        return False
    return normalize_role(getattr(user, "role", "")) in MANAGER_ARCHIVE_ROLES


def manager_archive_allowed_employee_ids(user: Any) -> set[int]:
    """Yöneticinin görebileceği arşiv personel ID kapsamını döndürür.

    Faz 7.5 kesin sözleşmesi:
    - Yönetici kapsamı ``phase3_allowed_employee_ids`` çıktısına bağlıdır.
    - Boş yönetici kapsamı hiçbir zaman tüm personel anlamına gelmez.
    - Kapsam boşsa güvenli daraltma için sadece kendi ID'sine düşülür.
    """
    if not is_manager_archive_user(user):
        return set()

    own_id = user_id_or_none(user)
    try:
        ids = phase3_allowed_employee_ids(user)
        cleaned = {int(v) for v in ids if v is not None and int(v) > 0}
        if cleaned:
            return cleaned
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/archive_service.py")
    return {own_id} if own_id else set()


def archive_visibility_scope(user: Any) -> str:
    if not user or not getattr(user, "is_authenticated", False):
        return "none"
    if can_manage_archive(user):
        return "manage_all"
    if is_personnel_only_archive_user(user):
        return "personnel_own"
    if is_manager_archive_user(user):
        return "manager_scope"
    return "personnel_own"


def archive_visibility_context(user: Any) -> dict[str, str]:
    scope = archive_visibility_scope(user)
    labels = {
        "manage_all": "Genel arşiv görünürlüğü",
        "manager_scope": "Yetki kapsamı görünürlüğü",
        "personnel_own": "Kişisel arşiv görünürlüğü",
        "none": "Görünürlük yok",
    }
    descriptions = {
        "manage_all": "Yetkiniz kapsamında geçmiş karne arşivindeki kayıtları yönetebilir ve görüntüleyebilirsiniz.",
        "manager_scope": "Yalnızca yönetsel yetki kapsamınızdaki geçmiş karne kayıtları gösterilir.",
        "personnel_own": "Bu ekranda yalnızca kendi geçmiş karne ve puan arşiviniz gösterilir.",
        "none": "Bu ekranda görüntüleyebileceğiniz geçmiş karne kaydı bulunmamaktadır.",
    }
    return {"scope": scope, "label": labels.get(scope, labels["none"]), "description": descriptions.get(scope, descriptions["none"])}


def allowed_archive_employee_ids(user: Any) -> set[int]:
    """Arşiv görünürlüğünü rol/yetki kapsamına göre daraltır.

    Faz 7.5 kesin sözleşmesi:
    - Başkan/Admin ve yetkili yönetim rolleri genel arşiv yönetimi alır.
    - Personel yalnızca kendi geçmişini görür.
    - Yönetici yalnızca kendi yetki kapsamındaki geçmişi görür.
    - Boş set hiçbir zaman "herkes" anlamına gelmez.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return set()

    if can_manage_archive(user):
        try:
            return {int(row[0]) for row in User.query.with_entities(User.id).all() if row[0] is not None}
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            return set()

    own_id = user_id_or_none(user)

    if is_personnel_only_archive_user(user):
        return {own_id} if own_id else set()

    if is_manager_archive_user(user):
        return manager_archive_allowed_employee_ids(user)

    # Bilinmeyen roller güvenli tarafta kalır: yalnızca kendi geçmişi.
    return {own_id} if own_id else set()


def apply_archive_visibility_filter(query, user: Any):
    allowed_ids = allowed_archive_employee_ids(user)
    if not allowed_ids:
        return query.filter(PerformanceArchivedResult.employee_id == -1)
    return query.filter(PerformanceArchivedResult.employee_id.in_(allowed_ids))


def can_view_archived_result(user: Any, result: PerformanceArchivedResult | None) -> bool:
    if not result:
        return False
    try:
        return int(result.employee_id) in allowed_archive_employee_ids(user)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def parse_year(value: Any) -> int:
    try:
        year = int(str(value or "").strip())
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        raise ValueError("Yıl alanı geçerli bir sayı olmalıdır.") from exc
    if year < 2000 or year > 2100:
        raise ValueError("Yıl 2000 ile 2100 arasında olmalıdır.")
    return year


def parse_score(value: Any) -> Decimal:
    try:
        score = Decimal(str(value or "").replace(",", ".").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Puan alanı geçerli bir sayı olmalıdır.") from exc
    if score < Decimal("0") or score > Decimal("100"):
        raise ValueError("Puan 0 ile 100 arasında olmalıdır.")
    return score


def _user_column(name: str):
    return getattr(User, name, None)


def resolve_employee(*, employee_id: Any = None, sicil_no: Any = None, personel: Any = None) -> User | None:
    if employee_id not in (None, ""):
        try:
            found = db.session.get(User, int(employee_id))
            if found:
                return found
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/performance/archive_service.py")
    sicil = str(sicil_no or "").strip()
    sicil_col = _user_column("sicil_no")
    if sicil and sicil_col is not None:
        found = User.query.filter(sicil_col == sicil).first()
        if found:
            return found

    name = str(personel or "").strip()
    if name:
        like = f"%{name}%"
        filters = []
        for col_name in ["full_name_cache", "ad", "soyad", "email"]:
            col = _user_column(col_name)
            if col is not None:
                filters.append(col.ilike(like))
        if filters:
            found = User.query.filter(or_(*filters)).first()
            if found:
                return found
    return None


def archive_duplicate_exists(*, employee_id: int, result_year: Any, period_label: Any) -> bool:
    year = parse_year(result_year)
    period = str(period_label or "").strip()
    if not period:
        return False
    return db.session.query(PerformanceArchivedResult.id).filter(
        PerformanceArchivedResult.employee_id == int(employee_id),
        PerformanceArchivedResult.result_year == year,
        func.lower(PerformanceArchivedResult.period_label) == period.lower(),
    ).first() is not None


def create_archive_result(
    *,
    actor: Any,
    employee: User,
    result_year: Any,
    period_label: Any,
    score: Any,
    description: Any = None,
    source_document: Any = None,
    source_document_name: Any = None,
    source_type: str = "manual",
    commit: bool = False,
) -> PerformanceArchivedResult:
    period = str(period_label or "").strip()
    if not period:
        raise ValueError("Dönem alanı zorunludur.")

    source_text = str(source_document or "").strip() or None
    source_name = str(source_document_name or "").strip() or source_text
    result = PerformanceArchivedResult(
        employee_id=employee.id,
        result_year=parse_year(result_year),
        period_label=period[:120],
        score=parse_score(score),
        description=str(description or "").strip() or None,
        source_document=source_text,
        source_document_name=source_name,
        source_type=(source_type or "manual")[:40],
        created_by_user_id=getattr(actor, "id", None),
    )
    db.session.add(result)
    if commit:
        db.session.commit()
    return result


def create_manual_archive_result(
    *,
    actor: Any,
    employee_id: Any,
    result_year: Any,
    period_label: Any,
    score: Any,
    description: Any = None,
    source_document: Any = None,
    source_document_name: Any = None,
) -> PerformanceArchivedResult:
    if not can_manage_archive(actor):
        raise PermissionError("Geçmiş karne arşivine manuel kayıt ekleme yetkiniz bulunmamaktadır.")

    employee = resolve_employee(employee_id=employee_id)
    if not employee:
        raise ValueError("Personel bulunamadı.")

    if archive_duplicate_exists(employee_id=employee.id, result_year=result_year, period_label=period_label):
        raise ValueError("Bu personel, yıl ve dönem için arşiv kaydı zaten var.")

    result = create_archive_result(
        actor=actor,
        employee=employee,
        result_year=result_year,
        period_label=period_label,
        score=score,
        description=description,
        source_document=source_document,
        source_document_name=source_document_name,
        source_type="manual",
        commit=True,
    )
    return result


def _load_workbook_from_storage(file_storage: Any):
    try:
        from openpyxl import load_workbook
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        raise RuntimeError("Excel aktarımı için openpyxl paketi gereklidir.") from exc

    raw = file_storage.read()
    if not raw:
        raise ValueError("Excel dosyası boş görünüyor.")
    return load_workbook(BytesIO(raw), data_only=True)


def validate_archive_excel_schema(header_row: Any) -> dict[str, Any]:
    """Geçmiş karne Excel başlıklarını import başlamadan önce doğrular."""
    if not header_row:
        return {"ok": False, "mapping": {}, "errors": ["Excel dosyasında başlık satırı bulunamadı."], "warnings": []}
    mapping: dict[int, str] = {}
    seen: dict[str, int] = {}
    unknown: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    for idx, header in enumerate(header_row):
        raw = str(header or "").strip()
        if not raw:
            continue
        canonical = canonical_header(raw)
        if canonical:
            if canonical in seen:
                errors.append(f"Tekrarlanan Excel başlığı: {raw}")
            seen[canonical] = idx
            mapping[idx] = canonical
        else:
            unknown.append(raw)
    required = {"result_year", "period_label", "score"}
    missing = required - set(mapping.values())
    if missing:
        readable = {"result_year": "Yıl", "period_label": "Dönem", "score": "Puan"}
        errors.append("Excel başlıkları eksik: " + ", ".join(readable.get(m, "Bilinmiyor") for m in sorted(missing)))
    if not ({"sicil_no", "employee_id", "personel"} & set(mapping.values())):
        errors.append("Personel eşleştirmesi için Sicil No, Personel ID veya Personel başlığı gereklidir.")
    if unknown:
        warnings.append("Tanımsız Excel başlıkları yok sayıldı: " + ", ".join(unknown[:8]))
    return {"ok": not errors, "mapping": mapping, "errors": errors, "warnings": warnings, "unknown_headers": unknown}


def import_archive_results_from_excel(file_storage: Any, *, actor: Any, duplicate_policy: str = "skip") -> dict[str, Any]:
    """Excel'den geçmiş karne kayıtlarını yeni arşiv tablosuna alır.

    Desteklenen başlıklar esnektir: Sicil No, Personel ID, Personel, Yıl,
    Dönem, Puan, Açıklama, Kaynak Belge. Personel eşleştirmesinde Sicil No
    ve Personel ID önceliklidir. Aynı personel + yıl + dönem tekrarı varsayılan
    olarak atlanır.
    """
    if not can_manage_archive(actor):
        raise PermissionError("Geçmiş karne arşivine Excel yükleme yetkiniz bulunmamaktadır.")

    filename = str(getattr(file_storage, "filename", "") or "gecmis_karne.xlsx")
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Yalnızca .xlsx formatındaki Excel dosyaları desteklenir.")

    workbook = _load_workbook_from_storage(file_storage)
    sheet = workbook.active
    header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if not header_row:
        raise ValueError("Excel dosyasında başlık satırı bulunamadı.")

    schema = validate_archive_excel_schema(header_row)
    if not schema.get("ok"):
        raise ValueError("; ".join(schema.get("errors") or ["Excel başlık yapısı doğrulanamadı."]))
    mapping: dict[int, str] = schema["mapping"]
    schema_warnings = schema.get("warnings") or []

    created = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    preview: list[dict[str, Any]] = []

    for excel_row_no, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not values or not any(value is not None and str(value).strip() for value in values):
            continue
        row_data = {name: values[idx] if idx < len(values) else None for idx, name in mapping.items()}
        try:
            employee = resolve_employee(
                employee_id=row_data.get("employee_id"),
                sicil_no=row_data.get("sicil_no"),
                personel=row_data.get("personel"),
            )
            if not employee:
                raise ValueError("Personel bulunamadı")

            if archive_duplicate_exists(
                employee_id=employee.id,
                result_year=row_data.get("result_year"),
                period_label=row_data.get("period_label"),
            ):
                skipped += 1
                errors.append({"row": excel_row_no, "message": "Aynı personel, yıl ve dönem için arşiv kaydı zaten var."})
                continue

            result = create_archive_result(
                actor=actor,
                employee=employee,
                result_year=row_data.get("result_year"),
                period_label=row_data.get("period_label"),
                score=row_data.get("score"),
                description=row_data.get("description"),
                source_document=row_data.get("source_document") or filename,
                source_document_name=row_data.get("source_document") or filename,
                source_type="excel",
                commit=False,
            )
            db.session.flush()
            created += 1
            if len(preview) < 20:
                preview.append({
                    "row": excel_row_no,
                    "personel": display_name(employee),
                    "yil": result.result_year,
                    "donem": result.period_label,
                    "puan": float(result.score or 0),
                })
        except Exception as exc:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            skipped += 1
            errors.append({"row": excel_row_no, "message": str(exc)})

    db.session.commit()
    return {
        "created": created,
        "skipped": skipped,
        "errors": errors[:100],
        "preview": preview,
        "filename": filename,
        "schema_warnings": schema_warnings,
    }


def build_archive_excel_template_bytes() -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except Exception as exc:  # pragma: no cover
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        raise RuntimeError("Excel şablonu için openpyxl paketi gereklidir.") from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Gecmis Karne Arsivi"
    ws.append(TEMPLATE_HEADERS)
    ws.append(["12345", "", "Ad Soyad", 2024, "2024 Yıllık", 87.50, "Eski cetvelden aktarıldı.", "2024 performans cetveli"])

    header_fill = PatternFill("solid", fgColor="8B0000")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
    widths = [16, 14, 28, 12, 22, 12, 42, 32]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def build_archive_query_for_user(user: Any):
    query = PerformanceArchivedResult.query
    return apply_archive_visibility_filter(query, user)


def apply_archive_search_filters(query, *, q: str = "", year: int | None = None):
    q = (q or "").strip()
    if year:
        query = query.filter(PerformanceArchivedResult.result_year == int(year))
    if q:
        like = f"%{q}%"
        user_filters = []
        for col_name in ["ad", "soyad", "full_name_cache", "sicil_no", "birim", "email"]:
            col = _user_column(col_name)
            if col is not None:
                user_filters.append(col.ilike(like))
        query = query.join(User, User.id == PerformanceArchivedResult.employee_id)
        filters = user_filters + [
            PerformanceArchivedResult.period_label.ilike(like),
            PerformanceArchivedResult.description.ilike(like),
            PerformanceArchivedResult.source_document_name.ilike(like),
        ]
        query = query.filter(or_(*filters))
    return query


def build_archive_summary(rows: list[PerformanceArchivedResult]) -> dict[str, Any]:
    scores = [float(row.score or 0) for row in rows]
    count = len(scores)
    avg = round(sum(scores) / count, 2) if count else 0
    return {
        "count": count,
        "avg_score": avg,
        "low_count": len([s for s in scores if s < 70]),
        "high_count": len([s for s in scores if s >= 90]),
        "manual_count": len([row for row in rows if str(row.source_type or "") == "manual"]),
        "excel_count": len([row for row in rows if str(row.source_type or "") == "excel"]),
    }


def archive_year_options_for_user(user: Any) -> list[int]:
    query = db.session.query(PerformanceArchivedResult.result_year).distinct()
    query = apply_archive_visibility_filter(query, user)
    return [int(row[0]) for row in query.order_by(PerformanceArchivedResult.result_year.desc()).all() if row[0] is not None]


def manual_entry_employee_options(user: Any, limit: int = 1500) -> list[User]:
    if not can_manage_archive(user):
        return []
    return User.query.order_by(User.ad.asc(), User.soyad.asc(), User.sicil_no.asc()).limit(limit).all()
