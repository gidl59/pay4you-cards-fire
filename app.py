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

# WhatsApp Cloud API
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "verify_token_change_me")
WA_TOKEN = os.getenv("WA_TOKEN", "")  # permanent access token
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")  # phone number id
WA_API_VERSION = os.getenv("WA_API_VERSION", "v20.0")

# ✅ Numero per link OPT-IN (WhatsApp web "wa.me/<numero>?text=...")
# Default: Pay4You +39 350 872 5353 -> "393508725353"
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

# ===== i18n MINIMO (IT+EN) =====
I18N = {
    "it": {
        "profile": "Profilo",
        "profile_1": "Profilo 1",
        "profile_2": "Profilo 2",
        "open_profile_2": "Apri Profilo 2",
        "open_profile_1": "Apri Profilo principale",
        "language": "Lingua",
        "save_contact": "Salva contatto",
        "share": "Condividi",
        "scan_qr": "Scansiona QR",
        "nfc_link": "Link NFC diretto",
        "close": "Chiudi",
    },
    "en": {
        "profile": "Profile",
        "profile_1": "Profile 1",
        "profile_2": "Profile 2",
        "open_profile_2": "Open Profile 2",
        "open_profile_1": "Open main profile",
        "language": "Language",
        "save_contact": "Save contact",
        "share": "Share",
        "scan_qr": "Scan QR",
        "nfc_link": "Direct NFC link",
        "close": "Close",
    }
}


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

    # ✅ Piano (basic/pro). Basic = solo card, Pro = WhatsApp promo + broadcast ecc.
    plan = Column(String, nullable=True)  # "basic" | "pro"

    # ✅ Multi-profile JSON (testo JSON)
    profiles_json = Column(Text, nullable=True)


