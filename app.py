import os
import re
import json
import uuid
from types import SimpleNamespace
from datetime import datetime
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Flask, request, render_template, redirect, url_for, session, abort,
    send_from_directory, flash, make_response
)
from werkzeug.utils import secure_filename

from sqlalchemy import (
    create_engine, Column, Integer, String, Text
)
from sqlalchemy.orm import sessionmaker, declarative_base

# QR (dipendenze comuni: qrcode + pillow)
try:
    import qrcode
except Exception:
    qrcode = None


# ---------------------------
# Config
# ---------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
UPLOAD_IMG = os.path.join(UPLOAD_DIR, "img")
UPLOAD_VID = os.path.join(UPLOAD_DIR, "video")
UPLOAD_PDF = os.path.join(UPLOAD_DIR, "pdf")

for d in [UPLOAD_DIR, UPLOAD_IMG, UPLOAD_VID, UPLOAD_PDF]:
    os.makedirs(d, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(APP_DIR,'data.db')}")
SECRET_KEY = os.environ.get("SECRET_KEY", "pay4you-secret-CHANGE-ME")
BASE_URL_ENV = os.environ.get("BASE_URL", "").strip()  # es: https://pay4you-cards-fire.onrender.com


# ---------------------------
# Flask
# ---------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024  # 250MB (video)

# ---------------------------
# DB (SQLAlchemy)
# ---------------------------
Base = declarative_base()
engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password = Column(String(120), nullable=False)
    role = Column(String(20), default="client")  # admin/client


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True)
    slug = Column(String(120), unique=True, nullable=False)

    # pubblici
    name = Column(String(200), default="")
    company = Column(String(200), default="")
    role = Column(String(200), default="")
    bio = Column(Text, default="")

    # contatti
    phone_mobile = Column(String(80), default="")
    phone_mobile2 = Column(String(80), default="")
    phone_office = Column(String(80), default="")
    whatsapp = Column(String(240), default="")
    emails = Column(Text, default="")     # comma separated
    websites = Column(Text, default="")   # comma separated
    pec = Column(String(240), default="")
    addresses = Column(Text, default="")  # multiline

    # dati fiscali
    piva = Column(String(80), default="")
    sdi = Column(String(80), default="")

    # social
    facebook = Column(String(300), default="")
    instagram = Column(String(300), default="")
    linkedin = Column(String(300), default="")
    tiktok = Column(String(300), default="")
    telegram = Column(String(300), default="")
    youtube = Column(String(300), default="")
    spotify = Column(String(300), default="")

    # immagini principali
    photo_url = Column(String(400), default="")
    logo_url = Column(String(400), default="")
    back_media_mode = Column(String(40), default="company")  # company/personal
    back_media_url = Column(String(400), default="")

    # crop/zoom
    photo_pos_x = Column(Integer, default=50)
    photo_pos_y = Column(Integer, default=35)
    photo_zoom = Column(String(30), default="1.0")

    # effetti
    orbit_spin = Column(Integer, default=0)
    avatar_spin = Column(Integer, default=0)
    logo_spin = Column(Integer, default=0)
    allow_flip = Column(Integer, default=0)

    # media lists (pipe separated)
    gallery_urls = Column(Text, default="")  # url|url|url
    video_urls = Column(Text, default="")    # url|url|url

    # pdf list (pipe separated). ogni item può essere "nomefile.pdf||/uploads/pdf/xxx.pdf"
    pdf1_url = Column(Text, default="")

    # profilo 2
    p2_enabled = Column(Integer, default=0)
    profiles_json = Column(Text, default="")  # lista di profili, includendo p2

    # traduzioni opzionali
    i18n_json = Column(Text, default="")      # dict: { "en": {...}, "fr": {...} }


Base.metadata.create_all(engine)


# ---------------------------
# Helpers
# ---------------------------
def get_base_url() -> str:
    if BASE_URL_ENV:
        return BASE_URL_ENV.rstrip("/")
    # fallback dinamico
    return request.url_root.strip().rstrip("/")


