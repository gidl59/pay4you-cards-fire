import os
import re
import uuid
import json
from datetime import datetime
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
        "close": "Chiudi",
        "open": "Apri",
        "profile2": "Profilo 2",
        "edit": "Modifica",
        "logout": "Logout",
        "back": "Indietro",
    },
    "en": {
        "save_contact": "Save contact",
        "scan_qr": "Scan QR",
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
        "close": "Close",
        "open": "Open",
        "profile2": "Profile 2",
        "edit": "Edit",
        "logout": "Logout",
        "back": "Back",
    },
    "fr": {
        "save_contact": "Enregistrer le contact",
        "scan_qr": "Scanner le QR",
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
        "close": "Fermer",
        "open": "Ouvrir",
        "profile2": "Profil 2",
        "edit": "Modifier",
        "logout": "Déconnexion",
        "back": "Retour",
    },
    "es": {
        "save_contact": "Guardar contacto",
        "scan_qr": "Escanear QR",
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
        "close": "Cerrar",
        "open": "Abrir",
        "profile2": "Perfil 2",
        "edit": "Editar",
        "logout": "Salir",
        "back": "Atrás",
    },
    "de": {
        "save_contact": "Kontakt speichern",
        "scan_qr": "QR scannen",
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
        "close": "Schließen",
        "open": "Öffnen",
        "profile2": "Profil 2",
        "edit": "Bearbeiten",
        "logout": "Abmelden",
        "back": "Zurück",
    },
}

def t(lang: str, key: str) -> str:
    lang = (lang or "it").lower()
    if lang not in SUPPORTED_LANGS:
        lang = "it"
    return I18N.get(lang, I18N["it"]).get(key, key)

def mb_to_bytes(mb: int) -> int:
    return int(mb) * 1024 * 1024


app = Flask(__name__)
app.secret_key = APP_SECRET
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024  # massimo request complessiva (250MB)

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
    logo_url = Column(String, nullable=True)      # (nuovo) logo
    extra_logo_url = Column(String, nullable=True)  # (vecchio) fallback se esiste

    gallery_urls = Column(Text, nullable=True)
    video_urls = Column(Text, nullable=True)
    pdf1_url = Column(Text, nullable=True)

    # multi profilo (p2)
    profiles_json = Column(Text, nullable=True)

    # traduzioni profilo 1
    i18n_json = Column(Text, nullable=True)


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
ensure_sqlite_column("agents", "extra_logo_url", "TEXT")
ensure_sqlite_column("agents", "phone_office", "TEXT")
ensure_sqlite_column("agents", "phone_mobile2", "TEXT")
ensure_sqlite_column("agents", "sdi", "TEXT")
ensure_sqlite_column("agents", "piva", "TEXT")


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
        v = (tr.get(k) or "").strip()
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
            parsed = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed.path) or "Documento"
            pdfs.append({"name": filename, "url": url})
    return pdfs

def normalize_whatsapp_link(raw: str) -> str:
    t0 = (raw or "").strip()
    if not t0:
        return ""
    if t0.startswith("http://") or t0.startswith("https://"):
        return t0

    t = t0.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if t.startswith("+"):
        t = t[1:]
    if t.startswith("00"):
        t = t[2:]
    if t.isdigit():
        return f"https://wa.me/{t}"
    return ""

def parse_profiles_json(raw: str):
    data = safe_json_load(raw or "", [])
    if not isinstance(data, list):
        return []
    out = []
    for p in data:
        if isinstance(p, dict) and p.get("key"):
            out.append(p)
    return out

def upsert_profile(profiles: list, key: str, payload: dict):
    found = False
    for p in profiles:
        if p.get("key") == key:
            p.update(payload)
            found = True
            break
    if not found:
        base = {"key": key}
        base.update(payload)
        profiles.append(base)
    return profiles

def select_profile(profiles: list, key: str):
    if not key:
        return None
    for p in profiles:
        if p.get("key") == key:
            return p
    return None

def agent_to_view(ag: Agent):
    logo = (getattr(ag, "logo_url", None) or "").strip() or (getattr(ag, "extra_logo_url", None) or "").strip()
    return SimpleNamespace(
        id=ag.id,
        slug=ag.slug,
        name=ag.name,
        company=ag.company,
        role=ag.role,
        bio=ag.bio,
        phone_mobile=ag.phone_mobile,
        phone_mobile2=ag.phone_mobile2,
        phone_office=ag.phone_office,
        emails=ag.emails,
        websites=ag.websites,
        facebook=ag.facebook,
        instagram=ag.instagram,
        linkedin=ag.linkedin,
        tiktok=ag.tiktok,
        telegram=ag.telegram,
        whatsapp=ag.whatsapp,
        pec=ag.pec,
        piva=ag.piva,
        sdi=ag.sdi,
        addresses=ag.addresses,
        photo_url=ag.photo_url,
        logo_url=logo,
        gallery_urls=ag.gallery_urls,
        video_urls=ag.video_urls,
        pdf1_url=ag.pdf1_url,
    )

