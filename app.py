import os
import re
import json
import uuid
import datetime as dt
from pathlib import Path
from urllib.parse import unquote

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

UPLOADS_DIR = Path(PERSIST_UPLOADS_DIR)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

SUBDIR_IMG = UPLOADS_DIR / "images"
SUBDIR_VID = UPLOADS_DIR / "videos"
SUBDIR_PDF = UPLOADS_DIR / "pdf"
for d in (SUBDIR_IMG, SUBDIR_VID, SUBDIR_PDF):
    d.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_MB = 6
MAX_VIDEO_MB = 40
MAX_PDF_MB = 15

MAX_GALLERY_IMAGES = 30
MAX_VIDEOS = 10
MAX_PDFS = 10

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

    # ===== P1 columns =====
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
    back_media_url = Column(String(255), default="")

    photo_pos_x = Column(Integer, default=50)
    photo_pos_y = Column(Integer, default=35)
    photo_zoom = Column(String(20), default="1.0")

    orbit_spin = Column(Integer, default=0)
    avatar_spin = Column(Integer, default=0)
    logo_spin = Column(Integer, default=0)
    allow_flip = Column(Integer, default=0)

    gallery_urls = Column(Text, default="")   # pipe list
    video_urls = Column(Text, default="")     # pipe list
    pdf1_url = Column(Text, default="")       # pipe list (name||url)

    # ===== P2/P3 =====
    p2_enabled = Column(Integer, default=0)
    p3_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")
    p3_json = Column(Text, default="{}")

    i18n_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=lambda: dt.datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: dt.datetime.utcnow())


# ==========================
# DB INIT / MIGRATION (sqlite)
# ==========================
def ensure_db():
    Base.metadata.create_all(engine)

    if not DATABASE_URL.startswith("sqlite"):
        return

    with engine.connect() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(agents)").fetchall()}

        def add_col(name, coltype):
            if name not in cols:
                conn.exec_driver_sql(f"ALTER TABLE agents ADD COLUMN {name} {coltype}")

        for name, coltype in [
            ("gallery_urls", "TEXT"),
            ("video_urls", "TEXT"),
            ("pdf1_url", "TEXT"),

            ("p3_enabled", "INTEGER"),
            ("p3_json", "TEXT"),
            ("i18n_json", "TEXT"),
            ("photo_pos_x", "INTEGER"),
            ("photo_pos_y", "INTEGER"),
            ("photo_zoom", "TEXT"),
            ("orbit_spin", "INTEGER"),
            ("avatar_spin", "INTEGER"),
            ("logo_spin", "INTEGER"),
            ("allow_flip", "INTEGER"),
            ("back_media_url", "TEXT"),
            ("created_at", "DATETIME"),
            ("updated_at", "DATETIME"),
        ]:
            add_col(name, coltype)

        now = dt.datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        conn.exec_driver_sql("UPDATE agents SET created_at = COALESCE(created_at, :now)", {"now": now})
        conn.exec_driver_sql("UPDATE agents SET updated_at = COALESCE(updated_at, :now)", {"now": now})

        conn.exec_driver_sql("UPDATE agents SET p2_json = COALESCE(p2_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET p3_json = COALESCE(p3_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET i18n_json = COALESCE(i18n_json, '{}')")

        conn.exec_driver_sql("UPDATE agents SET gallery_urls = COALESCE(gallery_urls, '')")
        conn.exec_driver_sql("UPDATE agents SET video_urls = COALESCE(video_urls, '')")
        conn.exec_driver_sql("UPDATE agents SET pdf1_url = COALESCE(pdf1_url, '')")

        conn.exec_driver_sql("UPDATE agents SET photo_pos_x = COALESCE(photo_pos_x, 50)")
        conn.exec_driver_sql("UPDATE agents SET photo_pos_y = COALESCE(photo_pos_y, 35)")
        conn.exec_driver_sql("UPDATE agents SET photo_zoom = COALESCE(photo_zoom, '1.0')")

        for f in ["orbit_spin", "avatar_spin", "logo_spin", "allow_flip", "p2_enabled", "p3_enabled"]:
            conn.exec_driver_sql(f"UPDATE agents SET {f} = COALESCE({f}, 0)")

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

def parse_pipe_list(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split("|")]
    return [p for p in parts if p]