def is_admin() -> bool:
    return session.get("role") == "admin"


def current_client_slug() -> str:
    return session.get("username", "")


def login_required(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrap


def normalize_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"\-+", "-", s).strip("-")
    return s


def safe_float_str(x, default="1.0"):
    try:
        v = float(x)
        if v < 1.0:
            v = 1.0
        if v > 2.6:
            v = 2.6
        return f"{v:.2f}"
    except Exception:
        return default


def split_csv(s: str):
    if not s:
        return []
    arr = [x.strip() for x in s.split(",")]
    return [x for x in arr if x]


def split_pipe(s: str):
    if not s:
        return []
    arr = [x.strip() for x in s.split("|")]
    return [x for x in arr if x]


def _remove_item_from_pipe_list(s: str, idx: int) -> str:
    items = split_pipe(s or "")
    if idx < 0 or idx >= len(items):
        return s or ""
    items.pop(idx)
    return "|".join(items)


def _remove_pdf_from_list(s: str, idx: int) -> str:
    items = split_pipe(s or "")
    if idx < 0 or idx >= len(items):
        return s or ""
    items.pop(idx)
    return "|".join(items)


def parse_profiles_json(raw: str):
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def select_profile(profiles, key: str):
    for p in profiles or []:
        if isinstance(p, dict) and p.get("key") == key:
            return p
    return None


def upsert_profile(profiles, key: str, payload: dict):
    out = []
    found = False
    for p in profiles or []:
        if isinstance(p, dict) and p.get("key") == key:
            out.append(payload)
            found = True
        else:
            out.append(p)
    if not found:
        out.append(payload)
    return out


def parse_i18n(raw: str):
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_upload(file_storage, folder: str, prefix: str):
    """
    Ritorna url pubblico tipo /uploads/img/xxx.jpg
    """
    if not file_storage or not file_storage.filename:
        return ""

    fname = secure_filename(file_storage.filename)
    ext = os.path.splitext(fname)[1].lower()
    uid = uuid.uuid4().hex[:12]
    out_name = f"{prefix}_{uid}{ext}"

    if folder == "img":
        out_path = os.path.join(UPLOAD_IMG, out_name)
        url = f"/uploads/img/{out_name}"
    elif folder == "video":
        out_path = os.path.join(UPLOAD_VID, out_name)
        url = f"/uploads/video/{out_name}"
    else:
        out_path = os.path.join(UPLOAD_PDF, out_name)
        url = f"/uploads/pdf/{out_name}"

    file_storage.save(out_path)
    return url


def pdf_item_label_and_url(item: str):
    """
    item può essere:
      - "nome.pdf||/uploads/pdf/xxx.pdf"
      - "/uploads/pdf/xxx.pdf"
    """
    if "||" in item:
        parts = item.split("||", 1)
        return parts[0].strip(), parts[1].strip()
    # fallback: prova ricavare nome da path
    path = item.strip()
    name = os.path.basename(path) if path else "Documento"
    return name, path


def to_agent_namespace(agent: Agent, override: dict = None):
    """
    Converte Agent SQLAlchemy in oggetto con attributi (per Jinja).
    override può sostituire campi (utile per P2).
    """
    d = {c.name: getattr(agent, c.name) for c in agent.__table__.columns}
    if override:
        d.update(override)
    return SimpleNamespace(**d)


def build_whatsapp_link(raw: str, name: str = ""):
    if not raw:
        return ""
    s = raw.strip()
    # se è già link wa.me o whatsapp
    if s.startswith("http://") or s.startswith("https://"):
        return s
    # se è numero -> wa.me
    num = re.sub(r"[^\d+]", "", s)
    if not num:
        return ""
    if not num.startswith("+"):
        # se manca + prova IT
        num = "+39" + num
    return f"https://wa.me/{num.replace('+','')}"


