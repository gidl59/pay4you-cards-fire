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

# ✅ SMTP (per invio email credenziali)
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER).strip()

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

SUPPORTED_LANGS = ("it", "en", "es", "fr", "de")


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


def extract_merchant_from_optin(text_body: str) -> str:
    """
    Accetta:
      "ISCRIVIMI bar jonni + accetto ricevere promo"
      "iscrivimi BAR-JONNI"
    Ritorna uno slug tipo "bar-jonni"
    """
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
    """
    Se guess_slug corrisponde a uno slug esistente → ok.
    Se no, prova match sul nome agente slugificato.
    """
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
    """
    IMPORTANTISSIMO:
    - Non cancelliamo dati dal DB automaticamente.
    """
    return


# ===== LINGUA =====
def pick_lang_from_request() -> str:
    # 1) querystring ?lang=
    q = (request.args.get("lang") or "").strip().lower()
    if q:
        q = q.split("-", 1)[0]
        return q if q in SUPPORTED_LANGS else "it"

    # 2) header Accept-Language
    al = (request.headers.get("Accept-Language") or "").lower()
    if al:
        first = al.split(",", 1)[0].strip().split("-", 1)[0]
        if first in SUPPORTED_LANGS:
            return first

    return "it"


# ===== MULTI-PROFILI (JSON) =====
def parse_profiles_json(raw: str):
    """
    Ritorna una lista di profili normalizzati:
    [
      {"key":"p1","label":"...","photo_url":"...","logo_url":"...","name":"...","role":"...","company":"...","bio":"..."}
    ]
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

        key = (p.get("key") or "").strip()
        if not key:
            key = f"p{i+1}"

        key = re.sub(r"[^a-zA-Z0-9_-]", "", key) or f"p{i+1}"

        out.append({
            "key": key,
            "label": (p.get("label") or p.get("name") or f"Profilo {i+1}").strip(),
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


def agent_to_view(ag: Agent):
    """
    Crea una copia "view" (SimpleNamespace) dell'agente,
    così possiamo fare override senza modificare l'oggetto SQLAlchemy.
    """
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
    Override SOLO per: foto/logo + eventuali testi.
    """
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


# ===== EMAIL SMTP helpers =====
def send_email_smtp(to_email: str, subject: str, body: str) -> (bool, str):
    """
    Invia email semplice via SMTP.
    Richiede: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
    """
    to_email = (to_email or "").strip()
    if not to_email:
        return False, "Email vuota"

    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS or not SMTP_FROM:
        return False, "SMTP non configurato (ENV mancanti)"

    try:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.ehlo()
            try:
                s.starttls()
            except Exception:
                pass
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)

        return True, "ok"
    except Exception as e:
        return False, str(e)


def normalize_wa_id(raw: str) -> str:
    """
    Accetta:
      "+39 340 111 2233"
      "3401112233"
      "393401112233"
    Ritorna "393401112233" (solo numeri).
    Se non riesce → "".
    """
    t = (raw or "").strip()
    if not t:
        return ""

    t = t.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    t = t.replace("+", "")

    # se inizia con 00 -> togli
    if t.startswith("00"):
        t = t[2:]

    # se è italiano senza prefisso e lungo 10 -> aggiungi 39
    if t.isdigit() and len(t) == 10 and t.startswith("3"):
        t = "39" + t

    if not t.isdigit():
        return ""
    if len(t) < 8:
        return ""

    return t


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


def send_credentials_to_client(ag: Agent, user_obj: User, wa_raw: str = "", email_raw: str = ""):
    """
    Invia credenziali via WhatsApp e/o Email.
    - Se wa_raw è vuoto: prova agent.phone_mobile
    - Se email_raw è vuoto: prova prima email in agent.emails
    """
    results = {"wa": None, "email": None}

    # WhatsApp
    wa_target = normalize_wa_id(wa_raw) or normalize_wa_id(getattr(ag, "phone_mobile", "") or "")
    if wa_target:
        body = build_credentials_message(ag.slug, user_obj.username, user_obj.password)
        ok, resp = wa_send_text(wa_target, body)
        results["wa"] = (ok, resp)
    else:
        results["wa"] = (False, "numero WhatsApp non presente")

    # Email
    email_target = (email_raw or "").strip()
    if not email_target:
        # prende la prima email dall'agente
        emails = [e.strip() for e in (getattr(ag, "emails", "") or "").split(",") if e.strip()]
        if emails:
            email_target = emails[0]

    if email_target:
        subject = "Credenziali Pay4You Card"
        body = build_credentials_message(ag.slug, user_obj.username, user_obj.password)
        ok, resp = send_email_smtp(email_target, subject, body)
        results["email"] = (ok, resp)
    else:
        results["email"] = (False, "email non presente")

    return results


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

    # admin
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


