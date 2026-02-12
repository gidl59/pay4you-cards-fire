import os
import re
import json
import uuid
import datetime as dt
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, abort, flash, send_from_directory, Response, jsonify
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
SUBDIR_VID = UPLOADS_DIR / "video"
SUBDIR_PDF = UPLOADS_DIR / "pdf"
for d in (SUBDIR_IMG, SUBDIR_VID, SUBDIR_PDF):
    d.mkdir(parents=True, exist_ok=True)

# limiti
MAX_IMAGE_MB = 5
MAX_VIDEO_MB = 80
MAX_PDF_MB = 10
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

    # -------- P1 (colonne)
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

    # ✅ Media (P1)
    gallery_urls = Column(Text, default="")  # immagini: url|url|...
    video_urls = Column(Text, default="")    # video: url|url|...
    pdf1_url = Column(Text, default="")      # pdf: nome||url|nome||url|...

    # -------- P2/P3
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

        # aggiunte “safe”
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
    if kind == "video" and mb > MAX_VIDEO_MB:
        return False, f"Video troppo grande ({mb:.1f} MB). Max {MAX_VIDEO_MB} MB."
    if kind == "pdf" and mb > MAX_PDF_MB:
        return False, f"PDF troppo grande ({mb:.1f} MB). Max {MAX_PDF_MB} MB."
    return True, ""

def _safe_ext(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if not ext or len(ext) > 10:
        return ""
    return ext

def save_upload(file_storage, kind: str):
    if not file_storage or not file_storage.filename:
        return ""

    ok, err = enforce_size(kind, file_storage)
    if not ok:
        raise ValueError(err)

    filename = secure_filename(file_storage.filename)
    ext = _safe_ext(filename)
    uid = uuid.uuid4().hex[:12]
    outname = f"{uid}{ext}"

    if kind == "images":
        outpath = SUBDIR_IMG / outname
        rel = f"images/{outname}"
    elif kind == "video":
        outpath = SUBDIR_VID / outname
        rel = f"video/{outname}"
    else:
        outpath = SUBDIR_PDF / outname
        rel = f"pdf/{outname}"

    file_storage.save(str(outpath))
    return uploads_url(rel)

def parse_pipe_list(s: str):
    parts = []
    for x in (s or "").split("|"):
        x = (x or "").strip()
        if x:
            parts.append(x)
    return parts

def unique_keep_order(items):
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def parse_pdf_items(s: str):
    """
    Formato: nome||url|nome||url|...
    """
    items = []
    for part in (s or "").split("|"):
        part = (part or "").strip()
        if not part:
            continue
        if "||" in part:
            nm, url = part.split("||", 1)
            nm = (nm or "").strip()
            url = (url or "").strip()
        else:
            nm, url = part, part
        # pulizia neri / rotti
        if not url or url == "black":
            continue
        if nm and url:
            items.append((nm, url))
    # dedup per url mantenendo ordine
    seen = set()
    out = []
    for nm, url in items:
        if url not in seen:
            seen.add(url)
            out.append((nm, url))
    return out

def serialize_pdf_items(items):
    parts = []
    for nm, url in items:
        nm = (nm or "").strip()
        url = (url or "").strip()
        if not url:
            continue
        if not nm:
            nm = url
        parts.append(f"{nm}||{url}")
    return "|".join(parts)

def url_to_local_path(u: str) -> Path | None:
    """
    Accetta solo URL interni /uploads/...
    """
    if not u:
        return None
    try:
        pu = urlparse(u)
        path = pu.path or ""
        if path.startswith("/uploads/"):
            rel = path.replace("/uploads/", "", 1)
            return UPLOADS_DIR / rel
    except Exception:
        pass
    return None

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

def empty_profile_blob():
    return {
        "name":"", "company":"", "role":"", "bio":"",
        "phone_mobile":"", "phone_mobile2":"", "phone_office":"", "whatsapp":"",
        "emails":"", "websites":"", "pec":"", "addresses":"",
        "piva":"", "sdi":"",
        "facebook":"", "instagram":"", "linkedin":"", "tiktok":"", "telegram":"", "youtube":"", "spotify":"",

        "photo_url":"", "logo_url":"", "back_media_url":"",
        "photo_pos_x":50, "photo_pos_y":35, "photo_zoom":"1.0",
        "orbit_spin":0, "avatar_spin":0, "logo_spin":0, "allow_flip":0,

        "gallery_urls":"", "video_urls":"", "pdf_urls":"",  # pdf_urls = nome||url|...
    }

def get_profile_blob(agent: Agent, profile: str) -> dict:
    profile = (profile or "p1").lower()
    if profile == "p1":
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

            "gallery_urls": agent.gallery_urls or "",
            "video_urls": agent.video_urls or "",
            "pdf_urls": agent.pdf1_url or "",
        }

    blob = load_profile_json(agent, profile)
    base = empty_profile_blob()
    base.update(blob if isinstance(blob, dict) else {})
    # pulizia pdf
    base["pdf_urls"] = serialize_pdf_items(parse_pdf_items(base.get("pdf_urls","")))
    base["gallery_urls"] = "|".join(unique_keep_order(parse_pipe_list(base.get("gallery_urls",""))))
    base["video_urls"] = "|".join(unique_keep_order(parse_pipe_list(base.get("video_urls",""))))
    return base

