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

    # ---- P1 fields
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

    photo_url = Column(String(255), default="")
    logo_url = Column(String(255), default="")
    back_media_mode = Column(String(30), default="company")
    back_media_url = Column(String(255), default="")

    photo_pos_x = Column(Integer, default=50)
    photo_pos_y = Column(Integer, default=35)
    photo_zoom = Column(String(20), default="1.0")

    orbit_spin = Column(Integer, default=0)
    avatar_spin = Column(Integer, default=0)
    logo_spin = Column(Integer, default=0)
    allow_flip = Column(Integer, default=0)

    gallery_urls = Column(Text, default="")
    video_urls = Column(Text, default="")
    pdf1_url = Column(Text, default="")

    i18n_json = Column(Text, default="{}")

    # ---- P2 (FULL, indipendente)
    p2_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")
    p2_gallery_urls = Column(Text, default="")
    p2_video_urls = Column(Text, default="")
    p2_pdf1_url = Column(Text, default="")
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

    # ---- P3 (FULL, indipendente)
    p3_enabled = Column(Integer, default=0)
    p3_json = Column(Text, default="{}")
    p3_gallery_urls = Column(Text, default="")
    p3_video_urls = Column(Text, default="")
    p3_pdf1_url = Column(Text, default="")
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

    created_at = Column(DateTime, default=lambda: dt.datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: dt.datetime.utcnow())


# ==========================
# DB INIT + MIGRATION
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
        missing = []

        def add_col(name, coltype):
            if name not in cols:
                missing.append((name, coltype))

        # base columns
        add_col("created_at", "DATETIME")
        add_col("updated_at", "DATETIME")
        add_col("i18n_json", "TEXT")

        # P2 full set
        add_col("p2_enabled", "INTEGER")
        add_col("p2_json", "TEXT")
        add_col("p2_gallery_urls", "TEXT")
        add_col("p2_video_urls", "TEXT")
        add_col("p2_pdf1_url", "TEXT")
        add_col("p2_i18n_json", "TEXT")
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

        # P3 full set
        add_col("p3_enabled", "INTEGER")
        add_col("p3_json", "TEXT")
        add_col("p3_gallery_urls", "TEXT")
        add_col("p3_video_urls", "TEXT")
        add_col("p3_pdf1_url", "TEXT")
        add_col("p3_i18n_json", "TEXT")
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

        for (name, coltype) in missing:
            conn.exec_driver_sql(f"ALTER TABLE agents ADD COLUMN {name} {coltype}")

        now = dt.datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        conn.exec_driver_sql("UPDATE agents SET created_at = COALESCE(created_at, :now)", {"now": now})
        conn.exec_driver_sql("UPDATE agents SET updated_at = COALESCE(updated_at, :now)", {"now": now})

        # defaults
        conn.exec_driver_sql("UPDATE agents SET i18n_json = COALESCE(i18n_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET p2_json = COALESCE(p2_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET p2_i18n_json = COALESCE(p2_i18n_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET p3_json = COALESCE(p3_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET p3_i18n_json = COALESCE(p3_i18n_json, '{}')")

        # ints defaults
        for f in [
            "p2_enabled", "p3_enabled",
            "p2_orbit_spin", "p2_avatar_spin", "p2_logo_spin", "p2_allow_flip",
            "p3_orbit_spin", "p3_avatar_spin", "p3_logo_spin", "p3_allow_flip",
            "p2_photo_pos_x", "p2_photo_pos_y",
            "p3_photo_pos_x", "p3_photo_pos_y",
        ]:
            conn.exec_driver_sql(f"UPDATE agents SET {f} = COALESCE({f}, 0)")

        # zoom defaults
        conn.exec_driver_sql("UPDATE agents SET p2_photo_zoom = COALESCE(p2_photo_zoom, '1.0')")
        conn.exec_driver_sql("UPDATE agents SET p3_photo_zoom = COALESCE(p3_photo_zoom, '1.0')")

        # mode defaults
        conn.exec_driver_sql("UPDATE agents SET p2_back_media_mode = COALESCE(p2_back_media_mode, 'company')")
        conn.exec_driver_sql("UPDATE agents SET p3_back_media_mode = COALESCE(p3_back_media_mode, 'company')")

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
    return [x.strip() for x in (s or "").splitlines() if x.strip()]

