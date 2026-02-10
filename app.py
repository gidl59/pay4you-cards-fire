import os
import re
import json
import uuid
import datetime as dt
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, abort, flash, send_from_directory, Response
)

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime
)
from sqlalchemy.orm import declarative_base, sessionmaker
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

import qrcode


# ==========================
# CONFIG
# ==========================
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////var/data/pay4you.db").strip()
PERSIST_UPLOADS_DIR = os.getenv("PERSIST_UPLOADS_DIR", "/var/data/uploads").strip()

MAX_GALLERY_IMAGES = 30
MAX_VIDEOS = 10
MAX_PDFS = 12

SUPPORTED_LANGS = ["it", "en", "fr", "es", "de"]


# ==========================
# DIRS
# ==========================
UPLOADS_DIR = Path(PERSIST_UPLOADS_DIR)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

SUBDIR_IMG = UPLOADS_DIR / "images"
SUBDIR_VID = UPLOADS_DIR / "videos"
SUBDIR_PDF = UPLOADS_DIR / "pdf"
for d in (SUBDIR_IMG, SUBDIR_VID, SUBDIR_PDF):
    d.mkdir(parents=True, exist_ok=True)


# ==========================
# FLASK
# ==========================
app = Flask(__name__)
app.secret_key = APP_SECRET


# ==========================
# SQLA
# ==========================
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ==========================
# MODEL
# ==========================
class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)

    # auth
    slug = Column(String(120), unique=True, nullable=False, index=True)
    username = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)

    # core P1
    name = Column(String(200), default="")
    company = Column(String(200), default="")
    role = Column(String(200), default="")
    bio = Column(Text, default="")

    phone_mobile = Column(String(120), default="")
    phone_mobile2 = Column(String(120), default="")
    phone_office = Column(String(120), default="")
    whatsapp = Column(String(255), default="")
    emails = Column(Text, default="")
    websites = Column(Text, default="")
    pec = Column(String(255), default="")
    addresses = Column(Text, default="")

    piva = Column(String(120), default="")
    sdi = Column(String(120), default="")

    facebook = Column(String(255), default="")
    instagram = Column(String(255), default="")
    linkedin = Column(String(255), default="")
    tiktok = Column(String(255), default="")
    telegram = Column(String(255), default="")
    youtube = Column(String(255), default="")
    spotify = Column(String(255), default="")

    # media P1
    photo_url = Column(String(255), default="")
    logo_url = Column(String(255), default="")
    back_media_mode = Column(String(30), default="company")  # company|personal
    back_media_url = Column(String(255), default="")

    photo_pos_x = Column(Integer, default=50)
    photo_pos_y = Column(Integer, default=35)
    photo_zoom = Column(String(20), default="1.0")

    orbit_spin = Column(Integer, default=0)
    avatar_spin = Column(Integer, default=0)
    logo_spin = Column(Integer, default=0)
    allow_flip = Column(Integer, default=0)

    gallery_urls = Column(Text, default="")  # url|url|...
    video_urls = Column(Text, default="")    # url|url|...
    pdf1_url = Column(Text, default="")      # name||url|name||url...

    # P2
    p2_enabled = Column(Integer, default=0)

    # P2 text fields (JSON) -> same fields as P1
    p2_json = Column(Text, default="{}")

    # P2 media / effects / crop / lists
    p2_photo_url = Column(String(255), default="")
    p2_logo_url = Column(String(255), default="")
    p2_back_media_mode = Column(String(30), default="company")
    p2_back_media_url = Column(String(255), default="")

    p2_photo_pos_x = Column(Integer, default=50)
    p2_photo_pos_y = Column(Integer, default=35)
    p2_photo_zoom = Column(String(20), default="1.0")

    p2_orbit_spin = Column(Integer, default=0)
    p2_avatar_spin = Column(Integer, default=0)
    p2_logo_spin = Column(Integer, default=0)
    p2_allow_flip = Column(Integer, default=0)

    p2_gallery_urls = Column(Text, default="")
    p2_video_urls = Column(Text, default="")
    p2_pdf1_url = Column(Text, default="")

    # i18n: supports both old format {"en":{name,...}} and new format {"en":{"p1":{...},"p2":{...}}}
    i18n_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=lambda: dt.datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: dt.datetime.utcnow())


# ==========================
# DB INIT + SAFE MIGRATION (SQLite)
# ==========================
def _sqlite_table_columns(conn, table_name: str):
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    return {r[1] for r in rows}


