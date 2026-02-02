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
    send_from_directory, flash, make_response
)
from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    text as sa_text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import qrcode
import urllib.parse

try:
    import requests
except Exception:
    requests = None

load_dotenv()

# ===== ENV / CONFIG =====
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")

# WhatsApp Cloud API
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "verify_token_change_me")
WA_TOKEN = os.getenv("WA_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_API_VERSION = os.getenv("WA_API_VERSION", "v20.0")

WA_OPTIN_PHONE = os.getenv("WA_OPTIN_PHONE", "393508725353").strip().replace("+", "").replace(" ", "")

PERSIST_UPLOADS_DIR = os.getenv("PERSIST_UPLOADS_DIR", "/var/data/uploads")

app = Flask(__name__)
app.secret_key = APP_SECRET
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB

DB_URL = "sqlite:////var/data/data.db"
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

MAX_GALLERY_IMAGES = 30
MAX_VIDEOS = 10

SUPPORTED_LANGS = ("it", "en")  # ✅ IT+EN per ora


# =========================
# ✅ TRANSLATIONS (IT/EN)
# =========================
I18N = {
    "it": {
        "save_contact": "Salva contatto",
        "scan_qr": "Scansiona QR",
        "nfc_direct": "Link NFC diretto",
        "how_it_works": "Come funziona",
        "tap_nfc": "1) Tocco (NFC)",
        "tap_nfc_desc": "Appoggia la card sul telefono: si apre il profilo automaticamente.",
        "qr_desc": "Scansiona il QR: funziona sempre, anche senza NFC.",
        "link_desc": "Condividi il profilo via WhatsApp, email o social.",
        "contacts": "Contatti",
        "phones": "Telefoni",
        "office_phone": "Ufficio",
        "mobile_phone": "Cellulare",
        "whatsapp": "WhatsApp",
        "email": "Email",
        "website": "Sito",
        "social": "Social",
        "address": "Indirizzi",
        "docs": "Documenti",
        "gallery": "Galleria",
        "videos": "Video",
        "close": "Chiudi",
        "open_qr": "Apri QR",
        "download_vcard": "Scarica contatto (vCard)",
        "language": "Lingua",
        "profile": "Profilo",
        "profile_main": "Profilo principale",
        "profile_2": "Profilo 2",
        "no_app": "Nessuna app richiesta",
        "updated": "Aggiornabile in tempo reale",
        "compat": "Compatibile Apple & Android",
        "promo_box_title": "Pubblicità WhatsApp (solo PRO)",
        "promo_box_desc": "Da qui invii promozioni ai tuoi clienti iscritti (solo tu).",
    },
    "en": {
        "save_contact": "Save contact",
        "scan_qr": "Scan QR",
        "nfc_direct": "Direct NFC link",
        "how_it_works": "How it works",
        "tap_nfc": "1) Tap (NFC)",
        "tap_nfc_desc": "Tap the card on the phone: the profile opens automatically.",
        "qr_desc": "Scan the QR: it works even without NFC.",
        "link_desc": "Share the profile via WhatsApp, email or social.",
        "contacts": "Contacts",
        "phones": "Phones",
        "office_phone": "Office",
        "mobile_phone": "Mobile",
        "whatsapp": "WhatsApp",
        "email": "Email",
        "website": "Website",
        "social": "Social",
        "address": "Addresses",
        "docs": "Documents",
        "gallery": "Gallery",
        "videos": "Videos",
        "close": "Close",
        "open_qr": "Open QR",
        "download_vcard": "Download contact (vCard)",
        "language": "Language",
        "profile": "Profile",
        "profile_main": "Main profile",
        "profile_2": "Profile 2",
        "no_app": "No app required",
        "updated": "Real-time updates",
        "compat": "Works on Apple & Android",
        "promo_box_title": "WhatsApp Ads (PRO only)",
        "promo_box_desc": "From here you send promotions to your subscribed customers (only you).",
    }
}

def tr(lang: str, key: str) -> str:
    lang = (lang or "it").split("-", 1)[0].lower()
    if lang not in SUPPORTED_LANGS:
        lang = "it"
    return I18N.get(lang, I18N["it"]).get(key, I18N["it"].get(key, key))


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

    plan = Column(String, nullable=True)  # "basic" | "pro"
    profiles_json = Column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="client")
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
ensure_sqlite_column("agents", "phone_office", "TEXT")
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


