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

# ✅ LIMITI (come richiesto)
MAX_GALLERY_IMAGES = 15
MAX_VIDEOS = 8
MAX_PDFS = 10

# ✅ LIMITI PESO (puoi cambiare se vuoi)
MAX_IMAGE_MB = 3
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

    # P1
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
    back_media_mode = Column(String(30), default="company")  # company | personal
    back_media_url = Column(String(255), default="")

    photo_pos_x = Column(Integer, default=50)
    photo_pos_y = Column(Integer, default=35)
    photo_zoom = Column(String(20), default="1.0")

    orbit_spin = Column(Integer, default=0)
    avatar_spin = Column(Integer, default=0)
    logo_spin = Column(Integer, default=0)
    allow_flip = Column(Integer, default=0)

    gallery_urls = Column(Text, default="")   # url|url|...
    video_urls = Column(Text, default="")     # url|url|...
    pdf1_url = Column(Text, default="")       # name||url|name||url...

    # ✅ MULTI PROFILI
    p2_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")
    p3_enabled = Column(Integer, default=0)
    p3_json = Column(Text, default="{}")

    # traduzioni solo su P1
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
        add_col("p2_enabled", "INTEGER")
        add_col("p3_enabled", "INTEGER")

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

        conn.exec_driver_sql("UPDATE agents SET p2_enabled = COALESCE(p2_enabled, 0)")
        conn.exec_driver_sql("UPDATE agents SET p3_enabled = COALESCE(p3_enabled, 0)")

        # ✅ Fix username vuoti/none
        conn.exec_driver_sql("UPDATE agents SET username = COALESCE(NULLIF(username,''), slug)")

        conn.commit()

ensure_db()


# ==========================
# HELPERS
# ==========================
PROFILE_FIELDS = [
    "name", "company", "role", "bio",
    "phone_mobile", "phone_mobile2", "phone_office", "whatsapp",
    "emails", "websites", "pec", "addresses",
    "piva", "sdi",
    "facebook", "instagram", "linkedin", "tiktok", "telegram", "youtube", "spotify",
]

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

def _new_password(length=10):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    import random
    return "".join(random.choice(alphabet) for _ in range(length))

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

def get_profile_json(agent: Agent, p: str) -> dict:
    raw = "{}"
    if p == "p2":
        raw = agent.p2_json or "{}"
    elif p == "p3":
        raw = agent.p3_json or "{}"
    else:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def set_profile_json(agent: Agent, p: str, data: dict):
    js = json.dumps(data, ensure_ascii=False)
    if p == "p2":
        agent.p2_json = js
    elif p == "p3":
        agent.p3_json = js

def is_enabled(agent: Agent, p: str) -> bool:
    if p == "p2":
        return int(agent.p2_enabled or 0) == 1
    if p == "p3":
        return int(agent.p3_enabled or 0) == 1
    return True

def set_enabled(agent: Agent, p: str, v: int):
    if p == "p2":
        agent.p2_enabled = v
    elif p == "p3":
        agent.p3_enabled = v

def set_profile_data_generic(agent: Agent, p: str, form: dict):
    data = {}
    for k in PROFILE_FIELDS:
        data[k] = (form.get(k) or "").strip()
    set_profile_json(agent, p, data)
    agent.updated_at = dt.datetime.utcnow()

def safe_int(v, d):
    try:
        return int(v)
    except Exception:
        return d

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

def set_profile_data_p1(agent: Agent, form: dict):
    avatar_spin = 1 if form.get("avatar_spin") == "on" else 0
    allow_flip = 1 if form.get("allow_flip") == "on" else 0
    if avatar_spin == 1:
        allow_flip = 0
    if allow_flip == 1:
        avatar_spin = 0

    orbit_spin = 1 if form.get("orbit_spin") == "on" else 0
    logo_spin = 1 if form.get("logo_spin") == "on" else 0

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

    agent.back_media_mode = (form.get("back_media_mode") or "company").strip()

    agent.photo_pos_x = safe_int(form.get("photo_pos_x"), 50)
    agent.photo_pos_y = safe_int(form.get("photo_pos_y"), 35)

    z = (form.get("photo_zoom") or "1.0").strip()
    try:
        float(z)
        agent.photo_zoom = z
    except Exception:
        agent.photo_zoom = "1.0"

    agent.orbit_spin = orbit_spin
    agent.avatar_spin = avatar_spin
    agent.logo_spin = logo_spin
    agent.allow_flip = allow_flip

    agent.updated_at = dt.datetime.utcnow()