def set_profile_blob(agent: Agent, profile: str, form: dict):
    profile = (profile or "p1").lower()

    def safe_int(v, d):
        try: return int(v)
        except Exception: return d

    # leggi “source of truth” dal form (se presente) per evitare duplicazioni
    blob = get_profile_blob(agent, profile)
    out = empty_profile_blob()
    out.update(blob)

    # campi testo
    for k in [
        "name","company","role","bio",
        "phone_mobile","phone_mobile2","phone_office","whatsapp",
        "emails","websites","pec","addresses",
        "piva","sdi",
        "facebook","instagram","linkedin","tiktok","telegram","youtube","spotify"
    ]:
        if k in form:
            out[k] = (form.get(k) or "").strip()

    # media urls “singole”
    for k in ["photo_url","logo_url","back_media_url"]:
        if k in form:
            out[k] = (form.get(k) or "").strip()

    # crop/effetti
    out["photo_pos_x"] = safe_int(form.get("photo_pos_x", out.get("photo_pos_x",50)), 50)
    out["photo_pos_y"] = safe_int(form.get("photo_pos_y", out.get("photo_pos_y",35)), 35)
    z = (form.get("photo_zoom") or out.get("photo_zoom") or "1.0").strip()
    try:
        float(z)
        out["photo_zoom"] = z
    except Exception:
        out["photo_zoom"] = "1.0"

    out["orbit_spin"] = 1 if form.get("orbit_spin") == "on" else int(out.get("orbit_spin",0) or 0)
    out["avatar_spin"] = 1 if form.get("avatar_spin") == "on" else int(out.get("avatar_spin",0) or 0)
    out["logo_spin"]   = 1 if form.get("logo_spin") == "on" else int(out.get("logo_spin",0) or 0)
    out["allow_flip"]  = 1 if form.get("allow_flip") == "on" else int(out.get("allow_flip",0) or 0)

    # gallery/video/pdf strings dal form (se esistono) -> EVITA append doppio
    # accetto più nomi possibili
    for gk in ["gallery_urls", "gallery", "gallery_images_urls"]:
        if gk in form:
            out["gallery_urls"] = (form.get(gk) or "").strip()
            break
    for vk in ["video_urls", "videos", "video_files_urls"]:
        if vk in form:
            out["video_urls"] = (form.get(vk) or "").strip()
            break
    for pk in ["pdf_urls", "pdf1_url", "pdf_list"]:
        if pk in form:
            out["pdf_urls"] = (form.get(pk) or "").strip()
            break

    # normalizza
    out["gallery_urls"] = "|".join(unique_keep_order(parse_pipe_list(out.get("gallery_urls",""))))
    out["video_urls"] = "|".join(unique_keep_order(parse_pipe_list(out.get("video_urls",""))))
    out["pdf_urls"] = serialize_pdf_items(parse_pdf_items(out.get("pdf_urls","")))

    # scrivi su DB
    if profile == "p1":
        agent.name = out["name"]
        agent.company = out["company"]
        agent.role = out["role"]
        agent.bio = out["bio"]

        agent.phone_mobile = out["phone_mobile"]
        agent.phone_mobile2 = out["phone_mobile2"]
        agent.phone_office = out["phone_office"]
        agent.whatsapp = out["whatsapp"]
        agent.emails = out["emails"]
        agent.websites = out["websites"]
        agent.pec = out["pec"]
        agent.addresses = out["addresses"]

        agent.piva = out["piva"]
        agent.sdi = out["sdi"]

        agent.facebook = out["facebook"]
        agent.instagram = out["instagram"]
        agent.linkedin = out["linkedin"]
        agent.tiktok = out["tiktok"]
        agent.telegram = out["telegram"]
        agent.youtube = out["youtube"]
        agent.spotify = out["spotify"]

        agent.photo_url = out["photo_url"]
        agent.logo_url = out["logo_url"]
        agent.back_media_url = out["back_media_url"]

        agent.photo_pos_x = int(out["photo_pos_x"])
        agent.photo_pos_y = int(out["photo_pos_y"])
        agent.photo_zoom = out["photo_zoom"]

        agent.orbit_spin = int(out["orbit_spin"])
        agent.avatar_spin = int(out["avatar_spin"])
        agent.logo_spin = int(out["logo_spin"])
        agent.allow_flip = int(out["allow_flip"])

        agent.gallery_urls = out["gallery_urls"]
        agent.video_urls = out["video_urls"]
        agent.pdf1_url = out["pdf_urls"]
    else:
        save_profile_json(agent, profile, out)

    agent.updated_at = dt.datetime.utcnow()


