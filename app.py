import os
import base64
import requests
from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, session, abort, Response
)
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import qrcode
from io import BytesIO
from datetime import datetime, timedelta
import uuid, tempfile

load_dotenv()

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_BUCKET = os.getenv("FIREBASE_BUCKET")
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON")

app = Flask(__name__)
app.secret_key = APP_SECRET
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB

DB_URL = "sqlite:///data.db"
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


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
    gallery_urls = Column(Text, nullable=True)
    # pdf1_url contiene tutti gli URL PDF separati da "|"
    pdf1_url = Column(String, nullable=True)
    pdf2_url = Column(String, nullable=True)  # non usato ora, tenuto per compatibilità


Base.metadata.create_all(engine)


# --------------------------------------------------
# Helper per autenticazione admin
# --------------------------------------------------
def admin_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)

    return wrapper


# --------------------------------------------------
# Firebase (se disponibile) + Upload locale
# --------------------------------------------------
def get_storage_client():
    try:
        if not (FIREBASE_BUCKET and FIREBASE_CREDENTIALS_JSON):
            return None
        from google.cloud import storage

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.write(FIREBASE_CREDENTIALS_JSON.encode("utf-8"))
        tmp.flush()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name
        return storage.Client(project=FIREBASE_PROJECT_ID)
    except Exception as e:
        app.logger.exception("Firebase disabled due to error: %s", e)
        return None


