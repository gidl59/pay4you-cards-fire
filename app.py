import os
import re
import uuid
import json
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import quote

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

try:
    import requests
except Exception:
    requests = None

load_dotenv()

# ===== ENV / CONFIG =====
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")

# WhatsApp Cloud API (poi lo rifiniamo)
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

SUPPORTED_LANGS = ("it", "en")

# ===== TRADUZIONI (IT/EN) =====
I18N = {
    "it": {
        "save_contact": "Salva contatto",
        "scan_qr": "Scansiona QR",
        "direct_nfc": "Link NFC diretto",
        "actions": "Azioni",
        "contacts": "Contatti",
        "addresses": "Indirizzi",
        "documents": "Documenti",
        "gallery": "Galleria",
        "videos": "Video",
        "close": "Chiudi",
        "open": "Apri",
        "phone_mobile": "Cellulare",
        "phone_office": "Telefono ufficio",
        "whatsapp": "WhatsApp",
        "email": "Email",
        "website": "Sito web",
        "pec": "PEC",
        "piva": "Partita IVA",
        "sdi": "SDI",
        "social": "Social",
        "facebook": "Facebook",
        "instagram": "Instagram",
        "linkedin": "LinkedIn",
        "tiktok": "TikTok",
        "telegram": "Telegram",
        "subscribe_title": "Promozioni su WhatsApp",
        "subscribe_desc": "Se sei un cliente, puoi iscriverti alle promozioni inviando il messaggio su WhatsApp.",
        "subscribe_btn": "Iscriviti (clienti)",
        "profile": "Profilo",
        "profile2": "Profilo 2",
        "lang": "Lingua",
    },
    "en": {
        "save_contact": "Save contact",
        "scan_qr": "Scan QR",
        "direct_nfc": "Direct NFC link",
        "actions": "Actions",
        "contacts": "Contacts",
        "addresses": "Addresses",
        "documents": "Documents",
        "gallery": "Gallery",
        "videos": "Videos",
        "close": "Close",
        "open": "Open",
        "phone_mobile": "Mobile",
        "phone_office": "Office phone",
        "whatsapp": "WhatsApp",
        "email": "Email",
        "website": "Website",
        "pec": "PEC",
        "piva": "VAT",
        "sdi": "SDI",
        "social": "Social",
        "facebook": "Facebook",
        "instagram": "Instagram",
        "linkedin": "LinkedIn",
        "tiktok": "TikTok",
        "telegram": "Telegram",
        "subscribe_title": "WhatsApp Promotions",
        "subscribe_desc": "If you are a customer, you can subscribe by sending the message on WhatsApp.",
        "subscribe_btn": "Subscribe (customers)",
        "profile": "Profile",
        "profile2": "Profile 2",
        "lang": "Language",
    }
}

def t(lang: str, key: str) -> str:
    lang = (lang or "it").lower()
    if lang not in SUPPORTED_LANGS:
        lang = "it"
    return I18N.get(lang, I18N["it"]).get(key, key)


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

    plan = Column(String, nullable=True)  # basic|pro
    profiles_json = Column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)  # (per ora semplice)
    role = Column(String, nullable=False, default="client")  # admin|client
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


# ===== MICRO-MIGRAZIONI (safe) =====
def ensure_sqlite_column(table: str, column: str, coltype: str):
    with engine.connect() as conn:
        rows = conn.execute(sa_text(f"PRAGMA table_info({table})")).fetchall()
        existing = {r[1] for r in rows}
        if column not in existing:
            conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            conn.commit()

ensure_sqlite_column("agents", "phone_mobile2", "TEXT")
ensure_sqlite_column("agents", "phone_office", "TEXT")
ensure_sqlite_column("agents", "plan", "TEXT")
ensure_sqlite_column("agents", "profiles_json", "TEXT")
ensure_sqlite_column("agents", "video_urls", "TEXT")

ensure_sqlite_column("subscribers", "status", "TEXT")
ensure_sqlite_column("subscribers", "created_at", "TEXT")
ensure_sqlite_column("subscribers", "updated_at", "TEXT")
ensure_sqlite_column("subscribers", "last_text", "TEXT")


def ensure_default_plan_basic():
    with engine.connect() as conn:
        conn.execute(sa_text("UPDATE agents SET plan='basic' WHERE plan IS NULL OR TRIM(plan)=''"))
        conn.commit()

