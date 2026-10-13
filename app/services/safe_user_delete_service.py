"""
BYS360 güvenli kullanıcı/personel silme servisi.

Kalıcı amaç:
- ORM delete ORM ilişkilerini tetiklediği için aktif omurgada olmayan
  eski personnel_* tablolarını lazy-load etmeye çalışabilir.
- Bu servis kullanıcı silmeyi ORM relationship zincirine bırakmaz.
- Veritabanında gerçekten var olan tabloları introspection ile okur.
- Sadece mevcut tablolar üzerinde users.id foreign key bağlantılarını temizler.
- Son olarak users kaydını doğrudan SQL ile siler.

Bu sayede veritabanında olmayan eski modeller/tablo adları personel silme sırasında sorgulanmaz.
"""
from __future__ import annotations

from typing import Any, cast

from sqlalchemy import MetaData, inspect, text

from app import db
from app.models import User


def _q(identifier: str) -> str:
    """PostgreSQL identifier güvenli quote."""
    return '"' + str(identifier).replace('"', '""') + '"'


def _existing_tables_ordered() -> list[str]:
    """
    DB'deki gerçek tabloları bağımlılık sırasına göre döndürür.
    Çocuk tablolar önce temizlensin diye ters sorted_tables kullanılır.
    """
    try:
        metadata = MetaData()
        metadata.reflect(bind=db.engine)
        return [table.name for table in reversed(metadata.sorted_tables)]
    except Exception:
        inspector = inspect(db.engine)
        return list(reversed(inspector.get_table_names()))


def _user_fk_refs() -> list[dict[str, Any]]:
    """
    DB'de gerçekten var olan tablolardan users.id alanına FK veren kolonları bulur.
    Olmayan model tabloları bu listede yer almaz.
    """
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    ordered_tables = _existing_tables_ordered()

    refs: list[dict[str, Any]] = []

    for table_name in ordered_tables:
        if table_name == "users" or table_name not in existing_tables:
            continue

        try:
            columns = {
                col["name"]: col
                for col in inspector.get_columns(table_name)
            }
            fks = inspector.get_foreign_keys(table_name)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/safe_user_delete_service.py:66)")
            continue

        for fk in fks:
            if fk.get("referred_table") != "users":
                continue

            constrained_columns = fk.get("constrained_columns") or []
            referred_columns = fk.get("referred_columns") or []

            if "id" not in referred_columns:
                continue

            for column_name in constrained_columns:
                col_info = cast("dict[str, Any]", columns.get(column_name, {}))
                refs.append(
                    {
                        "table": table_name,
                        "column": column_name,
                        "nullable": bool(col_info.get("nullable", True)),
                    }
                )

    return refs


def safe_delete_user_by_id(
    user_id: int,
    *,
    actor_id: int | None = None,
    allow_admin: bool = False,
    commit: bool = False,
) -> dict[str, Any]:
    """
    Kullanıcı/personel kaydını ORM relationship zincirini tetiklemeden siler.

    Varsayılan olarak admin kullanıcı silinmez.
    commit=False bırakılırsa çağıran route mevcut db.session.commit() akışını korur.
    """
    uid = int(user_id)

    user = db.session.get(User, uid)
    if user is None:
        return {
            "deleted": False,
            "reason": "not_found",
            "user_id": uid,
            "touched": [],
        }

    # R05c / K4: every spelling of the admin role ("Admin", " admin ") is an admin account.
    if str(getattr(user, "role", None) or "").strip().lower() == "admin" and not allow_admin:
        raise ValueError("Admin kullanıcı güvenli silme servisiyle silinemez.")

    touched: list[dict[str, Any]] = []

    try:
        # DB'de var olan FK bağlantılarını temizle.
        # Nullable kolonlarda kayıt geçmişi kalsın diye NULL yapılır.
        # Nullable değilse ilgili bağımlı kayıt silinir.
        for ref in _user_fk_refs():
            table_name = ref["table"]
            column_name = ref["column"]

            if ref["nullable"]:
                sql = text(
                    f"UPDATE {_q(table_name)} "
                    f"SET {_q(column_name)} = NULL "
                    f"WHERE {_q(column_name)} = :uid"
                )
                result = db.session.execute(sql, {"uid": uid})
                action = "null"
            else:
                sql = text(
                    f"DELETE FROM {_q(table_name)} "
                    f"WHERE {_q(column_name)} = :uid"
                )
                result = db.session.execute(sql, {"uid": uid})
                action = "delete"

            rowcount = int(result.rowcount or 0)  # type: ignore[attr-defined]
            if rowcount:
                touched.append(
                    {
                        "table": table_name,
                        "column": column_name,
                        "action": action,
                        "rowcount": rowcount,
                    }
                )

        # En kritik nokta:
        # ORM delete kullanılmaz.
        # Böylece User modelindeki eski/missing relationship'ler lazy-load edilmez.
        result = db.session.execute(
            text('DELETE FROM "users" WHERE "id" = :uid'),
            {"uid": uid},
        )

        deleted = int(result.rowcount or 0)  # type: ignore[attr-defined]

        if commit:
            db.session.commit()
        else:
            db.session.flush()

        return {
            "deleted": bool(deleted),
            "user_id": uid,
            "actor_id": actor_id,
            "touched": touched,
        }

    except Exception:
        db.session.rollback()
        raise