def upload_file(file_storage, folder="uploads"):
    """
    Se Firebase è configurato, carica su bucket.
    Altrimenti salva in static/<folder> e restituisce URL statico.
    """
    if not file_storage or not file_storage.filename:
        return None

    client = get_storage_client()
    ext = os.path.splitext(file_storage.filename or "")[1].lower()

    if client and FIREBASE_BUCKET:
        try:
            from google.cloud import storage  # noqa

            bucket = client.bucket(FIREBASE_BUCKET)
            key = f"{folder}/{datetime.utcnow().strftime('%Y/%m/%d')}/{uuid.uuid4().hex}{ext}"
            blob = bucket.blob(key)
            blob.upload_from_file(file_storage.stream, content_type=file_storage.mimetype)
            url = blob.generate_signed_url(
                expiration=datetime.utcnow() + timedelta(days=3650),
                method="GET",
            )
            return url
        except Exception as e:
            app.logger.exception("Firebase upload failed: %s", e)
            # fallback a salvataggio locale

    # Fallback locale in static/<folder>
    try:
        uploads_folder = os.path.join(app.static_folder, folder)
        os.makedirs(uploads_folder, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{ext}"
        fullpath = os.path.join(uploads_folder, filename)
        file_storage.save(fullpath)
        # URL relativo allo static
        return url_for("static", filename=f"{folder}/{filename}", _external=False)
    except Exception as e:
        app.logger.exception("Local upload failed: %s", e)
        return None


def get_base_url():
    b = BASE_URL or ""
    if b:
        return b
    from flask import request

    return request.url_root.strip().rstrip("/")


# --------------------------------------------------
# ROUTES BASE
# --------------------------------------------------
@app.get("/")
def home():
    if session.get("admin"):
        return redirect(url_for("admin_home"))
    return redirect(url_for("login"))


@app.get("/health")
def health():
    return "ok", 200


# --------------------------------------------------
# LOGIN / LOGOUT
# --------------------------------------------------
@app.get("/login")
def login():
    return render_template(
        "login.html",
        error=None,
        next=request.args.get("next", "/admin")
    )


@app.post("/login")
def login_post():
    pw = request.form.get("password", "")
    nxt = request.form.get("next", "/admin")
    if pw == ADMIN_PASSWORD:
        session["admin"] = True
        return redirect(nxt)
    return render_template("login.html", error="Password errata", next=nxt)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------
# ADMIN – LISTA AGENTI
# --------------------------------------------------
@app.get("/admin")
@admin_required
def admin_home():
    db = SessionLocal()
    agents = db.query(Agent).order_by(Agent.name).all()
    return render_template("admin_list.html", agents=agents)


# --------------------------------------------------
# ADMIN – NUOVO AGENTE
# --------------------------------------------------
@app.get("/admin/new")
@admin_required
def new_agent():
    return render_template("agent_form.html", agent=None)


@app.post("/admin/new")
@admin_required
def create_agent():
    db = SessionLocal()
    fields = [
        "slug",
        "name",
        "company",
        "role",
        "bio",
        "phone_mobile",
        "phone_office",
        "emails",
        "websites",
        "facebook",
        "instagram",
        "linkedin",
        "tiktok",
        "telegram",
        "whatsapp",
        "pec",
        "piva",
        "sdi",
        "addresses",
    ]
    data = {k: request.form.get(k, "").strip() for k in fields}

    if not data["slug"] or not data["name"]:
        return "Slug e Nome sono obbligatori", 400

    if db.query(Agent).filter_by(slug=data["slug"]).first():
        return "Slug già esistente", 400

    photo = request.files.get("photo")
    gallery_files = request.files.getlist("gallery")

    # FOTO PROFILO
    photo_url = upload_file(photo, "photos") if photo and photo.filename else None

    # PDF 1–6
    pdf_urls = []
    for i in range(1, 7):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_urls.append(u)
    pdf_joined = "|".join(pdf_urls) if pdf_urls else None

    # GALLERIA (max 12)
    gallery_urls = []
    for f in gallery_files[:12]:
        if f and f.filename:
            u = upload_file(f, "gallery")
            if u:
                gallery_urls.append(u)

    ag = Agent(
        **data,
        photo_url=photo_url,
        pdf1_url=pdf_joined,
        pdf2_url=None,
        gallery_urls="|".join(gallery_urls) if gallery_urls else None,
    )
    db.add(ag)
    db.commit()
    return redirect(url_for("admin_home"))


# --------------------------------------------------
# ADMIN – MODIFICA / ELIMINA
# --------------------------------------------------
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
        "slug",
        "name",
        "company",
        "role",
        "bio",
        "phone_mobile",
        "phone_office",
        "emails",
        "websites",
        "facebook",
        "instagram",
        "linkedin",
        "tiktok",
        "telegram",
        "whatsapp",
        "pec",
        "piva",
        "sdi",
        "addresses",
    ]:
        setattr(ag, k, request.form.get(k, "").strip())

    photo = request.files.get("photo")
    gallery_files = request.files.getlist("gallery")

    # FOTO PROFILO
    if photo and photo.filename:
        u = upload_file(photo, "photos")
        if u:
            ag.photo_url = u

    # PDF 1–6 – se carichi almeno un PDF nuovo, rimpiazziamo lista
    new_pdf_urls = []
    for i in range(1, 7):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                new_pdf_urls.append(u)
    if new_pdf_urls:
        ag.pdf1_url = "|".join(new_pdf_urls)

    # GALLERIA – se carichi nuove foto, sostituisci la galleria
    if gallery_files and any(g.filename for g in gallery_files):
        urls = []
        for f in gallery_files[:12]:
            if f and f.filename:
                u = upload_file(f, "gallery")
                if u:
                    urls.append(u)
        if urls:
            ag.gallery_urls = "|".join(urls)

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