def handle_media_uploads(agent: Agent, profile: str):
    """
    Supporta nomi multipli di campi:
    - singoli: photo, logo, back_media
    - galleria foto: gallery_images / gallery / photos (multiple)
    - video: videos / video_files (multiple)
    - pdf: pdf_files / pdf (multiple)
    """
    profile = (profile or "p1").lower()
    blob = get_profile_blob(agent, profile)

    # singoli
    photo = request.files.get("photo")
    if photo and photo.filename:
        blob["photo_url"] = save_upload(photo, "images")

    logo = request.files.get("logo")
    if logo and logo.filename:
        blob["logo_url"] = save_upload(logo, "images")

    back_media = request.files.get("back_media")
    if back_media and back_media.filename:
        blob["back_media_url"] = save_upload(back_media, "images")

    # galleria foto (multiple)
    gallery_files = []
    for key in ["gallery_images", "gallery", "photos", "gallery_files"]:
        if key in request.files:
            gallery_files = request.files.getlist(key)
            if gallery_files:
                break

    if gallery_files:
        cur = parse_pipe_list(blob.get("gallery_urls", ""))
        for fs in gallery_files:
            if fs and fs.filename:
                cur.append(save_upload(fs, "images"))
        cur = unique_keep_order(cur)[:MAX_GALLERY_IMAGES]
        blob["gallery_urls"] = "|".join(cur)

    # video (multiple)
    video_files = []
    for key in ["videos", "video_files", "video_gallery"]:
        if key in request.files:
            video_files = request.files.getlist(key)
            if video_files:
                break

    if video_files:
        cur = parse_pipe_list(blob.get("video_urls",""))
        for fs in video_files:
            if fs and fs.filename:
                cur.append(save_upload(fs, "video"))
        cur = unique_keep_order(cur)[:MAX_VIDEOS]
        blob["video_urls"] = "|".join(cur)

    # pdf (multiple)
    pdf_files = []
    for key in ["pdf_files", "pdf", "pdf_upload"]:
        if key in request.files:
            pdf_files = request.files.getlist(key)
            if pdf_files:
                break

    if pdf_files:
        cur_items = parse_pdf_items(blob.get("pdf_urls",""))
        for fs in pdf_files:
            if fs and fs.filename:
                # max 10
                if len(cur_items) >= MAX_PDFS:
                    break
                url = save_upload(fs, "pdf")
                nm = secure_filename(fs.filename) or "documento.pdf"
                cur_items.append((nm, url))
        # dedup + max
        cur_items = parse_pdf_items(serialize_pdf_items(cur_items))[:MAX_PDFS]
        blob["pdf_urls"] = serialize_pdf_items(cur_items)

    # salva blob su DB
    if profile == "p1":
        agent.photo_url = blob.get("photo_url","")
        agent.logo_url = blob.get("logo_url","")
        agent.back_media_url = blob.get("back_media_url","")
        agent.gallery_urls = blob.get("gallery_urls","")
        agent.video_urls = blob.get("video_urls","")
        agent.pdf1_url = blob.get("pdf_urls","")
    else:
        save_profile_json(agent, profile, blob)

    agent.updated_at = dt.datetime.utcnow()


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
            p2_json=json.dumps(empty_profile_blob(), ensure_ascii=False),
            p3_json=json.dumps(empty_profile_blob(), ensure_ascii=False),
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
        return redirect(url_for("edit_agent_profile", slug=slug, profile="p1"))

    return render_template(
        "agent_form.html",
        agent=None,
        data=empty_profile_blob(),
        i18n={},
        show_i18n=True,
        page_title="Nuova Card (P1)",
        page_hint="Crea i dati principali della card.",
        profile_label="Profilo 1"
    )


