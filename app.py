import os
import re
import json
import uuid
import datetime as dt
from pathlib import Path
from io import BytesIO

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, abort, flash, send_from_directory, Response
)

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import qrcode
except Exception:
    qrcode = None


# ==========================
# CONFIG
# ==========================
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////var/data/pay4you.db").strip()
PERSIST_UPLOADS_DIR = os.getenv("PERSIST_UPLOADS_DIR", "/var/data/uploads").strip()

# LIMITI
MAX_GALLERY_IMAGES = 15
MAX_VIDEOS = 8
MAX_PDFS = 10

MAX_IMAGE_MB = 5
MAX_VIDEO_MB = 25
MAX_PDF_MB = 10

UPLOADS_DIR = Path(PERSIST_UPLOADS_DIR)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

SUBDIR_IMG = UPLOADS_DIR / "images"
SUBDIR_VID = UPLOADS_DIR / "videos"
SUBDIR_PDF = UPLOADS_DIR / "pdf"
for d in (SUBDIR_IMG, SUBDIR_VID, SUBDIR_PDF):
    d.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = APP_SECRET

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

    slug = Column(String(120), unique=True, nullable=False, index=True)
    username = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)

    # ===== P1 DATA =====
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

    # ===== P1 VISUAL =====
    photo_url = Column(String(255), default="")
    logo_url = Column(String(255), default="")
    back_media_mode = Column(String(30), default="company")  # company|custom
    back_media_url = Column(String(255), default="")

    photo_pos_x = Column(Integer, default=50)
    photo_pos_y = Column(Integer, default=35)
    photo_zoom = Column(String(20), default="1.0")

    orbit_spin = Column(Integer, default=0)
    avatar_spin = Column(Integer, default=0)
    logo_spin = Column(Integer, default=0)
    allow_flip = Column(Integer, default=0)

    # ===== P1 MEDIA =====
    gallery_urls = Column(Text, default="")   # url|url|...
    video_urls = Column(Text, default="")     # url|url|...
    pdf1_url = Column(Text, default="")       # name||url|name||url...

    # ===== P1 I18N =====
    i18n_json = Column(Text, default="{}")

    # ===== P2 =====
    p2_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")
    p2_i18n_json = Column(Text, default="{}")

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

    # ===== P3 =====
    p3_enabled = Column(Integer, default=0)
    p3_json = Column(Text, default="{}")
    p3_i18n_json = Column(Text, default="{}")

    p3_photo_url = Column(String(255), default="")
    p3_logo_url = Column(String(255), default="")
    p3_back_media_mode = Column(String(30), default="company")
    p3_back_media_url = Column(String(255), default="")

    p3_photo_pos_x = Column(Integer, default=50)
    p3_photo_pos_y = Column(Integer, default=35)
    p3_photo_zoom = Column(String(20), default="1.0")

    p3_orbit_spin = Column(Integer, default=0)
    p3_avatar_spin = Column(Integer, default=0)
    p3_logo_spin = Column(Integer, default=0)
    p3_allow_flip = Column(Integer, default=0)

    p3_gallery_urls = Column(Text, default="")
    p3_video_urls = Column(Text, default="")
    p3_pdf1_url = Column(Text, default="")

    created_at = Column(DateTime, default=lambda: dt.datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: dt.datetime.utcnow())