def join_pipe_list(items):
    items2 = []
    for x in items or []:
        x = (x or "").strip()
        if x:
            items2.append(x)
    return "|".join(items2)

def canon_url(u: str) -> str:
    """
    Normalizza qualsiasi variante in una forma coerente /uploads/...
    """
    u = (u or "").strip()
    if not u:
        return ""

    if re.match(r"^https?://", u, re.I):
        return u

    if u.startswith("/uploads/"):
        return u

    if u.startswith("uploads/"):
        return "/" + u

    if u.startswith("pdf/") or u.startswith("images/") or u.startswith("videos/"):
        return "/uploads/" + u

    if u.startswith("/pdf/") or u.startswith("/images/") or u.startswith("/videos/"):
        return "/uploads" + u

    return u

def pdf_name_from_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    base = url.split("?")[0].split("#")[0]
    return base.rsplit("/", 1)[-1]

def normalize_pdf_item(item: str):
    item = (item or "").strip()
    if not item:
        return ("", "")
    if "||" in item:
        nm, url = item.split("||", 1)
        return ((nm or "").strip(), (url or "").strip())
    return ("", item)

# ✅ FIX MIRATO: accetta SOLO pdf veri (evita "uploads" junk e duplicazioni strane)
def _is_valid_pdf_url(u: str) -> bool:
    u = (u or "").strip()
    if not u:
        return False
    if re.match(r"^https?://", u, re.I):
        return u.lower().endswith(".pdf")
    return u.startswith("/uploads/pdf/") and u.lower().endswith(".pdf")

def clean_pdf_pipe(raw: str) -> str:
    items = parse_pipe_list(raw or "")
    out = []
    seen = set()
    for it in items:
        nm, url = normalize_pdf_item(it)
        url = canon_url(url)

        # ✅ SOLO pdf veri
        if not _is_valid_pdf_url(url):
            continue

        if url in seen:
            continue
        seen.add(url)

        nm = (nm or "").strip() or pdf_name_from_url(url)
        out.append(f"{nm}||{url}")

    # ✅ limite massimo
    out = out[:MAX_PDFS]
    return join_pipe_list(out)

def clean_media_pipe(raw: str) -> str:
    items = parse_pipe_list(raw or "")
    out = []
    seen = set()
    for u in items:
        u = canon_url(u)
        if not u:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return join_pipe_list(out)

