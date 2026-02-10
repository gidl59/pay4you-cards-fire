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

MAX_GALLERY_IMAGES = 30
MAX_VIDEOS = 10
MAX_PDFS = 12   

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

    p2_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")      # ✅ anche crop + traduzioni P2 dentro qui

    i18n_json = Column(Text, default="{}")    # P1 translations

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
        conn.exec_driver_sql("UPDATE agents SET i18n_json = COALESCE(i18n_json, '{}')")

        conn.exec_driver_sql("UPDATE agents SET photo_pos_x = COALESCE(photo_pos_x, 50)")
        conn.exec_driver_sql("UPDATE agents SET photo_pos_y = COALESCE(photo_pos_y, 35)")
        conn.exec_driver_sql("UPDATE agents SET photo_zoom = COALESCE(photo_zoom, '1.0')")

        conn.exec_driver_sql("UPDATE agents SET back_media_mode = COALESCE(back_media_mode, 'company')")
        conn.exec_driver_sql("UPDATE agents SET back_media_url = COALESCE(back_media_url, '')")

        for f in ["orbit_spin", "avatar_spin", "logo_spin", "allow_flip", "p2_enabled"]:
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

def _new_password(length=10):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    import random
    return "".join(random.choice(alphabet) for _ in range(length))


def _json_load(s: str, default):
    try:
        x = json.loads(s or "")
        return x if isinstance(x, dict) else default
    except Exception:
        return default


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
        return render_template("dashboard.html", agents=agents, is_admin=True, agent=None, pdf_max=MAX_PDFS)

    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        session.clear()
        return redirect(url_for("login"))

    return render_template("dashboard.html", agents=[ag], is_admin=False, agent=ag, pdf_max=MAX_PDFS)


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
        return redirect(url_for("edit_agent", slug=slug))

    return render_template(
        "agent_form.html",
        agent=None,
        editing_profile2=False,
        i18n_data={},
        is_admin=True,
        gallery=[],
        videos=[],
        pdfs=[],
        pdf_max=MAX_PDFS
    )


def save_i18n_p1(agent: Agent, form: dict):
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

def save_i18n_p2(agent: Agent, form: dict):
    p2 = _json_load(agent.p2_json or "{}", {})
    data = {}
    for L in ["en", "fr", "es", "de"]:
        data[L] = {
            "name": (form.get(f"name_{L}") or "").strip(),
            "company": (form.get(f"company_{L}") or "").strip(),
            "role": (form.get(f"role_{L}") or "").strip(),
            "bio": (form.get(f"bio_{L}") or "").strip(),
            "addresses": (form.get(f"addresses_{L}") or "").strip(),
        }
    p2["__i18n"] = data
    agent.p2_json = json.dumps(p2, ensure_ascii=False)

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

    def safe_int(v, d):
        try:
            return int(v)
        except Exception:
            return d

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

def set_profile_data_p2(agent: Agent, form: dict):
    # ✅ P2: tutti i campi testo + crop dentro p2_json
    data = _json_load(agent.p2_json or "{}", {})

    for k in [
        "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office", "whatsapp",
        "emails", "websites", "pec", "addresses",
        "piva", "sdi",
        "facebook", "instagram", "linkedin", "tiktok", "telegram", "youtube", "spotify"
    ]:
        data[k] = (form.get(k) or "").strip()

    # crop P2 (indipendente da P1)
    def safe_int(v, d):
        try:
            return int(v)
        except Exception:
            return d

    data["photo_pos_x"] = safe_int(form.get("photo_pos_x"), 50)
    data["photo_pos_y"] = safe_int(form.get("photo_pos_y"), 35)

    z = (form.get("photo_zoom") or "1.0").strip()
    try:
        float(z)
        data["photo_zoom"] = z
    except Exception:
        data["photo_zoom"] = "1.0"

    agent.p2_json = json.dumps(data, ensure_ascii=False)
    agent.updated_at = dt.datetime.utcnow()

