from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from flask import abort, flash, jsonify, redirect, request, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    Notification,
    PortalCommentMention,
    PortalGroup,
    PortalGroupMember,
    PortalModerationLog,
    PortalPost,
    PortalPostAttachment,
    PortalPostComment,
    PortalPostReport,
    PortalProfile,
    User,
)
from app.route_registry import main_bp
from app.route_support import (
    can_access_menu,
    menu_key_required,
    normalize_role_name,
    render_access_denied,
    safe_render,
    sanitize_free_text,
)
from app.security.private_uploads import (
    legacy_static_upload_path,
    locate_upload,
    private_upload_dir,
    private_upload_path,
)
from app.services.bys360_notification_bridge import (
    notify_portal_comment_added,
    notify_portal_post_created,
    notify_portal_reaction,
    notify_portal_report_created,
)
from app.services.instagram_portal_sync import sync_instagram_to_portal
from app.services.portal_experience_service import portal_experience_context
from app.services.portal_experience_v2_service import portal_experience_v2_context
from app.services.portal_permission_matrix import portal_permission_allowed
from app.services.portal_press_news_service import (
    archive_press_news_candidate,
    press_news_home_context,
    press_news_review_context,
    publish_press_news_candidate,
    scan_press_news_candidates,
)
from app.services.portal_service import (
    PORTAL_ALL_ROLES,
    POST_TYPE_OPTIONS,
    REACTION_OPTIONS,
    VISIBILITY_OPTIONS,
    add_audience_entries,
    can_manage_portal,
    can_publish_announcement,
    can_user_delete_post,
    can_user_post_to_wall,
    can_user_view_post,
    display_user_name,
    enrich_posts,
    get_or_create_profile,
    is_group_member,
    list_active_groups_for_user,
    normalize_post_type,
    normalize_visibility,
    reaction_counts,
    toggle_reaction,
    toggle_save,
    user_reaction_for_post,
    user_unit_name,
    user_upper_unit_name,
    visible_posts_for_user,
)

# Compatibility guard.
_PORTAL_PRESS_NEWS_ADMIN_ONLY_ROLES = {"admin", "super_admin", "system_admin", "sistem_yoneticisi"}

def _portal_press_news_admin_only_allowed(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return normalize_role_name(getattr(user, "role", "")) in _PORTAL_PRESS_NEWS_ADMIN_ONLY_ROLES

def _portal_press_news_visible_for_user(user) -> bool:
    return _portal_press_news_admin_only_allowed(user) and can_access_menu(user, "portal_press_news")
# Compatibility guard.

def _slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    text = text.translate(tr_map)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "portal-grubu"

# BYS360_CORPORATE_PORTAL_MEDIA_VIDEO_V2_3_HELPERS
# BYS360_PORTAL_MEDIA_COMMENTS_MENTIONS_V2_12_1_HELPERS
PORTAL_ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
PORTAL_ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PORTAL_ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "m4v"}
PORTAL_ALLOWED_VIDEO_MIMES = {"video/mp4", "video/webm", "video/quicktime", "video/x-m4v"}
PORTAL_MAX_IMAGES_PER_POST = 6
PORTAL_MAX_MEDIA_BYTES = 50 * 1024 * 1024
PORTAL_MAX_VIDEO_FILES_PER_POST = 1


def _portal_upload_dir() -> Path:
    """Yeni portal medyası için yazma klasörü (B2-F06: static dışındaki özel depo)."""
    return private_upload_dir("portal")


def _portal_file_size(file_storage) -> int | None:
    try:
        stream = file_storage.stream
        current = stream.tell()
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(current)
        return int(size)
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/portal/routes.py:125")
        return None


def _portal_media_extension(filename: str) -> str:
    cleaned = secure_filename(filename or "")
    if "." not in cleaned:
        return ""
    return cleaned.rsplit(".", 1)[-1].lower().strip()


def _portal_image_extension(filename: str) -> str:
    return _portal_media_extension(filename)


def _portal_limit_label() -> str:
    return "50 MB"


def _save_portal_images(post: PortalPost, files) -> None:
    saved_count = 0
    total_bytes = 0
    for file_storage in list(files or [])[:PORTAL_MAX_IMAGES_PER_POST]:
        if not file_storage or not getattr(file_storage, "filename", ""):
            continue
        ext = _portal_image_extension(file_storage.filename)
        mime = (getattr(file_storage, "mimetype", "") or "").lower().strip()
        if ext not in PORTAL_ALLOWED_IMAGE_EXTENSIONS or (mime and mime not in PORTAL_ALLOWED_IMAGE_MIMES):
            flash("Yalnızca JPG, PNG, WEBP veya GIF görsel dosyaları yüklenebilir.", "warning")
            continue
        size = _portal_file_size(file_storage)
        if size is not None:
            total_bytes += size
            if size > PORTAL_MAX_MEDIA_BYTES or total_bytes > PORTAL_MAX_MEDIA_BYTES:
                flash(f"Portal paylaşım dosya sınırı {_portal_limit_label()} olduğu için bazı görseller eklenmedi.", "warning")
                continue
        original_name = secure_filename(file_storage.filename) or f"portal_gorsel.{ext}"
        stored_name = f"post_{post.id}_{uuid4().hex}.{ext}"
        stored_path = _portal_upload_dir() / stored_name
        try:
            file_storage.stream.seek(0)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/portal/routes.py:166")
            pass
        file_storage.save(stored_path)
        image_mime = mime or ("image/jpeg" if ext in {"jpg", "jpeg"} else f"image/{ext}")
        db.session.add(PortalPostAttachment(
            post_id=post.id,
            filename=original_name,
            stored_path=f"uploads/portal/{stored_name}",
            mime_type=image_mime,
            size_bytes=size,
            uploaded_by_user_id=current_user.id,
        ))
        saved_count += 1
    if saved_count:
        flash(f"{saved_count} görsel paylaşımınıza eklendi.", "success")


