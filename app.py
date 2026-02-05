import os
import re
import uuid
import json
from io import BytesIO
from types import SimpleNamespace
import urllib.parse

from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, session, abort, Response,
    send_from_directory, flash
)

from sqlalchemy import create_engine, Column, Integer, String, Text, text as sa_text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
import qrcode

load_dotenv()

# ===== ENV / CONFIG =====
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")

# Upload persistenti (Render Disk su /var/data/uploads)
PERSIST_UPLOADS_DIR = os.getenv("PERSIST_UPLOADS_DIR", "/var/data/uploads")

# Limiti upload
MAX_GALLERY_IMAGES = 30
MAX_VIDEOS = 10
MAX_IMAGE_MB = 8
MAX_VIDEO_MB = 60
MAX_PDF_MB = 15

SUPPORTED_LANGS = ("it", "en", "fr", "es", "de")

# ===== UI I18N (etichette fisse) =====
I18N = {
    "it": {
        "save_contact": "Salva contatto",
        "scan_qr": "QR Code",
        "contacts": "Contatti",
        "social": "Social",
        "documents": "Documenti",
        "gallery": "Foto",
        "videos": "Video",
        "actions": "Azioni",
        "data": "Dati",
        "vat": "P.IVA",
        "sdi": "SDI",
        "open_maps": "Apri Maps",
        "open_website": "Apri sito",
        "mobile_phone": "Cellulare",
        "office_phone": "Ufficio",
        "whatsapp": "WhatsApp",
        "close": "Chiudi",
        "theme": "Tema",
        "theme_auto": "Auto",
        "theme_light": "Chiaro",
        "theme_dark": "Scuro",
    },
    "en": {
        "save_contact": "Save contact",
        "scan_qr": "QR Code",
        "contacts": "Contacts",
        "social": "Social",
        "documents": "Documents",
        "gallery": "Photos",
        "videos": "Videos",
        "actions": "Actions",
        "data": "Company data",
        "vat": "VAT",
        "sdi": "SDI",
        "open_maps": "Open Maps",
        "open_website": "Open website",
        "mobile_phone": "Mobile",
        "office_phone": "Office",
        "whatsapp": "WhatsApp",
        "close": "Close",
        "theme": "Theme",
        "theme_auto": "Auto",
        "theme_light": "Light",
        "theme_dark": "Dark",
    },
    "fr": {
        "save_contact": "Enregistrer le contact",
        "scan_qr": "QR Code",
        "contacts": "Contacts",
        "social": "Réseaux sociaux",
        "documents": "Documents",
        "gallery": "Photos",
        "videos": "Vidéos",
        "actions": "Actions",
        "data": "Données",
        "vat": "TVA",
        "sdi": "SDI",
        "open_maps": "Ouvrir Maps",
        "open_website": "Ouvrir le site",
        "mobile_phone": "Mobile",
        "office_phone": "Bureau",
        "whatsapp": "WhatsApp",
        "close": "Fermer",
        "theme": "Thème",
        "theme_auto": "Auto",
        "theme_light": "Clair",
        "theme_dark": "Sombre",
    },
    "es": {
        "save_contact": "Guardar contacto",
        "scan_qr": "Código QR",
        "contacts": "Contactos",
        "social": "Redes",
        "documents": "Documentos",
        "gallery": "Fotos",
        "videos": "Vídeos",
        "actions": "Acciones",
        "data": "Datos",
        "vat": "IVA",
        "sdi": "SDI",
        "open_maps": "Abrir Maps",
        "open_website": "Abrir sitio",
        "mobile_phone": "Móvil",
        "office_phone": "Oficina",
        "whatsapp": "WhatsApp",
        "close": "Cerrar",
        "theme": "Tema",
        "theme_auto": "Auto",
        "theme_light": "Claro",
        "theme_dark": "Oscuro",
    },
    "de": {
        "save_contact": "Kontakt speichern",
        "scan_qr": "QR Code",
        "contacts": "Kontakte",
        "social": "Social",
        "documents": "Dokumente",
        "gallery": "Fotos",
        "videos": "Videos",
        "actions": "Aktionen",
        "data": "Daten",
        "vat": "USt-IdNr.",
        "sdi": "SDI",
        "open_maps": "Maps öffnen",
        "open_website": "Website öffnen",
        "mobile_phone": "Mobil",
        "office_phone": "Büro",
        "whatsapp": "WhatsApp",
        "close": "Schließen",
        "theme": "Theme",
        "theme_auto": "Auto",
        "theme_light": "Hell",
        "theme_dark": "Dunkel",
    },
}

def t(lang: str, key: str) -> str:
    lang = (lang or "it").lower()
    if lang not in SUPPORTED_LANGS:
        lang = "it"
    return I18N.get(lang, I18N["it"]).get(key, key)

def mb_to_bytes(mb: int) -> int:
    return int(mb) * 1024 * 1024

def form_checkbox_int(name: str) -> int:
    return 1 if request.form.get(name) in ("1", "on", "true", "True") else 0

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET", "dev_secret")
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024