# ===== LINGUA =====
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


# ===== MULTI-PROFILI (JSON) =====
def parse_profiles_json(raw: str):
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

        key = (p.get("key") or "").strip()
        if not key:
            key = f"p{i+1}"

        key = re.sub(r"[^a-zA-Z0-9_-]", "", key) or f"p{i+1}"

        out.append({
            "key": key,
            "label_it": (p.get("label_it") or p.get("label") or f"Profilo {i+1}").strip(),
            "label_en": (p.get("label_en") or p.get("label") or f"Profile {i+1}").strip(),
            "photo_url": (p.get("photo_url") or "").strip(),
            "logo_url": (p.get("logo_url") or p.get("extra_logo_url") or "").strip(),
            "name": (p.get("name") or "").strip(),
            "role": (p.get("role") or "").strip(),
            "company": (p.get("company") or "").strip(),
            "bio": (p.get("bio") or "").strip(),
        })

    return out


def select_profile(profiles, requested_key: str):
    if not requested_key:
        return None
    for p in profiles:
        if p.get("key") == requested_key:
            return p
    return None


def upsert_profile(raw_json: str, profile_key: str, payload: dict) -> str:
    """
    Inserisce o aggiorna un profilo in profiles_json.
    Ritorna JSON string (list).
    """
    profiles = parse_profiles_json(raw_json or "")
    found = False
    for p in profiles:
        if p.get("key") == profile_key:
            p.update(payload)
            found = True
            break
    if not found:
        newp = {"key": profile_key}
        newp.update(payload)
        profiles.append(newp)
    return json.dumps(profiles, ensure_ascii=False, indent=2)


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
    if not profile:
        return view

    if profile.get("photo_url"):
        view.photo_url = profile["photo_url"]
    if profile.get("logo_url"):
        view.extra_logo_url = profile["logo_url"]
    if profile.get("name"):
        view.name = profile["name"]
    if profile.get("role"):
        view.role = profile["role"]
    if profile.get("company"):
        view.company = profile["company"]
    if profile.get("bio"):
        view.bio = profile["bio"]

    return view


# ===== WhatsApp Cloud API helpers =====
def wa_api_url(path: str) -> str:
    return f"https://graph.facebook.com/{WA_API_VERSION}/{path.lstrip('/')}"

def wa_send_text(to_wa_id: str, body: str) -> (bool, str):
    if not WA_TOKEN or not WA_PHONE_NUMBER_ID:
        return False, "WA_TOKEN o WA_PHONE_NUMBER_ID mancanti"

    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": body}
    }

    try:
        if requests:
            r = requests.post(
                wa_api_url(f"{WA_PHONE_NUMBER_ID}/messages"),
                headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=20
            )
            ok = 200 <= r.status_code < 300
            return ok, r.text
        else:
            import urllib.request
            req = urllib.request.Request(
                wa_api_url(f"{WA_PHONE_NUMBER_ID}/messages"),
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                return True, resp.read().decode("utf-8")
    except Exception as e:
        return False, str(e)


# ------------------ ROUTES BASE ------------------
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


# ------------------ LOGIN ------------------
@app.get("/login")
def login():
    lang = pick_lang_from_request()
    return render_template("login.html", error=None, next=request.args.get("next", ""), lang=lang)

@app.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()

    lang = pick_lang_from_request()

    if not username or not password:
        return render_template("login.html", error="Inserisci username e password", next="", lang=lang)

    if username == "admin" and password == ADMIN_PASSWORD:
        session["username"] = "admin"
        session["role"] = "admin"
        session["agent_slug"] = None
        return redirect(url_for("admin_home"))

    db = SessionLocal()
    u = db.query(User).filter_by(username=username, password=password).first()
    if not u:
        return render_template("login.html", error="Credenziali errate", next="", lang=lang)

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


# ------------------ ADMIN LISTA ------------------
@app.get("/admin")
@admin_required
def admin_home():
    db = SessionLocal()
    agents = db.query(Agent).order_by(Agent.name).all()
    for a in agents:
        a.plan = normalize_plan(getattr(a, "plan", "basic"))
    lang = pick_lang_from_request()
    return render_template("admin_list.html", agents=agents, lang=lang)


# ------------------ AREA CLIENTE (Profilo 1) ------------------
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
    lang = pick_lang_from_request()
    return render_template("agent_form.html", agent=ag, lang=lang)


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
        "whatsapp",
        "pec",
        "piva", "sdi", "addresses",
    ]

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
    flash("Salvato ✅", "ok")
    return redirect(url_for("me_edit"))


