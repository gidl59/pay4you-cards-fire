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
import urllib.parse

load_dotenv()

APP_SECRET = os.getenv("APP_SECRET", "dev_secret")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")

app = Flask(__name__)
app.secret_key = APP_SECRET

DB_URL = "sqlite:////var/data/data.db"
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ---------------- MODELS ----------------

class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    company = Column(String)
    role = Column(String)
    bio = Column(Text)
    phone_mobile = Column(String)
    phone_mobile2 = Column(String)
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
    video_urls = Column(Text)
    pdf1_url = Column(Text)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password = Column(String)
    role = Column(String)          # admin | client
    agent_slug = Column(String)    # slug associato

Base.metadata.create_all(engine)

# ---------------- HELPERS ----------------

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrap(*a, **kw):
        if session.get("role") != "admin":
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrap

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrap(*a, **kw):
        if not session.get("username"):
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrap

def upload_file(file_storage, folder="uploads"):
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1]
    path = os.path.join(app.static_folder, folder)
    os.makedirs(path, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    file_storage.save(os.path.join(path, name))
    return url_for("static", filename=f"{folder}/{name}")

def get_base_url():
    return BASE_URL if BASE_URL else request.url_root.strip().rstrip("/")

# ---------------- LOGIN ----------------

@app.get("/login")
def login():
    return render_template("login.html", error=None)

@app.post("/login")
def login_post():
    username = request.form.get("username")
    password = request.form.get("password")

    db = SessionLocal()
    user = db.query(User).filter_by(username=username, password=password).first()

    if not user:
        return render_template("login.html", error="Credenziali errate")

    session["username"] = user.username
    session["role"] = user.role
    session["agent_slug"] = user.agent_slug

    if user.role == "admin":
        return redirect("/admin")
    else:
        return redirect("/me/edit")

@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------- ADMIN ----------------

@app.get("/admin")
@admin_required
def admin_home():
    db = SessionLocal()
    agents = db.query(Agent).all()
    return render_template("admin_list.html", agents=agents)

# CREA AGENTE (ADMIN)
@app.post("/admin/new")
@admin_required
def create_agent():
    db = SessionLocal()
    slug = request.form.get("slug")
    name = request.form.get("name")

    ag = Agent(slug=slug, name=name)
    db.add(ag)

    # crea anche utente cliente
    password = uuid.uuid4().hex[:8]
    user = User(username=slug, password=password, role="client", agent_slug=slug)
    db.add(user)

    db.commit()
    return f"Cliente creato.<br>Username: {slug}<br>Password: {password}"

# ---------------- CLIENT ----------------

@app.get("/me/edit")
@login_required
def client_edit():
    slug = session.get("agent_slug")
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    return render_template("agent_form.html", agent=ag)

@app.post("/me/edit")
@login_required
def client_update():
    slug = session.get("agent_slug")
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()

    ag.name = request.form.get("name")
    ag.company = request.form.get("company")
    ag.phone_mobile = request.form.get("phone_mobile")
    ag.whatsapp = request.form.get("whatsapp")
    ag.bio = request.form.get("bio")

    db.commit()
    return redirect("/me/edit")

# ---------------- CARD PUBBLICA ----------------

@app.get("/<slug>")
def public_card(slug):
    db = SessionLocal()
    ag = db.query(Agent).filter_by(slug=slug).first()
    if not ag:
        abort(404)
    return render_template("card.html", ag=ag, base_url=get_base_url())

# ---------------- QR ----------------

@app.get("/<slug>/qr.png")
def qr(slug):
    url = f"{get_base_url()}/{slug}"
    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