def handle_media_uploads(agent: Agent):
    # ✅ media condivisi (un solo set) ma gestibili anche da P2 per comodità admin/cliente
    photo = request.files.get("photo")
    if photo and photo.filename:
        agent.photo_url = save_upload(photo, "images")

    logo = request.files.get("logo")
    if logo and logo.filename:
        agent.logo_url = save_upload(logo, "images")

    back_media = request.files.get("back_media")
    if back_media and back_media.filename:
        agent.back_media_url = save_upload(back_media, "images")

    gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
    if gallery_files:
        gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
        urls = [save_upload(f, "images") for f in gallery_files]
        urls = [u for u in urls if u]
        existing = [x for x in (agent.gallery_urls or "").split("|") if x.strip()]
        agent.gallery_urls = "|".join(existing + urls)

    video_files = [f for f in request.files.getlist("videos") if f and f.filename]
    if video_files:
        video_files = video_files[:MAX_VIDEOS]
        urls = [save_upload(f, "videos") for f in video_files]
        urls = [u for u in urls if u]
        existing = [x for x in (agent.video_urls or "").split("|") if x.strip()]
        agent.video_urls = "|".join(existing + urls)

    existing_pdf = parse_pdf_items(agent.pdf1_url or "")
    out = existing_pdf[:] if existing_pdf else []
    for i in range(1, MAX_PDFS + 1):
        f = request.files.get(f"pdf{i}")
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
            out2.append(f"{item.get('name', 'Documento')}||{item.get('url')}")
    agent.pdf1_url = "|".join(out2)


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
        handle_media_uploads(ag)
        save_i18n_p1(ag, request.form)

        s.commit()
        flash("Salvato!", "ok")
        return redirect(url_for("edit_agent", slug=slug))

    i18n_data = _json_load(ag.i18n_json or "{}", {})
    gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(ag.pdf1_url or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=False,
        i18n_data=i18n_data,
        is_admin=True,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        pdf_max=MAX_PDFS
    )