def ensure_url_scheme(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "https://" + u


# ---------------------------
# Auth
# ---------------------------
@app.get("/login")
def login():
    return render_template("login.html")


@app.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()

    db = SessionLocal()
    u = db.query(User).filter_by(username=username).first()
    db.close()

    if not u or u.password != password:
        flash("Credenziali non valide.", "error")
        return redirect(url_for("login"))

    session["username"] = u.username
    session["role"] = u.role

    return redirect(url_for("dashboard"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------
# Upload public serving
# ---------------------------
@app.get("/uploads/<path:filename>")
def uploads(filename):
    # filename include folder
    base = os.path.abspath(UPLOAD_DIR)
    full = os.path.abspath(os.path.join(UPLOAD_DIR, filename))
    if not full.startswith(base):
        abort(404)
    folder = os.path.dirname(full)
    name = os.path.basename(full)
    if not os.path.exists(full):
        abort(404)
    return send_from_directory(folder, name)


# ---------------------------
# Dashboard
# ---------------------------
@app.get("/dashboard")
@login_required
def dashboard():
    db = SessionLocal()

    if is_admin():
        agents = db.query(Agent).order_by(Agent.id.desc()).all()
        db.close()
        return render_template("admin_list.html", is_admin=True, agents=agents, agent=None)

    # client
    slug = current_client_slug()
    ag = db.query(Agent).filter_by(slug=slug).first()
    agents = [ag] if ag else []
    db.close()
    return render_template("admin_list.html", is_admin=False, agents=agents, agent=ag)


# ---------------------------
# Credenziali (ADMIN + CLIENT)
# ---------------------------
@app.get("/admin/<slug>/credentials")
@login_required
def admin_credentials_html(slug):
    if not is_admin():
        abort(403)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    u = db.query(User).filter_by(username=slug).first()
    db.close()
    if not ag or not u:
        abort(404)

    base = get_base_url()
    login_url = f"{base}/login"
    card_url = f"{base}/{slug}"
    return render_template(
        "credentials.html",
        username=u.username,
        password=u.password,
        login_url=login_url,
        card_url=card_url,
        p2_enabled=int(getattr(ag, "p2_enabled", 0) or 0),
    )


@app.get("/me/credentials")
@login_required
def me_credentials():
    if is_admin():
        return redirect(url_for("dashboard"))
    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    u = db.query(User).filter_by(username=slug).first()
    db.close()
    if not ag or not u:
        abort(404)

    base = get_base_url()
    login_url = f"{base}/login"
    card_url = f"{base}/{slug}"
    return render_template(
        "credentials.html",
        username=u.username,
        password=u.password,
        login_url=login_url,
        card_url=card_url,
        p2_enabled=int(getattr(ag, "p2_enabled", 0) or 0),
    )


# ---------------------------
# Create / Edit agents (ADMIN)
# ---------------------------
@app.get("/admin/new")
@login_required
def new_agent():
    if not is_admin():
        abort(403)
    # i18n_data richiesto dal template
    return render_template("agent_form.html", agent=None, editing_profile2=False, i18n_data={})


@app.post("/admin/new")
@login_required
def new_agent_post():
    if not is_admin():
        abort(403)

    slug = normalize_slug(request.form.get("slug") or "")
    name = (request.form.get("name") or "").strip()

    if not slug or not name:
        flash("Slug e Nome sono obbligatori.", "error")
        return redirect(url_for("new_agent"))

    db = SessionLocal()
    exists = db.query(Agent).filter_by(slug=slug).first()
    if exists:
        db.close()
        flash("Slug già esistente.", "error")
        return redirect(url_for("new_agent"))

    # crea user con password random semplice
    pwd = uuid.uuid4().hex[:8]
    u = User(username=slug, password=pwd, role="client")

    ag = Agent(slug=slug, name=name)
    db.add(u)
    db.add(ag)
    db.commit()
    db.close()

    flash("Card creata. Ricorda di copiare le credenziali.", "ok")
    return redirect(url_for("edit_agent", slug=slug))


@app.get("/admin/<slug>/edit")
@login_required
def edit_agent(slug):
    if not is_admin():
        abort(403)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    i18n_data = parse_i18n(ag.i18n_json if ag else "")
    db.close()
    if not ag:
        abort(404)
    return render_template("agent_form.html", agent=ag, editing_profile2=False, i18n_data=i18n_data)


@app.post("/admin/<slug>/edit")
@login_required
def edit_agent_post(slug):
    if not is_admin():
        abort(403)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    save_agent_from_form(db, ag, editing_profile2=False)
    db.commit()
    db.close()
    flash("Profilo 1 salvato.", "ok")
    return redirect(url_for("edit_agent", slug=slug))


@app.get("/admin/<slug>/profile2")
@login_required
def admin_profile2(slug):
    if not is_admin():
        abort(403)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    profiles = parse_profiles_json(ag.profiles_json or "")
    p2 = select_profile(profiles, "p2") or {}

    # se P2 non attivo, mostra uguale la pagina (modificabile comunque)
    # override campi per compilare form con valori di P2
    override = p2.copy() if isinstance(p2, dict) else {}
    override.pop("key", None)

    # i18n solo per admin, lo teniamo uguale (card pubblica)
    i18n_data = parse_i18n(ag.i18n_json or "")

    db.close()

    agent_ns = to_agent_namespace(ag, override=override)
    return render_template("agent_form.html", agent=agent_ns, editing_profile2=True, i18n_data=i18n_data)


@app.post("/admin/<slug>/profile2")
@login_required
def admin_profile2_post(slug):
    if not is_admin():
        abort(403)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    save_agent_from_form(db, ag, editing_profile2=True)
    db.commit()
    db.close()
    flash("Profilo 2 salvato.", "ok")
    return redirect(url_for("admin_profile2", slug=slug))


@app.post("/admin/<slug>/delete")
@login_required
def delete_agent(slug):
    if not is_admin():
        abort(403)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    u = db.query(User).filter_by(username=slug).first()
    if ag:
        db.delete(ag)
    if u:
        db.delete(u)
    db.commit()
    db.close()
    flash("Card eliminata.", "ok")
    return redirect(url_for("dashboard"))


@app.post("/admin/<slug>/p2/activate")
@login_required
def admin_activate_p2(slug):
    if not is_admin():
        abort(403)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)
    ag.p2_enabled = 1
    db.commit()
    db.close()
    return redirect(url_for("dashboard"))


@app.post("/admin/<slug>/p2/deactivate")
@login_required
def admin_deactivate_p2(slug):
    if not is_admin():
        abort(403)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)
    ag.p2_enabled = 0
    db.commit()
    db.close()
    return redirect(url_for("dashboard"))


# ---------------------------
# Client self edit
# ---------------------------
@app.get("/me/edit")
@login_required
def me_edit():
    if is_admin():
        return redirect(url_for("dashboard"))

    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)

    return render_template("agent_form.html", agent=ag, editing_profile2=False, i18n_data={})