def ensure_db():
    Base.metadata.create_all(engine)

    if not DATABASE_URL.startswith("sqlite"):
        return

    with engine.connect() as conn:
        cols = _sqlite_table_columns(conn, "agents")

        def add_col(name, coltype):
            if name not in cols:
                conn.exec_driver_sql(f"ALTER TABLE agents ADD COLUMN {name} {coltype}")

        # columns that may be missing in old dbs
        add_col("created_at", "DATETIME")
        add_col("updated_at", "DATETIME")
        add_col("p2_json", "TEXT")
        add_col("i18n_json", "TEXT")

        add_col("photo_pos_x", "INTEGER")
        add_col("photo_pos_y", "INTEGER")
        add_col("photo_zoom", "TEXT")
        add_col("back_media_mode", "TEXT")
        add_col("back_media_url", "TEXT")
        add_col("orbit_spin", "INTEGER")
        add_col("avatar_spin", "INTEGER")
        add_col("logo_spin", "INTEGER")
        add_col("allow_flip", "INTEGER")

        # P2 columns
        add_col("p2_enabled", "INTEGER")
        add_col("p2_photo_url", "TEXT")
        add_col("p2_logo_url", "TEXT")
        add_col("p2_back_media_mode", "TEXT")
        add_col("p2_back_media_url", "TEXT")
        add_col("p2_photo_pos_x", "INTEGER")
        add_col("p2_photo_pos_y", "INTEGER")
        add_col("p2_photo_zoom", "TEXT")
        add_col("p2_orbit_spin", "INTEGER")
        add_col("p2_avatar_spin", "INTEGER")
        add_col("p2_logo_spin", "INTEGER")
        add_col("p2_allow_flip", "INTEGER")
        add_col("p2_gallery_urls", "TEXT")
        add_col("p2_video_urls", "TEXT")
        add_col("p2_pdf1_url", "TEXT")

        # backfill defaults safely
        now = dt.datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        conn.exec_driver_sql("UPDATE agents SET created_at = COALESCE(created_at, ?)", (now,))
        conn.exec_driver_sql("UPDATE agents SET updated_at = COALESCE(updated_at, ?)", (now,))
        conn.exec_driver_sql("UPDATE agents SET p2_json = COALESCE(p2_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET i18n_json = COALESCE(i18n_json, '{}')")

        conn.exec_driver_sql("UPDATE agents SET photo_pos_x = COALESCE(photo_pos_x, 50)")
        conn.exec_driver_sql("UPDATE agents SET photo_pos_y = COALESCE(photo_pos_y, 35)")
        conn.exec_driver_sql("UPDATE agents SET photo_zoom = COALESCE(photo_zoom, '1.0')")
        conn.exec_driver_sql("UPDATE agents SET back_media_mode = COALESCE(back_media_mode, 'company')")
        conn.exec_driver_sql("UPDATE agents SET back_media_url = COALESCE(back_media_url, '')")
        conn.exec_driver_sql("UPDATE agents SET orbit_spin = COALESCE(orbit_spin, 0)")
        conn.exec_driver_sql("UPDATE agents SET avatar_spin = COALESCE(avatar_spin, 0)")
        conn.exec_driver_sql("UPDATE agents SET logo_spin = COALESCE(logo_spin, 0)")
        conn.exec_driver_sql("UPDATE agents SET allow_flip = COALESCE(allow_flip, 0)")

        conn.exec_driver_sql("UPDATE agents SET p2_enabled = COALESCE(p2_enabled, 0)")
        conn.exec_driver_sql("UPDATE agents SET p2_photo_pos_x = COALESCE(p2_photo_pos_x, 50)")
        conn.exec_driver_sql("UPDATE agents SET p2_photo_pos_y = COALESCE(p2_photo_pos_y, 35)")
        conn.exec_driver_sql("UPDATE agents SET p2_photo_zoom = COALESCE(p2_photo_zoom, '1.0')")
        conn.exec_driver_sql("UPDATE agents SET p2_orbit_spin = COALESCE(p2_orbit_spin, 0)")
        conn.exec_driver_sql("UPDATE agents SET p2_avatar_spin = COALESCE(p2_avatar_spin, 0)")
        conn.exec_driver_sql("UPDATE agents SET p2_logo_spin = COALESCE(p2_logo_spin, 0)")
        conn.exec_driver_sql("UPDATE agents SET p2_allow_flip = COALESCE(p2_allow_flip, 0)")
        conn.exec_driver_sql("UPDATE agents SET p2_gallery_urls = COALESCE(p2_gallery_urls, '')")
        conn.exec_driver_sql("UPDATE agents SET p2_video_urls = COALESCE(p2_video_urls, '')")
        conn.exec_driver_sql("UPDATE agents SET p2_pdf1_url = COALESCE(p2_pdf1_url, '')")

        conn.commit()


ensure_db()


# ==========================
# HELPERS
# ==========================
def db():
    return SessionLocal()


def is_admin():
    return session.get("role") == "admin"


def require_login():
    if not session.get("role"):
        return redirect(url_for("login"))
    return None


def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9\- ]+", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    s = re.sub(r"\-+", "-", s)
    return s[:80] if s else ""


def public_base_url():
    if BASE_URL:
        return BASE_URL
    return request.url_root.strip().rstrip("/")


def split_csv(s: str):
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def split_lines(s: str):
    if not s:
        return []
    return [x.strip() for x in s.splitlines() if x.strip()]


def normalize_url(u: str):
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "https://" + u


def uploads_url(rel_path: str) -> str:
    rel_path = rel_path.lstrip("/")
    return f"/uploads/{rel_path}"


def save_upload(file_storage, kind: str):
    if not file_storage or not file_storage.filename:
        return ""
    filename = secure_filename(file_storage.filename)
    ext = os.path.splitext(filename)[1].lower()
    uid = uuid.uuid4().hex[:12]
    outname = f"{uid}{ext}"

    if kind == "images":
        outpath = SUBDIR_IMG / outname
        rel = f"images/{outname}"
    elif kind == "videos":
        outpath = SUBDIR_VID / outname
        rel = f"videos/{outname}"
    else:
        outpath = SUBDIR_PDF / outname
        rel = f"pdf/{outname}"

    file_storage.save(str(outpath))
    return uploads_url(rel)


def parse_pdf_items(pdf1_url: str):
    items = []
    if not pdf1_url:
        return items
    for chunk in pdf1_url.split("|"):
        if not chunk.strip():
            continue
        if "||" in chunk:
            name, url = chunk.split("||", 1)
            items.append({"name": name.strip() or "Documento", "url": url.strip()})
        else:
            items.append({"name": chunk.strip(), "url": chunk.strip()})
    return items


