import os
import uuid
import tempfile
from datetime import datetime, timedelta
from io import BytesIO

from flask import (
    Flask,
    render_template,
render_template_string,
    request,
    redirect,
    url_for,
    send_file,
    session,
    abort,
    Response,
)
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import qrcode

# ================== CONFIG ==================

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

# ================== MODEL ==================


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

    pdf1_url = Column(String, nullable=True)
    pdf2_url = Column(String, nullable=True)
    pdf3_url = Column(String, nullable=True)
    pdf4_url = Column(String, nullable=True)
    pdf5_url = Column(String, nullable=True)
    pdf6_url = Column(String, nullable=True)


Base.metadata.create_all(engine)

# ================== HELPER ==================


def admin_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)

    return wrapper


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


def upload_to_firebase(file_storage, folder="uploads"):
    try:
        client = get_storage_client()
        if not client:
            return None
        bucket = client.bucket(FIREBASE_BUCKET)
        ext = os.path.splitext(file_storage.filename or "")[1].lower()
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
        return None


def get_base_url():
    if BASE_URL:
        return BASE_URL
    return request.url_root.strip().rstrip("/")


# ================== ROUTES BASE ==================


@app.get("/")
def home():
    return redirect(url_for("admin_home")) if session.get("admin") else redirect(
        url_for("login")
    )


@app.get("/health")
def health():
    return "ok", 200


# ================== LOGIN ==================


@app.get("/login")
def login():
    return render_template("login.html", error=None, next=request.args.get("next", "/admin"))


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


# ================== ADMIN ==================


@app.get("/admin")
@admin_required
def admin_home():
    db = SessionLocal()
    agents = db.query(Agent).order_by(Agent.name).all()
    return render_template("admin_list.html", agents=agents)


@app.get("/admin/new")
@admin_required
def new_agent():
    return render_template("agent_form.html", agent=None)


