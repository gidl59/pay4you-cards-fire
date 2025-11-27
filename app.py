import os
import base64
from io import BytesIO
from datetime import datetime, timedelta
import uuid
import tempfile

from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, session, abort, Response
)
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import qrcode

load_dotenv()

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_BUCKET = os.getenv("FIREBASE_BUCKET")
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON")

app = Flask(__name__)
app.secret_key = APP_SECRET
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

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
    pdf1_url = Column(String, nullable=True)
    pdf2_url = Column(String, nullable=True)  # IBAN


Base.metadata.create_all(engine)


# --------------------------------------------------
# Upload helpers
# --------------------------------------------------
def save_cropped_image(data_url, folder="photos"):
    if not data_url:
        return None
    try:
        header, b64data = data_url.split(",", 1) if "," in data_url else ("", data_url)
        ext = ".png" if "png" in header.lower() else ".jpg"
        img_bytes = base64.b64decode(b64data)
        uploads_folder = os.path.join(app.static_folder, folder)
        os.makedirs(uploads_folder, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{ext}"
        fullpath = os.path.join(uploads_folder, filename)
        with open(fullpath, "wb") as f:
            f.write(img_bytes)
        return url_for("static", filename=f"{folder}/{filename}", _external=False)
    except Exception:
        return None


def upload_file(file_storage, folder="uploads"):
    if not file_storage or not file_storage.filename:
        return None
    try:
        uploads_folder = os.path.join(app.static_folder, folder)
        os.makedirs(uploads_folder, exist_ok=True)
        ext = os.path.splitext(file_storage.filename or "")[1].lower()
        filename = f"{uuid.uuid4().hex}{ext}"
        file_storage.save(os.path.join(uploads_folder, filename))
        return url_for("static", filename=f"{folder}/{filename}", _external=False)
    except Exception:
        return None


# --------------------------------------------------
# ADMIN ROUTES
# --------------------------------------------------
@app.get("/")
def home():
    if session.get("admin"):
        return redirect(url_for("admin_home"))
    return redirect(url_for("login"))


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


@app.get("/admin")
def admin_home():
    if not session.get("admin"):
        return redirect(url_for("login"))
    db = SessionLocal()
    agents = db.query(Agent).order_by(Agent.name).all()
    return render_template("admin_list.html", agents=agents)


# ---------- CREATE ----------
@app.get("/admin/new")
def new_agent():
    if not session.get("admin"):
        return redirect(url_for("login"))
    return render_template("agent_form.html", agent=None)


@app.post("/admin/new")
def create_agent():
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = SessionLocal()
    fields = ["slug","name","company","role","bio","phone_mobile","phone_office",
              "emails","websites","facebook","instagram","linkedin","tiktok",
              "telegram","whatsapp","pec","piva","sdi","addresses"]
    data = {k: request.form.get(k, "").strip() for k in fields}

    if not data["slug"] or not data["name"]:
        return "Slug e Nome sono obbligatori", 400
    if db.query(Agent).filter_by(slug=data["slug"]).first():
        return "Slug già esistente", 400

    iban = request.form.get("iban", "").strip()

    cropped = request.form.get("photo_cropped", "").strip()
    photo_url = save_cropped_image(cropped, "photos") if cropped else None
    if not photo_url:
        f = request.files.get("photo")
        if f and f.filename:
            photo_url = upload_file(f, "photos")

    pdf_urls = []
    for i in range(1,7):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u: pdf_urls.append(u)
    pdf_joined = "|".join(pdf_urls) if pdf_urls else None

    gallery_urls = []
    for f in request.files.getlist("gallery")[:12]:
        if f and f.filename:
            u = upload_file(f, "gallery")
            if u: gallery_urls.append(u)

    ag = Agent(**data,
               photo_url=photo_url,
               pdf1_url=pdf_joined,
               pdf2_url=iban,
               gallery_urls="|".join(gallery_urls) if gallery_urls else None)
    db.add(ag); db.commit()
    return redirect(url_for("admin_home"))


# ---------- EDIT ----------
@app.get("/admin/<slug>/edit")
def edit_agent(slug):
    if not session.get("admin"):
        return redirect(url_for("login"))
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first() or abort(404)
    return render_template("agent_form.html", agent=ag)


@app.post("/admin/<slug>/edit")
def update_agent(slug):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first() or abort(404)

    for k in ["slug","name","company","role","bio","phone_mobile","phone_office",
              "emails","websites","facebook","instagram","linkedin","tiktok",
              "telegram","whatsapp","pec","piva","sdi","addresses"]:
        setattr(ag, k, request.form.get(k,"").strip())

    ag.pdf2_url = request.form.get("iban","").strip()

    cropped = request.form.get("photo_cropped","").strip()
    if cropped:
        u = save_cropped_image(cropped,"photos")
        if u: ag.photo_url = u
    else:
        f = request.files.get("photo")
        if f and f.filename:
            u = upload_file(f,"photos")
            if u: ag.photo_url = u

    new_pdfs = []
    for i in range(1,7):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f,"pdf")
            if u: new_pdfs.append(u)
    if new_pdfs: ag.pdf1_url = "|".join(new_pdfs)

    gallery_files = request.files.getlist("gallery")
    if gallery_files and any(g.filename for g in gallery_files):
        urls = []
        for f in gallery_files[:12]:
            if f and f.filename:
                u = upload_file(f,"gallery")
                if u: urls.append(u)
        if urls: ag.gallery_urls = "|".join(urls)

    db.commit()
    return redirect(url_for("admin_home"))


