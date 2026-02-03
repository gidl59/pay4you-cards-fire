import os
import re
import uuid
import json
from datetime import datetime
from io import BytesIO
from urllib.parse import quote
from types import SimpleNamespace

from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, session, abort, Response,
    send_from_directory, flash
)
from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    text as sa_text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import qrcode
import urllib.parse

# ---- optional requests (better) ----
try:
    import requests
except Exception:
    requests = None

load_dotenv()

# ===== ENV / CONFIG =====
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")

# WhatsApp Cloud API (lo facciamo dopo)
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "verify_token_change_me")
WA_TOKEN = os.getenv("WA_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_API_VERSION = os.getenv("WA_API_VERSION", "v20.0")

WA_OPTIN_PHONE = os.getenv("WA_OPTIN_PHONE", "393508725353").strip().replace("+", "").replace(" ", "")

# Upload persistenti (Render Disk su /var/data)
PERSIST_UPLOADS_DIR = os.getenv("PERSIST_UPLOADS_DIR", "/var/data/uploads")

app = Flask(__name__)
app.secret_key = APP_SECRET
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB

DB_URL = "sqlite:////var/data/data.db"
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ✅ LIMITI
MAX_GALLERY_IMAGES = 30
MAX_VIDEOS = 10

SUPPORTED_LANGS = ("it", "en")


# ===== MODELS =====
class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
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
    extra_logo_url = Column(String, nullable=True)

    gallery_urls = Column(Text, nullable=True)
    video_urls = Column(Text, nullable=True)
    pdf1_url = Column(Text, nullable=True)

    # Piano (basic/pro)
    plan = Column(String, nullable=True)  # "basic" | "pro"

    # Multi-profile JSON (lista di profili)
    profiles_json = Column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)                  # per ora in chiaro
    role = Column(String, nullable=False, default="client")    # admin | client
    agent_slug = Column(String, nullable=True)


class Subscriber(Base):
    __tablename__ = "subscribers"
    id = Column(Integer, primary_key=True)
    wa_id = Column(String, nullable=False)
    merchant_slug = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    created_at = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)
    last_text = Column(Text, nullable=True)


Base.metadata.create_all(engine)


# ===== MICRO-MIGRAZIONI =====
def ensure_sqlite_column(table: str, column: str, coltype: str):
    with engine.connect() as conn:
        rows = conn.execute(sa_text(f"PRAGMA table_info({table})")).fetchall()
        existing_cols = {r[1] for r in rows}
        if column not in existing_cols:
            conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            conn.commit()

ensure_sqlite_column("agents", "video_urls", "TEXT")
ensure_sqlite_column("agents", "phone_mobile2", "TEXT")
ensure_sqlite_column("agents", "plan", "TEXT")
ensure_sqlite_column("agents", "profiles_json", "TEXT")

ensure_sqlite_column("subscribers", "last_text", "TEXT")
ensure_sqlite_column("subscribers", "updated_at", "TEXT")
ensure_sqlite_column("subscribers", "created_at", "TEXT")
ensure_sqlite_column("subscribers", "status", "TEXT")


def ensure_default_plan_basic():
    with engine.connect() as conn:
        conn.execute(sa_text("UPDATE agents SET plan='basic' WHERE plan IS NULL OR TRIM(plan)=''"))
        conn.commit()

ensure_default_plan_basic()


# ===== HELPERS =====
def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

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

def ensure_admin_user():
    db = SessionLocal()
    admin = db.query(User).filter_by(username="admin").first()
    if not admin:
        db.add(User(username="admin", password=ADMIN_PASSWORD, role="admin", agent_slug=None))
        db.commit()

ensure_admin_user()


def get_base_url():
    if BASE_URL:
        return BASE_URL
    return request.url_root.strip().rstrip("/")


def upload_file(file_storage, folder="uploads"):
    if not file_storage or not file_storage.filename:
        return None

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
    i = 0
    while i < len(tokens):
        item = tokens[i].strip()
        if not item:
            i += 1
            continue

        if "||" in item:
            name, url = item.split("||", 1)
            name = (name or "Documento").strip()
            url = url.strip()
            if url:
                pdfs.append({"name": name, "url": url})
            i += 1
        else:
            url = item
            parsed = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed.path) or "Documento"
            pdfs.append({"name": filename, "url": url})
            i += 1

    return pdfs


