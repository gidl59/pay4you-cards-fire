import os
import re
import uuid
import json
import base64
from datetime import datetime
from urllib.parse import quote_plus

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, abort, flash, send_from_directory
)

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError

from dotenv import load_dotenv

load_dotenv()

# =========================
# ENV / CONFIG
# =========================
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")  # es: https://pay4you-cards-fire.onrender.com

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////var/data/pay4you.db").strip()
PERSIST_UPLOADS_DIR = os.getenv("PERSIST_UPLOADS_DIR", "/var/data/uploads").strip()

MAX_GALLERY_IMAGES = 30
MAX_VIDEOS = 10
MAX_PDFS = 12

# =========================
# APP
# =========================
app = Flask(__name__)
app.secret_key = APP_SECRET

# =========================
# DB
# =========================
Base = declarative_base()

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    slug = Column(String(120), unique=True, nullable=False)
    username = Column(String(120), unique=True, nullable=False)  # login user
    password = Column(String(255), nullable=False)

    # P1 base
    name = Column(String(255), default="")
    company = Column(String(255), default="")
    role = Column(String(255), default="")
    bio = Column(Text, default="")

    phone_mobile = Column(String(80), default="")
    phone_mobile2 = Column(String(80), default="")
    phone_office = Column(String(80), default="")
    whatsapp = Column(String(255), default="")
    emails = Column(String(255), default="")     # comma separated
    websites = Column(String(255), default="")   # comma separated
    pec = Column(String(255), default="")
    addresses = Column(Text, default="")         # one per line

    piva = Column(String(80), default="")
    sdi = Column(String(80), default="")

    facebook = Column(String(255), default="")
    instagram = Column(String(255), default="")
    linkedin = Column(String(255), default="")
    tiktok = Column(String(255), default="")
    telegram = Column(String(255), default="")
    youtube = Column(String(255), default="")
    spotify = Column(String(255), default="")

    photo_url = Column(String(500), default="")
    logo_url = Column(String(500), default="")
    back_media_mode = Column(String(30), default="company")  # company/personal
    back_media_url = Column(String(500), default="")

    photo_pos_x = Column(Integer, default=50)
    photo_pos_y = Column(Integer, default=35)
    photo_zoom = Column(String(20), default="1.0")

    orbit_spin = Column(Integer, default=0)
    avatar_spin = Column(Integer, default=0)
    logo_spin = Column(Integer, default=0)
    allow_flip = Column(Integer, default=0)

    # Media lists for P1
    gallery_urls = Column(Text, default="")  # "|" separated
    video_urls = Column(Text, default="")    # "|" separated
    pdf1_url = Column(Text, default="")      # store "name||url|name||url|..."

    # P2 enabled + JSON data
    p2_enabled = Column(Integer, default=0)
    p2_json = Column(Text, default="")       # JSON string for P2 fields

    created_at = Column(DateTime, default=datetime.utcnow)


def _engine_from_url(url: str):
    # sqlite needs check_same_thread=False
    if url.startswith("sqlite:"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)