def _max_bytes_for_kind(kind: str) -> int:
    if kind == "images":
        return MAX_IMAGE_MB * 1024 * 1024
    if kind == "videos":
        return MAX_VIDEO_MB * 1024 * 1024
    return MAX_PDF_MB * 1024 * 1024

def save_upload(file_storage, kind: str):
    """
    Salva upload in /uploads/images|videos|pdf con controllo dimensione.
    """
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

    # salva
    file_storage.save(str(outpath))

    # check size post-save (sicuro, senza dipendere dal client)
    try:
        max_b = _max_bytes_for_kind(kind)
        size_b = os.path.getsize(str(outpath))
        if size_b > max_b:
            try:
                os.remove(str(outpath))
            except Exception:
                pass
            flash(f"File troppo grande. Limite {kind}: {max_b // (1024*1024)} MB", "error")
            return ""
    except Exception:
        # se non riesco a controllare, lo lascio salvato
        pass

    return uploads_url(rel)


# ==========================
# ✅ FAVICON ROOT
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
            p3_enabled=0,
            p3_json="{}",
            i18n_json="{}",
        )
        s.add(ag)
        s.commit()

        flash("Card creata!", "ok")
        return redirect(url_for("edit_agent", slug=slug))

    return render_template(
        "agent_form.html",
        agent=None,
        editing_profile="p1",
        i18n_data={},
        is_admin=True,
        gallery=[],
        videos=[],
        pdfs=[],
        profile_data={}
    )


@app.route("/area/edit/<slug>", methods=["GET", "POST"])
def edit_agent(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if request.method == "POST":
        set_profile_data_p1(ag, request.form)

        photo = request.files.get("photo")
        if photo and photo.filename:
            out = save_upload(photo, "images")
            if out:
                ag.photo_url = out

        logo = request.files.get("logo")
        if logo and logo.filename:
            out = save_upload(logo, "images")
            if out:
                ag.logo_url = out

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            out = save_upload(back_media, "images")
            if out:
                ag.back_media_url = out

        # GALLERY (append)
        gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
        if gallery_files:
            gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
            urls = [save_upload(f, "images") for f in gallery_files]
            urls = [u for u in urls if u]
            existing = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
            ag.gallery_urls = "|".join(existing + urls)

        # VIDEOS (append)
        video_files = [f for f in request.files.getlist("videos") if f and f.filename]
        if video_files:
            video_files = video_files[:MAX_VIDEOS]
            urls = [save_upload(f, "videos") for f in video_files]
            urls = [u for u in urls if u]
            existing = [x for x in (ag.video_urls or "").split("|") if x.strip()]
            ag.video_urls = "|".join(existing + urls)

        # PDF (slots)
        existing_pdf = parse_pdf_items(ag.pdf1_url or "")
        out = existing_pdf[:] if existing_pdf else []
        for i in range(1, MAX_PDFS + 1):
            f = request.files.get(f"pdf{i}")
            if f and f.filename:
                url = save_upload(f, "pdf")
                if not url:
                    continue
                name = secure_filename(f.filename) or f"PDF {i}"
                idx = i - 1
                while len(out) <= idx:
                    out.append({"name": "", "url": ""})
                out[idx] = {"name": name, "url": url}

        out2 = []
        for item in out:
            if item.get("url"):
                out2.append(f"{item.get('name', 'Documento')}||{item.get('url')}")
        ag.pdf1_url = "|".join(out2)

        save_i18n(ag, request.form)

        s.commit()
        flash("Salvato!", "ok")
        return redirect(url_for("edit_agent", slug=slug))

    # load i18n
    try:
        i18n_data = json.loads(ag.i18n_json or "{}")
        if not isinstance(i18n_data, dict):
            i18n_data = {}
    except Exception:
        i18n_data = {}

    gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(ag.pdf1_url or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile="p1",
        i18n_data=i18n_data,
        is_admin=True,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        profile_data={}
    )


def _admin_edit_profile_generic(slug: str, p: str):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if not is_enabled(ag, p):
        flash(f"{p.upper()} non attivo", "error")
        return redirect(url_for("edit_agent", slug=slug))

    if request.method == "POST":
        set_profile_data_generic(ag, p, request.form)
        s.commit()
        flash(f"{p.upper()} salvato!", "ok")
        return redirect(url_for(f"admin_edit_{p}", slug=slug))

    profile_data = get_profile_json(ag, p)

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile=p,
        i18n_data={},
        is_admin=True,
        gallery=[],
        videos=[],
        pdfs=[],
        profile_data=profile_data
    )