@app.post("/me/edit")
@login_required
def me_edit_post():
    if is_admin():
        abort(403)
    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    save_agent_from_form(db, ag, editing_profile2=False)
    db.commit()
    db.close()
    flash("Salvato.", "ok")
    return redirect(url_for("me_edit"))


@app.get("/me/profile2")
@login_required
def me_profile2():
    if is_admin():
        return redirect(url_for("dashboard"))

    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    profiles = parse_profiles_json(ag.profiles_json or "")
    p2 = select_profile(profiles, "p2") or {}
    override = p2.copy() if isinstance(p2, dict) else {}
    override.pop("key", None)

    db.close()

    agent_ns = to_agent_namespace(ag, override=override)
    return render_template("agent_form.html", agent=agent_ns, editing_profile2=True, i18n_data={})


@app.post("/me/profile2")
@login_required
def me_profile2_post():
    if is_admin():
        abort(403)

    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    save_agent_from_form(db, ag, editing_profile2=True)
    db.commit()
    db.close()
    flash("Profilo 2 salvato.", "ok")
    return redirect(url_for("me_profile2"))


@app.post("/me/p2/activate")
@login_required
def me_activate_p2():
    if is_admin():
        abort(403)
    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)
    ag.p2_enabled = 1
    db.commit()
    db.close()
    return redirect(url_for("dashboard"))