def uploads_url(rel_path: str) -> str:
    rel_path = rel_path.lstrip("/")
    return f"/uploads/{rel_path}"

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

def parse_pdf_items(pdf_blob: str):
    items = []
    if not pdf_blob:
        return items
    for chunk in pdf_blob.split("|"):
        if not chunk.strip():
            continue
        if "||" in chunk:
            name, url = chunk.split("||", 1)
            items.append({"name": (name.strip() or "Documento"), "url": url.strip()})
        else:
            items.append({"name": chunk.strip(), "url": chunk.strip()})
    return items

def pdf_items_to_blob(items):
    out = []
    for it in items:
        u = (it.get("url") or "").strip()
        if not u:
            continue
        n = (it.get("name") or "Documento").strip()
        out.append(f"{n}||{u}")
    return "|".join(out)

def _new_password(length=10):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    import random
    return "".join(random.choice(alphabet) for _ in range(length))

def load_json_dict(s: str):
    try:
        d = json.loads(s or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def profile_prefix(profile: str) -> str:
    profile = (profile or "p1").lower()
    if profile not in ("p1", "p2", "p3"):
        profile = "p1"
    return profile

def get_profile_enabled(agent: Agent, profile: str) -> bool:
    p = profile_prefix(profile)
    if p == "p1":
        return True
    return int(getattr(agent, f"{p}_enabled") or 0) == 1

def set_profile_enabled(agent: Agent, profile: str, enabled: bool):
    p = profile_prefix(profile)
    if p == "p1":
        return
    setattr(agent, f"{p}_enabled", 1 if enabled else 0)

def get_profile_data(agent: Agent, profile: str) -> dict:
    """
    ritorna dict con tutti i campi testuali della card per il profilo (p1/p2/p3)
    """
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
    return load_json_dict(getattr(agent, f"{p}_json") or "{}")

def set_profile_data(agent: Agent, profile: str, form: dict):
    """
    salva campi testuali + opzioni spin/flip + crop + background del profilo
    """
    p = profile_prefix(profile)

    # spin/flip
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

    # crop
    pos_x = safe_int(form.get("photo_pos_x"), 50)
    pos_y = safe_int(form.get("photo_pos_y"), 35)
    z = (form.get("photo_zoom") or "1.0").strip()
    try:
        float(z)
    except Exception:
        z = "1.0"

    back_mode = (form.get("back_media_mode") or "company").strip()

    if p == "p1":
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

        agent.back_media_mode = back_mode
        agent.photo_pos_x = pos_x
        agent.photo_pos_y = pos_y
        agent.photo_zoom = z

        agent.orbit_spin = orbit_spin
        agent.avatar_spin = avatar_spin
        agent.logo_spin = logo_spin
        agent.allow_flip = allow_flip
    else:
        data = {}
        for k in [
            "name", "company", "role", "bio",
            "phone_mobile", "phone_mobile2", "phone_office", "whatsapp",
            "emails", "websites", "pec", "addresses",
            "piva", "sdi",
            "facebook", "instagram", "linkedin", "tiktok", "telegram", "youtube", "spotify"
        ]:
            data[k] = (form.get(k) or "").strip()
        setattr(agent, f"{p}_json", json.dumps(data, ensure_ascii=False))

        setattr(agent, f"{p}_back_media_mode", back_mode)
        setattr(agent, f"{p}_photo_pos_x", pos_x)
        setattr(agent, f"{p}_photo_pos_y", pos_y)
        setattr(agent, f"{p}_photo_zoom", z)

        setattr(agent, f"{p}_orbit_spin", orbit_spin)
        setattr(agent, f"{p}_avatar_spin", avatar_spin)
        setattr(agent, f"{p}_logo_spin", logo_spin)
        setattr(agent, f"{p}_allow_flip", allow_flip)

    agent.updated_at = dt.datetime.utcnow()

def load_i18n_profile(agent: Agent, profile: str) -> dict:
    p = profile_prefix(profile)
    blob = agent.i18n_json if p == "p1" else getattr(agent, f"{p}_i18n_json") or "{}"
    return load_json_dict(blob)

def save_i18n_profile(agent: Agent, profile: str, form: dict):
    data = {}
    for L in ["en", "fr", "es", "de"]:
        data[L] = {
            "name": (form.get(f"name_{L}") or "").strip(),
            "company": (form.get(f"company_{L}") or "").strip(),
            "role": (form.get(f"role_{L}") or "").strip(),
            "bio": (form.get(f"bio_{L}") or "").strip(),
            "addresses": (form.get(f"addresses_{L}") or "").strip(),
        }
    p = profile_prefix(profile)
    if p == "p1":
        agent.i18n_json = json.dumps(data, ensure_ascii=False)
    else:
        setattr(agent, f"{p}_i18n_json", json.dumps(data, ensure_ascii=False))

def get_media(agent: Agent, profile: str):
    p = profile_prefix(profile)
    if p == "p1":
        g = [x for x in (agent.gallery_urls or "").split("|") if x.strip()]
        v = [x for x in (agent.video_urls or "").split("|") if x.strip()]
        pdfs = parse_pdf_items(agent.pdf1_url or "")
        return g, v, pdfs
    g = [x for x in (getattr(agent, f"{p}_gallery_urls") or "").split("|") if x.strip()]
    v = [x for x in (getattr(agent, f"{p}_video_urls") or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(getattr(agent, f"{p}_pdf1_url") or "")
    return g, v, pdfs

def set_media(agent: Agent, profile: str, gallery_list, video_list, pdf_items):
    p = profile_prefix(profile)
    gallery_list = (gallery_list or [])[:MAX_GALLERY_IMAGES]
    video_list = (video_list or [])[:MAX_VIDEOS]
    pdf_items = (pdf_items or [])[:MAX_PDFS]

    if p == "p1":
        agent.gallery_urls = "|".join(gallery_list)
        agent.video_urls = "|".join(video_list)
        agent.pdf1_url = pdf_items_to_blob(pdf_items)
    else:
        setattr(agent, f"{p}_gallery_urls", "|".join(gallery_list))
        setattr(agent, f"{p}_video_urls", "|".join(video_list))
        setattr(agent, f"{p}_pdf1_url", pdf_items_to_blob(pdf_items))

def compact_limits(agent: Agent, profile: str) -> bool:
    """
    taglia gallery/video/pdf ai limiti, evita esplosioni (es: 100 pdf).
    ritorna True se ha modificato qualcosa.
    """
    changed = False
    g, v, pdfs = get_media(agent, profile)

    g2 = g[:MAX_GALLERY_IMAGES]
    v2 = v[:MAX_VIDEOS]
    pdf2 = pdfs[:MAX_PDFS]

    if g2 != g or v2 != v or pdf2 != pdfs:
        set_media(agent, profile, g2, v2, pdf2)
        agent.updated_at = dt.datetime.utcnow()
        changed = True
    return changed

def handle_media_uploads(agent: Agent, profile: str):
    """
    upload media per profilo (p1/p2/p3) + hard limit pdf=10
    """
    p = profile_prefix(profile)

    # foto profilo
    photo = request.files.get("photo")
    if photo and photo.filename:
        url = save_upload(photo, "images")
        if p == "p1":
            agent.photo_url = url
        else:
            setattr(agent, f"{p}_photo_url", url)

    # logo
    logo = request.files.get("logo")
    if logo and logo.filename:
        url = save_upload(logo, "images")
        if p == "p1":
            agent.logo_url = url
        else:
            setattr(agent, f"{p}_logo_url", url)

    # background
    back_media = request.files.get("back_media")
    if back_media and back_media.filename:
        url = save_upload(back_media, "images")
        if p == "p1":
            agent.back_media_url = url
        else:
            setattr(agent, f"{p}_back_media_url", url)

    # load current
    g, v, pdfs = get_media(agent, profile)

    # galleria
    gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
    if gallery_files:
        gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
        urls = [save_upload(f, "images") for f in gallery_files]
        urls = [u for u in urls if u]
        combined = (g + urls)[:MAX_GALLERY_IMAGES]
        g = combined

    # video
    video_files = [f for f in request.files.getlist("videos") if f and f.filename]
    if video_files:
        video_files = video_files[:MAX_VIDEOS]
        urls = [save_upload(f, "videos") for f in video_files]
        urls = [u for u in urls if u]
        combined = (v + urls)[:MAX_VIDEOS]
        v = combined

    # pdf (max 10, stop oltre)
    # Carico i pdf nei 10 slot (pdf1..pdf10). Se già 10 pieni, NON aggiunge.
    existing = pdfs[:MAX_PDFS]
    for i in range(1, MAX_PDFS + 1):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            url = save_upload(f, "pdf")
            name = secure_filename(f.filename) or f"PDF {i}"
            idx = i - 1
            while len(existing) <= idx:
                existing.append({"name": "", "url": ""})
            existing[idx] = {"name": name, "url": url}

    # ripulisce vuoti + limita
    existing2 = [x for x in existing if (x.get("url") or "").strip()]
    existing2 = existing2[:MAX_PDFS]

    set_media(agent, profile, g, v, existing2)


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
# ADMIN: NEW
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
            # P2/P3 OFF + vuoti
            p2_enabled=0, p2_json="{}", p2_gallery_urls="", p2_video_urls="", p2_pdf1_url="", p2_i18n_json="{}",
            p3_enabled=0, p3_json="{}", p3_gallery_urls="", p3_video_urls="", p3_pdf1_url="", p3_i18n_json="{}",
        )
        s.add(ag)
        s.commit()

        flash("Card creata!", "ok")
        return redirect(url_for("edit_agent", slug=slug, profile="p1"))

    return render_template(
        "agent_form.html",
        agent=None,
        profile="p1",
        is_admin=True,
        data={},
        i18n_data={},
        gallery=[],
        videos=[],
        pdfs=[],
        limits={
            "max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
            "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB
        }
    )


# ==========================
# EDIT (ADMIN + ME)
# ==========================
def _render_edit(agent: Agent, profile: str, is_admin_flag: bool):
    # taglia eventuali esplosioni (100 pdf ecc.)
    s = db()
    changed = compact_limits(agent, profile)
    if changed:
        s.merge(agent)
        s.commit()

    data = get_profile_data(agent, profile)
    i18n_data = load_i18n_profile(agent, profile)
    gallery, videos, pdfs = get_media(agent, profile)

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
        limits={
            "max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
            "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB
        }
    )

@app.route("/area/edit/<slug>", methods=["GET", "POST"])
def edit_agent(slug):
    return redirect(url_for("edit_agent_profile", slug=slug, profile="p1"))

@app.route("/area/edit/<slug>/<profile>", methods=["GET", "POST"])
def edit_agent_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    profile = profile_prefix(profile)
    if profile in ("p2", "p3"):
        # deve essere attivo per modificare
        s = db()
        ag = s.query(Agent).filter(Agent.slug == slug).first()
        if not ag:
            abort(404)
        if not get_profile_enabled(ag, profile):
            flash(f"{profile.upper()} non attivo", "error")
            return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if request.method == "POST":
        try:
            set_profile_data(ag, profile, request.form)
            handle_media_uploads(ag, profile)
            save_i18n_profile(ag, profile, request.form)
            compact_limits(ag, profile)
            s.commit()
            flash("Salvato!", "ok")
            return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))

    return _render_edit(ag, profile, True)