DB_URL = "sqlite:////var/data/data.db"
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ===== MODELS =====
class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)

    # Profilo 1
    name = Column(String, nullable=False)
    company = Column(String, nullable=True)
    role = Column(String, nullable=True)
    bio = Column(Text, nullable=True)

    phone_mobile = Column(String, nullable=True)
    phone_mobile2 = Column(String, nullable=True)
    phone_office = Column(String, nullable=True)

    emails = Column(String, nullable=True)
    websites = Column(String, nullable=True)

    facebook = Column(String, nullable=True)
    instagram = Column(String, nullable=True)
    linkedin = Column(String, nullable=True)
    tiktok = Column(String, nullable=True)
    telegram = Column(String, nullable=True)
    whatsapp = Column(String, nullable=True)

    pec = Column(String, nullable=True)
    piva = Column(String, nullable=True)
    sdi = Column(String, nullable=True)
    addresses = Column(Text, nullable=True)

    photo_url = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    extra_logo_url = Column(String, nullable=True)

    gallery_urls = Column(Text, nullable=True)
    video_urls = Column(Text, nullable=True)
    pdf1_url = Column(Text, nullable=True)

    # Multi-utente
    p2_enabled = Column(Integer, nullable=True)     # 0/1
    profiles_json = Column(Text, nullable=True)     # salva profilo 2

    # Traduzioni profilo 1
    i18n_json = Column(Text, nullable=True)

    # Effetti grafici P1 (P2 salva in profiles_json)
    orbit_spin = Column(Integer, nullable=True)     # 0/1
    avatar_spin = Column(Integer, nullable=True)    # 0/1
    logo_spin = Column(Integer, nullable=True)      # 0/1
    allow_flip = Column(Integer, nullable=True)     # 0/1

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="client")  # admin|client
    agent_slug = Column(String, nullable=True)

Base.metadata.create_all(engine)

# ===== micro-migrazioni =====
def ensure_sqlite_column(table: str, column: str, coltype: str):
    with engine.connect() as conn:
        rows = conn.execute(sa_text(f"PRAGMA table_info({table})")).fetchall()
        existing = {r[1] for r in rows}
        if column not in existing:
            conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            conn.commit()

ensure_sqlite_column("agents", "logo_url", "TEXT")
ensure_sqlite_column("agents", "extra_logo_url", "TEXT")
ensure_sqlite_column("agents", "phone_office", "TEXT")
ensure_sqlite_column("agents", "phone_mobile2", "TEXT")
ensure_sqlite_column("agents", "p2_enabled", "INTEGER")
ensure_sqlite_column("agents", "profiles_json", "TEXT")
ensure_sqlite_column("agents", "i18n_json", "TEXT")

ensure_sqlite_column("agents", "orbit_spin", "INTEGER")
ensure_sqlite_column("agents", "avatar_spin", "INTEGER")
ensure_sqlite_column("agents", "logo_spin", "INTEGER")
ensure_sqlite_column("agents", "allow_flip", "INTEGER")

# ===== HELPERS =====
def is_logged_in() -> bool:
    return bool(session.get("username"))

def is_admin() -> bool:
    return session.get("role") == "admin"

def current_client_slug():
    return session.get("agent_slug")

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_logged_in() or not is_admin():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def generate_password(length=10):
    return uuid.uuid4().hex[:length]

def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("+", " ")
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s

def clean_str(v):
    if v is None:
        return None
    v = str(v).strip()
    if not v or v.lower() == "none":
        return None
    return v

def ensure_admin_user():
    db = SessionLocal()
    admin = db.query(User).filter_by(username="admin").first()
    if not admin:
        db.add(User(username="admin", password=ADMIN_PASSWORD, role="admin", agent_slug=None))
        db.commit()
    db.close()

ensure_admin_user()

def get_base_url():
    if BASE_URL:
        return BASE_URL
    return request.url_root.strip().rstrip("/")

def pick_lang_from_request() -> str:
    q = (request.args.get("lang") or "").strip().lower()
    if q:
        q = q.split("-", 1)[0]
        return q if q in SUPPORTED_LANGS else "it"

    al = (request.headers.get("Accept-Language") or "").lower()
    if al:
        first = al.split(",", 1)[0].strip().split("-", 1)[0]
        if first in SUPPORTED_LANGS:
            return first
    return "it"

def safe_json_load(s: str, default):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default

def i18n_get(ag: Agent) -> dict:
    return safe_json_load(getattr(ag, "i18n_json", "") or "", {})

def i18n_set(ag: Agent, data: dict):
    ag.i18n_json = json.dumps(data, ensure_ascii=False)

def apply_i18n_to_agent_view(ag_view, ag: Agent, lang: str):
    if lang not in SUPPORTED_LANGS or lang == "it":
        return ag_view
    data = i18n_get(ag)
    tr = data.get(lang) if isinstance(data, dict) else None
    if not isinstance(tr, dict):
        return ag_view
    for k in ("name", "company", "role", "bio", "addresses"):
        v = clean_str(tr.get(k))
        if v:
            setattr(ag_view, k, v)
    return ag_view

