import os
import re
import json
import uuid
import datetime as dt
from pathlib import Path
from urllib.parse import quote, unquote

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

UPLOADS_DIR = Path(PERSIST_UPLOADS_DIR)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

SUBDIR_IMG = UPLOADS_DIR / "images"
SUBDIR_VID = UPLOADS_DIR / "videos"
SUBDIR_PDF = UPLOADS_DIR / "pdf"
for d in (SUBDIR_IMG, SUBDIR_VID, SUBDIR_PDF):
    d.mkdir(parents=True, exist_ok=True)

# limiti base
MAX_IMAGE_MB = 7
MAX_VIDEO_MB = 60
MAX_PDF_MB = 15

MAX_GALLERY_IMAGES = 30
MAX_VIDEOS = 10
MAX_PDFS = 10

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXT = {".mp4", ".webm", ".mov"}
ALLOWED_PDF_EXT = {".pdf"}


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

    # P1 in colonne
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

    # media base
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

    # ✅ gallerie P1 (compatibili dashboard.html)
    gallery_urls = Column(Text, default="")   # images
    video_urls = Column(Text, default="")     # videos
    pdf1_url = Column(Text, default="")       # pdf list

    # P2/P3
    p2_enabled = Column(Integer, default=0)
    p3_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")
    p3_json = Column(Text, default="{}")

    i18n_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=lambda: dt.datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: dt.datetime.utcnow())


# ==========================
# DB INIT / MIGRATION
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
            ("gallery_urls", "TEXT"),
            ("video_urls", "TEXT"),
            ("pdf1_url", "TEXT"),
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
        conn.exec_driver_sql("UPDATE agents SET photo_pos_x = COALESCE(photo_pos_x, 50)")
        conn.exec_driver_sql("UPDATE agents SET photo_pos_y = COALESCE(photo_pos_y, 35)")
        conn.exec_driver_sql("UPDATE agents SET photo_zoom = COALESCE(photo_zoom, '1.0')")
        conn.exec_driver_sql("UPDATE agents SET gallery_urls = COALESCE(gallery_urls, '')")
        conn.exec_driver_sql("UPDATE agents SET video_urls = COALESCE(video_urls, '')")
        conn.exec_driver_sql("UPDATE agents SET pdf1_url = COALESCE(pdf1_url, '')")

        for f in ["orbit_spin","avatar_spin","logo_spin","allow_flip","p2_enabled","p3_enabled"]:
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

def _ext_ok(ext: str, kind: str) -> bool:
    ext = (ext or "").lower()
    if kind == "images":
        return ext in ALLOWED_IMAGE_EXT
    if kind == "videos":
        return ext in ALLOWED_VIDEO_EXT
    if kind == "pdf":
        return ext in ALLOWED_PDF_EXT
    return False

def save_upload(file_storage, kind: str) -> str:
    if not file_storage or not file_storage.filename:
        return ""

    ok, err = enforce_size(kind, file_storage)
    if not ok:
        raise ValueError(err)

    filename = secure_filename(file_storage.filename)
    ext = os.path.splitext(filename)[1].lower()

    if not _ext_ok(ext, kind):
        raise ValueError("Formato file non supportato.")

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

def parse_pipe_list(s: str) -> list:
    if not s:
        return []
    parts = [x.strip() for x in s.split("|")]
    return [x for x in parts if x]

def join_pipe_list(items: list) -> str:
    items2 = []
    for x in items:
        if not x:
            continue
        x = str(x).strip()
        if x and x not in items2:
            items2.append(x)
    return "|".join(items2)

def normalize_pdf_item(item: str) -> tuple:
    """
    supporta:
      - "Nome.pdf||/uploads/pdf/xxx.pdf"
      - "/uploads/pdf/xxx.pdf"
    ritorna (name, url)
    """
    item = (item or "").strip()
    if not item:
        return ("", "")
    if "||" in item:
        nm, url = item.split("||", 1)
        return (nm.strip(), url.strip())
    return ("", item)