@app.route("/area/me/edit", methods=["GET", "POST"])
def me_edit():
    return redirect(url_for("me_edit_profile", profile="p1"))

@app.route("/area/me/<profile>", methods=["GET", "POST"])
def me_edit_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        return redirect(url_for("dashboard"))

    profile = profile_prefix(profile)
    if profile == "p1":
        pass
    else:
        # p2/p3 devono essere attivi
        pass

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if profile in ("p2", "p3") and not get_profile_enabled(ag, profile):
        flash(f"{profile.upper()} non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            set_profile_data(ag, profile, request.form)
            handle_media_uploads(ag, profile)
            save_i18n_profile(ag, profile, request.form)
            compact_limits(ag, profile)
            s.commit()
            flash("Salvato!", "ok")
            return redirect(url_for("me_edit_profile", profile=profile))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("me_edit_profile", profile=profile))

    return _render_edit(ag, profile, False)


# ==========================
# ACTIVATE/DEACTIVATE P2/P3 (ADMIN)
# ==========================
def reset_profile_to_empty(agent: Agent, profile: str):
    p = profile_prefix(profile)
    if p == "p1":
        return
    # svuota tutto
    setattr(agent, f"{p}_json", "{}")
    setattr(agent, f"{p}_gallery_urls", "")
    setattr(agent, f"{p}_video_urls", "")
    setattr(agent, f"{p}_pdf1_url", "")
    setattr(agent, f"{p}_i18n_json", "{}")
    setattr(agent, f"{p}_photo_url", "")
    setattr(agent, f"{p}_logo_url", "")
    setattr(agent, f"{p}_back_media_url", "")
    setattr(agent, f"{p}_back_media_mode", "company")
    setattr(agent, f"{p}_photo_pos_x", 50)
    setattr(agent, f"{p}_photo_pos_y", 35)
    setattr(agent, f"{p}_photo_zoom", "1.0")
    setattr(agent, f"{p}_orbit_spin", 0)
    setattr(agent, f"{p}_avatar_spin", 0)
    setattr(agent, f"{p}_logo_spin", 0)
    setattr(agent, f"{p}_allow_flip", 0)