engine = _engine_from_url(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(engine)

init_db()

# =========================
# HELPERS
# =========================
def db():
    return SessionLocal()

def is_admin():
    return session.get("role") == "admin"

def require_login():
    if not session.get("role"):
        return redirect(url_for("login"))
    return None

def clean_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s

def ensure_dirs():
    os.makedirs(PERSIST_UPLOADS_DIR, exist_ok=True)
    os.makedirs(os.path.join(PERSIST_UPLOADS_DIR, "img"), exist_ok=True)
    os.makedirs(os.path.join(PERSIST_UPLOADS_DIR, "video"), exist_ok=True)
    os.makedirs(os.path.join(PERSIST_UPLOADS_DIR, "pdf"), exist_ok=True)

ensure_dirs()

def save_upload(file_storage, subdir: str, slug: str) -> str:
    """
    Save upload to /var/data/uploads/<subdir>/<slug>/...
    Return URL path: /uploads/<subdir>/<slug>/<filename>
    """
    if not file_storage or not file_storage.filename:
        return ""

    ext = os.path.splitext(file_storage.filename)[1].lower()
    safe_name = re.sub(r"[^a-zA-Z0-9\.\-_]+", "_", os.path.splitext(file_storage.filename)[0]).strip("_")
    safe_name = (safe_name[:60] if safe_name else "file")
    fname = f"{safe_name}_{uuid.uuid4().hex[:10]}{ext}"

    dir_path = os.path.join(PERSIST_UPLOADS_DIR, subdir, slug)
    os.makedirs(dir_path, exist_ok=True)
    abs_path = os.path.join(dir_path, fname)
    file_storage.save(abs_path)

    return f"/uploads/{subdir}/{slug}/{fname}"

def split_pipe(s: str):
    if not s:
        return []
    return [x for x in s.split("|") if x.strip()]

def join_pipe(items):
    return "|".join([x for x in items if x])

def parse_pdfs(raw: str):
    """
    raw: "name||/url|name||/url|..."
    """
    out = []
    for item in split_pipe(raw):
        if "||" in item:
            name, url = item.split("||", 1)
        else:
            name, url = item, item
        out.append({"name": name, "url": url})
    return out

def build_pdfs_raw(pdfs):
    # pdfs: list of dict {name,url}
    items = []
    for p in pdfs:
        name = (p.get("name") or "").strip()
        url = (p.get("url") or "").strip()
        if not url:
            continue
        if not name:
            name = os.path.basename(url)
        items.append(f"{name}||{url}")
    return join_pipe(items)

def normalize_whatsapp(val: str):
    v = (val or "").strip()
    if not v:
        return ""
    if v.startswith("http://") or v.startswith("https://"):
        return v
    # number: keep digits + +
    digits = re.sub(r"[^\d\+]", "", v)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("39") and not digits.startswith("+"):
        digits = "+" + digits
    if not digits.startswith("+"):
        # best guess
        digits = "+39" + re.sub(r"[^\d]", "", digits)
    return f"https://wa.me/{digits.replace('+','')}"

def safe_list_from_csv(s: str):
    if not s:
        return []
    parts = [x.strip() for x in s.split(",") if x.strip()]
    return parts

def t(lang):
    # super minimal translator (keep your existing if you had one)
    IT = {
        "actions": "Azioni",
        "save_contact": "Salva contatto",
        "whatsapp": "WhatsApp",
        "scan_qr": "QR",
        "contacts": "Contatti",
        "mobile_phone": "Cellulare",
        "office_phone": "Ufficio",
        "open_website": "Sito",
        "open_maps": "Apri Maps",
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
        "data": "Dati",
        "vat": "P.IVA",
        "sdi": "SDI"
    }
    return IT

def current_base_url():
    if BASE_URL:
        return BASE_URL
    # fallback: request.url_root is available only in request context; used in templates too
    return ""

# =========================
# STATIC UPLOADS
# =========================
@app.route("/uploads/<path:subpath>")
def uploads(subpath):
    # serve from PERSIST_UPLOADS_DIR
    return send_from_directory(PERSIST_UPLOADS_DIR, subpath)

# =========================
# AUTH
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = (request.form.get("password") or "").strip()

        if username == "admin" and password == ADMIN_PASSWORD:
            session["role"] = "admin"
            session["username"] = "admin"
            return redirect(url_for("dashboard"))

        s = db()
        ag = s.query(Agent).filter(Agent.username == username).first()
        s.close()
        if ag and ag.password == password:
            session["role"] = "agent"
            session["username"] = username
            session["slug"] = ag.slug
            return redirect(url_for("dashboard"))

        flash("Credenziali non valide", "error")
        return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():
    r = require_login()
    if r: return r

    s = db()
    if is_admin():
        agents = s.query(Agent).order_by(Agent.created_at.desc()).all()
        agent = None
    else:
        agent = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
        agents = [agent] if agent else []
    s.close()

    return render_template("admin_list.html", agents=agents, is_admin=is_admin(), agent=agent)

# =========================
# CREATE AGENT (ADMIN)
# =========================
@app.route("/admin/new", methods=["GET", "POST"])
def new_agent():
    r = require_login()
    if r: return r
    if not is_admin():
        abort(403)

    if request.method == "POST":
        slug = clean_slug(request.form.get("slug"))
        name = (request.form.get("name") or "").strip()
        if not slug or not name:
            flash("Slug e Nome sono obbligatori", "error")
            return redirect(url_for("new_agent"))

        # default credentials: username=slug, password=random short
        username = slug
        password = uuid.uuid4().hex[:8]

        s = db()
        ag = Agent(slug=slug, username=username, password=password, name=name)
        try:
            s.add(ag)
            s.commit()
        except IntegrityError:
            s.rollback()
            s.close()
            flash("Slug già esistente", "error")
            return redirect(url_for("new_agent"))

        s.close()
        flash(f"Card creata. Username: {username} Password: {password}", "ok")
        return redirect(url_for("dashboard"))

    return render_template("agent_form.html", agent=None, editing_profile2=False, i18n_data={})

# =========================
# EDIT P1/P2 (ADMIN)
# =========================
@app.route("/admin/<slug>/edit", methods=["GET", "POST"])
def edit_agent(slug):
    r = require_login()
    if r: return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        s.close()
        abort(404)

    if request.method == "POST":
        apply_form_to_agent(ag, request, editing_profile2=False)
        s.commit()
        s.close()
        flash("Salvato Profilo 1", "ok")
        return redirect(url_for("dashboard"))

    i18n_data = {}
    s.close()
    return render_template("agent_form.html", agent=ag, editing_profile2=False, i18n_data=i18n_data)

@app.route("/admin/<slug>/p2", methods=["GET", "POST"])
def admin_profile2(slug):
    r = require_login()
    if r: return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        s.close()
        abort(404)

    if (ag.p2_enabled or 0) != 1:
        s.close()
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))

    # load p2 json into a temp dict (so template uses agent fields normally)
    p2 = json.loads(ag.p2_json or "{}")
    ag_view = clone_agent_for_profile(ag, p2)

    if request.method == "POST":
        # save changes into p2 json, not overwrite p1
        p2 = apply_form_to_profile_json(ag, request)
        ag.p2_json = json.dumps(p2, ensure_ascii=False)
        s.commit()
        s.close()
        flash("Salvato Profilo 2", "ok")
        return redirect(url_for("dashboard"))

    i18n_data = {}
    s.close()
    return render_template("agent_form.html", agent=ag_view, editing_profile2=True, i18n_data=i18n_data)

