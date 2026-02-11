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

# ✅ LIMITI
MAX_GALLERY_IMAGES = 15
MAX_VIDEOS = 8
MAX_PDFS = 10

# ✅ LIMITI PESO (MB)
MAX_IMAGE_MB = 4
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
@app.template_filter("loads")
def loads_filter(s):
    import json
    try:
        v = json.loads(s or "{}")
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}

app.secret_key = APP_SECRET

# ✅ JINJA FILTER: loads (serve per dashboard.html)
@app.template_filter("loads")
def _loads_filter(s):
    try:
        v = json.loads(s or "{}")
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}

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

    profiles_json = Column(Text, default="{}")

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
        add_col("profiles_json", "TEXT")

        for (name, coltype) in missing:
            conn.exec_driver_sql(f"ALTER TABLE agents ADD COLUMN {name} {coltype}")

        now = dt.datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        conn.exec_driver_sql("UPDATE agents SET created_at = COALESCE(created_at, :now)", {"now": now})
        conn.exec_driver_sql("UPDATE agents SET updated_at = COALESCE(updated_at, :now)", {"now": now})
        conn.exec_driver_sql("UPDATE agents SET profiles_json = COALESCE(profiles_json, '{}')")

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

def _file_size_bytes(file_storage):
    try:
        pos = file_storage.stream.tell()
        file_storage.stream.seek(0, os.SEEK_END)
        size = file_storage.stream.tell()
        file_storage.stream.seek(pos, os.SEEK_SET)
        return int(size or 0)
    except Exception:
        return 0

def _mb(bytes_n: int) -> float:
    return float(bytes_n) / (1024.0 * 1024.0)

def save_upload(file_storage, kind: str, max_mb: int):
    if not file_storage or not file_storage.filename:
        return ""

    size = _file_size_bytes(file_storage)
    if size > 0:
        if _mb(size) > float(max_mb):
            raise ValueError(f"File troppo grande: max {max_mb}MB.")

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

def _empty_profile():
    return {
        "enabled": 0,
        "data": {
            "name": "",
            "company": "",
            "role": "",
            "bio": "",
            "phone_mobile": "",
            "phone_mobile2": "",
            "phone_office": "",
            "whatsapp": "",
            "emails": "",
            "websites": "",
            "pec": "",
            "addresses": "",
            "piva": "",
            "sdi": "",
            "facebook": "",
            "instagram": "",
            "linkedin": "",
            "tiktok": "",
            "telegram": "",
            "youtube": "",
            "spotify": ""
        },
        "media": {
            "photo_url": "",
            "logo_url": "",
            "back_media_mode": "company",
            "back_media_url": "",
            "photo_pos_x": 50,
            "photo_pos_y": 35,
            "photo_zoom": "1.0",
            "gallery": [],
            "videos": [],
            "pdfs": []
        },
        "i18n": {
            "en": {"name":"","company":"","role":"","bio":"","addresses":""},
            "fr": {"name":"","company":"","role":"","bio":"","addresses":""},
            "es": {"name":"","company":"","role":"","bio":"","addresses":""},
            "de": {"name":"","company":"","role":"","bio":"","addresses":""}
        }
    }

def _ensure_profiles(agent: Agent):
    try:
        pj = json.loads(agent.profiles_json or "{}")
        if not isinstance(pj, dict):
            pj = {}
    except Exception:
        pj = {}

    changed = False
    for k in ["p1", "p2", "p3"]:
        if k not in pj or not isinstance(pj.get(k), dict):
            pj[k] = _empty_profile()
            changed = True

    if "enabled" not in pj["p1"]:
        pj["p1"]["enabled"] = 1
        changed = True

    if changed:
        agent.profiles_json = json.dumps(pj, ensure_ascii=False)

    return pj

def _save_profiles(agent: Agent, pj: dict):
    agent.profiles_json = json.dumps(pj, ensure_ascii=False)
    agent.updated_at = dt.datetime.utcnow()

def _get_profile(pj: dict, key: str):
    key = (key or "p1").lower().strip()
    if key not in ("p1", "p2", "p3"):
        key = "p1"
    return key, pj[key]

def _new_password(length=10):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    import random
    return "".join(random.choice(alphabet) for _ in range(length))


# ==========================
# FAVICON ROOT
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
        agents.sort(key=lambda x: ((x.slug or "").strip().lower(),))
        for a in agents:
            _ensure_profiles(a)
        s.commit()
        return render_template("dashboard.html", agents=agents, is_admin=True, agent=None)

    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        session.clear()
        return redirect(url_for("login"))

    _ensure_profiles(ag)
    s.commit()
    return render_template("dashboard.html", agents=[ag], is_admin=False, agent=ag)