# ==========================
# DB INIT + MIGRATION (SQLITE)
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

        # colonne nuove (se mancano)
        add_col("created_at", "DATETIME")
        add_col("updated_at", "DATETIME")

        # P2 / P3 base
        add_col("p2_enabled", "INTEGER")
        add_col("p2_json", "TEXT")
        add_col("p2_i18n_json", "TEXT")

        add_col("p3_enabled", "INTEGER")
        add_col("p3_json", "TEXT")
        add_col("p3_i18n_json", "TEXT")

        # VISUAL P2
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

        # MEDIA P2
        add_col("p2_gallery_urls", "TEXT")
        add_col("p2_video_urls", "TEXT")
        add_col("p2_pdf1_url", "TEXT")

        # VISUAL P3
        add_col("p3_photo_url", "TEXT")
        add_col("p3_logo_url", "TEXT")
        add_col("p3_back_media_mode", "TEXT")
        add_col("p3_back_media_url", "TEXT")
        add_col("p3_photo_pos_x", "INTEGER")
        add_col("p3_photo_pos_y", "INTEGER")
        add_col("p3_photo_zoom", "TEXT")
        add_col("p3_orbit_spin", "INTEGER")
        add_col("p3_avatar_spin", "INTEGER")
        add_col("p3_logo_spin", "INTEGER")
        add_col("p3_allow_flip", "INTEGER")

        # MEDIA P3
        add_col("p3_gallery_urls", "TEXT")
        add_col("p3_video_urls", "TEXT")
        add_col("p3_pdf1_url", "TEXT")

        # default safe
        now = dt.datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        conn.exec_driver_sql("UPDATE agents SET created_at = COALESCE(created_at, :now)", {"now": now})
        conn.exec_driver_sql("UPDATE agents SET updated_at = COALESCE(updated_at, :now)", {"now": now})

        conn.exec_driver_sql("UPDATE agents SET p2_enabled = COALESCE(p2_enabled, 0)")
        conn.exec_driver_sql("UPDATE agents SET p3_enabled = COALESCE(p3_enabled, 0)")

        conn.exec_driver_sql("UPDATE agents SET p2_json = COALESCE(p2_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET p3_json = COALESCE(p3_json, '{}')")

        conn.exec_driver_sql("UPDATE agents SET p2_i18n_json = COALESCE(p2_i18n_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET p3_i18n_json = COALESCE(p3_i18n_json, '{}')")

        # zoom defaults
        conn.exec_driver_sql("UPDATE agents SET photo_zoom = COALESCE(photo_zoom, '1.0')")
        conn.exec_driver_sql("UPDATE agents SET p2_photo_zoom = COALESCE(p2_photo_zoom, '1.0')")
        conn.exec_driver_sql("UPDATE agents SET p3_photo_zoom = COALESCE(p3_photo_zoom, '1.0')")

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

def uploads_url(rel_path: str) -> str:
    rel_path = rel_path.lstrip("/")
    return f"/uploads/{rel_path}"

def profile_prefix(profile: str) -> str:
    p = (profile or "p1").strip().lower()
    if p not in ("p1", "p2", "p3"):
        return "p1"
    return p

def enabled_for_profile(agent: Agent, profile: str) -> bool:
    p = profile_prefix(profile)
    if p == "p1":
        return True
    if p == "p2":
        return int(agent.p2_enabled or 0) == 1
    if p == "p3":
        return int(agent.p3_enabled or 0) == 1
    return False

def file_size_bytes(file_storage) -> int:
    try:
        stream = file_storage.stream
        pos = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(pos, os.SEEK_SET)
        return int(size)
    except Exception:
        return 0

def enforce_size(kind: str, file_storage):
    size = file_size_bytes(file_storage)
    if size <= 0:
        return True, ""
    mb = size / (1024 * 1024)

    if kind == "images" and mb > MAX_IMAGE_MB:
        return False, f"Immagine troppo grande ({mb:.1f} MB). Max {MAX_IMAGE_MB} MB."
    if kind == "videos" and mb > MAX_VIDEO_MB:
        return False, f"Video troppo grande ({mb:.1f} MB). Max {MAX_VIDEO_MB} MB."
    if kind == "pdf" and mb > MAX_PDF_MB:
        return False, f"PDF troppo grande ({mb:.1f} MB). Max {MAX_PDF_MB} MB."
    return True, ""

def save_upload(file_storage, kind: str):
    if not file_storage or not file_storage.filename:
        return ""

    ok, err = enforce_size(kind, file_storage)
    if not ok:
        raise ValueError(err)

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

def parse_pdf_items(pdf_str: str):
    items = []
    if not pdf_str:
        return items
    for chunk in pdf_str.split("|"):
        if not chunk.strip():
            continue
        if "||" in chunk:
            name, url = chunk.split("||", 1)
            items.append({"name": name.strip() or "Documento", "url": url.strip()})
        else:
            items.append({"name": chunk.strip(), "url": chunk.strip()})
    return items

def pdf_items_to_str(items):
    out = []
    for it in items[:MAX_PDFS]:
        url = (it.get("url") or "").strip()
        if not url:
            continue
        name = (it.get("name") or "Documento").strip()
        out.append(f"{name}||{url}")
    return "|".join(out)

def _new_password(length=10):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    import random
    return "".join(random.choice(alphabet) for _ in range(length))

def load_json(textval: str) -> dict:
    try:
        d = json.loads(textval or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def set_json(agent: Agent, field: str, data: dict):
    setattr(agent, field, json.dumps(data or {}, ensure_ascii=False))

def get_profile_data(agent: Agent, profile: str) -> dict:
    p = profile_prefix(profile)
    if p == "p1":
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
        }
    if p == "p2":
        return load_json(agent.p2_json)
    if p == "p3":
        return load_json(agent.p3_json)
    return {}