@app.post("/admin/new")
@admin_required
def create_agent():
    db = SessionLocal()

    slug = (request.form.get("slug") or "").strip()
    name = (request.form.get("name") or "").strip()

    if not slug or not name:
        return "Slug e Nome sono obbligatori", 400

    if db.query(Agent).filter(Agent.slug == slug).first():
        return "Slug già esistente", 400

    fields = [
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
    data = {k: (request.form.get(k) or "").strip() for k in fields}
    data["slug"] = slug
    data["name"] = name

    photo = request.files.get("photo")
    gallery_files = request.files.getlist("gallery")

    pdf_files = [
        request.files.get("pdf1"),
        request.files.get("pdf2"),
        request.files.get("pdf3"),
        request.files.get("pdf4"),
        request.files.get("pdf5"),
        request.files.get("pdf6"),
    ]

    photo_url = upload_to_firebase(photo, "photos") if photo and photo.filename else None

    pdf_urls = []
    for f in pdf_files:
        if f and f.filename:
            pdf_urls.append(upload_to_firebase(f, "pdf"))
        else:
            pdf_urls.append(None)

    gallery_urls = []
    for f in gallery_files[:12]:
        if f and f.filename:
            u = upload_to_firebase(f, "gallery")
            if u:
                gallery_urls.append(u)

    ag = Agent(
        **data,
        photo_url=photo_url,
        gallery_urls="|".join(gallery_urls) if gallery_urls else None,
        pdf1_url=pdf_urls[0],
        pdf2_url=pdf_urls[1],
        pdf3_url=pdf_urls[2],
        pdf4_url=pdf_urls[3],
        pdf5_url=pdf_urls[4],
        pdf6_url=pdf_urls[5],
    )
    db.add(ag)
    db.commit()
    return redirect(url_for("admin_home"))


@app.get("/admin/<slug>/edit")
@admin_required
def edit_agent(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)
    return render_template("agent_form.html", agent=ag)


@app.post("/admin/<slug>/edit")
@admin_required
def update_agent(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    new_slug = (request.form.get("slug") or "").strip()
    if not new_slug:
        return "Slug obbligatorio", 400

    if new_slug != ag.slug and db.query(Agent).filter(Agent.slug == new_slug).first():
        return "Slug già esistente", 400

    ag.slug = new_slug
    ag.name = (request.form.get("name") or "").strip()

    for k in [
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
        setattr(ag, k, (request.form.get(k) or "").strip())

    photo = request.files.get("photo")
    if photo and photo.filename:
        u = upload_to_firebase(photo, "photos")
        if u:
            ag.photo_url = u

    gallery_files = request.files.getlist("gallery")
    if gallery_files and any(g.filename for g in gallery_files):
        urls = []
        for f in gallery_files[:12]:
            if f and f.filename:
                u = upload_to_firebase(f, "gallery")
                if u:
                    urls.append(u)
        if urls:
            ag.gallery_urls = "|".join(urls)

    pdf_files = [
        request.files.get("pdf1"),
        request.files.get("pdf2"),
        request.files.get("pdf3"),
        request.files.get("pdf4"),
        request.files.get("pdf5"),
        request.files.get("pdf6"),
    ]
    pdf_attrs = ["pdf1_url", "pdf2_url", "pdf3_url", "pdf4_url", "pdf5_url", "pdf6_url"]
    for f, attr in zip(pdf_files, pdf_attrs):
        if f and f.filename:
            u = upload_to_firebase(f, "pdf")
            if u:
                setattr(ag, attr, u)

    db.commit()
    return redirect(url_for("admin_home"))


@app.post("/admin/<slug>/delete")
@admin_required
def delete_agent(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter(Agent.slug == slug).first()
    if ag:
        db.delete(ag)
        db.commit()
    return redirect(url_for("admin_home"))


# ================== CARD PUBBLICA ==================


@app.get("/<slug>")
def public_card(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        return render_template("404.html"), 404

    gallery = ag.gallery_urls.split("|") if ag.gallery_urls else []
    emails = [e.strip() for e in (ag.emails or "").split(",") if e.strip()]
    websites = [w.strip() for w in (ag.websites or "").split(",") if w.strip()]
    addresses = [a.strip() for a in (ag.addresses or "").split("\n") if a.strip()]

    pdf_urls = []
    for idx in range(1, 7):
        url = getattr(ag, f"pdf{idx}_url", None)
        if url:
            pdf_urls.append((idx, url))

    base = get_base_url()

    return render_template(
        "card.html",
        ag=ag,
        base_url=base,
        gallery=gallery,
        emails=emails,
        websites=websites,
        addresses=addresses,
        pdf_urls=pdf_urls,
    )


# ================== VCF & QR ==================


@app.get("/<slug>.vcf")
def vcard(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{ag.name}",
        f"N:{ag.name};;;;",
    ]
    if ag.role:
        lines.append(f"TITLE:{ag.role}")
    if ag.phone_mobile:
        lines.append(f"TEL;TYPE=CELL:{ag.phone_mobile}")
    if ag.phone_office:
        lines.append(f"TEL;TYPE=WORK:{ag.phone_office}")
    if ag.emails:
        for e in [x.strip() for x in ag.emails.split(",") if x.strip()]:
            lines.append(f"EMAIL;TYPE=WORK:{e}")
    if ag.websites:
        for w in [x.strip() for x in ag.websites.split(",") if x.strip()]:
            lines.append(f"URL:{w}")
    if ag.company:
        lines.append(f"ORG:{ag.company}")
    if ag.piva:
        lines.append(f"X-TAX-ID:{ag.piva}")
    if ag.sdi:
        lines.append(f"X-SDI-CODE:{ag.sdi}")

    note_parts = []
    if ag.piva:
        note_parts.append(f"Partita IVA: {ag.piva}")
    if ag.sdi:
        note_parts.append(f"SDI: {ag.sdi}")
    if note_parts:
        lines.append("NOTE:" + " | ".join(note_parts))

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


# ================== PDF & SITO (TORNA ALLA CARD) ==================


@app.get("/<slug>/pdf/<int:index>")
def pdf_view(slug, index):
    db = SessionLocal()
    ag = db.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    pdf_attr = f"pdf{index}_url"
    pdf_url = getattr(ag, pdf_attr, None)
    if not pdf_url:
        abort(404)

    html = """
    <!doctype html>
    <html lang="it">
    <head>
      <meta charset="utf-8">
      <title>Documento – {{ ag.name }}</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
      <style>
        body { margin:0; padding:0; background:#020617; }
        .pdf-frame { width:100%; height:calc(100vh - 60px); border:none; }
        .back-bar { padding:10px 14px; }
      </style>
    </head>
    <body>
      <div class="back-bar">
        <a href="{{ url_for('public_card', slug=ag.slug) }}" class="back-btn">← Torna alla card</a>
      </div>
      <iframe class="pdf-frame" src="{{ pdf_url }}"></iframe>
    </body>
    </html>
    """
    return render_template_string(html, ag=ag, pdf_url=pdf_url)


@app.get("/<slug>/site/<int:index>")
def site_view(slug, index):
    db = SessionLocal()
    ag = db.query(Agent).filter(Agent.slug == slug).first()
    if not ag:
        abort(404)

    websites = [w.strip() for w in (ag.websites or "").split(",") if w.strip()]
    if index < 0 or index >= len(websites):
        abort(404)

    site_url = websites[index]

    # niente iframe (Aruba lo blocca), solo bottone + link
    html = """
    <!doctype html>
    <html lang="it">
    <head>
      <meta charset="utf-8">
      <title>Sito – {{ ag.name }}</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
      <style>
        body { margin:0; padding:20px; background:#020617; color:#e5e7eb; font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", sans-serif; }
        .back-bar { margin-bottom:16px; }
        .site-link { margin-top:12px; }
        .site-link a { padding:10px 18px; border-radius:999px; border:1px solid rgba(148,163,184,0.8); background:rgba(15,23,42,0.95); color:#e5e7eb; text-decoration:none; }
      </style>
    </head>
    <body>
      <div class="back-bar">
        <a href="{{ url_for('public_card', slug=ag.slug) }}" class="back-btn">← Torna alla card</a>
      </div>
      <p>Per aprire il sito internet:</p>
      <div class="site-link">
        <a href="{{ site_url }}" target="_blank">Apri www</a>
      </div>
    </body>
    </html>
    """
    return render_template_string(html, ag=ag, site_url=site_url)


# ================== 404 ==================


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