@app.route("/admin/<slug>/delete", methods=["POST"])
def delete_agent(slug):
    r = require_login()
    if r: return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        s.close()
        abort(404)
    s.delete(ag)
    s.commit()
    s.close()
    flash("Card eliminata", "ok")
    return redirect(url_for("dashboard"))

# =========================
# ACTIVATE / DEACTIVATE P2
# =========================
@app.route("/admin/<slug>/p2/activate", methods=["POST"])
def admin_activate_p2(slug):
    r = require_login()
    if r: return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        s.close()
        abort(404)

    ag.p2_enabled = 1
    # IMPORTANT: start empty, do not copy P1
    ag.p2_json = json.dumps({}, ensure_ascii=False)
    s.commit()
    s.close()
    flash("Profilo 2 attivato (vuoto)", "ok")
    return redirect(url_for("dashboard"))

@app.route("/admin/<slug>/p2/deactivate", methods=["POST"])
def admin_deactivate_p2(slug):
    r = require_login()
    if r: return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        s.close()
        abort(404)

    ag.p2_enabled = 0
    ag.p2_json = json.dumps({}, ensure_ascii=False)
    s.commit()
    s.close()
    flash("Profilo 2 disattivato", "ok")
    return redirect(url_for("dashboard"))

# =========================
# SELF (AGENT) EDIT
# =========================
@app.route("/me/edit", methods=["GET", "POST"])
def me_edit():
    r = require_login()
    if r: return r
    if is_admin():
        return redirect(url_for("dashboard"))

    slug = session.get("slug")
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        s.close()
        abort(404)

    if request.method == "POST":
        apply_form_to_agent(ag, request, editing_profile2=False)
        s.commit()
        s.close()
        flash("Salvato Profilo 1", "ok")
        return redirect(url_for("dashboard"))

    i18n_data = {}
    s.close()
    return render_template("agent_form.html", agent=ag, editing_profile2=False, i18n_data=i18n_data)