class User(Base):
    """
    Utenti per login:
    - admin: username=admin, password=ADMIN_PASSWORD (creato automaticamente)
    - client: username=slug, password=generata, agent_slug=slug
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)                  # per ora in chiaro
    role = Column(String, nullable=False, default="client")    # admin | client
    agent_slug = Column(String, nullable=True)


class Subscriber(Base):
    """
    Iscritti WhatsApp per singola attività (merchant_slug).
    wa_id = numero utente senza + (es: 39333...)
    status = active | stopped
    """
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True)
    wa_id = Column(String, nullable=False)            # es "393333..."
    merchant_slug = Column(String, nullable=False)    # es "bar-jonni"
    status = Column(String, nullable=False, default="active")  # active/stopped
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
    """
    Imposta plan='basic' dove mancante/vuoto.
    (Così di default NON appare WhatsApp promo)
    """
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
    """
    ✅ Salva i file su disco persistente Render: /var/data/uploads/<folder>/...
    e restituisce un URL servito da /uploads/<folder>/<filename>
    """
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


# ✅ VALIDAZIONE NUMERO WHATSAPP (FORTE)
def normalize_wa_id_strict(raw: str):
    """
    Accetta:
      - "393401112233"
      - "+39 340 111 2233"
      - "3401112233"  -> diventa "393401112233"
    """
    t = (raw or "").strip()
    if not t:
        return "", ""  # vuoto = ok (non obbligatorio)

    t = t.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if t.startswith("+"):
        t = t[1:]
    if t.startswith("00"):
        t = t[2:]

    if not t.isdigit():
        return "", "Numero WhatsApp non valido: usa solo numeri (es: 393401112233)."

    if len(t) == 10 and t.startswith("3"):
        t = "39" + t

    if not t.startswith("39"):
        return "", "Numero WhatsApp non valido: usa formato italiano con prefisso 39 (es: 393401112233)."

    if len(t) != 12:
        return "", "Numero WhatsApp non valido: per Italia deve essere 12 cifre (39 + 10). Esempio: 393401112233."

    if not t[2:].startswith("3"):
        return "", "Numero WhatsApp non valido: sembra non essere un cellulare (deve iniziare con 3 dopo 39)."

    return t, ""


def extract_merchant_from_optin(text_body: str) -> str:
    t = (text_body or "").strip()
    t_up = t.upper()
    if "ISCRIVIMI" not in t_up:
        return ""

    after = re.split(r"\bISCRIVIMI\b", t, flags=re.IGNORECASE, maxsplit=1)[-1].strip()

    if "+" in after:
        after = after.split("+", 1)[0].strip()

    after = re.split(r"\bACCETTO\b", after, flags=re.IGNORECASE, maxsplit=1)[0].strip()

    return slugify(after)


def find_agent_slug_best_effort(db, guess_slug: str) -> str:
    if not guess_slug:
        return ""

    ag = db.query(Agent).filter_by(slug=guess_slug).first()
    if ag:
        return ag.slug

    agents = db.query(Agent).all()
    for a in agents:
        if slugify(a.name) == guess_slug:
            return a.slug
        if slugify(a.company or "") == guess_slug:
            return a.slug

    return ""


def normalize_plan(p: str) -> str:
    p = (p or "").strip().lower()
    return p if p in ("basic", "pro") else "basic"


def is_pro_agent(ag) -> bool:
    return normalize_plan(getattr(ag, "plan", "basic")) == "pro"


def sanitize_fields_for_plan(ag):
    return


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
# ✅ Ora supportiamo OVERRIDE COMPLETO (non solo 4 campi)
PROFILE_FIELDS = [
    "label_it", "label_en",
    "photo_url", "logo_url",
    "name", "company", "role", "bio",
    "phone_mobile", "phone_mobile2", "phone_office",
    "emails", "websites",
    "facebook", "instagram", "linkedin", "tiktok", "telegram",
    "whatsapp", "pec",
    "piva", "sdi", "addresses"
]

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

        key = (p.get("key") or "").strip() or f"p{i+1}"
        key = re.sub(r"[^a-zA-Z0-9_-]", "", key) or f"p{i+1}"

        item = {"key": key}
        for f in PROFILE_FIELDS:
            item[f] = (p.get(f) or "").strip()
        out.append(item)

    return out


def select_profile(profiles, requested_key: str):
    if not requested_key:
        return None
    for p in profiles:
        if p.get("key") == requested_key:
            return p
    return None


def upsert_profile(profiles, key: str, data: dict):
    key = (key or "").strip() or "p2"
    found = None
    for p in profiles:
        if p.get("key") == key:
            found = p
            break
    if not found:
        found = {"key": key}
        for f in PROFILE_FIELDS:
            found[f] = ""
        profiles.append(found)

    for f in PROFILE_FIELDS:
        if f in data:
            found[f] = (data.get(f) or "").strip()

    # label fallback
    if not found.get("label_it"):
        found["label_it"] = "Profilo 2" if key == "p2" else f"Profilo {key}"
    if not found.get("label_en"):
        found["label_en"] = "Profile 2" if key == "p2" else f"Profile {key}"

    return profiles


def profiles_to_json(profiles):
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

    # immagini
    if profile.get("photo_url"):
        view.photo_url = profile["photo_url"]
    if profile.get("logo_url"):
        view.extra_logo_url = profile["logo_url"]

    # testuali
    for k in [
        "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office",
        "emails", "websites",
        "facebook", "instagram", "linkedin", "tiktok", "telegram",
        "whatsapp", "pec",
        "piva", "sdi", "addresses"
    ]:
        if profile.get(k):
            setattr(view, k, profile[k])

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


def build_credentials_message(slug: str, username: str, password: str) -> str:
    base = get_base_url()
    login_url = f"{base}/login"
    card_url = f"{base}/{slug}"
    msg = (
        "✅ Credenziali Pay4You Card\n\n"
        f"Login: {login_url}\n"
        f"Username: {username}\n"
        f"Password: {password}\n\n"
        f"Card: {card_url}\n\n"
        "Consiglio: al primo accesso salva queste credenziali."
    )
    return msg


def send_credentials_to_client_wa_only(ag: Agent, user_obj: User, wa_raw: str = ""):
    wa_target, err = normalize_wa_id_strict(wa_raw or (getattr(ag, "phone_mobile", "") or ""))
    if err:
        return {"wa": (False, err)}

    if not wa_target:
        return {"wa": (False, "numero WhatsApp non presente")}

    body = build_credentials_message(ag.slug, user_obj.username, user_obj.password)
    ok, resp = wa_send_text(wa_target, body)
    return {"wa": (ok, resp)}


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


# ------------------ ADMIN LISTA ------------------
@app.get("/admin")
@admin_required
def admin_home():
    db = SessionLocal()
    agents = db.query(Agent).order_by(Agent.name).all()
    for a in agents:
        a.plan = normalize_plan(getattr(a, "plan", "basic"))
    return render_template("admin_list.html", agents=agents)


# ✅ CREAZIONE RAPIDA PRO + INVIO (WHATSAPP)
@app.post("/admin/quick-pro")
@admin_required
def admin_quick_pro_create():
    db = SessionLocal()

    slug = slugify(request.form.get("slug", ""))
    name = (request.form.get("name") or "").strip()
    wa_raw = (request.form.get("wa") or "").strip()
    email_raw = (request.form.get("email") or "").strip()

    if not slug:
        flash("Slug obbligatorio", "error")
        return redirect(url_for("admin_home"))

    if db.query(Agent).filter_by(slug=slug).first():
        flash("Slug già esistente", "error")
        return redirect(url_for("admin_home"))

    if not name:
        name = slug

    wa_norm, wa_err = normalize_wa_id_strict(wa_raw)
    if wa_err:
        flash(wa_err, "error")
        return redirect(url_for("admin_home"))

    ag = Agent(
        slug=slug,
        name=name,
        company=None,
        role=None,
        bio=None,
        phone_mobile=wa_norm or None,
        phone_mobile2=None,
        phone_office=None,
        emails=email_raw or None,
        websites=None,
        facebook=None,
        instagram=None,
        linkedin=None,
        tiktok=None,
        telegram=None,
        whatsapp=None,
        pec=None,
        piva=None,
        sdi=None,
        addresses=None,
        photo_url=None,
        extra_logo_url=None,
        gallery_urls=None,
        video_urls=None,
        pdf1_url=None,
        plan="pro",
        profiles_json=None,
    )

    sanitize_fields_for_plan(ag)

    db.add(ag)
    db.commit()

    pw = generate_password()
    u = User(username=slug, password=pw, role="client", agent_slug=slug)
    db.add(u)
    db.commit()

    results = send_credentials_to_client_wa_only(ag, u, wa_raw=wa_norm)
    wa_ok, wa_resp = results.get("wa") or (False, "")

    info = ["Cliente PRO creato ✅"]
    if wa_ok:
        info.append("WhatsApp inviato ✅")
    else:
        info.append(f"WhatsApp non inviato ({wa_resp})")

    if email_raw:
        info.append("Email: domani (SMTP)")

    flash(" — ".join(info), "ok" if wa_ok else "error")
    return redirect(url_for("admin_home"))


@app.post("/admin/<slug>/send-credentials")
@admin_required
def admin_send_credentials(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    if not is_pro_agent(ag):
        flash("Funzione disponibile solo per piano PRO.", "error")
        return redirect(url_for("admin_home"))

    u = db.query(User).filter_by(username=slug).first()
    if not u:
        u = User(username=slug, password=generate_password(), role="client", agent_slug=slug)
        db.add(u)
    else:
        u.password = generate_password()

    db.commit()

    results = send_credentials_to_client_wa_only(ag, u)
    wa_ok, wa_resp = results.get("wa") or (False, "")

    if wa_ok:
        flash("WhatsApp inviato ✅", "ok")
    else:
        flash(f"WhatsApp non inviato ({wa_resp})", "error")

    return redirect(url_for("admin_home"))


# ------------------ NUOVO AGENTE ------------------
@app.get("/admin/new")
@admin_required
def new_agent():
    return render_template("agent_form.html", agent=None, form_mode="main", profile_key="")


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


# ------------------ MODIFICA / ELIMINA (ADMIN) ------------------
@app.get("/admin/<slug>/edit")
@admin_required
def edit_agent(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)
    ag.plan = normalize_plan(getattr(ag, "plan", "basic"))
    return render_template("agent_form.html", agent=ag, form_mode="main", profile_key="")


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

    if request.form.get("delete_pdfs") == "1":
        ag.pdf1_url = None

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

    if request.form.get("delete_pdfs") != "1":
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
    return render_template("agent_form.html", agent=ag, form_mode="main", profile_key="")


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
    flash("Salvato ✅", "ok")
    return redirect(url_for("me_edit"))


# ------------------ AREA CLIENTE (Profilo 2 SEMPLICE) ------------------
@app.get("/me/profile2")
@login_required
def me_profile2():
    """
    Pagina uguale al profilo principale, ma salva in profiles_json dentro key=p2.
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
    p2 = select_profile(profiles, "p2")

    # se non esiste ancora, crea una bozza vuota per mostrare il form
    if not p2:
        profiles = upsert_profile(profiles, "p2", {
            "label_it": "Profilo 2",
            "label_en": "Profile 2"
        })
        p2 = select_profile(profiles, "p2")
        ag.profiles_json = profiles_to_json(profiles)
        db.commit()

    # Passo al template sia agent (profilo 1) che profile_data (p2)
    ag.plan = normalize_plan(getattr(ag, "plan", "basic"))
    return render_template("agent_form.html", agent=ag, form_mode="profile2", profile_key="p2", profile_data=p2)


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

    profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")

    # prendiamo TUTTI i campi come nel profilo 1
    data = {}
    for k in [
        "label_it", "label_en",
        "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office",
        "emails", "websites",
        "facebook", "instagram", "linkedin", "tiktok", "telegram",
        "whatsapp", "pec",
        "piva", "sdi", "addresses",
    ]:
        data[k] = (request.form.get(k, "") or "").strip()

    # upload foto/logo specifici del profilo 2
    photo = request.files.get("photo")
    extra_logo = request.files.get("extra_logo")
    if photo and photo.filename:
        u = upload_file(photo, "photos")
        if u:
            data["photo_url"] = u
    if extra_logo and extra_logo.filename:
        u = upload_file(extra_logo, "logos")
        if u:
            data["logo_url"] = u

    # NOTA: per semplicità p2 NON ha galleria/video/pdf separati (restano quelli del profilo principale)
    # se vuoi anche quelli separati, lo facciamo dopo.

    profiles = upsert_profile(profiles, "p2", data)
    ag.profiles_json = profiles_to_json(profiles)
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
    t = I18N.get(lang, I18N["it"])

    profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")
    p_key = (request.args.get("p") or "").strip()
    active_profile = select_profile(profiles, p_key)

    ag_view = agent_to_view(ag)
    if active_profile:
        ag_view = apply_profile_to_view(ag_view, active_profile)

    gallery = (ag.gallery_urls.split("|") if ag.gallery_urls else [])
    videos = (ag.video_urls.split("|") if ag.video_urls else [])

    emails = [e.strip() for e in (ag_view.emails or "").split(",") if e.strip()]
    websites = [w.strip() for w in (ag_view.websites or "").split(",") if w.strip()]
    addresses = [a.strip() for a in (ag_view.addresses or "").split("\n") if a.strip()]

    pdfs = parse_pdfs(ag.pdf1_url or "")
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

    # ✅ Link NFC diretto (include p + lang)
    nfc_direct_url = f"{base}/{ag.slug}"
    qs = []
    if p_key:
        qs.append("p=" + urllib.parse.quote(p_key))
    if lang:
        qs.append("lang=" + urllib.parse.quote(lang))
    if qs:
        nfc_direct_url = nfc_direct_url + "?" + "&".join(qs)

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
        t=t,
        profiles=profiles,
        active_profile=active_profile,
        p_key=p_key,
        nfc_direct_url=nfc_direct_url,
    )


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