def save_profile_data(agent: Agent, profile: str, form: dict):
    p = profile_prefix(profile)

    # effetti (mutua esclusione)
    avatar_spin = 1 if form.get("avatar_spin") == "on" else 0
    allow_flip = 1 if form.get("allow_flip") == "on" else 0
    if avatar_spin == 1:
        allow_flip = 0
    if allow_flip == 1:
        avatar_spin = 0
    orbit_spin = 1 if form.get("orbit_spin") == "on" else 0
    logo_spin = 1 if form.get("logo_spin") == "on" else 0

    def safe_int(v, d):
        try:
            return int(v)
        except Exception:
            return d

    z = (form.get("photo_zoom") or "1.0").strip()
    try:
        float(z)
    except Exception:
        z = "1.0"

    back_mode = (form.get("back_media_mode") or "company").strip()
    if back_mode not in ("company", "custom"):
        back_mode = "company"

    data = {}
    for k in [
        "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office", "whatsapp",
        "emails", "websites", "pec", "addresses",
        "piva", "sdi",
        "facebook", "instagram", "linkedin", "tiktok", "telegram", "youtube", "spotify"
    ]:
        data[k] = (form.get(k) or "").strip()

    if p == "p1":
        agent.name = data["name"]
        agent.company = data["company"]
        agent.role = data["role"]
        agent.bio = data["bio"]

        agent.phone_mobile = data["phone_mobile"]
        agent.phone_mobile2 = data["phone_mobile2"]
        agent.phone_office = data["phone_office"]
        agent.whatsapp = data["whatsapp"]
        agent.emails = data["emails"]
        agent.websites = data["websites"]
        agent.pec = data["pec"]
        agent.addresses = data["addresses"]

        agent.piva = data["piva"]
        agent.sdi = data["sdi"]

        agent.facebook = data["facebook"]
        agent.instagram = data["instagram"]
        agent.linkedin = data["linkedin"]
        agent.tiktok = data["tiktok"]
        agent.telegram = data["telegram"]
        agent.youtube = data["youtube"]
        agent.spotify = data["spotify"]

        agent.back_media_mode = back_mode
        agent.photo_pos_x = safe_int(form.get("photo_pos_x"), 50)
        agent.photo_pos_y = safe_int(form.get("photo_pos_y"), 35)
        agent.photo_zoom = z

        agent.orbit_spin = orbit_spin
        agent.avatar_spin = avatar_spin
        agent.logo_spin = logo_spin
        agent.allow_flip = allow_flip
    else:
        # P2/P3: JSON dati
        if p == "p2":
            set_json(agent, "p2_json", data)
            agent.p2_back_media_mode = back_mode
            agent.p2_photo_pos_x = safe_int(form.get("photo_pos_x"), 50)
            agent.p2_photo_pos_y = safe_int(form.get("photo_pos_y"), 35)
            agent.p2_photo_zoom = z
            agent.p2_orbit_spin = orbit_spin
            agent.p2_avatar_spin = avatar_spin
            agent.p2_logo_spin = logo_spin
            agent.p2_allow_flip = allow_flip
        if p == "p3":
            set_json(agent, "p3_json", data)
            agent.p3_back_media_mode = back_mode
            agent.p3_photo_pos_x = safe_int(form.get("photo_pos_x"), 50)
            agent.p3_photo_pos_y = safe_int(form.get("photo_pos_y"), 35)
            agent.p3_photo_zoom = z
            agent.p3_orbit_spin = orbit_spin
            agent.p3_avatar_spin = avatar_spin
            agent.p3_logo_spin = logo_spin
            agent.p3_allow_flip = allow_flip

    agent.updated_at = dt.datetime.utcnow()

def load_i18n_profile(agent: Agent, profile: str) -> dict:
    p = profile_prefix(profile)
    if p == "p1":
        return load_json(agent.i18n_json)
    if p == "p2":
        return load_json(agent.p2_i18n_json)
    if p == "p3":
        return load_json(agent.p3_i18n_json)
    return {}

def save_i18n_profile(agent: Agent, profile: str, form: dict):
    p = profile_prefix(profile)
    data = {}
    for L in ["en", "fr", "es", "de"]:
        data[L] = {
            "name": (form.get(f"name_{L}") or "").strip(),
            "company": (form.get(f"company_{L}") or "").strip(),
            "role": (form.get(f"role_{L}") or "").strip(),
            "bio": (form.get(f"bio_{L}") or "").strip(),
            "addresses": (form.get(f"addresses_{L}") or "").strip(),
        }
    if p == "p1":
        agent.i18n_json = json.dumps(data, ensure_ascii=False)
    elif p == "p2":
        agent.p2_i18n_json = json.dumps(data, ensure_ascii=False)
    elif p == "p3":
        agent.p3_i18n_json = json.dumps(data, ensure_ascii=False)