def infer_lang_from_request(default="it"):
    # If user passes ?lang=xx we use it.
    q = (request.args.get("lang") or "").strip().lower()
    if q in SUPPORTED_LANGS:
        return q

    # Otherwise infer from Accept-Language (phone locale)
    best = request.accept_languages.best_match(SUPPORTED_LANGS)
    if best:
        return best
    return default


def get_i18n(agent: Agent):
    try:
        data = json.loads(agent.i18n_json or "{}")
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _i18n_get_profile_block(i18n_data: dict, lang: str, profile: str):
    """
    Supports:
      old format: i18n["en"] = {"name":...,"company":...}
      new format: i18n["en"] = {"p1":{...}, "p2":{...}}
    """
    pack = i18n_data.get(lang) or {}
    if not isinstance(pack, dict):
        return {}

    # new
    if "p1" in pack or "p2" in pack:
        blk = pack.get(profile) or {}
        if isinstance(blk, dict):
            return blk
        return {}

    # old => treat as p1 only
    if profile == "p1":
        return pack
    return {}


def get_profile_dict(agent: Agent, profile: str):
    """
    profile: 'p1' or 'p2'
    returns dict containing all fields for that profile (same keys)
    """
    if profile == "p2":
        try:
            d = json.loads(agent.p2_json or "{}")
            if not isinstance(d, dict):
                d = {}
        except Exception:
            d = {}

        # ensure same keys as P1
        base = {
            "name": d.get("name", "") or "",
            "company": d.get("company", "") or "",
            "role": d.get("role", "") or "",
            "bio": d.get("bio", "") or "",

            "phone_mobile": d.get("phone_mobile", "") or "",
            "phone_mobile2": d.get("phone_mobile2", "") or "",
            "phone_office": d.get("phone_office", "") or "",
            "whatsapp": d.get("whatsapp", "") or "",
            "emails": d.get("emails", "") or "",
            "websites": d.get("websites", "") or "",
            "pec": d.get("pec", "") or "",
            "addresses": d.get("addresses", "") or "",

            "piva": d.get("piva", "") or "",
            "sdi": d.get("sdi", "") or "",

            "facebook": d.get("facebook", "") or "",
            "instagram": d.get("instagram", "") or "",
            "linkedin": d.get("linkedin", "") or "",
            "tiktok": d.get("tiktok", "") or "",
            "telegram": d.get("telegram", "") or "",
            "youtube": d.get("youtube", "") or "",
            "spotify": d.get("spotify", "") or "",

            # media columns P2
            "photo_url": agent.p2_photo_url or "",
            "logo_url": agent.p2_logo_url or "",
            "back_media_mode": agent.p2_back_media_mode or "company",
            "back_media_url": agent.p2_back_media_url or "",

            "photo_pos_x": agent.p2_photo_pos_x if agent.p2_photo_pos_x is not None else 50,
            "photo_pos_y": agent.p2_photo_pos_y if agent.p2_photo_pos_y is not None else 35,
            "photo_zoom": agent.p2_photo_zoom or "1.0",

            "orbit_spin": int(agent.p2_orbit_spin or 0),
            "avatar_spin": int(agent.p2_avatar_spin or 0),
            "logo_spin": int(agent.p2_logo_spin or 0),
            "allow_flip": int(agent.p2_allow_flip or 0),

            "gallery_urls": agent.p2_gallery_urls or "",
            "video_urls": agent.p2_video_urls or "",
            "pdf1_url": agent.p2_pdf1_url or "",
        }
        return base

    # P1
    return {
        "name": agent.name or "",
        "company": agent.company or "",
        "role": agent.role or "",
        "bio": agent.bio or "",

        "phone_mobile": agent.phone_mobile or "",
        "phone_mobile2": agent.phone_mobile2 or "",
        "phone_office": agent.phone_office or "",
        "whatsapp": agent.whatsapp or "",
        "emails": agent.emails or "",
        "websites": agent.websites or "",
        "pec": agent.pec or "",
        "addresses": agent.addresses or "",

        "piva": agent.piva or "",
        "sdi": agent.sdi or "",

        "facebook": agent.facebook or "",
        "instagram": agent.instagram or "",
        "linkedin": agent.linkedin or "",
        "tiktok": agent.tiktok or "",
        "telegram": agent.telegram or "",
        "youtube": agent.youtube or "",
        "spotify": agent.spotify or "",

        "photo_url": agent.photo_url or "",
        "logo_url": agent.logo_url or "",
        "back_media_mode": agent.back_media_mode or "company",
        "back_media_url": agent.back_media_url or "",

        "photo_pos_x": agent.photo_pos_x if agent.photo_pos_x is not None else 50,
        "photo_pos_y": agent.photo_pos_y if agent.photo_pos_y is not None else 35,
        "photo_zoom": agent.photo_zoom or "1.0",

        "orbit_spin": int(agent.orbit_spin or 0),
        "avatar_spin": int(agent.avatar_spin or 0),
        "logo_spin": int(agent.logo_spin or 0),
        "allow_flip": int(agent.allow_flip or 0),

        "gallery_urls": agent.gallery_urls or "",
        "video_urls": agent.video_urls or "",
        "pdf1_url": agent.pdf1_url or "",
    }


