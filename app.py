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

    # --- P1 (storico: colonne) ---
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
    pdf1_url = Column(Text, default="")  # name||url|name||url...

    # --- P2 / P3 (JSON separati e vuoti su attivazione) ---
    p2_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")

    p3_enabled = Column(Integer, default=0)
    p3_json = Column(Text, default="{}")

    # traduzioni P1 (storico)
    i18n_json = Column(Text, default="{}")

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

        add_col("created_at", "DATETIME")
        add_col("updated_at", "DATETIME")

        add_col("p2_json", "TEXT")
        add_col("p3_json", "TEXT")
        add_col("p3_enabled", "INTEGER")

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

        for (name, coltype) in missing:
            conn.exec_driver_sql(f"ALTER TABLE agents ADD COLUMN {name} {coltype}")

        now = dt.datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        conn.exec_driver_sql("UPDATE agents SET created_at = COALESCE(created_at, :now)", {"now": now})
        conn.exec_driver_sql("UPDATE agents SET updated_at = COALESCE(updated_at, :now)", {"now": now})

        conn.exec_driver_sql("UPDATE agents SET p2_json = COALESCE(p2_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET p3_json = COALESCE(p3_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET i18n_json = COALESCE(i18n_json, '{}')")

        conn.exec_driver_sql("UPDATE agents SET photo_pos_x = COALESCE(photo_pos_x, 50)")
        conn.exec_driver_sql("UPDATE agents SET photo_pos_y = COALESCE(photo_pos_y, 35)")
        conn.exec_driver_sql("UPDATE agents SET photo_zoom = COALESCE(photo_zoom, '1.0')")

        conn.exec_driver_sql("UPDATE agents SET back_media_mode = COALESCE(back_media_mode, 'company')")
        conn.exec_driver_sql("UPDATE agents SET back_media_url = COALESCE(back_media_url, '')")

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
    """
    pdf_str: "name||url|name||url|..."
    IMPORTANT: scarta elementi senza url (così niente 'neri' e niente duplicazioni sporche)
    """
    items = []
    if not pdf_str:
        return items
    for chunk in pdf_str.split("|"):
        c = (chunk or "").strip()
        if not c:
            continue
        if "||" in c:
            name, url = c.split("||", 1)
            name = (name or "").strip() or "Documento"
            url = (url or "").strip()
            if url:
                items.append({"name": name, "url": url})
        else:
            # se non c'è separatore, assumo che sia url
            url = c.strip()
            if url:
                items.append({"name": "Documento", "url": url})
    return items

def build_pdf_string(items):
    """items: list of {name,url} -> string max MAX_PDFS senza duplicati per url"""
    out = []
    seen = set()
    for it in items:
        url = (it.get("url") or "").strip()
        name = (it.get("name") or "Documento").strip() or "Documento"
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(f"{name}||{url}")
        if len(out) >= MAX_PDFS:
            break
    return "|".join(out)

def _new_password(length=10):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    import random
    return "".join(random.choice(alphabet) for _ in range(length))