# ------------------ ✅ AREA CLIENTE (Profilo 2 SEMPLICE) ------------------
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
    if not ag:
        abort(404)

    lang = pick_lang_from_request()

    profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")
    p2 = select_profile(profiles, "p2") or {
        "key": "p2",
        "label_it": "Profilo 2",
        "label_en": "Profile 2",
        "photo_url": "",
        "logo_url": "",
        "name": "",
        "role": "",
        "company": "",
        "bio": "",
    }

    return render_template("profile2_form.html", agent=ag, p2=p2, lang=lang)


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
        abort(404)

    # campi “semplici” profilo 2
    payload = {
        "key": "p2",
        "label_it": (request.form.get("label_it") or "Profilo 2").strip(),
        "label_en": (request.form.get("label_en") or "Profile 2").strip(),
        "name": (request.form.get("name") or "").strip(),
        "company": (request.form.get("company") or "").strip(),
        "role": (request.form.get("role") or "").strip(),
        "bio": (request.form.get("bio") or "").strip(),
    }

    # upload foto/logo profilo 2 (salviamo URL nel JSON)
    photo = request.files.get("photo")
    logo = request.files.get("logo")

    if photo and photo.filename:
        u = upload_file(photo, "photos")
        if u:
            payload["photo_url"] = u

    if logo and logo.filename:
        u = upload_file(logo, "logos")
        if u:
            payload["logo_url"] = u

    ag.profiles_json = upsert_profile(getattr(ag, "profiles_json", "") or "", "p2", payload)
    db.commit()

    flash("Profilo 2 salvato ✅", "ok")
    return redirect(url_for("me_profile2"))


# ------------------ CARD PUBBLICA ------------------
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

    gallery = (ag.gallery_urls.split("|") if ag.gallery_urls else [])
    videos = (ag.video_urls.split("|") if ag.video_urls else [])

    emails = [e.strip() for e in (ag.emails or "").split(",") if e.strip()]
    websites = [w.strip() for w in (ag.websites or "").split(",") if w.strip()]
    addresses = [a.strip() for a in (ag.addresses or "").split("\n") if a.strip()]

    pdfs = parse_pdfs(ag.pdf1_url or "")
    base = get_base_url()

    mobiles = []
    if ag.phone_mobile:
        mobiles.append(ag.phone_mobile.strip())
    if ag.phone_mobile2:
        m2 = ag.phone_mobile2.strip()
        if m2:
            mobiles.append(m2)

    # ✅ Per PRO: link opt-in (questo serve ai clienti finali per iscriversi)
    wa_optin_link = ""
    if ag.plan == "pro":
        optin_text = f"ISCRIVIMI {ag.slug} + ACCETTO RICEVERE PROMO"
        wa_optin_link = f"https://wa.me/{WA_OPTIN_PHONE}?text={quote(optin_text)}"

    # ✅ Link NFC diretto (profilo)
    nfc_direct_url = f"{base}/{ag.slug}"
    if p_key:
        nfc_direct_url = f"{nfc_direct_url}?p={urllib.parse.quote(p_key)}"

    # ✅ response con header anti-cache + Vary lingua
    html = render_template(
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
        profiles=profiles,
        active_profile=active_profile,
        p_key=p_key,
        nfc_direct_url=nfc_direct_url,
        t=lambda k: tr(lang, k),
        plan=ag.plan,
        office_phone=(ag.phone_office or "").strip(),
    )
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["Vary"] = "Accept-Language"
    return resp


# ------------------ VCARD ------------------
@app.get("/<slug>.vcf")
def vcard(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
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


# ------------------ QR CODE ------------------
@app.get("/<slug>/qr.png")
def qr(slug):
    base = get_base_url()
    p = (request.args.get("p") or "").strip()
    lang = (request.args.get("lang") or "").strip()
    if p:
        url = f"{base}/{slug}?p={urllib.parse.quote(p)}"
    else:
        url = f"{base}/{slug}"
    if lang:
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}lang={urllib.parse.quote(lang)}"

    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")


# ------------------ ERRORI ------------------
@app.errorhandler(404)
def not_found(e):
    lang = pick_lang_from_request()
    return render_template("404.html", lang=lang), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