def load_i18n(agent: Agent) -> dict:
    try:
        d = json.loads(agent.i18n_json or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def save_i18n(agent: Agent, form: dict):
    data = {}
    for L in ["en", "fr", "es", "de"]:
        data[L] = {
            "name": (form.get(f"name_{L}") or "").strip(),
            "company": (form.get(f"company_{L}") or "").strip(),
            "role": (form.get(f"role_{L}") or "").strip(),
            "bio": (form.get(f"bio_{L}") or "").strip(),
            "addresses": (form.get(f"addresses_{L}") or "").strip(),
        }
    agent.i18n_json = json.dumps(data, ensure_ascii=False)

def load_profile_json(agent: Agent, key: str) -> dict:
    raw = agent.p2_json if key == "p2" else agent.p3_json
    try:
        d = json.loads(raw or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def save_profile_json(agent: Agent, key: str, data: dict):
    if key == "p2":
        agent.p2_json = json.dumps(data, ensure_ascii=False)
    else:
        agent.p3_json = json.dumps(data, ensure_ascii=False)

def default_profile_dict():
    return {
        "name": "", "company": "", "role": "", "bio": "",
        "phone_mobile": "", "phone_mobile2": "", "phone_office": "", "whatsapp": "",
        "emails": "", "websites": "", "pec": "", "addresses": "",
        "piva": "", "sdi": "",
        "facebook": "", "instagram": "", "linkedin": "", "tiktok": "", "telegram": "", "youtube": "", "spotify": "",

        "photo_url": "", "logo_url": "", "back_media_url": "",
        "photo_pos_x": 50, "photo_pos_y": 35, "photo_zoom": "1.0",
        "orbit_spin": 0, "avatar_spin": 0, "logo_spin": 0, "allow_flip": 0,

        "gallery_urls": "", "video_urls": "", "pdf_urls": ""
    }

def build_data_dict_p1(agent: Agent) -> dict:
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

        "photo_url": canon_url(agent.photo_url or ""),
        "logo_url": canon_url(agent.logo_url or ""),
        "back_media_url": canon_url(agent.back_media_url or ""),

        "photo_pos_x": int(agent.photo_pos_x or 50),
        "photo_pos_y": int(agent.photo_pos_y or 35),
        "photo_zoom": (agent.photo_zoom or "1.0"),

        "orbit_spin": int(agent.orbit_spin or 0),
        "avatar_spin": int(agent.avatar_spin or 0),
        "logo_spin": int(agent.logo_spin or 0),
        "allow_flip": int(agent.allow_flip or 0),

        "gallery_urls": clean_media_pipe(agent.gallery_urls or ""),
        "video_urls": clean_media_pipe(agent.video_urls or ""),
        "pdf_urls": clean_pdf_pipe(agent.pdf1_url or ""),
    }

def set_profile_data_p1(agent: Agent, form: dict):
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

    def safe_int(v, d):
        try: return int(v)
        except Exception: return d

    agent.photo_pos_x = safe_int(form.get("photo_pos_x"), 50)
    agent.photo_pos_y = safe_int(form.get("photo_pos_y"), 35)

    z = (form.get("photo_zoom") or "1.0").strip()
    try:
        float(z)
        agent.photo_zoom = z
    except Exception:
        agent.photo_zoom = "1.0"

    agent.orbit_spin = 1 if form.get("orbit_spin") == "on" else 0
    agent.avatar_spin = 1 if form.get("avatar_spin") == "on" else 0
    agent.logo_spin = 1 if form.get("logo_spin") == "on" else 0
    agent.allow_flip = 1 if form.get("allow_flip") == "on" else 0

    agent.updated_at = dt.datetime.utcnow()

def get_profile_data(agent: Agent, profile: str) -> dict:
    if profile == "p1":
        return build_data_dict_p1(agent)
    d = load_profile_json(agent, profile)
    base = default_profile_dict()
    base.update(d or {})
    base["photo_url"] = canon_url(base.get("photo_url", ""))
    base["logo_url"] = canon_url(base.get("logo_url", ""))
    base["back_media_url"] = canon_url(base.get("back_media_url", ""))
    base["gallery_urls"] = clean_media_pipe(base.get("gallery_urls", ""))
    base["video_urls"] = clean_media_pipe(base.get("video_urls", ""))
    base["pdf_urls"] = clean_pdf_pipe(base.get("pdf_urls", ""))
    return base

def set_profile_from_form(existing: dict, form: dict) -> dict:
    d = dict(existing or {})
    for k in [
        "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office", "whatsapp",
        "emails", "websites", "pec", "addresses",
        "piva", "sdi",
        "facebook", "instagram", "linkedin", "tiktok", "telegram", "youtube", "spotify"
    ]:
        d[k] = (form.get(k) or "").strip()

    def safe_int(v, default):
        try:
            return int(v)
        except Exception:
            return default

    d["photo_pos_x"] = safe_int(form.get("photo_pos_x"), int(d.get("photo_pos_x", 50) or 50))
    d["photo_pos_y"] = safe_int(form.get("photo_pos_y"), int(d.get("photo_pos_y", 35) or 35))

    z = (form.get("photo_zoom") or d.get("photo_zoom", "1.0") or "1.0").strip()
    try:
        float(z)
        d["photo_zoom"] = z
    except Exception:
        d["photo_zoom"] = "1.0"

    d["orbit_spin"] = 1 if form.get("orbit_spin") == "on" else 0
    d["avatar_spin"] = 1 if form.get("avatar_spin") == "on" else 0
    d["logo_spin"] = 1 if form.get("logo_spin") == "on" else 0
    d["allow_flip"] = 1 if form.get("allow_flip") == "on" else 0

    return d

def handle_media_uploads_common(data: dict):
    photo = request.files.get("photo")
    if photo and photo.filename:
        data["photo_url"] = save_upload(photo, "images")

    logo = request.files.get("logo")
    if logo and logo.filename:
        data["logo_url"] = save_upload(logo, "images")

    back_media = request.files.get("back_media")
    if back_media and back_media.filename:
        data["back_media_url"] = save_upload(back_media, "images")

    imgs = request.files.getlist("gallery_images")
    if imgs:
        current = parse_pipe_list(clean_media_pipe(data.get("gallery_urls", "")))
        for f in imgs:
            if f and f.filename:
                current.append(save_upload(f, "images"))
        current = current[:MAX_GALLERY_IMAGES]
        data["gallery_urls"] = clean_media_pipe(join_pipe_list(current))

    vids = request.files.getlist("gallery_videos")
    if vids:
        current = parse_pipe_list(clean_media_pipe(data.get("video_urls", "")))
        for f in vids:
            if f and f.filename:
                current.append(save_upload(f, "videos"))
        current = current[:MAX_VIDEOS]
        data["video_urls"] = clean_media_pipe(join_pipe_list(current))

    pdfs = request.files.getlist("pdf_files")
    if pdfs:
        current = parse_pipe_list(clean_pdf_pipe(data.get("pdf_urls", "")))
        for f in pdfs:
            if f and f.filename:
                url = save_upload(f, "pdf")
                nm = secure_filename(f.filename) or pdf_name_from_url(url)
                current.append(f"{nm}||{url}")
        # ✅ pulizia + limite + dedupe
        data["pdf_urls"] = clean_pdf_pipe(join_pipe_list(current))

def handle_media_uploads_p1(agent: Agent):
    photo = request.files.get("photo")
    if photo and photo.filename:
        agent.photo_url = save_upload(photo, "images")

    logo = request.files.get("logo")
    if logo and logo.filename:
        agent.logo_url = save_upload(logo, "images")

    back_media = request.files.get("back_media")
    if back_media and back_media.filename:
        agent.back_media_url = save_upload(back_media, "images")

    imgs = request.files.getlist("gallery_images")
    if imgs:
        current = parse_pipe_list(clean_media_pipe(agent.gallery_urls or ""))
        for f in imgs:
            if f and f.filename:
                current.append(save_upload(f, "images"))
        current = current[:MAX_GALLERY_IMAGES]
        agent.gallery_urls = clean_media_pipe(join_pipe_list(current))

    vids = request.files.getlist("gallery_videos")
    if vids:
        current = parse_pipe_list(clean_media_pipe(agent.video_urls or ""))
        for f in vids:
            if f and f.filename:
                current.append(save_upload(f, "videos"))
        current = current[:MAX_VIDEOS]
        agent.video_urls = clean_media_pipe(join_pipe_list(current))

    pdfs = request.files.getlist("pdf_files")
    if pdfs:
        current = parse_pipe_list(clean_pdf_pipe(agent.pdf1_url or ""))
        for f in pdfs:
            if f and f.filename:
                url = save_upload(f, "pdf")
                nm = secure_filename(f.filename) or pdf_name_from_url(url)
                current.append(f"{nm}||{url}")
        # ✅ pulizia + limite + dedupe
        agent.pdf1_url = clean_pdf_pipe(join_pipe_list(current))


# ==========================
# STATIC
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
    if r: return r

    s = db()
    if is_admin():
        agents = s.query(Agent).all()
        agents.sort(key=lambda x: ((x.name or "").strip().lower(), (x.slug or "").strip().lower()))
        return render_template("dashboard.html", agents=agents, is_admin=True)

    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        session.clear()
        return redirect(url_for("login"))
    return render_template("dashboard.html", agents=[ag], is_admin=False)


# ==========================
# ADMIN: NEW
# ==========================
@app.route("/area/new", methods=["GET", "POST"])
def new_agent():
    r = require_login()
    if r: return r
    if not is_admin(): abort(403)

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
            p2_enabled=0, p3_enabled=0,
            p2_json=json.dumps(default_profile_dict(), ensure_ascii=False),
            p3_json=json.dumps(default_profile_dict(), ensure_ascii=False),
            i18n_json="{}",
            gallery_urls="",
            video_urls="",
            pdf1_url="",
            created_at=dt.datetime.utcnow(),
            updated_at=dt.datetime.utcnow(),
        )
        s.add(ag)
        s.commit()

        flash("Card creata!", "ok")
        return redirect(url_for("edit_agent_p1", slug=slug))

    return render_template(
        "agent_form.html",
        agent=None,
        data=default_profile_dict(),
        i18n={},
        show_i18n=True,
        page_title="Nuova Card (P1)",
        page_hint="Crea i dati principali della card.",
        profile_label="Profilo 1"
    )