def get_profile_visual(agent: Agent, profile: str) -> dict:
    p = profile_prefix(profile)
    if p == "p1":
        return {
            "photo_url": agent.photo_url or "",
            "logo_url": agent.logo_url or "",
            "back_media_mode": agent.back_media_mode or "company",
            "back_media_url": agent.back_media_url or "",
            "photo_pos_x": int(agent.photo_pos_x or 50),
            "photo_pos_y": int(agent.photo_pos_y or 35),
            "photo_zoom": (agent.photo_zoom or "1.0"),
            "orbit_spin": int(agent.orbit_spin or 0),
            "avatar_spin": int(agent.avatar_spin or 0),
            "logo_spin": int(agent.logo_spin or 0),
            "allow_flip": int(agent.allow_flip or 0),
        }
    if p == "p2":
        return {
            "photo_url": agent.p2_photo_url or "",
            "logo_url": agent.p2_logo_url or "",
            "back_media_mode": agent.p2_back_media_mode or "company",
            "back_media_url": agent.p2_back_media_url or "",
            "photo_pos_x": int(agent.p2_photo_pos_x or 50),
            "photo_pos_y": int(agent.p2_photo_pos_y or 35),
            "photo_zoom": (agent.p2_photo_zoom or "1.0"),
            "orbit_spin": int(agent.p2_orbit_spin or 0),
            "avatar_spin": int(agent.p2_avatar_spin or 0),
            "logo_spin": int(agent.p2_logo_spin or 0),
            "allow_flip": int(agent.p2_allow_flip or 0),
        }
    if p == "p3":
        return {
            "photo_url": agent.p3_photo_url or "",
            "logo_url": agent.p3_logo_url or "",
            "back_media_mode": agent.p3_back_media_mode or "company",
            "back_media_url": agent.p3_back_media_url or "",
            "photo_pos_x": int(agent.p3_photo_pos_x or 50),
            "photo_pos_y": int(agent.p3_photo_pos_y or 35),
            "photo_zoom": (agent.p3_photo_zoom or "1.0"),
            "orbit_spin": int(agent.p3_orbit_spin or 0),
            "avatar_spin": int(agent.p3_avatar_spin or 0),
            "logo_spin": int(agent.p3_logo_spin or 0),
            "allow_flip": int(agent.p3_allow_flip or 0),
        }
    return {}

def get_media(agent: Agent, profile: str):
    p = profile_prefix(profile)
    if p == "p1":
        gallery = [x for x in (agent.gallery_urls or "").split("|") if x.strip()]
        videos = [x for x in (agent.video_urls or "").split("|") if x.strip()]
        pdfs = parse_pdf_items(agent.pdf1_url or "")
        return gallery[:MAX_GALLERY_IMAGES], videos[:MAX_VIDEOS], pdfs[:MAX_PDFS]
    if p == "p2":
        gallery = [x for x in (agent.p2_gallery_urls or "").split("|") if x.strip()]
        videos = [x for x in (agent.p2_video_urls or "").split("|") if x.strip()]
        pdfs = parse_pdf_items(agent.p2_pdf1_url or "")
        return gallery[:MAX_GALLERY_IMAGES], videos[:MAX_VIDEOS], pdfs[:MAX_PDFS]
    if p == "p3":
        gallery = [x for x in (agent.p3_gallery_urls or "").split("|") if x.strip()]
        videos = [x for x in (agent.p3_video_urls or "").split("|") if x.strip()]
        pdfs = parse_pdf_items(agent.p3_pdf1_url or "")
        return gallery[:MAX_GALLERY_IMAGES], videos[:MAX_VIDEOS], pdfs[:MAX_PDFS]
    return [], [], []

def set_media_strings(agent: Agent, profile: str, gallery: list, videos: list, pdfs_items: list):
    p = profile_prefix(profile)
    g_str = "|".join(gallery[:MAX_GALLERY_IMAGES])
    v_str = "|".join(videos[:MAX_VIDEOS])
    p_str = pdf_items_to_str(pdfs_items[:MAX_PDFS])

    if p == "p1":
        agent.gallery_urls = g_str
        agent.video_urls = v_str
        agent.pdf1_url = p_str
    elif p == "p2":
        agent.p2_gallery_urls = g_str
        agent.p2_video_urls = v_str
        agent.p2_pdf1_url = p_str
    elif p == "p3":
        agent.p3_gallery_urls = g_str
        agent.p3_video_urls = v_str
        agent.p3_pdf1_url = p_str