# ==========================
# PROFILE UPDATE HELPERS
# ==========================
def _set_profile_data(profile: dict, form: dict):
    d = profile["data"]
    for k in [
        "name","company","role","bio",
        "phone_mobile","phone_mobile2","phone_office","whatsapp",
        "emails","websites","pec","addresses",
        "piva","sdi",
        "facebook","instagram","linkedin","tiktok","telegram","youtube","spotify"
    ]:
        d[k] = (form.get(k) or "").strip()

    m = profile["media"]
    m["back_media_mode"] = (form.get("back_media_mode") or "company").strip() or "company"

    def safe_int(v, dflt):
        try:
            return int(v)
        except Exception:
            return dflt

    m["photo_pos_x"] = safe_int(form.get("photo_pos_x"), 50)
    m["photo_pos_y"] = safe_int(form.get("photo_pos_y"), 35)

    z = (form.get("photo_zoom") or "1.0").strip()
    try:
        float(z)
        m["photo_zoom"] = z
    except Exception:
        m["photo_zoom"] = "1.0"

def _save_i18n(profile: dict, form: dict):
    i18n = profile.get("i18n") or {}
    for L in ["en", "fr", "es", "de"]:
        i18n[L] = {
            "name": (form.get(f"name_{L}") or "").strip(),
            "company": (form.get(f"company_{L}") or "").strip(),
            "role": (form.get(f"role_{L}") or "").strip(),
            "bio": (form.get(f"bio_{L}") or "").strip(),
            "addresses": (form.get(f"addresses_{L}") or "").strip(),
        }
    profile["i18n"] = i18n


