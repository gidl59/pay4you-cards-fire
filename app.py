import os
import re
import uuid
import json
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import quote_plus

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
import urllib.parse

load_dotenv()

# ===== ENV / CONFIG =====
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")

# Upload persistenti (Render Disk su /var/data/uploads)
PERSIST_UPLOADS_DIR = os.getenv("PERSIST_UPLOADS_DIR", "/var/data/uploads")

# Limiti upload (per evitare blocchi)
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
        "scan_qr": "Scansiona QR",
        "open_website": "Apri sito",
        "open_pdf": "Apri PDF",
        "contacts": "Contatti",
        "social": "Social",
        "documents": "Documenti",
        "gallery": "Galleria",
        "videos": "Video",
        "vat": "Partita IVA",
        "sdi": "SDI",
        "office_phone": "Telefono ufficio",
        "mobile_phone": "Cellulare",
        "whatsapp": "WhatsApp",
        "addresses": "Indirizzi",
        "back": "Indietro",
        "lang": "Lingua",
        "actions": "Azioni",
        "data": "Dati",
        "close": "Chiudi",
        "open_maps": "Apri in Maps",
    },
    "en": {
        "save_contact": "Save contact",
        "scan_qr": "Scan QR",
        "open_website": "Open website",
        "open_pdf": "Open PDF",
        "contacts": "Contacts",
        "social": "Social",
        "documents": "Documents",
        "gallery": "Gallery",
        "videos": "Videos",
        "vat": "VAT number",
        "sdi": "SDI",
        "office_phone": "Office phone",
        "mobile_phone": "Mobile",
        "whatsapp": "WhatsApp",
        "addresses": "Addresses",
        "back": "Back",
        "lang": "Language",
        "actions": "Actions",
        "data": "Data",
        "close": "Close",
        "open_maps": "Open in Maps",
    },
    "fr": {
        "save_contact": "Enregistrer le contact",
        "scan_qr": "Scanner le QR",
        "open_website": "Ouvrir le site",
        "open_pdf": "Ouvrir le PDF",
        "contacts": "Contacts",
        "social": "Réseaux sociaux",
        "documents": "Documents",
        "gallery": "Galerie",
        "videos": "Vidéos",
        "vat": "TVA",
        "sdi": "SDI",
        "office_phone": "Téléphone bureau",
        "mobile_phone": "Mobile",
        "whatsapp": "WhatsApp",
        "addresses": "Adresses",
        "back": "Retour",
        "lang": "Langue",
        "actions": "Actions",
        "data": "Données",
        "close": "Fermer",
        "open_maps": "Ouvrir dans Maps",
    },
    "es": {
        "save_contact": "Guardar contacto",
        "scan_qr": "Escanear QR",
        "open_website": "Abrir web",
        "open_pdf": "Abrir PDF",
        "contacts": "Contactos",
        "social": "Redes sociales",
        "documents": "Documentos",
        "gallery": "Galería",
        "videos": "Vídeos",
        "vat": "NIF/IVA",
        "sdi": "SDI",
        "office_phone": "Tel. oficina",
        "mobile_phone": "Móvil",
        "whatsapp": "WhatsApp",
        "addresses": "Direcciones",
        "back": "Atrás",
        "lang": "Idioma",
        "actions": "Acciones",
        "data": "Datos",
        "close": "Cerrar",
        "open_maps": "Abrir en Maps",
    },
    "de": {
        "save_contact": "Kontakt speichern",
        "scan_qr": "QR scannen",
        "open_website": "Website öffnen",
        "open_pdf": "PDF öffnen",
        "contacts": "Kontakte",
        "social": "Social",
        "documents": "Dokumente",
        "gallery": "Galerie",
        "videos": "Videos",
        "vat": "USt-IdNr.",
        "sdi": "SDI",
        "office_phone": "Büro",
        "mobile_phone": "Mobil",
        "whatsapp": "WhatsApp",
        "addresses": "Adressen",
        "back": "Zurück",
        "lang": "Sprache",
        "actions": "Aktionen",
        "data": "Daten",
        "close": "Schließen",
        "open_maps": "In Maps öffnen",
    },
}

def t(lang: str, key: str) -> str:
    lang = (lang or "it").lower()
    if lang not in SUPPORTED_LANGS:
        lang = "it"
    return I18N.get(lang, I18N["it"]).get(key, key)

def mb_to_bytes(mb: int) -> int:
    return int(mb) * 1024 * 1024

def clean_none(v: str) -> str:
    """Evita che in card compaia 'None' (stringa)"""
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if s.lower() == "none":
        return ""
    return s

