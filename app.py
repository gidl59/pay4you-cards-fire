import os
import uuid
from io import BytesIO
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, session, abort, Response
)
from sqlalchemy import create_engine, Column, Integer, String, Text, text as sa_text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import qrcode
import urllib.parse  # <-- per ricavare nome file da URL

load_dotenv()

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
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


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    company = Column(String, nullable=True)
    role = Column(String, nullable=True)
    bio = Column(Text, nullable=True)

    phone_mobile = Column(String, nullable=True)
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

    # gallery_urls = "url1|url2|..."
    gallery_urls = Column(Text, nullable=True)

    # ✅ NUOVO: video_urls = "url1|url2|..."
    video_urls = Column(Text, nullable=True)

    # pdf1_url = "nome1||url1|nome2||url2|..." (nuovo formato)
    # oppure "url1|url2|..." (vecchio formato)
    pdf1_url = Column(Text, nullable=True)


Base.metadata.create_all(engine)


# ✅ Micro-migrazione SQLite: aggiunge colonne mancanti se DB già esistente
def ensure_sqlite_column(table: str, column: str, coltype: str):
    with engine.connect() as conn:
        rows = conn.execute(sa_text(f"PRAGMA table_info({table})")).fetchall()
        existing_cols = {r[1] for r in rows}  # r[1] = name
        if column not in existing_cols:
            conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            conn.commit()


ensure_sqlite_column("agents", "video_urls", "TEXT")


# ------------------ Helper ------------------
def admin_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
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
    from flask import request
    return request.url_root.strip().rstrip("/")


def parse_pdfs(raw: str):
    """
    Converte la stringa pdf1_url in una lista di dict:
    [
      {"name": "Nome file.pdf", "url": "/static/pdf/xxx.pdf"},
      ...
    ]

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
            if i + 2 < len(tokens) and tokens[i + 1] == "":
                name = item or "Documento"
                url = tokens[i + 2].strip()
                if url:
                    pdfs.append({"name": name, "url": url})
                i += 3
            else:
                url = item
                parsed = urllib.parse.urlparse(url)
                filename = os.path.basename(parsed.path) or "Documento"
                pdfs.append({"name": filename, "url": url})
                i += 1

    return pdfs


# ------------------ ROUTES BASE ------------------
@app.get("/")
def home():
    if session.get("admin"):
        return redirect(url_for("admin_home"))
    return redirect(url_for("login"))


@app.get("/health")
def health():
    return "ok", 200


# ------------------ LOGIN ------------------
@app.get("/login")
def login():
    return render_template("login.html", error=None)


@app.post("/login")
def login_post():
    pw = request.form.get("password", "")
    if pw == ADMIN_PASSWORD:
        session["admin"] = True
        return redirect(url_for("admin_home"))
    return render_template("login.html", error="Password errata")


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
        "phone_mobile", "phone_office",
        "emails", "websites",
        "facebook", "instagram", "linkedin", "tiktok",
        "telegram", "whatsapp", "pec",
        "piva", "sdi", "addresses",
    ]
    data = {k: request.form.get(k, "").strip() for k in fields}

    if not data["slug"] or not data["name"]:
        return "Slug e Nome sono obbligatori", 400

    if db.query(Agent).filter_by(slug=data["slug"]).first():
        return "Slug già esistente", 400

    photo = request.files.get("photo")
    extra_logo = request.files.get("extra_logo")

    gallery_files = request.files.getlist("gallery")
    video_files = request.files.getlist("videos")  # ✅ nuovi video

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

    # ✅ GALLERIA fino a 30 immagini
    gallery_urls = []
    for f in gallery_files[:MAX_GALLERY_IMAGES]:
        if f and f.filename:
            u = upload_file(f, "gallery")
            if u:
                gallery_urls.append(u)

    # ✅ VIDEO fino a 10
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
    return redirect(url_for("admin_home"))


# ------------------ MODIFICA / ELIMINA ------------------
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
        "phone_mobile", "phone_office",
        "emails", "websites",
        "facebook", "instagram", "linkedin", "tiktok",
        "telegram", "whatsapp", "pec",
        "piva", "sdi", "addresses",
    ]:
        setattr(ag, k, request.form.get(k, "").strip())

    photo = request.files.get("photo")
    extra_logo = request.files.get("extra_logo")

    gallery_files = request.files.getlist("gallery")
    video_files = request.files.getlist("videos")  # ✅

    # Foto: solo se carichi un nuovo file
    if photo and photo.filename:
        u = upload_file(photo, "photos")
        if u:
            ag.photo_url = u

    # Logo extra: solo se carichi un nuovo file
    if extra_logo and extra_logo.filename:
        u = upload_file(extra_logo, "logos")
        if u:
            ag.extra_logo_url = u

    # PDF: sostituisco solo se carichi almeno un nuovo file
    pdf_entries = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_entries.append(f"{f.filename}||{u}")
    if pdf_entries:
        ag.pdf1_url = "|".join(pdf_entries)

    # ✅ Galleria: sostituisco solo se carichi nuove immagini
    if gallery_files and any(g.filename for g in gallery_files):
        gallery_urls = []
        for f in gallery_files[:MAX_GALLERY_IMAGES]:
            if f and f.filename:
                u = upload_file(f, "gallery")
                if u:
                    gallery_urls.append(u)
        if gallery_urls:
            ag.gallery_urls = "|".join(gallery_urls)

    # ✅ Video: sostituisco solo se carichi nuovi video
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


# ------------------ CARD PUBBLICA ------------------
@app.get("/<slug>")
def public_card(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    gallery = ag.gallery_urls.split("|") if ag.gallery_urls else []
    videos = ag.video_urls.split("|") if ag.video_urls else []  # ✅

    emails = [e.strip() for e in (ag.emails or "").split(",") if e.strip()]
    websites = [w.strip() for w in (ag.websites or "").split(",") if w.strip()]
    addresses = [a.strip() for a in (ag.addresses or "").split("\n") if a.strip()]

    pdfs = parse_pdfs(ag.pdf1_url or "")
    base = get_base_url()

    return render_template(
        "card.html",
        ag=ag,
        base_url=base,
        gallery=gallery,
        videos=videos,   # ✅ PASSO I VIDEO AL TEMPLATE
        emails=emails,
        websites=websites,
        addresses=addresses,
        pdfs=pdfs,
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
    resp.headers["Content-Disposition"] = f'attachment; filename=\"{ag.slug}.vcf\"'
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