# ==========================
# EDIT (ADMIN + CLIENTE)
# ==========================
def _can_edit_agent(slug: str):
    if is_admin():
        return True
    return slug == session.get("slug")

@app.route("/area/edit/<slug>/<profile>", methods=["GET","POST"])
def edit_agent_profile(slug, profile):
    r = require_login()
    if r: return r

    profile = (profile or "p1").lower()
    if profile not in ("p1","p2","p3"):
        abort(404)

    if not _can_edit_agent(slug):
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    # check abilitazione p2/p3
    if profile == "p2" and int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))
    if profile == "p3" and int(ag.p3_enabled or 0) != 1:
        flash("Profilo 3 non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            # 1) salva campi (NO duplicazioni: usa stringhe dal form come sorgente)
            set_profile_blob(ag, profile, request.form)

            # 2) carica eventuali media (append controllata + limiti)
            handle_media_uploads(ag, profile)

            # 3) traduzioni sempre disponibili
            save_i18n(ag, request.form)

            s.commit()
            flash("Salvato!", "ok")

        except ValueError as e:
            s.rollback()
            flash(str(e), "error")
        except Exception as e:
            s.rollback()
            flash(f"Errore salvataggio: {e}", "error")

        return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))

    data = get_profile_blob(ag, profile)
    i18n = load_i18n(ag)

    label = "Profilo 1" if profile == "p1" else ("Profilo 2" if profile == "p2" else "Profilo 3")
    hint = "Qui modifichi i dati della tua Pay4You Card." if not is_admin() else f"Modifica dati {label}."

    return render_template(
        "agent_form.html",
        agent=ag,
        data=data,
        i18n=i18n,
        show_i18n=True,
        page_title=f"Modifica {label}",
        page_hint=hint,
        profile_label=label
    )

# alias vecchi (compat)
@app.route("/area/edit/<slug>/p1", methods=["GET","POST"])
def edit_agent_p1(slug):
    return edit_agent_profile(slug, "p1")

@app.route("/area/edit/<slug>/p2", methods=["GET","POST"])
def edit_agent_p2(slug):
    return edit_agent_profile(slug, "p2")

@app.route("/area/edit/<slug>/p3", methods=["GET","POST"])
def edit_agent_p3(slug):
    return edit_agent_profile(slug, "p3")

@app.route("/area/me/edit", methods=["GET","POST"])
def me_edit_p1():
    r = require_login()
    if r: return r
    if is_admin():
        return redirect(url_for("dashboard"))
    return edit_agent_profile(session.get("slug"), "p1")

@app.route("/area/me/p2", methods=["GET","POST"])
def me_edit_p2():
    r = require_login()
    if r: return r
    if is_admin():
        return redirect(url_for("dashboard"))
    return edit_agent_profile(session.get("slug"), "p2")

