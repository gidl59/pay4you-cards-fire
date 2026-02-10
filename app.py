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
MAX_PDFS = 30  # ✅ tu hai 22 pdf → ok

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

    # ===== P1 data =====
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

    # ===== P2 switch + JSON base fields =====
    p2_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")

    # ✅ P2 media separati
    p2_photo_url = Column(String(255), default="")
    p2_logo_url = Column(String(255), default="")
    p2_back_media_mode = Column(String(30), default="company")
    p2_back_media_url = Column(String(255), default="")
    p2_photo_pos_x = Column(Integer, default=50)
    p2_photo_pos_y = Column(Integer, default=35)
    p2_photo_zoom = Column(String(20), default="1.0")
    p2_gallery_urls = Column(Text, default="")
    p2_video_urls = Column(Text, default="")
    p2_pdf1_url = Column(Text, default="")

    # ===== translations (shared for both; applicate ai dati correnti P1/P2) =====
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

        # ✅ P2 media columns (se mancano)
        add_col("p2_photo_url", "TEXT")
        add_col("p2_logo_url", "TEXT")
        add_col("p2_back_media_mode", "TEXT")
        add_col("p2_back_media_url", "TEXT")
        add_col("p2_photo_pos_x", "INTEGER")
        add_col("p2_photo_pos_y", "INTEGER")
        add_col("p2_photo_zoom", "TEXT")
        add_col("p2_gallery_urls", "TEXT")
        add_col("p2_video_urls", "TEXT")
        add_col("p2_pdf1_url", "TEXT")

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

        # defaults P2 media
        conn.exec_driver_sql("UPDATE agents SET p2_back_media_mode = COALESCE(p2_back_media_mode, 'company')")
        conn.exec_driver_sql("UPDATE agents SET p2_back_media_url = COALESCE(p2_back_media_url, '')")
        conn.exec_driver_sql("UPDATE agents SET p2_photo_pos_x = COALESCE(p2_photo_pos_x, 50)")
        conn.exec_driver_sql("UPDATE agents SET p2_photo_pos_y = COALESCE(p2_photo_pos_y, 35)")
        conn.exec_driver_sql("UPDATE agents SET p2_photo_zoom = COALESCE(p2_photo_zoom, '1.0')")
        conn.exec_driver_sql("UPDATE agents SET p2_gallery_urls = COALESCE(p2_gallery_urls, '')")
        conn.exec_driver_sql("UPDATE agents SET p2_video_urls = COALESCE(p2_video_urls, '')")
        conn.exec_driver_sql("UPDATE agents SET p2_pdf1_url = COALESCE(p2_pdf1_url, '')")
        conn.exec_driver_sql("UPDATE agents SET p2_photo_url = COALESCE(p2_photo_url, '')")
        conn.exec_driver_sql("UPDATE agents SET p2_logo_url = COALESCE(p2_logo_url, '')")

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

def safe_int(v, d):
    try:
        return int(v)
    except Exception:
        return d

def safe_float_str(v, d="1.0"):
    vv = (v or d).strip()
    try:
        float(vv)
        return vv
    except Exception:
        return d

def get_accept_lang():
    # es: "it-IT,it;q=0.9,en;q=0.8"
    hdr = (request.headers.get("Accept-Language") or "").lower()
    if not hdr:
        return "it"
    # prendi primo token
    first = hdr.split(",")[0].strip()
    if "-" in first:
        first = first.split("-")[0].strip()
    if first in ("it", "en", "fr", "es", "de"):
        return first
    return "it"

def load_json_dict(s: str):
    try:
        d = json.loads(s or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


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

    return render_template("login.html")  # qui devi mettere favicon nel template login.html


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
        current_profile="p1",
        max_pdfs=MAX_PDFS,
        form_data={},
        form_media={},
        i18n_data={},
        is_admin=True,
        gallery=[], videos=[], pdfs=[]
    )


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
    agent.photo_zoom = safe_float_str(form.get("photo_zoom"), "1.0")

    agent.updated_at = dt.datetime.utcnow()