def safe_local_upload_path(url: str) -> Path | None:
    """
    Se url è del tipo /uploads/pdf/xxx.pdf o /uploads/images/... o /uploads/videos/...
    ritorna Path assoluto nella cartella UPLOADS_DIR, altrimenti None
    """
    if not url:
        return None
    url = url.strip()
    if not url.startswith("/uploads/"):
        return None
    rel = url[len("/uploads/"):]
    rel = rel.lstrip("/").replace("..", "")
    p = UPLOADS_DIR / rel
    try:
        p.resolve()
    except Exception:
        return None
    return p

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

def save_profile_json(agent: Agent, key: str, form: dict):
    # campi base
    data = {}
    for k in [
        "name","company","role","bio",
        "phone_mobile","phone_mobile2","phone_office","whatsapp",
        "emails","websites","pec","addresses",
        "piva","sdi",
        "facebook","instagram","linkedin","tiktok","telegram","youtube","spotify"
    ]:
        data[k] = (form.get(k) or "").strip()

    # media/crop/effects (solo se il template li manda)
    for k in ["photo_url","logo_url","back_media_url"]:
        data[k] = (form.get(k) or data.get(k) or "").strip()

    # crop/effects (se presenti)
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

    data["orbit_spin"] = 1 if form.get("orbit_spin") == "on" else 0
    data["avatar_spin"] = 1 if form.get("avatar_spin") == "on" else 0
    data["logo_spin"] = 1 if form.get("logo_spin") == "on" else 0
    data["allow_flip"] = 1 if form.get("allow_flip") == "on" else 0

    # ✅ gallerie separate in json
    data["gallery_urls"] = (form.get("gallery_urls") or "").strip()
    data["video_urls"] = (form.get("video_urls") or "").strip()
    data["pdf_urls"] = (form.get("pdf_urls") or "").strip()

    if key == "p2":
        agent.p2_json = json.dumps(data, ensure_ascii=False)
    else:
        agent.p3_json = json.dumps(data, ensure_ascii=False)

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

        "photo_url": agent.photo_url or "",
        "logo_url": agent.logo_url or "",
        "back_media_url": agent.back_media_url or "",

        "photo_pos_x": int(agent.photo_pos_x or 50),
        "photo_pos_y": int(agent.photo_pos_y or 35),
        "photo_zoom": (agent.photo_zoom or "1.0"),

        "orbit_spin": int(agent.orbit_spin or 0),
        "avatar_spin": int(agent.avatar_spin or 0),
        "logo_spin": int(agent.logo_spin or 0),
        "allow_flip": int(agent.allow_flip or 0),

        # ✅ compat template hidden
        "gallery_urls": agent.gallery_urls or "",
        "video_urls": agent.video_urls or "",
        "pdf_urls": agent.pdf1_url or "",
        "pdf1_url": agent.pdf1_url or "",
    }

def set_profile_data_p1(agent: Agent, form: dict):
    def safe_int(v, d):
        try:
            return int(v)
        except Exception:
            return d

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

    # ✅ hidden (source of truth)
    agent.gallery_urls = (form.get("gallery_urls") or agent.gallery_urls or "").strip()
    agent.video_urls = (form.get("video_urls") or agent.video_urls or "").strip()
    agent.pdf1_url = (form.get("pdf_urls") or agent.pdf1_url or "").strip()

    agent.updated_at = dt.datetime.utcnow()

def handle_media_uploads_p1(agent: Agent):
    # foto/logo/back
    photo = request.files.get("photo")
    if photo and photo.filename:
        agent.photo_url = save_upload(photo, "images")

    logo = request.files.get("logo")
    if logo and logo.filename:
        agent.logo_url = save_upload(logo, "images")

    back_media = request.files.get("back_media")
    if back_media and back_media.filename:
        agent.back_media_url = save_upload(back_media, "images")