# --------------------------------------------------
# CARD PUBBLICA
# --------------------------------------------------
@app.get("/<slug>")
def public_card(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    gallery = ag.gallery_urls.split("|") if ag.gallery_urls else []
    emails = [e.strip() for e in (ag.emails or "").split(",") if e.strip()]
    websites = [w.strip() for w in (ag.websites or "").split(",") if w.strip()]
    addresses = [a.strip() for a in (ag.addresses or "").split("\n") if a.strip()]
    pdfs = [u.strip() for u in (ag.pdf1_url or "").split("|") if u.strip()]

    base = get_base_url()
    return render_template(
        "card.html",
        ag=ag,
        base_url=base,
        gallery=gallery,
        emails=emails,
        websites=websites,
        addresses=addresses,
        pdfs=pdfs,
    )


# --------------------------------------------------
# VIEWER PDF – (se vorrai usarlo a parte)
# --------------------------------------------------
@app.get("/<slug>/pdf/<int:index>")
def pdf_viewer(slug, index):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    pdfs = [u.strip() for u in (ag.pdf1_url or "").split("|") if u.strip()]
    if index < 1 or index > len(pdfs):
        abort(404)

    pdf_url = pdfs[index - 1]
    return render_template("pdf_viewer.html", ag=ag, pdf_url=pdf_url, index=index)


# --------------------------------------------------
# VCARD & QR (con FOTO incorporata e link card)
# --------------------------------------------------
@app.get("/<slug>.vcf")
def vcard(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)

    base = get_base_url()
    full_name = ag.name or ""
    parts = full_name.strip().split(" ", 1)
    if len(parts) == 2:
        first_name = parts[0]
        last_name = parts[1]
    else:
        first_name = full_name
        last_name = ""

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{full_name}",
        f"N:{last_name};{first_name};;;",
    ]

    # Ruolo / azienda
    if getattr(ag, "role", None):
        lines.append(f"TITLE:{ag.role}")
    if getattr(ag, "company", None):
        lines.append(f"ORG:{ag.company}")

    # Telefoni
    if getattr(ag, "phone_mobile", None):
        lines.append(f"TEL;TYPE=CELL:{ag.phone_mobile}")
    if getattr(ag, "phone_office", None):
        lines.append(f"TEL;TYPE=WORK:{ag.phone_office}")

    # Email lavoro (anche multiple)
    if getattr(ag, "emails", None):
        for e in [x.strip() for x in ag.emails.split(",") if x.strip()]:
            lines.append(f"EMAIL;TYPE=WORK:{e}")

    # PEC separata
    if getattr(ag, "pec", None):
        lines.append(f"EMAIL;TYPE=INTERNET:{ag.pec}")

    # Siti internet
    if getattr(ag, "websites", None):
        for w in [x.strip() for x in ag.websites.split(",") if x.strip()]:
            lines.append(f"URL:{w}")

    # URL principale della card (per PDF, galleria, ecc.)
    card_url = f"{base}/{ag.slug}"
    lines.append(f"URL:{card_url}")

    # FOTO PROFILO INCORPORATA (Base64)
    if getattr(ag, "photo_url", None):
        photo_url = ag.photo_url
        if photo_url.startswith("/"):
            photo_url = f"{base}{photo_url}"

        try:
            r = requests.get(photo_url, timeout=5)
            if r.ok and r.content:
                mime = r.headers.get("Content-Type", "image/jpeg").lower()
                if "png" in mime:
                    img_type = "PNG"
                else:
                    img_type = "JPEG"
                b64 = base64.b64encode(r.content).decode("ascii")
                # vCard 3.0: PHOTO incorporata
                lines.append(f"PHOTO;ENCODING=b;TYPE={img_type}:{b64}")
            else:
                # fallback: URL, se il client la supporta
                lines.append(f"PHOTO;VALUE=URI:{photo_url}")
        except Exception:
            # in caso di errore rete, almeno mettiamo l'URL
            lines.append(f"PHOTO;VALUE=URI:{photo_url}")

    # Indirizzo (prendiamo il primo disponibile)
    if getattr(ag, "addresses", None):
        raw_addrs = [a.strip() for a in ag.addresses.split("\n") if a.strip()]
        if raw_addrs:
            first_addr = raw_addrs[0].replace(";", ",")
            # ADR: POBox;Extended;Street;Street;Locality;Region;PostalCode;Country
            lines.append(f"ADR;TYPE=WORK:;;{first_addr};;;;")

    # Dati fiscali in campi custom + NOTE
    note_parts = []

    if getattr(ag, "piva", None):
        lines.append(f"X-TAX-ID:{ag.piva}")
        note_parts.append(f"Partita IVA: {ag.piva}")

    if getattr(ag, "sdi", None):
        lines.append(f"X-SDI-CODE:{ag.sdi}")
        note_parts.append(f"SDI: {ag.sdi}")

    # Aggiungiamo sempre il link alla card nelle note
    note_parts.append(f"Card digitale: {card_url}")

    if note_parts:
        note = " | ".join(note_parts).replace(";", "\\;")
        lines.append("NOTE:" + note)

    lines.append("END:VCARD")
    content = "\r\n".join(lines)

    if request.args.get("download") == "1":
        resp = Response(content, mimetype="text/vcard; charset=utf-8")
        resp.headers["Content-Disposition"] = f'attachment; filename="{ag.slug}.vcf"'
        return resp

    return Response(content, mimetype="text/vcard; charset=utf-8")


@app.get("/<slug>/qr.png")
def qr(slug):
    base = get_base_url()
    url = f"{base}/{slug}"
    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")


# --------------------------------------------------
# ERRORI
# --------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