@app.route("/area/edit/<slug>/p2", methods=["GET", "POST"])
def admin_profile2(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if (ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("edit_agent", slug=slug))

    if request.method == "POST":
        set_profile_data_p2(ag, request.form)
        handle_media_uploads(ag)
        save_i18n_p2(ag, request.form)

        s.commit()
        flash("Profilo 2 salvato!", "ok")
        return redirect(url_for("admin_profile2", slug=slug))

    p2 = _json_load(ag.p2_json or "{}", {})
    i18n_data = p2.get("__i18n", {}) if isinstance(p2.get("__i18n", {}), dict) else {}

    gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(ag.pdf1_url or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=True,
        i18n_data=i18n_data,
        is_admin=True,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        pdf_max=MAX_PDFS
    )


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
        handle_media_uploads(ag)

        s.commit()
        flash("Salvato!", "ok")
        return redirect(url_for("me_edit"))

    gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(ag.pdf1_url or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=False,
        i18n_data={},
        is_admin=False,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        pdf_max=MAX_PDFS
    )


@app.route("/area/me/p2", methods=["GET", "POST"])
def me_profile2():
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    if (ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        set_profile_data_p2(ag, request.form)
        handle_media_uploads(ag)
        save_i18n_p2(ag, request.form)

        s.commit()
        flash("Profilo 2 salvato!", "ok")
        return redirect(url_for("me_profile2"))

    p2 = _json_load(ag.p2_json or "{}", {})
    i18n_data = p2.get("__i18n", {}) if isinstance(p2.get("__i18n", {}), dict) else {}

    gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(ag.pdf1_url or "")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=True,
        i18n_data=i18n_data,
        is_admin=False,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        pdf_max=MAX_PDFS
    )


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

    ag.p2_enabled = 1
    ag.p2_json = "{}"  # ✅ vuoto
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Profilo 2 attivato (vuoto).", "ok")
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

    ag.p2_enabled = 0
    ag.p2_json = "{}"
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Profilo 2 disattivato.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# ✅ ADMIN: activate / deactivate P2
# ==========================
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

    ag.p2_enabled = 1
    ag.p2_json = "{}"  # ✅ sempre vuoto
    ag.updated_at = dt.datetime.utcnow()
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

    ag.p2_enabled = 0
    ag.p2_json = "{}"
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P2 disattivato.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# ADMIN: CREDENTIALS MODAL (NO FLASH)
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
# ADMIN DELETE
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

    p = (request.args.get("p") or "").strip().lower()
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    base = public_base_url()
    url = f"{base}/{ag.slug}"
    if p == "p2" and int(ag.p2_enabled or 0) == 1:
        url = f"{base}/{ag.slug}?p=p2"

    img = qrcode.make(url)
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    filename = f"QR-{ag.slug}-{'P2' if (p=='p2') else 'P1'}.png"
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
# MEDIA DELETE
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

    # torna alla pagina corretta (P1 o P2)
    if is_admin():
        referer = request.headers.get("Referer", "")
        if "/p2" in referer:
            return redirect(url_for("admin_profile2", slug=slug))
        return redirect(url_for("edit_agent", slug=slug))

    referer = request.headers.get("Referer", "")
    if "/me/p2" in referer:
        return redirect(url_for("me_profile2"))
    return redirect(url_for("me_edit"))


# ==========================
# CARD PUBLIC (non tocchiamo ancora UI, ma P2 già pronto nei dati)
# ==========================
@app.route("/<slug>")
def card(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    lang = (request.args.get("lang") or "it").strip().lower()
    p_key = (request.args.get("p") or "").strip().lower()
    p2_enabled = int(ag.p2_enabled or 0) == 1
    use_p2 = (p_key == "p2" and p2_enabled)

    # base data
    base_data = {
        "name": ag.name,
        "company": ag.company,
        "role": ag.role,
        "bio": ag.bio,
        "photo_pos_x": ag.photo_pos_x,
        "photo_pos_y": ag.photo_pos_y,
        "photo_zoom": ag.photo_zoom or "1.0",
    }

    # P2 overrides
    if use_p2:
        p2 = _json_load(ag.p2_json or "{}", {})
        for k in ["name","company","role","bio"]:
            if (p2.get(k) or "").strip():
                base_data[k] = p2.get(k)
        # crop P2
        if isinstance(p2.get("photo_pos_x"), int):
            base_data["photo_pos_x"] = p2.get("photo_pos_x")
        if isinstance(p2.get("photo_pos_y"), int):
            base_data["photo_pos_y"] = p2.get("photo_pos_y")
        if (p2.get("photo_zoom") or "").strip():
            base_data["photo_zoom"] = p2.get("photo_zoom")

    emails = split_csv(ag.emails or "")
    websites = split_csv(ag.websites or "")
    addresses = split_lines(ag.addresses or "")
    addr_objs = []
    for a in addresses:
        q = a.replace(" ", "+")
        addr_objs.append({"text": a, "maps": f"https://www.google.com/maps/search/?api=1&query={q}"})

    mobiles = []
    if (ag.phone_mobile or "").strip():
        mobiles.append(ag.phone_mobile.strip())
    if (ag.phone_mobile2 or "").strip():
        mobiles.append(ag.phone_mobile2.strip())

    office_value = (ag.phone_office or "").strip()

    gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(ag.pdf1_url or "")

    wa_link = (ag.whatsapp or "").strip()
    if wa_link and wa_link.startswith("+"):
        wa_link = "https://wa.me/" + re.sub(r"\D+", "", wa_link)

    base_url = public_base_url()
    qr_url = f"{base_url}/{ag.slug}" + ("?p=p2" if use_p2 else "")

    def t_func(k):
        it = {
            "actions":"Azioni","scan_qr":"QR","whatsapp":"WhatsApp","contacts":"Contatti",
            "mobile_phone":"Cellulare","office_phone":"Ufficio","open_website":"Sito",
            "open_maps":"Apri Maps","data":"Dati","vat":"P.IVA","sdi":"SDI",
            "gallery":"Foto","videos":"Video","documents":"Documenti"
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
        "photo_pos_x": base_data["photo_pos_x"],
        "photo_pos_y": base_data["photo_pos_y"],
        "photo_zoom": float(base_data["photo_zoom"] or "1.0"),
        "orbit_spin": ag.orbit_spin,
        "avatar_spin": ag.avatar_spin,
        "logo_spin": ag.logo_spin,
        "allow_flip": ag.allow_flip,
        "name": base_data["name"],
        "company": base_data["company"],
        "role": base_data["role"],
        "bio": base_data["bio"],
        "piva": ag.piva,
        "sdi": ag.sdi,
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