def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("+", " ")
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


def normalize_plan(p: str) -> str:
    p = (p or "").strip().lower()
    return p if p in ("basic", "pro") else "basic"

def is_pro_agent(ag) -> bool:
    return normalize_plan(getattr(ag, "plan", "basic")) == "pro"

def sanitize_fields_for_plan(ag):
    return


# ===== LINGUA (IT/EN) =====
I18N = {
    "it": {
        "save_contact": "Salva contatto",
        "open_whatsapp": "Apri WhatsApp",
        "open_website": "Apri sito",
        "documents": "Documenti",
        "gallery": "Galleria",
        "videos": "Video",
        "addresses": "Indirizzi",
        "profile": "Profilo",
        "language": "Lingua",
    },
    "en": {
        "save_contact": "Save contact",
        "open_whatsapp": "Open WhatsApp",
        "open_website": "Open website",
        "documents": "Documents",
        "gallery": "Gallery",
        "videos": "Videos",
        "addresses": "Addresses",
        "profile": "Profile",
        "language": "Language",
    }
}

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

def t(lang: str, key: str) -> str:
    lang = lang if lang in I18N else "it"
    return I18N.get(lang, I18N["it"]).get(key, key)


# ===== MULTI-PROFILI =====
PROFILE_KEYS_ALLOWED = {"p1", "p2"}  # per ora gestiamo solo p2 (p1 = principale)

def parse_profiles_json(raw: str):
    """
    JSON = lista di oggetti.
    Supporta label_it / label_en
    Supporta (quasi) tutti i campi del profilo principale (identico).
    """
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
    except Exception:
        return []

    out = []
    for i, p in enumerate(data):
        if not isinstance(p, dict):
            continue

        key = (p.get("key") or "").strip() or f"p{i+1}"
        key = re.sub(r"[^a-zA-Z0-9_-]", "", key) or f"p{i+1}"

        # Normalizziamo solo p2 (ma non blocchiamo chi vuole p3 etc)
        label_it = (p.get("label_it") or p.get("label") or p.get("name") or f"Profilo {i+1}").strip()
        label_en = (p.get("label_en") or "Profile " + str(i+1)).strip()

        out.append({
            "key": key,
            "label_it": label_it,
            "label_en": label_en,

            "photo_url": (p.get("photo_url") or "").strip(),
            "logo_url": (p.get("logo_url") or p.get("extra_logo_url") or "").strip(),

            "name": (p.get("name") or "").strip(),
            "company": (p.get("company") or "").strip(),
            "role": (p.get("role") or "").strip(),
            "bio": (p.get("bio") or "").strip(),

            "phone_mobile": (p.get("phone_mobile") or "").strip(),
            "phone_mobile2": (p.get("phone_mobile2") or "").strip(),
            "phone_office": (p.get("phone_office") or "").strip(),

            "emails": (p.get("emails") or "").strip(),
            "websites": (p.get("websites") or "").strip(),

            "facebook": (p.get("facebook") or "").strip(),
            "instagram": (p.get("instagram") or "").strip(),
            "linkedin": (p.get("linkedin") or "").strip(),
            "tiktok": (p.get("tiktok") or "").strip(),
            "telegram": (p.get("telegram") or "").strip(),
            "whatsapp": (p.get("whatsapp") or "").strip(),
            "pec": (p.get("pec") or "").strip(),

            "piva": (p.get("piva") or "").strip(),
            "sdi": (p.get("sdi") or "").strip(),
            "addresses": (p.get("addresses") or "").strip(),

            # media opzionali separati (se non li vuoi, lasciali vuoti)
            "gallery_urls": (p.get("gallery_urls") or "").strip(),
            "video_urls": (p.get("video_urls") or "").strip(),
            "pdf1_url": (p.get("pdf1_url") or "").strip(),
        })

    return out


def profiles_to_json(profiles: list) -> str:
    return json.dumps(profiles, ensure_ascii=False, indent=2)


def select_profile(profiles, requested_key: str):
    if not requested_key:
        return None
    for p in profiles:
        if p.get("key") == requested_key:
            return p
    return None


def upsert_profile(profiles: list, key: str, new_obj: dict) -> list:
    updated = False
    for i, p in enumerate(profiles):
        if p.get("key") == key:
            profiles[i] = new_obj
            updated = True
            break
    if not updated:
        profiles.append(new_obj)
    return profiles


