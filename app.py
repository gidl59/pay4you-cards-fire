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

app = Flask(__name__)
app.secret_key = APP_SECRET
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

DB_URL = "sqlite:////var/data/data.db"
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    company = Column(String)
    role = Column(String)
    bio = Column(Text)

    phone_mobile = Column(String)
    phone_office = Column(String)
    emails = Column(String)
    websites = Column(String)

    facebook = Column(String)
    instagram = Column(String)
    linkedin = Column(String)
    tiktok = Column(String)
    telegram = Column(String)
    whatsapp = Column(String)
    pec = Column(String)

    piva = Column(String)
    sdi = Column(String)
    addresses = Column(Text)

    photo_url = Column(String)
    extra_logo_url = Column(String)

    gallery_urls = Column(Text)
    pdf1_url = Column(Text)


Base.metadata.create_all(engine)


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def upload_file(file_storage, folder="uploads"):
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
    b = BASE_URL or ""
    if b:
        return b
    from flask import request
    return request.url_root.strip().rstrip("/")


@app.get("/")
def home():
    if session.get("admin"):
        return redirect(url_for("admin_home"))
    return redirect(url_for("login"))


@app.get("/login")
def login():
    return render_template("login.html")


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

    fields = [
        "slug","name","company","role","bio","phone_mobile","phone_office",
        "emails","websites","facebook","instagram","linkedin","tiktok",
        "telegram","whatsapp","pec","piva","sdi","addresses"
    ]

    data = {k: request.form.get(k, "").strip() for k in fields}

    photo = request.files.get("photo")
    extra_logo = request.files.get("extra_logo")
    gallery_files = request.files.getlist("gallery")

    photo_url = upload_file(photo, "photos") if photo else None
    extra_logo_url = upload_file(extra_logo, "logos") if extra_logo else None

    # ===== PDF CON NOME ORIGINALE =====
    pdf_urls = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_urls.append(f"{f.filename}||{u}")

    pdf_joined = "|".join(pdf_urls) if pdf_urls else None

    # ===== GALLERIA FINO A 20 =====
    gallery_urls = []
    for f in gallery_files[:20]:
        if f and f.filename:
            u = upload_file(f, "gallery")
            if u:
                gallery_urls.append(u)

    ag = Agent(
        **data,
        photo_url=photo_url,
        extra_logo_url=extra_logo_url,
        pdf1_url=pdf_joined,
        gallery_urls="|".join(gallery_urls) if gallery_urls else None,
    )

    db.add(ag)
    db.commit()
    return redirect(url_for("admin_home"))


@app.get("/admin/<slug>/edit")
@admin_required
def edit_agent(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    return render_template("agent_form.html", agent=ag)


@app.post("/admin/<slug>/edit")
@admin_required
def update_agent(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()

    for k in ag.__table__.columns.keys():
        if k in request.form:
            setattr(ag, k, request.form.get(k))

    gallery_files = request.files.getlist("gallery")
    if gallery_files and gallery_files[0].filename:
        urls = []
        for f in gallery_files[:20]:
            u = upload_file(f, "gallery")
            if u:
                urls.append(u)
        ag.gallery_urls = "|".join(urls)

    pdf_urls = []
    for i in range(1, 13):
        f = request.files.get(f"pdf{i}")
        if f and f.filename:
            u = upload_file(f, "pdf")
            if u:
                pdf_urls.append(f"{f.filename}||{u}")

    if pdf_urls:
        ag.pdf1_url = "|".join(pdf_urls)

    db.commit()
    return redirect(url_for("admin_home"))


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

    pdfs = []
    for item in (ag.pdf1_url or "").split("|"):
        if "||" in item:
            name, url = item.split("||", 1)
            pdfs.append({"name": name, "url": url})

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


@app.get("/<slug>/qr.png")
def qr(slug):
    base = get_base_url()
    url = f"{base}/{slug}"
    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")