@app.route("/me/p2", methods=["GET", "POST"])
def me_profile2():
    r = require_login()
    if r: return r
    if is_admin():
        return redirect(url_for("dashboard"))

    slug = session.get("slug")
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        s.close()
        abort(404)

    if (ag.p2_enabled or 0) != 1:
        s.close()
        flash("Profilo 2 non attivo", "error")
        return redirect(url_for("dashboard"))

    p2 = json.loads(ag.p2_json or "{}")
    ag_view = clone_agent_for_profile(ag, p2)

    if request.method == "POST":
        p2 = apply_form_to_profile_json(ag, request)
        ag.p2_json = json.dumps(p2, ensure_ascii=False)
        s.commit()
        s.close()
        flash("Salvato Profilo 2", "ok")
        return redirect(url_for("dashboard"))

    i18n_data = {}
    s.close()
    return render_template("agent_form.html", agent=ag_view, editing_profile2=True, i18n_data=i18n_data)

@app.route("/me/p2/activate", methods=["POST"])
def me_activate_p2():
    r = require_login()
    if r: return r
    if is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        s.close()
        abort(404)

    ag.p2_enabled = 1
    ag.p2_json = json.dumps({}, ensure_ascii=False)
    s.commit()
    s.close()
    flash("Profilo 2 attivato (vuoto)", "ok")
    return redirect(url_for("dashboard"))

@app.route("/me/p2/deactivate", methods=["POST"])
def me_deactivate_p2():
    r = require_login()
    if r: return r
    if is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    if not ag:
        s.close()
        abort(404)

    ag.p2_enabled = 0
    ag.p2_json = json.dumps({}, ensure_ascii=False)
    s.commit()
    s.close()
    flash("Profilo 2 disattivato", "ok")
    return redirect(url_for("dashboard"))

# =========================
# CREDENTIALS
# =========================
@app.route("/me/credentials")
def me_credentials():
    r = require_login()
    if r: return r
    if is_admin():
        return redirect(url_for("dashboard"))

    s = db()
    ag = s.query(Agent).filter(Agent.slug == session.get("slug")).first()
    s.close()
    if not ag:
        abort(404)

    return render_template("credentials.html", ag=ag, is_admin=False)

@app.route("/admin/<slug>/credentials")
def admin_credentials_html(slug):
    r = require_login()
    if r: return r
    if not is_admin():
        abort(403)

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    s.close()
    if not ag:
        abort(404)
    return render_template("credentials.html", ag=ag, is_admin=True)

# =========================
# DELETE SINGLE MEDIA (P1)
# =========================
@app.route("/admin/<slug>/media/delete", methods=["POST"])
def admin_delete_media(slug):
    r = require_login()
    if r: return r
    if not is_admin():
        abort(403)

    kind = (request.form.get("kind") or "").strip()  # gallery/video/pdf
    url = (request.form.get("url") or "").strip()

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        s.close()
        abort(404)

    if kind == "gallery":
        items = split_pipe(ag.gallery_urls)
        items = [x for x in items if x != url]
        ag.gallery_urls = join_pipe(items)

    elif kind == "video":
        items = split_pipe(ag.video_urls)
        items = [x for x in items if x != url]
        ag.video_urls = join_pipe(items)

    elif kind == "pdf":
        pdfs = parse_pdfs(ag.pdf1_url)
        pdfs = [p for p in pdfs if p.get("url") != url]
        ag.pdf1_url = build_pdfs_raw(pdfs)

    s.commit()
    s.close()
    flash("Elemento eliminato", "ok")
    return redirect(url_for("edit_agent", slug=slug))

@app.route("/me/media/delete", methods=["POST"])
def me_delete_media():
    r = require_login()
    if r: return r
    if is_admin():
        abort(403)

    slug = session.get("slug")
    kind = (request.form.get("kind") or "").strip()
    url = (request.form.get("url") or "").strip()

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        s.close()
        abort(404)

    if kind == "gallery":
        items = split_pipe(ag.gallery_urls)
        items = [x for x in items if x != url]
        ag.gallery_urls = join_pipe(items)

    elif kind == "video":
        items = split_pipe(ag.video_urls)
        items = [x for x in items if x != url]
        ag.video_urls = join_pipe(items)

    elif kind == "pdf":
        pdfs = parse_pdfs(ag.pdf1_url)
        pdfs = [p for p in pdfs if p.get("url") != url]
        ag.pdf1_url = build_pdfs_raw(pdfs)

    s.commit()
    s.close()
    flash("Elemento eliminato", "ok")
    return redirect(url_for("me_edit"))