# ==========================
# ADMIN EDIT P1
# ==========================
@app.route("/area/edit/<slug>/p1", methods=["GET", "POST"])
def edit_agent_p1(slug):
    r = require_login()
    if r: return r
    if not is_admin(): abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag: abort(404)

    if request.method == "POST":
        try:
            set_profile_data_p1(ag, request.form)
            handle_media_uploads_p1(ag)
            save_i18n(ag, request.form)

            # pulizie forti
            ag.pdf1_url = clean_pdf_pipe(ag.pdf1_url or "")
            ag.gallery_urls = clean_media_pipe(ag.gallery_urls or "")
            ag.video_urls = clean_media_pipe(ag.video_urls or "")

            s.commit()
            flash("Salvato!", "ok")
            return redirect(url_for("edit_agent_p1", slug=slug))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("edit_agent_p1", slug=slug))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=build_data_dict_p1(ag),
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 1",
        page_hint="Qui modifichi i dati principali della tua Pay4You Card.",
        profile_label="Profilo 1"
    )


# ==========================
# ADMIN EDIT P2 / P3
# ==========================
@app.route("/area/edit/<slug>/p2", methods=["GET","POST"])
def edit_agent_p2(slug):
    r = require_login()
    if r: return r
    if not is_admin(): abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag: abort(404)
    if int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        d = get_profile_data(ag, "p2")
        d = set_profile_from_form(d, request.form)
        handle_media_uploads_common(d)

        d["gallery_urls"] = clean_media_pipe(d.get("gallery_urls", ""))
        d["video_urls"] = clean_media_pipe(d.get("video_urls", ""))
        d["pdf_urls"] = clean_pdf_pipe(d.get("pdf_urls", ""))

        save_profile_json(ag, "p2", d)
        save_i18n(ag, request.form)
        ag.updated_at = dt.datetime.utcnow()
        s.commit()
        flash("Profilo 2 salvato!", "ok")
        return redirect(url_for("edit_agent_p2", slug=slug))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=get_profile_data(ag, "p2"),
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 2",
        page_hint="Profilo 2 (vuoto e separato da P1).",
        profile_label="Profilo 2"
    )