def set_profile_from_form(agent: Agent, profile: str, form: dict, files: dict):
    """
    profile: p1 or p2
    Saves:
      - text/contact/social in columns (p1) or in p2_json (p2)
      - media/crop/effects/gallery/video/pdf in correct place
    """
    # Mutual exclusivity: avatar_spin vs allow_flip
    avatar_spin = 1 if form.get("avatar_spin") == "on" else 0
    allow_flip = 1 if form.get("allow_flip") == "on" else 0
    if avatar_spin == 1:
        allow_flip = 0
    if allow_flip == 1:
        avatar_spin = 0

    orbit_spin = 1 if form.get("orbit_spin") == "on" else 0
    logo_spin = 1 if form.get("logo_spin") == "on" else 0

    # common fields list
    fields = [
        "name","company","role","bio",
        "phone_mobile","phone_mobile2","phone_office","whatsapp",
        "emails","websites","pec","addresses",
        "piva","sdi",
        "facebook","instagram","linkedin","tiktok","telegram","youtube","spotify"
    ]

    if profile == "p2":
        # TEXT -> p2_json
        data = {}
        for k in fields:
            data[k] = (form.get(k) or "").strip()

        agent.p2_json = json.dumps(data, ensure_ascii=False)

        # media settings -> p2 columns
        agent.p2_back_media_mode = (form.get("back_media_mode") or "company").strip() or "company"
        agent.p2_photo_pos_x = int(form.get("photo_pos_x") or 50)
        agent.p2_photo_pos_y = int(form.get("photo_pos_y") or 35)
        agent.p2_photo_zoom = str(form.get("photo_zoom") or "1.0")

        agent.p2_orbit_spin = orbit_spin
        agent.p2_avatar_spin = avatar_spin
        agent.p2_logo_spin = logo_spin
        agent.p2_allow_flip = allow_flip

        # uploads P2
        photo = files.get("photo")
        if photo and photo.filename:
            agent.p2_photo_url = save_upload(photo, "images")

        logo = files.get("logo")
        if logo and logo.filename:
            agent.p2_logo_url = save_upload(logo, "images")

        back_media = files.get("back_media")
        if back_media and back_media.filename:
            agent.p2_back_media_url = save_upload(back_media, "images")

        # gallery overwrite if uploaded
        gallery_files = files.getlist("gallery") if hasattr(files, "getlist") else []
        gallery_files = [f for f in gallery_files if f and f.filename]
        if gallery_files:
            gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
            urls = [save_upload(f, "images") for f in gallery_files]
            agent.p2_gallery_urls = "|".join([u for u in urls if u])

        # videos overwrite if uploaded
        video_files = files.getlist("videos") if hasattr(files, "getlist") else []
        video_files = [f for f in video_files if f and f.filename]
        if video_files:
            video_files = video_files[:MAX_VIDEOS]
            urls = [save_upload(f, "videos") for f in video_files]
            agent.p2_video_urls = "|".join([u for u in urls if u])

        # pdf slots
        existing = parse_pdf_items(agent.p2_pdf1_url or "")
        out = existing[:] if existing else []
        for i in range(1, MAX_PDFS + 1):
            f = files.get(f"pdf{i}")
            if f and f.filename:
                url = save_upload(f, "pdf")
                name = secure_filename(f.filename) or f"PDF {i}"
                idx = i - 1
                while len(out) <= idx:
                    out.append({"name": "", "url": ""})
                out[idx] = {"name": name, "url": url}

        out2 = []
        for item in out:
            if item.get("url"):
                out2.append(f"{item.get('name','Documento')}||{item.get('url')}")
        agent.p2_pdf1_url = "|".join(out2)

        agent.updated_at = dt.datetime.utcnow()
        return

    # profile p1: save to columns
    agent.name = (form.get("name") or "").strip()
    agent.company = (form.get("company") or "").strip()
    agent.role = (form.get("role") or "").strip()
    agent.bio = (form.get("bio") or "").strip()

    agent.phone_mobile = (form.get("phone_mobile") or "").strip()
    agent.phone_mobile2 = (form.get("phone_mobile2") or "").strip()
    agent.phone_office = (form.get("phone_office") or "").strip()
    agent.whatsapp = (form.get("whatsapp") or "").strip()
    agent.emails = (form.get("emails") or "").strip()
    agent.websites = (form.get("websites") or "").strip()
    agent.pec = (form.get("pec") or "").strip()
    agent.addresses = (form.get("addresses") or "").strip()

    agent.piva = (form.get("piva") or "").strip()
    agent.sdi = (form.get("sdi") or "").strip()

    agent.facebook = (form.get("facebook") or "").strip()
    agent.instagram = (form.get("instagram") or "").strip()
    agent.linkedin = (form.get("linkedin") or "").strip()
    agent.tiktok = (form.get("tiktok") or "").strip()
    agent.telegram = (form.get("telegram") or "").strip()
    agent.youtube = (form.get("youtube") or "").strip()
    agent.spotify = (form.get("spotify") or "").strip()

    agent.back_media_mode = (form.get("back_media_mode") or "company").strip() or "company"
    agent.photo_pos_x = int(form.get("photo_pos_x") or 50)
    agent.photo_pos_y = int(form.get("photo_pos_y") or 35)
    agent.photo_zoom = str(form.get("photo_zoom") or "1.0")

    agent.orbit_spin = orbit_spin
    agent.avatar_spin = avatar_spin
    agent.logo_spin = logo_spin
    agent.allow_flip = allow_flip

    # uploads P1
    photo = files.get("photo")
    if photo and photo.filename:
        agent.photo_url = save_upload(photo, "images")

    logo = files.get("logo")
    if logo and logo.filename:
        agent.logo_url = save_upload(logo, "images")

    back_media = files.get("back_media")
    if back_media and back_media.filename:
        agent.back_media_url = save_upload(back_media, "images")

    gallery_files = files.getlist("gallery") if hasattr(files, "getlist") else []
    gallery_files = [f for f in gallery_files if f and f.filename]
    if gallery_files:
        gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
        urls = [save_upload(f, "images") for f in gallery_files]
        agent.gallery_urls = "|".join([u for u in urls if u])

    video_files = files.getlist("videos") if hasattr(files, "getlist") else []
    video_files = [f for f in video_files if f and f.filename]
    if video_files:
        video_files = video_files[:MAX_VIDEOS]
        urls = [save_upload(f, "videos") for f in video_files]
        agent.video_urls = "|".join([u for u in urls if u])

    existing = parse_pdf_items(agent.pdf1_url or "")
    out = existing[:] if existing else []
    for i in range(1, MAX_PDFS + 1):
        f = files.get(f"pdf{i}")
        if f and f.filename:
            url = save_upload(f, "pdf")
            name = secure_filename(f.filename) or f"PDF {i}"
            idx = i - 1
            while len(out) <= idx:
                out.append({"name": "", "url": ""})
            out[idx] = {"name": name, "url": url}

    out2 = []
    for item in out:
        if item.get("url"):
            out2.append(f"{item.get('name','Documento')}||{item.get('url')}")
    agent.pdf1_url = "|".join(out2)

    agent.updated_at = dt.datetime.utcnow()