# =========================
# PUBLIC CARD + VCF + QR
# =========================
@app.route("/<slug>")
def public_card(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    s.close()
    if not ag:
        abort(404)

    lang = (request.args.get("lang") or "it").lower()
    p_key = (request.args.get("p") or "").lower()

    # pick profile data
    p2_enabled = (ag.p2_enabled or 0) == 1
    if p_key == "p2" and p2_enabled:
        p2 = json.loads(ag.p2_json or "{}")
        ag_view = clone_agent_for_profile(ag, p2)
    else:
        ag_view = ag

    # build lists
    mobiles = [x for x in [ag_view.phone_mobile, ag_view.phone_mobile2] if (x or "").strip()]
    office_value = (ag_view.phone_office or "").strip()
    emails = safe_list_from_csv(ag_view.emails)
    websites = safe_list_from_csv(ag_view.websites)
    pec_email = (ag_view.pec or "").strip()

    addresses = []
    for line in (ag_view.addresses or "").splitlines():
        line = line.strip()
        if not line:
            continue
        q = quote_plus(line)
        addresses.append({"text": line, "maps": f"https://www.google.com/maps/search/?api=1&query={q}"})

    gallery = split_pipe(ag_view.gallery_urls)
    videos = split_pipe(ag_view.video_urls)
    pdfs = parse_pdfs(ag_view.pdf1_url)

    wa_link = normalize_whatsapp(ag_view.whatsapp) if ag_view.whatsapp else ""
    base_url = BASE_URL or request.url_root.strip().rstrip("/")

    qr_url = f"/{ag.slug}/qr.png" + (f"?p={p_key}" if p_key else "")

    return render_template(
        "card.html",
        ag=ag_view,
        lang=lang,
        base_url=base_url,
        p2_enabled=p2_enabled,
        p_key=("p2" if (p_key == "p2" and p2_enabled) else ""),
        t_func=t(lang),
        mobiles=mobiles,
        office_value=office_value,
        emails=emails,
        websites=websites,
        pec_email=pec_email,
        addresses=addresses,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        wa_link=wa_link,
        qr_url=qr_url
    )

@app.route("/<slug>.vcf")
def vcf(slug):
    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    s.close()
    if not ag:
        abort(404)

    p_key = (request.args.get("p") or "").lower()
    if p_key == "p2" and (ag.p2_enabled or 0) == 1:
        p2 = json.loads(ag.p2_json or "{}")
        ag = clone_agent_for_profile(ag, p2)

    name = (ag.name or "").strip()
    org = (ag.company or "").strip()
    title = (ag.role or "").strip()
    tel = (ag.phone_mobile or "").strip()
    email = (safe_list_from_csv(ag.emails)[0] if ag.emails else "").strip()

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{name};;;;",
        f"FN:{name}",
    ]
    if org:
        lines.append(f"ORG:{org}")
    if title:
        lines.append(f"TITLE:{title}")
    if tel:
        lines.append(f"TEL;TYPE=CELL:{tel}")
    if email:
        lines.append(f"EMAIL:{email}")
    lines.append("END:VCARD")

    v = "\n".join(lines)
    return app.response_class(v, mimetype="text/vcard")

@app.route("/<slug>/qr.png")
def qr_png(slug):
    # very simple: render QR via an embedded SVG-ish approach not needed; easiest is to serve a prebuilt static
    # To keep dependency-free, we generate a PNG using qrcode if installed.
    import qrcode
    from io import BytesIO
    from flask import send_file

    s = db()
    ag = s.query(Agent).filter(Agent.slug == slug).first()
    s.close()
    if not ag:
        abort(404)

    base_url = BASE_URL or request.url_root.strip().rstrip("/")
    p_key = (request.args.get("p") or "").lower()
    url = f"{base_url}/{ag.slug}" + (f"?p={p_key}" if p_key else "")

    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# =========================