def apply_profile2_to_view(view, p2: dict):
    """
    Profilo 2: prende SOLO i campi compilati, sovrascrive la view.
    (no traduzione automatica su p2)
    """
    if not isinstance(p2, dict):
        return view

    mapping = {
        "name": "name",
        "company": "company",
        "role": "role",
        "bio": "bio",
        "phone_mobile": "phone_mobile",
        "phone_mobile2": "phone_mobile2",
        "phone_office": "phone_office",
        "emails": "emails",
        "websites": "websites",
        "facebook": "facebook",
        "instagram": "instagram",
        "linkedin": "linkedin",
        "tiktok": "tiktok",
        "telegram": "telegram",
        "whatsapp": "whatsapp",
        "pec": "pec",
        "piva": "piva",
        "sdi": "sdi",
        "addresses": "addresses",
        "photo_url": "photo_url",
        "logo_url": "logo_url",
    }

    for k, attr in mapping.items():
        v = (p2.get(k) or "").strip()
        if v:
            setattr(view, attr, v)
    return view


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
    db.close()
    return render_template("admin_list.html", agents=agents)

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
            "logo_url": (getattr(a, "logo_url", None) or getattr(a, "extra_logo_url", None)),
            "gallery_urls": a.gallery_urls,
            "video_urls": a.video_urls,
            "pdf1_url": a.pdf1_url,
            "profiles_json": a.profiles_json,
            "i18n_json": a.i18n_json,
        })
    db.close()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    resp = Response(content, mimetype="application/json; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="agents-export.json"'
    return resp

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
        company=(request.form.get("company") or "").strip() or None,
        role=(request.form.get("role") or "").strip() or None,
        bio=(request.form.get("bio") or "").strip() or None,
        phone_mobile=(request.form.get("phone_mobile") or "").strip() or None,
        phone_mobile2=(request.form.get("phone_mobile2") or "").strip() or None,
        phone_office=(request.form.get("phone_office") or "").strip() or None,
        emails=(request.form.get("emails") or "").strip() or None,
        websites=(request.form.get("websites") or "").strip() or None,
        facebook=(request.form.get("facebook") or "").strip() or None,
        instagram=(request.form.get("instagram") or "").strip() or None,
        linkedin=(request.form.get("linkedin") or "").strip() or None,
        tiktok=(request.form.get("tiktok") or "").strip() or None,
        telegram=(request.form.get("telegram") or "").strip() or None,
        whatsapp=(request.form.get("whatsapp") or "").strip() or None,
        pec=(request.form.get("pec") or "").strip() or None,
        piva=(request.form.get("piva") or "").strip() or None,
        sdi=(request.form.get("sdi") or "").strip() or None,
        addresses=(request.form.get("addresses") or "").strip() or None,
        i18n_json=None,
        profiles_json=None,
    )

    # i18n profile 1
    i18n_data = {}
    for lang in ("en", "fr", "es", "de"):
        tr = {
            "name": (request.form.get(f"name_{lang}") or "").strip(),
            "company": (request.form.get(f"company_{lang}") or "").strip(),
            "role": (request.form.get(f"role_{lang}") or "").strip(),
            "bio": (request.form.get(f"bio_{lang}") or "").strip(),
            "addresses": (request.form.get(f"addresses_{lang}") or "").strip(),
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

    # pdfs
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

    # crea utente client automatico
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
    return render_template("agent_form.html", agent=ag, i18n_data=i18n_get(ag), editing_profile2=False)

@app.post("/admin/<slug>/edit")
@admin_required
def update_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        db.close()
        abort(404)

    for k in [
        "name","company","role","bio",
        "phone_mobile","phone_mobile2","phone_office",
        "emails","websites",
        "facebook","instagram","linkedin","tiktok","telegram","whatsapp",
        "pec","piva","sdi","addresses",
    ]:
        setattr(ag, k, (request.form.get(k) or "").strip() or None)

    # i18n update
    i18n_data = i18n_get(ag)
    if not isinstance(i18n_data, dict):
        i18n_data = {}

    for lang in ("en", "fr", "es", "de"):
        tr = {
            "name": (request.form.get(f"name_{lang}") or "").strip(),
            "company": (request.form.get(f"company_{lang}") or "").strip(),
            "role": (request.form.get(f"role_{lang}") or "").strip(),
            "bio": (request.form.get(f"bio_{lang}") or "").strip(),
            "addresses": (request.form.get(f"addresses_{lang}") or "").strip(),
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
        db.commit()
    db.close()
    return redirect(url_for("admin_home"))


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

    return render_template("agent_form.html", agent=ag, i18n_data=i18n_get(ag), editing_profile2=False)

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
        setattr(ag, k, (request.form.get(k) or "").strip() or None)

    # i18n profile 1 (cliente compila)
    i18n_data = i18n_get(ag)
    if not isinstance(i18n_data, dict):
        i18n_data = {}

    for lang in ("en", "fr", "es", "de"):
        tr = {
            "name": (request.form.get(f"name_{lang}") or "").strip(),
            "company": (request.form.get(f"company_{lang}") or "").strip(),
            "role": (request.form.get(f"role_{lang}") or "").strip(),
            "bio": (request.form.get(f"bio_{lang}") or "").strip(),
            "addresses": (request.form.get(f"addresses_{lang}") or "").strip(),
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
        ag.pdf1_url = "|".join(pdf_entries)

    db.commit()
    db.close()
    return redirect(url_for("me_edit"))


# ---------- CLIENT (profilo 2) ----------
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

    profiles = parse_profiles_json(ag.profiles_json or "")
    p2 = select_profile(profiles, "p2") or {"key": "p2"}

    # creo view base e applico p2 sopra
    view = agent_to_view(ag)
    view = apply_profile2_to_view(view, p2)

    return render_template("agent_form.html", agent=view, i18n_data=None, editing_profile2=True)

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

    profiles = parse_profiles_json(ag.profiles_json or "")

    payload = {
        "key": "p2",
        "name": (request.form.get("name") or "").strip(),
        "company": (request.form.get("company") or "").strip(),
        "role": (request.form.get("role") or "").strip(),
        "bio": (request.form.get("bio") or "").strip(),
        "phone_mobile": (request.form.get("phone_mobile") or "").strip(),
        "phone_mobile2": (request.form.get("phone_mobile2") or "").strip(),
        "phone_office": (request.form.get("phone_office") or "").strip(),
        "emails": (request.form.get("emails") or "").strip(),
        "websites": (request.form.get("websites") or "").strip(),
        "facebook": (request.form.get("facebook") or "").strip(),
        "instagram": (request.form.get("instagram") or "").strip(),
        "linkedin": (request.form.get("linkedin") or "").strip(),
        "tiktok": (request.form.get("tiktok") or "").strip(),
        "telegram": (request.form.get("telegram") or "").strip(),
        "whatsapp": (request.form.get("whatsapp") or "").strip(),
        "pec": (request.form.get("pec") or "").strip(),
        "piva": (request.form.get("piva") or "").strip(),
        "sdi": (request.form.get("sdi") or "").strip(),
        "addresses": (request.form.get("addresses") or "").strip(),
    }

    # uploads p2 (foto e logo)
    photo = request.files.get("photo")
    logo = request.files.get("logo")

    if photo and photo.filename:
        try:
            payload["photo_url"] = upload_file(photo, "photos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Foto troppo grande (max {MAX_IMAGE_MB}MB)", "error")

    if logo and logo.filename:
        try:
            payload["logo_url"] = upload_file(logo, "logos", max_bytes=mb_to_bytes(MAX_IMAGE_MB))
        except ValueError:
            flash(f"Logo troppo grande (max {MAX_IMAGE_MB}MB)", "error")

    profiles = upsert_profile(profiles, "p2", payload)
    ag.profiles_json = json.dumps(profiles, ensure_ascii=False)

    db.commit()
    db.close()
    return redirect(url_for("me_profile2"))


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
    p = (request.args.get("p") or "").strip().lower()

    # view base
    ag_view = agent_to_view(ag)

    # profilo 2 (solo se richiesto ?p=p2)
    if p == "p2":
        profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")
        p2 = select_profile(profiles, "p2")
        if p2:
            ag_view = apply_profile2_to_view(ag_view, p2)
        # NO i18n su p2
    else:
        # i18n su profilo 1
        ag_view = apply_i18n_to_agent_view(ag_view, ag, lang)

    gallery = (ag.gallery_urls.split("|") if ag.gallery_urls else [])
    videos = (ag.video_urls.split("|") if ag.video_urls else [])
    pdfs = parse_pdfs(ag.pdf1_url or "")

    base = get_base_url()

    emails = [e.strip() for e in (ag_view.emails or "").split(",") if e.strip()]
    websites = [w.strip() for w in (ag_view.websites or "").split(",") if w.strip()]
    addresses = [a.strip() for a in (ag_view.addresses or "").split("\n") if a.strip()]

    mobiles = []
    if ag_view.phone_mobile:
        mobiles.append(ag_view.phone_mobile.strip())
    if ag_view.phone_mobile2:
        mobiles.append(ag_view.phone_mobile2.strip())

    wa_link = normalize_whatsapp_link(ag_view.whatsapp or ag_view.phone_mobile or "")

    qr_url = f"{base}/{ag.slug}/qr.png?lang={urllib.parse.quote(lang)}"
    vcf_url = f"{base}/{ag.slug}.vcf"

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
        websites=websites,
        addresses=addresses,
        mobiles=mobiles,
        wa_link=wa_link,
        qr_url=qr_url,
        vcf_url=vcf_url,
        is_profile2=(p == "p2"),
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
    url = f"{base}/{slug}?lang={urllib.parse.quote(lang)}"

    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")


# ---------- ERRORS ----------
@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        return "Not found", 404

@app.errorhandler(500)
def server_error(e):
    # evita loop se manca 500.html
    return "Internal server error", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