def compact_limits(agent: Agent, profile: str) -> bool:
    """Se in passato è esploso (es: 100 pdf), taglia e salva."""
    changed = False
    gallery, videos, pdfs = get_media(agent, profile)

    if len(gallery) > MAX_GALLERY_IMAGES:
        gallery = gallery[:MAX_GALLERY_IMAGES]
        changed = True
    if len(videos) > MAX_VIDEOS:
        videos = videos[:MAX_VIDEOS]
        changed = True
    if len(pdfs) > MAX_PDFS:
        pdfs = pdfs[:MAX_PDFS]
        changed = True

    if changed:
        set_media_strings(agent, profile, gallery, videos, pdfs)
        agent.updated_at = dt.datetime.utcnow()
    return changed

def handle_media_uploads(agent: Agent, profile: str):
    p = profile_prefix(profile)

    # ===== FOTO PROFILO =====
    photo = request.files.get("photo")
    if photo and photo.filename:
        url = save_upload(photo, "images")
        if p == "p1":
            agent.photo_url = url
        elif p == "p2":
            agent.p2_photo_url = url
        elif p == "p3":
            agent.p3_photo_url = url

    # ===== LOGO =====
    logo = request.files.get("logo")
    if logo and logo.filename:
        url = save_upload(logo, "images")
        if p == "p1":
            agent.logo_url = url
        elif p == "p2":
            agent.p2_logo_url = url
        elif p == "p3":
            agent.p3_logo_url = url

    # ===== BACKGROUND =====
    back_media = request.files.get("back_media")
    if back_media and back_media.filename:
        url = save_upload(back_media, "images")
        if p == "p1":
            agent.back_media_url = url
        elif p == "p2":
            agent.p2_back_media_url = url
        elif p == "p3":
            agent.p3_back_media_url = url

    # ===== MEDIA LISTE =====
    gallery, videos, pdfs = get_media(agent, profile)

    # galleria
    gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
    if gallery_files:
        urls = [save_upload(f, "images") for f in gallery_files][:MAX_GALLERY_IMAGES]
        urls = [u for u in urls if u]
        gallery = (gallery + urls)[:MAX_GALLERY_IMAGES]

    # video
    video_files = [f for f in request.files.getlist("videos") if f and f.filename]
    if video_files:
        urls = [save_upload(f, "videos") for f in video_files][:MAX_VIDEOS]
        urls = [u for u in urls if u]
        videos = (videos + urls)[:MAX_VIDEOS]

    # pdf slots
    existing_pdf = pdfs[:] if pdfs else []
    out = existing_pdf[:]
    for i in range(1, MAX_PDFS + 1):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            url = save_upload(f, "pdf")
            name = secure_filename(f.filename) or f"PDF {i}"
            idx = i - 1
            while len(out) <= idx:
                out.append({"name": "", "url": ""})
            out[idx] = {"name": name, "url": url}

    # salva tutto
    set_media_strings(agent, profile, gallery, videos, out)
    agent.updated_at = dt.datetime.utcnow()


def reset_profile(agent: Agent, profile: str):
    """Quando attivi P2/P3 deve essere tutto vuoto e nuovo."""
    p = profile_prefix(profile)
    if p == "p2":
        agent.p2_json = "{}"
        agent.p2_i18n_json = "{}"
        agent.p2_photo_url = ""
        agent.p2_logo_url = ""
        agent.p2_back_media_mode = "company"
        agent.p2_back_media_url = ""
        agent.p2_photo_pos_x = 50
        agent.p2_photo_pos_y = 35
        agent.p2_photo_zoom = "1.0"
        agent.p2_orbit_spin = 0
        agent.p2_avatar_spin = 0
        agent.p2_logo_spin = 0
        agent.p2_allow_flip = 0
        agent.p2_gallery_urls = ""
        agent.p2_video_urls = ""
        agent.p2_pdf1_url = ""
    if p == "p3":
        agent.p3_json = "{}"
        agent.p3_i18n_json = "{}"
        agent.p3_photo_url = ""
        agent.p3_logo_url = ""
        agent.p3_back_media_mode = "company"
        agent.p3_back_media_url = ""
        agent.p3_photo_pos_x = 50
        agent.p3_photo_pos_y = 35
        agent.p3_photo_zoom = "1.0"
        agent.p3_orbit_spin = 0
        agent.p3_avatar_spin = 0
        agent.p3_logo_spin = 0
        agent.p3_allow_flip = 0
        agent.p3_gallery_urls = ""
        agent.p3_video_urls = ""
        agent.p3_pdf1_url = ""
    agent.updated_at = dt.datetime.utcnow()