@app.route("/area/edit/<slug>/p3", methods=["GET","POST"])
def edit_agent_p3(slug):
    r = require_login()
    if r: return r
    if not is_admin(): abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag: abort(404)
    if int(ag.p3_enabled or 0) != 1:
        flash("Profilo 3 non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        d = get_profile_data(ag, "p3")
        d = set_profile_from_form(d, request.form)
        handle_media_uploads_common(d)

        d["gallery_urls"] = clean_media_pipe(d.get("gallery_urls", ""))
        d["video_urls"] = clean_media_pipe(d.get("video_urls", ""))
        d["pdf_urls"] = clean_pdf_pipe(d.get("pdf_urls", ""))

        save_profile_json(ag, "p3", d)
        save_i18n(ag, request.form)
        ag.updated_at = dt.datetime.utcnow()
        s.commit()
        flash("Profilo 3 salvato!", "ok")
        return redirect(url_for("edit_agent_p3", slug=slug))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=get_profile_data(ag, "p3"),
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 3",
        page_hint="Profilo 3 (vuoto e separato da P1).",
        profile_label="Profilo 3"
    )


# ==========================
# CLIENT EDIT
# ==========================
@app.route("/area/me/edit", methods=["GET","POST"])
def me_edit_p1():
    r = require_login()
    if r: return r
    if is_admin(): return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag: abort(404)

    if request.method == "POST":
        try:
            set_profile_data_p1(ag, request.form)
            handle_media_uploads_p1(ag)
            save_i18n(ag, request.form)

            ag.pdf1_url = clean_pdf_pipe(ag.pdf1_url or "")
            ag.gallery_urls = clean_media_pipe(ag.gallery_urls or "")
            ag.video_urls = clean_media_pipe(ag.video_urls or "")

            s.commit()
            flash("Salvato!", "ok")
            return redirect(url_for("me_edit_p1"))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("me_edit_p1"))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=build_data_dict_p1(ag),
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 1",
        page_hint="Qui modifichi la tua Pay4You Card.",
        profile_label="Profilo 1"
    )

