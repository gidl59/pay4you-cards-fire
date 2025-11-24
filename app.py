import os
import datetime
import io

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_file, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import qrcode

# ---------------------------------------------------------------------------
# App & Config
# ---------------------------------------------------------------------------

db = SQLAlchemy()
migrate = Migrate()


def create_app():
    app = Flask(__name__)

    # Secret key (per session e flash). In produzione mettila come variabile d'ambiente.
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key")

    # Database URL da variabile d'ambiente (Render -> Environment -> DATABASE_URL)
    db_url = os.environ.get("DATABASE_URL")

    # Render / alcuni provider usano ancora "postgres://" ma SQLAlchemy vuole "postgresql://"
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    if not db_url:
        # Fallback locale per sviluppo
        db_url = "sqlite:///card.db"

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Cartella per le immagini/foto agenti
    upload_folder = os.environ.get("UPLOAD_FOLDER", os.path.join(app.root_path, "uploads"))
    os.makedirs(upload_folder, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = upload_folder

    db.init_app(app)
    migrate.init_app(app, db)

    register_routes(app)

    return app


# ---------------------------------------------------------------------------
# Modelli
# ---------------------------------------------------------------------------


class Agent(db.Model):
    __tablename__ = "agents"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(120), nullable=True)
    company = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    whatsapp = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)

    photo_filename = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Agent {self.id} {self.name!r}>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def save_photo(app: Flask, file_storage):
    """Salva il file immagine caricato e restituisce il nome del file."""
    if not file_storage:
        return None
    if file_storage.filename == "":
        return None

    filename = file_storage.filename
    # in produzione puoi sanificare meglio il nome file
    upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file_storage.save(upload_path)
    return filename


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def register_routes(app: Flask):
    @app.route("/")
    def index():
        """Home semplice: reindirizza alla lista agenti oppure mostra landing."""
        agents = Agent.query.order_by(Agent.created_at.desc()).all()
        return render_template("index.html", agents=agents)

    # ----------------------- ADMIN: lista agenti ---------------------------

    @app.route("/admin/agents")
    def admin_agents():
        agents = Agent.query.order_by(Agent.created_at.desc()).all()
        return render_template("admin/agents_list.html", agents=agents)

    # ----------------------- ADMIN: nuovo agente ---------------------------

    @app.route("/admin/agents/new", methods=["GET", "POST"], endpoint="admin_new_agent")
    def admin_new_agent():
        if request.method == "POST":
            name = request.form.get("name") or ""
            slug = request.form.get("slug") or ""
            role = request.form.get("role")
            company = request.form.get("company")
            phone = request.form.get("phone")
            whatsapp = request.form.get("whatsapp")
            email = request.form.get("email")
            description = request.form.get("description")

            if not name or not slug:
                flash("Nome e slug sono obbligatori.", "danger")
                return redirect(url_for("admin_new_agent"))

            # Controllo slug unico
            existing = Agent.query.filter_by(slug=slug).first()
            if existing:
                flash("Slug già utilizzato. Scegline un altro.", "danger")
                return redirect(url_for("admin_new_agent"))

            photo_filename = None
            if "photo" in request.files:
                photo_file = request.files["photo"]
                photo_filename = save_photo(app, photo_file)

            agent = Agent(
                name=name,
                slug=slug,
                role=role,
                company=company,
                phone=phone,
                whatsapp=whatsapp,
                email=email,
                description=description,
                photo_filename=photo_filename,
            )
            db.session.add(agent)
            db.session.commit()
            flash("Agente creato con successo.", "success")
            return redirect(url_for("admin_agents"))

        # GET
        return render_template("admin/agent_form.html", agent=None, agent_id=None)

    # ----------------------- ADMIN: modifica agente ------------------------

    @app.route(
        "/admin/agents/<int:agent_id>/edit",
        methods=["GET", "POST"],
        endpoint="admin_edit_agent",
    )
    def admin_edit_agent(agent_id):
        agent = Agent.query.get_or_404(agent_id)

        if request.method == "POST":
            name = request.form.get("name") or ""
            slug = request.form.get("slug") or ""
            role = request.form.get("role")
            company = request.form.get("company")
            phone = request.form.get("phone")
            whatsapp = request.form.get("whatsapp")
            email = request.form.get("email")
            description = request.form.get("description")

            if not name or not slug:
                flash("Nome e slug sono obbligatori.", "danger")
                return redirect(url_for("admin_edit_agent", agent_id=agent.id))

            # Se lo slug è stato cambiato, controlliamo che non sia già usato da un altro
            existing = Agent.query.filter(Agent.slug == slug, Agent.id != agent.id).first()
            if existing:
                flash("Slug già utilizzato da un altro agente.", "danger")
                return redirect(url_for("admin_edit_agent", agent_id=agent.id))

            agent.name = name
            agent.slug = slug
            agent.role = role
            agent.company = company
            agent.phone = phone
            agent.whatsapp = whatsapp
            agent.email = email
            agent.description = description

            if "photo" in request.files:
                photo_file = request.files["photo"]
                if photo_file and photo_file.filename:
                    photo_filename = save_photo(app, photo_file)
                    agent.photo_filename = photo_filename

            db.session.commit()
            flash("Agente aggiornato con successo.", "success")
            return redirect(url_for("admin_agents"))

        # GET
        return render_template("admin/agent_form.html", agent=agent, agent_id=agent.id)

    # ----------------------- Scheda pubblica agente ------------------------

    @app.route("/a/<slug>", endpoint="public_card")
    def public_card(slug):
        agent = Agent.query.filter_by(slug=slug).first_or_404()
        return render_template("card.html", agent=agent)

    # ----------------------- VCF: biglietto da visita ----------------------

    @app.route("/admin/agents/<int:agent_id>/vcf")
    def agent_vcf(agent_id):
        agent = Agent.query.get_or_404(agent_id)

        vcf_lines = [
            "BEGIN:VCARD",
            "VERSION:3.0",
            f"FN:{agent.name}",
        ]
        if agent.company:
            vcf_lines.append(f"ORG:{agent.company}")
        if agent.phone:
            vcf_lines.append(f"TEL;TYPE=CELL:{agent.phone}")
        if agent.email:
            vcf_lines.append(f"EMAIL;TYPE=INTERNET:{agent.email}")
        vcf_lines.append("END:VCARD")

        vcf_data = "\r\n".join(vcf_lines)
        vcf_bytes = vcf_data.encode("utf-8")

        return send_file(
            io.BytesIO(vcf_bytes),
            mimetype="text/vcard",
            as_attachment=True,
            download_name=f"{agent.slug}.vcf",
        )

    # ----------------------- QR code per la card ---------------------------

    @app.route("/admin/agents/<int:agent_id>/qr")
    def agent_qr(agent_id):
        agent = Agent.query.get_or_404(agent_id)
        # URL pubblico della card
        card_url = url_for("public_card", slug=agent.slug, _external=True)

        qr_img = qrcode.make(card_url)
        img_io = io.BytesIO()
        qr_img.save(img_io, "PNG")
        img_io.seek(0)

        return send_file(img_io, mimetype="image/png")


# ---------------------------------------------------------------------------
# Entrypoint per esecuzione locale: `python app.py`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    flask_app = create_app()
    # debug=True solo in sviluppo
    flask_app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