def handle_pdf_uploads(profile: str, agent: Agent, blob: dict | None = None):
    """
    profile:
      - "p1": usa agent.pdf1_url
      - "p2"/"p3": usa blob["pdf_urls"]
    """
    files = request.files.getlist("pdf_files")
    if not files:
        return

    # carica massimo tot
    current = ""
    if profile == "p1":
        current = agent.pdf1_url or ""
    else:
        current = (blob or {}).get("pdf_urls") or ""

    items = parse_pipe_list(current)

    # normalizza/de-dup esistente per url
    seen = set()
    norm = []
    for it in items:
        nm, url = normalize_pdf_item(it)
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        norm.append((nm, url))

    for fs in files:
        if not fs or not fs.filename:
            continue

        # stop se raggiunto limite
        if len(norm) >= MAX_PDFS:
            break

        url = save_upload(fs, "pdf")
        # nome originale come label
        nm = secure_filename(fs.filename) or "documento.pdf"

        # de-dup per url
        if url in seen:
            continue
        seen.add(url)
        norm.append((nm, url))

    out_list = []
    for nm, url in norm:
        if nm:
            out_list.append(f"{nm}||{url}")
        else:
            out_list.append(url)

    out = join_pipe_list(out_list)

    if profile == "p1":
        agent.pdf1_url = out
    else:
        blob["pdf_urls"] = out


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
    if r:
        return r

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
            p2_enabled=0, p3_enabled=0,
            p2_json="{}", p3_json="{}",
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
        data={},
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
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if request.method == "POST":
        try:
            set_profile_data_p1(ag, request.form)
            handle_media_uploads_p1(ag)
            handle_pdf_uploads("p1", ag)
            save_i18n(ag, request.form)
            ag.updated_at = dt.datetime.utcnow()
            s.commit()
            flash("Salvato!", "ok")
            return redirect(url_for("edit_agent_p1", slug=slug))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("edit_agent_p1", slug=slug))

    data = build_data_dict_p1(ag)
    i18n = load_i18n(ag)

    return render_template(
        "agent_form.html",
        agent=ag,
        data=data,
        i18n=i18n,
        show_i18n=True,
        page_title="Modifica Profilo 1",
        page_hint="Qui modifichi i dati principali della tua Pay4You Card.",
        profile_label="Profilo 1"
    )


# ==========================
# ADMIN EDIT P2 / P3
# ==========================
def ensure_profile_defaults(d: dict) -> dict:
    d = d or {}
    # questi default evitano "sparizioni" nel template
    d.setdefault("name", "")
    d.setdefault("company", "")
    d.setdefault("role", "")
    d.setdefault("bio", "")
    d.setdefault("phone_mobile", "")
    d.setdefault("phone_mobile2", "")
    d.setdefault("phone_office", "")
    d.setdefault("whatsapp", "")
    d.setdefault("emails", "")
    d.setdefault("websites", "")
    d.setdefault("pec", "")
    d.setdefault("addresses", "")
    d.setdefault("piva", "")
    d.setdefault("sdi", "")
    d.setdefault("facebook", "")
    d.setdefault("instagram", "")
    d.setdefault("linkedin", "")
    d.setdefault("tiktok", "")
    d.setdefault("telegram", "")
    d.setdefault("youtube", "")
    d.setdefault("spotify", "")

    d.setdefault("photo_url", "")
    d.setdefault("logo_url", "")
    d.setdefault("back_media_url", "")
    d.setdefault("photo_pos_x", 50)
    d.setdefault("photo_pos_y", 35)
    d.setdefault("photo_zoom", "1.0")
    d.setdefault("orbit_spin", 0)
    d.setdefault("avatar_spin", 0)
    d.setdefault("logo_spin", 0)
    d.setdefault("allow_flip", 0)

    d.setdefault("gallery_urls", "")
    d.setdefault("video_urls", "")
    d.setdefault("pdf_urls", "")
    return d

@app.route("/area/edit/<slug>/p2", methods=["GET","POST"])
def edit_agent_p2(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)
    if int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))

    data = ensure_profile_defaults(load_profile_json(ag, "p2"))

    if request.method == "POST":
        try:
            save_profile_json(ag, "p2", request.form)
            # pdf upload su blob
            blob = load_profile_json(ag, "p2")
            blob = ensure_profile_defaults(blob)
            handle_pdf_uploads("p2", ag, blob)
            ag.p2_json = json.dumps(blob, ensure_ascii=False)

            ag.updated_at = dt.datetime.utcnow()
            s.commit()
            flash("Profilo 2 salvato!", "ok")
            return redirect(url_for("edit_agent_p2", slug=slug))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("edit_agent_p2", slug=slug))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=data,
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 2",
        page_hint="Profilo 2 (vuoto e separato da P1).",
        profile_label="Profilo 2"
    )