@app.route("/area/edit/<slug>/p2", methods=["GET", "POST"])
def admin_edit_p2(slug):
    return _admin_edit_profile_generic(slug, "p2")

@app.route("/area/edit/<slug>/p3", methods=["GET", "POST"])
def admin_edit_p3(slug):
    return _admin_edit_profile_generic(slug, "p3")


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

    if request.method == "POST":
        set_profile_data_p1(ag, request.form)

        photo = request.files.get("photo")
        if photo and photo.filename:
            out = save_upload(photo, "images")
            if out:
                ag.photo_url = out

        logo = request.files.get("logo")
        if logo and logo.filename:
            out = save_upload(logo, "images")
            if out:
                ag.logo_url = out

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            out = save_upload(back_media, "images")
            if out:
                ag.back_media_url = out

        gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
        if gallery_files:
            gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
            urls = [save_upload(f, "images") for f in gallery_files]
            urls = [u for u in urls if u]
            existing = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
            ag.gallery_urls = "|".join(existing + urls)

        video_files = [f for f in request.files.getlist("videos") if f and f.filename]
        if video_files:
            video_files = video_files[:MAX_VIDEOS]
            urls = [save_upload(f, "videos") for f in video_files]
            urls = [u for u in urls if u]
            existing = [x for x in (ag.video_urls or "").split("|") if x.strip()]
            ag.video_urls = "|".join(existing + urls)

        existing_pdf = parse_pdf_items(ag.pdf1_url or "")
        out = existing_pdf[:] if existing_pdf else []
        for i in range(1, MAX_PDFS + 1):
            f = request.files.get(f"pdf{i}")
            if f and f.filename:
                url = save_upload(f, "pdf")
                if not url:
                    continue
                name = secure_filename(f.filename) or f"PDF {i}"
                idx = i - 1
                while len(out) <= idx:
                    out.append({"name": "", "url": ""})
                out[idx] = {"name": name, "url": url}

        out2 = []
        for item in out:
            if item.get("url"):
                out2.append(f"{item.get('name', 'Documento')}||{item.get('url')}")
        ag.pdf1_url = "|".join(out2)

        s.commit()
        flash("Salvato!", "ok")
        return redirect(url_for("me_edit"))

    gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(ag.pdf1_url or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile="p1",
        i18n_data={},
        is_admin=False,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        profile_data={}
    )


def _me_edit_profile_generic(p: str):
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if not is_enabled(ag, p):
        flash(f"{p.upper()} non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        set_profile_data_generic(ag, p, request.form)
        s.commit()
        flash(f"{p.upper()} salvato!", "ok")
        return redirect(url_for(f"me_{p}"))

    profile_data = get_profile_json(ag, p)
    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile=p,
        i18n_data={},
        is_admin=False,
        gallery=[],
        videos=[],
        pdfs=[],
        profile_data=profile_data
    )

@app.route("/area/me/p2", methods=["GET", "POST"])
def me_p2():
    return _me_edit_profile_generic("p2")

@app.route("/area/me/p3", methods=["GET", "POST"])
def me_p3():
    return _me_edit_profile_generic("p3")


# ==========================
# ✅ ACTIVATE / DEACTIVATE P2/P3 (admin + cliente) - sempre vuoti
# ==========================
def _activate_profile(agent: Agent, p: str):
    set_enabled(agent, p, 1)
    set_profile_json(agent, p, {})  # ✅ vuoto vero
    agent.updated_at = dt.datetime.utcnow()

def _deactivate_profile(agent: Agent, p: str):
    set_enabled(agent, p, 0)
    set_profile_json(agent, p, {})  # ✅ svuota
    agent.updated_at = dt.datetime.utcnow()