# ✅ CREAZIONE RAPIDA PRO + INVIO CREDENZIALI
@app.post("/admin/quick-pro")
@admin_required
def admin_quick_pro_create():
    db = SessionLocal()

    slug = slugify(request.form.get("slug", ""))
    name = (request.form.get("name") or "").strip()
    wa = (request.form.get("wa") or "").strip()
    email = (request.form.get("email") or "").strip()

    if not slug:
        flash("Slug obbligatorio", "error")
        return redirect(url_for("admin_home"))

    if db.query(Agent).filter_by(slug=slug).first():
        flash("Slug già esistente", "error")
        return redirect(url_for("admin_home"))

    if not name:
        name = slug

    # ✅ crea agente PRO minimale
    ag = Agent(
        slug=slug,
        name=name,
        company=None,
        role=None,
        bio=None,
        phone_mobile=wa or None,   # salvo qui così poi posso inviare e ritrovarlo
        phone_mobile2=None,
        phone_office=None,
        emails=email or None,
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

    # ✅ crea utente (username=slug) + password
    pw = generate_password()
    u = User(username=slug, password=pw, role="client", agent_slug=slug)
    db.add(u)
    db.commit()

    # ✅ invia credenziali
    results = send_credentials_to_client(ag, u, wa_raw=wa, email_raw=email)

    wa_ok, wa_resp = results.get("wa") or (False, "")
    em_ok, em_resp = results.get("email") or (False, "")

    info = []
    info.append("Cliente PRO creato ✅")
    if wa_ok:
        info.append("WhatsApp inviato ✅")
    else:
        info.append(f"WhatsApp non inviato ({wa_resp})")

    if em_ok:
        info.append("Email inviata ✅")
    else:
        info.append(f"Email non inviata ({em_resp})")

    flash(" — ".join(info), "ok")
    return redirect(url_for("admin_home"))


# ✅ REINVIO CREDENZIALI (rigenera password e invia)
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
        # se per qualche motivo manca user, lo creo
        u = User(username=slug, password=generate_password(), role="client", agent_slug=slug)
        db.add(u)
    else:
        u.password = generate_password()

    db.commit()

    results = send_credentials_to_client(ag, u)

    wa_ok, wa_resp = results.get("wa") or (False, "")
    em_ok, em_resp = results.get("email") or (False, "")

    info = []
    if wa_ok:
        info.append("WhatsApp inviato ✅")
    else:
        info.append(f"WhatsApp non inviato ({wa_resp})")

    if em_ok:
        info.append("Email inviata ✅")
    else:
        info.append(f"Email non inviata ({em_resp})")

    flash(" — ".join(info), "ok" if (wa_ok or em_ok) else "error")
    return redirect(url_for("admin_home"))


# ✅ EXPORT JSON (backup “salvo in file json”)
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
            "extra_logo_url": a.extra_logo_url,
            "gallery_urls": a.gallery_urls,
            "video_urls": a.video_urls,
            "pdf1_url": a.pdf1_url,
            "plan": normalize_plan(getattr(a, "plan", "basic")),
            "profiles_json": a.profiles_json,
        })

    content = json.dumps(payload, ensure_ascii=False, indent=2)
    resp = Response(content, mimetype="application/json; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="agents-export.json"'
    return resp


# ------------------ CREDENZIALI CLIENTE (RESET + COPIA) ------------------
@app.get("/admin/<slug>/credentials")
@admin_required
def admin_credentials(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    # ✅ solo PRO genera credenziali (paywall)
    if not is_pro_agent(ag):
        return "Funzione disponibile solo per piano PRO.", 403

    u = db.query(User).filter_by(username=slug).first()
    if not u:
        u = User(username=slug, password=generate_password(), role="client", agent_slug=slug)
        db.add(u)
    else:
        u.password = generate_password()

    db.commit()

    return f"""
    <!doctype html>
    <html lang="it">
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width, initial-scale=1"/>
      <title>Credenziali - {slug}</title>
      <style>
        body{{font-family:Arial,sans-serif;background:#0b1220;color:#e5e7eb;padding:24px}}
        .box{{max-width:560px;margin:auto;background:#0f172a;border:1px solid #1f2937;border-radius:14px;padding:18px}}
        h2{{margin:0 0 12px 0}}
        .row{{display:flex;gap:10px;align-items:center;margin:10px 0;flex-wrap:wrap}}
        code{{background:#111827;padding:8px 10px;border-radius:10px;border:1px solid #1f2937}}
        button,a{{background:#2563eb;color:white;border:none;padding:10px 12px;border-radius:10px;cursor:pointer;text-decoration:none}}
        button.secondary,a.secondary{{background:#334155}}
        .small{{color:#94a3b8;font-size:12px;margin-top:10px}}
      </style>
    </head>
    <body>
      <div class="box">
        <h2>Credenziali cliente</h2>
        <div class="small">Card: <b>{slug}</b></div>

        <div class="row">
          <div style="min-width:90px;">Username</div>
          <code>{u.username}</code>
          <button onclick="copyText('{u.username}')">Copia</button>
        </div>

        <div class="row">
          <div style="min-width:90px;">Password</div>
          <code>{u.password}</code>
          <button onclick="copyText('{u.password}')">Copia</button>
        </div>

        <div class="row" style="margin-top:14px;">
          <a class="secondary" href="/login" target="_blank">Apri login</a>
          <a class="secondary" href="/{slug}" target="_blank">Apri card</a>
          <a class="secondary" href="{url_for('admin_home')}">⬅ Torna alla lista</a>
        </div>

        <form method="post" action="/admin/{slug}/send-credentials" style="margin-top:14px;">
          <button type="submit">📨 Rigenera e invia credenziali</button>
        </form>

        <p class="small">Nota: aprendo questa pagina rigeneri la password (reset).</p>
      </div>

      <script>
        function copyText(t){{
          if(navigator.clipboard) {{
            navigator.clipboard.writeText(t).then(()=>alert("Copiato: " + t));
          }} else {{
            window.prompt("Copia:", t);
          }}
        }}
      </script>
    </body>
    </html>
    """


# ------------------ ADMIN BROADCAST (INVIO PROMO) ------------------
@app.get("/admin/<slug>/broadcast")
@admin_required
def admin_broadcast(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    if not is_pro_agent(ag):
        return "Funzione disponibile solo per piano PRO.", 403

    subs_count = db.query(Subscriber).filter_by(merchant_slug=slug, status="active").count()
    return render_template("admin_broadcast.html", agent=ag, subs_count=subs_count)


@app.post("/admin/<slug>/broadcast")
@admin_required
def admin_broadcast_post(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    if not is_pro_agent(ag):
        return "Funzione disponibile solo per piano PRO.", 403

    message = (request.form.get("message") or "").strip()
    if not message:
        flash("Scrivi un messaggio", "error")
        subs_count = db.query(Subscriber).filter_by(merchant_slug=slug, status="active").count()
        return render_template("admin_broadcast.html", agent=ag, subs_count=subs_count)

    subs = db.query(Subscriber).filter_by(merchant_slug=slug, status="active").all()

    sent = 0
    failed = 0
    for s in subs:
        ok, _resp = wa_send_text(s.wa_id, message)
        if ok:
            sent += 1
        else:
            failed += 1

    flash(f"Inviati: {sent} — Errori: {failed}.", "ok")
    return redirect(url_for("admin_broadcast", slug=slug))


# ------------------ NUOVO AGENTE ------------------
@app.get("/admin/new")
@admin_required
def new_agent():
    return render_template("agent_form.html", agent=None)


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

    # ✅ valida JSON profili (se inserito)
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

    # PDF 1–12
    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    pdf_joined = "|".join(pdf_entries) if pdf_entries else None

    # gallery
    gallery_urls = []
    for f in gallery_files[:MAX_GALLERY_IMAGES]:
        if f and f.filename:
            u = upload_file(f, "gallery")
            if u:
                gallery_urls.append(u)

    # videos
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

    # crea utente cliente (username = slug)
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
    return render_template("agent_form.html", agent=ag)


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


# ------------------ AREA CLIENTE: MODIFICA SOLO LA PROPRIA CARD ------------------
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
    return render_template("agent_form.html", agent=ag)


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
    return redirect(url_for("me_edit"))


# ------------------ CARD PUBBLICA ------------------
@app.get("/<slug>")
def public_card(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    ag.plan = normalize_plan(getattr(ag, "plan", "basic"))

    # ✅ lingua
    lang = pick_lang_from_request()

    # ✅ multi-profili
    profiles = parse_profiles_json(getattr(ag, "profiles_json", "") or "")
    p_key = (request.args.get("p") or "").strip()  # <-- questa è la chiave che userà il template
    active_profile = select_profile(profiles, p_key)

    # ✅ copia “view” e override (NON tocca oggetto DB)
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

    # ✅ link opt-in WhatsApp SOLO per piano PRO
    wa_optin_link = ""
    if ag.plan == "pro":
        optin_text = f"ISCRIVIMI {ag.slug} + ACCETTO RICEVERE PROMO"
        wa_optin_link = f"https://wa.me/{WA_OPTIN_PHONE}?text={quote(optin_text)}"

    # ✅ URL “NFC direct” (profilo se presente) + mantiene lingua se vuoi
    nfc_direct_url = f"{base}/{ag.slug}"
    if p_key:
        nfc_direct_url = f"{nfc_direct_url}?p={urllib.parse.quote(p_key)}"
        # se vuoi includere lang anche su NFC direct:
        # nfc_direct_url += f"&lang={urllib.parse.quote(lang)}"

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

        # ✅ MULTI-LINGUA
        lang=lang,

        # ✅ MULTI-PROFILI per schermata scelta
        profiles=profiles,
        active_profile=active_profile,
        p_key=p_key,                 # <-- fondamentale per la “scelta profilo”
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


# ------------------ QR CODE ------------------
@app.get("/<slug>/qr.png")
def qr(slug):
    base = get_base_url()

    # ✅ se passi ?p=p1 il QR punta al profilo (NFC direct)
    p = (request.args.get("p") or "").strip()
    if p:
        url = f"{base}/{slug}?p={urllib.parse.quote(p)}"
    else:
        url = f"{base}/{slug}"

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
