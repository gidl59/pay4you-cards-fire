import os
import uuid
from io import BytesIO
from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, session, abort, Response
)
from sqlalchemy import create_engine, Column, Integer, String, Text, text as sa_text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import qrcode
import urllib.parse  # per ricavare nome file da URL

load_dotenv()

# ===== ENV / CONFIG =====
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")  # ✅ la tua password attuale
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")

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


# ===== MODELS =====
class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    company = Column(String, nullable=True)
    role = Column(String, nullable=True)
    bio = Column(Text, nullable=True)

    # ✅ TELEFONI
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

    gallery_urls = Column(Text, nullable=True)  # "url1|url2|..."
    video_urls = Column(Text, nullable=True)    # "url1|url2|..."
    pdf1_url = Column(Text, nullable=True)      # "nome||url|nome||url|..."


class User(Base):
    """
    Utenti per login.
    - admin: username=admin, password=ADMIN_PASSWORD (creato automaticamente)
    - client: username=slug, password=generata, agent_slug=slug
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)          # (per ora in chiaro; poi si può hashare)
    role = Column(String, nullable=False, default="client")  # "admin" | "client"
    agent_slug = Column(String, nullable=True)         # es. "barrossi"


Base.metadata.create_all(engine)


# ===== MICRO-MIGRAZIONI (solo per agents) =====
def ensure_sqlite_column(table: str, column: str, coltype: str):
    with engine.connect() as conn:
        rows = conn.execute(sa_text(f"PRAGMA table_info({table})")).fetchall()
        existing_cols = {r[1] for r in rows}
        if column not in existing_cols:
            conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            conn.commit()


ensure_sqlite_column("agents", "video_urls", "TEXT")
ensure_sqlite_column("agents", "phone_mobile2", "TEXT")


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


def upload_file(file_storage, folder="uploads"):
    """Salva il file in static/<folder> e restituisce l'URL relativo."""
    if not file_storage or not file_storage.filename:
        return None

    ext = os.path.splitext(file_storage.filename or "")[1].lower()
    uploads_folder = os.path.join(app.static_folder, folder)
    os.makedirs(uploads_folder, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{ext}"
    fullpath = os.path.join(uploads_folder, filename)
    file_storage.save(fullpath)

    return url_for("static", filename=f"{folder}/{filename}", _external=False)


def get_base_url():
    if BASE_URL:
        return BASE_URL
    return request.url_root.strip().rstrip("/")


def parse_pdfs(raw: str):
    """
    Supporta:
    - NUOVO FORMATO: "nome1||url1|nome2||url2|..."
    - VECCHIO FORMATO: "url1|url2|..."
    """
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
            # compat vecchio formato
            url = item
            parsed = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed.path) or "Documento"
            pdfs.append({"name": filename, "url": url})
            i += 1

    return pdfs


def ensure_admin_user():
    """Crea l'utente admin in DB se non esiste (password = ADMIN_PASSWORD)."""
    db = SessionLocal()
    admin = db.query(User).filter_by(username="admin").first()
    if not admin:
        db.add(User(username="admin", password=ADMIN_PASSWORD, role="admin", agent_slug=None))
        db.commit()


ensure_admin_user()


def generate_password(length=10):
    return uuid.uuid4().hex[:length]


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

    # ✅ admin: username=admin + password = ADMIN_PASSWORD
    if username == "admin" and password == ADMIN_PASSWORD:
        session["username"] = "admin"
        session["role"] = "admin"
        session["agent_slug"] = None
        return redirect(url_for("admin_home"))

    # ✅ client: cerca in DB
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
    return render_template("admin_list.html", agents=agents)


# ------------------ CREDENZIALI CLIENTE (RESET) ------------------
@app.get("/admin/<slug>/credentials")
@admin_required
def admin_credentials(slug):
    """
    Genera o resetta la password del cliente (username=slug).
    Mostra a video username + nuova password.
    """
    db = SessionLocal()
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

    # Pagina semplice con credenziali (così non devi toccare template)
    return f"""
    <h2>Credenziali Cliente</h2>
    <p><b>Card:</b> {slug}</p>
    <p><b>Username:</b> {u.username}</p>
    <p><b>Password:</b> {u.password}</p>
    <p><a href="{url_for('admin_home')}">⬅ Torna alla lista</a></p>
    """


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
    ]
    data = {k: (request.form.get(k, "") or "").strip() for k in fields}

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

    # PDF 1–12: "nome_originale||url"
    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    pdf_joined = "|".join(pdf_entries) if pdf_entries else None

    # GALLERIA fino a 30 immagini
    gallery_urls = []
    for f in gallery_files[:MAX_GALLERY_IMAGES]:
        if f and f.filename:
            u = upload_file(f, "gallery")
            if u:
                gallery_urls.append(u)

    # VIDEO fino a 10
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
    db.commit()

    # ✅ crea utente cliente (username = slug)
    slug = data["slug"]
    existing_user = db.query(User).filter_by(username=slug).first()
    if not existing_user:
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
    ]:
        setattr(ag, k, (request.form.get(k, "") or "").strip())

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
    # opzionale: potresti anche eliminare user associato, ma per ora lasciamo semplice
    return redirect(url_for("admin_home"))


# ------------------ AREA CLIENTE: MODIFICA SOLO LA PROPRIA CARD ------------------
@app.get("/me/edit")
@login_required
def me_edit():
    if is_admin():
        # admin può comunque usare il pannello admin
        return redirect(url_for("admin_home"))

    slug = current_client_slug()
    if not slug:
        return redirect(url_for("login"))

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

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

    # ✅ aggiorno gli stessi campi dell'admin (ma solo per il proprio slug)
    for k in [
        "name", "company", "role", "bio",
        "phone_mobile", "phone_mobile2", "phone_office",
        "emails", "websites",
        "facebook", "instagram", "linkedin", "tiktok",
        "telegram", "whatsapp", "pec",
        "piva", "sdi", "addresses",
    ]:
        setattr(ag, k, (request.form.get(k, "") or "").strip())

    # ✅ client: può caricare foto/logo/gallery/video/pdf (se vuoi puoi limitarlo dopo)
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

    # PDF: sostituisce solo se carica nuovi pdf
    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        ag.pdf1_url = "|".join(pdf_entries)

    # Gallery
    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                u = upload_file(f, "gallery")
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            ag.gallery_urls = "|".join(gallery_urls)

    # Videos
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

    gallery = ag.gallery_urls.split("|") if ag.gallery_urls else []
    videos = ag.video_urls.split("|") if ag.video_urls else []

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

    return render_template(
        "card.html",
        ag=ag,
        base_url=base,
        gallery=gallery,
        videos=videos,
        emails=emails,
        websites=websites,
        addresses=addresses,
        pdfs=pdfs,
        mobiles=mobiles,
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
    url = f"{base}/{slug}"
    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")


# ------------------ ERRORI ------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
