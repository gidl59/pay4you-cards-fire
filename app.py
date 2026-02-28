import os
import json
import base64
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_from_directory, make_response, flash
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.jinja_env.add_extension('jinja2.ext.do')
app.secret_key = "pay4you_final_fix_v8"

# ===== CONFIG =====
if os.path.exists('/var/data'):
    BASE_DIR = '/var/data'
else:
    BASE_DIR = os.path.join(os.getcwd(), 'static')

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_FILE = os.path.join(BASE_DIR, 'clients.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024

# ===== ENV CONFIG =====
CARD_BASE_URL = os.getenv("CARD_BASE_URL", "https://pay4you-cards-fire.onrender.com").rstrip("/")

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587").strip() or "587")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER).strip()
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Pay4You").strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1").strip() == "1"

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()

# Branding email
BRAND_NAME = os.getenv("BRAND_NAME", "Pay4You").strip()
BRAND_SITE = os.getenv("BRAND_SITE", "https://www.pay4you.store").strip()
BRAND_EMAIL = os.getenv("BRAND_EMAIL", "info@pay4you.store").strip()
BRAND_PHONE = os.getenv("BRAND_PHONE", "+39 0541 1646895").strip()
BRAND_LOGO_URL = os.getenv("BRAND_LOGO_URL", "").strip()  # opzionale: se la metti, mostra il logo in mail

# ===== DB =====
def load_db():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_db(data):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Errore DB: {e}")