def _render_edit(agent: Agent, profile: str, is_admin_flag: bool):
    profile = profile_prefix(profile)

    # taglio automatico se esploso
    s = db()
    if compact_limits(agent, profile):
        s.merge(agent)
        s.commit()

    data = get_profile_data(agent, profile)
    i18n_data = load_i18n_profile(agent, profile)
    gallery, videos, pdfs = get_media(agent, profile)
    vis = get_profile_visual(agent, profile)

    preview_photo = vis.get("photo_url") or vis.get("logo_url") or ""

    return render_template(
        "agent_form.html",
        agent=agent,
        profile=profile,
        is_admin=is_admin_flag,
        data=data,
        i18n_data=i18n_data,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        vis=vis,
        preview_photo=preview_photo,
        limits={
            "max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
            "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB
        }
    )


# ==========================
# FAVICON + UPLOADS
# ==========================
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.ico")

@app.route("/uploads/<path:filename>")
def serve_uploads(filename):
    return send_from_directory(str(UPLOADS_DIR), filename)


# ==========================
# AUTH
# ==========================
@app.route("/area/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = (request.form.get("password") or "").strip()

        if u == "admin" and p == ADMIN_PASSWORD:
            session["role"] = "admin"
            session["slug"] = None
            return redirect(url_for("dashboard"))

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
        agents.sort(key=lambda x: ((x.name or "").strip().lower(), (x.slug or "").strip().lower()))
        return render_template("dashboard.html", agents=agents, is_admin=True, agent=None)

    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        session.clear()
        return redirect(url_for("login"))

    return render_template("dashboard.html", agents=[ag], is_admin=False, agent=ag)


# ==========================
# ADMIN: NEW / EDIT P1/P2/P3
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
            p2_enabled=0, p2_json="{}", p2_i18n_json="{}",
            p3_enabled=0, p3_json="{}", p3_i18n_json="{}",
            i18n_json="{}"
        )
        s.add(ag)
        s.commit()

        flash("Card creata!", "ok")
        return redirect(url_for("edit_agent_profile", slug=slug, profile="p1"))

    # GET: una “nuova card” = P1 vuoto
    dummy = Agent(slug="new", username="new", password_hash="x")
    return _render_edit(dummy, "p1", True)


@app.route("/area/edit/<slug>", methods=["GET", "POST"])
def edit_agent(slug):
    # compat: /area/edit/<slug> = P1
    return edit_agent_profile(slug, "p1")


@app.route("/area/edit/<slug>/<profile>", methods=["GET", "POST"])
def edit_agent_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    profile = profile_prefix(profile)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if profile in ("p2", "p3") and not enabled_for_profile(ag, profile):
        flash(f"Profilo {profile.upper()} non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            save_profile_data(ag, profile, request.form)
            save_i18n_profile(ag, profile, request.form)
            handle_media_uploads(ag, profile)
            s.commit()
            flash("Salvato!", "ok")
            return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))

    return _render_edit(ag, profile, True)


# ==========================
# AGENT SELF EDIT
# ==========================
@app.route("/area/me/edit", methods=["GET", "POST"])
def me_edit():
    r = require_login()
    if r:
        return r
    if is_admin():
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    profile = "p1"
    if request.method == "POST":
        try:
            save_profile_data(ag, profile, request.form)
            save_i18n_profile(ag, profile, request.form)
            handle_media_uploads(ag, profile)
            s.commit()
            flash("Salvato!", "ok")
            return redirect(url_for("me_edit"))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("me_edit"))

    return _render_edit(ag, profile, False)