# APPLY FORM TO AGENT (P1)
# =========================
def apply_form_to_agent(ag: Agent, req, editing_profile2: bool):
    """
    editing_profile2=False: save directly into columns (P1)
    """
    # text fields
    ag.name = (req.form.get("name") or "").strip()
    ag.company = (req.form.get("company") or "").strip()
    ag.role = (req.form.get("role") or "").strip()
    ag.bio = (req.form.get("bio") or "").strip()

    ag.phone_mobile = (req.form.get("phone_mobile") or "").strip()
    ag.phone_mobile2 = (req.form.get("phone_mobile2") or "").strip()
    ag.phone_office = (req.form.get("phone_office") or "").strip()
    ag.whatsapp = (req.form.get("whatsapp") or "").strip()
    ag.emails = (req.form.get("emails") or "").strip()
    ag.websites = (req.form.get("websites") or "").strip()
    ag.pec = (req.form.get("pec") or "").strip()
    ag.addresses = (req.form.get("addresses") or "").strip()

    ag.piva = (req.form.get("piva") or "").strip()
    ag.sdi = (req.form.get("sdi") or "").strip()

    ag.facebook = (req.form.get("facebook") or "").strip()
    ag.instagram = (req.form.get("instagram") or "").strip()
    ag.linkedin = (req.form.get("linkedin") or "").strip()
    ag.tiktok = (req.form.get("tiktok") or "").strip()
    ag.telegram = (req.form.get("telegram") or "").strip()
    ag.youtube = (req.form.get("youtube") or "").strip()
    ag.spotify = (req.form.get("spotify") or "").strip()

    ag.back_media_mode = (req.form.get("back_media_mode") or "company").strip() or "company"

    # crop/zoom
    try:
        ag.photo_pos_x = int(req.form.get("photo_pos_x") or 50)
    except:
        ag.photo_pos_x = 50
    try:
        ag.photo_pos_y = int(req.form.get("photo_pos_y") or 35)
    except:
        ag.photo_pos_y = 35
    try:
        ag.photo_zoom = str(float(req.form.get("photo_zoom") or 1.0))
    except:
        ag.photo_zoom = "1.0"

    # effects
    ag.orbit_spin = 1 if req.form.get("orbit_spin") == "on" else 0
    ag.avatar_spin = 1 if req.form.get("avatar_spin") == "on" else 0
    ag.logo_spin = 1 if req.form.get("logo_spin") == "on" else 0
    ag.allow_flip = 1 if req.form.get("allow_flip") == "on" else 0

    # if avatar spin -> disable flip
    if ag.avatar_spin == 1:
        ag.allow_flip = 0

    # uploads
    if req.files.get("photo") and req.files.get("photo").filename:
        ag.photo_url = save_upload(req.files["photo"], "img", ag.slug)

    if req.files.get("logo") and req.files.get("logo").filename:
        ag.logo_url = save_upload(req.files["logo"], "img", ag.slug)

    if req.files.get("back_media") and req.files.get("back_media").filename:
        ag.back_media_url = save_upload(req.files["back_media"], "img", ag.slug)

    # gallery (append)
    gallery_files = req.files.getlist("gallery")
    if gallery_files:
        existing = split_pipe(ag.gallery_urls)
        for f in gallery_files:
            if not f or not f.filename:
                continue
            if len(existing) >= MAX_GALLERY_IMAGES:
                break
            existing.append(save_upload(f, "img", ag.slug))
        ag.gallery_urls = join_pipe(existing)

    # videos (append)
    video_files = req.files.getlist("videos")
    if video_files:
        existing = split_pipe(ag.video_urls)
        for f in video_files:
            if not f or not f.filename:
                continue
            if len(existing) >= MAX_VIDEOS:
                break
            existing.append(save_upload(f, "video", ag.slug))
        ag.video_urls = join_pipe(existing)

    # pdf slots (append each uploaded)
    pdfs = parse_pdfs(ag.pdf1_url)
    for i in range(1, MAX_PDFS + 1):
        key = f"pdf{i}"
        if req.files.get(key) and req.files.get(key).filename:
            url = save_upload(req.files[key], "pdf", ag.slug)
            name = req.files[key].filename
            pdfs.append({"name": name, "url": url})
    # keep last MAX_PDFS
    pdfs = pdfs[:MAX_PDFS]
    ag.pdf1_url = build_pdfs_raw(pdfs)