# ===== FILES =====
def save_file(file, prefix):
    if file and file.filename:
        filename = secure_filename(f"{prefix}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return f"/uploads/{filename}"
    return None

# ===== HELPERS =====
def to_int(v, d=50):
    try:
        return int(float(v))
    except:
        return d

def to_float(v, d=1.0):
    try:
        return float(v)
    except:
        return d

def normalize_phone(phone: str) -> str:
    """
    Accetta:
    - +39333...
    - 39333...
    - 333...
    - whatsapp:+39333...
    e restituisce sempre un numero in formato +39...
    """
    phone = str(phone or "").strip()
    if not phone:
        return ""

    phone = phone.replace("whatsapp:", "", 1)
    phone = phone.replace(" ", "").replace("-", "").replace("/", "").replace(".", "")

    # lascia solo + e cifre
    cleaned = []
    for i, ch in enumerate(phone):
        if ch.isdigit():
            cleaned.append(ch)
        elif ch == '+' and i == 0:
            cleaned.append(ch)
    phone = "".join(cleaned)

    if not phone:
        return ""

    # 0039.... -> +39....
    if phone.startswith("00"):
        phone = "+" + phone[2:]

    # 39.... senza +
    if phone.startswith("39") and not phone.startswith("+39"):
        phone = "+" + phone

    # numero italiano senza prefisso
    if not phone.startswith("+"):
        # se è verosimilmente un cellulare/numero IT
        if len(phone) >= 9:
            phone = "+39" + phone

    return phone

def repair_user(user):
    dirty = False

    if 'default_profile' not in user:
        user['default_profile'] = 'p1'
        dirty = True

    if 'admin_contact' not in user or not isinstance(user['admin_contact'], dict):
        user['admin_contact'] = {'email': '', 'whatsapp': ''}
        dirty = True
    else:
        if 'email' not in user['admin_contact']:
            user['admin_contact']['email'] = ''
            dirty = True
        if 'whatsapp' not in user['admin_contact']:
            user['admin_contact']['whatsapp'] = ''
            dirty = True

    for pid in ['p1', 'p2', 'p3']:
        if pid not in user:
            user[pid] = {'active': False}
            dirty = True

        p = user[pid]
        defaults = {
            'name': '', 'role': '', 'company': '', 'bio': '',
            'foto': '', 'logo': '', 'personal_foto': '',
            'office_phone': '', 'address': '',
            'mobiles': [], 'emails': [], 'websites': [], 'socials': [],
            'gallery_img': [], 'gallery_vid': [], 'gallery_pdf': [],
            'piva': '', 'cod_sdi': '', 'pec': '',
            'fx_rotate_logo': 'off', 'fx_rotate_agent': 'off',
            'fx_interaction': 'tap', 'fx_back_content': 'logo',
            'pos_x': 50, 'pos_y': 50, 'zoom': 1.0,
            'trans': {'en': {}, 'fr': {}, 'es': {}, 'de': {}}
        }

        for k, v in defaults.items():
            if k not in p:
                p[k] = v
                dirty = True

        if not isinstance(p.get('emails'), list):
            p['emails'] = []
            dirty = True
        if not isinstance(p.get('websites'), list):
            p['websites'] = []
            dirty = True
        if p.get('socials') is None:
            p['socials'] = []
            dirty = True
        if p.get('trans') is None or not isinstance(p.get('trans'), dict):
            p['trans'] = defaults['trans']
            dirty = True
        if p.get('gallery_img') is None:
            p['gallery_img'] = []
            dirty = True
        if p.get('gallery_vid') is None:
            p['gallery_vid'] = []
            dirty = True
        if p.get('gallery_pdf') is None:
            p['gallery_pdf'] = []
            dirty = True

        p['pos_x'] = to_int(p.get('pos_x', 50), 50)
        p['pos_y'] = to_int(p.get('pos_y', 50), 50)
        p['zoom'] = to_float(p.get('zoom', 1.0), 1.0)

    return dirty

# ===== CREDENTIALS =====
def build_credentials_data(user: dict) -> dict:
    slug = (user.get("slug") or "").strip()
    username = (user.get("username") or slug).strip()
    password = (user.get("password") or "").strip()

    login_url = f"{CARD_BASE_URL}/area/login"
    public_url = f"{CARD_BASE_URL}/card/{slug}"

    return {
        "slug": slug,
        "username": username,
        "password": password,
        "login_url": login_url,
        "public_url": public_url
    }

def build_credentials_email_html(user: dict) -> str:
    cd = build_credentials_data(user)

    logo_html = ""
    if BRAND_LOGO_URL:
        logo_html = f"""
        <div style="text-align:center; padding:18px 0 10px;">
          <img src="{BRAND_LOGO_URL}" alt="{BRAND_NAME}" style="max-width:180px; height:auto; display:inline-block;">
        </div>
        """

    return f"""
    <div style="margin:0; padding:0; background:#f3f3f3;">
      <div style="max-width:760px; margin:0 auto; background:#0b0b0b; color:#ffffff; font-family:Arial,Helvetica,sans-serif;">

        {logo_html}

        <div style="padding:24px 22px 8px;">
          <h1 style="margin:0 0 16px; color:#f6d47a; font-size:20px;">Credenziali della tua Card Digitale</h1>

          <p style="margin:0 0 14px; font-size:16px; line-height:1.6;">
            Ciao! Abbiamo preparato le credenziali per gestire la tua nuova <strong>Card Digitale {BRAND_NAME}</strong>.
          </p>

          <p style="margin:0 0 18px; font-size:16px; line-height:1.6;">
            Qui sotto trovi tutti i dati utili per accedere, modificare la card e condividere il tuo link pubblico.
          </p>
        </div>

        <div style="padding:0 14px 14px;">
          <div style="background:#111111; border:1px solid #3a2d16; border-radius:16px; padding:18px;">
            <div style="color:#58d5ff; font-size:18px; font-weight:700; margin-bottom:12px;">Riepilogo accesso</div>

            <div style="font-size:16px; line-height:1.7;">
              <div><strong>Login:</strong> <a href="{cd['login_url']}" style="color:#66cfff;">{cd['login_url']}</a></div>
              <div><strong>Username:</strong> {cd['username']}</div>
              <div><strong>Password:</strong> {cd['password']}</div>
              <div style="margin-top:10px;"><strong>Link pubblico:</strong> <a href="{cd['public_url']}" style="color:#66cfff;">{cd['public_url']}</a></div>
            </div>
          </div>
        </div>

        <div style="padding:0 14px 14px;">
          <div style="background:#1a1710; border:1px solid #47391b; border-radius:16px; padding:18px;">
            <div style="color:#f6d47a; font-size:18px; font-weight:700; margin-bottom:12px;">Consiglio utile</div>
            <div style="font-size:16px; line-height:1.6; color:#f0f0f0;">
              Salva questi dati e cambia la password al primo accesso.
            </div>
          </div>
        </div>

        <div style="padding:0 14px 14px;">
          <div style="background:#111111; border:1px solid #2a2a2a; border-radius:16px; padding:18px;">
            <div style="color:#58d5ff; font-size:18px; font-weight:700; margin-bottom:12px;">Contatti {BRAND_NAME}</div>
            <div style="font-size:16px; line-height:1.8;">
              <div>📧 <a href="mailto:{BRAND_EMAIL}" style="color:#66cfff;">{BRAND_EMAIL}</a></div>
              <div>📞 {BRAND_PHONE}</div>
              <div>🌐 <a href="{BRAND_SITE}" style="color:#66cfff;">{BRAND_SITE}</a></div>
            </div>
          </div>
        </div>

        <div style="padding:18px 22px 28px; color:#bdbdbd; font-size:13px; text-align:center;">
          © 2026 {BRAND_NAME}
        </div>
      </div>
    </div>
    """

def build_credentials_email_text(user: dict) -> str:
    cd = build_credentials_data(user)
    return (
        "Pay4You - Credenziali Accesso\n\n"
        "Ciao!\n\n"
        "Ecco le tue credenziali per gestire la tua nuova Card Digitale Pay4You.\n\n"
        "Ti preghiamo di accedere e compilare i tuoi dati.\n\n"
        f"LOGIN (Per modificare):\n{cd['login_url']}\n"
        f"USER: {cd['username']}\n"
        f"PASSWORD: {cd['password']}\n\n"
        f"IL TUO LINK PUBBLICO:\n{cd['public_url']}\n\n"
        "Consiglio: salva questi dati e cambia la password al primo accesso."
    )

def build_credentials_whatsapp_text(user: dict) -> str:
    cd = build_credentials_data(user)
    return (
        "Pay4You - Credenziali Accesso\n\n"
        "Ciao! Ecco le credenziali della tua nuova Card Digitale Pay4You.\n\n"
        f"LOGIN: {cd['login_url']}\n"
        f"USER: {cd['username']}\n"
        f"PASSWORD: {cd['password']}\n\n"
        f"LINK PUBBLICO: {cd['public_url']}\n\n"
        "Consiglio: salva questi dati e cambia la password al primo accesso."
    )

# ===== SENDERS =====
def send_email_smtp(to_email: str, subject: str, html_body: str, text_body: str = ""):
    if not SMTP_HOST or not SMTP_PORT or not SMTP_FROM:
        raise Exception("SMTP non configurato. Imposta SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS e SMTP_FROM.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM}>"
    msg["To"] = to_email

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
    try:
        server.ehlo()
        if SMTP_USE_TLS:
            server.starttls()
            server.ehlo()
        if SMTP_USER and SMTP_PASS:
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_FROM, [to_email], msg.as_string())
    finally:
        try:
            server.quit()
        except:
            pass

def send_whatsapp_twilio(to_phone: str, body: str):
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_WHATSAPP_FROM:
        raise Exception("Twilio non configurato. Imposta TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN e TWILIO_WHATSAPP_FROM.")

    to_phone = normalize_phone(to_phone)
    if not to_phone.startswith("+"):
        raise Exception("Numero WhatsApp destinatario non valido.")

    api_url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    post_data = urlencode({
        "From": TWILIO_WHATSAPP_FROM,
        "To": f"whatsapp:{to_phone}",
        "Body": body
    }).encode("utf-8")

    auth_raw = f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode("utf-8")
    auth_b64 = base64.b64encode(auth_raw).decode("ascii")

    req = Request(api_url, data=post_data)
    req.add_header("Authorization", f"Basic {auth_b64}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return raw
    except HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        raise Exception(f"Errore Twilio HTTP {e.code}: {err}")
    except URLError as e:
        raise Exception(f"Errore rete Twilio: {e}")

def get_user_by_id(clienti, user_id):
    return next((c for c in clienti if c.get('id') == user_id), None)

# ===== VCF =====
def vcf_escape(s: str) -> str:
    s = str(s or "").replace("\\", "\\\\").replace("\r", " ").replace("\n", " ").replace(";", r"\;").replace(",", r"\,")
    return s.strip()

def guess_mime_from_filename(fn: str) -> str:
    return "PNG" if (fn or "").lower().endswith(".png") else "JPEG"

def file_path_from_url(url_path: str) -> str:
    if not url_path:
        return ""
    path = urlparse(url_path).path
    if path.startswith("/uploads/"):
        filename = path.split("/uploads/", 1)[1]
        return os.path.join(app.config["UPLOAD_FOLDER"], filename)
    return ""

@app.route('/vcf/<slug>')
def download_vcf(slug):
    clienti = load_db()
    user = next((c for c in clienti if c.get('slug') == slug), None)
    if not user:
        return "Utente non trovato", 404

    p_req = request.args.get('p', user.get('default_profile', 'p1'))
    if p_req == 'menu':
        p_req = 'p1'
    if not user.get(p_req, {}).get('active'):
        p_req = 'p1'
    p = user[p_req]

    full_card_url = request.url_root.rstrip("/") + f"/card/{slug}"
    branded_url_label = "CARD DIGITALE PAY4YOU"

    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    n_val = (p.get('name') or 'Contatto').strip()
    lines.append(f"FN:{vcf_escape(n_val)}")
    lines.append(f"N:{vcf_escape(n_val)};;;;")

    if p.get('company'):
        lines.append(f"ORG:{vcf_escape(p.get('company'))}")
    if p.get('role'):
        lines.append(f"TITLE:{vcf_escape(p.get('role'))}")

    for m in p.get('mobiles', []) or []:
        if m:
            lines.append(f"TEL;TYPE=CELL:{vcf_escape(m)}")
    if p.get('office_phone'):
        lines.append(f"TEL;TYPE=WORK,VOICE:{vcf_escape(p.get('office_phone'))}")

    email_list = p.get('emails', []) or []
    email_idx = 2
    if isinstance(email_list, list):
        for e_item in email_list:
            for e in str(e_item).split(','):
                e = e.strip()
                if e:
                    lines.append(f"item{email_idx}.EMAIL:{vcf_escape(e)}")
                    lines.append(f"item{email_idx}.X-ABLabel:MAIL")
                    email_idx += 1

    web_list = p.get('websites', []) or []
    if isinstance(web_list, list):
        for w_item in web_list:
            for w in str(w_item).split(','):
                w = w.strip()
                if not w:
                    continue
                if not w.startswith("http"):
                    w = "https://" + w
                lines.append(f"URL:{vcf_escape(w)}")

    lines.append(f"item1.URL:{vcf_escape(full_card_url)}")
    lines.append(f"item1.X-ABLabel:{vcf_escape(branded_url_label)}")

    if p.get('address'):
        addr = str(p.get('address')).replace(',', ' ').strip()
        lines.append(f"ADR;TYPE=WORK:;;{vcf_escape(addr)};;;;")

    socials = p.get('socials', []) or []
    idx = max(email_idx, 3)
    for s in socials:
        try:
            label = (s.get("label") or "").strip()
            url = (s.get("url") or "").strip()
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://" + url
            lines.append(f"item{idx}.URL:{vcf_escape(url)}")
            lines.append(f"item{idx}.X-ABLabel:{vcf_escape(label)}")
            idx += 1
        except:
            continue

    note_parts = []
    if p.get('bio'):
        note_parts.append(str(p.get('bio')).strip())
    if p.get('piva'):
        note_parts.append(f"P.IVA: {p.get('piva')}")
    if p.get('cod_sdi'):
        note_parts.append(f"SDI: {p.get('cod_sdi')}")
    if note_parts:
        lines.append(f"NOTE:{vcf_escape(' | '.join(note_parts))}")

    foto_url = p.get('foto')
    fp = file_path_from_url(foto_url)
    if fp and os.path.exists(fp):
        try:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            lines.append(f"PHOTO;ENCODING=b;TYPE={guess_mime_from_filename(fp)}:{b64}")
        except:
            pass

    lines.append("END:VCARD")
    response = make_response("\r\n".join(lines) + "\r\n")
    response.headers["Content-Disposition"] = f"attachment; filename={slug}.vcf"
    response.headers["Content-Type"] = "text/vcard; charset=utf-8"
    return response

# ===== ROUTES =====
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        clienti = load_db()
        user = next((c for c in clienti if c.get('username') == u and c.get('password') == p), None)
        if user:
            session['logged_in'] = True
            session['user_id'] = user['id']
            if repair_user(user):
                save_db(clienti)
            return redirect(url_for('area'))
    return render_template('login.html')

@app.route('/area')
def area():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    user = next((c for c in load_db() if c.get('id') == session.get('user_id')), None)
    if not user:
        return redirect(url_for('logout'))
    return render_template('dashboard.html', user=user)

@app.route('/area/activate/<p_id>')
def activate_profile(p_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    clienti = load_db()
    user = get_user_by_id(clienti, session.get('user_id'))
    if not user:
        return redirect(url_for('logout'))
    user['p' + p_id]['active'] = True
    repair_user(user)
    save_db(clienti)
    return redirect(url_for('area'))

@app.route('/area/deactivate/<p_id>')
def deactivate_profile(p_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if p_id == '1':
        return "Impossibile"
    clienti = load_db()
    user = get_user_by_id(clienti, session.get('user_id'))
    if not user:
        return redirect(url_for('logout'))
    user['p' + p_id]['active'] = False
    if user.get('default_profile') == ('p' + p_id):
        user['default_profile'] = 'p1'
    save_db(clienti)
    return redirect(url_for('area'))

@app.route('/area/set_default/<mode>')
def set_default_profile(mode):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    clienti = load_db()
    user = get_user_by_id(clienti, session.get('user_id'))
    if not user:
        return redirect(url_for('logout'))

    if mode.startswith('p') and user.get(mode, {}).get('active'):
        user['default_profile'] = mode
    elif mode == 'menu':
        user['default_profile'] = 'menu'

    save_db(clienti)
    return redirect(url_for('area'))

@app.route('/area/edit/<p_id>', methods=['GET', 'POST'])
def edit_profile(p_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    clienti = load_db()
    user = get_user_by_id(clienti, session.get('user_id'))
    if not user:
        return redirect(url_for('logout'))
    if repair_user(user):
        save_db(clienti)

    p_key = 'p' + p_id
    if not user[p_key].get('active'):
        user[p_key]['active'] = True
        save_db(clienti)

    if request.method == 'POST':
        p = user[p_key]
        prefix = f"u{user['id']}_{p_id}"

        p['name'] = request.form.get('name', '')
        p['role'] = request.form.get('role', '')
        p['company'] = request.form.get('company', '')
        p['bio'] = request.form.get('bio', '')
        p['piva'] = request.form.get('piva', '')
        p['cod_sdi'] = request.form.get('cod_sdi', '')
        p['pec'] = request.form.get('pec', '')
        p['office_phone'] = request.form.get('office_phone', '')
        p['address'] = request.form.get('address', '')

        p['mobiles'] = [x for x in [request.form.get('mobile1'), request.form.get('mobile2')] if x]
        p['emails'] = [x for x in [request.form.get('email1')] if x]
        p['websites'] = [x for x in [request.form.get('website')] if x]

        socials = []
        for soc in ['Facebook', 'Instagram', 'Linkedin', 'TikTok', 'Spotify', 'Telegram', 'YouTube']:
            url = (request.form.get(soc.lower()) or '').strip()
            if url:
                socials.append({'label': soc, 'url': url})
        p['socials'] = socials

        p['fx_rotate_logo'] = 'on' if request.form.get('fx_rotate_logo') else 'off'
        p['fx_rotate_agent'] = 'on' if request.form.get('fx_rotate_agent') else 'off'
        p['fx_interaction'] = request.form.get('fx_interaction', 'tap')
        p['fx_back_content'] = request.form.get('fx_back_content', 'logo')
        if p['fx_rotate_agent'] == 'on':
            p['fx_interaction'] = 'tap'

        p['pos_x'] = to_int(request.form.get('pos_x', 50), 50)
        p['pos_y'] = to_int(request.form.get('pos_y', 50), 50)
        p['zoom'] = to_float(request.form.get('zoom', 1), 1.0)

        p['trans'] = {
            'en': {'role': request.form.get('role_en', ''), 'bio': request.form.get('bio_en', '')},
            'fr': {'role': request.form.get('role_fr', ''), 'bio': request.form.get('bio_fr', '')},
            'es': {'role': request.form.get('role_es', ''), 'bio': request.form.get('bio_es', '')},
            'de': {'role': request.form.get('role_de', ''), 'bio': request.form.get('bio_de', '')}
        }

        if 'foto' in request.files:
            path = save_file(request.files['foto'], f"{prefix}_foto")
            if path:
                p['foto'] = path
        if 'logo' in request.files:
            path = save_file(request.files['logo'], f"{prefix}_logo")
            if path:
                p['logo'] = path
        if 'personal_foto' in request.files:
            path = save_file(request.files['personal_foto'], f"{prefix}_pers")
            if path:
                p['personal_foto'] = path

        if 'gallery_img' in request.files:
            for f in request.files.getlist('gallery_img'):
                path = save_file(f, f"{prefix}_gimg")
                if path:
                    p['gallery_img'].append(path)
        if 'gallery_pdf' in request.files:
            for f in request.files.getlist('gallery_pdf'):
                path = save_file(f, f"{prefix}_gpdf")
                if path:
                    p['gallery_pdf'].append({'path': path, 'name': f.filename})
        if 'gallery_vid' in request.files:
            for f in request.files.getlist('gallery_vid'):
                path = save_file(f, f"{prefix}_gvid")
                if path:
                    p['gallery_vid'].append(path)

        if request.form.get('delete_media'):
            to_del = request.form.getlist('delete_media')
            p['gallery_img'] = [x for x in p.get('gallery_img', []) if x not in to_del]
            p['gallery_pdf'] = [x for x in p.get('gallery_pdf', []) if x.get('path') not in to_del]
            p['gallery_vid'] = [x for x in p.get('gallery_vid', []) if x not in to_del]

        repair_user(user)
        save_db(clienti)
        return redirect(url_for('area'))

    return render_template('edit_card.html', p=user[p_key], p_id=p_id)

@app.route('/master', methods=['GET', 'POST'])
def master_login():
    if session.get('is_master'):
        clienti = load_db()
        dirty = False
        for c in clienti:
            if repair_user(c):
                dirty = True
        if dirty:
            save_db(clienti)
        return render_template('master_dashboard.html', clienti=clienti, files=[])

    if request.method == 'POST' and request.form.get('username') == "admin" and request.form.get('password') == "Peppone16@":
        session['is_master'] = True
        return redirect(url_for('master_login'))

    return render_template('master_login.html')

@app.route('/master/add', methods=['POST'])
def master_add():
    if not session.get('is_master'):
        return redirect(url_for('master_login'))

    clienti = load_db()

    slug = (request.form.get('slug') or '').strip().lower()
    admin_email = (request.form.get('admin_email') or '').strip()
    admin_whatsapp = normalize_phone(request.form.get('admin_whatsapp') or '')

    if not slug or not admin_email or not admin_whatsapp:
        flash("Errore: Tutti i campi (Slug, Email, WhatsApp) sono obbligatori.", "error")
        return redirect(url_for('master_login'))

    if any(c.get('slug') == slug for c in clienti):
        flash(f"Errore: Lo slug '{slug}' è già in uso. Scegline un altro.", "error")
        return redirect(url_for('master_login'))

    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(random.choice(chars) for i in range(12))
    new_id = max([c['id'] for c in clienti], default=0) + 1

    new_client = {
        "id": new_id,
        "slug": slug,
        "username": slug,
        "password": password,
        "admin_contact": {
            "email": admin_email,
            "whatsapp": admin_whatsapp
        },
        "p1": {"active": True},
        "p2": {"active": False},
        "p3": {"active": False},
        "default_profile": "p1"
    }

    repair_user(new_client)
    clienti.append(new_client)
    save_db(clienti)

    flash(f"Card '{slug}' creata con successo!", "success")
    return redirect(url_for('master_login'))

@app.route('/master/credentials/<int:id>')
def master_credentials(id):
    if not session.get('is_master'):
        return redirect(url_for('master_login'))

    clienti = load_db()
    user = get_user_by_id(clienti, id)
    if not user:
        flash("Card non trovata.", "error")
        return redirect(url_for('master_login'))

    cd = build_credentials_data(user)
    recipient_email = (user.get('admin_contact', {}) or {}).get('email', '')
    recipient_whatsapp = (user.get('admin_contact', {}) or {}).get('whatsapp', '')

    return render_template(
        'credentials.html',
        user=user,
        slug=cd['slug'],
        username=cd['username'],
        password=cd['password'],
        login_url=cd['login_url'],
        public_url=cd['public_url'],
        recipient_email=recipient_email,
        recipient_whatsapp=recipient_whatsapp,
        email_subject="Pay4You - Credenziali Accesso",
        whatsapp_text=build_credentials_whatsapp_text(user),
        email_text=build_credentials_email_text(user),
    )

@app.route('/master/send-credentials-email/<int:id>')
def master_send_credentials_email(id):
    if not session.get('is_master'):
        return redirect(url_for('master_login'))

    clienti = load_db()
    user = get_user_by_id(clienti, id)
    if not user:
        flash("Card non trovata.", "error")
        return redirect(url_for('master_login'))

    to_email = ((user.get('admin_contact', {}) or {}).get('email') or '').strip()
    if not to_email:
        flash("Nessuna email destinatario presente nella card.", "error")
        return redirect(url_for('master_login'))

    try:
        send_email_smtp(
            to_email=to_email,
            subject="Pay4You - Credenziali Accesso",
            html_body=build_credentials_email_html(user),
            text_body=build_credentials_email_text(user)
        )
        flash(f"Email inviata con successo a {to_email}", "success")
    except Exception as e:
        flash(f"Errore invio email: {e}", "error")

    return redirect(url_for('master_login'))

@app.route('/master/send-credentials-whatsapp/<int:id>')
def master_send_credentials_whatsapp(id):
    if not session.get('is_master'):
        return redirect(url_for('master_login'))

    clienti = load_db()
    user = get_user_by_id(clienti, id)
    if not user:
        flash("Card non trovata.", "error")
        return redirect(url_for('master_login'))

    to_phone = ((user.get('admin_contact', {}) or {}).get('whatsapp') or '').strip()
    if not to_phone:
        flash("Nessun numero WhatsApp destinatario presente nella card.", "error")
        return redirect(url_for('master_login'))

    try:
        result = send_whatsapp_twilio(
            to_phone=to_phone,
            body=build_credentials_whatsapp_text(user)
        )
        print("Twilio result:", result)
        flash(f"WhatsApp inviato con successo a {normalize_phone(to_phone)}", "success")
    except Exception as e:
        flash(f"Errore invio WhatsApp: {e}", "error")

    return redirect(url_for('master_login'))

@app.route('/master/send-credentials-all/<int:id>')
def master_send_credentials_all(id):
    if not session.get('is_master'):
        return redirect(url_for('master_login'))

    clienti = load_db()
    user = get_user_by_id(clienti, id)
    if not user:
        flash("Card non trovata.", "error")
        return redirect(url_for('master_login'))

    to_email = ((user.get('admin_contact', {}) or {}).get('email') or '').strip()
    to_phone = ((user.get('admin_contact', {}) or {}).get('whatsapp') or '').strip()

    email_ok = False
    wa_ok = False
    errors = []

    if to_email:
        try:
            send_email_smtp(
                to_email=to_email,
                subject="Pay4You - Credenziali Accesso",
                html_body=build_credentials_email_html(user),
                text_body=build_credentials_email_text(user)
            )
            email_ok = True
        except Exception as e:
            errors.append(f"Email: {e}")
    else:
        errors.append("Email: destinatario mancante")

    if to_phone:
        try:
            send_whatsapp_twilio(
                to_phone=to_phone,
                body=build_credentials_whatsapp_text(user)
            )
            wa_ok = True
        except Exception as e:
            errors.append(f"WhatsApp: {e}")
    else:
        errors.append("WhatsApp: numero mancante")

    if email_ok and wa_ok:
        flash("Credenziali inviate con successo via Email + WhatsApp.", "success")
    elif email_ok and not wa_ok:
        flash("Email inviata. WhatsApp non inviato.", "error")
        for err in errors:
            flash(err, "error")
    elif wa_ok and not email_ok:
        flash("WhatsApp inviato. Email non inviata.", "error")
        for err in errors:
            flash(err, "error")
    else:
        flash("Invio credenziali fallito.", "error")
        for err in errors:
            flash(err, "error")

    return redirect(url_for('master_login'))

@app.route('/card/<slug>')
def view_card(slug):
    clienti = load_db()
    user = next((c for c in clienti if c.get('slug') == slug), None)
    if not user:
        return "<h1>Card non trovata</h1>", 404
    if repair_user(user):
        save_db(clienti)

    default_p = user.get('default_profile', 'p1')
    p_req = request.args.get('p')
    if not p_req:
        p_req = default_p
    if p_req == 'menu':
        return render_template('menu_card.html', user=user, slug=slug)
    if not user.get(p_req, {}).get('active'):
        p_req = 'p1'
    p = user[p_req]

    ag = {
        "name": p.get('name'),
        "role": p.get('role'),
        "company": p.get('company'),
        "bio": p.get('bio'),
        "photo_url": p.get('foto'),
        "logo_url": p.get('logo'),
        "personal_url": p.get('personal_foto'),
        "slug": slug,
        "piva": p.get('piva'),
        "pec": p.get('pec'),
        "cod_sdi": p.get('cod_sdi'),
        "office_phone": p.get('office_phone'),
        "address": p.get('address'),
        "fx_rotate_logo": p.get('fx_rotate_logo'),
        "fx_rotate_agent": p.get('fx_rotate_agent'),
        "fx_interaction": p.get('fx_interaction'),
        "fx_back": p.get('fx_back_content'),
        "photo_pos_x": p.get('pos_x', 50),
        "photo_pos_y": p.get('pos_y', 50),
        "photo_zoom": p.get('zoom', 1.0),
        "trans": p.get('trans', {})
    }

    return render_template(
        'card.html',
        lang='it',
        ag=ag,
        mobiles=p.get('mobiles', []),
        emails=p.get('emails', []),
        websites=p.get('websites', []),
        socials=p.get('socials', []),
        p_data=p,
        profile=p_req,
        p2_enabled=user['p2']['active'],
        p3_enabled=user['p3']['active']
    )

@app.route('/master/delete/<int:id>')
def master_delete(id):
    if not session.get('is_master'):
        return redirect(url_for('master_login'))
    save_db([c for c in load_db() if c.get('id') != id])
    flash("Card eliminata.", "success")
    return redirect(url_for('master_login'))

@app.route('/master/impersonate/<int:id>')
def master_impersonate(id):
    session['logged_in'] = True
    session['user_id'] = id
    return redirect(url_for('area'))

@app.route('/master/logout')
def master_logout():
    session.pop('is_master', None)
    return redirect(url_for('master_login'))

@app.route('/area/logout')
def logout():
    if session.get('is_master'):
        session.pop('user_id', None)
        return redirect(url_for('master_login'))
    session.clear()
    return redirect(url_for('login'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico')

@app.route('/reset-tutto')
def reset_db_emergency():
    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
            return "DB CANCELLATO"
        except:
            pass
    return "DB PULITO"

if __name__ == '__main__':
    app.run(debug=True)