def save_i18n(agent: Agent, form: dict):
    """
    Stores new format:
      i18n_json = {
        "en": {"p1": {...}, "p2": {...}},
        "fr": {"p1": {...}, "p2": {...}},
        ...
      }
    """
    data = {}
    for L in ["en", "fr", "es", "de"]:
        data[L] = {
            "p1": {
                "name": (form.get(f"p1_name_{L}") or "").strip(),
                "company": (form.get(f"p1_company_{L}") or "").strip(),
                "role": (form.get(f"p1_role_{L}") or "").strip(),
                "bio": (form.get(f"p1_bio_{L}") or "").strip(),
                "addresses": (form.get(f"p1_addresses_{L}") or "").strip(),
            },
            "p2": {
                "name": (form.get(f"p2_name_{L}") or "").strip(),
                "company": (form.get(f"p2_company_{L}") or "").strip(),
                "role": (form.get(f"p2_role_{L}") or "").strip(),
                "bio": (form.get(f"p2_bio_{L}") or "").strip(),
                "addresses": (form.get(f"p2_addresses_{L}") or "").strip(),
            }
        }
    agent.i18n_json = json.dumps(data, ensure_ascii=False)


def gen_password(length=10):
    # password facile: lettere+numeri senza simboli
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    import random
    return "".join(random.choice(alphabet) for _ in range(length))


def make_vcard(profile: dict):
    # basic vCard 3.0
    name = (profile.get("name") or "").strip()
    company = (profile.get("company") or "").strip()
    role = (profile.get("role") or "").strip()

    phones = []
    for k in ["phone_mobile", "phone_mobile2", "phone_office"]:
        v = (profile.get(k) or "").strip()
        if v:
            phones.append(v)

    emails = split_csv(profile.get("emails") or "")
    websites = split_csv(profile.get("websites") or "")

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{name};;;;" if name else "N:;;;;;",
        f"FN:{name}" if name else "FN:Pay4You",
    ]
    if company:
        lines.append(f"ORG:{company}")
    if role:
        lines.append(f"TITLE:{role}")

    for p in phones:
        lines.append(f"TEL;TYPE=CELL:{p}")

    for e in emails:
        lines.append(f"EMAIL;TYPE=INTERNET:{e}")

    for w in websites:
        lines.append(f"URL:{w}")

    lines.append("END:VCARD")
    return "\r\n".join(lines)


# ==========================
# STATIC UPLOADS
# ==========================
@app.route("/uploads/<path:filename>")
def serve_uploads(filename):
    return send_from_directory(str(UPLOADS_DIR), filename)


# ==========================
# SHORT ROUTES (fix 404)
# ==========================
@app.get("/login")
def login_alias():
    return redirect(url_for("login"))


@app.get("/dashboard")
def dash_alias():
    return redirect(url_for("dashboard"))