@app.route("/area/me/<profile>", methods=["GET", "POST"])
def me_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    profile = profile_prefix(profile)
    if profile == "p1":
        return redirect(url_for("me_edit"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if not enabled_for_profile(ag, profile):
        flash(f"Profilo {profile.upper()} non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            save_profile_data(ag, profile, request.form)
            save_i18n_profile(ag, profile, request.form)
            handle_media_uploads(ag, profile)
            s.commit()
            flash("Salvato!", "ok")
            return redirect(url_for("me_profile", profile=profile))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("me_profile", profile=profile))

    return _render_edit(ag, profile, False)


# ==========================
# ACTIVATE/DEACTIVATE P2/P3 (ADMIN + ME)
# ==========================
@app.route("/area/admin/activate/<slug>/<profile>", methods=["POST"])
def admin_activate_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    profile = profile_prefix(profile)
    if profile == "p1":
        abort(400)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if profile == "p2":
        ag.p2_enabled = 1
        reset_profile(ag, "p2")
        flash("P2 attivato (vuoto).", "ok")
    elif profile == "p3":
        ag.p3_enabled = 1
        reset_profile(ag, "p3")
        flash("P3 attivato (vuoto).", "ok")

    s.commit()
    return redirect(url_for("dashboard"))


@app.route("/area/admin/deactivate/<slug>/<profile>", methods=["POST"])
def admin_deactivate_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    profile = profile_prefix(profile)
    if profile == "p1":
        abort(400)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if profile == "p2":
        ag.p2_enabled = 0
        reset_profile(ag, "p2")
        flash("P2 disattivato (svuotato).", "ok")
    elif profile == "p3":
        ag.p3_enabled = 0
        reset_profile(ag, "p3")
        flash("P3 disattivato (svuotato).", "ok")

    s.commit()
    return redirect(url_for("dashboard"))


@app.route("/area/me/activate/<profile>", methods=["POST"])
def me_activate_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    profile = profile_prefix(profile)
    if profile == "p1":
        abort(400)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if profile == "p2":
        ag.p2_enabled = 1
        reset_profile(ag, "p2")
        flash("P2 attivato (vuoto).", "ok")
    elif profile == "p3":
        ag.p3_enabled = 1
        reset_profile(ag, "p3")
        flash("P3 attivato (vuoto).", "ok")

    s.commit()
    return redirect(url_for("dashboard"))


@app.route("/area/me/deactivate/<profile>", methods=["POST"])
def me_deactivate_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    profile = profile_prefix(profile)
    if profile == "p1":
        abort(400)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if profile == "p2":
        ag.p2_enabled = 0
        reset_profile(ag, "p2")
        flash("P2 disattivato (svuotato).", "ok")
    elif profile == "p3":
        ag.p3_enabled = 0
        reset_profile(ag, "p3")
        flash("P3 disattivato (svuotato).", "ok")

    s.commit()
    return redirect(url_for("dashboard"))


# ==========================
# ADMIN: CREDENTIALS
# ==========================
@app.route("/area/admin/credentials/<slug>", methods=["POST"])
def admin_generate_credentials(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    newp = _new_password(10)
    ag.password_hash = generate_password_hash(newp)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()

    session["last_credentials"] = {
        "slug": ag.slug,
        "username": ag.username,
        "password": newp,
        "ts": dt.datetime.utcnow().isoformat()
    }
    return redirect(url_for("dashboard"))


@app.route("/area/admin/send_credentials", methods=["POST"])
def admin_send_credentials_placeholder():
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)
    flash("Invio credenziali via Email/WhatsApp: lo attiviamo dopo con SMTP + WhatsApp.", "warning")
    return redirect(url_for("dashboard"))


# ==========================
# ADMIN DELETE CARD (mantengo com'è: serve solo admin)
# ==========================
@app.route("/area/admin/delete/<slug>", methods=["POST"])
def admin_delete_agent(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    confirm = (request.form.get("confirm") or "").strip().lower()
    if confirm != "si":
        flash("Conferma mancante: scrivi SI per eliminare.", "error")
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    s.delete(ag)
    s.commit()
    flash(f"Card eliminata: {slug}", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# MEDIA DELETE (funziona per P1/P2/P3)
# ==========================
@app.route("/area/media/delete/<slug>", methods=["POST"])
def delete_media(slug):
    r = require_login()
    if r:
        return r

    t = (request.form.get("type") or "").strip()  # gallery|video|pdf
    idx = int(request.form.get("idx") or -1)
    profile = profile_prefix(request.form.get("profile") or "p1")

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if not is_admin() and ag.slug != session.get("slug"):
        abort(403)

    gallery, videos, pdfs = get_media(ag, profile)

    if t == "gallery":
        if 0 <= idx < len(gallery):
            gallery.pop(idx)
    elif t == "video":
        if 0 <= idx < len(videos):
            videos.pop(idx)
    elif t == "pdf":
        if 0 <= idx < len(pdfs):
            pdfs.pop(idx)
    else:
        abort(400)

    set_media_strings(ag, profile, gallery, videos, pdfs)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Eliminato.", "ok")

    if is_admin():
        return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))
    return redirect(url_for("me_profile", profile=profile) if profile != "p1" else url_for("me_edit"))


# ==========================
# QR + VCF (non tocchiamo)
# ==========================
@app.route("/qr/<slug>.png")
def qr_png(slug):
    if qrcode is None:
        abort(500)

    p = profile_prefix(request.args.get("p") or "p1")
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    base = public_base_url()
    url = f"{base}/{ag.slug}"
    if p in ("p2", "p3") and enabled_for_profile(ag, p):
        url = f"{base}/{ag.slug}?p={p}"

    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    filename = f"QR-{ag.slug}-{p.upper()}.png"
    return Response(
        buf.getvalue(),
        mimetype="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.route("/vcf/<slug>")
def vcf(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    full_name = (ag.name or ag.slug or "").strip()
    org = (ag.company or "").strip()
    title = (ag.role or "").strip()
    emails = split_csv(ag.emails or "")
    webs = split_csv(ag.websites or "")
    tel1 = (ag.phone_mobile or "").strip()
    tel2 = (ag.phone_mobile2 or "").strip()
    office = (ag.phone_office or "").strip()

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{full_name}",
    ]
    if org:
        lines.append(f"ORG:{org}")
    if title:
        lines.append(f"TITLE:{title}")
    if tel1:
        lines.append(f"TEL;TYPE=CELL:{tel1}")
    if tel2:
        lines.append(f"TEL;TYPE=CELL:{tel2}")
    if office:
        lines.append(f"TEL;TYPE=WORK:{office}")
    for e in emails[:5]:
        lines.append(f"EMAIL;TYPE=INTERNET:{e}")
    for w in webs[:3]:
        lines.append(f"URL:{w}")
    lines.append("END:VCARD")

    vcf_text = "\r\n".join(lines) + "\r\n"
    filename = f"{ag.slug}-P1.vcf"
    return Response(
        vcf_text,
        mimetype="text/vcard; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ==========================
# CARD PUBLIC (P1/P2/P3)
# ==========================
@app.route("/<slug>")
def card(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    p = profile_prefix(request.args.get("p") or "p1")
    if p in ("p2", "p3") and not enabled_for_profile(ag, p):
        p = "p1"

    data = get_profile_data(ag, p)
    vis = get_profile_visual(ag, p)
    i18n_data = load_i18n_profile(ag, p)
    gallery, videos, pdfs = get_media(ag, p)

    # CONTATTI
    emails = split_csv(data.get("emails", ""))
    websites = split_csv(data.get("websites", ""))
    addresses = split_lines(data.get("addresses", ""))

    addr_objs = []
    for a in addresses:
        q = a.replace(" ", "+")
        addr_objs.append({"text": a, "maps": f"https://www.google.com/maps/search/?api=1&query={q}"})

    mobiles = []
    if (data.get("phone_mobile") or "").strip():
        mobiles.append((data.get("phone_mobile") or "").strip())
    if (data.get("phone_mobile2") or "").strip():
        mobiles.append((data.get("phone_mobile2") or "").strip())

    office_value = (data.get("phone_office") or "").strip()

    wa_link = (data.get("whatsapp") or "").strip()
    if wa_link and wa_link.startswith("+"):
        wa_link = "https://wa.me/" + re.sub(r"\D+", "", wa_link)

    base_url = public_base_url()
    qr_url = f"{base_url}/{ag.slug}" + ("" if p == "p1" else f"?p={p}")

    # compat con tuo card.html attuale
    class Obj(dict):
        __getattr__ = dict.get

    ag_view = Obj({
        "slug": ag.slug,
        "name": data.get("name", ""),
        "company": data.get("company", ""),
        "role": data.get("role", ""),
        "bio": data.get("bio", ""),
        "piva": data.get("piva", ""),
        "sdi": data.get("sdi", ""),

        "photo_url": vis.get("photo_url", ""),
        "logo_url": vis.get("logo_url", ""),
        "back_media_mode": vis.get("back_media_mode", "company"),
        "back_media_url": vis.get("back_media_url", ""),

        "photo_pos_x": vis.get("photo_pos_x", 50),
        "photo_pos_y": vis.get("photo_pos_y", 35),
        "photo_zoom": float(vis.get("photo_zoom", "1.0") or "1.0"),

        "orbit_spin": vis.get("orbit_spin", 0),
        "avatar_spin": vis.get("avatar_spin", 0),
        "logo_spin": vis.get("logo_spin", 0),
        "allow_flip": vis.get("allow_flip", 0),
    })

    return render_template(
        "card.html",
        ag=ag_view,
        p=p,
        wa_link=wa_link,
        qr_url=qr_url,
        emails=emails,
        websites=websites,
        addresses=addr_objs,
        mobiles=mobiles,
        office_value=office_value,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        i18n_data=i18n_data
    )


@app.route("/")
def home():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