def _save_portal_video_file(post: PortalPost, files) -> None:
    saved_count = 0
    for file_storage in list(files or [])[:PORTAL_MAX_VIDEO_FILES_PER_POST]:
        if not file_storage or not getattr(file_storage, "filename", ""):
            continue
        ext = _portal_media_extension(file_storage.filename)
        mime = (getattr(file_storage, "mimetype", "") or "").lower().strip()
        if ext not in PORTAL_ALLOWED_VIDEO_EXTENSIONS or (mime and mime not in PORTAL_ALLOWED_VIDEO_MIMES):
            flash("Yalnızca MP4, WEBM, MOV veya M4V video dosyası yüklenebilir.", "warning")
            continue
        size = _portal_file_size(file_storage)
        if size is not None and size > PORTAL_MAX_MEDIA_BYTES:
            flash(f"Video dosyası {_portal_limit_label()} sınırını aştığı için eklenmedi.", "warning")
            continue
        original_name = secure_filename(file_storage.filename) or f"portal_video.{ext}"
        stored_name = f"post_{post.id}_{uuid4().hex}.{ext}"
        stored_path = _portal_upload_dir() / stored_name
        try:
            file_storage.stream.seek(0)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/portal/routes.py:202")
            pass
        file_storage.save(stored_path)
        video_mime = mime or ("video/mp4" if ext in {"mp4", "m4v"} else "video/webm")
        if ext == "mov" and not mime:
            video_mime = "video/quicktime"
        db.session.add(PortalPostAttachment(
            post_id=post.id,
            filename=original_name,
            stored_path=f"uploads/portal/{stored_name}",
            mime_type=video_mime,
            size_bytes=size,
            uploaded_by_user_id=current_user.id,
        ))
        saved_count += 1
    if saved_count:
        flash("Video paylaşımınıza eklendi.", "success")


def _host_matches_domain(host: str, domain: str) -> bool:
    """Exact eşleşme veya nokta sınırlı alt alan adı eşleşmesi.

    `str.endswith(domain)` yanlış pozitif üretir: "notyoutube.com" da
    "youtube.com" ile biter ama onun alt alan adı değildir.
    """
    return host == domain or host.endswith(f".{domain}")


def _youtube_video_id(parsed_url) -> str:
    host = (parsed_url.netloc or "").lower().replace("www.", "")
    path = (parsed_url.path or "").strip("/")
    if host == "youtu.be":
        return path.split("/", 1)[0]
    if _host_matches_domain(host, "youtube.com") or _host_matches_domain(host, "youtube-nocookie.com"):
        if path.startswith("embed/"):
            return path.split("/", 1)[1].split("/", 1)[0]
        if path.startswith("shorts/"):
            return path.split("/", 1)[1].split("/", 1)[0]
        query = parse_qs(parsed_url.query or "")
        return (query.get("v") or [""])[0]
    return ""


def _portal_video_embed_url(raw_url: str) -> str:
    raw = sanitize_free_text(raw_url, limit=700)
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = (parsed.netloc or "").lower().replace("www.", "")
    if host == "youtu.be" or _host_matches_domain(host, "youtube.com") or _host_matches_domain(host, "youtube-nocookie.com"):
        video_id = _youtube_video_id(parsed)
        if re.fullmatch(r"[A-Za-z0-9_-]{6,32}", video_id or ""):
            return f"https://www.youtube-nocookie.com/embed/{video_id}"
        return ""
    if _host_matches_domain(host, "vimeo.com"):
        match = re.search(r"/(?:video/)?([0-9]{5,20})", parsed.path or "")
        if match:
            return f"https://player.vimeo.com/video/{match.group(1)}"
    return ""


def _save_portal_video_link(post: PortalPost, raw_url: str | None) -> None:
    raw = sanitize_free_text(raw_url, limit=700)
    if not raw:
        return
    embed_url = _portal_video_embed_url(raw)
    if not embed_url:
        flash("Video bağlantısı desteklenmedi. YouTube veya Vimeo bağlantısı ekleyebilirsiniz.", "warning")
        return
    db.session.add(PortalPostAttachment(
        post_id=post.id,
        filename=raw[:255],
        stored_path=embed_url,
        mime_type="text/x-portal-video",
        size_bytes=0,
        uploaded_by_user_id=current_user.id,
    ))
    flash("Video bağlantısı paylaşımınıza eklendi.", "success")


def _portal_user_label(user: User) -> str:
    return sanitize_free_text(getattr(user, "full_name", ""), limit=180) or " ".join(
        part for part in [sanitize_free_text(getattr(user, "ad", ""), limit=80), sanitize_free_text(getattr(user, "soyad", ""), limit=80)] if part
    ) or sanitize_free_text(getattr(user, "email", ""), limit=180) or "BYS360 Kullanıcısı"