@app.route("/area/me/p2", methods=["GET","POST"])
def me_edit_p2():
    r = require_login()
    if r: return r
    if is_admin(): return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag: abort(404)
    if int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        d = get_profile_data(ag, "p2")
        d = set_profile_from_form(d, request.form)
        handle_media_uploads_common(d)

        d["gallery_urls"] = clean_media_pipe(d.get("gallery_urls", ""))
        d["video_urls"] = clean_media_pipe(d.get("video_urls", ""))
        d["pdf_urls"] = clean_pdf_pipe(d.get("pdf_urls", ""))

        save_profile_json(ag, "p2", d)
        save_i18n(ag, request.form)
        ag.updated_at = dt.datetime.utcnow()
        s.commit()
        flash("Salvato!", "ok")
        return redirect(url_for("me_edit_p2"))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=get_profile_data(ag, "p2"),
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 2",
        page_hint="Profilo 2 (separato da P1).",
        profile_label="Profilo 2"
    )

@app.route("/area/me/p3", methods=["GET","POST"])
def me_edit_p3():
    r = require_login()
    if r: return r
    if is_admin(): return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag: abort(404)
    if int(ag.p3_enabled or 0) != 1:
        flash("Profilo 3 non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        d = get_profile_data(ag, "p3")
        d = set_profile_from_form(d, request.form)
        handle_media_uploads_common(d)

        d["gallery_urls"] = clean_media_pipe(d.get("gallery_urls", ""))
        d["video_urls"] = clean_media_pipe(d.get("video_urls", ""))
        d["pdf_urls"] = clean_pdf_pipe(d.get("pdf_urls", ""))

        save_profile_json(ag, "p3", d)
        save_i18n(ag, request.form)
        ag.updated_at = dt.datetime.utcnow()
        s.commit()
        flash("Salvato!", "ok")
        return redirect(url_for("me_edit_p3"))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=get_profile_data(ag, "p3"),
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 3",
        page_hint="Profilo 3 (separato da P1).",
        profile_label="Profilo 3"
    )


# ==========================
# ACTIVATE/DEACTIVATE P2/P3
# ==========================
@app.route("/area/admin/activate/<slug>/p2", methods=["POST"])
def admin_activate_p2(slug):
    r = require_login()
    if r: return r
    if not is_admin(): abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag: abort(404)
    ag.p2_enabled = 1
    ag.p2_json = json.dumps(default_profile_dict(), ensure_ascii=False)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P2 attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/deactivate/<slug>/p2", methods=["POST"])
def admin_deactivate_p2(slug):
    r = require_login()
    if r: return r
    if not is_admin(): abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag: abort(404)
    ag.p2_enabled = 0
    ag.p2_json = json.dumps(default_profile_dict(), ensure_ascii=False)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P2 disattivato.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/activate/<slug>/p3", methods=["POST"])
def admin_activate_p3(slug):
    r = require_login()
    if r: return r
    if not is_admin(): abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag: abort(404)
    ag.p3_enabled = 1
    ag.p3_json = json.dumps(default_profile_dict(), ensure_ascii=False)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P3 attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/deactivate/<slug>/p3", methods=["POST"])
def admin_deactivate_p3(slug):
    r = require_login()
    if r: return r
    if not is_admin(): abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag: abort(404)
    ag.p3_enabled = 0
    ag.p3_json = json.dumps(default_profile_dict(), ensure_ascii=False)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P3 disattivato.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# DELETE MEDIA