@app.post("/admin/<slug>/delete")
def delete_agent(slug):
    if not session.get("admin"):
        return redirect(url_for("login"))
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if ag: db.delete(ag); db.commit()
    return redirect(url_for("admin_home"))


# --------------------------------------------------
# PUBLIC CARD
# --------------------------------------------------
@app.get("/<slug>")
def public_card(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first() or abort(404)

    gallery = ag.gallery_urls.split("|") if ag.gallery_urls else []
    emails = [x.strip() for x in (ag.emails or "").split(",") if x.strip()]
    websites = [x.strip() for x in (ag.websites or "").split(",") if x.strip()]
    addresses = [x.strip() for x in (ag.addresses or "").split("\n") if x.strip()]
    pdfs = [x.strip() for x in (ag.pdf1_url or "").split("|") if x.strip()]
    return render_template("card.html", ag=ag, emails=emails,
                           websites=websites, addresses=addresses,
                           gallery=gallery, pdfs=pdfs,
                           base_url=request.url_root.rstrip("/"))


# --------------------------------------------------
# VCARD + QR
# --------------------------------------------------
@app.get("/<slug>.vcf")
def vcard(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first() or abort(404)

    full = ag.name or ""
    fn = full.strip().split(" ",1)
    first = fn[0]; last = fn[1] if len(fn)==2 else ""

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{full}",
        f"N:{last};{first};;;",
    ]
    if ag.role: lines.append(f"TITLE:{ag.role}")
    if ag.phone_mobile: lines.append(f"TEL;TYPE=CELL:{ag.phone_mobile}")
    if ag.phone_office: lines.append(f"TEL;TYPE=WORK:{ag.phone_office}")

    if ag.emails:
        for e in [x.strip() for x in ag.emails.split(",") if x.strip()]:
            lines.append(f"EMAIL:{e}")

    if ag.websites:
        for w in [x.strip() for x in ag.websites.split(",") if x.strip()]:
            lines.append(f"URL:{w}")

    if ag.company: lines.append(f"ORG:{ag.company}")
    if ag.piva: lines.append(f"X-TAX-ID:{ag.piva}")
    if ag.sdi: lines.append(f"X-SDI-CODE:{ag.sdi}")
    if ag.pdf2_url: lines.append(f"X-IBAN:{ag.pdf2_url}")

    if ag.addresses:
        for a in [x.strip() for x in ag.addresses.split("\n") if x.strip()]:
            lines.append(f"ADR;TYPE=WORK:;;;{a};;;;")

    if ag.pdf2_url: lines.append(f"NOTE:IBAN {ag.pdf2_url}")
    lines.append("END:VCARD")

    resp = Response("\r\n".join(lines), mimetype="text/vcard")
    resp.headers["Content-Disposition"] = f'attachment; filename="{ag.slug}.vcf"'
    return resp


@app.get("/<slug>/qr.png")
def qr(slug):
    url = request.url_root.rstrip("/") + "/" + slug
    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404