@app.post("/me/p2/deactivate")
@login_required
def me_deactivate_p2():
    if is_admin():
        abort(403)
    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)
    ag.p2_enabled = 0
    db.commit()
    db.close()
    return redirect(url_for("dashboard"))


# ---------------------------
# Delete singolo media (ADMIN + CLIENT)
# ---------------------------
@app.post("/admin/<slug>/media/delete")
@login_required
def admin_media_delete(slug):
    if not is_admin():
        abort(403)

    kind = (request.form.get("kind") or "").strip().lower()
    idx = int(request.form.get("idx") or "0")
    profile = (request.form.get("profile") or "").strip().lower()  # "" or "p2"

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    delete_media_for_agent(ag, kind, idx, profile=profile)

    db.commit()
    db.close()
    flash("Eliminato.", "ok")
    return redirect(url_for("dashboard"))


@app.post("/me/media/delete")
@login_required
def me_media_delete():
    if is_admin():
        abort(403)

    slug = current_client_slug()
    kind = (request.form.get("kind") or "").strip().lower()
    idx = int(request.form.get("idx") or "0")
    profile = (request.form.get("profile") or "").strip().lower()  # "" or "p2"

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    delete_media_for_agent(ag, kind, idx, profile=profile)

    db.commit()
    db.close()
    flash("Eliminato.", "ok")
    # torna al form giusto
    if profile == "p2":
        return redirect(url_for("me_profile2"))
    return redirect(url_for("me_edit"))


def delete_media_for_agent(ag: Agent, kind: str, idx: int, profile: str = ""):
    """
    kind: gallery | video | pdf
    profile: "" (P1) or "p2"
    """
    kind = kind or ""
    if kind not in ("gallery", "video", "pdf"):
        return

    if profile == "p2":
        profiles = parse_profiles_json(ag.profiles_json or "")
        p2 = select_profile(profiles, "p2") or {"key": "p2"}

        if kind == "gallery":
            p2["gallery_urls"] = _remove_item_from_pipe_list(p2.get("gallery_urls", "") or "", idx)
        elif kind == "video":
            p2["video_urls"] = _remove_item_from_pipe_list(p2.get("video_urls", "") or "", idx)
        elif kind == "pdf":
            p2["pdf1_url"] = _remove_pdf_from_list(p2.get("pdf1_url", "") or "", idx)

        profiles = upsert_profile(profiles, "p2", p2)
        ag.profiles_json = json.dumps(profiles, ensure_ascii=False)
        return

    # P1
    if kind == "gallery":
        ag.gallery_urls = _remove_item_from_pipe_list(ag.gallery_urls or "", idx)
    elif kind == "video":
        ag.video_urls = _remove_item_from_pipe_list(ag.video_urls or "", idx)
    elif kind == "pdf":
        ag.pdf1_url = _remove_pdf_from_list(ag.pdf1_url or "", idx)