ensure_default_plan_basic()


# ===== HELPERS =====
def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def generate_password(length=10):
    return uuid.uuid4().hex[:length]

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

def ensure_admin_user():
    db = SessionLocal()
    try:
        admin = db.query(User).filter_by(username="admin").first()
        if not admin:
            db.add(User(username="admin", password=ADMIN_PASSWORD, role="admin", agent_slug=None))
            db.commit()
    finally:
        db.close()

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


# ===== LINGUA (AUTO) =====
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


# ===== MULTI-PROFILI =====
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

        out.append({
            "key": key,
            "label_it": (p.get("label_it") or p.get("label") or f"Profilo {i+1}").strip(),
            "label_en": (p.get("label_en") or p.get("label") or f"Profile {i+1}").strip(),

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
            "pec": (p.get("pec") or "").strip(),
            "piva": (p.get("piva") or "").strip(),
            "sdi": (p.get("sdi") or "").strip(),
            "addresses": (p.get("addresses") or "").strip(),

            "facebook": (p.get("facebook") or "").strip(),
            "instagram": (p.get("instagram") or "").strip(),
            "linkedin": (p.get("linkedin") or "").strip(),
            "tiktok": (p.get("tiktok") or "").strip(),
            "telegram": (p.get("telegram") or "").strip(),
            "whatsapp": (p.get("whatsapp") or "").strip(),
        })
    return out

def dump_profiles_json(profiles: list) -> str:
    return json.dumps(profiles, ensure_ascii=False)

def select_profile(profiles, requested_key: str):
    if not requested_key:
        return None
    for p in profiles:
        if p.get("key") == requested_key:
            return p
    return None

def upsert_profile(profiles: list, key: str, payload: dict):
    for p in profiles:
        if p.get("key") == key:
            p.update(payload)
            return profiles
    base = {"key": key}
    base.update(payload)
    profiles.append(base)
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
    if not profile:
        return view

    def set_if(key_src, key_dst=None):
        v = (profile.get(key_src) or "").strip()
        if not v:
            return
        setattr(view, key_dst or key_src, v)

    set_if("photo_url")
    set_if("logo_url", "extra_logo_url")
    set_if("name")
    set_if("company")
    set_if("role")
    set_if("bio")

    set_if("phone_mobile")
    set_if("phone_mobile2")
    set_if("phone_office")

    set_if("emails")
    set_if("websites")
    set_if("pec")
    set_if("piva")
    set_if("sdi")
    set_if("addresses")

    set_if("facebook")
    set_if("instagram")
    set_if("linkedin")
    set_if("tiktok")
    set_if("telegram")
    set_if("whatsapp")

    return view


# ===== WhatsApp send (solo testo base) =====
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
        return False, "requests non disponibile"
    except Exception as e:
        return False, str(e)


# =========================
# ROUTES
# =========================
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


# -------- LOGIN --------
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
    try:
        u = db.query(User).filter_by(username=username, password=password).first()
        if not u:
            return render_template("login.html", error="Credenziali errate", next="")
        session["username"] = u.username
        session["role"] = u.role
        session["agent_slug"] = u.agent_slug
        if u.role == "admin":
            return redirect(url_for("admin_home"))
        return redirect(url_for("me_edit"))
    finally:
        db.close()

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------- ADMIN LISTA --------
@app.get("/admin")
@admin_required
def admin_home():
    db = SessionLocal()
    try:
        agents = db.query(Agent).order_by(Agent.name).all()
        for a in agents:
            a.plan = normalize_plan(getattr(a, "plan", "basic"))
        return render_template("admin_list.html", agents=agents)
    finally:
        db.close()

# -------- ADMIN EXPORT JSON --------
@app.get("/admin/export_agents.json")
@admin_required
def admin_export_agents_json():
    db = SessionLocal()
    try:
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
    finally:
        db.close()