def _mention_user_ids_from_form(post: PortalPost) -> list[int]:
    selected: list[int] = []
    for value in request.form.getlist("mention_user_ids"):
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            continue
        if user_id <= 0 or user_id in selected:
            continue
        mentioned_user = User.query.filter_by(id=user_id, is_active=True).first()
        if not mentioned_user:
            continue
        if not can_user_view_post(mentioned_user, post):
            continue
        selected.append(user_id)
    return selected[:20]


def _notify_portal_user(*, user_id: int | None, title: str, body: str, link_url: str, notification_type: str, source_id: int | None) -> None:
    try:
        if not user_id or int(user_id) == int(getattr(current_user, "id", 0) or 0):
            return
        db.session.add(Notification(
            user_id=int(user_id),
            title=sanitize_free_text(title, limit=255) or "Kurumsal Portal",
            body=sanitize_free_text(body, limit=700),
            notification_type=notification_type,
            source_type="portal",
            source_id=source_id,
            link_url=link_url,
            priority="normal",
            is_read=False,
        ))
    except Exception:
        # Bildirim üretimi portal yorumunu düşürmemeli.
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/portal/routes.py:314")
        pass


def _save_comment_mentions(comment: PortalPostComment, post: PortalPost, mention_user_ids: list[int]) -> set[int]:
    notified: set[int] = set()
    actor_name = _portal_user_label(current_user)
    link_url = url_for("main.portal_feed", _anchor=f"post-{post.id}")
    for user_id in mention_user_ids:
        if user_id in notified:
            continue
        db.session.add(PortalCommentMention(
            comment_id=comment.id,
            mentioned_user_id=user_id,
            mentioned_by_user_id=getattr(current_user, "id", None),
            source_type="reply" if comment.parent_comment_id else "comment",
        ))
        notified.add(user_id)
        _notify_portal_user(
            user_id=user_id,
            title="Portal yorumunda etiketlendiniz",
            body=f"{actor_name} sizi bir portal yorumunda etiketledi.",
            link_url=link_url,
            notification_type="portal_comment_mention",
            source_id=comment.id,
        )
    return notified


def _notify_comment_reply(comment: PortalPostComment, post: PortalPost, already_notified: set[int]) -> None:
    if not comment.parent_comment_id:
        return
    parent = PortalPostComment.query.get(comment.parent_comment_id)
    if not parent or not parent.author_user_id or int(parent.author_user_id) in already_notified:
        return
    actor_name = _portal_user_label(current_user)
    _notify_portal_user(
        user_id=parent.author_user_id,
        title="Portal yorumunuza cevap geldi",
        body=f"{actor_name} yorumunuza cevap yazdı.",
        link_url=url_for("main.portal_feed", _anchor=f"post-{post.id}"),
        notification_type="portal_comment_reply",
        source_id=comment.id,
    )
# /BYS360_CORPORATE_PORTAL_MEDIA_VIDEO_V2_3_HELPERS
# /BYS360_PORTAL_MEDIA_COMMENTS_MENTIONS_V2_12_1_HELPERS


def _portal_common_context() -> dict:
    users = (
        User.query.filter_by(is_active=True)
        .order_by(User.ad.asc(), User.soyad.asc(), User.id.asc())
        .limit(400)
        .all()
    )
    return {
        "portal_reaction_options": REACTION_OPTIONS,
        "portal_post_type_options": POST_TYPE_OPTIONS,
        "portal_visibility_options": VISIBILITY_OPTIONS,
        "portal_groups": list_active_groups_for_user(current_user, include_all_for_manager=True),
        "portal_target_users": users,
        "portal_all_roles": sorted(PORTAL_ALL_ROLES),
        "portal_can_manage": can_manage_portal(current_user),
        "portal_press_news_visible": _portal_press_news_visible_for_user(current_user),
        "portal_can_announce": can_publish_announcement(current_user),
        "portal_current_profile": get_or_create_profile(current_user),
        **portal_experience_context(current_user),
        **portal_experience_v2_context(current_user),
    }