def load_json_safe(s: str) -> dict:
    try:
        d = json.loads(s or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def profile_empty_template():
    return {
        "name": "", "company": "", "role": "", "bio": "",
        "phone_mobile": "", "phone_mobile2": "", "phone_office": "",
        "whatsapp": "", "emails": "", "websites": "", "pec": "", "addresses": "",
        "piva": "", "sdi": "",
        "facebook": "", "instagram": "", "linkedin": "", "tiktok": "", "telegram": "", "youtube": "", "spotify": "",
        "photo_url": "", "logo_url": "", "back_media_mode": "company", "back_media_url": "",
        "photo_pos_x": 50, "photo_pos_y": 35, "photo_zoom": "1.0",
        "orbit_spin": 0, "avatar_spin": 0, "logo_spin": 0, "allow_flip": 0,
        "gallery_urls": "", "video_urls": "", "pdf_urls": "",
        "i18n": {"en": {}, "fr": {}, "es": {}, "de": {}},
    }

def get_profile_blob(agent: Agent, key: str) -> dict:
    """
    p1 = colonne
    p2/p3 = json separato
    """
    key = (key or "p1").lower().strip()
    if key == "p1":
        # P1 dalle colonne
        blob = profile_empty_template()
        blob.update({
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

            "photo_pos_x": int(agent.photo_pos_x or 50),
            "photo_pos_y": int(agent.photo_pos_y or 35),
            "photo_zoom": (agent.photo_zoom or "1.0"),

            "orbit_spin": int(agent.orbit_spin or 0),
            "avatar_spin": int(agent.avatar_spin or 0),
            "logo_spin": int(agent.logo_spin or 0),
            "allow_flip": int(agent.allow_flip or 0),

            "gallery_urls": agent.gallery_urls or "",
            "video_urls": agent.video_urls or "",
            "pdf_urls": agent.pdf1_url or "",
        })

        # i18n P1 storico
        blob["i18n"] = load_json_safe(agent.i18n_json or "{}") or {"en": {}, "fr": {}, "es": {}, "de": {}}
        for L in ["en", "fr", "es", "de"]:
            blob["i18n"].setdefault(L, {})
        return blob

    if key == "p2":
        d = load_json_safe(agent.p2_json or "{}")
    else:
        d = load_json_safe(agent.p3_json or "{}")

    base = profile_empty_template()
    base.update(d or {})
    # assicuro struttura i18n
    base["i18n"] = base.get("i18n") if isinstance(base.get("i18n"), dict) else {"en": {}, "fr": {}, "es": {}, "de": {}}
    for L in ["en", "fr", "es", "de"]:
        base["i18n"].setdefault(L, {})
    return base

def set_profile_blob(agent: Agent, key: str, blob: dict):
    key = (key or "p1").lower().strip()
    blob = blob if isinstance(blob, dict) else {}

    if key == "p1":
        # salva su colonne
        agent.name = (blob.get("name") or "").strip()
        agent.company = (blob.get("company") or "").strip()
        agent.role = (blob.get("role") or "").strip()
        agent.bio = (blob.get("bio") or "").strip()

        agent.phone_mobile = (blob.get("phone_mobile") or "").strip()
        agent.phone_mobile2 = (blob.get("phone_mobile2") or "").strip()
        agent.phone_office = (blob.get("phone_office") or "").strip()
        agent.whatsapp = (blob.get("whatsapp") or "").strip()
        agent.emails = (blob.get("emails") or "").strip()
        agent.websites = (blob.get("websites") or "").strip()
        agent.pec = (blob.get("pec") or "").strip()
        agent.addresses = (blob.get("addresses") or "").strip()

        agent.piva = (blob.get("piva") or "").strip()
        agent.sdi = (blob.get("sdi") or "").strip()

        agent.facebook = (blob.get("facebook") or "").strip()
        agent.instagram = (blob.get("instagram") or "").strip()
        agent.linkedin = (blob.get("linkedin") or "").strip()
        agent.tiktok = (blob.get("tiktok") or "").strip()
        agent.telegram = (blob.get("telegram") or "").strip()
        agent.youtube = (blob.get("youtube") or "").strip()
        agent.spotify = (blob.get("spotify") or "").strip()

        agent.photo_url = (blob.get("photo_url") or "").strip()
        agent.logo_url = (blob.get("logo_url") or "").strip()
        agent.back_media_mode = (blob.get("back_media_mode") or "company").strip()
        agent.back_media_url = (blob.get("back_media_url") or "").strip()

        def safe_int(v, d):
            try:
                return int(v)
            except Exception:
                return d

        agent.photo_pos_x = safe_int(blob.get("photo_pos_x"), 50)
        agent.photo_pos_y = safe_int(blob.get("photo_pos_y"), 35)

        z = (blob.get("photo_zoom") or "1.0").strip()
        try:
            float(z)
            agent.photo_zoom = z
        except Exception:
            agent.photo_zoom = "1.0"

        agent.orbit_spin = safe_int(blob.get("orbit_spin"), 0)
        agent.avatar_spin = safe_int(blob.get("avatar_spin"), 0)
        agent.logo_spin = safe_int(blob.get("logo_spin"), 0)
        agent.allow_flip = safe_int(blob.get("allow_flip"), 0)

        agent.gallery_urls = (blob.get("gallery_urls") or "").strip()
        agent.video_urls = (blob.get("video_urls") or "").strip()

        # PDF: pulizia + max + no duplicati
        items = parse_pdf_items(blob.get("pdf_urls") or "")
        agent.pdf1_url = build_pdf_string(items)

        # i18n
        i18n = blob.get("i18n") if isinstance(blob.get("i18n"), dict) else {}
        agent.i18n_json = json.dumps(i18n, ensure_ascii=False)

        agent.updated_at = dt.datetime.utcnow()
        return

    # P2/P3 su json
    out = profile_empty_template()
    out.update(blob or {})
    # pulizia pdf anche qui
    items = parse_pdf_items(out.get("pdf_urls") or "")
    out["pdf_urls"] = build_pdf_string(items)

    if key == "p2":
        agent.p2_json = json.dumps(out, ensure_ascii=False)
    else:
        agent.p3_json = json.dumps(out, ensure_ascii=False)

    agent.updated_at = dt.datetime.utcnow()

def save_i18n_into_blob(blob: dict, form: dict):
    blob = blob if isinstance(blob, dict) else {}
    i18n = blob.get("i18n") if isinstance(blob.get("i18n"), dict) else {}
    for L in ["en", "fr", "es", "de"]:
        i18n[L] = {
            "name": (form.get(f"name_{L}") or "").strip(),
            "company": (form.get(f"company_{L}") or "").strip(),
            "role": (form.get(f"role_{L}") or "").strip(),
            "bio": (form.get(f"bio_{L}") or "").strip(),
            "addresses": (form.get(f"addresses_{L}") or "").strip(),
        }
    blob["i18n"] = i18n
    return blob


# ==========================
# FAVICON
# ==========================
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.ico")


# ==========================
# STATIC UPLOADS
# ==========================
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
            p2_enabled=0,
            p3_enabled=0,
            p2_json=json.dumps(profile_empty_template(), ensure_ascii=False),
            p3_json=json.dumps(profile_empty_template(), ensure_ascii=False),
            i18n_json=json.dumps({"en": {}, "fr": {}, "es": {}, "de": {}}, ensure_ascii=False),
        )
        s.add(ag)
        s.commit()

        flash("Card creata!", "ok")
        return redirect(url_for("edit_agent_profile", slug=slug, profile="p1"))

    # form vuoto P1
    return render_template(
        "agent_form.html",
        agent=None,
        profile="p1",
        is_admin=True,
        data=profile_empty_template(),
        gallery=[],
        videos=[],
        pdfs=[],
        limits={
            "max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
            "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB
        }
    )