# ==========================
@app.route("/area/media/delete/<slug>/<profile>")
def media_delete(slug, profile):
    r = require_login()
    if r: return r

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag: abort(404)

    if not is_admin() and session.get("slug") != ag.slug:
        abort(403)

    profile = (profile or "").strip().lower()
    if profile not in ["p1", "p2", "p3"]:
        abort(400)

    kind = (request.args.get("kind") or "").strip().lower()
    url = canon_url(unquote((request.args.get("url") or "").strip()))

    if not url or kind not in ["img", "vid", "pdf"]:
        abort(400)

    def remove_url_from_pipe(raw: str, target: str) -> str:
        items = parse_pipe_list(raw or "")
        out = []
        for x in items:
            if canon_url(x) != target:
                out.append(x)
        return clean_media_pipe(join_pipe_list(out))

    def remove_pdf_from_pipe(raw: str, target: str) -> str:
        items = parse_pipe_list(raw or "")
        out = []
        for it in items:
            nm, u = normalize_pdf_item(it)
            u = canon_url(u)
            if u and u != target:
                nm = nm or pdf_name_from_url(u)
                out.append(f"{nm}||{u}")
        return clean_pdf_pipe(join_pipe_list(out))

    def try_delete_physical(upload_url: str):
        try:
            if not upload_url.startswith("/uploads/"):
                return
            rel = upload_url[len("/uploads/"):]
            p = UPLOADS_DIR / rel
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    if profile == "p1":
        if kind == "img":
            ag.gallery_urls = remove_url_from_pipe(ag.gallery_urls or "", url)
        elif kind == "vid":
            ag.video_urls = remove_url_from_pipe(ag.video_urls or "", url)
        else:
            ag.pdf1_url = remove_pdf_from_pipe(ag.pdf1_url or "", url)
        s.commit()
        try_delete_physical(url)
        flash("Eliminato.", "ok")
        return redirect(request.referrer or url_for("dashboard"))

    d = get_profile_data(ag, profile)
    if kind == "img":
        d["gallery_urls"] = remove_url_from_pipe(d.get("gallery_urls", ""), url)
    elif kind == "vid":
        d["video_urls"] = remove_url_from_pipe(d.get("video_urls", ""), url)
    else:
        d["pdf_urls"] = remove_pdf_from_pipe(d.get("pdf_urls", ""), url)

    save_profile_json(ag, profile, d)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()

    try_delete_physical(url)
    flash("Eliminato.", "ok")
    return redirect(request.referrer or url_for("dashboard"))