@app.route("/area/admin/activate/<slug>/<profile>", methods=["POST"])
def admin_activate_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    profile = profile_prefix(profile)
    if profile == "p1":
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    set_profile_enabled(ag, profile, True)
    reset_profile_to_empty(ag, profile)  # ✅ SEMPRE VUOTO
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash(f"{profile.upper()} attivato (vuoto).", "ok")
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
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    set_profile_enabled(ag, profile, False)
    reset_profile_to_empty(ag, profile)  # ✅ svuota
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash(f"{profile.upper()} disattivato (svuotato).", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# ACTIVATE/DEACTIVATE P2/P3 (ME)
# ==========================
@app.route("/area/me/activate/<profile>", methods=["POST"])
def me_activate_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    profile = profile_prefix(profile)
    if profile == "p1":
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    set_profile_enabled(ag, profile, True)
    reset_profile_to_empty(ag, profile)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash(f"{profile.upper()} attivato (vuoto).", "ok")
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
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    set_profile_enabled(ag, profile, False)
    reset_profile_to_empty(ag, profile)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash(f"{profile.upper()} disattivato (svuotato).", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# ADMIN: CREDENTIALS (come prima)
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
# MEDIA DELETE (P1/P2/P3)
# ==========================
@app.route("/area/media/delete/<slug>", methods=["POST"])
def delete_media(slug):
    r = require_login()
    if r:
        return r

    t = (request.form.get("type") or "").strip()      # gallery | video | pdf
    idx = int(request.form.get("idx") or -1)
    profile = profile_prefix(request.form.get("profile") or "p1")

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if not is_admin() and ag.slug != session.get("slug"):
        abort(403)

    g, v, pdfs = get_media(ag, profile)

    if t == "gallery":
        if 0 <= idx < len(g):
            g.pop(idx)
    elif t == "video":
        if 0 <= idx < len(v):
            v.pop(idx)
    elif t == "pdf":
        if 0 <= idx < len(pdfs):
            pdfs.pop(idx)
    else:
        abort(400)

    # salva + compatta
    set_media(ag, profile, g, v, pdfs[:MAX_PDFS])
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Eliminato.", "ok")

    # torna dove eri
    ref = request.referrer or ""
    if ref:
        return redirect(ref)

    if is_admin():
        return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))
    return redirect(url_for("me_edit_profile", profile=profile))