# ---------------------------
# Public card + QR + VCF
# ---------------------------
@app.get("/<slug>")
def public_card(slug):
    slug = normalize_slug(slug)
    if not slug:
        abort(404)

    p_key = (request.args.get("p") or "").strip().lower()  # "p2" o ""
    lang = (request.args.get("lang") or "it").strip().lower()

    db = SessionLocal()
    ag_db = db.query(Agent).filter_by(slug=slug).first()
    db.close()

    if not ag_db:
        # pagina più bella "contenuto non disponibile"
        return render_template("not_found_card.html", back=url_for("dashboard")), 404

    base_url = get_base_url()

    # P2: override da profiles_json
    p2_enabled = int(getattr(ag_db, "p2_enabled", 0) or 0)
    profiles = parse_profiles_json(ag_db.profiles_json or "")
    p2 = select_profile(profiles, "p2") or {}

    override = {}
    if p_key == "p2" and p2_enabled == 1 and isinstance(p2, dict):
        override = p2.copy()
        override.pop("key", None)

    ag = to_agent_namespace(ag_db, override=override)

    # contatti
    mobiles = []
    if ag.phone_mobile:
        mobiles.append(ag.phone_mobile)
    if getattr(ag, "phone_mobile2", ""):
        mobiles.append(ag.phone_mobile2)

    emails = split_csv(ag.emails or "")
    websites = [ensure_url_scheme(x) for x in split_csv(ag.websites or "")]
    websites = [x for x in websites if x]

    pec_email = ag.pec or ""
    office_value = ag.phone_office or ""

    # whatsapp
    wa_link = build_whatsapp_link(ag.whatsapp or "", ag.name or "")

    # addresses -> maps
    addresses = []
    if ag.addresses:
        for line in [x.strip() for x in ag.addresses.splitlines() if x.strip()]:
            q = line.replace(" ", "+")
            addresses.append({"text": line, "maps": f"https://www.google.com/maps/search/?api=1&query={q}"})

    # gallery/videos/pdf
    gallery = split_pipe(getattr(ag, "gallery_urls", "") or "")
    videos = split_pipe(getattr(ag, "video_urls", "") or "")

    pdfs = []
    raw_pdfs = split_pipe(getattr(ag, "pdf1_url", "") or "")
    for item in raw_pdfs:
        name, url = pdf_item_label_and_url(item)
        if url:
            pdfs.append({"name": name, "url": url})

    # traduzioni (solo testo base, non tocchiamo layout)
    i18n = parse_i18n(ag_db.i18n_json or "")
    # funzione di traduzione minima per label UI (solo italiano)
    def t_func(key):
        it = {
            "profile_1": "Profilo 1",
            "profile_2": "Profilo 2",
            "actions": "Azioni",
            "save_contact": "Salva contatto",
            "whatsapp": "WhatsApp",
            "scan_qr": "QR Code",
            "contacts": "Contatti",
            "mobile_phone": "Cellulare",
            "office_phone": "Ufficio",
            "open_website": "Sito",
            "data": "Dati",
            "vat": "Partita IVA",
            "sdi": "SDI",
            "open_maps": "Apri su Maps",
            "theme": "Tema",
            "theme_auto": "Auto",
            "theme_light": "Chiaro",
            "theme_dark": "Scuro",
            "gallery": "Foto",
            "videos": "Video",
            "documents": "Documenti",
            "close": "Chiudi",
        }
        return it.get(key, key)

    qr_url = f"/{slug}/qr.png" + (("?p=p2" if p_key == "p2" else ""))
    return render_template(
        "card.html",
        ag=ag,
        lang=lang,
        base_url=base_url,
        p_key=("p2" if p_key == "p2" else ""),
        p2_enabled=(p2_enabled == 1),
        t_func=t_func,
        wa_link=wa_link,
        mobiles=mobiles,
        emails=emails,
        websites=websites,
        pec_email=pec_email,
        office_value=office_value,
        addresses=addresses,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        qr_url=qr_url
    )


@app.get("/<slug>/qr.png")
def qr_png(slug):
    slug = normalize_slug(slug)
    if not slug:
        abort(404)

    p_key = (request.args.get("p") or "").strip().lower()
    url = f"{get_base_url()}/{slug}" + (("?p=p2" if p_key == "p2" else ""))

    if qrcode is None:
        # fallback: se manca lib, ritorna 404 (ma idealmente qrcode c'è)
        abort(404)

    img = qrcode.make(url)
    resp = make_response()
    resp.headers["Content-Type"] = "image/png"
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    resp.data = buf.getvalue()
    return resp