# ==========================
# MEDIA HELPERS per PROFILO
# ==========================
def handle_media_uploads_profile(agent: Agent, profile: str, blob: dict):
    """
    Carica media SOLO nel blob del profilo (p1 su colonne, p2/p3 su json)
    """
    # foto profilo
    photo = request.files.get("photo")
    if photo and photo.filename:
        blob["photo_url"] = save_upload(photo, "images")

    # logo
    logo = request.files.get("logo")
    if logo and logo.filename:
        blob["logo_url"] = save_upload(logo, "images")

    # background
    back_media = request.files.get("back_media")
    if back_media and back_media.filename:
        blob["back_media_url"] = save_upload(back_media, "images")

    # galleria foto
    gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
    if gallery_files:
        gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
        urls = [save_upload(f, "images") for f in gallery_files]
        urls = [u for u in urls if u]
        existing = [x for x in (blob.get("gallery_urls") or "").split("|") if x.strip()]
        combined = (existing + urls)[:MAX_GALLERY_IMAGES]
        blob["gallery_urls"] = "|".join(combined)

    # video
    video_files = [f for f in request.files.getlist("videos") if f and f.filename]
    if video_files:
        video_files = video_files[:MAX_VIDEOS]
        urls = [save_upload(f, "videos") for f in video_files]
        urls = [u for u in urls if u]
        existing = [x for x in (blob.get("video_urls") or "").split("|") if x.strip()]
        combined = (existing + urls)[:MAX_VIDEOS]
        blob["video_urls"] = "|".join(combined)

    # pdf1..pdf10 (MAX_PDFS)
    existing_items = parse_pdf_items(blob.get("pdf_urls") or "")
    out = existing_items[:]  # list
    for i in range(1, MAX_PDFS + 1):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            url = save_upload(f, "pdf")
            name = secure_filename(f.filename) or f"PDF {i}"
            idx = i - 1
            while len(out) <= idx:
                out.append({"name": "", "url": ""})
            out[idx] = {"name": name, "url": url}

    # pulizia + max + no duplicati
    blob["pdf_urls"] = build_pdf_string(out)

    return blob


