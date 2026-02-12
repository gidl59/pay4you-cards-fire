import os
import re
import json
import uuid
import hashlib
import datetime as dt
from pathlib import Path

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

    p2_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="{}")

    p3_enabled = Column(Integer, default=0)
    p3_json = Column(Text, default="{}")

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
        add_col("p2_enabled", "INTEGER")
        add_col("p3_enabled", "INTEGER")

        add_col("photo_pos_x", "INTEGER")
        add_col("photo_pos_y", "INTEGER")
        add_col("photo_zoom", "TEXT")
        add_col("back_media_mode", "TEXT")
        add_col("back_media_url", "TEXT")

        for f in ["orbit_spin", "avatar_spin", "logo_spin", "allow_flip"]:
            add_col(f, "INTEGER")

        for (name, coltype) in missing:
            conn.exec_driver_sql(f"ALTER TABLE agents ADD COLUMN {name} {coltype}")

        now = dt.datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        conn.exec_driver_sql("UPDATE agents SET created_at = COALESCE(created_at, :now)", {"now": now})
        conn.exec_driver_sql("UPDATE agents SET updated_at = COALESCE(updated_at, :now)", {"now": now})

        conn.exec_driver_sql("UPDATE agents SET p2_json = COALESCE(p2_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET p3_json = COALESCE(p3_json, '{}')")
        conn.exec_driver_sql("UPDATE agents SET i18n_json = COALESCE(i18n_json, '{}')")

        conn.exec_driver_sql("UPDATE agents SET p2_enabled = COALESCE(p2_enabled, 0)")
        conn.exec_driver_sql("UPDATE agents SET p3_enabled = COALESCE(p3_enabled, 0)")

        conn.exec_driver_sql("UPDATE agents SET photo_pos_x = COALESCE(photo_pos_x, 50)")
        conn.exec_driver_sql("UPDATE agents SET photo_pos_y = COALESCE(photo_pos_y, 35)")
        conn.exec_driver_sql("UPDATE agents SET photo_zoom = COALESCE(photo_zoom, '1.0')")

        conn.exec_driver_sql("UPDATE agents SET back_media_mode = COALESCE(back_media_mode, 'company')")
        conn.exec_driver_sql("UPDATE agents SET back_media_url = COALESCE(back_media_url, '')")

        for f in ["orbit_spin", "avatar_spin", "logo_spin", "allow_flip"]:
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

def file_hash_sha1(file_storage) -> str:
    """Hash stabile per dedupe (max 10MB pdf)."""
    try:
        stream = file_storage.stream
        pos = stream.tell()
        stream.seek(0)
        h = hashlib.sha1()
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
        stream.seek(pos)
        return h.hexdigest()
    except Exception:
        return ""

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

def parse_pdf_items(pdf1_url: str):
    items = []
    if not pdf1_url:
        return items
    for chunk in (pdf1_url or "").split("|"):
        chunk = (chunk or "").strip()
        if not chunk:
            continue
        if "||" in chunk:
            name, url = chunk.split("||", 1)
            name = (name or "").strip()
            url = (url or "").strip()
            if not url:
                continue
            items.append({"name": name or "Documento", "url": url})
        else:
            # formato legacy: url diretto
            items.append({"name": chunk, "url": chunk})
    return items

def pack_pdf_items(items):
    out = []
    for it in items[:MAX_PDFS]:
        nm = (it.get("name","Documento") or "Documento").strip()
        url = (it.get("url","") or "").strip()
        if not url:
            continue
        out.append(f"{nm}||{url}")
    return "|".join(out)

def _dedupe_list_keep_order(lst):
    seen = set()
    out = []
    for x in lst:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

def normalize_pdf_string(s: str) -> str:
    items = parse_pdf_items(s or "")
    seen = set()
    out = []
    for it in items:
        url = (it.get("url","") or "").strip()
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append({"name": (it.get("name","Documento") or "Documento").strip(), "url": url})
    return pack_pdf_items(out[:MAX_PDFS])

def normalize_media_p1(ag: Agent):
    g = [x.strip() for x in (ag.gallery_urls or "").split("|") if x.strip()]
    ag.gallery_urls = "|".join(_dedupe_list_keep_order(g)[:MAX_GALLERY_IMAGES])

    v = [x.strip() for x in (ag.video_urls or "").split("|") if x.strip()]
    ag.video_urls = "|".join(_dedupe_list_keep_order(v)[:MAX_VIDEOS])

    ag.pdf1_url = normalize_pdf_string(ag.pdf1_url or "")

