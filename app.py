import os
import re
import json
import uuid
import datetime as dt
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, abort, flash, send_from_directory
)

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime
)
from sqlalchemy.orm import declarative_base, sessionmaker
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

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

# Directories
UPLOADS_DIR = Path(PERSIST_UPLOADS_DIR)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

SUBDIR_IMG = UPLOADS_DIR / "images"
SUBDIR_VID = UPLOADS_DIR / "videos"
SUBDIR_PDF = UPLOADS_DIR / "pdf"
for d in (SUBDIR_IMG, SUBDIR_VID, SUBDIR_PDF):
    d.mkdir(parents=True, exist_ok=True)

# Flask
app = Flask(__name__)
app.secret_key = APP_SECRET

# SQLAlchemy
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

    # core
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

    # Profile2
    p2_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")  # JSON con campi del profilo 2 (VUOTO di default)

    # i18n
    i18n_json = Column(Text, default="{}")  # {"en": {...}, "fr": {...} ...}

    created_at = Column(DateTime, default=lambda: dt.datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: dt.datetime.utcnow())


# ==========================
# DB INIT + MIGRATION (SQLite)
# ==========================
def _sqlite_table_columns(conn, table_name: str):
    # SQLAlchemy 2.x: usare exec_driver_sql per query raw SQLite
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    # PRAGMA table_info ritorna colonne: cid, name, type, notnull, dflt_value, pk
    return {r[1] for r in rows}


def ensure_db():
    Base.metadata.create_all(engine)

    if not DATABASE_URL.startswith("sqlite"):
        return

    # Auto-add missing columns in SQLite (safe migrations)
    with engine.connect() as conn:
        cols = _sqlite_table_columns(conn, "agents")

        # Columns that might be missing if DB was created with older schema
        missing = []

        def add_col(name, coltype, default_sql=None):
            nonlocal missing
            if name not in cols:
                missing.append((name, coltype, default_sql))

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

        # Add them
        for (name, coltype, default_sql) in missing:
            sql = f"ALTER TABLE agents ADD COLUMN {name} {coltype}"
            conn.execute(sql)

        # Backfill defaults for new cols
        # (SQLite doesn't apply default retroactively)
        now = dt.datetime.utcnow().isoformat(sep=" ", timespec="seconds")

        if "created_at" in missing or "created_at" not in cols:
            conn.execute(f"UPDATE agents SET created_at = COALESCE(created_at, '{now}')")
        if "updated_at" in missing or "updated_at" not in cols:
            conn.execute(f"UPDATE agents SET updated_at = COALESCE(updated_at, '{now}')")

        # JSON defaults
        if "p2_json" in missing or "p2_json" not in cols:
            conn.execute("UPDATE agents SET p2_json = COALESCE(p2_json, '{}')")
        if "i18n_json" in missing or "i18n_json" not in cols:
            conn.execute("UPDATE agents SET i18n_json = COALESCE(i18n_json, '{}')")

        # Numeric defaults
        if "photo_pos_x" in missing or "photo_pos_x" not in cols:
            conn.execute("UPDATE agents SET photo_pos_x = COALESCE(photo_pos_x, 50)")
        if "photo_pos_y" in missing or "photo_pos_y" not in cols:
            conn.execute("UPDATE agents SET photo_pos_y = COALESCE(photo_pos_y, 35)")
        if "photo_zoom" in missing or "photo_zoom" not in cols:
            conn.execute("UPDATE agents SET photo_zoom = COALESCE(photo_zoom, '1.0')")

        if "back_media_mode" in missing or "back_media_mode" not in cols:
            conn.execute("UPDATE agents SET back_media_mode = COALESCE(back_media_mode, 'company')")
        if "back_media_url" in missing or "back_media_url" not in cols:
            conn.execute("UPDATE agents SET back_media_url = COALESCE(back_media_url, '')")

        for f in ["orbit_spin", "avatar_spin", "logo_spin", "allow_flip", "p2_enabled"]:
            if f in missing or f not in cols:
                conn.execute(f"UPDATE agents SET {f} = COALESCE({f}, 0)")

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
    # If BASE_URL not set, derive from request host
    if BASE_URL:
        return BASE_URL
    # fallback: scheme://host
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
    # accept domain without scheme
    return "https://" + u