# ------------------ QR CODE (multilingua + profilo) ------------------
@app.get("/<slug>/qr.png")
def qr(slug):
    base = get_base_url()
    p = (request.args.get("p") or "").strip()
    lang = (request.args.get("lang") or "").strip().lower()
    if lang and lang not in SUPPORTED_LANGS:
        lang = "it"

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


# ------------------ WhatsApp Webhook ------------------
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
    data = request.get_json(silent=True) or {}

    try:
        entry = data.get("entry", []) or []
        for e in entry:
            changes = (e.get("changes", []) or [])
            for c in changes:
                value = (c.get("value", {}) or {})
                messages = (value.get("messages", []) or [])
                for m in messages:
                    wa_id = (m.get("from") or "").strip()
                    text_obj = m.get("text") or {}
                    body = (text_obj.get("body") or "").strip()

                    if not wa_id or not body:
                        continue

                    db = SessionLocal()

                    if re.search(r"\bSTOP\b", body, flags=re.IGNORECASE):
                        subs = db.query(Subscriber).filter_by(wa_id=wa_id, status="active").all()
                        for s in subs:
                            s.status = "stopped"
                            s.updated_at = now_iso()
                            s.last_text = body
                        db.commit()

                        wa_send_text(wa_id, "✅ Ok, iscrizione disattivata. Se vuoi riattivare: scrivi ISCRIVIMI <attività> + ACCETTO RICEVERE PROMO.")
                        continue

                    if re.search(r"\bISCRIVIMI\b", body, flags=re.IGNORECASE):
                        guess = extract_merchant_from_optin(body)
                        merchant_slug = find_agent_slug_best_effort(db, guess)

                        if not merchant_slug:
                            wa_send_text(wa_id, "⚠️ Non ho capito quale attività. Scrivi: ISCRIVIMI NOME-ATTIVITÀ + ACCETTO RICEVERE PROMO")
                            continue

                        ag = db.query(Agent).filter_by(slug=merchant_slug).first()
                        if not ag or not is_pro_agent(ag):
                            wa_send_text(wa_id, "⚠️ Questo servizio non è attivo per questa card.")
                            continue

                        sub = db.query(Subscriber).filter_by(wa_id=wa_id, merchant_slug=merchant_slug).first()
                        if not sub:
                            sub = Subscriber(
                                wa_id=wa_id,
                                merchant_slug=merchant_slug,
                                status="active",
                                created_at=now_iso(),
                                updated_at=now_iso(),
                                last_text=body
                            )
                            db.add(sub)
                        else:
                            sub.status = "active"
                            sub.updated_at = now_iso()
                            sub.last_text = body
                        db.commit()

                        wa_send_text(wa_id, f"✅ Iscrizione confermata per {merchant_slug}. Per annullare: scrivi STOP.")
                        continue

                    wa_send_text(wa_id, "Ciao! Per iscriverti alle novità scrivi: ISCRIVIMI <attività> + ACCETTO RICEVERE PROMO. Per annullare: STOP.")

    except Exception:
        pass

    return "ok", 200


# ------------------ ERRORI ------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