def load_json_field(txt: str) -> dict:
    try:
        d = json.loads(txt or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def save_json_field(d: dict) -> str:
    return json.dumps(d or {}, ensure_ascii=False)

def profile_defaults():
    return {
        "name":"", "company":"", "role":"", "bio":"",
        "phone_mobile":"", "phone_mobile2":"", "phone_office":"", "whatsapp":"",
        "emails":"", "websites":"", "pec":"", "addresses":"",
        "piva":"", "sdi":"",
        "facebook":"", "instagram":"", "linkedin":"", "tiktok":"", "telegram":"", "youtube":"", "spotify":"",

        "photo_url":"", "logo_url":"", "back_media_url":"",
        "photo_pos_x":50, "photo_pos_y":35, "photo_zoom":"1.0",
        "orbit_spin":0, "avatar_spin":0, "logo_spin":0, "allow_flip":0,
        "gallery_urls":"", "video_urls":"", "pdf_urls":""
    }

def get_profile_blob(agent: Agent, which: str) -> dict:
    if which == "p2":
        d = load_json_field(agent.p2_json or "{}")
    elif which == "p3":
        d = load_json_field(agent.p3_json or "{}")
    else:
        d = {}
    base = profile_defaults()
    base.update({k:v for k,v in d.items() if k in base})
    return base

def set_profile_blob(agent: Agent, which: str, blob: dict):
    blob = blob or {}

    g = [x.strip() for x in (blob.get("gallery_urls","") or "").split("|") if x.strip()]
    blob["gallery_urls"] = "|".join(_dedupe_list_keep_order(g)[:MAX_GALLERY_IMAGES])

    v = [x.strip() for x in (blob.get("video_urls","") or "").split("|") if x.strip()]
    blob["video_urls"] = "|".join(_dedupe_list_keep_order(v)[:MAX_VIDEOS])

    blob["pdf_urls"] = normalize_pdf_string(blob.get("pdf_urls","") or "")

    if which == "p2":
        agent.p2_json = save_json_field(blob)
    elif which == "p3":
        agent.p3_json = save_json_field(blob)

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

def load_i18n(agent: Agent) -> dict:
    return load_json_field(agent.i18n_json or "{}")


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
        for a in agents:
            normalize_media_p1(a)
            set_profile_blob(a, "p2", get_profile_blob(a, "p2"))
            set_profile_blob(a, "p3", get_profile_blob(a, "p3"))
        s.commit()

        agents.sort(key=lambda x: ((x.name or "").strip().lower(), (x.slug or "").strip().lower()))
        return render_template("dashboard.html", agents=agents, is_admin=True, agent=None)

    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        session.clear()
        return redirect(url_for("login"))

    normalize_media_p1(ag)
    set_profile_blob(ag, "p2", get_profile_blob(ag, "p2"))
    set_profile_blob(ag, "p3", get_profile_blob(ag, "p3"))
    s.commit()

    return render_template("dashboard.html", agents=[ag], is_admin=False, agent=ag)


# ==========================
# RESET PDF (ADMIN)
# ==========================
@app.route("/area/admin/reset_pdfs")
def reset_pdfs_all():
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    agents = s.query(Agent).all()
    for ag in agents:
        ag.pdf1_url = ""
        # P2/P3
        b2 = get_profile_blob(ag, "p2")
        b3 = get_profile_blob(ag, "p3")
        b2["pdf_urls"] = ""
        b3["pdf_urls"] = ""
        set_profile_blob(ag, "p2", b2)
        set_profile_blob(ag, "p3", b3)

        ag.updated_at = dt.datetime.utcnow()

    s.commit()
    flash("RESET completato: PDF rimossi da tutti gli agenti (P1+P2+P3).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/reset_pdfs/<slug>")
def reset_pdfs_one(slug):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    ag.pdf1_url = ""
    b2 = get_profile_blob(ag, "p2")
    b3 = get_profile_blob(ag, "p3")
    b2["pdf_urls"] = ""
    b3["pdf_urls"] = ""
    set_profile_blob(ag, "p2", b2)
    set_profile_blob(ag, "p3", b3)

    ag.updated_at = dt.datetime.utcnow()
    s.commit()

    flash(f"RESET completato: PDF rimossi per {slug} (P1+P2+P3).", "ok")
    return redirect(url_for("edit_agent", slug=slug))


# ==========================
# ADMIN NEW
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
            p2_enabled=0, p2_json="{}",
            p3_enabled=0, p3_json="{}",
            i18n_json="{}",
        )
        s.add(ag)
        s.commit()

        flash("Card creata!", "ok")
        return redirect(url_for("edit_agent_p1", slug=slug))

    return render_template(
        "agent_form.html",
        agent=None,
        editing_profile2=False,
        editing_profile3=False,
        is_admin=True,
        p2_data={},
        p3_data={},
        i18n_data={},
        gallery=[],
        videos=[],
        pdfs=[],
        limits={"max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
                "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB}
    )


def set_profile_data_from_form(blob: dict, form: dict):
    avatar_spin = 1 if form.get("avatar_spin") == "on" else 0
    allow_flip = 1 if form.get("allow_flip") == "on" else 0
    if avatar_spin == 1:
        allow_flip = 0
    if allow_flip == 1:
        avatar_spin = 0

    blob["orbit_spin"] = 1 if form.get("orbit_spin") == "on" else 0
    blob["logo_spin"] = 1 if form.get("logo_spin") == "on" else 0
    blob["avatar_spin"] = avatar_spin
    blob["allow_flip"] = allow_flip

    for k in [
        "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office", "whatsapp",
        "emails", "websites", "pec", "addresses",
        "piva", "sdi",
        "facebook", "instagram", "linkedin", "tiktok", "telegram", "youtube", "spotify"
    ]:
        blob[k] = (form.get(k) or "").strip()

    def safe_int(v, d):
        try:
            return int(v)
        except Exception:
            return d

    blob["photo_pos_x"] = safe_int(form.get("photo_pos_x"), int(blob.get("photo_pos_x", 50)))
    blob["photo_pos_y"] = safe_int(form.get("photo_pos_y"), int(blob.get("photo_pos_y", 35)))

    z = (form.get("photo_zoom") or str(blob.get("photo_zoom","1.0"))).strip()
    try:
        float(z)
        blob["photo_zoom"] = z
    except Exception:
        blob["photo_zoom"] = "1.0"


# ✅ dedupe robusto: filename+size+hash+kind
def _sig(file_storage, kind: str):
    return (
        secure_filename(file_storage.filename or ""),
        file_size_bytes(file_storage),
        file_hash_sha1(file_storage),
        kind
    )

def handle_media_uploads_into_blob(blob: dict):
    warnings = []
    seen_req = set()

    def try_save_single(field, kind, target_key):
        f = request.files.get(field)
        if f and f.filename:
            sig = _sig(f, kind)
            if sig in seen_req:
                return
            seen_req.add(sig)
            try:
                url = save_upload(f, kind)
                blob[target_key] = url
            except ValueError as e:
                warnings.append(str(e))

    try_save_single("photo", "images", "photo_url")
    try_save_single("logo", "images", "logo_url")
    try_save_single("back_media", "images", "back_media_url")

    # gallery
    gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
    if gallery_files:
        existing = [x for x in (blob.get("gallery_urls","") or "").split("|") if x.strip()]
        for f in gallery_files:
            if len(existing) >= MAX_GALLERY_IMAGES:
                break
            sig = _sig(f, "images")
            if sig in seen_req:
                continue
            seen_req.add(sig)
            try:
                existing.append(save_upload(f, "images"))
            except ValueError as e:
                warnings.append(str(e))
        blob["gallery_urls"] = "|".join(existing)

    # videos
    video_files = [f for f in request.files.getlist("videos") if f and f.filename]
    if video_files:
        existing = [x for x in (blob.get("video_urls","") or "").split("|") if x.strip()]
        for f in video_files:
            if len(existing) >= MAX_VIDEOS:
                break
            sig = _sig(f, "videos")
            if sig in seen_req:
                continue
            seen_req.add(sig)
            try:
                existing.append(save_upload(f, "videos"))
            except ValueError as e:
                warnings.append(str(e))
        blob["video_urls"] = "|".join(existing)

    # pdf slots
    items = parse_pdf_items(blob.get("pdf_urls","") or "")
    items = items[:MAX_PDFS]

    for i in range(1, MAX_PDFS + 1):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            sig = _sig(f, "pdf")
            if sig in seen_req:
                continue
            seen_req.add(sig)
            try:
                url = save_upload(f, "pdf")
                name = secure_filename(f.filename) or f"PDF {i}"
                idx = i - 1
                while len(items) <= idx:
                    items.append({"name": "", "url": ""})
                items[idx] = {"name": name, "url": url}
            except ValueError as e:
                warnings.append(str(e))

    blob["pdf_urls"] = normalize_pdf_string(pack_pdf_items(items))
    return warnings


def handle_media_uploads_p1(ag: Agent):
    warnings = []
    seen_req = set()

    def try_save(field, kind, setter):
        f = request.files.get(field)
        if f and f.filename:
            sig = _sig(f, kind)
            if sig in seen_req:
                return
            seen_req.add(sig)
            try:
                url = save_upload(f, kind)
                setter(url)
            except ValueError as e:
                warnings.append(str(e))

    try_save("photo", "images", lambda u: setattr(ag, "photo_url", u))
    try_save("logo", "images", lambda u: setattr(ag, "logo_url", u))
    try_save("back_media", "images", lambda u: setattr(ag, "back_media_url", u))

    gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
    if gallery_files:
        existing = [x for x in (ag.gallery_urls or "").split("|") if x.strip()]
        for f in gallery_files:
            if len(existing) >= MAX_GALLERY_IMAGES:
                break
            sig = _sig(f, "images")
            if sig in seen_req:
                continue
            seen_req.add(sig)
            try:
                existing.append(save_upload(f, "images"))
            except ValueError as e:
                warnings.append(str(e))
        ag.gallery_urls = "|".join(existing)

    video_files = [f for f in request.files.getlist("videos") if f and f.filename]
    if video_files:
        existing = [x for x in (ag.video_urls or "").split("|") if x.strip()]
        for f in video_files:
            if len(existing) >= MAX_VIDEOS:
                break
            sig = _sig(f, "videos")
            if sig in seen_req:
                continue
            seen_req.add(sig)
            try:
                existing.append(save_upload(f, "videos"))
            except ValueError as e:
                warnings.append(str(e))
        ag.video_urls = "|".join(existing)

    items = parse_pdf_items(ag.pdf1_url or "")
    items = items[:MAX_PDFS]

    for i in range(1, MAX_PDFS + 1):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            sig = _sig(f, "pdf")
            if sig in seen_req:
                continue
            seen_req.add(sig)
            try:
                url = save_upload(f, "pdf")
                name = secure_filename(f.filename) or f"PDF {i}"
                idx = i - 1
                while len(items) <= idx:
                    items.append({"name": "", "url": ""})
                items[idx] = {"name": name, "url": url}
            except ValueError as e:
                warnings.append(str(e))

    ag.pdf1_url = normalize_pdf_string(pack_pdf_items(items))
    normalize_media_p1(ag)
    return warnings


# ==========================
# ADMIN EDIT P1/P2/P3 (come già avevi)
# ==========================
@app.route("/area/edit/<slug>/p1", methods=["GET", "POST"])
def edit_agent_p1(slug):
    return edit_agent(slug)

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
        avatar_spin = 1 if request.form.get("avatar_spin") == "on" else 0
        allow_flip = 1 if request.form.get("allow_flip") == "on" else 0
        if avatar_spin == 1:
            allow_flip = 0
        if allow_flip == 1:
            avatar_spin = 0

        ag.orbit_spin = 1 if request.form.get("orbit_spin") == "on" else 0
        ag.logo_spin = 1 if request.form.get("logo_spin") == "on" else 0
        ag.avatar_spin = avatar_spin
        ag.allow_flip = allow_flip

        ag.name = (request.form.get("name") or "").strip()
        ag.company = (request.form.get("company") or "").strip()
        ag.role = (request.form.get("role") or "").strip()
        ag.bio = (request.form.get("bio") or "").strip()

        ag.phone_mobile = (request.form.get("phone_mobile") or "").strip()
        ag.phone_mobile2 = (request.form.get("phone_mobile2") or "").strip()
        ag.phone_office = (request.form.get("phone_office") or "").strip()
        ag.whatsapp = (request.form.get("whatsapp") or "").strip()
        ag.emails = (request.form.get("emails") or "").strip()
        ag.websites = (request.form.get("websites") or "").strip()
        ag.pec = (request.form.get("pec") or "").strip()
        ag.addresses = (request.form.get("addresses") or "").strip()

        ag.piva = (request.form.get("piva") or "").strip()
        ag.sdi = (request.form.get("sdi") or "").strip()

        ag.facebook = (request.form.get("facebook") or "").strip()
        ag.instagram = (request.form.get("instagram") or "").strip()
        ag.linkedin = (request.form.get("linkedin") or "").strip()
        ag.tiktok = (request.form.get("tiktok") or "").strip()
        ag.telegram = (request.form.get("telegram") or "").strip()
        ag.youtube = (request.form.get("youtube") or "").strip()
        ag.spotify = (request.form.get("spotify") or "").strip()

        def safe_int(v, d):
            try:
                return int(v)
            except Exception:
                return d

        ag.photo_pos_x = safe_int(request.form.get("photo_pos_x"), 50)
        ag.photo_pos_y = safe_int(request.form.get("photo_pos_y"), 35)

        z = (request.form.get("photo_zoom") or "1.0").strip()
        try:
            float(z)
            ag.photo_zoom = z
        except Exception:
            ag.photo_zoom = "1.0"

        warnings = handle_media_uploads_p1(ag)
        save_i18n(ag, request.form)

        normalize_media_p1(ag)
        ag.updated_at = dt.datetime.utcnow()
        s.commit()

        flash("Salvato!", "ok")
        for w in warnings:
            flash(w, "warning")
        return redirect(url_for("edit_agent", slug=slug))

    normalize_media_p1(ag)
    set_profile_blob(ag, "p2", get_profile_blob(ag, "p2"))
    set_profile_blob(ag, "p3", get_profile_blob(ag, "p3"))
    s.commit()

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=False,
        editing_profile3=False,
        is_admin=True,
        p2_data=get_profile_blob(ag, "p2"),
        p3_data=get_profile_blob(ag, "p3"),
        i18n_data=load_i18n(ag),
        gallery=[x for x in (ag.gallery_urls or "").split("|") if x.strip()],
        videos=[x for x in (ag.video_urls or "").split("|") if x.strip()],
        pdfs=parse_pdf_items(ag.pdf1_url or ""),
        limits={"max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
                "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB}
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
    if int(ag.p2_enabled or 0) != 1:
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("edit_agent", slug=slug))

    blob = get_profile_blob(ag, "p2")

    if request.method == "POST":
        set_profile_data_from_form(blob, request.form)
        warnings = handle_media_uploads_into_blob(blob)
        set_profile_blob(ag, "p2", blob)
        save_i18n(ag, request.form)

        ag.updated_at = dt.datetime.utcnow()
        s.commit()
        flash("Profilo 2 salvato!", "ok")
        for w in warnings:
            flash(w, "warning")
        return redirect(url_for("admin_profile2", slug=slug))

    set_profile_blob(ag, "p2", blob)
    s.commit()

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=True,
        editing_profile3=False,
        is_admin=True,
        p2_data=blob,
        p3_data={},
        i18n_data=load_i18n(ag),
        gallery=[x for x in (blob.get("gallery_urls","") or "").split("|") if x.strip()],
        videos=[x for x in (blob.get("video_urls","") or "").split("|") if x.strip()],
        pdfs=parse_pdf_items(blob.get("pdf_urls","") or ""),
        limits={"max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
                "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB}
    )

@app.route("/area/edit/<slug>/p3", methods=["GET", "POST"])
def admin_profile3(slug):
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
        return redirect(url_for("edit_agent", slug=slug))

    blob = get_profile_blob(ag, "p3")

    if request.method == "POST":
        set_profile_data_from_form(blob, request.form)
        warnings = handle_media_uploads_into_blob(blob)
        set_profile_blob(ag, "p3", blob)
        save_i18n(ag, request.form)

        ag.updated_at = dt.datetime.utcnow()
        s.commit()
        flash("Profilo 3 salvato!", "ok")
        for w in warnings:
            flash(w, "warning")
        return redirect(url_for("admin_profile3", slug=slug))

    set_profile_blob(ag, "p3", blob)
    s.commit()

    return render_template(
        "agent_form.html",
        agent=ag,
        editing_profile2=False,
        editing_profile3=True,
        is_admin=True,
        p2_data={},
        p3_data=blob,
        i18n_data=load_i18n(ag),
        gallery=[x for x in (blob.get("gallery_urls","") or "").split("|") if x.strip()],
        videos=[x for x in (blob.get("video_urls","") or "").split("|") if x.strip()],
        pdfs=parse_pdf_items(blob.get("pdf_urls","") or ""),
        limits={"max_imgs": MAX_GALLERY_IMAGES, "max_vids": MAX_VIDEOS, "max_pdfs": MAX_PDFS,
                "img_mb": MAX_IMAGE_MB, "vid_mb": MAX_VIDEO_MB, "pdf_mb": MAX_PDF_MB}
    )


# ==========================
# ACTIVATE / DEACTIVATE P2,P3
# ==========================
def _activate_profile(ag: Agent, which: str):
    if which == "p2":
        ag.p2_enabled = 1
        ag.p2_json = "{}"
    elif which == "p3":
        ag.p3_enabled = 1
        ag.p3_json = "{}"
    else:
        abort(400)
    ag.updated_at = dt.datetime.utcnow()

def _deactivate_profile(ag: Agent, which: str):
    if which == "p2":
        ag.p2_enabled = 0
        ag.p2_json = "{}"
    elif which == "p3":
        ag.p3_enabled = 0
        ag.p3_json = "{}"
    else:
        abort(400)
    ag.updated_at = dt.datetime.utcnow()

@app.route("/area/admin/activate/<slug>/<which>", methods=["POST"])
def admin_activate_profile(slug, which):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    _activate_profile(ag, which)
    s.commit()
    flash(f"{which.upper()} attivato (vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/deactivate/<slug>/<which>", methods=["POST"])
def admin_deactivate_profile(slug, which):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    _deactivate_profile(ag, which)
    s.commit()
    flash(f"{which.upper()} disattivato (svuotato).", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# MEDIA DELETE (token anti doppio)
# ==========================
@app.route("/area/media/delete/<slug>", methods=["POST"])
def delete_media(slug):
    r = require_login()
    if r:
        return r

    token = (request.form.get("token") or "").strip()
    if token:
        if session.get("last_delete_token") == token:
            flash("Operazione già eseguita.", "warning")
            return redirect(url_for("dashboard"))
        session["last_delete_token"] = token

    t = (request.form.get("type") or "").strip()      # gallery | video | pdf
    idx = int(request.form.get("idx") or -1)
    profile = (request.form.get("profile") or "p1").strip().lower()

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    if not is_admin() and ag.slug != session.get("slug"):
        abort(403)

    if profile == "p1":
        normalize_media_p1(ag)

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
            ag.pdf1_url = normalize_pdf_string(pack_pdf_items(items))
        else:
            abort(400)

        normalize_media_p1(ag)
        ag.updated_at = dt.datetime.utcnow()
        s.commit()
        flash("Eliminato.", "ok")
        return redirect(url_for("edit_agent", slug=slug))

    which = "p2" if profile == "p2" else "p3"
    if which == "p2" and int(ag.p2_enabled or 0) != 1:
        abort(400)
    if which == "p3" and int(ag.p3_enabled or 0) != 1:
        abort(400)

    blob = get_profile_blob(ag, which)

    if t == "gallery":
        items = [x for x in (blob.get("gallery_urls","") or "").split("|") if x.strip()]
        if 0 <= idx < len(items):
            items.pop(idx)
            blob["gallery_urls"] = "|".join(items)
    elif t == "video":
        items = [x for x in (blob.get("video_urls","") or "").split("|") if x.strip()]
        if 0 <= idx < len(items):
            items.pop(idx)
            blob["video_urls"] = "|".join(items)
    elif t == "pdf":
        items = parse_pdf_items(blob.get("pdf_urls","") or "")
        if 0 <= idx < len(items):
            items.pop(idx)
        blob["pdf_urls"] = normalize_pdf_string(pack_pdf_items(items))
    else:
        abort(400)

    set_profile_blob(ag, which, blob)
    ag.updated_at = dt.datetime.utcnow()
    s.commit()
    flash("Eliminato.", "ok")

    return redirect(url_for("admin_profile2", slug=slug) if which == "p2" else url_for("admin_profile3", slug=slug))


# ==========================
# QR + VCF + CARD (come prima)
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
    if p == "p3" and int(ag.p3_enabled or 0) == 1:
        url = f"{base}/{ag.slug}?p=p3"

    img = qrcode.make(url)
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    filename = f"QR-{ag.slug}-{p.upper() if p else 'P1'}.png"
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

    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{full_name}"]
    if org: lines.append(f"ORG:{org}")
    if title: lines.append(f"TITLE:{title}")
    if tel1: lines.append(f"TEL;TYPE=CELL:{tel1}")
    if tel2: lines.append(f"TEL;TYPE=CELL:{tel2}")
    if office: lines.append(f"TEL;TYPE=WORK:{office}")
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

@app.route("/")
def home():
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