def valid_http_url(u: str) -> bool:
    u = (u or "").strip()
    return u.startswith("http://") or u.startswith("https://")

def normalize_social(u: str) -> str:
    """Mostra social solo se è un link valido http/https, altrimenti nascondi."""
    u = clean_none(u)
    if not u:
        return ""
    if not valid_http_url(u):
        return ""
    return u

def normalize_phone_display(v: str) -> str:
    v = clean_none(v)
    if not v:
        return ""
    return v

def normalize_whatsapp_link(raw: str) -> str:
    """
    Accetta:
    - +39333337521
    - 39333337521
    - link già pronto
    """
    t0 = clean_none(raw)
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

def get_base_url():
    if BASE_URL:
        return BASE_URL
    return request.url_root.strip().rstrip("/")

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

app = Flask(__name__)
app.secret_key = APP_SECRET
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024  # max request complessiva

DB_URL = "sqlite:////var/data/data.db"
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ===== MODELS =====
class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)

    # Profilo 1 (base)
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

    gallery_urls = Column(Text, nullable=True)
    video_urls = Column(Text, nullable=True)
    pdf1_url = Column(Text, nullable=True)

    # Multi profilo + i18n
    profiles_json = Column(Text, nullable=True)   # profilo 2 (e settings)
    i18n_json = Column(Text, nullable=True)       # traduzioni P1

    # UI settings P1
    theme = Column(String, nullable=True)         # auto|dark|light
    logo_size = Column(String, nullable=True)     # es "72"
    logo_spin = Column(String, nullable=True)     # "1"/"0"
    avatar_spin = Column(String, nullable=True)   # "1"/"0" (di default 0)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="client")  # admin|client
    agent_slug = Column(String, nullable=True)

Base.metadata.create_all(engine)

# ===== micro-migrazioni (non rompono DB esistente) =====
def ensure_sqlite_column(table: str, column: str, coltype: str):
    with engine.connect() as conn:
        rows = conn.execute(sa_text(f"PRAGMA table_info({table})")).fetchall()
        existing = {r[1] for r in rows}
        if column not in existing:
            conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            conn.commit()

ensure_sqlite_column("agents", "profiles_json", "TEXT")
ensure_sqlite_column("agents", "i18n_json", "TEXT")
ensure_sqlite_column("agents", "logo_url", "TEXT")
ensure_sqlite_column("agents", "phone_office", "TEXT")
ensure_sqlite_column("agents", "phone_mobile2", "TEXT")
ensure_sqlite_column("agents", "sdi", "TEXT")
ensure_sqlite_column("agents", "piva", "TEXT")
ensure_sqlite_column("agents", "theme", "TEXT")
ensure_sqlite_column("agents", "logo_size", "TEXT")
ensure_sqlite_column("agents", "logo_spin", "TEXT")
ensure_sqlite_column("agents", "avatar_spin", "TEXT")

# ===== AUTH HELPERS =====
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

def ensure_admin_user():
    db = SessionLocal()
    admin = db.query(User).filter_by(username="admin").first()
    if not admin:
        db.add(User(username="admin", password=ADMIN_PASSWORD, role="admin", agent_slug=None))
        db.commit()
    db.close()

ensure_admin_user()

# ===== I18N =====
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
        v = clean_none(tr.get(k) or "")
        if v:
            setattr(ag_view, k, v)
    return ag_view

# ===== PROFILES (P2) =====
P2_FIELDS = (
    "name", "company", "role", "bio",
    "phone_mobile", "phone_mobile2", "phone_office",
    "emails", "websites",
    "facebook", "instagram", "linkedin", "tiktok", "telegram", "whatsapp",
    "pec", "piva", "sdi", "addresses",
    "photo_url", "logo_url",
)

def profiles_get(ag: Agent) -> dict:
    data = safe_json_load(getattr(ag, "profiles_json", "") or "", {})
    return data if isinstance(data, dict) else {}

def profiles_set(ag: Agent, data: dict):
    ag.profiles_json = json.dumps(data, ensure_ascii=False)