# ==========================
# PURGE PDF TOTALE (tutti gli agenti)
# ==========================
@app.route("/area/admin/purge_pdfs", methods=["POST"])
def purge_pdfs_all():
    r = require_login()
    if r: return r
    if not is_admin(): abort(403)

    try:
        for p in SUBDIR_PDF.glob("*"):
            if p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    s = db()
    agents = s.query(Agent).all()
    for ag in agents:
        ag.pdf1_url = ""

        b2 = get_profile_data(ag, "p2")
        b3 = get_profile_data(ag, "p3")
        b2["pdf_urls"] = ""
        b3["pdf_urls"] = ""
        save_profile_json(ag, "p2", b2)
        save_profile_json(ag, "p3", b3)

        ag.updated_at = dt.datetime.utcnow()
    s.commit()

    flash("PURGE completato: eliminati tutti i PDF (file + DB) per tutti gli agenti.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# QR
# ==========================
@app.route("/qr/<slug>.png")
def qr_png(slug):
    if qrcode is None:
        abort(500)

    p = (request.args.get("p") or "").strip().lower()
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag: abort(404)

    base = public_base_url()
    url = f"{base}/{ag.slug}"
    if p == "p2" and int(ag.p2_enabled or 0) == 1:
        url = f"{base}/{ag.slug}?p=p2"
    if p == "p3" and int(ag.p3_enabled or 0) == 1:
        url = f"{base}/{ag.slug}?p=p3"

    img = qrcode.make(url)
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


# ==========================
# ✅ FIX MIRATO: PAGINA PUBBLICA CARD /<slug> (Apri P1/P2/P3 NO 404)
# ==========================
def _t_func_factory(lang: str = "it"):
    it = {
        "actions": "Azioni",
        "scan_qr": "Apri QR",
        "whatsapp": "WhatsApp",
        "contacts": "Contatti",
        "mobile_phone": "Telefono",
        "office_phone": "Telefono ufficio",
        "open_website": "Sito",
        "open_maps": "Apri Maps",
        "data": "Dati aziendali",
        "vat": "P.IVA",
        "sdi": "SDI",
        "gallery": "Galleria",
        "videos": "Video",
        "documents": "Documenti",
    }
    def t(k):
        return it.get(k, k)
    return t

def _split_lines(s: str):
    out = []
    for ln in (s or "").splitlines():
        ln = (ln or "").strip()
        if ln:
            out.append(ln)
    return out

def _split_commas(s: str):
    out = []
    for x in (s or "").split(","):
        x = (x or "").strip()
        if x:
            out.append(x)
    return out

def _make_wa_link(v: str):
    v = (v or "").strip()
    if not v:
        return ""
    if v.startswith("http://") or v.startswith("https://") or v.startswith("wa.me"):
        if v.startswith("wa.me"):
            return "https://" + v
        return v
    # numero: +39...
    num = re.sub(r"[^\d+]", "", v)
    if num.startswith("+"):
        num2 = num[1:]
    else:
        num2 = num
    if not num2:
        return ""
    return f"https://wa.me/{num2}"

def _parse_pdfs(raw_pdf_pipe: str):
    items = parse_pipe_list(clean_pdf_pipe(raw_pdf_pipe or ""))
    out = []
    for it in items:
        nm, url = normalize_pdf_item(it)
        url = canon_url(url)
        if not _is_valid_pdf_url(url):
            continue
        nm = (nm or "").strip() or pdf_name_from_url(url)
        out.append({"name": nm, "url": url})
    return out

@app.route("/<slug>", methods=["GET"])
def public_card(slug):
    profile = (request.args.get("p") or "p1").strip().lower()
    if profile not in ["p1", "p2", "p3"]:
        profile = "p1"

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    # blocco accesso P2/P3 se non attivi
    if profile == "p2" and int(ag.p2_enabled or 0) != 1:
        abort(404)
    if profile == "p3" and int(ag.p3_enabled or 0) != 1:
        abort(404)

    data = get_profile_data(ag, profile)

    # usa il template CARD che mi hai dato (card.html), ma lui usa "ag"
    # quindi costruiamo "ag" con i campi della card (senza cambiare il template)
    class Obj: pass
    ag_view = Obj()
    # campi testuali
    ag_view.slug = ag.slug
    ag_view.name = data.get("name", "") or ag.name or ""
    ag_view.company = data.get("company", "") or ""
    ag_view.role = data.get("role", "") or ""
    ag_view.bio = data.get("bio", "") or ""
    ag_view.piva = data.get("piva", "") or ""
    ag_view.sdi = data.get("sdi", "") or ""

    # media / effetti
    ag_view.photo_url = canon_url(data.get("photo_url", "") or "")
    ag_view.logo_url = canon_url(data.get("logo_url", "") or "")
    ag_view.back_media_url = canon_url(data.get("back_media_url", "") or "")

    ag_view.photo_pos_x = int(data.get("photo_pos_x", 50) or 50)
    ag_view.photo_pos_y = int(data.get("photo_pos_y", 35) or 35)
    ag_view.photo_zoom = (data.get("photo_zoom", "1.0") or "1.0")

    ag_view.orbit_spin = int(data.get("orbit_spin", 0) or 0)
    ag_view.avatar_spin = int(data.get("avatar_spin", 0) or 0)
    ag_view.logo_spin = int(data.get("logo_spin", 0) or 0)
    ag_view.allow_flip = int(data.get("allow_flip", 0) or 0)

    # contatti
    mobiles = []
    if (data.get("phone_mobile") or "").strip():
        mobiles.append((data.get("phone_mobile") or "").strip())
    if (data.get("phone_mobile2") or "").strip():
        mobiles.append((data.get("phone_mobile2") or "").strip())
    office_value = (data.get("phone_office") or "").strip()

    emails = _split_commas(data.get("emails") or "")
    websites = _split_commas(data.get("websites") or "")
    wa_link = _make_wa_link(data.get("whatsapp") or "")

    # indirizzi
    addresses = []
    for a in _split_lines(data.get("addresses") or ""):
        q = re.sub(r"\s+", "+", a.strip())
        addresses.append({
            "text": a,
            "maps": f"https://www.google.com/maps/search/?api=1&query={q}"
        })

    # gallery / videos / pdfs
    gallery = [canon_url(x) for x in parse_pipe_list(clean_media_pipe(data.get("gallery_urls") or ""))]
    videos = [canon_url(x) for x in parse_pipe_list(clean_media_pipe(data.get("video_urls") or ""))]
    pdfs = _parse_pdfs(data.get("pdf_urls") or "")

    lang = "it"
    t_func = _t_func_factory(lang)

    base = public_base_url()
    qr_url = f"{base}/qr/{ag.slug}.png"
    if profile in ["p2", "p3"]:
        qr_url = f"{base}/qr/{ag.slug}.png?p={profile}"

    return render_template(
        "card.html",
        ag=ag_view,
        lang=lang,
        t_func=t_func,
        qr_url=qr_url,
        wa_link=wa_link,
        mobiles=mobiles,
        office_value=office_value,
        emails=emails,
        websites=websites,
        addresses=addresses,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
    )


@app.route("/")
def home():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