@app.route("/area/admin/activate-p2/<slug>", methods=["POST"])
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
    _activate_profile(ag, "p2")
    s.commit()
    flash("P2 attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/deactivate-p2/<slug>", methods=["POST"])
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
    _deactivate_profile(ag, "p2")
    s.commit()
    flash("P2 disattivato (svuotato).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/activate-p3/<slug>", methods=["POST"])
def admin_activate_p3(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)
    _activate_profile(ag, "p3")
    s.commit()
    flash("P3 attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/deactivate-p3/<slug>", methods=["POST"])
def admin_deactivate_p3(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)
    _deactivate_profile(ag, "p3")
    s.commit()
    flash("P3 disattivato (svuotato).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/me/activate-p2", methods=["POST"])
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
    _activate_profile(ag, "p2")
    s.commit()
    flash("P2 attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/me/deactivate-p2", methods=["POST"])
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
    _deactivate_profile(ag, "p2")
    s.commit()
    flash("P2 disattivato (svuotato).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/me/activate-p3", methods=["POST"])
def me_activate_p3():
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)
    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)
    _activate_profile(ag, "p3")
    s.commit()
    flash("P3 attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/me/deactivate-p3", methods=["POST"])
def me_deactivate_p3():
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)
    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)
    _deactivate_profile(ag, "p3")
    s.commit()
    flash("P3 disattivato (svuotato).", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# ADMIN: CREDENTIALS MODAL (placeholder)
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
# ADMIN DELETE (intera card)
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
# QR PNG + VCF
# ==========================
@app.route("/qr/<slug>.png")
def qr_png(slug):
    if qrcode is None:
        abort(500)

    p = (request.args.get("p") or "").strip().lower()  # p1|p2|p3
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    base = public_base_url()
    url = f"{base}/{ag.slug}"

    if p == "p2" and is_enabled(ag, "p2"):
        url = f"{base}/{ag.slug}?p=p2"
    elif p == "p3" and is_enabled(ag, "p3"):
        url = f"{base}/{ag.slug}?p=p3"

    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    # ✅ inline (si apre al click)
    return Response(
        buf.getvalue(),
        mimetype="image/png",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="qr.png"'
        }
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
# MEDIA DELETE (solo da edit via viewer)
# ==========================
@app.route("/area/media/delete/<slug>", methods=["POST"])
def delete_media(slug):
    r = require_login()
    if r:
        return r

    t = (request.form.get("type") or "").strip()  # gallery | video | pdf
    idx = int(request.form.get("idx") or -1)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if not is_admin() and ag.slug != session.get("slug"):
        abort(403)

    if t == "gallery":
        items = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
        if 0 <= idx < len(items):
            items.pop(idx)
            ag.gallery_urls = "|".join(items)
    elif t == "video":
        items = [x for x in (ag.video_urls or "").split("|") if x.strip()]
        if 0 <= idx < len(items):
            items.pop(idx)
            ag.video_urls = "|".join(items)
    elif t == "pdf":
        items = parse_pdf_items(ag.pdf1_url or "")
        if 0 <= idx < len(items):
            items.pop(idx)
            ag.pdf1_url = "|".join([f"{x['name']}||{x['url']}" for x in items])
    else:
        abort(400)

    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Eliminato.", "ok")

    if is_admin():
        # torna sulla pagina corretta
        return redirect(url_for("edit_agent", slug=slug))
    return redirect(url_for("me_edit"))


# ==========================
# CARD PUBLIC (aggiunto P3 senza cambiare card.html)
# ==========================
@app.route("/<slug>")
def card(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    lang = (request.args.get("lang") or "it").strip().lower()
    p_key = (request.args.get("p") or "").strip().lower()  # p2 / p3

    use_profile = "p1"
    if p_key == "p2" and is_enabled(ag, "p2"):
        use_profile = "p2"
    elif p_key == "p3" and is_enabled(ag, "p3"):
        use_profile = "p3"

    # dati base da P1
    name = ag.name
    company = ag.company
    role = ag.role
    bio = ag.bio

    phone_mobile = ag.phone_mobile
    phone_mobile2 = ag.phone_mobile2
    phone_office = ag.phone_office
    whatsapp = ag.whatsapp
    emails_raw = ag.emails
    websites_raw = ag.websites
    pec = ag.pec
    addresses_raw = ag.addresses
    piva = ag.piva
    sdi = ag.sdi

    facebook = ag.facebook
    instagram = ag.instagram
    linkedin = ag.linkedin
    tiktok = ag.tiktok
    telegram = ag.telegram
    youtube = ag.youtube
    spotify = ag.spotify

    # se P2/P3 -> override SOLO campi testuali
    if use_profile in ("p2", "p3"):
        pdata = get_profile_json(ag, use_profile)
        name = pdata.get("name", "") or ""
        company = pdata.get("company", "") or ""
        role = pdata.get("role", "") or ""
        bio = pdata.get("bio", "") or ""

        phone_mobile = pdata.get("phone_mobile", "") or ""
        phone_mobile2 = pdata.get("phone_mobile2", "") or ""
        phone_office = pdata.get("phone_office", "") or ""
        whatsapp = pdata.get("whatsapp", "") or ""
        emails_raw = pdata.get("emails", "") or ""
        websites_raw = pdata.get("websites", "") or ""
        pec = pdata.get("pec", "") or ""
        addresses_raw = pdata.get("addresses", "") or ""
        piva = pdata.get("piva", "") or ""
        sdi = pdata.get("sdi", "") or ""

        facebook = pdata.get("facebook", "") or ""
        instagram = pdata.get("instagram", "") or ""
        linkedin = pdata.get("linkedin", "") or ""
        tiktok = pdata.get("tiktok", "") or ""
        telegram = pdata.get("telegram", "") or ""
        youtube = pdata.get("youtube", "") or ""
        spotify = pdata.get("spotify", "") or ""

    emails = split_csv(emails_raw or "")
    websites = split_csv(websites_raw or "")
    addresses = split_lines(addresses_raw or "")
    addr_objs = []
    for a in addresses:
        q = a.replace(" ", "+")
        addr_objs.append({"text": a, "maps": f"https://www.google.com/maps/search/?api=1&query={q}"})

    mobiles = []
    if (phone_mobile or "").strip():
        mobiles.append(phone_mobile.strip())
    if (phone_mobile2 or "").strip():
        mobiles.append(phone_mobile2.strip())

    office_value = (phone_office or "").strip()

    gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(ag.pdf1_url or "")

    wa_link = (whatsapp or "").strip()
    if wa_link and wa_link.startswith("+"):
        wa_link = "https://wa.me/" + re.sub(r"\D+", "", wa_link)

    base_url = public_base_url()
    qr_url = f"{base_url}/{ag.slug}"
    if use_profile == "p2":
        qr_url += "?p=p2"
    elif use_profile == "p3":
        qr_url += "?p=p3"

    def t_func(k):
        it = {
            "actions": "Azioni", "scan_qr": "QR", "whatsapp": "WhatsApp", "contacts": "Contatti",
            "mobile_phone": "Cellulare", "office_phone": "Ufficio", "open_website": "Sito",
            "open_maps": "Apri Maps", "data": "Dati", "vat": "P.IVA", "sdi": "SDI",
            "gallery": "Foto", "videos": "Video", "documents": "Documenti"
        }
        return it.get(k, k)

    class Obj(dict):
        __getattr__ = dict.get

    ag_view = Obj({
        "slug": ag.slug,
        "logo_url": ag.logo_url,
        "photo_url": ag.photo_url,
        "back_media_mode": ag.back_media_mode,
        "back_media_url": ag.back_media_url,
        "photo_pos_x": ag.photo_pos_x,
        "photo_pos_y": ag.photo_pos_y,
        "photo_zoom": float(ag.photo_zoom or "1.0"),
        "orbit_spin": ag.orbit_spin,
        "avatar_spin": ag.avatar_spin,
        "logo_spin": ag.logo_spin,
        "allow_flip": ag.allow_flip,
        "name": name,
        "company": company,
        "role": role,
        "bio": bio,
        "piva": piva,
        "sdi": sdi,
        "facebook": facebook,
        "instagram": instagram,
        "linkedin": linkedin,
        "tiktok": tiktok,
        "telegram": telegram,
        "youtube": youtube,
        "spotify": spotify,
    })

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
        t_func=t_func
    )


@app.route("/")
def home():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