def set_profile_from_form(blob: dict, form: dict):
    blob["name"] = (form.get("name") or "").strip()
    blob["company"] = (form.get("company") or "").strip()
    blob["role"] = (form.get("role") or "").strip()
    blob["bio"] = (form.get("bio") or "").strip()

    blob["phone_mobile"] = (form.get("phone_mobile") or "").strip()
    blob["phone_mobile2"] = (form.get("phone_mobile2") or "").strip()
    blob["phone_office"] = (form.get("phone_office") or "").strip()
    blob["whatsapp"] = (form.get("whatsapp") or "").strip()
    blob["emails"] = (form.get("emails") or "").strip()
    blob["websites"] = (form.get("websites") or "").strip()
    blob["pec"] = (form.get("pec") or "").strip()
    blob["addresses"] = (form.get("addresses") or "").strip()

    blob["piva"] = (form.get("piva") or "").strip()
    blob["sdi"] = (form.get("sdi") or "").strip()

    blob["facebook"] = (form.get("facebook") or "").strip()
    blob["instagram"] = (form.get("instagram") or "").strip()
    blob["linkedin"] = (form.get("linkedin") or "").strip()
    blob["tiktok"] = (form.get("tiktok") or "").strip()
    blob["telegram"] = (form.get("telegram") or "").strip()
    blob["youtube"] = (form.get("youtube") or "").strip()
    blob["spotify"] = (form.get("spotify") or "").strip()

    blob["back_media_mode"] = (form.get("back_media_mode") or "company").strip()

    def safe_int(v, d):
        try:
            return int(v)
        except Exception:
            return d

    blob["photo_pos_x"] = safe_int(form.get("photo_pos_x"), 50)
    blob["photo_pos_y"] = safe_int(form.get("photo_pos_y"), 35)

    z = (form.get("photo_zoom") or "1.0").strip()
    try:
        float(z)
        blob["photo_zoom"] = z
    except Exception:
        blob["photo_zoom"] = "1.0"

    # effetti (mutua esclusione gestita lato UI, qui salvo solo valori)
    blob["orbit_spin"] = 1 if form.get("orbit_spin") == "on" else 0
    blob["avatar_spin"] = 1 if form.get("avatar_spin") == "on" else 0
    blob["logo_spin"] = 1 if form.get("logo_spin") == "on" else 0
    blob["allow_flip"] = 1 if form.get("allow_flip") == "on" else 0

    # sicurezza: se uno è ON disabilito l'altro (ruota vs flip)
    if blob["avatar_spin"] == 1:
        blob["allow_flip"] = 0
    if blob["allow_flip"] == 1:
        blob["avatar_spin"] = 0

    return blob