# BYS360_PORTAL_PROFILE_WALL_V2_9_WALL_HELPERS
def _wall_owner_id_from_form() -> int:
    raw_value = request.form.get("target_wall_user_id") or request.form.get("wall_owner_user_id")
    try:
        value = int(raw_value or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        value = int(getattr(current_user, "id", 0) or 0)
    return value


def _portal_people_query(limit: int = 80):
    q = sanitize_free_text(request.args.get("q"), limit=120)
    query = User.query.filter_by(is_active=True)
    if q:
        like = f"%{q}%"
        filters = []
        for attr in ("ad", "soyad", "email", "sicil_no", "unvan", "birim"):
            if hasattr(User, attr):
                filters.append(getattr(User, attr).ilike(like))
        if filters:
            query = query.filter(or_(*filters))
    people = query.order_by(User.ad.asc(), User.soyad.asc()).limit(limit).all()
    return q, people

def _selected_user_ids_from_form() -> list[int]:
    selected: list[int] = []
    for value in request.form.getlist("target_user_ids"):
        try:
            uid = int(value)
        except (TypeError, ValueError):
            continue
        if uid > 0 and uid not in selected:
            selected.append(uid)
    return selected[:200]


# BYS360_PORTAL_SETTINGS_ROLE_MATRIX_V2_12_ROUTE_GUARDS_BEGIN
def _portal_permission_denied_redirect(message: str):
    flash(message, "warning")
    return redirect(request.referrer or url_for("main.portal_feed"))


def _portal_has_permission(key: str) -> bool:
    return portal_permission_allowed(current_user, key)


# BYS360_PORTAL_AJAX_REACTIONS_V1_BEGIN
def _portal_wants_json_response() -> bool:
    """Portal küçük etkileşimlerinde sayfa yenilemeden JSON cevap üretir."""
    requested_with = (request.headers.get("X-Requested-With") or "").lower()
    accept = (request.headers.get("Accept") or "").lower()
    return (
        requested_with == "xmlhttprequest"
        or "application/json" in accept
        or request.form.get("_ajax") == "1"
    )


def _portal_reaction_payload(post: PortalPost, action: str, message: str) -> dict:
    counts = reaction_counts(post)
    return {
        "ok": True,
        "post_id": int(post.id),
        "action": action,
        "message": message,
        "reaction_counts": counts,
        "total_reactions": int(sum(counts.values())),
        "user_reaction": user_reaction_for_post(post, current_user),
    }
# BYS360_PORTAL_AJAX_REACTIONS_V1_END
# BYS360_PORTAL_SETTINGS_ROLE_MATRIX_V2_12_ROUTE_GUARDS_END


@main_bp.get("/portal")
@login_required
@menu_key_required("portal_feed")
def portal_feed():
    posts = [p for p in visible_posts_for_user(current_user, limit=40) if getattr(p, "post_type", "") not in ("instagram", "instagram_story")]
    # BYS360_PORTAL_LIGHT_HOME_V2_8_81_HIDE_INSTAGRAM_FEED
    context = _portal_common_context()
    context.update(
        page_title="Kurumsal Portal",
        active_portal_tab="feed",
        portal_feed_posts=enrich_posts(posts, current_user),
        portal_instagram_stories=[],
        press_news=press_news_home_context(current_user),
        # BYS360_PORTAL_LIGHT_HOME_V2_8_81_HIDE_INSTAGRAM_STORIES
    )
    return safe_render("portal/feed.html", "<h3>Kurumsal Portal</h3>", **context)


@main_bp.post("/portal/posts")
@login_required
@menu_key_required("portal_feed")
def portal_post_create():
    if not _portal_has_permission("portal_post_create"):
        return _portal_permission_denied_redirect("Yeni paylaşım yapma yetkiniz bulunmamaktadır.")
    title = sanitize_free_text(request.form.get("title"), limit=220)
    body = sanitize_free_text(request.form.get("body"), limit=4000)
    visibility_scope = normalize_visibility(request.form.get("visibility_scope"))
    post_type = normalize_post_type(request.form.get("post_type"), current_user)
    group_id = None
    target_role_name = ""
    if not body:
        flash("Paylaşım metni boş bırakılamaz.", "warning")
        return redirect(request.referrer or url_for("main.portal_feed"))

    # BYS360_PORTAL_PROFILE_WALL_V2_9_POST_WALL_VALIDATE
    wall_owner_user_id = _wall_owner_id_from_form()
    wall_owner_user = User.query.get(wall_owner_user_id)
    wall_owner_profile = None
    if wall_owner_user:
        if int(wall_owner_user_id) == int(getattr(current_user, "id", 0) or 0):
            wall_owner_profile = get_or_create_profile(wall_owner_user)
        else:
            wall_owner_profile = PortalProfile.query.filter_by(user_id=wall_owner_user_id).first()
    if wall_owner_user and int(wall_owner_user_id) != int(getattr(current_user, "id", 0) or 0) and not _portal_has_permission("portal_wall_post"):
        flash("Başka personelin profil duvarına paylaşım yapma yetkiniz bulunmamaktadır.", "warning")
        return redirect(request.referrer or url_for("main.portal_feed"))
    if not wall_owner_user or not can_user_post_to_wall(current_user, wall_owner_user, wall_owner_profile):
        flash("Bu profil duvarına paylaşım yapma yetkiniz bulunmamaktadır.", "warning")
        return redirect(request.referrer or url_for("main.portal_feed"))

    # BYS360_PORTAL_PROFILE_WALL_V2_8_WALL_VALIDATE
    wall_owner_user_id = _wall_owner_id_from_form()
    wall_owner_user = User.query.get(wall_owner_user_id)
    wall_owner_profile = None
    if wall_owner_user:
        if int(wall_owner_user_id) == int(getattr(current_user, "id", 0) or 0):
            wall_owner_profile = get_or_create_profile(wall_owner_user)
        else:
            wall_owner_profile = PortalProfile.query.filter_by(user_id=wall_owner_user_id).first()
    if not wall_owner_user or not can_user_post_to_wall(current_user, wall_owner_user, wall_owner_profile):
        flash("Bu profil duvarına paylaşım yapma yetkiniz bulunmamaktadır.", "warning")
        return redirect(request.referrer or url_for("main.portal_feed"))
    if visibility_scope == "group":
        try:
            group_id = int(request.form.get("target_group_id") or 0)
        except (TypeError, ValueError):
            group_id = None
        if not group_id:
            flash("Grup görünürlüğü için bir grup seçilmelidir.", "warning")
            return redirect(request.referrer or url_for("main.portal_feed"))
        if not (is_group_member(current_user, group_id) or can_manage_portal(current_user)):
            return render_access_denied()
    if visibility_scope == "selected_users" and not _selected_user_ids_from_form():
        flash("Belirli kişiler görünürlüğü için en az bir kişi seçilmelidir.", "warning")
        return redirect(request.referrer or url_for("main.portal_feed"))
    if visibility_scope == "role":
        target_role_name = sanitize_free_text(request.form.get("target_role_name"), limit=80)
        if not target_role_name:
            flash("Rol görünürlüğü için bir rol seçilmelidir.", "warning")
            return redirect(request.referrer or url_for("main.portal_feed"))

    post = PortalPost(
        author_user_id=current_user.id,
        # BYS360_PORTAL_PROFILE_WALL_V2_8_POST_FIELD
        wall_owner_user_id=wall_owner_user_id,
        group_id=group_id if visibility_scope == "group" else None,
        title=title or None,
        body=body,
        post_type=post_type,
        visibility_scope=visibility_scope,
        comments_enabled=bool(request.form.get("comments_enabled", "on")),
        target_unit_name=user_unit_name(current_user) if visibility_scope == "unit" else None,
        target_upper_unit_name=user_upper_unit_name(current_user) if visibility_scope == "upper_unit" else None,
        target_role_name=target_role_name if visibility_scope == "role" else None,
        published_at=utc_now(),
    )
    db.session.add(post)
    db.session.flush()
    _save_portal_images(post, request.files.getlist("portal_images"))
    _save_portal_video_file(post, request.files.getlist("portal_video_file"))
    _save_portal_video_link(post, request.form.get("video_url"))
    add_audience_entries(
        post,
        selected_user_ids=_selected_user_ids_from_form() if visibility_scope == "selected_users" else [],
        group_id=group_id if visibility_scope == "group" else None,
        role_name=target_role_name if visibility_scope == "role" else None,
    )
    notify_portal_post_created(post, current_user)
    db.session.commit()
    flash("Paylaşım yayınlandı.", "success")
    return redirect(request.referrer or url_for("main.portal_feed"))


# BYS360_B2F06_PORTAL_ATTACHMENT_ROUTE: portal medyası /static yerine bu route'tan,
# paylaşımı görebilen kullanıcıya sunulur (kart; akış, profil ve grup ekranlarında).
_PORTAL_POST_CARD_MENU_KEYS = ("portal_feed", "portal_profiles", "portal_groups")
_PORTAL_FILE_MIME_PREFIXES = ("image/", "video/")


@main_bp.get("/portal/attachments/<int:attachment_id>")
@login_required
def portal_attachment_file(attachment_id: int):
    if not any(can_access_menu(current_user, key) for key in _PORTAL_POST_CARD_MENU_KEYS):
        return render_access_denied()
    attachment = PortalPostAttachment.query.get_or_404(attachment_id)
    post = db.session.get(PortalPost, attachment.post_id)
    if post is None:
        abort(404)
    if not can_user_view_post(current_user, post):
        return render_access_denied()
    mime_type = str(attachment.mime_type or "").strip().lower()
    if not mime_type.startswith(_PORTAL_FILE_MIME_PREFIXES):
        abort(404)
    stored_name = Path(str(attachment.stored_path or "").replace("\\", "/")).name
    located = locate_upload(stored_name, (private_upload_path("portal"), legacy_static_upload_path("portal")))
    if located is None:
        abort(404)
    folder, safe_name = located
    response = send_from_directory(
        folder,
        safe_name,
        mimetype=mime_type,
        as_attachment=False,
        download_name=attachment.filename or safe_name,
    )
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


@main_bp.post("/portal/posts/<int:post_id>/react")
@login_required
@menu_key_required("portal_feed")
def portal_post_react(post_id: int):
    wants_json = _portal_wants_json_response()
    if not _portal_has_permission("portal_post_interact"):
        message = "Bu paylaşımda etkileşim yapma yetkiniz bulunmamaktadır."
        if wants_json:
            return jsonify({"ok": False, "message": message}), 403
        return _portal_permission_denied_redirect(message)
    post = PortalPost.query.get_or_404(post_id)
    if not can_user_view_post(current_user, post):
        if wants_json:
            return jsonify({"ok": False, "message": "Bu paylaşımı görüntüleme yetkiniz bulunmamaktadır."}), 403
        return render_access_denied()
    action = toggle_reaction(post, current_user, request.form.get("reaction_type", "like"))
    notify_portal_reaction(post, current_user, action=action)
    db.session.commit()
    message = "Tepkiniz güncellendi." if action != "removed" else "Tepkiniz kaldırıldı."
    if wants_json:
        return jsonify(_portal_reaction_payload(post, action, message))
    flash(message, "success")
    return redirect(request.referrer or url_for("main.portal_feed"))


@main_bp.post("/portal/posts/<int:post_id>/comments")
@login_required
@menu_key_required("portal_feed")
def portal_post_comment(post_id: int):
    if not _portal_has_permission("portal_post_interact"):
        return _portal_permission_denied_redirect("Bu paylaşımda yorum yapma yetkiniz bulunmamaktadır.")
    post = PortalPost.query.get_or_404(post_id)
    if not can_user_view_post(current_user, post):
        return render_access_denied()
    if not post.comments_enabled:
        flash("Bu paylaşımda yorumlar kapalıdır.", "warning")
        return redirect(request.referrer or url_for("main.portal_feed"))
    body = sanitize_free_text(request.form.get("comment_body"), limit=1200)
    if not body:
        flash("Yorum metni boş bırakılamaz.", "warning")
        return redirect(request.referrer or url_for("main.portal_feed"))
    parent_comment_id = None
    try:
        raw_parent_id = int(request.form.get("parent_comment_id") or 0)
    except (TypeError, ValueError):
        raw_parent_id = 0
    if raw_parent_id > 0:
        parent = PortalPostComment.query.filter_by(id=raw_parent_id, post_id=post.id, status="published").first()
        if not parent:
            flash("Cevap verilecek yorum bulunamadı.", "warning")
            return redirect(request.referrer or url_for("main.portal_feed"))
        parent_comment_id = parent.id
    comment = PortalPostComment(
        post_id=post.id,
        author_user_id=current_user.id,
        parent_comment_id=parent_comment_id,
        body=body,
    )
    db.session.add(comment)
    db.session.flush()
    notified = _save_comment_mentions(comment, post, _mention_user_ids_from_form(post))
    _notify_comment_reply(comment, post, notified)
    notify_portal_comment_added(post, comment, current_user, already_notified=notified)
    db.session.commit()
    flash("Cevabınız eklendi." if parent_comment_id else "Yorumunuz eklendi.", "success")
    return redirect(request.referrer or url_for("main.portal_feed"))


@main_bp.post("/portal/posts/<int:post_id>/save")
@login_required
@menu_key_required("portal_feed")
def portal_post_save(post_id: int):
    if not _portal_has_permission("portal_post_interact"):
        return _portal_permission_denied_redirect("Bu paylaşımı kaydetme yetkiniz bulunmamaktadır.")
    post = PortalPost.query.get_or_404(post_id)
    if not can_user_view_post(current_user, post):
        return render_access_denied()
    action = toggle_save(post, current_user)
    db.session.commit()
    flash("Paylaşım kaydedildi." if action == "added" else "Kaydedilenlerden kaldırıldı.", "success")
    return redirect(request.referrer or url_for("main.portal_feed"))

@main_bp.post("/portal/posts/<int:post_id>/report")
@login_required
@menu_key_required("portal_feed")
def portal_post_report(post_id: int):
    if not _portal_has_permission("portal_post_report"):
        return _portal_permission_denied_redirect("Paylaşım bildirme yetkiniz bulunmamaktadır.")
    post = PortalPost.query.get_or_404(post_id)
    if not can_user_view_post(current_user, post):
        return render_access_denied()
    reason = sanitize_free_text(request.form.get("reason"), limit=500)
    if not reason:
        reason = "Kullanıcı tarafından incelenmesi istendi."
    report = PortalPostReport(post_id=post.id, reporter_user_id=current_user.id, reason=reason)
    db.session.add(report)
    db.session.flush()
    notify_portal_report_created(post, current_user, report_id=report.id)
    db.session.commit()
    flash("Paylaşım inceleme için bildirildi.", "success")
    return redirect(request.referrer or url_for("main.portal_feed"))

# BYS360_PORTAL_MEDIA_COMMENTS_MENTIONS_V2_12_1_MENTION_ROUTE
@main_bp.get("/portal/mentions/users")
@login_required
@menu_key_required("portal_feed")
def portal_mention_users():
    if not _portal_has_permission("portal_post_interact"):
        return jsonify({"items": []})
    q = sanitize_free_text(request.args.get("q"), limit=80)
    query = User.query.filter_by(is_active=True)
    if q:
        like = f"%{q}%"
        filters = []
        for attr in ("ad", "soyad", "email", "sicil_no", "unvan", "birim"):
            if hasattr(User, attr):
                filters.append(getattr(User, attr).ilike(like))
        if filters:
            query = query.filter(or_(*filters))
    rows = query.order_by(User.ad.asc(), User.soyad.asc(), User.id.asc()).limit(12).all()
    items = []
    for user in rows:
        label = _portal_user_label(user)
        subtitle_parts = [sanitize_free_text(getattr(user, "unvan", ""), limit=80), sanitize_free_text(getattr(user, "birim", ""), limit=120)]
        items.append({
            "id": int(user.id),
            "label": label,
            "insert": "@" + label,
            "subtitle": " · ".join(part for part in subtitle_parts if part),
        })
    return jsonify({"items": items})

# BYS360_PORTAL_PROFILE_WALL_V2_9_PEOPLE_ROUTE
@main_bp.get("/portal/people")
@login_required
@menu_key_required("portal_profiles")
def portal_people():
    if not _portal_has_permission("portal_people"):
        return render_access_denied()
    q, people = _portal_people_query(limit=120)
    context = _portal_common_context()
    context.update(
        page_title="Personel Duvarları",
        active_portal_tab="people",
        portal_people_query=q,
        portal_people=people,
    )
    return safe_render("portal/people.html", "<h3>Personel Duvarları</h3>", **context)

@main_bp.get("/portal/profile/me")
@login_required
@menu_key_required("portal_profiles")
def portal_my_profile():
    return redirect(url_for("main.portal_profile", user_id=current_user.id))


@main_bp.get("/portal/profile/<int:user_id>")
@login_required
@menu_key_required("portal_profiles")
def portal_profile(user_id: int):
    user = User.query.get_or_404(user_id)
    profile = get_or_create_profile(user) if user_id == current_user.id else PortalProfile.query.filter_by(user_id=user_id).first()
    # BYS360_PORTAL_PROFILE_WALL_V2_8_PROFILE_WALL_QUERY
    posts = visible_posts_for_user(current_user, limit=40, wall_owner_id=user_id)
    context = _portal_common_context()
    context.update(
        page_title=f"{display_user_name(user)} - Portal Profili",
        active_portal_tab="profile",
        portal_profile_user=user,
        portal_profile=profile,
        # BYS360_PORTAL_PROFILE_WALL_V2_8_PROFILE_CONTEXT
        portal_wall_owner_user=user,
        portal_can_post_to_wall=can_user_post_to_wall(current_user, user, profile),
        portal_feed_posts=enrich_posts(posts, current_user),
    )
    return safe_render("portal/profile.html", "<h3>Portal Profili</h3>", **context)

@main_bp.get("/portal/groups")
@login_required
@menu_key_required("portal_groups")
def portal_groups():
    groups = list_active_groups_for_user(current_user, include_all_for_manager=True)
    context = _portal_common_context()
    context.update(page_title="Portal Grupları", active_portal_tab="groups", portal_group_list=groups)
    return safe_render("portal/groups.html", "<h3>Portal Grupları</h3>", **context)


@main_bp.post("/portal/groups")
@login_required
@menu_key_required("portal_groups")
def portal_group_create():
    if not _portal_has_permission("portal_group_create"):
        return _portal_permission_denied_redirect("Portal grubu oluşturma yetkiniz bulunmamaktadır.")
    if not can_manage_portal(current_user):
        return render_access_denied()
    name = sanitize_free_text(request.form.get("name"), limit=180)
    description = sanitize_free_text(request.form.get("description"), limit=1200)
    group_type = sanitize_free_text(request.form.get("group_type"), limit=30) or "official"
    if not name:
        flash("Grup adı boş bırakılamaz.", "warning")
        return redirect(url_for("main.portal_groups"))
    base_slug = _slugify(name)
    slug = base_slug
    counter = 2
    while PortalGroup.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    group = PortalGroup(name=name, slug=slug, description=description, group_type=group_type, owner_user_id=current_user.id)
    db.session.add(group)
    db.session.flush()
    db.session.add(PortalGroupMember(group_id=group.id, user_id=current_user.id, member_role="owner", status="active", approved_by_user_id=current_user.id, approved_at=utc_now()))
    db.session.commit()
    flash("Portal grubu oluşturuldu.", "success")
    return redirect(url_for("main.portal_group_detail", group_id=group.id))


@main_bp.get("/portal/groups/<int:group_id>")
@login_required
@menu_key_required("portal_groups")
def portal_group_detail(group_id: int):
    group = PortalGroup.query.get_or_404(group_id)
    if not (is_group_member(current_user, group.id) or can_manage_portal(current_user)):
        return render_access_denied()
    posts = visible_posts_for_user(current_user, limit=40, group_id=group.id)
    context = _portal_common_context()
    context.update(
        page_title=group.name,
        active_portal_tab="groups",
        portal_group=group,
        portal_feed_posts=enrich_posts(posts, current_user),
    )
    return safe_render("portal/group_detail.html", "<h3>Portal Grubu</h3>", **context)


@main_bp.get("/portal/moderation")
@login_required
@menu_key_required("portal_moderation")
def portal_moderation():
    if not can_manage_portal(current_user):
        return render_access_denied()
    reports = PortalPostReport.query.order_by(PortalPostReport.created_at.desc()).limit(80).all()
    hidden_posts = PortalPost.query.filter(PortalPost.status != "published").order_by(PortalPost.updated_at.desc()).limit(80).all()
    context = _portal_common_context()
    context.update(
        page_title="Portal Yönetimi",
        active_portal_tab="moderation",
        portal_reports=reports,
        portal_hidden_posts=hidden_posts,
    )
    return safe_render("portal/moderation.html", "<h3>Portal Yönetimi</h3>", **context)


@main_bp.post("/portal/posts/<int:post_id>/moderate")
@login_required
@menu_key_required("portal_moderation")
def portal_post_moderate(post_id: int):
    if not can_manage_portal(current_user):
        return render_access_denied()
    post = PortalPost.query.get_or_404(post_id)
    action = sanitize_free_text(request.form.get("action"), limit=30)
    note = sanitize_free_text(request.form.get("note"), limit=500)
    if action == "hide":
        post.status = "hidden"
        post.hidden_by_user_id = current_user.id
        post.hidden_at = utc_now()
        post.hidden_reason = note or "Portal yönetimi tarafından gizlendi."
        flash("Paylaşım gizlendi.", "success")
    elif action == "publish":
        post.status = "published"
        post.hidden_by_user_id = None
        post.hidden_at = None
        post.hidden_reason = None
        flash("Paylaşım yeniden yayınlandı.", "success")
    elif action == "pin":
        post.is_pinned = True
        flash("Paylaşım sabitlendi.", "success")
    elif action == "unpin":
        post.is_pinned = False
        flash("Paylaşım sabitlemesi kaldırıldı.", "success")
    else:
        flash("Geçersiz portal yönetimi işlemi.", "warning")
        return redirect(request.referrer or url_for("main.portal_moderation"))
    db.session.add(PortalModerationLog(actor_user_id=current_user.id, post_id=post.id, action_type=action, note=note))
    db.session.commit()
    return redirect(request.referrer or url_for("main.portal_moderation"))

# BYS360_PORTAL_INSTAGRAM_FEED_V2_11_0_ROUTE_BEGIN
@main_bp.post("/portal/instagram/sync")
@login_required
@menu_key_required("portal_moderation")
def portal_instagram_sync():
    if not can_manage_portal(current_user):
        return render_access_denied()
    result = sync_instagram_to_portal(actor_user=current_user)
    message = result.get("message") or "Instagram akisi kontrol edildi."
    if result.get("ok"):
        flash(message, "success" if result.get("enabled") else "info")
    else:
        flash(message, "warning")
    return redirect(request.referrer or url_for("main.portal_feed"))
# BYS360_PORTAL_INSTAGRAM_FEED_V2_11_0_ROUTE_END


# BYS360_PROFILE_WALL_DELETE_ROUTE_V2_9_4
@main_bp.post("/portal/posts/<int:post_id>/delete")
@login_required
@menu_key_required("portal_feed")
def portal_post_delete(post_id: int):
    if not _portal_has_permission("portal_post_delete"):
        return _portal_permission_denied_redirect("Paylaşımı yayından kaldırma yetkiniz bulunmamaktadır.")
    post = PortalPost.query.get_or_404(post_id)
    if not can_user_delete_post(current_user, post):
        flash("Bu paylaşımı silme yetkiniz bulunmamaktadır.", "warning")
        return redirect(request.referrer or url_for("main.portal_feed"))

    now = utc_now()
    post.status = "deleted"
    if hasattr(post, "hidden_at"):
        post.hidden_at = now
    if hasattr(post, "hidden_by_user_id"):
        post.hidden_by_user_id = getattr(current_user, "id", None)
    if hasattr(post, "hidden_reason"):
        post.hidden_reason = "Kullanıcı tarafından yayından kaldırıldı"
    if hasattr(post, "updated_at"):
        post.updated_at = now
    db.session.commit()
    flash("Paylaşım yayından kaldırıldı.", "success")
    return redirect(request.referrer or url_for("main.portal_feed"))


# BYS360_PORTAL_DELETE_ROUTE_DEDUPE_V2_10_2: duplicate portal_post_delete blocks removed safely

# Compatibility guard.
def _portal_press_news_admin_only(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if bool(getattr(user, 'is_admin', False)) or bool(getattr(user, 'is_superuser', False)):
        return True
    role = str(getattr(user, 'role', '') or '').strip().lower().replace('-', '_').replace(' ', '_')
    role = (role.replace('İ', 'i').replace('I', 'i').replace('ı', 'i')
                 .replace('Ş', 's').replace('ş', 's')
                 .replace('Ğ', 'g').replace('ğ', 'g')
                 .replace('Ü', 'u').replace('ü', 'u')
                 .replace('Ö', 'o').replace('ö', 'o')
                 .replace('Ç', 'c').replace('ç', 'c'))
    return role in {'admin', 'super_admin', 'system_admin', 'sistem_yoneticisi', 'administrator'}

# BYS360_PORTAL_EXPERIENCE_V3A_PRESS_NEWS_ROUTES_BEGIN
@main_bp.get("/portal/press-news")
@login_required
@menu_key_required("portal_press_news")
def portal_press_news_review():
    if not _portal_press_news_admin_only_allowed(current_user):
        return render_access_denied()
    context = _portal_common_context()
    context.update(
        page_title="Basında Tarihi Alan",
        active_portal_tab="press_news",
        press_news_review=press_news_review_context(current_user),
    )
    return safe_render("portal/press_news_review_v3a.html", "<h3>Basında Tarihi Alan</h3>", **context)


@main_bp.post("/portal/press-news/scan")
@login_required
@menu_key_required("portal_press_news")
def portal_press_news_scan_now():
    if not _portal_press_news_admin_only_allowed(current_user):
        return render_access_denied()
    result = scan_press_news_candidates(triggered_by_user_id=getattr(current_user, "id", None), manual=True)
    added = int(result.get("added", 0) or 0)
    if added:
        flash(f"{added} yeni haber adayı inceleme havuzuna alındı.", "success")
    else:
        flash("Yeni haber adayı bulunamadı. Mevcut adaylar kontrol edildi.", "info")
    return redirect(url_for("main.portal_press_news_review"))


@main_bp.post("/portal/press-news/<candidate_id>/publish")
@login_required
@menu_key_required("portal_press_news")
def portal_press_news_publish(candidate_id: str):
    if not _portal_press_news_admin_only_allowed(current_user):
        return render_access_denied()
    result = publish_press_news_candidate(candidate_id, current_user)
    if result.get("ok"):
        flash("Haber adayı portal paylaşımı olarak yayınlandı.", "success")
    else:
        flash(result.get("message") or "Haber adayı yayınlanamadı.", "warning")
    return redirect(url_for("main.portal_press_news_review"))


@main_bp.post("/portal/press-news/<candidate_id>/archive")
@login_required
@menu_key_required("portal_press_news")
def portal_press_news_archive(candidate_id: str):
    if not _portal_press_news_admin_only_allowed(current_user):
        return render_access_denied()
    result = archive_press_news_candidate(candidate_id, current_user)
    flash(result.get("message") or "Haber adayı arşivlendi.", "info")
    return redirect(url_for("main.portal_press_news_review"))
# BYS360_PORTAL_EXPERIENCE_V3A_PRESS_NEWS_ROUTES_END

# BYS360_PORTAL_EXPERIENCE_V3B8_SOCIAL_IMPORT_REMOVED_REDIRECT_BEGIN
@main_bp.before_app_request
def bys360_portal_v3b8_social_import_removed_redirect():
    try:
        from flask import (
            redirect as _bys360_redirect,
            request as _bys360_request,
            url_for as _bys360_url_for,
        )
        if str(getattr(_bys360_request, 'path', '') or '').startswith('/portal/social-import'):
            return _bys360_redirect(_bys360_url_for('main.portal_press_news_review'))
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 SAFE V4: sessiz except loglandi: app/portal/routes.py:982")
        return None
    return None
# BYS360_PORTAL_EXPERIENCE_V3B8_SOCIAL_IMPORT_REMOVED_REDIRECT_END