def upload_file(file_storage, folder="uploads", max_bytes=None):
    if not file_storage or not file_storage.filename:
        return None

    if max_bytes is not None:
        file_storage.stream.seek(0, os.SEEK_END)
        size = file_storage.stream.tell()
        file_storage.stream.seek(0)
        if size > max_bytes:
            raise ValueError("file too large")

    ext = os.path.splitext(file_storage.filename or "")[1].lower()
    uploads_folder = os.path.join(PERSIST_UPLOADS_DIR, folder)
    os.makedirs(uploads_folder, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{ext}"
    fullpath = os.path.join(uploads_folder, filename)
    file_storage.save(fullpath)

    return f"/uploads/{folder}/{filename}"

@app.get("/uploads/<path:subpath>")
def serve_uploads(subpath):
    return send_from_directory(PERSIST_UPLOADS_DIR, subpath)

def parse_pdfs(raw: str):
    pdfs = []
    if not raw:
        return pdfs
    tokens = raw.split("|")
    for item in tokens:
        item = (item or "").strip()
        if not item:
            continue
        if "||" in item:
            name, url = item.split("||", 1)
            name = (name or "Documento").strip()
            url = (url or "").strip()
            if url:
                pdfs.append({"name": name, "url": url})
        else:
            url = item
            filename = os.path.basename(urllib.parse.urlparse(url).path) or "Documento"
            pdfs.append({"name": filename, "url": url})
    return pdfs

def parse_media_list(raw: str):
    raw = clean_str(raw)
    if not raw:
        return []
    return [x.strip() for x in raw.split("|") if clean_str(x)]

def normalize_whatsapp_link(raw: str) -> str:
    t0 = clean_str(raw)
    if not t0:
        return ""
    if t0.startswith("http://") or t0.startswith("https://"):
        return t0
    t2 = t0.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if t2.startswith("+"):
        t2 = t2[1:]
    if t2.startswith("00"):
        t2 = t2[2:]
    if t2.isdigit():
        return f"https://wa.me/{t2}"
    return ""

def safe_url(u: str) -> str:
    u = clean_str(u)
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("@"):
        return f"https://t.me/{u[1:]}"
    if "." in u and " " not in u and not u.startswith("mailto:"):
        return "https://" + u.lstrip("/")
    return ""

def google_maps_link(address: str) -> str:
    q = urllib.parse.quote_plus(address)
    return f"https://www.google.com/maps/search/?api=1&query={q}"

def parse_profiles_json(raw: str):
    data = safe_json_load(raw, [])
    if not isinstance(data, list):
        return []
    out = []
    for p in data:
        if isinstance(p, dict) and p.get("key"):
            out.append(p)
    return out

def upsert_profile(profiles: list, key: str, payload: dict):
    for p in profiles:
        if p.get("key") == key:
            p.update(payload)
            return profiles
    profiles.append({"key": key, **payload})
    return profiles

def select_profile(profiles: list, key: str):
    if not key:
        return None
    for p in profiles:
        if p.get("key") == key:
            return p
    return None

def agent_to_view(ag: Agent):
    logo = clean_str(getattr(ag, "logo_url", None)) or clean_str(getattr(ag, "extra_logo_url", None))
    return SimpleNamespace(
        id=ag.id,
        slug=ag.slug,
        name=clean_str(ag.name) or "",
        company=clean_str(ag.company),
        role=clean_str(ag.role),
        bio=clean_str(ag.bio),
        phone_mobile=clean_str(ag.phone_mobile),
        phone_mobile2=clean_str(ag.phone_mobile2),
        phone_office=clean_str(ag.phone_office),
        emails=clean_str(ag.emails),
        websites=clean_str(ag.websites),
        facebook=safe_url(ag.facebook),
        instagram=safe_url(ag.instagram),
        linkedin=safe_url(ag.linkedin),
        tiktok=safe_url(ag.tiktok),
        telegram=safe_url(ag.telegram),
        whatsapp=clean_str(ag.whatsapp),
        pec=clean_str(ag.pec),
        piva=clean_str(ag.piva),
        sdi=clean_str(ag.sdi),
        addresses=clean_str(ag.addresses),
        photo_url=clean_str(ag.photo_url),
        logo_url=logo,
        gallery_urls=clean_str(ag.gallery_urls),
        video_urls=clean_str(ag.video_urls),
        pdf1_url=clean_str(ag.pdf1_url),
        p2_enabled=int(getattr(ag, "p2_enabled", 0) or 0),
        profiles_json=getattr(ag, "profiles_json", None),

        orbit_spin=int(getattr(ag, "orbit_spin", 0) or 0),
        avatar_spin=int(getattr(ag, "avatar_spin", 0) or 0),
        logo_spin=int(getattr(ag, "logo_spin", 0) or 0),
        allow_flip=int(getattr(ag, "allow_flip", 0) or 0),
    )

def blank_profile_view_from_agent(ag: Agent) -> SimpleNamespace:
    """
    View per Profilo 2 completamente VUOTO (NON copia P1).
    """
    return SimpleNamespace(
        id=ag.id,
        slug=ag.slug,

        name="",
        company="",
        role="",
        bio="",

        phone_mobile="",
        phone_mobile2="",
        phone_office="",

        emails="",
        websites="",

        facebook="",
        instagram="",
        linkedin="",
        tiktok="",
        telegram="",
        whatsapp="",

        pec="",
        piva="",
        sdi="",
        addresses="",

        photo_url="",
        logo_url="",

        gallery_urls="",
        video_urls="",
        pdf1_url="",

        p2_enabled=1,
        profiles_json=ag.profiles_json,

        orbit_spin=0,
        avatar_spin=0,
        logo_spin=0,
        allow_flip=0,
    )

# ===================== ROUTES =====================

@app.get("/")
def home():
    if is_logged_in():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.get("/health")
def health():
    return "ok", 200

# ---------- LOGIN ----------
@app.get("/login")
def login():
    return render_template("login.html", error=None)

@app.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()

    if not username or not password:
        return render_template("login.html", error="Inserisci username e password")

    if username == "admin" and password == ADMIN_PASSWORD:
        session["username"] = "admin"
        session["role"] = "admin"
        session["agent_slug"] = None
        return redirect(url_for("dashboard"))

    db = SessionLocal()
    u = db.query(User).filter_by(username=username, password=password).first()
    db.close()
    if not u:
        return render_template("login.html", error="Credenziali errate")

    session["username"] = u.username
    session["role"] = u.role
    session["agent_slug"] = u.agent_slug
    return redirect(url_for("dashboard"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- DASHBOARD (admin e clienti) ----------
@app.get("/dashboard")
@login_required
def dashboard():
    db = SessionLocal()
    if is_admin():
        agents = db.query(Agent).order_by(Agent.name).all()
        db.close()
        return render_template("admin_list.html", agents=agents, is_admin=True, agent=None)
    else:
        slug = current_client_slug()
        ag = db.query(Agent).filter_by(slug=slug).first()
        db.close()
        if not ag:
            abort(404)
        return render_template("admin_list.html", agents=[ag], is_admin=False, agent=ag)

# ---------- ADMIN CRUD ----------
@app.get("/admin", endpoint="admin_home")
@admin_required
def admin_home():
    return redirect(url_for("dashboard"))

@app.get("/admin/new")
@admin_required
def new_agent():
    return render_template("agent_form.html", agent=None, i18n_data=None, editing_profile2=False)

@app.post("/admin/new")
@admin_required
def create_agent():
    db = SessionLocal()
    slug = slugify(request.form.get("slug", ""))
    name = (request.form.get("name") or "").strip()
    if not slug or not name:
        db.close()
        return "Slug e Nome obbligatori", 400
    if db.query(Agent).filter_by(slug=slug).first():
        db.close()
        return "Slug già esistente", 400

    ag = Agent(
        slug=slug,
        name=name,
        p2_enabled=0,
        orbit_spin=form_checkbox_int("orbit_spin"),
        avatar_spin=form_checkbox_int("avatar_spin"),
        logo_spin=form_checkbox_int("logo_spin"),
        allow_flip=form_checkbox_int("allow_flip"),
    )

    for k in ["company","role","bio","phone_mobile","phone_mobile2","phone_office","whatsapp",
              "emails","websites","pec","piva","sdi","addresses",
              "facebook","instagram","linkedin","tiktok","telegram"]:
        setattr(ag, k, clean_str(request.form.get(k)))

    # i18n
    i18n_data = {}
    for lang in ("en", "fr", "es", "de"):
        tr = {
            "name": clean_str(request.form.get(f"name_{lang}")),
            "company": clean_str(request.form.get(f"company_{lang}")),
            "role": clean_str(request.form.get(f"role_{lang}")),
            "bio": clean_str(request.form.get(f"bio_{lang}")),
            "addresses": clean_str(request.form.get(f"addresses_{lang}")),
        }
        tr = {k: v for k, v in tr.items() if v}
        if tr:
            i18n_data[lang] = tr
    if i18n_data:
        i18n_set(ag, i18n_data)

    photo = request.files.get("photo")
    logo = request.files.get("logo")
    if photo and photo.filename:
        ag.photo_url = upload_file(photo, "photos", mb_to_bytes(MAX_IMAGE_MB))
    if logo and logo.filename:
        ag.logo_url = upload_file(logo, "logos", mb_to_bytes(MAX_IMAGE_MB))

    gallery_files = request.files.getlist("gallery")
    gallery_urls = []
    for f in gallery_files[:MAX_GALLERY_IMAGES]:
        if f and f.filename:
            u = upload_file(f, "gallery", mb_to_bytes(MAX_IMAGE_MB))
            if u:
                gallery_urls.append(u)
    if gallery_urls:
        ag.gallery_urls = "|".join(gallery_urls)

    video_files = request.files.getlist("videos")
    video_urls = []
    for f in video_files[:MAX_VIDEOS]:
        if f and f.filename:
            u = upload_file(f, "videos", mb_to_bytes(MAX_VIDEO_MB))
            if u:
                video_urls.append(u)
    if video_urls:
        ag.video_urls = "|".join(video_urls)

    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf", mb_to_bytes(MAX_PDF_MB))
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        ag.pdf1_url = "|".join(pdf_entries)

    db.add(ag)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        db.close()
        return "Errore salvataggio", 400

    # crea utente client automatico
    u = db.query(User).filter_by(username=slug).first()
    if not u:
        pw = generate_password()
        db.add(User(username=slug, password=pw, role="client", agent_slug=slug))
        db.commit()

    db.close()
    flash("Card creata.", "success")
    return redirect(url_for("dashboard"))

@app.get("/admin/<slug>/edit")
@admin_required
def edit_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)
    return render_template("agent_form.html", agent=agent_to_view(ag), i18n_data=i18n_get(ag), editing_profile2=False)

@app.post("/admin/<slug>/edit")
@admin_required
def update_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    for k in ["name","company","role","bio","phone_mobile","phone_mobile2","phone_office","whatsapp",
              "emails","websites","pec","piva","sdi","addresses",
              "facebook","instagram","linkedin","tiktok","telegram"]:
        setattr(ag, k, clean_str(request.form.get(k)))

    ag.orbit_spin = form_checkbox_int("orbit_spin")
    ag.avatar_spin = form_checkbox_int("avatar_spin")
    ag.logo_spin = form_checkbox_int("logo_spin")
    ag.allow_flip = form_checkbox_int("allow_flip")

    i18n_data = i18n_get(ag)
    if not isinstance(i18n_data, dict):
        i18n_data = {}
    for lang in ("en", "fr", "es", "de"):
        tr = {
            "name": clean_str(request.form.get(f"name_{lang}")),
            "company": clean_str(request.form.get(f"company_{lang}")),
            "role": clean_str(request.form.get(f"role_{lang}")),
            "bio": clean_str(request.form.get(f"bio_{lang}")),
            "addresses": clean_str(request.form.get(f"addresses_{lang}")),
        }
        tr = {k: v for k, v in tr.items() if v}
        if tr:
            i18n_data[lang] = tr
    i18n_set(ag, i18n_data)

    photo = request.files.get("photo")
    logo = request.files.get("logo")
    if photo and photo.filename:
        ag.photo_url = upload_file(photo, "photos", mb_to_bytes(MAX_IMAGE_MB))
    if logo and logo.filename:
        ag.logo_url = upload_file(logo, "logos", mb_to_bytes(MAX_IMAGE_MB))

    gallery_files = request.files.getlist("gallery")
    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                u = upload_file(f, "gallery", mb_to_bytes(MAX_IMAGE_MB))
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            ag.gallery_urls = "|".join(gallery_urls)

    video_files = request.files.getlist("videos")
    if video_files and any(v.filename for v in video_files):
        video_urls = []
        for f in video_files[:MAX_VIDEOS]:
            if f and f.filename:
                u = upload_file(f, "videos", mb_to_bytes(MAX_VIDEO_MB))
                if u:
                    video_urls.append(u)
        if video_urls:
            ag.video_urls = "|".join(video_urls)

    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf", mb_to_bytes(MAX_PDF_MB))
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        ag.pdf1_url = "|".join(pdf_entries)

    db.commit()
    db.close()
    flash("Profilo 1 salvato.", "success")
    return redirect(url_for("dashboard"))

@app.post("/admin/<slug>/delete")
@admin_required
def delete_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if ag:
        db.delete(ag)
        db.commit()
    db.close()
    flash("Card eliminata.", "success")
    return redirect(url_for("dashboard"))

# ---------- CLIENT EDIT P1 ----------
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
    return render_template("agent_form.html", agent=agent_to_view(ag), i18n_data=i18n_get(ag), editing_profile2=False)

@app.post("/me/edit")
@login_required
def me_edit_post():
    if is_admin():
        return redirect(url_for("dashboard"))
    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    for k in ["name","company","role","bio","phone_mobile","phone_mobile2","phone_office","whatsapp",
              "emails","websites","pec","piva","sdi","addresses",
              "facebook","instagram","linkedin","tiktok","telegram"]:
        setattr(ag, k, clean_str(request.form.get(k)))

    ag.orbit_spin = form_checkbox_int("orbit_spin")
    ag.avatar_spin = form_checkbox_int("avatar_spin")
    ag.logo_spin = form_checkbox_int("logo_spin")
    ag.allow_flip = form_checkbox_int("allow_flip")

    i18n_data = i18n_get(ag)
    if not isinstance(i18n_data, dict):
        i18n_data = {}
    for lang in ("en", "fr", "es", "de"):
        tr = {
            "name": clean_str(request.form.get(f"name_{lang}")),
            "company": clean_str(request.form.get(f"company_{lang}")),
            "role": clean_str(request.form.get(f"role_{lang}")),
            "bio": clean_str(request.form.get(f"bio_{lang}")),
            "addresses": clean_str(request.form.get(f"addresses_{lang}")),
        }
        tr = {k: v for k, v in tr.items() if v}
        if tr:
            i18n_data[lang] = tr
    i18n_set(ag, i18n_data)

    photo = request.files.get("photo")
    logo = request.files.get("logo")
    if photo and photo.filename:
        ag.photo_url = upload_file(photo, "photos", mb_to_bytes(MAX_IMAGE_MB))
    if logo and logo.filename:
        ag.logo_url = upload_file(logo, "logos", mb_to_bytes(MAX_IMAGE_MB))

    gallery_files = request.files.getlist("gallery")
    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                u = upload_file(f, "gallery", mb_to_bytes(MAX_IMAGE_MB))
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            ag.gallery_urls = "|".join(gallery_urls)

    video_files = request.files.getlist("videos")
    if video_files and any(v.filename for v in video_files):
        video_urls = []
        for f in video_files[:MAX_VIDEOS]:
            if f and f.filename:
                u = upload_file(f, "videos", mb_to_bytes(MAX_VIDEO_MB))
                if u:
                    video_urls.append(u)
        if video_urls:
            ag.video_urls = "|".join(video_urls)

    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf", mb_to_bytes(MAX_PDF_MB))
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        ag.pdf1_url = "|".join(pdf_entries)

    db.commit()
    db.close()
    flash("Profilo 1 salvato.", "success")
    return redirect(url_for("me_edit"))

# ---------- P2: attiva + disattiva + edit ----------
@app.post("/me/activate_p2")
@login_required
def me_activate_p2():
    if is_admin():
        return redirect(url_for("dashboard"))

    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    ag.p2_enabled = 1

    # P2 deve partire VUOTO (nessuna copia da P1)
    profiles = parse_profiles_json(ag.profiles_json or "")
    if not select_profile(profiles, "p2"):
        profiles = upsert_profile(profiles, "p2", {"key": "p2"})
        ag.profiles_json = json.dumps(profiles, ensure_ascii=False)

    db.commit()
    db.close()
    flash("Profilo 2 attivato (vuoto).", "success")
    return redirect(url_for("me_profile2"))

@app.post("/me/deactivate_p2")
@login_required
def me_deactivate_p2():
    if is_admin():
        return redirect(url_for("dashboard"))

    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    ag.p2_enabled = 0
    db.commit()
    db.close()
    flash("Profilo 2 disattivato.", "success")
    return redirect(url_for("me_edit"))

@app.post("/admin/<slug>/activate_p2")
@admin_required
def admin_activate_p2(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    ag.p2_enabled = 1

    profiles = parse_profiles_json(ag.profiles_json or "")
    if not select_profile(profiles, "p2"):
        profiles = upsert_profile(profiles, "p2", {"key": "p2"})
        ag.profiles_json = json.dumps(profiles, ensure_ascii=False)

    db.commit()
    db.close()
    flash("Profilo 2 attivato (vuoto).", "success")
    return redirect(url_for("dashboard"))

@app.post("/admin/<slug>/deactivate_p2")
@admin_required
def admin_deactivate_p2(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    ag.p2_enabled = 0
    db.commit()
    db.close()
    flash("Profilo 2 disattivato.", "success")
    return redirect(url_for("dashboard"))

@app.get("/me/profile2")
@login_required
def me_profile2():
    if is_admin():
        return redirect(url_for("dashboard"))
    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)
    if int(getattr(ag, "p2_enabled", 0) or 0) != 1:
        return redirect(url_for("me_edit"))

    profiles = parse_profiles_json(ag.profiles_json or "")
    p2 = select_profile(profiles, "p2") or {"key": "p2"}

    view = blank_profile_view_from_agent(ag)

    for k in ["name","company","role","bio","phone_mobile","phone_mobile2","phone_office","emails","websites",
              "whatsapp","pec","piva","sdi","addresses","facebook","instagram","linkedin","tiktok","telegram",
              "photo_url","logo_url","gallery_urls","video_urls","pdf1_url",
              "orbit_spin","avatar_spin","logo_spin","allow_flip"]:
        v = p2.get(k)
        if v is None:
            continue
        if k in ("orbit_spin","avatar_spin","logo_spin","allow_flip"):
            try:
                setattr(view, k, int(v))
            except Exception:
                pass
        else:
            vv = clean_str(v)
            if vv is not None:
                setattr(view, k, vv)

    return render_template("agent_form.html", agent=view, i18n_data=i18n_get(ag), editing_profile2=True)

@app.post("/me/profile2")
@login_required
def me_profile2_post():
    if is_admin():
        return redirect(url_for("dashboard"))
    slug = current_client_slug()
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)
    ag.p2_enabled = 1

    profiles = parse_profiles_json(ag.profiles_json or "")
    payload = {}
    for k in ["name","company","role","bio","phone_mobile","phone_mobile2","phone_office","emails","websites",
              "whatsapp","pec","piva","sdi","addresses","facebook","instagram","linkedin","tiktok","telegram"]:
        payload[k] = clean_str(request.form.get(k))

    payload["orbit_spin"] = form_checkbox_int("orbit_spin")
    payload["avatar_spin"] = form_checkbox_int("avatar_spin")
    payload["logo_spin"] = form_checkbox_int("logo_spin")
    payload["allow_flip"] = form_checkbox_int("allow_flip")

    photo = request.files.get("photo")
    logo = request.files.get("logo")
    if photo and photo.filename:
        payload["photo_url"] = upload_file(photo, "photos", mb_to_bytes(MAX_IMAGE_MB))
    if logo and logo.filename:
        payload["logo_url"] = upload_file(logo, "logos", mb_to_bytes(MAX_IMAGE_MB))

    # MEDIA P2 (separati!)
    gallery_files = request.files.getlist("gallery")
    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                u = upload_file(f, "gallery", mb_to_bytes(MAX_IMAGE_MB))
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            payload["gallery_urls"] = "|".join(gallery_urls)

    video_files = request.files.getlist("videos")
    if video_files and any(v.filename for v in video_files):
        video_urls = []
        for f in video_files[:MAX_VIDEOS]:
            if f and f.filename:
                u = upload_file(f, "videos", mb_to_bytes(MAX_VIDEO_MB))
                if u:
                    video_urls.append(u)
        if video_urls:
            payload["video_urls"] = "|".join(video_urls)

    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf", mb_to_bytes(MAX_PDF_MB))
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        payload["pdf1_url"] = "|".join(pdf_entries)

    profiles = upsert_profile(
        profiles,
        "p2",
        {"key": "p2", **{k: v for k, v in payload.items() if v is not None}}
    )
    ag.profiles_json = json.dumps(profiles, ensure_ascii=False)

    db.commit()
    db.close()
    flash("Profilo 2 salvato.", "success")
    return redirect(url_for("me_profile2"))

# --- ADMIN: modifica P2 ---
@app.get("/admin/<slug>/profile2")
@admin_required
def admin_profile2(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)

    if int(getattr(ag, "p2_enabled", 0) or 0) != 1:
        flash("Prima attiva il Profilo 2.", "warning")
        return redirect(url_for("dashboard"))

    profiles = parse_profiles_json(ag.profiles_json or "")
    p2 = select_profile(profiles, "p2") or {"key": "p2"}

    view = blank_profile_view_from_agent(ag)

    for k in ["name","company","role","bio","phone_mobile","phone_mobile2","phone_office","emails","websites",
              "whatsapp","pec","piva","sdi","addresses","facebook","instagram","linkedin","tiktok","telegram",
              "photo_url","logo_url","gallery_urls","video_urls","pdf1_url",
              "orbit_spin","avatar_spin","logo_spin","allow_flip"]:
        v = p2.get(k)
        if v is None:
            continue
        if k in ("orbit_spin","avatar_spin","logo_spin","allow_flip"):
            try:
                setattr(view, k, int(v))
            except Exception:
                pass
        else:
            vv = clean_str(v)
            if vv is not None:
                setattr(view, k, vv)

    return render_template("agent_form.html", agent=view, i18n_data=i18n_get(ag), editing_profile2=True)

@app.post("/admin/<slug>/profile2")
@admin_required
def admin_profile2_post(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    ag.p2_enabled = 1
    profiles = parse_profiles_json(ag.profiles_json or "")

    payload = {}
    for k in ["name","company","role","bio","phone_mobile","phone_mobile2","phone_office","emails","websites",
              "whatsapp","pec","piva","sdi","addresses","facebook","instagram","linkedin","tiktok","telegram"]:
        payload[k] = clean_str(request.form.get(k))

    payload["orbit_spin"] = form_checkbox_int("orbit_spin")
    payload["avatar_spin"] = form_checkbox_int("avatar_spin")
    payload["logo_spin"] = form_checkbox_int("logo_spin")
    payload["allow_flip"] = form_checkbox_int("allow_flip")

    photo = request.files.get("photo")
    logo = request.files.get("logo")
    if photo and photo.filename:
        payload["photo_url"] = upload_file(photo, "photos", mb_to_bytes(MAX_IMAGE_MB))
    if logo and logo.filename:
        payload["logo_url"] = upload_file(logo, "logos", mb_to_bytes(MAX_IMAGE_MB))

    # MEDIA P2 (separati!)
    gallery_files = request.files.getlist("gallery")
    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                u = upload_file(f, "gallery", mb_to_bytes(MAX_IMAGE_MB))
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            payload["gallery_urls"] = "|".join(gallery_urls)

    video_files = request.files.getlist("videos")
    if video_files and any(v.filename for v in video_files):
        video_urls = []
        for f in video_files[:MAX_VIDEOS]:
            if f and f.filename:
                u = upload_file(f, "videos", mb_to_bytes(MAX_VIDEO_MB))
                if u:
                    video_urls.append(u)
        if video_urls:
            payload["video_urls"] = "|".join(video_urls)

    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf", mb_to_bytes(MAX_PDF_MB))
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        payload["pdf1_url"] = "|".join(pdf_entries)

    profiles = upsert_profile(
        profiles,
        "p2",
        {"key": "p2", **{k: v for k, v in payload.items() if v is not None}}
    )
    ag.profiles_json = json.dumps(profiles, ensure_ascii=False)

    db.commit()
    db.close()
    flash("Profilo 2 salvato.", "success")
    return redirect(url_for("admin_profile2", slug=slug))

# ---------- ADMIN: INVIA CODICI (HTML) ----------
@app.get("/admin/<slug>/credentials")
@admin_required
def admin_credentials_html(slug):
    slug = slugify(slug)
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
        card_url=card_url
    )

# ---------- PUBLIC CARD ----------
@app.get("/<slug>")
def public_card(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)

    lang = pick_lang_from_request()
    p_key = (request.args.get("p") or "").strip()  # "" o "p2"

    p2_enabled = int(getattr(ag, "p2_enabled", 0) or 0) == 1
    profiles = parse_profiles_json(ag.profiles_json or "")
    p2 = select_profile(profiles, "p2")

    if p_key != "p2":
        ag_view = agent_to_view(ag)
        ag_view = apply_i18n_to_agent_view(ag_view, ag, lang)

        gallery = parse_media_list(ag.gallery_urls)
        videos = parse_media_list(ag.video_urls)
        pdfs = parse_pdfs(ag.pdf1_url or "")
    else:
        ag_view = blank_profile_view_from_agent(ag)
        if p2_enabled and p2:
            for k in ["name","company","role","bio","phone_mobile","phone_mobile2","phone_office","emails","websites",
                      "whatsapp","pec","piva","sdi","addresses","facebook","instagram","linkedin","tiktok","telegram",
                      "photo_url","logo_url","gallery_urls","video_urls","pdf1_url",
                      "orbit_spin","avatar_spin","logo_spin","allow_flip"]:
                v = p2.get(k)
                if v is None:
                    continue
                if k in ("orbit_spin","avatar_spin","logo_spin","allow_flip"):
                    try:
                        setattr(ag_view, k, int(v))
                    except Exception:
                        pass
                else:
                    vv = clean_str(v)
                    if vv is not None:
                        setattr(ag_view, k, vv)

        # MEDIA DI P2 (vuoti se non caricati)
        gallery = parse_media_list(getattr(ag_view, "gallery_urls", "") or "")
        videos = parse_media_list(getattr(ag_view, "video_urls", "") or "")
        pdfs = parse_pdfs(getattr(ag_view, "pdf1_url", "") or "")

    base = get_base_url()

    emails = [e.strip() for e in (ag_view.emails or "").split(",") if clean_str(e)]
    pec_email = clean_str(ag_view.pec)

    websites = [w.strip() for w in (ag_view.websites or "").split(",") if clean_str(w)]
    raw_addresses = [a.strip() for a in (ag_view.addresses or "").split("\n") if clean_str(a)]
    addresses = [{"text": a, "maps": google_maps_link(a)} for a in raw_addresses]

    mobiles = []
    if clean_str(ag_view.phone_mobile):
        mobiles.append(ag_view.phone_mobile.strip())
    if clean_str(ag_view.phone_mobile2):
        mobiles.append(ag_view.phone_mobile2.strip())

    wa_link = normalize_whatsapp_link(ag_view.whatsapp or ag_view.phone_mobile or "")

    qr_url = f"{base}/{ag.slug}/qr.png?lang={urllib.parse.quote(lang)}"
    if p_key:
        qr_url += f"&p={urllib.parse.quote(p_key)}"

    return render_template(
        "card.html",
        ag=ag_view,
        lang=lang,
        t_func=lambda k: t(lang, k),
        base_url=base,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        emails=emails,
        pec_email=pec_email,
        websites=websites,
        addresses=addresses,
        mobiles=mobiles,
        wa_link=wa_link,
        qr_url=qr_url,
        p_key=p_key,
        p2_enabled=p2_enabled,
    )

# ---------- VCARD ----------
@app.get("/<slug>.vcf")
def vcard(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)

    full_name = ag.name or ""
    parts = full_name.strip().split(" ", 1)
    if len(parts) == 2:
        first_name, last_name = parts[0], parts[1]
    else:
        first_name, last_name = full_name, ""

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{full_name}",
        f"N:{last_name};{first_name};;;",
    ]

    if ag.role:
        lines.append(f"TITLE:{ag.role}")
    if ag.company:
        lines.append(f"ORG:{ag.company}")

    if ag.phone_mobile:
        lines.append(f"TEL;TYPE=CELL:{ag.phone_mobile}")
    if ag.phone_mobile2:
        lines.append(f"TEL;TYPE=CELL:{ag.phone_mobile2}")
    if ag.phone_office:
        lines.append(f"TEL;TYPE=WORK:{ag.phone_office}")

    if ag.emails:
        for e in [x.strip() for x in ag.emails.split(",") if x.strip()]:
            lines.append(f"EMAIL;TYPE=WORK:{e}")
    if ag.pec:
        lines.append(f"EMAIL;TYPE=INTERNET:{ag.pec}")

    base = get_base_url()
    card_url = f"{base}/{ag.slug}"
    lines.append(f"URL:{card_url}")

    if ag.piva:
        lines.append(f"X-TAX-ID:{ag.piva}")
    if ag.sdi:
        lines.append(f"X-SDI-CODE:{ag.sdi}")

    lines.append("END:VCARD")
    content = "\r\n".join(lines)

    resp = Response(content, mimetype="text/vcard; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{ag.slug}.vcf"'
    return resp

# ---------- QR ----------
@app.get("/<slug>/qr.png")
def qr(slug):
    slug = slugify(slug)
    base = get_base_url()
    lang = pick_lang_from_request()
    p = (request.args.get("p") or "").strip()

    url = f"{base}/{slug}?lang={urllib.parse.quote(lang)}"
    if p:
        url += f"&p={urllib.parse.quote(p)}"

    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")

# ---------- ERRORS ----------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