def get_profile_view(ag: Agent, profile_key: str):
    """Ritorna view per P1 o P2 (se presente)."""
    base_logo = getattr(ag, "logo_url", None) or getattr(ag, "extra_logo_url", None)
    pkey = (profile_key or "").strip().lower()
    if pkey != "p2":
        return SimpleNamespace(
            key="p1",
            slug=ag.slug,
            name=clean_none(ag.name),
            company=clean_none(ag.company),
            role=clean_none(ag.role),
            bio=clean_none(ag.bio),
            phone_mobile=clean_none(ag.phone_mobile),
            phone_mobile2=clean_none(ag.phone_mobile2),
            phone_office=clean_none(ag.phone_office),
            emails=clean_none(ag.emails),
            websites=clean_none(ag.websites),
            facebook=normalize_social(ag.facebook),
            instagram=normalize_social(ag.instagram),
            linkedin=normalize_social(ag.linkedin),
            tiktok=normalize_social(ag.tiktok),
            telegram=normalize_social(ag.telegram),
            whatsapp=clean_none(ag.whatsapp),
            pec=clean_none(ag.pec),
            piva=clean_none(ag.piva),
            sdi=clean_none(ag.sdi),
            addresses=clean_none(ag.addresses),
            photo_url=clean_none(ag.photo_url),
            logo_url=clean_none(base_logo),
            gallery_urls=clean_none(ag.gallery_urls),
            video_urls=clean_none(ag.video_urls),
            pdf1_url=clean_none(ag.pdf1_url),
            theme=clean_none(getattr(ag, "theme", "") or "auto"),
            logo_size=clean_none(getattr(ag, "logo_size", "") or "72"),
            logo_spin=clean_none(getattr(ag, "logo_spin", "") or "1"),
            avatar_spin=clean_none(getattr(ag, "avatar_spin", "") or "0"),
        )

    # P2
    pdata = profiles_get(ag)
    p2 = pdata.get("p2") if isinstance(pdata, dict) else None
    if not isinstance(p2, dict):
        p2 = {}

    # fallback P2: se campo manca, resta vuoto (così P2 è davvero “diverso”)
    def p2v(k):
        return clean_none(p2.get(k) or "")

    # settings P2 (se non presenti, usa quelli P1)
    theme = clean_none(p2.get("theme") or "") or clean_none(getattr(ag, "theme", "") or "auto")
    logo_size = clean_none(p2.get("logo_size") or "") or clean_none(getattr(ag, "logo_size", "") or "72")
    logo_spin = clean_none(p2.get("logo_spin") or "") or clean_none(getattr(ag, "logo_spin", "") or "1")
    avatar_spin = clean_none(p2.get("avatar_spin") or "") or clean_none(getattr(ag, "avatar_spin", "") or "0")

    return SimpleNamespace(
        key="p2",
        slug=ag.slug,
        name=p2v("name"),
        company=p2v("company"),
        role=p2v("role"),
        bio=p2v("bio"),
        phone_mobile=p2v("phone_mobile"),
        phone_mobile2=p2v("phone_mobile2"),
        phone_office=p2v("phone_office"),
        emails=p2v("emails"),
        websites=p2v("websites"),
        facebook=normalize_social(p2.get("facebook")),
        instagram=normalize_social(p2.get("instagram")),
        linkedin=normalize_social(p2.get("linkedin")),
        tiktok=normalize_social(p2.get("tiktok")),
        telegram=normalize_social(p2.get("telegram")),
        whatsapp=p2v("whatsapp"),
        pec=p2v("pec"),
        piva=p2v("piva"),
        sdi=p2v("sdi"),
        addresses=p2v("addresses"),
        photo_url=p2v("photo_url"),
        logo_url=p2v("logo_url") or clean_none(getattr(ag, "logo_url", None) or getattr(ag, "extra_logo_url", None)),
        gallery_urls="",   # P2 non usa media (resta su P1)
        video_urls="",
        pdf1_url="",
        theme=theme,
        logo_size=logo_size,
        logo_spin=logo_spin,
        avatar_spin=avatar_spin,
    )

@app.get("/uploads/<path:subpath>")
def serve_uploads(subpath):
    return send_from_directory(PERSIST_UPLOADS_DIR, subpath)

# ===================== ROUTES =====================