def set_profile_data_p2(agent: Agent, form: dict):
    # JSON base fields
    data = {}
    for k in [
        "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office", "whatsapp",
        "emails", "websites", "pec", "addresses",
        "piva", "sdi",
        "facebook", "instagram", "linkedin", "tiktok", "telegram", "youtube", "spotify"
    ]:
        data[k] = (form.get(k) or "").strip()
    agent.p2_json = json.dumps(data, ensure_ascii=False)

    # media/crop fields
    agent.p2_back_media_mode = (form.get("back_media_mode") or agent.p2_back_media_mode or "company").strip()
    agent.p2_photo_pos_x = safe_int(form.get("photo_pos_x"), agent.p2_photo_pos_x or 50)
    agent.p2_photo_pos_y = safe_int(form.get("photo_pos_y"), agent.p2_photo_pos_y or 35)
    agent.p2_photo_zoom = safe_float_str(form.get("photo_zoom"), agent.p2_photo_zoom or "1.0")

    agent.updated_at = dt.datetime.utcnow()


def _get_form_data_for(agent: Agent, editing_profile2: bool):
    if not agent:
        return {}, {}

    if not editing_profile2:
        form_data = {
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
        form_media = {
            "photo_url": agent.photo_url or "",
            "logo_url": agent.logo_url or "",
            "back_media_url": agent.back_media_url or "",
            "back_media_mode": agent.back_media_mode or "company",
            "photo_pos_x": agent.photo_pos_x or 50,
            "photo_pos_y": agent.photo_pos_y or 35,
            "photo_zoom": agent.photo_zoom or "1.0",
        }
        return form_data, form_media

    # P2
    p2 = load_json_dict(agent.p2_json or "{}")
    form_data = {k: (p2.get(k) or "") for k in [
        "name","company","role","bio","phone_mobile","phone_mobile2","phone_office","whatsapp",
        "emails","websites","pec","addresses","piva","sdi",
        "facebook","instagram","linkedin","tiktok","telegram","youtube","spotify"
    ]}

    form_media = {
        "photo_url": agent.p2_photo_url or "",
        "logo_url": agent.p2_logo_url or "",
        "back_media_url": agent.p2_back_media_url or "",
        "back_media_mode": agent.p2_back_media_mode or "company",
        "photo_pos_x": agent.p2_photo_pos_x or 50,
        "photo_pos_y": agent.p2_photo_pos_y or 35,
        "photo_zoom": agent.p2_photo_zoom or "1.0",
    }
    return form_data, form_media


def _get_media_lists(agent: Agent, profile: str):
    if not agent:
        return [], [], []
    if profile == "p2":
        gallery = [x for x in (agent.p2_gallery_urls or "").split("|") if x.strip()]
        videos = [x for x in (agent.p2_video_urls or "").split("|") if x.strip()]
        pdfs = parse_pdf_items(agent.p2_pdf1_url or "")
        return gallery, videos, pdfs
    gallery = [x for x in (agent.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (agent.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(agent.pdf1_url or "")
    return gallery, videos, pdfs


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
            ag.photo_url = save_upload(photo, "images")

        logo = request.files.get("logo")
        if logo and logo.filename:
            ag.logo_url = save_upload(logo, "images")

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            ag.back_media_url = save_upload(back_media, "images")

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

    i18n_data = load_json_dict(ag.i18n_json or "{}")
    form_data, form_media = _get_form_data_for(ag, editing_profile2=False)
    gallery, videos, pdfs = _get_media_lists(ag, "p1")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=False,
        current_profile="p1",
        max_pdfs=MAX_PDFS,
        form_data=form_data,
        form_media=form_media,
        i18n_data=i18n_data,
        is_admin=True,
        gallery=gallery, videos=videos, pdfs=pdfs
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

        photo = request.files.get("photo")
        if photo and photo.filename:
            ag.p2_photo_url = save_upload(photo, "images")

        logo = request.files.get("logo")
        if logo and logo.filename:
            ag.p2_logo_url = save_upload(logo, "images")

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            ag.p2_back_media_url = save_upload(back_media, "images")

        gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
        if gallery_files:
            gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
            urls = [save_upload(f, "images") for f in gallery_files]
            urls = [u for u in urls if u]
            existing = [x for x in (ag.p2_gallery_urls or "").split("|") if x.strip()]
            ag.p2_gallery_urls = "|".join(existing + urls)

        video_files = [f for f in request.files.getlist("videos") if f and f.filename]
        if video_files:
            video_files = video_files[:MAX_VIDEOS]
            urls = [save_upload(f, "videos") for f in video_files]
            urls = [u for u in urls if u]
            existing = [x for x in (ag.p2_video_urls or "").split("|") if x.strip()]
            ag.p2_video_urls = "|".join(existing + urls)

        existing_pdf = parse_pdf_items(ag.p2_pdf1_url or "")
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
        ag.p2_pdf1_url = "|".join(out2)

        save_i18n(ag, request.form)

        s.commit()
        flash("Profilo 2 salvato!", "ok")
        return redirect(url_for("admin_profile2", slug=slug))

    i18n_data = load_json_dict(ag.i18n_json or "{}")
    form_data, form_media = _get_form_data_for(ag, editing_profile2=True)
    gallery, videos, pdfs = _get_media_lists(ag, "p2")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=True,
        current_profile="p2",
        max_pdfs=MAX_PDFS,
        form_data=form_data,
        form_media=form_media,
        i18n_data=i18n_data,
        is_admin=True,
        gallery=gallery, videos=videos, pdfs=pdfs
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

        photo = request.files.get("photo")
        if photo and photo.filename:
            ag.photo_url = save_upload(photo, "images")

        logo = request.files.get("logo")
        if logo and logo.filename:
            ag.logo_url = save_upload(logo, "images")

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            ag.back_media_url = save_upload(back_media, "images")

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
        return redirect(url_for("me_edit"))

    i18n_data = load_json_dict(ag.i18n_json or "{}")
    form_data, form_media = _get_form_data_for(ag, editing_profile2=False)
    gallery, videos, pdfs = _get_media_lists(ag, "p1")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=False,
        current_profile="p1",
        max_pdfs=MAX_PDFS,
        form_data=form_data,
        form_media=form_media,
        i18n_data=i18n_data,
        is_admin=False,
        gallery=gallery, videos=videos, pdfs=pdfs
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

        photo = request.files.get("photo")
        if photo and photo.filename:
            ag.p2_photo_url = save_upload(photo, "images")

        logo = request.files.get("logo")
        if logo and logo.filename:
            ag.p2_logo_url = save_upload(logo, "images")

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            ag.p2_back_media_url = save_upload(back_media, "images")

        gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
        if gallery_files:
            gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
            urls = [save_upload(f, "images") for f in gallery_files]
            urls = [u for u in urls if u]
            existing = [x for x in (ag.p2_gallery_urls or "").split("|") if x.strip()]
            ag.p2_gallery_urls = "|".join(existing + urls)

        video_files = [f for f in request.files.getlist("videos") if f and f.filename]
        if video_files:
            video_files = video_files[:MAX_VIDEOS]
            urls = [save_upload(f, "videos") for f in video_files]
            urls = [u for u in urls if u]
            existing = [x for x in (ag.p2_video_urls or "").split("|") if x.strip()]
            ag.p2_video_urls = "|".join(existing + urls)

        existing_pdf = parse_pdf_items(ag.p2_pdf1_url or "")
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
        ag.p2_pdf1_url = "|".join(out2)

        save_i18n(ag, request.form)

        s.commit()
        flash("Profilo 2 salvato!", "ok")
        return redirect(url_for("me_profile2"))

    i18n_data = load_json_dict(ag.i18n_json or "{}")
    form_data, form_media = _get_form_data_for(ag, editing_profile2=True)
    gallery, videos, pdfs = _get_media_lists(ag, "p2")

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=True,
        current_profile="p2",
        max_pdfs=MAX_PDFS,
        form_data=form_data,
        form_media=form_media,
        i18n_data=i18n_data,
        is_admin=False,
        gallery=gallery, videos=videos, pdfs=pdfs
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
    ag.p2_json = "{}"              # ✅ vuoto
    ag.p2_photo_url = ""           # ✅ vuoto
    ag.p2_logo_url = ""
    ag.p2_back_media_url = ""
    ag.p2_gallery_urls = ""
    ag.p2_video_urls = ""
    ag.p2_pdf1_url = ""
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
    ag.p2_photo_url = ""
    ag.p2_logo_url = ""
    ag.p2_back_media_url = ""
    ag.p2_gallery_urls = ""
    ag.p2_video_urls = ""
    ag.p2_pdf1_url = ""
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Profilo 2 disattivato.", "ok")
    return redirect(url_for("dashboard"))


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
    ag.p2_json = "{}"
    ag.p2_photo_url = ""
    ag.p2_logo_url = ""
    ag.p2_back_media_url = ""
    ag.p2_gallery_urls = ""
    ag.p2_video_urls = ""
    ag.p2_pdf1_url = ""
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
    ag.p2_photo_url = ""
    ag.p2_logo_url = ""
    ag.p2_back_media_url = ""
    ag.p2_gallery_urls = ""
    ag.p2_video_urls = ""
    ag.p2_pdf1_url = ""
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
# MEDIA DELETE (P1/P2)
# ==========================
@app.route("/area/media/delete/<slug>", methods=["POST"])
def delete_media(slug):
    r = require_login()
    if r:
        return r

    t = (request.form.get("type") or "").strip()      # gallery | video | pdf
    idx = int(request.form.get("idx") or -1)
    profile = (request.form.get("profile") or "p1").strip().lower()

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if not is_admin() and ag.slug != session.get("slug"):
        abort(403)

    if profile not in ("p1", "p2"):
        profile = "p1"

    if profile == "p2" and int(ag.p2_enabled or 0) != 1:
        abort(400)

    # choose field set
    if profile == "p2":
        if t == "gallery":
            items = [x for x in (ag.p2_gallery_urls or "").split("|") if x.strip()]
            if 0 <= idx < len(items):
                items.pop(idx)
                ag.p2_gallery_urls = "|".join(items)
        elif t == "video":
            items = [x for x in (ag.p2_video_urls or "").split("|") if x.strip()]
            if 0 <= idx < len(items):
                items.pop(idx)
                ag.p2_video_urls = "|".join(items)
        elif t == "pdf":
            items = parse_pdf_items(ag.p2_pdf1_url or "")
            if 0 <= idx < len(items):
                items.pop(idx)
                ag.p2_pdf1_url = "|".join([f"{x['name']}||{x['url']}" for x in items])
        else:
            abort(400)
    else:
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
        if profile == "p2":
            return redirect(url_for("admin_profile2", slug=slug))
        return redirect(url_for("edit_agent", slug=slug))
    else:
        if profile == "p2":
            return redirect(url_for("me_profile2"))
        return redirect(url_for("me_edit"))


# ==========================
# CARD PUBLIC (lingua auto + P1/P2)
# ==========================
@app.route("/<slug>")
def card(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    p_key = (request.args.get("p") or "").strip().lower()
    p2_enabled = int(ag.p2_enabled or 0) == 1
    use_p2 = (p_key == "p2" and p2_enabled)

    # ✅ lingua: ?lang=xx oppure dal telefono (Accept-Language)
    lang = (request.args.get("lang") or "").strip().lower()
    if lang not in ("it", "en", "fr", "es", "de"):
        lang = get_accept_lang()

    i18n = load_json_dict(ag.i18n_json or "{}")
    tr = i18n.get(lang, {}) if isinstance(i18n.get(lang, {}), dict) else {}

    # base fields depending on profile
    if use_p2:
        p2 = load_json_dict(ag.p2_json or "{}")
        base = {
            "name": p2.get("name",""),
            "company": p2.get("company",""),
            "role": p2.get("role",""),
            "bio": p2.get("bio",""),
            "addresses": p2.get("addresses",""),
            "piva": p2.get("piva",""),
            "sdi": p2.get("sdi",""),
        }
        emails = split_csv(p2.get("emails",""))
        websites = split_csv(p2.get("websites",""))
        whatsapp_raw = (p2.get("whatsapp","") or "").strip()
        mobiles = [x for x in [p2.get("phone_mobile","").strip(), p2.get("phone_mobile2","").strip()] if x]
        office_value = (p2.get("phone_office","") or "").strip()

        gallery = [x for x in (ag.p2_gallery_urls or "").split("|") if x.strip()]
        videos = [x for x in (ag.p2_video_urls or "").split("|") if x.strip()]
        pdfs = parse_pdf_items(ag.p2_pdf1_url or "")

        photo_url = ag.p2_photo_url or ""
        logo_url = ag.p2_logo_url or ""
        back_media_mode = ag.p2_back_media_mode or "company"
        back_media_url = ag.p2_back_media_url or ""
        photo_pos_x = ag.p2_photo_pos_x or 50
        photo_pos_y = ag.p2_photo_pos_y or 35
        photo_zoom = float(ag.p2_photo_zoom or "1.0")
    else:
        base = {
            "name": ag.name or "",
            "company": ag.company or "",
            "role": ag.role or "",
            "bio": ag.bio or "",
            "addresses": ag.addresses or "",
            "piva": ag.piva or "",
            "sdi": ag.sdi or "",
        }
        emails = split_csv(ag.emails or "")
        websites = split_csv(ag.websites or "")
        whatsapp_raw = (ag.whatsapp or "").strip()
        mobiles = [x for x in [(ag.phone_mobile or "").strip(), (ag.phone_mobile2 or "").strip()] if x]
        office_value = (ag.phone_office or "").strip()

        gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
        videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
        pdfs = parse_pdf_items(ag.pdf1_url or "")

        photo_url = ag.photo_url or ""
        logo_url = ag.logo_url or ""
        back_media_mode = ag.back_media_mode or "company"
        back_media_url = ag.back_media_url or ""
        photo_pos_x = ag.photo_pos_x or 50
        photo_pos_y = ag.photo_pos_y or 35
        photo_zoom = float(ag.photo_zoom or "1.0")

    # apply translations if present (solo su name/company/role/bio/addresses)
    def pick(k):
        v_tr = (tr.get(k) or "").strip()
        return v_tr if v_tr else (base.get(k) or "")

    addresses_text = pick("addresses")
    addresses = split_lines(addresses_text)
    addr_objs = []
    for a in addresses:
        q = a.replace(" ", "+")
        addr_objs.append({"text": a, "maps": f"https://www.google.com/maps/search/?api=1&query={q}"})

    wa_link = whatsapp_raw
    if wa_link and wa_link.startswith("+"):
        wa_link = "https://wa.me/" + re.sub(r"\D+", "", wa_link)

    base_url = public_base_url()
    qr_url = f"{base_url}/{ag.slug}" + ("?p=p2" if use_p2 else "")

    class Obj(dict):
        __getattr__ = dict.get

    ag_view = Obj({
        "slug": ag.slug,
        "logo_url": logo_url,
        "photo_url": photo_url,
        "back_media_mode": back_media_mode,
        "back_media_url": back_media_url,
        "photo_pos_x": photo_pos_x,
        "photo_pos_y": photo_pos_y,
        "photo_zoom": photo_zoom,
        "orbit_spin": ag.orbit_spin,
        "avatar_spin": ag.avatar_spin,
        "logo_spin": ag.logo_spin,
        "allow_flip": ag.allow_flip,
        "name": pick("name"),
        "company": pick("company"),
        "role": pick("role"),
        "bio": pick("bio"),
        "piva": base.get("piva",""),
        "sdi": base.get("sdi",""),
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
    )


@app.route("/")
def home():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