# ==========================
# QR PNG + VCF
# ==========================
@app.route("/qr/<slug>.png")
def qr_png(slug):
    if qrcode is None:
        abort(500)

    p = (request.args.get("p") or "").strip().lower()
    if p not in ("p2", "p3"):
        p = "p1"

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    base = public_base_url()
    url = f"{base}/{ag.slug}"
    if p in ("p2", "p3") and get_profile_enabled(ag, p):
        url = f"{base}/{ag.slug}?p={p}"

    img = qrcode.make(url)
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    filename = f"QR-{ag.slug}-{p.upper()}.png"
    # IMPORTANT: non forzare attachment (così click apre direttamente nel browser)
    return Response(
        buf.getvalue(),
        mimetype="image/png",
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
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
# CARD PUBLIC (P1/P2/P3 dati separati)
# (non tocchiamo HTML, passiamo i dati giusti)
# ==========================
@app.route("/<slug>")
def card(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    lang = (request.args.get("lang") or "it").strip().lower()
    p = (request.args.get("p") or "p1").strip().lower()
    if p not in ("p1", "p2", "p3"):
        p = "p1"
    if p in ("p2", "p3") and not get_profile_enabled(ag, p):
        p = "p1"

    # dati e media del profilo selezionato
    data = get_profile_data(ag, p)
    i18n_data = load_i18n_profile(ag, p)
    gallery, videos, pdfs = get_media(ag, p)

    emails = split_csv(data.get("emails", ""))
    websites = split_csv(data.get("websites", ""))
    addresses = split_lines(data.get("addresses", ""))

    addr_objs = []
    for a in addresses:
        q = a.replace(" ", "+")
        addr_objs.append({"text": a, "maps": f"https://www.google.com/maps/search/?api=1&query={q}"})

    mobiles = []
    if (data.get("phone_mobile") or "").strip():
        mobiles.append(data["phone_mobile"].strip())
    if (data.get("phone_mobile2") or "").strip():
        mobiles.append(data["phone_mobile2"].strip())
    office_value = (data.get("phone_office") or "").strip()

    wa_link = (data.get("whatsapp") or "").strip()
    if wa_link and wa_link.startswith("+"):
        wa_link = "https://wa.me/" + re.sub(r"\D+", "", wa_link)

    base_url = public_base_url()
    qr_url = f"{base_url}/{ag.slug}" + ("" if p == "p1" else f"?p={p}")

    # immagini/logo/back/crop/opzioni del profilo
    def get_attr_profile(field_p1, field_px):
        if p == "p1":
            return getattr(ag, field_p1)
        return getattr(ag, f"{p}_{field_px}")

    class Obj(dict):
        __getattr__ = dict.get

    ag_view = Obj({
        "slug": ag.slug,
        "logo_url": get_attr_profile("logo_url", "logo_url"),
        "photo_url": get_attr_profile("photo_url", "photo_url"),
        "back_media_mode": get_attr_profile("back_media_mode", "back_media_mode"),
        "back_media_url": get_attr_profile("back_media_url", "back_media_url"),
        "photo_pos_x": get_attr_profile("photo_pos_x", "photo_pos_x"),
        "photo_pos_y": get_attr_profile("photo_pos_y", "photo_pos_y"),
        "photo_zoom": float(get_attr_profile("photo_zoom", "photo_zoom") or "1.0"),
        "orbit_spin": get_attr_profile("orbit_spin", "orbit_spin"),
        "avatar_spin": get_attr_profile("avatar_spin", "avatar_spin"),
        "logo_spin": get_attr_profile("logo_spin", "logo_spin"),
        "allow_flip": get_attr_profile("allow_flip", "allow_flip"),
        "name": data.get("name", ""),
        "company": data.get("company", ""),
        "role": data.get("role", ""),
        "bio": data.get("bio", ""),
        "piva": data.get("piva", ""),
        "sdi": data.get("sdi", ""),
    })

    # traduzioni: se lang non è it, prova i18n
    # (se card.html già le usa, ok. Altrimenti non rompe nulla)
    def t_func(k):
        it = {
            "actions":"Azioni","scan_qr":"QR","whatsapp":"WhatsApp","contacts":"Contatti",
            "mobile_phone":"Cellulare","office_phone":"Ufficio","open_website":"Sito",
            "open_maps":"Apri Maps","data":"Dati","vat":"P.IVA","sdi":"SDI",
            "gallery":"Foto","videos":"Video","documents":"Documenti"
        }
        return it.get(k, k)

    return render_template(
        "card.html",
        ag=ag_view,
        lang=lang,
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
        i18n_data=i18n_data,
        profile=p,
        t_func=t_func
    )


@app.route("/")
def home():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