@app.get("/<slug>.vcf")
def vcf(slug):
    slug = normalize_slug(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)

    # genera vCard minimale
    name = ag.name or slug
    org = ag.company or ""
    role = ag.role or ""
    tel = ag.phone_mobile or ""
    email = split_csv(ag.emails or "")
    email1 = email[0] if email else ""
    url = ""
    webs = split_csv(ag.websites or "")
    if webs:
        url = ensure_url_scheme(webs[0])

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{name};;;;",
        f"FN:{name}",
    ]
    if org:
        lines.append(f"ORG:{org}")
    if role:
        lines.append(f"TITLE:{role}")
    if tel:
        lines.append(f"TEL;TYPE=CELL:{tel}")
    if email1:
        lines.append(f"EMAIL;TYPE=INTERNET:{email1}")
    if url:
        lines.append(f"URL:{url}")
    lines.append("END:VCARD")

    data = "\n".join(lines)
    resp = make_response(data)
    resp.headers["Content-Type"] = "text/vcard; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{slug}.vcf"'
    return resp


# ---------------------------
# Webview + Share (cornice)
# ---------------------------
@app.get("/webview")
def webview():
    url = (request.args.get("u") or "").strip()
    back = (request.args.get("back") or "").strip()
    if not url:
        return render_template("404.html"), 404
    return render_template("webview.html", url=url, back=back)


@app.get("/share")
def share():
    back = (request.args.get("back") or "").strip()
    text = (request.args.get("text") or "")
    return render_template("share.html", back=back, text=text)