# -------- ADMIN CREDENZIALI (reset password + mostra) --------
@app.get("/admin/<slug>/credentials")
@admin_required
def admin_credentials(slug):
    slug = slugify(slug)
    db = SessionLocal()
    try:
        ag = db.query(Agent).filter_by(slug=slug).first()
        if not ag:
            abort(404)

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
            a.secondary{{background:#334155}}
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
              <a class="secondary" href="/admin">⬅ Torna alla lista</a>
            </div>

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
    finally:
        db.close()


# -------- ADMIN NEW --------
@app.get("/admin/new")
@admin_required
def new_agent():
    return render_template("agent_form.html", agent=None)

@app.post("/admin/new")
@admin_required
def create_agent():
    db = SessionLocal()
    try:
        fields = [
            "slug", "name", "company", "role", "bio",
            "phone_mobile", "phone_mobile2", "phone_office",
            "emails", "websites",
            "facebook", "instagram", "linkedin", "tiktok",
            "telegram", "whatsapp",
            "pec", "piva", "sdi", "addresses",
            "plan", "profiles_json",
        ]
        data = {k: (request.form.get(k, "") or "").strip() for k in fields}
        data["slug"] = slugify(data.get("slug", ""))
        data["plan"] = normalize_plan(data.get("plan", "basic"))

        # valida JSON (se presente)
        if data.get("profiles_json"):
            try:
                tmp = json.loads(data["profiles_json"])
                if not isinstance(tmp, list):
                    data["profiles_json"] = ""
            except Exception:
                data["profiles_json"] = ""

        if not data["slug"] or not data["name"]:
            flash("Slug e Nome sono obbligatori", "error")
            return redirect(url_for("new_agent"))

        if db.query(Agent).filter_by(slug=data["slug"]).first():
            flash("Slug già esistente", "error")
            return redirect(url_for("new_agent"))

        # upload
        photo = request.files.get("photo")
        extra_logo = request.files.get("extra_logo")
        gallery_files = request.files.getlist("gallery")
        video_files = request.files.getlist("videos")

        photo_url = upload_file(photo, "photos") if photo and photo.filename else None
        extra_logo_url = upload_file(extra_logo, "logos") if extra_logo and extra_logo.filename else None

        # pdfs
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

        db.add(ag)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("Errore salvataggio (slug duplicato?)", "error")
            return redirect(url_for("new_agent"))

        # crea user client (username=slug)
        slug = data["slug"]
        u = db.query(User).filter_by(username=slug).first()
        if not u:
            pw = generate_password()
            db.add(User(username=slug, password=pw, role="client", agent_slug=slug))
            db.commit()

        flash("Agente creato ✅", "ok")
        return redirect(url_for("admin_home"))
    finally:
        db.close()


# -------- ADMIN EDIT --------
@app.get("/admin/<slug>/edit")
@admin_required
def edit_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    try:
        ag = db.query(Agent).filter_by(slug=slug).first()
        if not ag:
            abort(404)
        ag.plan = normalize_plan(getattr(ag, "plan", "basic"))
        return render_template("agent_form.html", agent=ag)
    finally:
        db.close()

@app.post("/admin/<slug>/edit")
@admin_required
def update_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    try:
        ag = db.query(Agent).filter_by(slug=slug).first()
        if not ag:
            abort(404)

        # campi
        for k in [
            "name", "company", "role", "bio",
            "phone_mobile", "phone_mobile2", "phone_office",
            "emails", "websites",
            "facebook", "instagram", "linkedin", "tiktok",
            "telegram", "whatsapp",
            "pec", "piva", "sdi", "addresses",
            "profiles_json",
        ]:
            val = (request.form.get(k, "") or "").strip()
            if k == "profiles_json" and val:
                try:
                    tmp = json.loads(val)
                    if not isinstance(tmp, list):
                        val = ""
                except Exception:
                    val = ""
            setattr(ag, k, val)

        ag.plan = normalize_plan(request.form.get("plan", getattr(ag, "plan", "basic")))

        # delete pdfs
        if request.form.get("delete_pdfs") == "1":
            ag.pdf1_url = None

        # uploads
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

        # pdf append
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

        # gallery replace
        if gallery_files and any(g.filename for g in gallery_files):
            gallery_urls = []
            for f in gallery_files[:MAX_GALLERY_IMAGES]:
                if f and f.filename:
                    u = upload_file(f, "gallery")
                    if u:
                        gallery_urls.append(u)
            if gallery_urls:
                ag.gallery_urls = "|".join(gallery_urls)

        # video replace
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
        return redirect(url_for("admin_home"))
    finally:
        db.close()

@app.post("/admin/<slug>/delete")
@admin_required
def delete_agent(slug):
    slug = slugify(slug)
    db = SessionLocal()
    try:
        ag = db.query(Agent).filter_by(slug=slug).first()
        if ag:
            db.delete(ag)
            db.commit()
        flash("Eliminato", "ok")
        return redirect(url_for("admin_home"))
    finally:
        db.close()


# -------- CLIENT: PROFILO 1 --------
@app.get("/me/edit")
@login_required
def me_edit():
    if is_admin():
        return redirect(url_for("admin_home"))

    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    try:
        ag = db.query(Agent).filter_by(slug=slug).first()
        if not ag:
            abort(404)
        ag.plan = normalize_plan(getattr(ag, "plan", "basic"))
        return render_template("agent_form.html", agent=ag)
    finally:
        db.close()

@app.post("/me/edit")
@login_required
def me_edit_post():
    if is_admin():
        return redirect(url_for("admin_home"))

    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    try:
        ag = db.query(Agent).filter_by(slug=slug).first()
        if not ag:
            abort(404)

        current_plan = normalize_plan(getattr(ag, "plan", "basic"))

        allowed_fields = [
            "name", "company", "role", "bio",
            "phone_mobile", "phone_mobile2", "phone_office",
            "emails", "websites",
            "facebook", "instagram", "linkedin", "tiktok",
            "telegram", "whatsapp",
            "pec", "piva", "sdi", "addresses",
        ]

        for k in allowed_fields:
            setattr(ag, k, (request.form.get(k, "") or "").strip())

        ag.plan = current_plan

        # uploads
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

        # pdf append
        pdf_entries = []
        for i in range(1, 13):
            f = request.files.get(f"pdf{i}")
            if f and f.filename:
                u = upload_file(f, "pdf")
                if u:
                    pdf_entries.append(f"{f.filename}||{u}")
        if pdf_entries:
            ag.pdf1_url = "|".join(pdf_entries)

        # gallery replace
        if gallery_files and any(g.filename for g in gallery_files):
            gallery_urls = []
            for f in gallery_files[:MAX_GALLERY_IMAGES]:
                if f and f.filename:
                    u = upload_file(f, "gallery")
                    if u:
                        gallery_urls.append(u)
            if gallery_urls:
                ag.gallery_urls = "|".join(gallery_urls)

        # video replace
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
    finally:
        db.close()


# -------- CLIENT: PROFILO 2 (UGUALE, salva in profiles_json key=p2) --------
@app.get("/me/profile2")
@login_required
def me_profile2():
    if is_admin():
        return redirect(url_for("admin_home"))

    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    try:
        ag = db.query(Agent).filter_by(slug=slug).first()
        if not ag:
            abort(404)

        profiles = parse_profiles_json(ag.profiles_json or "")
        p2 = select_profile(profiles, "p2") or {"key": "p2", "label_it": "Profilo 2", "label_en": "Profile 2"}

        view = agent_to_view(ag)
        view = apply_profile_to_view(view, p2)
        setattr(view, "__editing_profile2__", True)   # flag per template

        return render_template("agent_form.html", agent=view)
    finally:
        db.close()

@app.post("/me/profile2")
@login_required
def me_profile2_post():
    if is_admin():
        return redirect(url_for("admin_home"))

    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    try:
        ag = db.query(Agent).filter_by(slug=slug).first()
        if not ag:
            abort(404)

        profiles = parse_profiles_json(ag.profiles_json or "")

        payload = {
            "key": "p2",
            "label_it": (request.form.get("label_it") or "Profilo 2").strip(),
            "label_en": (request.form.get("label_en") or "Profile 2").strip(),

            "name": (request.form.get("name") or "").strip(),
            "company": (request.form.get("company") or "").strip(),
            "role": (request.form.get("role") or "").strip(),
            "bio": (request.form.get("bio") or "").strip(),

            "phone_mobile": (request.form.get("phone_mobile") or "").strip(),
            "phone_mobile2": (request.form.get("phone_mobile2") or "").strip(),
            "phone_office": (request.form.get("phone_office") or "").strip(),

            "emails": (request.form.get("emails") or "").strip(),
            "websites": (request.form.get("websites") or "").strip(),
            "pec": (request.form.get("pec") or "").strip(),
            "piva": (request.form.get("piva") or "").strip(),
            "sdi": (request.form.get("sdi") or "").strip(),
            "addresses": (request.form.get("addresses") or "").strip(),

            "facebook": (request.form.get("facebook") or "").strip(),
            "instagram": (request.form.get("instagram") or "").strip(),
            "linkedin": (request.form.get("linkedin") or "").strip(),
            "tiktok": (request.form.get("tiktok") or "").strip(),
            "telegram": (request.form.get("telegram") or "").strip(),
            "whatsapp": (request.form.get("whatsapp") or "").strip(),
        }

        photo = request.files.get("photo")
        extra_logo = request.files.get("extra_logo")
        if photo and photo.filename:
            u = upload_file(photo, "photos")
            if u:
                payload["photo_url"] = u
        if extra_logo and extra_logo.filename:
            u = upload_file(extra_logo, "logos")
            if u:
                payload["logo_url"] = u

        profiles = upsert_profile(profiles, "p2", payload)
        ag.profiles_json = dump_profiles_json(profiles)

        db.commit()
        flash("Profilo 2 salvato ✅", "ok")
        return redirect(url_for("me_profile2"))
    finally:
        db.close()


# -------- PUBLIC CARD --------
@app.get("/<slug>")
def public_card(slug):
    slug = slugify(slug)
    db = SessionLocal()
    try:
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

        emails = [e.strip() for e in (ag_view.emails or "").split(",") if e.strip()]
        websites = [w.strip() for w in (ag_view.websites or "").split(",") if w.strip()]
        addresses = [a.strip() for a in (ag_view.addresses or "").split("\n") if a.strip()]
        pdfs = parse_pdfs(ag.pdf1_url or "")

        base = get_base_url()

        mobiles = []
        if getattr(ag_view, "phone_mobile", None):
            mobiles.append(ag_view.phone_mobile.strip())
        if getattr(ag_view, "phone_mobile2", None):
            m2 = (ag_view.phone_mobile2 or "").strip()
            if m2:
                mobiles.append(m2)

        # link opt-in (solo per clienti)
        wa_optin_link = ""
        if ag.plan == "pro":
            optin_text = f"ISCRIVIMI {ag.slug} + ACCETTO RICEVERE PROMO"
            wa_optin_link = f"https://wa.me/{WA_OPTIN_PHONE}?text={quote(optin_text)}"

        # nfc link mantiene p e lang
        nfc_direct_url = f"{base}/{ag.slug}"
        params = []
        if p_key:
            params.append(("p", p_key))
        params.append(("lang", lang))
        nfc_direct_url = nfc_direct_url + "?" + urllib.parse.urlencode(params)

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
            t_func=lambda k: t(lang, k),
            profiles=profiles,
            active_profile=active_profile,
            p_key=p_key,
            nfc_direct_url=nfc_direct_url,
        )
    finally:
        db.close()


# -------- VCARD --------
@app.get("/<slug>.vcf")
def vcard(slug):
    slug = slugify(slug)
    db = SessionLocal()
    try:
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
        lines.append(f"URL:{base}/{ag.slug}")

        if ag.piva:
            lines.append(f"X-TAX-ID:{ag.piva}")
        if ag.sdi:
            lines.append(f"X-SDI-CODE:{ag.sdi}")

        lines.append("END:VCARD")
        content = "\r\n".join(lines)

        resp = Response(content, mimetype="text/vcard; charset=utf-8")
        resp.headers["Content-Disposition"] = f'attachment; filename="{ag.slug}.vcf"'
        return resp
    finally:
        db.close()


# -------- QR PNG (sempre con lang + p) --------
@app.get("/<slug>/qr.png")
def qr(slug):
    slug = slugify(slug)
    base = get_base_url()
    lang = pick_lang_from_request()
    p = (request.args.get("p") or "").strip()

    params = [("lang", lang)]
    if p:
        params.append(("p", p))
    url = f"{base}/{slug}?" + urllib.parse.urlencode(params)

    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")


# -------- WhatsApp Webhook verify (per Meta) --------
@app.get("/wa/webhook")
def wa_webhook_verify():
    mode = request.args.get("hub.mode", "")
    token = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")
    if mode == "subscribe" and token == WA_VERIFY_TOKEN:
        return Response(challenge, status=200, mimetype="text/plain")
    return Response("forbidden", status=403, mimetype="text/plain")


# -------- ERRORI --------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