def agent_to_view(ag: Agent):
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
        extra_logo_url=ag.extra_logo_url,
        gallery_urls=ag.gallery_urls,
        video_urls=ag.video_urls,
        pdf1_url=ag.pdf1_url,
        plan=ag.plan,
        profiles_json=getattr(ag, "profiles_json", None),
    )


def apply_profile_to_view(view, profile: dict):
    """
    Profilo 2 IDENTICO: se un campo è valorizzato in p2, sovrascrive p1.
    """
    if not profile:
        return view

    def apply(attr, src_key=None):
        k = src_key or attr
        v = (profile.get(k) or "").strip()
        if v:
            setattr(view, attr, v)

    apply("photo_url", "photo_url")
    apply("extra_logo_url", "logo_url")

    apply("name")
    apply("company")
    apply("role")
    apply("bio")

    apply("phone_mobile")
    apply("phone_mobile2")
    apply("phone_office")

    apply("emails")
    apply("websites")

    apply("facebook")
    apply("instagram")
    apply("linkedin")
    apply("tiktok")
    apply("telegram")
    apply("whatsapp")
    apply("pec")

    apply("piva")
    apply("sdi")
    apply("addresses")

    # media (se valorizzati in p2 sovrascrivono p1)
    apply("gallery_urls")
    apply("video_urls")
    apply("pdf1_url")

    return view


def copy_agent_to_profile2(ag: Agent, existing_p2: dict | None = None) -> dict:
    """
    Crea p2 copiando TUTTO da p1 (ag).
    Se esiste già p2, mantiene eventuali campi già compilati (se vuoi).
    """
    def keep(existing_val, fallback):
        ev = (existing_val or "").strip()
        return ev if ev else (fallback or "")

    p2 = existing_p2 or {}

    return {
        "key": "p2",
        "label_it": keep(p2.get("label_it"), "Profilo 2"),
        "label_en": keep(p2.get("label_en"), "Profile 2"),

        "photo_url": keep(p2.get("photo_url"), ag.photo_url),
        "logo_url": keep(p2.get("logo_url"), ag.extra_logo_url),

        "name": keep(p2.get("name"), ag.name),
        "company": keep(p2.get("company"), ag.company),
        "role": keep(p2.get("role"), ag.role),
        "bio": keep(p2.get("bio"), ag.bio),

        "phone_mobile": keep(p2.get("phone_mobile"), ag.phone_mobile),
        "phone_mobile2": keep(p2.get("phone_mobile2"), ag.phone_mobile2),
        "phone_office": keep(p2.get("phone_office"), ag.phone_office),

        "emails": keep(p2.get("emails"), ag.emails),
        "websites": keep(p2.get("websites"), ag.websites),

        "facebook": keep(p2.get("facebook"), ag.facebook),
        "instagram": keep(p2.get("instagram"), ag.instagram),
        "linkedin": keep(p2.get("linkedin"), ag.linkedin),
        "tiktok": keep(p2.get("tiktok"), ag.tiktok),
        "telegram": keep(p2.get("telegram"), ag.telegram),
        "whatsapp": keep(p2.get("whatsapp"), ag.whatsapp),
        "pec": keep(p2.get("pec"), ag.pec),

        "piva": keep(p2.get("piva"), ag.piva),
        "sdi": keep(p2.get("sdi"), ag.sdi),
        "addresses": keep(p2.get("addresses"), ag.addresses),

        "gallery_urls": keep(p2.get("gallery_urls"), ag.gallery_urls),
        "video_urls": keep(p2.get("video_urls"), ag.video_urls),
        "pdf1_url": keep(p2.get("pdf1_url"), ag.pdf1_url),
    }


# ===== ROUTES BASE =====
@app.get("/")
def home():
    if is_logged_in():
        if is_admin():
            return redirect(url_for("admin_home"))
        return redirect(url_for("me_edit"))
    return redirect(url_for("login"))


@app.get("/health")
def health():
    return "ok", 200


# ===== LOGIN =====
@app.get("/login")
def login():
    return render_template("login.html", error=None, next=request.args.get("next", ""))