@app.route("/area/me/p3", methods=["GET","POST"])
def me_edit_p3():
    r = require_login()
    if r: return r
    if is_admin():
        return redirect(url_for("dashboard"))
    return edit_agent_profile(session.get("slug"), "p3")


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
    ag.p2_json = json.dumps(empty_profile_blob(), ensure_ascii=False)  # ✅ vuoto
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
    ag.p2_json = json.dumps(empty_profile_blob(), ensure_ascii=False)
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
    ag.p3_json = json.dumps(empty_profile_blob(), ensure_ascii=False)  # ✅ vuoto
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
    ag.p3_json = json.dumps(empty_profile_blob(), ensure_ascii=False)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("P3 disattivato.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# MEDIA DELETE (FIX 500 + FIX PDF DUPLICA/NERI)
# ==========================
@app.route("/area/media/delete/<slug>/<profile>", methods=["GET","POST"])
def media_delete(slug, profile):
    r = require_login()
    if r: return r

    profile = (profile or "p1").lower()
    if profile not in ("p1","p2","p3"):
        abort(404)

    if not _can_edit_agent(slug):
        abort(403)

    kind = (request.args.get("kind") or request.form.get("kind") or "").strip().lower()
    url  = (request.args.get("url")  or request.form.get("url")  or "").strip()

    # fallback: se chiamano /delete/... senza parametri
    if not kind or not url:
        return jsonify({"ok": False, "error": "Parametri mancanti (kind,url)."}), 400

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    blob = get_profile_blob(ag, profile)

    def delete_file_if_local(u):
        p = url_to_local_path(u)
        if p and p.exists() and p.is_file():
            try:
                p.unlink()
                return True
            except Exception:
                return False
        return False

    if kind in ("photo","logo","back"):
        key = "photo_url" if kind == "photo" else ("logo_url" if kind == "logo" else "back_media_url")
        if blob.get(key) == url:
            delete_file_if_local(url)
            blob[key] = ""
    elif kind in ("gallery","image"):
        arr = parse_pipe_list(blob.get("gallery_urls",""))
        arr2 = [x for x in arr if x != url]
        if len(arr2) != len(arr):
            delete_file_if_local(url)
        blob["gallery_urls"] = "|".join(arr2)
    elif kind in ("video","videos"):
        arr = parse_pipe_list(blob.get("video_urls",""))
        arr2 = [x for x in arr if x != url]
        if len(arr2) != len(arr):
            delete_file_if_local(url)
        blob["video_urls"] = "|".join(arr2)
    elif kind in ("pdf","pdfs"):
        items = parse_pdf_items(blob.get("pdf_urls",""))
        items2 = [(nm,u) for (nm,u) in items if u != url]
        if len(items2) != len(items):
            delete_file_if_local(url)
        blob["pdf_urls"] = serialize_pdf_items(items2)
    else:
        return jsonify({"ok": False, "error": "kind non valido"}), 400

    # risalva blob
    if profile == "p1":
        ag.photo_url = blob.get("photo_url","")
        ag.logo_url = blob.get("logo_url","")
        ag.back_media_url = blob.get("back_media_url","")
        ag.gallery_urls = blob.get("gallery_urls","")
        ag.video_urls = blob.get("video_urls","")
        ag.pdf1_url = blob.get("pdf_urls","")
    else:
        save_profile_json(ag, profile, blob)

    ag.updated_at = dt.datetime.utcnow()
    s.commit()

    # se chiamata dal browser (GET) -> torna alla pagina edit
    if request.method == "GET":
        flash("Eliminato.", "ok")
        return redirect(url_for("edit_agent_profile", slug=slug, profile=profile))

    return jsonify({"ok": True})


# ==========================
# CARD PUBLIC (P1/P2/P3)
# ==========================
@app.route("/<slug>")
def public_card(slug):
    p = (request.args.get("p") or "p1").strip().lower()

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if p == "p2" and int(ag.p2_enabled or 0) != 1:
        p = "p1"
    if p == "p3" and int(ag.p3_enabled or 0) != 1:
        p = "p1"

    data = get_profile_blob(ag, p)
    i18n = load_i18n(ag)

    # qui usi il tuo template card.html
    return render_template("card.html", agent=ag, data=data, i18n=i18n, profile=p)


# ==========================
# VCF (minimo)
# ==========================
@app.route("/vcf/<slug>")
def vcf(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    fn = (ag.name or ag.slug or "").strip()
    org = (ag.company or "").strip()
    tel = (ag.phone_mobile or "").strip()
    email = ""
    ems = (ag.emails or "").strip()
    if ems:
        email = ems.split("\n")[0].split(",")[0].strip()

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{fn}",
    ]
    if org:
        lines.append(f"ORG:{org}")
    if tel:
        lines.append(f"TEL;TYPE=CELL:{tel}")
    if email:
        lines.append(f"EMAIL:{email}")
    lines.append("END:VCARD")

    body = "\r\n".join(lines) + "\r\n"
    return Response(body, mimetype="text/vcard")


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