@app.route("/area/edit/<slug>/p3", methods=["GET","POST"])
def edit_agent_p3(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)
    if int(ag.p3_enabled or 0) != 1:
        flash("Profilo 3 non attivo", "error")
        return redirect(url_for("dashboard"))

    data = ensure_profile_defaults(load_profile_json(ag, "p3"))

    if request.method == "POST":
        try:
            save_profile_json(ag, "p3", request.form)
            blob = load_profile_json(ag, "p3")
            blob = ensure_profile_defaults(blob)
            handle_pdf_uploads("p3", ag, blob)
            ag.p3_json = json.dumps(blob, ensure_ascii=False)

            ag.updated_at = dt.datetime.utcnow()
            s.commit()
            flash("Profilo 3 salvato!", "ok")
            return redirect(url_for("edit_agent_p3", slug=slug))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("edit_agent_p3", slug=slug))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=data,
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 3",
        page_hint="Profilo 3 (vuoto e separato da P1).",
        profile_label="Profilo 3"
    )


# ==========================
# CLIENT EDIT (P1/P2/P3)
# ==========================
def require_agent_session():
    if session.get("role") != "agent":
        return None
    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    return ag

@app.route("/area/me/p1", methods=["GET","POST"])
def me_edit_p1():
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
        try:
            set_profile_data_p1(ag, request.form)
            handle_media_uploads_p1(ag)
            handle_pdf_uploads("p1", ag)
            save_i18n(ag, request.form)

            ag.updated_at = dt.datetime.utcnow()
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
    if r:
        return r
    if is_admin():
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)
    if int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))

    data = ensure_profile_defaults(load_profile_json(ag, "p2"))

    if request.method == "POST":
        try:
            save_profile_json(ag, "p2", request.form)
            blob = load_profile_json(ag, "p2")
            blob = ensure_profile_defaults(blob)
            handle_pdf_uploads("p2", ag, blob)
            ag.p2_json = json.dumps(blob, ensure_ascii=False)
            ag.updated_at = dt.datetime.utcnow()
            s.commit()
            flash("Profilo 2 salvato!", "ok")
            return redirect(url_for("me_edit_p2"))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("me_edit_p2"))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=data,
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 2",
        page_hint="Profilo 2 (vuoto e separato da P1).",
        profile_label="Profilo 2"
    )

@app.route("/area/me/p3", methods=["GET","POST"])
def me_edit_p3():
    r = require_login()
    if r:
        return r
    if is_admin():
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)
    if int(ag.p3_enabled or 0) != 1:
        flash("Profilo 3 non attivo", "error")
        return redirect(url_for("dashboard"))

    data = ensure_profile_defaults(load_profile_json(ag, "p3"))

    if request.method == "POST":
        try:
            save_profile_json(ag, "p3", request.form)
            blob = load_profile_json(ag, "p3")
            blob = ensure_profile_defaults(blob)
            handle_pdf_uploads("p3", ag, blob)
            ag.p3_json = json.dumps(blob, ensure_ascii=False)
            ag.updated_at = dt.datetime.utcnow()
            s.commit()
            flash("Profilo 3 salvato!", "ok")
            return redirect(url_for("me_edit_p3"))
        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
            return redirect(url_for("me_edit_p3"))

    return render_template(
        "agent_form.html",
        agent=ag,
        data=data,
        i18n=load_i18n(ag),
        show_i18n=True,
        page_title="Modifica Profilo 3",
        page_hint="Profilo 3 (vuoto e separato da P1).",
        profile_label="Profilo 3"
    )


# ==========================
# ACTIVATE/DEACTIVATE P2/P3
# ==========================
@app.route("/area/admin/activate/<slug>/p2", methods=["POST"])
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
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P2 attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/deactivate/<slug>/p2", methods=["POST"])
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