@app.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()

    if not username or not password:
        return render_template("login.html", error="Inserisci username e password", next="")

    if username == "admin" and password == ADMIN_PASSWORD:
        session["username"] = "admin"
        session["role"] = "admin"
        session["agent_slug"] = None
        return redirect(url_for("admin_home"))

    db = SessionLocal()
    u = db.query(User).filter_by(username=username, password=password).first()
    if not u:
        return render_template("login.html", error="Credenziali errate", next="")

    session["username"] = u.username
    session["role"] = u.role
    session["agent_slug"] = u.agent_slug

    if u.role == "admin":
        return redirect(url_for("admin_home"))
    return redirect(url_for("me_edit"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ===== ADMIN LISTA =====
@app.get("/admin")
@admin_required
def admin_home():
    db = SessionLocal()
    agents = db.query(Agent).order_by(Agent.name).all()
    for a in agents:
        a.plan = normalize_plan(getattr(a, "plan", "basic"))
    return render_template("admin_list.html", agents=agents)


# ===== ADMIN NEW/EDIT (come tuo codice, invariato nei concetti) =====
@app.get("/admin/new")
@admin_required
def new_agent():
    return render_template("agent_form.html", agent=None, mode="main", p_key="")


@app.post("/admin/new")
@admin_required
def create_agent():
    db = SessionLocal()

    fields = [
        "slug", "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office",
        "emails", "websites",
        "facebook", "instagram", "linkedin", "tiktok",
        "telegram", "whatsapp", "pec",
        "piva", "sdi", "addresses",
        "plan",
        "profiles_json",
    ]
    data = {k: (request.form.get(k, "") or "").strip() for k in fields}
    data["plan"] = normalize_plan(data.get("plan", "basic"))

    if data.get("profiles_json"):
        try:
            _tmp = json.loads(data["profiles_json"])
            if not isinstance(_tmp, list):
                data["profiles_json"] = ""
        except Exception:
            data["profiles_json"] = ""

    if not data["slug"] or not data["name"]:
        return "Slug e Nome sono obbligatori", 400

    if db.query(Agent).filter_by(slug=data["slug"]).first():
        return "Slug già esistente", 400

    photo = request.files.get("photo")
    extra_logo = request.files.get("extra_logo")
    gallery_files = request.files.getlist("gallery")
    video_files = request.files.getlist("videos")

    photo_url = upload_file(photo, "photos") if photo and photo.filename else None
    extra_logo_url = upload_file(extra_logo, "logos") if extra_logo and extra_logo.filename else None

    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    pdf_joined = "|".join(pdf_entries) if pdf_entries else None

    gallery_urls = []
    for f in gallery_files[:MAX_GALLERY_IMAGES]:
        if f and f.filename:
            u = upload_file(f, "gallery")
            if u:
                gallery_urls.append(u)

    video_urls = []
    for f in video_files[:MAX_VIDEOS]:
        if f and f.filename:
            u = upload_file(f, "videos")
            if u:
                video_urls.append(u)

    ag = Agent(
        **data,
        photo_url=photo_url,
        extra_logo_url=extra_logo_url,
        pdf1_url=pdf_joined,
        gallery_urls="|".join(gallery_urls) if gallery_urls else None,
        video_urls="|".join(video_urls) if video_urls else None,
    )

    sanitize_fields_for_plan(ag)

    db.add(ag)
    db.commit()

    slug = data["slug"]
    u = db.query(User).filter_by(username=slug).first()
    if not u:
        pw = generate_password()
        db.add(User(username=slug, password=pw, role="client", agent_slug=slug))
        db.commit()
        return f"""
        <h2>Cliente creato ✅</h2>
        <p><b>Card:</b> {slug}</p>
        <p><b>URL card:</b> <a href="/{slug}">/{slug}</a></p>
        <hr>
        <p><b>Login:</b> <a href="/login">/login</a></p>
        <p><b>Username:</b> {slug}</p>
        <p><b>Password:</b> {pw}</p>
        <p><a href="{url_for('admin_home')}">⬅ Torna alla lista</a></p>
        """

    return redirect(url_for("admin_home"))


@app.get("/admin/<slug>/edit")
@admin_required
def edit_agent(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)
    ag.plan = normalize_plan(getattr(ag, "plan", "basic"))
    return render_template("agent_form.html", agent=ag, mode="main", p_key="")


@app.post("/admin/<slug>/edit")
@admin_required
def update_agent(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    for k in [
        "slug", "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office",
        "emails", "websites",
        "facebook", "instagram", "linkedin", "tiktok",
        "telegram", "whatsapp", "pec",
        "piva", "sdi", "addresses",
        "profiles_json",
    ]:
        val = (request.form.get(k, "") or "").strip()
        if k == "profiles_json" and val:
            try:
                _tmp = json.loads(val)
                if not isinstance(_tmp, list):
                    val = ""
            except Exception:
                val = ""
        setattr(ag, k, val)

    ag.plan = normalize_plan(request.form.get("plan", getattr(ag, "plan", "basic")))
    sanitize_fields_for_plan(ag)

    photo = request.files.get("photo")
    extra_logo = request.files.get("extra_logo")
    gallery_files = request.files.getlist("gallery")
    video_files = request.files.getlist("videos")

    if photo and photo.filename:
        u = upload_file(photo, "photos")
        if u:
            ag.photo_url = u

    if extra_logo and extra_logo.filename:
        u = upload_file(extra_logo, "logos")
        if u:
            ag.extra_logo_url = u

    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        ag.pdf1_url = "|".join(pdf_entries)

    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                u = upload_file(f, "gallery")
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            ag.gallery_urls = "|".join(gallery_urls)

    if video_files and any(v.filename for v in video_files):
        video_urls = []
        for f in video_files[:MAX_VIDEOS]:
            if f and f.filename:
                u = upload_file(f, "videos")
                if u:
                    video_urls.append(u)
        if video_urls:
            ag.video_urls = "|".join(video_urls)

    db.commit()
    return redirect(url_for("admin_home"))


@app.post("/admin/<slug>/delete")
@admin_required
def delete_agent(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if ag:
        db.delete(ag)
        db.commit()
    return redirect(url_for("admin_home"))


# ===== AREA CLIENTE (PROFILO 1) =====
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
    if not ag:
        abort(404)

    ag.plan = normalize_plan(getattr(ag, "plan", "basic"))
    return render_template("agent_form.html", agent=ag, mode="main", p_key="")


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
        abort(404)

    current_plan = normalize_plan(getattr(ag, "plan", "basic"))

    allowed_fields = [
        "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office",
        "emails", "websites",
        "facebook", "instagram", "linkedin", "tiktok",
        "telegram",
        "pec",
        "piva", "sdi", "addresses",
    ]
    if current_plan == "pro":
        allowed_fields.append("whatsapp")

    for k in allowed_fields:
        setattr(ag, k, (request.form.get(k, "") or "").strip())

    ag.plan = current_plan

    photo = request.files.get("photo")
    extra_logo = request.files.get("extra_logo")
    gallery_files = request.files.getlist("gallery")
    video_files = request.files.getlist("videos")

    if photo and photo.filename:
        u = upload_file(photo, "photos")
        if u:
            ag.photo_url = u

    if extra_logo and extra_logo.filename:
        u = upload_file(extra_logo, "logos")
        if u:
            ag.extra_logo_url = u

    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        ag.pdf1_url = "|".join(pdf_entries)

    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                u = upload_file(f, "gallery")
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            ag.gallery_urls = "|".join(gallery_urls)

    if video_files and any(v.filename for v in video_files):
        video_urls = []
        for f in video_files[:MAX_VIDEOS]:
            if f and f.filename:
                u = upload_file(f, "videos")
                if u:
                    video_urls.append(u)
        if video_urls:
            ag.video_urls = "|".join(video_urls)

    db.commit()
    flash("Profilo salvato ✅", "ok")
    return redirect(url_for("me_edit"))


# ===== PROFILO 2 (IDENTICO) =====
@app.get("/me/profile2")
@login_required
def me_profile2():
    # route chiamata dal template (risolve il tuo errore)
    return redirect(url_for("me_profile_edit", p_key="p2"))


@app.post("/me/profile2/enable")
@login_required
def me_profile2_enable():
    """
    Bottone "Vuoi un secondo profilo?"
    - crea/aggiorna p2 copiando da p1
    """
    if is_admin():
        return redirect(url_for("admin_home"))

    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")
    existing_p2 = select_profile(profiles, "p2")

    p2 = copy_agent_to_profile2(ag, existing_p2)
    profiles = upsert_profile(profiles, "p2", p2)

    ag.profiles_json = profiles_to_json(profiles)
    db.commit()

    flash("Profilo 2 attivato ✅", "ok")
    return redirect(url_for("me_profile_edit", p_key="p2"))


@app.get("/me/profile/<p_key>/edit")
@login_required
def me_profile_edit(p_key):
    """
    Pagina identica per modificare p2.
    """
    if is_admin():
        return redirect(url_for("admin_home"))

    p_key = (p_key or "").strip()
    if p_key not in ("p2",):
        abort(404)

    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    ag.plan = normalize_plan(getattr(ag, "plan", "basic"))

    profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")
    p2 = select_profile(profiles, "p2")

    # se non esiste ancora, proponiamo enable
    return render_template(
        "agent_form.html",
        agent=ag,
        mode="profile",
        p_key="p2",
        profile=p2
    )


@app.post("/me/profile/<p_key>/edit")
@login_required
def me_profile_edit_post(p_key):
    if is_admin():
        return redirect(url_for("admin_home"))

    p_key = (p_key or "").strip()
    if p_key not in ("p2",):
        abort(404)

    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")
    existing = select_profile(profiles, "p2") or {}

    # campi identici
    def getf(k):
        return (request.form.get(k, "") or "").strip()

    p2 = {
        "key": "p2",
        "label_it": getf("label_it") or (existing.get("label_it") or "Profilo 2"),
        "label_en": getf("label_en") or (existing.get("label_en") or "Profile 2"),

        "photo_url": existing.get("photo_url", ""),
        "logo_url": existing.get("logo_url", ""),

        "name": getf("name"),
        "company": getf("company"),
        "role": getf("role"),
        "bio": getf("bio"),

        "phone_mobile": getf("phone_mobile"),
        "phone_mobile2": getf("phone_mobile2"),
        "phone_office": getf("phone_office"),

        "emails": getf("emails"),
        "websites": getf("websites"),

        "facebook": getf("facebook"),
        "instagram": getf("instagram"),
        "linkedin": getf("linkedin"),
        "tiktok": getf("tiktok"),
        "telegram": getf("telegram"),
        "whatsapp": getf("whatsapp"),
        "pec": getf("pec"),

        "piva": getf("piva"),
        "sdi": getf("sdi"),
        "addresses": getf("addresses"),

        "gallery_urls": existing.get("gallery_urls", ""),
        "video_urls": existing.get("video_urls", ""),
        "pdf1_url": existing.get("pdf1_url", ""),
    }

    # upload separati per p2
    photo = request.files.get("photo")
    extra_logo = request.files.get("extra_logo")
    gallery_files = request.files.getlist("gallery")
    video_files = request.files.getlist("videos")

    if photo and photo.filename:
        u = upload_file(photo, "photos")
        if u:
            p2["photo_url"] = u

    if extra_logo and extra_logo.filename:
        u = upload_file(extra_logo, "logos")
        if u:
            p2["logo_url"] = u

    # media opzionali per p2 (se carichi, sovrascrivono)
    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        p2["pdf1_url"] = "|".join(pdf_entries)

    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                u = upload_file(f, "gallery")
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            p2["gallery_urls"] = "|".join(gallery_urls)

    if video_files and any(v.filename for v in video_files):
        video_urls = []
        for f in video_files[:MAX_VIDEOS]:
            if f and f.filename:
                u = upload_file(f, "videos")
                if u:
                    video_urls.append(u)
        if video_urls:
            p2["video_urls"] = "|".join(video_urls)

    profiles = upsert_profile(profiles, "p2", p2)
    ag.profiles_json = profiles_to_json(profiles)
    db.commit()

    flash("Profilo 2 salvato ✅", "ok")
    return redirect(url_for("me_profile_edit", p_key="p2"))


# ===== CARD PUBBLICA =====
@app.get("/<slug>")
def public_card(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    ag.plan = normalize_plan(getattr(ag, "plan", "basic"))
    lang = pick_lang_from_request()

    profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")
    p_key = (request.args.get("p") or "").strip()
    active_profile = select_profile(profiles, p_key)

    ag_view = agent_to_view(ag)
    if active_profile:
        ag_view = apply_profile_to_view(ag_view, active_profile)

    gallery = (ag_view.gallery_urls.split("|") if ag_view.gallery_urls else [])
    videos = (ag_view.video_urls.split("|") if ag_view.video_urls else [])

    emails = [e.strip() for e in (ag_view.emails or "").split(",") if e.strip()]
    websites = [w.strip() for w in (ag_view.websites or "").split(",") if w.strip()]
    addresses = [a.strip() for a in (ag_view.addresses or "").split("\n") if a.strip()]

    pdfs = parse_pdfs(ag_view.pdf1_url or "")
    base = get_base_url()

    mobiles = []
    if ag_view.phone_mobile:
        mobiles.append(ag_view.phone_mobile.strip())
    if ag_view.phone_mobile2:
        m2 = ag_view.phone_mobile2.strip()
        if m2:
            mobiles.append(m2)

    wa_optin_link = ""
    if ag.plan == "pro":
        optin_text = f"ISCRIVIMI {ag.slug} + ACCETTO RICEVERE PROMO"
        wa_optin_link = f"https://wa.me/{WA_OPTIN_PHONE}?text={quote(optin_text)}"

    nfc_direct_url = f"{base}/{ag.slug}"
    if p_key:
        nfc_direct_url = f"{nfc_direct_url}?p={urllib.parse.quote(p_key)}"

    return render_template(
        "card.html",
        ag=ag_view,
        base_url=base,
        gallery=gallery,
        videos=videos,
        emails=emails,
        websites=websites,
        addresses=addresses,
        pdfs=pdfs,
        mobiles=mobiles,
        wa_optin_link=wa_optin_link,
        lang=lang,
        tfunc=lambda k: t(lang, k),
        profiles=profiles,
        active_profile=active_profile,
        p_key=p_key,
        nfc_direct_url=nfc_direct_url,
    )


# ===== VCARD =====
@app.get("/<slug>.vcf")
def vcard(slug):
    # vcf si riferisce sempre al profilo richiesto con ?p=
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")
    p_key = (request.args.get("p") or "").strip()
    active_profile = select_profile(profiles, p_key)

    ag_view = agent_to_view(ag)
    if active_profile:
        ag_view = apply_profile_to_view(ag_view, active_profile)

    full_name = ag_view.name or ""
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

    if ag_view.role:
        lines.append(f"TITLE:{ag_view.role}")
    if ag_view.company:
        lines.append(f"ORG:{ag_view.company}")

    if ag_view.phone_mobile:
        lines.append(f"TEL;TYPE=CELL:{ag_view.phone_mobile}")
    if ag_view.phone_mobile2:
        lines.append(f"TEL;TYPE=CELL:{ag_view.phone_mobile2}")
    if ag_view.phone_office:
        lines.append(f"TEL;TYPE=WORK:{ag_view.phone_office}")

    if ag_view.emails:
        for e in [x.strip() for x in ag_view.emails.split(",") if x.strip()]:
            lines.append(f"EMAIL;TYPE=WORK:{e}")

    base = get_base_url()
    card_url = f"{base}/{ag.slug}"
    if p_key:
        card_url = f"{card_url}?p={urllib.parse.quote(p_key)}"
    lines.append(f"URL:{card_url}")

    if ag_view.piva:
        lines.append(f"X-TAX-ID:{ag_view.piva}")
    if ag_view.sdi:
        lines.append(f"X-SDI-CODE:{ag_view.sdi}")

    lines.append("END:VCARD")
    content = "\r\n".join(lines)

    resp = Response(content, mimetype="text/vcard; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{ag.slug}.vcf"'
    return resp


# ===== QR CODE (multilingua + profilo) =====
@app.get("/<slug>/qr.png")
def qr(slug):
    base = get_base_url()
    p = (request.args.get("p") or "").strip()
    lang = (request.args.get("lang") or "").strip().lower()
    if lang not in SUPPORTED_LANGS:
        lang = ""

    url = f"{base}/{slug}"
    qs = []
    if p:
        qs.append("p=" + urllib.parse.quote(p))
    if lang:
        qs.append("lang=" + urllib.parse.quote(lang))
    if qs:
        url = url + "?" + "&".join(qs)

    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")


# ===== WhatsApp Webhook (lasciato, lo facciamo dopo) =====
@app.get("/wa/webhook")
def wa_webhook_verify():
    mode = request.args.get("hub.mode", "")
    token = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")

    if mode == "subscribe" and token == WA_VERIFY_TOKEN:
        return Response(challenge, status=200, mimetype="text/plain")
    return Response("forbidden", status=403, mimetype="text/plain")


@app.post("/wa/webhook")
def wa_webhook_receive():
    # lasciato invariato per ora
    return "ok", 200


# ===== ERRORI =====
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