# ==========================
# ADMIN: EDIT (P1/P2/P3)
# ==========================
@app.route("/area/edit/<slug>/<profile>", methods=["GET", "POST"])
def edit_agent_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    profile = (profile or "p1").lower().strip()
    if profile not in ["p1", "p2", "p3"]:
        abort(404)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    # profilo attivo?
    if profile == "p2" and int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))
    if profile == "p3" and int(ag.p3_enabled or 0) != 1:
        flash("Profilo 3 non attivo", "error")
        return redirect(url_for("dashboard"))

    blob = get_profile_blob(ag, profile)

    if request.method == "POST":
        try:
            blob = set_profile_from_form(blob, request.form)
            blob = handle_media_uploads_profile(ag, profile, blob)
            blob = save_i18n_into_blob(blob, request.form)

            set_profile_blob(ag, profile, blob)
            s.commit()

            flash("Salvato!", "ok")
            return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))

    gallery = [x for x in (blob.get("gallery_urls") or "").split("|") if x.strip()]
    videos = [x for x in (blob.get("video_urls") or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(blob.get("pdf_urls") or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        profile=profile,
        is_admin=True,
        data=blob,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        limits={
            "max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
            "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB
        }
    )


# ==========================
# AGENT SELF EDIT (P1/P2/P3)
# ==========================
@app.route("/area/me/<profile>", methods=["GET", "POST"])
def me_edit_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        return redirect(url_for("dashboard"))

    profile = (profile or "p1").lower().strip()
    if profile not in ["p1", "p2", "p3"]:
        abort(404)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if profile == "p2" and int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))
    if profile == "p3" and int(ag.p3_enabled or 0) != 1:
        flash("Profilo 3 non attivo", "error")
        return redirect(url_for("dashboard"))

    blob = get_profile_blob(ag, profile)

    if request.method == "POST":
        try:
            blob = set_profile_from_form(blob, request.form)
            blob = handle_media_uploads_profile(ag, profile, blob)
            blob = save_i18n_into_blob(blob, request.form)

            set_profile_blob(ag, profile, blob)
            s.commit()

            flash("Salvato!", "ok")
            return redirect(url_for("me_edit_profile", profile=profile))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("me_edit_profile", profile=profile))

    gallery = [x for x in (blob.get("gallery_urls") or "").split("|") if x.strip()]
    videos = [x for x in (blob.get("video_urls") or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(blob.get("pdf_urls") or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        profile=profile,
        is_admin=False,
        data=blob,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        limits={
            "max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
            "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB
        }
    )


# ==========================
# ACTIVATE / DEACTIVATE P2 / P3 (ADMIN)
# ==========================
@app.route("/area/admin/activate/<slug>/<profile>", methods=["POST"])
def admin_activate_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    profile = (profile or "").lower().strip()
    if profile not in ["p2", "p3"]:
        abort(404)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if profile == "p2":
        ag.p2_enabled = 1
        ag.p2_json = json.dumps(profile_empty_template(), ensure_ascii=False)
    else:
        ag.p3_enabled = 1
        ag.p3_json = json.dumps(profile_empty_template(), ensure_ascii=False)

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

    profile = (profile or "").lower().strip()
    if profile not in ["p2", "p3"]:
        abort(404)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if profile == "p2":
        ag.p2_enabled = 0
        ag.p2_json = json.dumps(profile_empty_template(), ensure_ascii=False)
    else:
        ag.p3_enabled = 0
        ag.p3_json = json.dumps(profile_empty_template(), ensure_ascii=False)

    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash(f"{profile.upper()} disattivato (svuotato).", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# ACTIVATE / DEACTIVATE (AGENT)
# ==========================
@app.route("/area/me/activate/<profile>", methods=["POST"])
def me_activate_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    profile = (profile or "").lower().strip()
    if profile not in ["p2", "p3"]:
        abort(404)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if profile == "p2":
        ag.p2_enabled = 1
        ag.p2_json = json.dumps(profile_empty_template(), ensure_ascii=False)
    else:
        ag.p3_enabled = 1
        ag.p3_json = json.dumps(profile_empty_template(), ensure_ascii=False)

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

    profile = (profile or "").lower().strip()
    if profile not in ["p2", "p3"]:
        abort(404)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if profile == "p2":
        ag.p2_enabled = 0
        ag.p2_json = json.dumps(profile_empty_template(), ensure_ascii=False)
    else:
        ag.p3_enabled = 0
        ag.p3_json = json.dumps(profile_empty_template(), ensure_ascii=False)

    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash(f"{profile.upper()} disattivato (svuotato).", "ok")
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
# PDF PURGE TOTALE (Vero)
# ==========================
@app.route("/area/admin/purge_pdfs", methods=["POST"])
def purge_pdfs_all():
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    # 1) elimina file fisici
    try:
        for p in SUBDIR_PDF.glob("*"):
            if p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    # 2) pulizia DB P1/P2/P3
    s = db()
    agents = s.query(Agent).all()
    for ag in agents:
        ag.pdf1_url = ""

        b2 = get_profile_blob(ag, "p2")
        b3 = get_profile_blob(ag, "p3")
        b2["pdf_urls"] = ""
        b3["pdf_urls"] = ""
        set_profile_blob(ag, "p2", b2)
        set_profile_blob(ag, "p3", b3)

        ag.updated_at = dt.datetime.utcnow()
    s.commit()

    flash("Eliminati tutti i PDF (file + DB) per tutti gli agenti.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# MEDIA DELETE (per profilo)
# ==========================
@app.route("/area/media/delete/<slug>/<profile>", methods=["POST"])
def delete_media(slug, profile):
    r = require_login()
    if r:
        return r

    profile = (profile or "p1").lower().strip()
    if profile not in ["p1", "p2", "p3"]:
        abort(404)

    t = (request.form.get("type") or "").strip()  # gallery | video | pdf
    idx = int(request.form.get("idx") or -1)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if not is_admin() and ag.slug != session.get("slug"):
        abort(403)

    blob = get_profile_blob(ag, profile)

    if t == "gallery":
        items = [x for x in (blob.get("gallery_urls") or "").split("|") if x.strip()]
        if 0 <= idx < len(items):
            items.pop(idx)
        blob["gallery_urls"] = "|".join(items)

    elif t == "video":
        items = [x for x in (blob.get("video_urls") or "").split("|") if x.strip()]
        if 0 <= idx < len(items):
            items.pop(idx)
        blob["video_urls"] = "|".join(items)

    elif t == "pdf":
        items = parse_pdf_items(blob.get("pdf_urls") or "")
        if 0 <= idx < len(items):
            items.pop(idx)
        blob["pdf_urls"] = build_pdf_string(items)  # pulizia + no neri + max 10

    else:
        abort(400)

    set_profile_blob(ag, profile, blob)
    s.commit()
    flash("Eliminato.", "ok")

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

    p = (request.args.get("p") or "p1").strip().lower()
    if p not in ["p1", "p2", "p3"]:
        p = "p1"

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

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

    filename = f"QR-{ag.slug}-{p.upper()}.png"
    # IMPORTANT: niente attachment (così si apre al click)
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
# CARD PUBLIC (NON TOCCO ORA)
# ==========================
@app.route("/<slug>")
def card(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    # (la tua card.html non la tocchiamo adesso)
    return f"Card pubblica: {slug}"


@app.route("/")
def home():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