@app.route("/area/admin/activate/<slug>/p3", methods=["POST"])
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

    ag.p3_enabled = 1
    ag.p3_json = "{}"
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P3 attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/deactivate/<slug>/p3", methods=["POST"])
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

    ag.p3_enabled = 0
    ag.p3_json = "{}"
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P3 disattivato.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# MEDIA DELETE (PDF/IMG/VID)
# ==========================
@app.route("/area/media/delete/<slug>/<profile>", methods=["GET"])
def media_delete(slug, profile):
    """
    Usa querystring:
      kind=pdf|img|vid
      url=...
    """
    r = require_login()
    if r:
        return r

    kind = (request.args.get("kind") or "").strip().lower()
    url = (request.args.get("url") or "").strip()
    url = unquote(url)

    if kind not in ("pdf", "img", "vid"):
        abort(400)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    # permessi: admin o stesso agente
    if not is_admin():
        if session.get("role") != "agent" or session.get("slug") != ag.slug:
            abort(403)

    profile = (profile or "p1").strip().lower()
    if profile not in ("p1", "p2", "p3"):
        profile = "p1"

    # scegli lista corretta
    if profile == "p1":
        if kind == "pdf":
            items = parse_pipe_list(ag.pdf1_url or "")
            kept = []
            for it in items:
                nm, u = normalize_pdf_item(it)
                if u and u.strip() == url:
                    continue
                kept.append(it)
            ag.pdf1_url = join_pipe_list(kept)

        elif kind == "img":
            items = parse_pipe_list(ag.gallery_urls or "")
            ag.gallery_urls = join_pipe_list([x for x in items if x != url])

        elif kind == "vid":
            items = parse_pipe_list(ag.video_urls or "")
            ag.video_urls = join_pipe_list([x for x in items if x != url])

    else:
        blob = load_profile_json(ag, profile)
        blob = ensure_profile_defaults(blob)

        if kind == "pdf":
            items = parse_pipe_list(blob.get("pdf_urls") or "")
            kept = []
            for it in items:
                nm, u = normalize_pdf_item(it)
                if u and u.strip() == url:
                    continue
                kept.append(it)
            blob["pdf_urls"] = join_pipe_list(kept)

        elif kind == "img":
            items = parse_pipe_list(blob.get("gallery_urls") or "")
            blob["gallery_urls"] = join_pipe_list([x for x in items if x != url])

        elif kind == "vid":
            items = parse_pipe_list(blob.get("video_urls") or "")
            blob["video_urls"] = join_pipe_list([x for x in items if x != url])

        if profile == "p2":
            ag.p2_json = json.dumps(blob, ensure_ascii=False)
        else:
            ag.p3_json = json.dumps(blob, ensure_ascii=False)

    # elimina file fisico se locale uploads
    p = safe_local_upload_path(url)
    if p and p.is_file():
        try:
            p.unlink()
        except Exception:
            pass

    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Eliminato.", "ok")

    # redirect coerente
    if is_admin():
        if profile == "p1":
            return redirect(url_for("edit_agent_p1", slug=ag.slug))
        if profile == "p2":
            return redirect(url_for("edit_agent_p2", slug=ag.slug))
        return redirect(url_for("edit_agent_p3", slug=ag.slug))
    else:
        if profile == "p1":
            return redirect(url_for("me_edit_p1"))
        if profile == "p2":
            return redirect(url_for("me_edit_p2"))
        return redirect(url_for("me_edit_p3"))


# ==========================
# PURGE PDF (TOTALE)
# ==========================
@app.route("/area/admin/purge_pdfs", methods=["POST"])
def purge_pdfs_all():
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    # 1) cancella file fisici in /pdf
    try:
        for p in SUBDIR_PDF.glob("*"):
            if p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    # 2) reset DB: P1 + P2 + P3
    s = db()
    agents = s.query(Agent).all()
    for ag in agents:
        ag.pdf1_url = ""

        b2 = ensure_profile_defaults(load_profile_json(ag, "p2"))
        b3 = ensure_profile_defaults(load_profile_json(ag, "p3"))
        b2["pdf_urls"] = ""
        b3["pdf_urls"] = ""
        ag.p2_json = json.dumps(b2, ensure_ascii=False)
        ag.p3_json = json.dumps(b3, ensure_ascii=False)

        ag.updated_at = dt.datetime.utcnow()

    s.commit()
    flash("PURGE completato: eliminati tutti i PDF (file + DB) per tutti gli agenti.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# QR PNG
# ==========================
@app.route("/qr/<slug>.png")
def qr_png(slug):
    if qrcode is None:
        abort(500)

    p = (request.args.get("p") or "").strip().lower()  # p2/p3
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
    return Response(buf.getvalue(), mimetype="image/png")


# ==========================
# HOME
# ==========================
@app.route("/")
def home():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