def uploads_url(rel_path: str) -> str:
    # Served from /uploads/...
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

def get_profile_data(agent: Agent, profile: str):
    """
    profile = "p1" | "p2"
    returns dict with fields for rendering/editing
    """
    if profile == "p2":
        try:
            data = json.loads(agent.p2_json or "{}")
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        # IMPORTANT: P2 starts empty (no auto copy). We only inject derived readonly fields.
        data["_p2"] = True
        return data

    # p1
    return {
        "_p2": False,
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

def set_profile_data(agent: Agent, profile: str, form: dict):
    """
    Saves P1 on columns or P2 inside p2_json.
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

    if profile == "p2":
        # Only save fields from form, do NOT copy P1
        data = {}
        for k in [
            "name","company","role","bio",
            "phone_mobile","phone_mobile2","phone_office","whatsapp",
            "emails","websites","pec","addresses",
            "piva","sdi",
            "facebook","instagram","linkedin","tiktok","telegram","youtube","spotify"
        ]:
            data[k] = (form.get(k) or "").strip()

        agent.p2_json = json.dumps(data, ensure_ascii=False)
        agent.updated_at = dt.datetime.utcnow()
        return

    # P1 (columns)
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

    # Images settings
    agent.back_media_mode = (form.get("back_media_mode") or "company").strip()
    agent.photo_pos_x = int(form.get("photo_pos_x") or 50)
    agent.photo_pos_y = int(form.get("photo_pos_y") or 35)
    agent.photo_zoom = str(form.get("photo_zoom") or "1.0")

    agent.orbit_spin = orbit_spin
    agent.avatar_spin = avatar_spin
    agent.logo_spin = logo_spin
    agent.allow_flip = allow_flip

    agent.updated_at = dt.datetime.utcnow()


def save_i18n(agent: Agent, form: dict):
    data = {}
    for L in ["en","fr","es","de"]:
        data[L] = {
            "name": (form.get(f"name_{L}") or "").strip(),
            "company": (form.get(f"company_{L}") or "").strip(),
            "role": (form.get(f"role_{L}") or "").strip(),
            "bio": (form.get(f"bio_{L}") or "").strip(),
            "addresses": (form.get(f"addresses_{L}") or "").strip(),
        }
    agent.i18n_json = json.dumps(data, ensure_ascii=False)


# ==========================
# STATIC UPLOADS
# ==========================
@app.route("/uploads/<path:filename>")
def serve_uploads(filename):
    # /uploads/... maps to PERSIST_UPLOADS_DIR
    return send_from_directory(str(UPLOADS_DIR), filename)


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
        agents = s.query(Agent).order_by(Agent.created_at.desc()).all()
        return render_template("admin_list.html", agents=agents, is_admin=True, agent=None)
    else:
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
        return redirect(url_for("edit_agent", slug=slug))

    return render_template("agent_form.html", agent=None, editing_profile2=False, i18n_data={})


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
        # save fields P1
        set_profile_data(ag, "p1", request.form)

        # uploads (P1 only)
        photo = request.files.get("photo")
        if photo and photo.filename:
            ag.photo_url = save_upload(photo, "images")

        logo = request.files.get("logo")
        if logo and logo.filename:
            ag.logo_url = save_upload(logo, "images")

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            ag.back_media_url = save_upload(back_media, "images")

        # gallery overwrite if uploaded
        gallery_files = request.files.getlist("gallery")
        gallery_files = [f for f in gallery_files if f and f.filename]
        if gallery_files:
            if len(gallery_files) > MAX_GALLERY_IMAGES:
                gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
            urls = [save_upload(f, "images") for f in gallery_files]
            ag.gallery_urls = "|".join([u for u in urls if u])

        # videos overwrite if uploaded
        video_files = request.files.getlist("videos")
        video_files = [f for f in video_files if f and f.filename]
        if video_files:
            if len(video_files) > MAX_VIDEOS:
                video_files = video_files[:MAX_VIDEOS]
            urls = [save_upload(f, "videos") for f in video_files]
            ag.video_urls = "|".join([u for u in urls if u])

        # pdf append/overwrite per slot
        existing = parse_pdf_items(ag.pdf1_url or "")
        existing_map = {i: existing[i] for i in range(len(existing))}
        # We store as list, add/replace by index from 1..12
        out = existing[:] if existing else []
        for i in range(1, MAX_PDFS + 1):
            f = request.files.get(f"pdf{i}")
            if f and f.filename:
                url = save_upload(f, "pdf")
                name = secure_filename(f.filename) or f"PDF {i}"
                # place in slot i-1
                idx = i - 1
                while len(out) <= idx:
                    out.append({"name": "", "url": ""})
                out[idx] = {"name": name, "url": url}

        # cleanup empties and serialize
        out2 = []
        for item in out:
            if item.get("url"):
                out2.append(f"{item.get('name','Documento')}||{item.get('url')}")
        ag.pdf1_url = "|".join(out2)

        # i18n (admin only)
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

    return render_template("agent_form.html", agent=ag, editing_profile2=False, i18n_data=i18n_data)


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
        set_profile_data(ag, "p2", request.form)
        s.commit()
        flash("Profilo 2 salvato!", "ok")
        return redirect(url_for("admin_profile2", slug=slug))

    # i18n not needed for p2 in this version (keep simple)
    return render_template("agent_form.html", agent=ag, editing_profile2=True, i18n_data={})


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
        set_profile_data(ag, "p1", request.form)

        photo = request.files.get("photo")
        if photo and photo.filename:
            ag.photo_url = save_upload(photo, "images")

        logo = request.files.get("logo")
        if logo and logo.filename:
            ag.logo_url = save_upload(logo, "images")

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            ag.back_media_url = save_upload(back_media, "images")

        gallery_files = request.files.getlist("gallery")
        gallery_files = [f for f in gallery_files if f and f.filename]
        if gallery_files:
            if len(gallery_files) > MAX_GALLERY_IMAGES:
                gallery_files = gallery_files[:MAX_GALLERY_IMAGES]
            urls = [save_upload(f, "images") for f in gallery_files]
            ag.gallery_urls = "|".join([u for u in urls if u])

        video_files = request.files.getlist("videos")
        video_files = [f for f in video_files if f and f.filename]
        if video_files:
            if len(video_files) > MAX_VIDEOS:
                video_files = video_files[:MAX_VIDEOS]
            urls = [save_upload(f, "videos") for f in video_files]
            ag.video_urls = "|".join([u for u in urls if u])

        existing = parse_pdf_items(ag.pdf1_url or "")
        out = existing[:] if existing else []
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
                out2.append(f"{item.get('name','Documento')}||{item.get('url')}")
        ag.pdf1_url = "|".join(out2)

        s.commit()
        flash("Salvato!", "ok")
        return redirect(url_for("me_edit"))

    return render_template("agent_form.html", agent=ag, editing_profile2=False, i18n_data={})


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
        set_profile_data(ag, "p2", request.form)
        s.commit()
        flash("Profilo 2 salvato!", "ok")
        return redirect(url_for("me_profile2"))

    return render_template("agent_form.html", agent=ag, editing_profile2=True, i18n_data={})


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
    # IMPORTANT: start empty
    ag.p2_json = "{}"
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
# MEDIA DELETE (single item)
# ==========================
@app.route("/area/media/delete/<slug>", methods=["POST"])
def delete_media(slug):
    r = require_login()
    if r:
        return r

    t = (request.form.get("type") or "").strip()  # gallery | video | pdf
    idx = int(request.form.get("idx") or -1)
    target = (request.form.get("target") or "dashboard").strip()  # dashboard | edit | p2
    # p2 not deleting media in this version (media are for P1)
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    # Auth: agent can only delete own
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

    if target == "edit":
        if is_admin():
            return redirect(url_for("edit_agent", slug=slug))
        return redirect(url_for("me_edit"))
    return redirect(url_for("dashboard"))


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
    lang = (request.args.get("lang") or "it").strip().lower()
    p2_enabled = int(ag.p2_enabled or 0) == 1
    use_p2 = (p_key == "p2" and p2_enabled)

    # i18n
    try:
        i18n = json.loads(ag.i18n_json or "{}")
        if not isinstance(i18n, dict):
            i18n = {}
    except Exception:
        i18n = {}

    profile = get_profile_data(ag, "p2" if use_p2 else "p1")

    # apply translation on public card (only for P1 data render)
    if lang in ["en","fr","es","de"] and i18n.get(lang):
        d = i18n.get(lang) or {}
        # if translated field empty, keep original
        for key in ["name","company","role","bio","addresses"]:
            if d.get(key):
                profile[key] = d.get(key)

    # Prepare derived lists
    emails = split_csv(profile.get("emails",""))
    websites = split_csv(profile.get("websites",""))
    addresses = split_lines(profile.get("addresses",""))

    # maps links for addresses
    addr_objs = []
    for a in addresses:
        q = a.replace(" ", "+")
        addr_objs.append({"text": a, "maps": f"https://www.google.com/maps/search/?api=1&query={q}"})

    mobiles = []
    m1 = profile.get("phone_mobile","").strip()
    m2 = profile.get("phone_mobile2","").strip()
    if m1:
        mobiles.append(m1)
    if m2:
        mobiles.append(m2)

    office_value = profile.get("phone_office","").strip()
    pec_email = profile.get("pec","").strip()

    # media
    gallery = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
    videos = [x for x in (ag.video_urls or "").split("|") if x.strip()]
    pdfs = parse_pdf_items(ag.pdf1_url or "")

    # whatsapp link
    wa_link = profile.get("whatsapp","").strip()
    if wa_link and wa_link.startswith("+"):
        wa_link = "https://wa.me/" + re.sub(r"\D+", "", wa_link)

    # qr
    base_url = public_base_url()
    qr_url = f"{base_url}/{ag.slug}"
    if use_p2:
        qr_url = f"{base_url}/{ag.slug}?p=p2"

    # translate strings minimal
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
            "theme": "Tema",
            "theme_auto": "Auto",
            "theme_light": "Chiaro",
            "theme_dark": "Scuro",
            "gallery": "Foto",
            "videos": "Video",
            "documents": "Documenti",
            "close": "Chiudi",
            "profile_1": "Profilo 1",
            "profile_2": "Profilo 2",
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
            "theme": "Theme",
            "theme_auto": "Auto",
            "theme_light": "Light",
            "theme_dark": "Dark",
            "gallery": "Photos",
            "videos": "Videos",
            "documents": "Documents",
            "close": "Close",
            "profile_1": "Profile 1",
            "profile_2": "Profile 2",
        }
        pack = it if lang == "it" else en
        return pack.get(key, it.get(key, key))

    # Compose object similar to your card.html
    class Obj(dict):
        __getattr__ = dict.get

    # Build ag-like for template expectations
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

        # profile fields (override by profile dict)
        "name": profile.get("name",""),
        "company": profile.get("company",""),
        "role": profile.get("role",""),
        "bio": profile.get("bio",""),
        "piva": profile.get("piva",""),
        "sdi": profile.get("sdi",""),

        "facebook": profile.get("facebook",""),
        "instagram": profile.get("instagram",""),
        "linkedin": profile.get("linkedin",""),
        "tiktok": profile.get("tiktok",""),
        "telegram": profile.get("telegram",""),
        "youtube": profile.get("youtube",""),
        "spotify": profile.get("spotify",""),
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
    # redirect to login for now
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