# ==========================
# ADMIN/AGENT: EDIT PROFILE (P1/P2/P3)
# ==========================
@app.route("/area/edit/<slug>/<profile>", methods=["GET", "POST"])
def edit_agent_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    pj = _ensure_profiles(ag)
    profile_key, prof = _get_profile(pj, profile)

    if int(prof.get("enabled", 0)) != 1:
        flash(f"{profile_key.upper()} non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        _set_profile_data(prof, request.form)

        photo = request.files.get("photo")
        if photo and photo.filename:
            try:
                prof["media"]["photo_url"] = save_upload(photo, "images", MAX_IMAGE_MB)
            except Exception as e:
                flash(str(e), "error")
                return redirect(url_for("edit_agent_profile", slug=slug, profile=profile_key))

        logo = request.files.get("logo")
        if logo and logo.filename:
            try:
                prof["media"]["logo_url"] = save_upload(logo, "images", MAX_IMAGE_MB)
            except Exception as e:
                flash(str(e), "error")
                return redirect(url_for("edit_agent_profile", slug=slug, profile=profile_key))

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            try:
                prof["media"]["back_media_url"] = save_upload(back_media, "images", MAX_IMAGE_MB)
            except Exception as e:
                flash(str(e), "error")
                return redirect(url_for("edit_agent_profile", slug=slug, profile=profile_key))

        gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
        if gallery_files:
            current = prof["media"].get("gallery") or []
            room = max(0, MAX_GALLERY_IMAGES - len(current))
            gallery_files = gallery_files[:room]
            new_urls = []
            for f in gallery_files:
                try:
                    new_urls.append(save_upload(f, "images", MAX_IMAGE_MB))
                except Exception as e:
                    flash(str(e), "error")
                    return redirect(url_for("edit_agent_profile", slug=slug, profile=profile_key))
            prof["media"]["gallery"] = current + [u for u in new_urls if u]

        video_files = [f for f in request.files.getlist("videos") if f and f.filename]
        if video_files:
            current = prof["media"].get("videos") or []
            room = max(0, MAX_VIDEOS - len(current))
            video_files = video_files[:room]
            new_urls = []
            for f in video_files:
                try:
                    new_urls.append(save_upload(f, "videos", MAX_VIDEO_MB))
                except Exception as e:
                    flash(str(e), "error")
                    return redirect(url_for("edit_agent_profile", slug=slug, profile=profile_key))
            prof["media"]["videos"] = current + [u for u in new_urls if u]

        pdfs = prof["media"].get("pdfs") or []
        for i in range(1, MAX_PDFS + 1):
            f = request.files.get(f"pdf{i}")
            if f and f.filename:
                try:
                    url = save_upload(f, "pdf", MAX_PDF_MB)
                except Exception as e:
                    flash(str(e), "error")
                    return redirect(url_for("edit_agent_profile", slug=slug, profile=profile_key))
                name = secure_filename(f.filename) or f"PDF {i}"
                idx = i - 1
                while len(pdfs) <= idx:
                    pdfs.append({"name": "", "url": ""})
                pdfs[idx] = {"name": name, "url": url}
        prof["media"]["pdfs"] = [x for x in pdfs if x.get("url")]

        _save_i18n(prof, request.form)

        pj[profile_key] = prof
        _save_profiles(ag, pj)
        s.commit()

        flash("Salvato!", "ok")
        return redirect(url_for("edit_agent_profile", slug=slug, profile=profile_key))

    limits = {
        "imgs": MAX_GALLERY_IMAGES, "img_mb": MAX_IMAGE_MB,
        "vids": MAX_VIDEOS, "vid_mb": MAX_VIDEO_MB,
        "pdfs": MAX_PDFS, "pdf_mb": MAX_PDF_MB
    }

    return render_template(
        "agent_form.html",
        agent=ag,
        profile_key=profile_key,
        profile=prof,
        is_admin=True,
        limits=limits
    )


@app.route("/area/me/<profile>", methods=["GET", "POST"])
def me_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    pj = _ensure_profiles(ag)
    profile_key, prof = _get_profile(pj, profile)

    if int(prof.get("enabled", 0)) != 1:
        flash(f"{profile_key.upper()} non attivo", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        _set_profile_data(prof, request.form)

        photo = request.files.get("photo")
        if photo and photo.filename:
            try:
                prof["media"]["photo_url"] = save_upload(photo, "images", MAX_IMAGE_MB)
            except Exception as e:
                flash(str(e), "error")
                return redirect(url_for("me_profile", profile=profile_key))

        logo = request.files.get("logo")
        if logo and logo.filename:
            try:
                prof["media"]["logo_url"] = save_upload(logo, "images", MAX_IMAGE_MB)
            except Exception as e:
                flash(str(e), "error")
                return redirect(url_for("me_profile", profile=profile_key))

        back_media = request.files.get("back_media")
        if back_media and back_media.filename:
            try:
                prof["media"]["back_media_url"] = save_upload(back_media, "images", MAX_IMAGE_MB)
            except Exception as e:
                flash(str(e), "error")
                return redirect(url_for("me_profile", profile=profile_key))

        gallery_files = [f for f in request.files.getlist("gallery") if f and f.filename]
        if gallery_files:
            current = prof["media"].get("gallery") or []
            room = max(0, MAX_GALLERY_IMAGES - len(current))
            gallery_files = gallery_files[:room]
            new_urls = []
            for f in gallery_files:
                try:
                    new_urls.append(save_upload(f, "images", MAX_IMAGE_MB))
                except Exception as e:
                    flash(str(e), "error")
                    return redirect(url_for("me_profile", profile=profile_key))
            prof["media"]["gallery"] = current + [u for u in new_urls if u]

        video_files = [f for f in request.files.getlist("videos") if f and f.filename]
        if video_files:
            current = prof["media"].get("videos") or []
            room = max(0, MAX_VIDEOS - len(current))
            video_files = video_files[:room]
            new_urls = []
            for f in video_files:
                try:
                    new_urls.append(save_upload(f, "videos", MAX_VIDEO_MB))
                except Exception as e:
                    flash(str(e), "error")
                    return redirect(url_for("me_profile", profile=profile_key))
            prof["media"]["videos"] = current + [u for u in new_urls if u]

        pdfs = prof["media"].get("pdfs") or []
        for i in range(1, MAX_PDFS + 1):
            f = request.files.get(f"pdf{i}")
            if f and f.filename:
                try:
                    url = save_upload(f, "pdf", MAX_PDF_MB)
                except Exception as e:
                    flash(str(e), "error")
                    return redirect(url_for("me_profile", profile=profile_key))
                name = secure_filename(f.filename) or f"PDF {i}"
                idx = i - 1
                while len(pdfs) <= idx:
                    pdfs.append({"name": "", "url": ""})
                pdfs[idx] = {"name": name, "url": url}
        prof["media"]["pdfs"] = [x for x in pdfs if x.get("url")]

        _save_i18n(prof, request.form)

        pj[profile_key] = prof
        _save_profiles(ag, pj)
        s.commit()

        flash("Salvato!", "ok")
        return redirect(url_for("me_profile", profile=profile_key))

    limits = {
        "imgs": MAX_GALLERY_IMAGES, "img_mb": MAX_IMAGE_MB,
        "vids": MAX_VIDEOS, "vid_mb": MAX_VIDEO_MB,
        "pdfs": MAX_PDFS, "pdf_mb": MAX_PDF_MB
    }

    return render_template(
        "agent_form.html",
        agent=ag,
        profile_key=profile_key,
        profile=prof,
        is_admin=False,
        limits=limits
    )


# ==========================
# ACTIVATE / DELETE P1 P2 P3
# ==========================
def _reset_profile(pj: dict, key: str, enable: int):
    p = _empty_profile()
    p["enabled"] = 1 if enable else 0
    pj[key] = p

@app.route("/area/admin/activate/<slug>/<profile>", methods=["POST"])
def admin_activate_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    pj = _ensure_profiles(ag)
    profile_key, _ = _get_profile(pj, profile)

    _reset_profile(pj, profile_key, enable=1)

    _save_profiles(ag, pj)
    s.commit()
    flash(f"{profile_key.upper()} attivato (nuovo e vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/admin/delete/<slug>/<profile>", methods=["POST"])
def admin_delete_profile(slug, profile):
    r = require_login()
    if r:
        return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    pj = _ensure_profiles(ag)
    profile_key, _ = _get_profile(pj, profile)

    if profile_key == "p1":
        _reset_profile(pj, "p1", enable=0)
        _reset_profile(pj, "p2", enable=0)
        _reset_profile(pj, "p3", enable=0)
        _save_profiles(ag, pj)
        s.commit()
        flash("P1 eliminato: reset totale (P1/P2/P3 svuotati e disattivati).", "ok")
        return redirect(url_for("dashboard"))

    _reset_profile(pj, profile_key, enable=0)
    _save_profiles(ag, pj)
    s.commit()
    flash(f"{profile_key.upper()} eliminato (svuotato e disattivato).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/me/activate/<profile>", methods=["POST"])
def me_activate_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    pj = _ensure_profiles(ag)
    profile_key, _ = _get_profile(pj, profile)

    _reset_profile(pj, profile_key, enable=1)

    _save_profiles(ag, pj)
    s.commit()
    flash(f"{profile_key.upper()} attivato (nuovo e vuoto).", "ok")
    return redirect(url_for("dashboard"))

@app.route("/area/me/delete/<profile>", methods=["POST"])
def me_delete_profile(profile):
    r = require_login()
    if r:
        return r
    if is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        abort(404)

    pj = _ensure_profiles(ag)
    profile_key, _ = _get_profile(pj, profile)

    if profile_key == "p1":
        _reset_profile(pj, "p1", enable=0)
        _reset_profile(pj, "p2", enable=0)
        _reset_profile(pj, "p3", enable=0)
        _save_profiles(ag, pj)
        s.commit()
        flash("P1 eliminato: reset totale (P1/P2/P3 svuotati e disattivati).", "ok")
        return redirect(url_for("dashboard"))

    _reset_profile(pj, profile_key, enable=0)
    _save_profiles(ag, pj)
    s.commit()
    flash(f"{profile_key.upper()} eliminato.", "ok")
    return redirect(url_for("dashboard"))


# ==========================
# QR PNG (inline => apre subito)
# ==========================
@app.route("/qr/<slug>.png")
def qr_png(slug):
    if qrcode is None:
        abort(500)

    p = (request.args.get("p") or "p1").strip().lower()
    if p not in ("p1", "p2", "p3"):
        p = "p1"

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    pj = _ensure_profiles(ag)
    prof = pj.get(p) or _empty_profile()
    if int(prof.get("enabled", 0)) != 1:
        abort(404)

    base = public_base_url()
    url = f"{base}/{ag.slug}?p={p}"

    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    filename = f"QR-{ag.slug}-{p.upper()}.png"
    return Response(
        buf.getvalue(),
        mimetype="image/png",
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )


# ==========================
# CARD PUBLIC (placeholder per ora)
# ==========================
@app.route("/<slug>")
def card(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    p = (request.args.get("p") or "p1").strip().lower()
    if p not in ("p1", "p2", "p3"):
        p = "p1"

    pj = _ensure_profiles(ag)
    prof = pj.get(p) or _empty_profile()
    if int(prof.get("enabled", 0)) != 1:
        abort(404)

    return render_template("card.html", agent=ag, profile_key=p, profile=prof)


@app.route("/")
def home():
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