@app.get("/")
def home():
    if is_logged_in():
        return redirect(url_for("admin_home" if is_admin() else "me_edit"))
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
        return redirect(url_for("admin_home"))

    db = SessionLocal()
    u = db.query(User).filter_by(username=username, password=password).first()
    db.close()

    if not u:
        return render_template("login.html", error="Credenziali errate")

    session["username"] = u.username
    session["role"] = u.role
    session["agent_slug"] = u.agent_slug

    return redirect(url_for("admin_home" if u.role == "admin" else "me_edit"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- ADMIN ----------
@app.get("/admin")
@admin_required
def admin_home():
    db = SessionLocal()
    agents = db.query(Agent).order_by(Agent.name).all()
    # flag “P2 esiste?”
    rows = []
    for a in agents:
        pdata = profiles_get(a)
        has_p2 = isinstance(pdata, dict) and isinstance(pdata.get("p2"), dict) and any(clean_none(pdata["p2"].get(k)) for k in ("name","company","role","bio","phone_mobile","emails"))
        rows.append(SimpleNamespace(
            name=a.name,
            slug=a.slug,
            has_p2=bool(has_p2),
        ))
    db.close()
    return render_template("admin_list.html", agents=rows)

@app.get("/admin/export_agents.json")
@admin_required
def admin_export_agents_json():
    db = SessionLocal()
    agents = db.query(Agent).order_by(Agent.id).all()
    payload = []
    for a in agents:
        payload.append({
            "id": a.id,
            "slug": a.slug,
            "name": a.name,
            "company": a.company,
            "role": a.role,
            "bio": a.bio,
            "phone_mobile": a.phone_mobile,
            "phone_mobile2": a.phone_mobile2,
            "phone_office": a.phone_office,
            "emails": a.emails,
            "websites": a.websites,
            "facebook": a.facebook,
            "instagram": a.instagram,
            "linkedin": a.linkedin,
            "tiktok": a.tiktok,
            "telegram": a.telegram,
            "whatsapp": a.whatsapp,
            "pec": a.pec,
            "piva": a.piva,
            "sdi": a.sdi,
            "addresses": a.addresses,
            "photo_url": a.photo_url,
            "logo_url": getattr(a, "logo_url", None) or getattr(a, "extra_logo_url", None),
            "gallery_urls": a.gallery_urls,
            "video_urls": a.video_urls,
            "pdf1_url": a.pdf1_url,
            "profiles_json": a.profiles_json,
            "i18n_json": a.i18n_json,
            "theme": a.theme,
            "logo_size": a.logo_size,
            "logo_spin": a.logo_spin,
            "avatar_spin": a.avatar_spin,
        })
    db.close()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    resp = Response(content, mimetype="application/json; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="agents-export.json"'
    return resp

@app.get("/admin/new")
@admin_required
def new_agent():
    return render_template("agent_form.html", agent=None, editing_profile2=False, p2=None, i18n_data=None)

@app.post("/admin/new")
@admin_required
def create_agent():
    db = SessionLocal()

    slug = slugify(request.form.get("slug", ""))
    name = clean_none(request.form.get("name") or "")
    if not slug or not name:
        db.close()
        return "Slug e Nome obbligatori", 400

    if db.query(Agent).filter_by(slug=slug).first():
        db.close()
        return "Slug già esistente", 400

    ag = Agent(
        slug=slug,
        name=name,
        company=clean_none(request.form.get("company") or "") or None,
        role=clean_none(request.form.get("role") or "") or None,
        bio=clean_none(request.form.get("bio") or "") or None,

        phone_mobile=clean_none(request.form.get("phone_mobile") or "") or None,
        phone_mobile2=clean_none(request.form.get("phone_mobile2") or "") or None,
        phone_office=clean_none(request.form.get("phone_office") or "") or None,

        whatsapp=clean_none(request.form.get("whatsapp") or "") or None,

        emails=clean_none(request.form.get("emails") or "") or None,
        websites=clean_none(request.form.get("websites") or "") or None,

        facebook=clean_none(request.form.get("facebook") or "") or None,
        instagram=clean_none(request.form.get("instagram") or "") or None,
        linkedin=clean_none(request.form.get("linkedin") or "") or None,
        tiktok=clean_none(request.form.get("tiktok") or "") or None,
        telegram=clean_none(request.form.get("telegram") or "") or None,

        pec=clean_none(request.form.get("pec") or "") or None,
        piva=clean_none(request.form.get("piva") or "") or None,
        sdi=clean_none(request.form.get("sdi") or "") or None,
        addresses=clean_none(request.form.get("addresses") or "") or None,

        theme=clean_none(request.form.get("theme") or "auto") or "auto",
        logo_size=clean_none(request.form.get("logo_size") or "72") or "72",
        logo_spin="1" if (request.form.get("logo_spin") == "1") else "0",
        avatar_spin="1" if (request.form.get("avatar_spin") == "1") else "0",
    )

    # i18n profile 1
    i18n_data = {}
    for lang in ("en", "fr", "es", "de"):
        tr = {
            "name": clean_none(request.form.get(f"name_{lang}") or ""),
            "company": clean_none(request.form.get(f"company_{lang}") or ""),
            "role": clean_none(request.form.get(f"role_{lang}") or ""),
            "bio": clean_none(request.form.get(f"bio_{lang}") or ""),
            "addresses": clean_none(request.form.get(f"addresses_{lang}") or ""),
        }
        tr = {k: v for k, v in tr.items() if v}
        if tr:
            i18n_data[lang] = tr
    if i18n_data:
        i18n_set(ag, i18n_data)

    # uploads
    photo = request.files.get("photo")
    logo = request.files.get("logo")

    if photo and photo.filename:
        try:
            ag.photo_url = upload_file(photo, "photos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Foto troppo grande (max {MAX_IMAGE_MB}MB)", "error")

    if logo and logo.filename:
        try:
            ag.logo_url = upload_file(logo, "logos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Logo troppo grande (max {MAX_IMAGE_MB}MB)", "error")

    # gallery
    gallery_files = request.files.getlist("gallery")
    gallery_urls = []
    for f in gallery_files[:MAX_GALLERY_IMAGES]:
        if f and f.filename:
            try:
                u = upload_file(f, "gallery", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
            except ValueError:
                flash(f"Immagine troppo grande (max {MAX_IMAGE_MB}MB): {f.filename}", "error")
                continue
            if u:
                gallery_urls.append(u)
    if gallery_urls:
        ag.gallery_urls = "|".join(gallery_urls)

    # videos
    video_files = request.files.getlist("videos")
    video_urls = []
    for f in video_files[:MAX_VIDEOS]:
        if f and f.filename:
            try:
                u = upload_file(f, "videos", max_bytes=mb_to_bytes(MAX_VIDEO_MB))
            except ValueError:
                flash(f"Video troppo grande (max {MAX_VIDEO_MB}MB): {f.filename}", "error")
                continue
            if u:
                video_urls.append(u)
    if video_urls:
        ag.video_urls = "|".join(video_urls)

    # pdfs (12)
    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            try:
                u = upload_file(f, "pdf", max_bytes=mb_to_bytes(MAX_PDF_MB))
            except ValueError:
                flash(f"PDF troppo grande (max {MAX_PDF_MB}MB): {f.filename}", "error")
                continue
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
        return "Errore salvataggio (slug duplicato?)", 400

    # crea user client automatico (username=slug)
    u = db.query(User).filter_by(username=slug).first()
    if not u:
        pw = generate_password()
        db.add(User(username=slug, password=pw, role="client", agent_slug=slug))
        db.commit()

    db.close()
    return redirect(url_for("admin_home"))

@app.get("/admin/<slug>/edit")
@admin_required
def edit_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)
    return render_template("agent_form.html", agent=ag, editing_profile2=False, p2=None, i18n_data=i18n_get(ag))

@app.post("/admin/<slug>/edit")
@admin_required
def update_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    # base fields
    for k in [
        "name","company","role","bio",
        "phone_mobile","phone_mobile2","phone_office",
        "emails","websites",
        "facebook","instagram","linkedin","tiktok","telegram","whatsapp",
        "pec","piva","sdi","addresses",
    ]:
        val = clean_none(request.form.get(k) or "")
        setattr(ag, k, val or None)

    ag.theme = clean_none(request.form.get("theme") or "auto") or "auto"
    ag.logo_size = clean_none(request.form.get("logo_size") or "72") or "72"
    ag.logo_spin = "1" if (request.form.get("logo_spin") == "1") else "0"
    ag.avatar_spin = "1" if (request.form.get("avatar_spin") == "1") else "0"

    # i18n update
    i18n_data = i18n_get(ag)
    if not isinstance(i18n_data, dict):
        i18n_data = {}
    for lang in ("en", "fr", "es", "de"):
        tr = {
            "name": clean_none(request.form.get(f"name_{lang}") or ""),
            "company": clean_none(request.form.get(f"company_{lang}") or ""),
            "role": clean_none(request.form.get(f"role_{lang}") or ""),
            "bio": clean_none(request.form.get(f"bio_{lang}") or ""),
            "addresses": clean_none(request.form.get(f"addresses_{lang}") or ""),
        }
        tr = {k: v for k, v in tr.items() if v}
        if tr:
            i18n_data[lang] = tr
    i18n_set(ag, i18n_data)

    # uploads
    photo = request.files.get("photo")
    logo = request.files.get("logo")

    if photo and photo.filename:
        try:
            ag.photo_url = upload_file(photo, "photos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Foto troppo grande (max {MAX_IMAGE_MB}MB)", "error")

    if logo and logo.filename:
        try:
            ag.logo_url = upload_file(logo, "logos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Logo troppo grande (max {MAX_IMAGE_MB}MB)", "error")

    # gallery replace (solo se carichi)
    gallery_files = request.files.getlist("gallery")
    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                try:
                    u = upload_file(f, "gallery", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
                except ValueError:
                    flash(f"Immagine troppo grande (max {MAX_IMAGE_MB}MB): {f.filename}", "error")
                    continue
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            ag.gallery_urls = "|".join(gallery_urls)

    # videos replace
    video_files = request.files.getlist("videos")
    if video_files and any(v.filename for v in video_files):
        video_urls = []
        for f in video_files[:MAX_VIDEOS]:
            if f and f.filename:
                try:
                    u = upload_file(f, "videos", max_bytes=mb_to_bytes(MAX_VIDEO_MB))
                except ValueError:
                    flash(f"Video troppo grande (max {MAX_VIDEO_MB}MB): {f.filename}", "error")
                    continue
                if u:
                    video_urls.append(u)
        if video_urls:
            ag.video_urls = "|".join(video_urls)

    # pdf append
    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            try:
                u = upload_file(f, "pdf", max_bytes=mb_to_bytes(MAX_PDF_MB))
            except ValueError:
                flash(f"PDF troppo grande (max {MAX_PDF_MB}MB): {f.filename}", "error")
                continue
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        # append (mantieni quelli già presenti)
        existing = clean_none(ag.pdf1_url or "")
        if existing:
            ag.pdf1_url = existing + "|" + "|".join(pdf_entries)
        else:
            ag.pdf1_url = "|".join(pdf_entries)

    db.commit()
    db.close()
    return redirect(url_for("admin_home"))

@app.post("/admin/<slug>/delete")
@admin_required
def delete_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if ag:
        db.delete(ag)
        # elimina anche user client
        u = db.query(User).filter_by(username=slug).first()
        if u:
            db.delete(u)
        db.commit()
    db.close()
    return redirect(url_for("admin_home"))

@app.get("/admin/<slug>/credentials")
@admin_required
def admin_credentials(slug):
    slug = slugify(slug)
    db = SessionLocal()
    u = db.query(User).filter_by(username=slug).first()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not u or not ag:
        abort(404)

    base = get_base_url()
    login_url = f"{base}/login"
    card_url = f"{base}/{slug}"

    # whatsapp "manuale" (in attesa meta business): se agente ha mobile, preparo testo
    phone = clean_none(ag.phone_mobile) or clean_none(ag.whatsapp)
    wa_link = normalize_whatsapp_link(phone)
    wa_prefill = ""
    if wa_link:
        msg = f"Ciao! Ecco le tue credenziali Pay4You.\nLogin: {login_url}\nUsername: {u.username}\nPassword: {u.password}\nLa tua card: {card_url}"
        wa_prefill = wa_link + "?text=" + urllib.parse.quote(msg)

    return render_template(
        "credentials.html",
        agent=ag,
        username=u.username,
        password=u.password,
        login_url=login_url,
        card_url=card_url,
        wa_prefill=wa_prefill,
    )

# ---------- CLIENT (profilo 1) ----------
@app.get("/me/edit")
@login_required
def me_edit():
    if is_admin():
        return redirect(url_for("admin_home"))
    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)
    return render_template("agent_form.html", agent=ag, editing_profile2=False, p2=None, i18n_data=i18n_get(ag))

@app.post("/me/edit")
@login_required
def me_edit_post():
    if is_admin():
        return redirect(url_for("admin_home"))
    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    allowed_fields = [
        "name","company","role","bio",
        "phone_mobile","phone_mobile2","phone_office",
        "emails","websites",
        "facebook","instagram","linkedin","tiktok","telegram",
        "pec","piva","sdi","addresses",
        "whatsapp",
    ]
    for k in allowed_fields:
        val = clean_none(request.form.get(k) or "")
        setattr(ag, k, val or None)

    # UI
    ag.theme = clean_none(request.form.get("theme") or "auto") or "auto"
    ag.logo_size = clean_none(request.form.get("logo_size") or "72") or "72"
    ag.logo_spin = "1" if (request.form.get("logo_spin") == "1") else "0"
    ag.avatar_spin = "1" if (request.form.get("avatar_spin") == "1") else "0"

    # i18n profile 1 (cliente può compilarlo)
    i18n_data = i18n_get(ag)
    if not isinstance(i18n_data, dict):
        i18n_data = {}
    for lang in ("en", "fr", "es", "de"):
        tr = {
            "name": clean_none(request.form.get(f"name_{lang}") or ""),
            "company": clean_none(request.form.get(f"company_{lang}") or ""),
            "role": clean_none(request.form.get(f"role_{lang}") or ""),
            "bio": clean_none(request.form.get(f"bio_{lang}") or ""),
            "addresses": clean_none(request.form.get(f"addresses_{lang}") or ""),
        }
        tr = {k: v for k, v in tr.items() if v}
        if tr:
            i18n_data[lang] = tr
    i18n_set(ag, i18n_data)

    # uploads
    photo = request.files.get("photo")
    logo = request.files.get("logo")

    if photo and photo.filename:
        try:
            ag.photo_url = upload_file(photo, "photos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Foto troppo grande (max {MAX_IMAGE_MB}MB)", "error")

    if logo and logo.filename:
        try:
            ag.logo_url = upload_file(logo, "logos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Logo troppo grande (max {MAX_IMAGE_MB}MB)", "error")

    # gallery replace
    gallery_files = request.files.getlist("gallery")
    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                try:
                    u = upload_file(f, "gallery", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
                except ValueError:
                    flash(f"Immagine troppo grande (max {MAX_IMAGE_MB}MB): {f.filename}", "error")
                    continue
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            ag.gallery_urls = "|".join(gallery_urls)

    # videos replace
    video_files = request.files.getlist("videos")
    if video_files and any(v.filename for v in video_files):
        video_urls = []
        for f in video_files[:MAX_VIDEOS]:
            if f and f.filename:
                try:
                    u = upload_file(f, "videos", max_bytes=mb_to_bytes(MAX_VIDEO_MB))
                except ValueError:
                    flash(f"Video troppo grande (max {MAX_VIDEO_MB}MB): {f.filename}", "error")
                    continue
                if u:
                    video_urls.append(u)
        if video_urls:
            ag.video_urls = "|".join(video_urls)

    # pdf append
    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            try:
                u = upload_file(f, "pdf", max_bytes=mb_to_bytes(MAX_PDF_MB))
            except ValueError:
                flash(f"PDF troppo grande (max {MAX_PDF_MB}MB): {f.filename}", "error")
                continue
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        existing = clean_none(ag.pdf1_url or "")
        if existing:
            ag.pdf1_url = existing + "|" + "|".join(pdf_entries)
        else:
            ag.pdf1_url = "|".join(pdf_entries)

    db.commit()
    db.close()
    return redirect(url_for("me_edit"))

# ---------- CLIENT P2 ----------
@app.get("/me/profile2")
@login_required
def me_profile2():
    if is_admin():
        return redirect(url_for("admin_home"))
    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)

    pdata = profiles_get(ag)
    p2 = pdata.get("p2") if isinstance(pdata, dict) else {}
    if not isinstance(p2, dict):
        p2 = {}

    return render_template("agent_form.html", agent=ag, editing_profile2=True, p2=p2, i18n_data=i18n_get(ag))

@app.post("/me/profile2")
@login_required
def me_profile2_post():
    if is_admin():
        return redirect(url_for("admin_home"))
    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    pdata = profiles_get(ag)
    if not isinstance(pdata, dict):
        pdata = {}
    p2 = pdata.get("p2") if isinstance(pdata.get("p2"), dict) else {}

    # salva solo i campi P2 (testuali)
    for k in P2_FIELDS:
        if k in ("photo_url","logo_url"):
            continue
        p2[k] = clean_none(request.form.get(k) or "")

    # UI settings P2
    p2["theme"] = clean_none(request.form.get("theme") or "")  # se vuoto eredita
    p2["logo_size"] = clean_none(request.form.get("logo_size") or "")
    p2["logo_spin"] = "1" if (request.form.get("logo_spin") == "1") else "0"
    p2["avatar_spin"] = "1" if (request.form.get("avatar_spin") == "1") else "0"

    # uploads P2
    photo = request.files.get("photo")
    logo = request.files.get("logo")
    if photo and photo.filename:
        try:
            p2["photo_url"] = upload_file(photo, "photos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Foto troppo grande (max {MAX_IMAGE_MB}MB)", "error")
    if logo and logo.filename:
        try:
            p2["logo_url"] = upload_file(logo, "logos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Logo troppo grande (max {MAX_IMAGE_MB}MB)", "error")

    pdata["p2"] = p2
    profiles_set(ag, pdata)

    db.commit()
    db.close()
    return redirect(url_for("me_profile2"))

# ---------- PUBLIC CARD ----------
@app.get("/<slug>")
def public_card(slug):
    slug = slugify(slug)
    p_key = (request.args.get("p") or "").strip().lower()
    if p_key != "p2":
        p_key = ""

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    db.close()
    if not ag:
        abort(404)

    lang = pick_lang_from_request()

    ag_view = get_profile_view(ag, "p2" if p_key == "p2" else "p1")
    # Applica traduzioni SOLO a P1 (come volevi)
    if p_key != "p2":
        ag_view = apply_i18n_to_agent_view(ag_view, ag, lang)

    # media solo per P1
    gallery = (ag.gallery_urls.split("|") if (p_key != "p2" and clean_none(ag.gallery_urls)) else [])
    videos = (ag.video_urls.split("|") if (p_key != "p2" and clean_none(ag.video_urls)) else [])
    pdfs = parse_pdfs(ag.pdf1_url or "") if p_key != "p2" else []

    base = get_base_url()

    emails = [e.strip() for e in clean_none(ag_view.emails).split(",") if e.strip()]
    websites = [w.strip() for w in clean_none(ag_view.websites).split(",") if w.strip()]

    addresses_raw = [a.strip() for a in clean_none(ag_view.addresses).split("\n") if a.strip()]
    addresses = []
    for a in addresses_raw:
        # ogni indirizzo apre maps (sempre)
        maps = "https://www.google.com/maps/search/?api=1&query=" + quote_plus(a)
        addresses.append({"text": a, "maps": maps})

    mobiles = []
    if clean_none(ag_view.phone_mobile):
        mobiles.append(ag_view.phone_mobile.strip())
    if clean_none(ag_view.phone_mobile2):
        mobiles.append(ag_view.phone_mobile2.strip())

    wa_link = normalize_whatsapp_link(clean_none(ag_view.whatsapp) or clean_none(ag_view.phone_mobile))

    # QR deve “portare” p e lang
    qr_url = url_for("qr", slug=ag.slug, _external=False, lang=lang, p=("p2" if p_key == "p2" else ""))

    # per switch P1/P2
    pdata = profiles_get(ag)
    has_p2 = isinstance(pdata, dict) and isinstance(pdata.get("p2"), dict) and any(clean_none(pdata["p2"].get(k)) for k in ("name","company","role","bio","phone_mobile","emails"))
    profiles = []
    if has_p2:
        profiles.append(SimpleNamespace(key="p2", label="Profilo 2"))

    # tema: auto/dark/light
    theme = clean_none(getattr(ag_view, "theme", "") or "auto")
    if theme not in ("auto", "dark", "light"):
        theme = "auto"

    # logo options
    logo_size = int(clean_none(getattr(ag_view, "logo_size", "") or "72") or "72")
    if logo_size < 48:
        logo_size = 48
    if logo_size > 120:
        logo_size = 120

    logo_spin = (clean_none(getattr(ag_view, "logo_spin", "") or "1") == "1")
    avatar_spin = (clean_none(getattr(ag_view, "avatar_spin", "") or "0") == "1")

    return render_template(
        "card.html",
        ag=ag_view,
        lang=lang,
        p_key=p_key,
        profiles=profiles,
        t_func=lambda k: t(lang, k),
        base_url=base,
        gallery=gallery,
        videos=videos,
        pdfs=pdfs,
        emails=emails,
        websites=websites,
        addresses=addresses,
        mobiles=mobiles,
        wa_link=wa_link,
        qr_url=qr_url,
        theme=theme,
        logo_size=logo_size,
        logo_spin=logo_spin,
        avatar_spin=avatar_spin,
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

    if clean_none(ag.phone_mobile):
        lines.append(f"TEL;TYPE=CELL:{ag.phone_mobile}")
    if clean_none(ag.phone_mobile2):
        lines.append(f"TEL;TYPE=CELL:{ag.phone_mobile2}")
    if clean_none(ag.phone_office):
        lines.append(f"TEL;TYPE=WORK:{ag.phone_office}")

    if clean_none(ag.emails):
        for e in [x.strip() for x in ag.emails.split(",") if x.strip()]:
            lines.append(f"EMAIL;TYPE=WORK:{e}")

    base = get_base_url()
    card_url = f"{base}/{ag.slug}"
    lines.append(f"URL:{card_url}")

    if clean_none(ag.piva):
        lines.append(f"X-TAX-ID:{ag.piva}")
    if clean_none(ag.sdi):
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
    p = (request.args.get("p") or "").strip().lower()
    if p != "p2":
        p = ""

    url = f"{base}/{slug}"
    qs = []
    if p:
        qs.append("p=p2")
    if lang:
        qs.append(f"lang={urllib.parse.quote(lang)}")
    if qs:
        url += "?" + "&".join(qs)

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
def internal(e):
    return render_template("500.html"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