# ---------------------------
# Save from form (P1/P2)
# ---------------------------
def save_agent_from_form(db, ag: Agent, editing_profile2: bool):
    """
    Se editing_profile2=True, salva dentro ag.profiles_json (chiave p2).
    Se False, salva direttamente campi Agent.
    """
    form = request.form

    def g(k, default=""):
        return (form.get(k) or default).strip()

    # fields comuni
    payload = {
        "name": g("name"),
        "company": g("company"),
        "role": g("role"),
        "bio": g("bio"),

        "phone_mobile": g("phone_mobile"),
        "phone_mobile2": g("phone_mobile2"),
        "phone_office": g("phone_office"),
        "whatsapp": g("whatsapp"),
        "emails": g("emails"),
        "websites": g("websites"),
        "pec": g("pec"),
        "addresses": g("addresses"),

        "piva": g("piva"),
        "sdi": g("sdi"),

        "facebook": g("facebook"),
        "instagram": g("instagram"),
        "linkedin": g("linkedin"),
        "tiktok": g("tiktok"),
        "telegram": g("telegram"),
        "youtube": g("youtube"),
        "spotify": g("spotify"),

        "back_media_mode": g("back_media_mode") or "company",
        "photo_pos_x": int(g("photo_pos_x", "50") or "50"),
        "photo_pos_y": int(g("photo_pos_y", "35") or "35"),
        "photo_zoom": safe_float_str(g("photo_zoom", "1.0")),
        "orbit_spin": 1 if form.get("orbit_spin") else 0,
        "avatar_spin": 1 if form.get("avatar_spin") else 0,
        "logo_spin": 1 if form.get("logo_spin") else 0,
        "allow_flip": 1 if form.get("allow_flip") else 0,
    }

    # upload singoli (photo/logo/back)
    photo_fs = request.files.get("photo")
    logo_fs = request.files.get("logo")
    back_fs = request.files.get("back_media")

    new_photo = save_upload(photo_fs, "img", "photo") if photo_fs and photo_fs.filename else ""
    new_logo = save_upload(logo_fs, "img", "logo") if logo_fs and logo_fs.filename else ""
    new_back = save_upload(back_fs, "img", "back") if back_fs and back_fs.filename else ""

    # media multipli
    gallery_files = request.files.getlist("gallery")
    video_files = request.files.getlist("videos")

    new_gallery_urls = []
    if gallery_files:
        for f in gallery_files:
            if f and f.filename:
                new_gallery_urls.append(save_upload(f, "img", "gal"))

    new_video_urls = []
    if video_files:
        for f in video_files:
            if f and f.filename:
                new_video_urls.append(save_upload(f, "video", "vid"))

    # PDF (12 slot) -> append/sovrascrive
    new_pdfs = []
    for i in range(1, 13):
        pf = request.files.get(f"pdf{i}")
        if pf and pf.filename:
            url = save_upload(pf, "pdf", "pdf")
            label = secure_filename(pf.filename) or f"pdf{i}.pdf"
            new_pdfs.append(f"{label}||{url}")

    # traduzioni (solo admin)
    if is_admin():
        i18n = parse_i18n(ag.i18n_json or "")
        for L in ["en", "fr", "es", "de"]:
            d = i18n.get(L, {})
            d["name"] = g(f"name_{L}")
            d["company"] = g(f"company_{L}")
            d["role"] = g(f"role_{L}")
            d["bio"] = g(f"bio_{L}")
            d["addresses"] = g(f"addresses_{L}")
            i18n[L] = d
        ag.i18n_json = json.dumps(i18n, ensure_ascii=False)

    # salva su P2 o P1
    if editing_profile2:
        profiles = parse_profiles_json(ag.profiles_json or "")
        p2 = select_profile(profiles, "p2") or {"key": "p2"}

        # aggiorna payload base
        for k, v in payload.items():
            p2[k] = v

        # immagini P2: se non carichi, lascia quelle esistenti del P2 (non ereditare P1)
        if new_photo:
            p2["photo_url"] = new_photo
        else:
            p2["photo_url"] = p2.get("photo_url", "") or ""

        if new_logo:
            p2["logo_url"] = new_logo
        else:
            p2["logo_url"] = p2.get("logo_url", "") or ""

        if new_back:
            p2["back_media_url"] = new_back
        else:
            p2["back_media_url"] = p2.get("back_media_url", "") or ""

        # gallery/videos: se carichi nuovi, sovrascrivi la lista del P2
        if new_gallery_urls:
            p2["gallery_urls"] = "|".join(new_gallery_urls)
        else:
            p2["gallery_urls"] = p2.get("gallery_urls", "") or ""

        if new_video_urls:
            p2["video_urls"] = "|".join(new_video_urls)
        else:
            p2["video_urls"] = p2.get("video_urls", "") or ""

        # pdf: append ai pdf esistenti P2
        if new_pdfs:
            existing = split_pipe(p2.get("pdf1_url", "") or "")
            merged = existing + new_pdfs
            p2["pdf1_url"] = "|".join(merged)
        else:
            p2["pdf1_url"] = p2.get("pdf1_url", "") or ""

        p2["key"] = "p2"
        profiles = upsert_profile(profiles, "p2", p2)
        ag.profiles_json = json.dumps(profiles, ensure_ascii=False)
        return

    # --- P1 ---
    for k, v in payload.items():
        setattr(ag, k, v)

    if new_photo:
        ag.photo_url = new_photo
    if new_logo:
        ag.logo_url = new_logo
    if new_back:
        ag.back_media_url = new_back

    if new_gallery_urls:
        ag.gallery_urls = "|".join(new_gallery_urls)

    if new_video_urls:
        ag.video_urls = "|".join(new_video_urls)

    if new_pdfs:
        existing = split_pipe(ag.pdf1_url or "")
        merged = existing + new_pdfs
        ag.pdf1_url = "|".join(merged)


# ---------------------------
# Error handlers
# ---------------------------
@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        return "404 - Not Found", 404


@app.errorhandler(500)
def server_error(e):
    try:
        return render_template("500.html"), 500
    except Exception:
        return "500 - Server Error", 500


# ---------------------------
# First run: ensure admin exists
# ---------------------------
def ensure_admin():
    admin_user = os.environ.get("ADMIN_USER", "giuseppe")
    admin_pass = os.environ.get("ADMIN_PASS", "giuseppe123")
    db = SessionLocal()
    u = db.query(User).filter_by(username=admin_user).first()
    if not u:
        db.add(User(username=admin_user, password=admin_pass, role="admin"))
        db.commit()
    db.close()


ensure_admin()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