def clone_agent_for_profile(ag: Agent, data: dict) -> Agent:
    """
    Returns a lightweight object that behaves like Agent in templates (same attributes),
    overriding with values in data dict.
    """
    class Obj: pass
    o = Obj()
    # copy all simple fields from ag
    for k in ag.__dict__.keys():
        if k.startswith("_"):
            continue
        setattr(o, k, getattr(ag, k))
    # apply overrides
    for k, v in (data or {}).items():
        setattr(o, k, v)
    # keep original slug
    o.slug = ag.slug
    return o

def apply_form_to_profile_json(ag_main: Agent, req) -> dict:
    """
    Build P2 json from form fields; it starts from existing json (so you can partial edit).
    IMPORTANT: doesn't copy from P1; only what the user fills.
    """
    p2 = json.loads(ag_main.p2_json or "{}")

    def setv(key):
        p2[key] = (req.form.get(key) or "").strip()

    # same keys used in template
    for key in [
        "name","company","role","bio",
        "phone_mobile","phone_mobile2","phone_office","whatsapp",
        "emails","websites","pec","addresses",
        "piva","sdi",
        "facebook","instagram","linkedin","tiktok","telegram","youtube","spotify",
        "back_media_mode"
    ]:
        setv(key)

    # crop/zoom numeric
    def seti(key, default):
        try:
            p2[key] = int(req.form.get(key) or default)
        except:
            p2[key] = default

    seti("photo_pos_x", 50)
    seti("photo_pos_y", 35)
    try:
        p2["photo_zoom"] = str(float(req.form.get("photo_zoom") or 1.0))
    except:
        p2["photo_zoom"] = "1.0"

    # effects
    p2["orbit_spin"] = 1 if req.form.get("orbit_spin") == "on" else 0
    p2["avatar_spin"] = 1 if req.form.get("avatar_spin") == "on" else 0
    p2["logo_spin"] = 1 if req.form.get("logo_spin") == "on" else 0
    p2["allow_flip"] = 1 if req.form.get("allow_flip") == "on" else 0
    if p2["avatar_spin"] == 1:
        p2["allow_flip"] = 0

    # uploads: P2 uses same storage but stored inside json keys
    if req.files.get("photo") and req.files.get("photo").filename:
        p2["photo_url"] = save_upload(req.files["photo"], "img", ag_main.slug)
    if req.files.get("logo") and req.files.get("logo").filename:
        p2["logo_url"] = save_upload(req.files["logo"], "img", ag_main.slug)
    if req.files.get("back_media") and req.files.get("back_media").filename:
        p2["back_media_url"] = save_upload(req.files["back_media"], "img", ag_main.slug)

    # media lists: stored in json keys
    g_existing = split_pipe(p2.get("gallery_urls",""))
    for f in req.files.getlist("gallery"):
        if not f or not f.filename:
            continue
        if len(g_existing) >= MAX_GALLERY_IMAGES:
            break
        g_existing.append(save_upload(f, "img", ag_main.slug))
    p2["gallery_urls"] = join_pipe(g_existing)

    v_existing = split_pipe(p2.get("video_urls",""))
    for f in req.files.getlist("videos"):
        if not f or not f.filename:
            continue
        if len(v_existing) >= MAX_VIDEOS:
            break
        v_existing.append(save_upload(f, "video", ag_main.slug))
    p2["video_urls"] = join_pipe(v_existing)

    pdfs = parse_pdfs(p2.get("pdf1_url",""))
    for i in range(1, MAX_PDFS + 1):
        key = f"pdf{i}"
        if req.files.get(key) and req.files.get(key).filename:
            url = save_upload(req.files[key], "pdf", ag_main.slug)
            name = req.files[key].filename
            pdfs.append({"name": name, "url": url})
    pdfs = pdfs[:MAX_PDFS]
    p2["pdf1_url"] = build_pdfs_raw(pdfs)

    return p2

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