# ==========================
# AUTH
# ==========================
@app.route("/area/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = (request.form.get("password") or "").strip()

        # admin
        if u == "admin" and p == ADMIN_PASSWORD:
            session["role"] = "admin"
            session["slug"] = None
            return redirect(url_for("dashboard"))

        # agent
        s = db()
        ag = s.query(Agent).filter(Agent.username == u).first()
        if ag and check_password_hash(ag.password_hash, p):
            session["role"] = "agent"
            session["slug"] = ag.slug
            return redirect(url_for("dashboard"))

        flash("Credenziali non valide", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/area/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ==========================
# DASHBOARD
# ==========================
@app.route("/area", methods=["GET"])
def dashboard():
    r = require_login()
    if r:
        return r

    s = db()

    if is_admin():
        agents = s.query(Agent).all()
        # alfabetico (nome -> slug)
        agents = sorted(agents, key=lambda a: ((a.name or "").lower(), (a.slug or "").lower()))
        return render_template("admin_list.html", agents=agents, is_admin=True, agent=None)

    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        session.clear()
        return redirect(url_for("login"))

    return render_template("admin_list.html", agents=[ag], is_admin=False, agent=ag)


# ==========================
# ADMIN: NEW / EDIT
# ==========================
@app.route("/area/new", methods=["GET", "POST"])
def new_agent():
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    if request.method == "POST":
        first = (request.form.get("first_name") or "").strip()
        last = (request.form.get("last_name") or "").strip()
        if not first:
            flash("Nome obbligatorio", "error")
            return redirect(url_for("new_agent"))

        name = first + ((" " + last) if last else "")

        slug_in = (request.form.get("slug") or "").strip()
        slug = slugify(slug_in) if slug_in else slugify(name)
        if not slug:
            flash("Slug non valido", "error")
            return redirect(url_for("new_agent"))

        password = (request.form.get("password") or "").strip()
        if not password or len(password) < 4:
            flash("Password troppo corta", "error")
            return redirect(url_for("new_agent"))

        s = db()
        if s.query(Agent).filter(Agent.slug == slug).first():
            flash("Slug già esistente", "error")
            return redirect(url_for("new_agent"))

        ag = Agent(
            slug=slug,
            username=slug,
            password_hash=generate_password_hash(password),
            name=name,
            created_at=dt.datetime.utcnow(),
            updated_at=dt.datetime.utcnow(),
            p2_enabled=0,
            p2_json="{}",
            i18n_json="{}",
        )
        s.add(ag)
        s.commit()

        flash("Card creata!", "ok")
        return redirect(url_for("edit_agent", slug=slug, profile="p1"))

    return render_template("agent_form.html", agent=None, profile="p1", i18n_data={}, is_admin=True)


@app.get("/area/edit/<slug>")
def edit_agent(slug):
    # default p1
    return redirect(url_for("edit_agent_profile", slug=slug, profile="p1"))


@app.route("/area/edit/<slug>/<profile>", methods=["GET", "POST"])
def edit_agent_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    profile = (profile or "p1").lower()
    if profile not in ["p1", "p2"]:
        abort(404)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if profile == "p2" and int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("edit_agent_profile", slug=slug, profile="p1"))

    if request.method == "POST":
        # save profile data (includes uploads + media)
        set_profile_from_form(ag, profile, request.form, request.files)

        # save translations (only on admin, both profiles in same form)
        save_i18n(ag, request.form)

        s.commit()
        flash("Salvato!", "ok")
        return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))

    # load i18n
    i18n_data = get_i18n(ag)

    # current profile data for form
    p = get_profile_dict(ag, profile)

    # current previews (profile specific)
    gallery = [x for x in (p.get("gallery_urls", "") or "").split("|") if x.strip()]
    videos = [x for x in (p.get("video_urls", "") or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(p.get("pdf1_url", "") or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        profile=profile,
        p=p,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        i18n_data=i18n_data,
        is_admin=True
    )


# ==========================
# AGENT SELF EDIT
# ==========================
@app.get("/area/me/edit")
def me_edit():
    return redirect(url_for("me_edit_profile", profile="p1"))


@app.route("/area/me/<profile>", methods=["GET", "POST"])
def me_edit_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        return redirect(url_for("dashboard"))

    profile = (profile or "p1").lower()
    if profile not in ["p1", "p2"]:
        abort(404)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if profile == "p2" and int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        set_profile_from_form(ag, profile, request.form, request.files)
        # agent can save translations too (you asked: language also for P2)
        save_i18n(ag, request.form)

        s.commit()
        flash("Salvato!", "ok")
        return redirect(url_for("me_edit_profile", profile=profile))

    i18n_data = get_i18n(ag)
    p = get_profile_dict(ag, profile)
    gallery = [x for x in (p.get("gallery_urls", "") or "").split("|") if x.strip()]
    videos = [x for x in (p.get("video_urls", "") or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(p.get("pdf1_url", "") or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        profile=profile,
        p=p,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        i18n_data=i18n_data,
        is_admin=False
    )


@app.post("/area/me/activate-p2")
def me_activate_p2():
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    # ✅ must be EMPTY
    ag.p2_enabled = 1
    ag.p2_json = "{}"

    ag.p2_photo_url = ""
    ag.p2_logo_url = ""
    ag.p2_back_media_mode = "company"
    ag.p2_back_media_url = ""
    ag.p2_photo_pos_x = 50
    ag.p2_photo_pos_y = 35
    ag.p2_photo_zoom = "1.0"
    ag.p2_orbit_spin = 0
    ag.p2_avatar_spin = 0
    ag.p2_logo_spin = 0
    ag.p2_allow_flip = 0
    ag.p2_gallery_urls = ""
    ag.p2_video_urls = ""
    ag.p2_pdf1_url = ""

    ag.updated_at = dt.datetime.utcnow()
    s.commit()

    flash("Profilo 2 attivato: vuoto e pronto da compilare.", "ok")
    return redirect(url_for("me_edit_profile", profile="p2"))


@app.post("/area/me/deactivate-p2")
def me_deactivate_p2():
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    ag.p2_enabled = 0
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Profilo 2 disattivato.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# ADMIN: TOGGLE P2
# ==========================
@app.post("/area/admin/<slug>/activate-p2")
def admin_activate_p2(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    ag.p2_enabled = 1

    # ✅ empty
    ag.p2_json = "{}"
    ag.p2_photo_url = ""
    ag.p2_logo_url = ""
    ag.p2_back_media_mode = "company"
    ag.p2_back_media_url = ""
    ag.p2_photo_pos_x = 50
    ag.p2_photo_pos_y = 35
    ag.p2_photo_zoom = "1.0"
    ag.p2_orbit_spin = 0
    ag.p2_avatar_spin = 0
    ag.p2_logo_spin = 0
    ag.p2_allow_flip = 0
    ag.p2_gallery_urls = ""
    ag.p2_video_urls = ""
    ag.p2_pdf1_url = ""

    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P2 attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))


@app.post("/area/admin/<slug>/deactivate-p2")
def admin_deactivate_p2(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    ag.p2_enabled = 0
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P2 disattivato.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# ADMIN: REGENERATE PASSWORD
# ==========================
@app.post("/area/admin/<slug>/regen-pass")
def admin_regen_pass(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    newp = gen_password(10)
    ag.password_hash = generate_password_hash(newp)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()

    # IMPORTANT: in dashboard we show it in a modal (client-side). Here we flash it.
    flash(f"Nuova password generata per {ag.slug}: {newp}", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# ADMIN: DELETE AGENT
# ==========================
@app.post("/area/admin/<slug>/delete")
def admin_delete_agent(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    s.delete(ag)
    s.commit()
    flash("Card eliminata definitivamente.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# MEDIA DELETE (single item)
# ==========================
@app.post("/area/media/delete/<slug>")
def delete_media(slug):
    r = require_login()
    if r:
        return r

    t = (request.form.get("type") or "").strip()       # gallery | video | pdf
    idx = int(request.form.get("idx") or -1)
    profile = (request.form.get("profile") or "p1").strip().lower()
    target = (request.form.get("target") or "edit").strip()  # edit/dashboard

    if profile not in ["p1", "p2"]:
        abort(400)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    # Auth: agent can only delete own
    if not is_admin() and ag.slug != session.get("slug"):
        abort(403)

    p = get_profile_dict(ag, profile)

    if t == "gallery":
        items = [x for x in (p.get("gallery_urls", "") or "").split("|") if x.strip()]
        if 0 <= idx < len(items):
            items.pop(idx)
            if profile == "p1":
                ag.gallery_urls = "|".join(items)
            else:
                ag.p2_gallery_urls = "|".join(items)

    elif t == "video":
        items = [x for x in (p.get("video_urls", "") or "").split("|") if x.strip()]
        if 0 <= idx < len(items):
            items.pop(idx)
            if profile == "p1":
                ag.video_urls = "|".join(items)
            else:
                ag.p2_video_urls = "|".join(items)

    elif t == "pdf":
        items = parse_pdf_items(p.get("pdf1_url", "") or "")
        if 0 <= idx < len(items):
            items.pop(idx)
            new_str = "|".join([f"{x['name']}||{x['url']}" for x in items])
            if profile == "p1":
                ag.pdf1_url = new_str
            else:
                ag.p2_pdf1_url = new_str

    else:
        abort(400)

    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Eliminato.", "ok")

    # redirect
    if target == "dashboard":
        return redirect(url_for("dashboard"))

    # edit page
    if is_admin():
        return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))
    return redirect(url_for("me_edit_profile", profile=profile))


# ==========================
# QR IMAGE (Dashboard modal)
# ==========================
@app.get("/qr/<slug>")
def qr_png(slug):
    # QR of card URL (p1/p2 + lang auto not forced)
    p = (request.args.get("p") or "").strip().lower()
    profile = "p2" if p == "p2" else "p1"
    base = public_base_url()
    url = f"{base}/{slug}"
    if profile == "p2":
        url = f"{base}/{slug}?p=p2"

    img = qrcode.make(url)
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


# ==========================
# VCF (fix 404)
# ==========================
@app.get("/<slug>.vcf")
def vcf(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    p = (request.args.get("p") or "").strip().lower()
    profile = "p2" if (p == "p2" and int(ag.p2_enabled or 0) == 1) else "p1"
    data = get_profile_dict(ag, profile)

    content = make_vcard(data)
    filename = f"{slug}-{profile}.vcf"
    return Response(
        content,
        mimetype="text/vcard; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ==========================
# CARD PUBLIC
# ==========================
@app.route("/<slug>")
def card(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    # profile key
    p_key = (request.args.get("p") or "").strip().lower()
    p2_enabled = int(ag.p2_enabled or 0) == 1
    use_p2 = (p_key == "p2" and p2_enabled)
    profile = "p2" if use_p2 else "p1"

    # language: auto from phone if not provided
    lang = infer_lang_from_request(default="it")

    # i18n
    i18n = get_i18n(ag)
    tr = _i18n_get_profile_block(i18n, lang, profile)

    data = get_profile_dict(ag, profile)

    # apply translations to shown fields if present
    for key in ["name", "company", "role", "bio", "addresses"]:
        v = (tr.get(key) or "").strip() if isinstance(tr, dict) else ""
        if v:
            data[key] = v

    # Prepare derived lists
    emails = split_csv(data.get("emails", ""))
    websites = [normalize_url(w) for w in split_csv(data.get("websites", ""))]
    addresses = split_lines(data.get("addresses", ""))

    # maps
    addr_objs = []
    for a in addresses:
        q = a.replace(" ", "+")
        addr_objs.append({"text": a, "maps": f"https://www.google.com/maps/search/?api=1&query={q}"})

    mobiles = []
    m1 = (data.get("phone_mobile", "") or "").strip()
    m2 = (data.get("phone_mobile2", "") or "").strip()
    if m1:
        mobiles.append(m1)
    if m2:
        mobiles.append(m2)

    office_value = (data.get("phone_office", "") or "").strip()
    pec_email = (data.get("pec", "") or "").strip()

    # media lists
    gallery = [x for x in (data.get("gallery_urls", "") or "").split("|") if x.strip()]
    videos = [x for x in (data.get("video_urls", "") or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(data.get("pdf1_url", "") or "")

    # whatsapp link
    wa_link = (data.get("whatsapp", "") or "").strip()
    if wa_link and wa_link.startswith("+"):
        wa_link = "https://wa.me/" + re.sub(r"\D+", "", wa_link)
    elif wa_link:
        wa_link = normalize_url(wa_link)

    base_url = public_base_url()
    qr_url = f"{base_url}/{ag.slug}"
    if use_p2:
        qr_url = f"{base_url}/{ag.slug}?p=p2"

    # t_func
    def t_func(key):
        it = {
            "actions": "Azioni",
            "save_contact": "Salva contatto",
            "whatsapp": "WhatsApp",
            "scan_qr": "QR",
            "contacts": "Contatti",
            "mobile_phone": "Cellulare",
            "office_phone": "Ufficio",
            "open_website": "Sito",
            "open_maps": "Apri Maps",
            "data": "Dati",
            "vat": "P.IVA",
            "sdi": "SDI",
            "gallery": "Foto",
            "videos": "Video",
            "documents": "Documenti",
            "close": "Chiudi",
        }
        en = {
            "actions": "Actions",
            "save_contact": "Save contact",
            "whatsapp": "WhatsApp",
            "scan_qr": "QR",
            "contacts": "Contacts",
            "mobile_phone": "Mobile",
            "office_phone": "Office",
            "open_website": "Website",
            "open_maps": "Open Maps",
            "data": "Data",
            "vat": "VAT",
            "sdi": "SDI",
            "gallery": "Photos",
            "videos": "Videos",
            "documents": "Documents",
            "close": "Close",
        }
        fr = {
            "actions": "Actions",
            "save_contact": "Enregistrer",
            "whatsapp": "WhatsApp",
            "scan_qr": "QR",
            "contacts": "Contacts",
            "mobile_phone": "Mobile",
            "office_phone": "Bureau",
            "open_website": "Site",
            "open_maps": "Ouvrir Maps",
            "data": "Données",
            "vat": "TVA",
            "sdi": "SDI",
            "gallery": "Photos",
            "videos": "Vidéos",
            "documents": "Documents",
            "close": "Fermer",
        }
        es = {
            "actions": "Acciones",
            "save_contact": "Guardar",
            "whatsapp": "WhatsApp",
            "scan_qr": "QR",
            "contacts": "Contactos",
            "mobile_phone": "Móvil",
            "office_phone": "Oficina",
            "open_website": "Sitio",
            "open_maps": "Abrir Maps",
            "data": "Datos",
            "vat": "IVA",
            "sdi": "SDI",
            "gallery": "Fotos",
            "videos": "Vídeos",
            "documents": "Documentos",
            "close": "Cerrar",
        }
        de = {
            "actions": "Aktionen",
            "save_contact": "Speichern",
            "whatsapp": "WhatsApp",
            "scan_qr": "QR",
            "contacts": "Kontakte",
            "mobile_phone": "Mobil",
            "office_phone": "Büro",
            "open_website": "Webseite",
            "open_maps": "Maps öffnen",
            "data": "Daten",
            "vat": "USt-IdNr.",
            "sdi": "SDI",
            "gallery": "Fotos",
            "videos": "Videos",
            "documents": "Dokumente",
            "close": "Schließen",
        }
        packs = {"it": it, "en": en, "fr": fr, "es": es, "de": de}
        return (packs.get(lang, it)).get(key, it.get(key, key))

    # build ag object for template
    class Obj(dict):
        __getattr__ = dict.get

    ag_view = Obj({
        "slug": ag.slug,

        # media/effects/crop
        "photo_url": data.get("photo_url", ""),
        "logo_url": data.get("logo_url", ""),
        "back_media_mode": data.get("back_media_mode", "company"),
        "back_media_url": data.get("back_media_url", ""),

        "photo_pos_x": int(data.get("photo_pos_x", 50) or 50),
        "photo_pos_y": int(data.get("photo_pos_y", 35) or 35),
        "photo_zoom": data.get("photo_zoom", "1.0"),

        "orbit_spin": int(data.get("orbit_spin", 0) or 0),
        "avatar_spin": int(data.get("avatar_spin", 0) or 0),
        "logo_spin": int(data.get("logo_spin", 0) or 0),
        "allow_flip": int(data.get("allow_flip", 0) or 0),

        # fields
        "name": data.get("name", ""),
        "company": data.get("company", ""),
        "role": data.get("role", ""),
        "bio": data.get("bio", ""),
        "piva": data.get("piva", ""),
        "sdi": data.get("sdi", ""),

        "facebook": data.get("facebook", ""),
        "instagram": data.get("instagram", ""),
        "linkedin": data.get("linkedin", ""),
        "tiktok": data.get("tiktok", ""),
        "telegram": data.get("telegram", ""),
        "youtube": data.get("youtube", ""),
        "spotify": data.get("spotify", ""),
    })

    return render_template(
        "card.html",
        ag=ag_view,
        lang=lang,
        base_url=base_url,
        p_key=("p2" if use_p2 else ""),
        p2_enabled=p2_enabled,
        wa_link=wa_link,
        qr_url=qr_url,
        emails=emails,
        websites=websites,
        addresses=addr_objs,
        mobiles=mobiles,
        office_value=office_value,
        pec_email=pec_email,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        t_func=t_func
    )


# ==========================
# MAIN
# ==========================
@app.route("/")
def home():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
