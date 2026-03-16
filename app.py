import os
import json
import base64
import random
import string
import smtplib
from io import BytesIO
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

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None

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
app.config['MAX_CONTENT_LENGTH'] = 160 * 1024 * 1024

MAX_GALLERY_IMG = 30
MAX_GALLERY_VID = 10
MAX_GALLERY_PDF = 12

MAX_IMAGE_MB = 8
MAX_VIDEO_MB = 40
MAX_PDF_MB = 16

ALLOWED_IMAGE_EXT = {'jpg', 'jpeg', 'png', 'webp'}
ALLOWED_VIDEO_EXT = {'mp4', 'mov', 'webm', 'm4v'}
ALLOWED_PDF_EXT = {'pdf'}

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
TWILIO_TEMPLATE_CARD_SID = os.getenv("TWILIO_TEMPLATE_CARD_SID", "").strip()


def load_db():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_db(data):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Errore DB: {e}")


def save_file(file, prefix):
    if file and file.filename:
        filename = secure_filename(f"{prefix}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return f"/uploads/{filename}"
    return None


def replace_uploaded_file_from_bytes(content: bytes, original_filename: str, prefix: str, fallback_ext: str = "jpg"):
    ext = get_file_ext(original_filename)
    if ext not in (ALLOWED_IMAGE_EXT | ALLOWED_VIDEO_EXT | ALLOWED_PDF_EXT):
        ext = fallback_ext

    safe_prefix = secure_filename(prefix)
    filename = secure_filename(f"{safe_prefix}.{ext}")
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    with open(path, 'wb') as f:
        f.write(content)

    return f"/uploads/{filename}"


def delete_uploaded_url(url_path: str):
    try:
        if not url_path:
            return
        parsed = urlparse(str(url_path)).path
        if not parsed.startswith('/uploads/'):
            return
        filename = parsed.split('/uploads/', 1)[1]
        fp = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.isfile(fp):
            os.remove(fp)
    except Exception:
        pass


def to_int(v, d=50):
    try:
        return int(float(v))
    except Exception:
        return d


def to_float(v, d=1.0):
    try:
        return float(v)
    except Exception:
        return d


def normalize_phone(phone: str) -> str:
    phone = str(phone or "").strip()
    if not phone:
        return ""
    phone = phone.replace("whatsapp:", "", 1)
    phone = phone.replace(" ", "").replace("-", "").replace("/", "").replace(".", "")

    cleaned = []
    for i, ch in enumerate(phone):
        if ch.isdigit():
            cleaned.append(ch)
        elif ch == '+' and i == 0:
            cleaned.append(ch)
    phone = "".join(cleaned)

    if not phone:
        return ""
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    if phone.startswith("39") and not phone.startswith("+39"):
        phone = "+" + phone
    if not phone.startswith("+"):
        if len(phone) >= 9:
            phone = "+39" + phone
    return phone


def ensure_whatsapp_prefix(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("whatsapp:"):
        return value
    return f"whatsapp:{value}"


def get_file_ext(filename: str) -> str:
    filename = (filename or "").lower().strip()
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1]


def get_file_size_bytes(file_storage) -> int:
    try:
        current_pos = file_storage.stream.tell()
        file_storage.stream.seek(0, os.SEEK_END)
        size = file_storage.stream.tell()
        file_storage.stream.seek(current_pos)
        return size
    except Exception:
        return 0


def file_size_ok(file_storage, max_mb: int) -> bool:
    size = get_file_size_bytes(file_storage)
    return size > 0 and size <= (max_mb * 1024 * 1024)


def validate_upload(file_storage, allowed_exts: set, max_mb: int):
    if not file_storage or not file_storage.filename:
        return False, "File mancante."
    ext = get_file_ext(file_storage.filename)
    if ext not in allowed_exts:
        return False, f"Formato non consentito: {file_storage.filename}"
    if not file_size_ok(file_storage, max_mb):
        return False, f"File troppo pesante: {file_storage.filename} (max {max_mb} MB)"
    return True, ""


def repair_user(user):
    dirty = False
    if 'default_profile' not in user:
        user['default_profile'] = 'p1'
        dirty = True
    if 'nome' not in user:
        user['nome'] = ''
        dirty = True
    if 'must_change_password' not in user:
        user['must_change_password'] = True
        dirty = True
    if 'reset_token' not in user:
        user['reset_token'] = ''
        dirty = True
    if 'reset_expires' not in user:
        user['reset_expires'] = 0
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
            'active': False,
            'name': '', 'role': '', 'company': '', 'bio': '',
            'foto': '', 'logo': '', 'personal_foto': '',
            'office_phone': '', 'address': '',
            'mobiles': [], 'emails': [], 'websites': [], 'socials': [],
            'gallery_img': [], 'gallery_vid': [], 'gallery_pdf': [],
            'piva': '', 'cod_sdi': '', 'pec': '',
            'fx_rotate_logo': 'off', 'fx_rotate_agent': 'off',
            'fx_interaction': 'tap', 'fx_back_content': 'logo',
            'pos_x': 0, 'pos_y': 0, 'zoom': 1.0,
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
        p['pos_x'] = to_int(p.get('pos_x', 0), 0)
        p['pos_y'] = to_int(p.get('pos_y', 0), 0)
        p['zoom'] = to_float(p.get('zoom', 1.0), 1.0)
    return dirty


def make_random_password(length=12):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(chars) for _ in range(length))


def save_cropped_agent_photo(file_storage, prefix: str, pos_x: int, pos_y: int, zoom: float):
    if not file_storage or not file_storage.filename:
        return None
    ok, err = validate_upload(file_storage, ALLOWED_IMAGE_EXT, MAX_IMAGE_MB)
    if not ok:
        raise ValueError(err)
    if Image is None:
        return save_file(file_storage, f"{prefix}_foto")

    file_storage.stream.seek(0)
    img = Image.open(file_storage.stream)
    img = ImageOps.exif_transpose(img).convert('RGB')
    w, h = img.size
    viewport = 160.0
    base_scale = max(viewport / w, viewport / h)
    zoom = max(0.5, min(3.0, float(zoom or 1.0)))
    final_scale = base_scale * zoom
    crop_w = viewport / final_scale
    crop_h = viewport / final_scale
    shift_x = (float(pos_x or 0) / 100.0) * crop_w
    shift_y = (float(pos_y or 0) / 100.0) * crop_h
    left = (w - crop_w) / 2.0 - shift_x
    top = (h - crop_h) / 2.0 - shift_y
    crop_w = min(crop_w, float(w))
    crop_h = min(crop_h, float(h))
    left = max(0.0, min(left, w - crop_w))
    top = max(0.0, min(top, h - crop_h))
    right = left + crop_w
    bottom = top + crop_h
    cropped = img.crop((int(round(left)), int(round(top)), int(round(right)), int(round(bottom))))
    cropped = ImageOps.fit(cropped, (800, 800), method=Image.LANCZOS, centering=(0.5, 0.5))
    bio = BytesIO()
    cropped.save(bio, format='JPEG', quality=92, optimize=True)
    bio.seek(0)
    return replace_uploaded_file_from_bytes(bio.read(), file_storage.filename, f"{prefix}_foto_crop", fallback_ext="jpg")


def get_user_by_id(clienti, user_id):
    return next((c for c in clienti if c.get('id') == user_id), None)


def get_user_by_email(clienti, email):
    email = (email or "").strip().lower()
    if not email:
        return None
    for c in clienti:
        admin_email = (((c.get('admin_contact') or {}).get('email')) or '').strip().lower()
        if admin_email and admin_email == email:
            return c
    return None


def detect_lang_from_request() -> str:
    try:
        raw = (request.headers.get("Accept-Language") or "").lower().strip()
    except Exception:
        raw = ""
    supported = ["it", "en", "fr", "es", "de"]
    if not raw:
        return "it"
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for part in parts:
        code = part.split(";")[0].strip()
        short = code.split("-")[0].strip()
        if short in supported:
            return short
    return "it"


def translated_value(p: dict, lang: str, field_name: str, fallback: str = "") -> str:
    if lang == "it":
        return (p.get(field_name) or fallback or "").strip()
    trans = p.get("trans") or {}
    block = trans.get(lang) or {}
    value = (block.get(field_name) or "").strip()
    if value:
        return value
    return (p.get(field_name) or fallback or "").strip()


def ui_labels_for_lang(lang: str) -> dict:
    labels = {
        "it": {"save_contact":"SALVA CONTATTO","contacts":"CONTATTI","photos":"FOTO","videos":"VIDEO","documents":"DOCUMENTI","light":"CHIARO","dark":"SCURO","auto":"AUTO"},
        "en": {"save_contact":"SAVE CONTACT","contacts":"CONTACTS","photos":"PHOTOS","videos":"VIDEOS","documents":"DOCUMENTS","light":"LIGHT","dark":"DARK","auto":"AUTO"},
        "fr": {"save_contact":"ENREGISTRER LE CONTACT","contacts":"CONTACTS","photos":"PHOTOS","videos":"VIDÉOS","documents":"DOCUMENTS","light":"CLAIR","dark":"SOMBRE","auto":"AUTO"},
        "es": {"save_contact":"GUARDAR CONTACTO","contacts":"CONTACTOS","photos":"FOTOS","videos":"VÍDEOS","documents":"DOCUMENTOS","light":"CLARO","dark":"OSCURO","auto":"AUTO"},
        "de": {"save_contact":"KONTAKT SPEICHERN","contacts":"KONTAKTE","photos":"FOTOS","videos":"VIDEOS","documents":"DOKUMENTE","light":"HELL","dark":"DUNKEL","auto":"AUTO"},
    }
    return labels.get(lang, labels["it"])


def vcf_escape(value: str) -> str:
    s = str(value or "")
    s = s.replace("\\", "\\\\")
    s = s.replace("\n", "\\n").replace("\r", "")
    s = s.replace(";", r"\;").replace(",", r"\,")
    return s.strip()


def absolute_url(path: str) -> str:
    path = str(path or "").strip()
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{CARD_BASE_URL}{path}"


def normalize_web_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return "https://" + url


@app.route('/')
def home():
    return redirect(url_for('login'))


@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        user = next((c for c in load_db() if c.get('id') == session.get('user_id')), None)
        if user and repair_user(user):
            clienti = load_db()
            for c in clienti:
                if c.get('id') == user.get('id'):
                    repair_user(c)
            save_db(clienti)
        if user and user.get('must_change_password'):
            return redirect(url_for('change_password'))
        return redirect(url_for('area'))

    error = None
    if request.method == 'POST':
        u = (request.form.get('username') or '').strip()
        p = request.form.get('password') or ''
        clienti = load_db()
        user = next((c for c in clienti if c.get('username') == u and c.get('password') == p), None)
        if user:
            if repair_user(user):
                save_db(clienti)
            session['logged_in'] = True
            session['user_id'] = user['id']
            if user.get('must_change_password'):
                return redirect(url_for('change_password'))
            return redirect(url_for('area'))
        error = "Credenziali non valide."
    return render_template('login.html', error=error)


@app.route('/area/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        clienti = load_db()
        user = get_user_by_email(clienti, email)
        public_msg = "Se la tua email è registrata, riceverai le istruzioni per recuperare la password."
        if user:
            new_password = make_random_password(12)
            user['password'] = new_password
            user['must_change_password'] = True
            save_db(clienti)
        flash(public_msg, "success")
        return redirect(url_for('login'))
    return render_template('forgot.html')


@app.route('/area/change-password', methods=['GET', 'POST'])
def change_password():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    clienti = load_db()
    user = get_user_by_id(clienti, session.get('user_id'))
    if not user:
        return redirect(url_for('logout'))
    if repair_user(user):
        save_db(clienti)
    forced = bool(user.get('must_change_password'))
    if request.method == 'POST':
        current_password = request.form.get('current_password') or ''
        new_password = (request.form.get('new_password') or '').strip()
        confirm_password = (request.form.get('confirm_password') or '').strip()
        if not forced and current_password != (user.get('password') or ''):
            flash("Password attuale non corretta.", "error")
            return render_template('change_password.html', forced=forced, user=user)
        if len(new_password) < 8:
            flash("La nuova password deve avere almeno 8 caratteri.", "error")
            return render_template('change_password.html', forced=forced, user=user)
        if new_password != confirm_password:
            flash("Le due password non coincidono.", "error")
            return render_template('change_password.html', forced=forced, user=user)
        if new_password == (user.get('password') or ''):
            flash("La nuova password deve essere diversa da quella attuale.", "error")
            return render_template('change_password.html', forced=forced, user=user)
        user['password'] = new_password
        user['must_change_password'] = False
        save_db(clienti)
        flash("Password aggiornata correttamente.", "success")
        return redirect(url_for('area'))
    return render_template('change_password.html', forced=forced, user=user)


@app.route('/area')
def area():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    user = next((c for c in load_db() if c.get('id') == session.get('user_id')), None)
    if not user:
        return redirect(url_for('logout'))
    if repair_user(user):
        clienti = load_db()
        for c in clienti:
            if c.get('id') == user.get('id'):
                repair_user(c)
        save_db(clienti)
    if user.get('must_change_password'):
        return redirect(url_for('change_password'))
    return render_template('dashboard.html', user=user)


@app.route('/area/activate/<p_id>')
def activate_profile(p_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    clienti = load_db()
    user = get_user_by_id(clienti, session.get('user_id'))
    if not user:
        return redirect(url_for('logout'))
    pkey = 'p' + p_id
    if pkey not in user:
        flash("Profilo non trovato.", "error")
        return redirect(url_for('area'))
    user[pkey]['active'] = True
    repair_user(user)
    save_db(clienti)
    flash(f"Profilo P{p_id} attivato correttamente.", "success")
    return redirect(url_for('area'))


@app.route('/area/deactivate/<p_id>')
def deactivate_profile(p_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if p_id == '1':
        flash("Il profilo P1 è principale e non può essere disattivato.", "error")
        return redirect(url_for('area'))
    clienti = load_db()
    user = get_user_by_id(clienti, session.get('user_id'))
    if not user:
        return redirect(url_for('logout'))
    pkey = 'p' + p_id
    if pkey not in user:
        flash("Profilo non trovato.", "error")
        return redirect(url_for('area'))
    user[pkey]['active'] = False
    if user.get('default_profile') == pkey:
        user['default_profile'] = 'p1'
    save_db(clienti)
    flash(f"Profilo P{p_id} disattivato.", "success")
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
        save_db(clienti)
        flash(f"Apertura predefinita impostata su {mode.upper()}.", "success")
    elif mode == 'menu':
        user['default_profile'] = 'menu'
        save_db(clienti)
        flash("Apertura predefinita impostata su Menu.", "success")
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
    if user.get('must_change_password'):
        return redirect(url_for('change_password'))
    p_key = 'p' + p_id
    if not user[p_key].get('active'):
        user[p_key]['active'] = True
        save_db(clienti)
    if request.method == 'POST':
        p = user[p_key]
        prefix = f"u{user['id']}_{p_id}"
        p['name'] = request.form.get('name', '')
        if p_id == '1':
            user['nome'] = p['name']
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
        p['pos_x'] = to_int(request.form.get('pos_x', 0), 0)
        p['pos_y'] = to_int(request.form.get('pos_y', 0), 0)
        p['zoom'] = to_float(request.form.get('zoom', 1), 1.0)
        p['trans'] = {
            'en': {'role': request.form.get('role_en', ''), 'bio': request.form.get('bio_en', '')},
            'fr': {'role': request.form.get('role_fr', ''), 'bio': request.form.get('bio_fr', '')},
            'es': {'role': request.form.get('role_es', ''), 'bio': request.form.get('bio_es', '')},
            'de': {'role': request.form.get('role_de', ''), 'bio': request.form.get('bio_de', '')},
        }
        if 'foto' in request.files and request.files['foto'] and request.files['foto'].filename:
            try:
                old_foto = p.get('foto')
                path = save_cropped_agent_photo(request.files['foto'], prefix=prefix, pos_x=p['pos_x'], pos_y=p['pos_y'], zoom=p['zoom'])
                if path:
                    p['foto'] = path
                    if old_foto and old_foto != path:
                        delete_uploaded_url(old_foto)
            except Exception as e:
                flash(f"Errore foto profilo: {e}", "error")
                return redirect(url_for('edit_profile', p_id=p_id))
        if 'logo' in request.files and request.files['logo'] and request.files['logo'].filename:
            path = save_file(request.files['logo'], f"{prefix}_logo")
            if path:
                p['logo'] = path
        if 'personal_foto' in request.files and request.files['personal_foto'] and request.files['personal_foto'].filename:
            path = save_file(request.files['personal_foto'], f"{prefix}_pers")
            if path:
                p['personal_foto'] = path
        to_del = request.form.getlist('delete_media')
        if to_del:
            p['gallery_img'] = [x for x in p.get('gallery_img', []) if x not in to_del]
            p['gallery_pdf'] = [x for x in p.get('gallery_pdf', []) if x.get('path') not in to_del]
            p['gallery_vid'] = [x for x in p.get('gallery_vid', []) if x not in to_del]
        if 'gallery_img' in request.files:
            new_imgs = [f for f in request.files.getlist('gallery_img') if f and f.filename]
            current_count = len(p.get('gallery_img', []))
            slots_left = max(0, MAX_GALLERY_IMG - current_count)
            imgs_to_upload = new_imgs[:slots_left]
            for f in imgs_to_upload:
                ok, err = validate_upload(f, ALLOWED_IMAGE_EXT, MAX_IMAGE_MB)
                if not ok:
                    flash(err, "error")
                    return redirect(url_for('edit_profile', p_id=p_id))
            for f in imgs_to_upload:
                path = save_file(f, f"{prefix}_gimg")
                if path:
                    p['gallery_img'].append(path)
        if 'gallery_pdf' in request.files:
            new_pdfs = [f for f in request.files.getlist('gallery_pdf') if f and f.filename]
            current_count = len(p.get('gallery_pdf', []))
            slots_left = max(0, MAX_GALLERY_PDF - current_count)
            pdfs_to_upload = new_pdfs[:slots_left]
            for f in pdfs_to_upload:
                ok, err = validate_upload(f, ALLOWED_PDF_EXT, MAX_PDF_MB)
                if not ok:
                    flash(err, "error")
                    return redirect(url_for('edit_profile', p_id=p_id))
            for f in pdfs_to_upload:
                path = save_file(f, f"{prefix}_gpdf")
                if path:
                    p['gallery_pdf'].append({'path': path, 'name': f.filename})
        if 'gallery_vid' in request.files:
            new_vids = [f for f in request.files.getlist('gallery_vid') if f and f.filename]
            current_count = len(p.get('gallery_vid', []))
            slots_left = max(0, MAX_GALLERY_VID - current_count)
            vids_to_upload = new_vids[:slots_left]
            for f in vids_to_upload:
                ok, err = validate_upload(f, ALLOWED_VIDEO_EXT, MAX_VIDEO_MB)
                if not ok:
                    flash(err, "error")
                    return redirect(url_for('edit_profile', p_id=p_id))
            for f in vids_to_upload:
                path = save_file(f, f"{prefix}_gvid")
                if path:
                    p['gallery_vid'].append(path)
        repair_user(user)
        save_db(clienti)
        flash(f"Profilo P{p_id} salvato correttamente.", "success")
        return redirect(url_for('area'))
    return render_template('edit_card.html', p=user[p_key], p_id=p_id)


@app.route('/vcf/<slug>')
def download_vcf(slug):
    clienti = load_db()
    user = next((c for c in clienti if c.get('slug') == slug), None)
    if not user:
        return "Contatto non trovato", 404
    if repair_user(user):
        save_db(clienti)
    p_req = (request.args.get('p') or '').strip().lower()
    if p_req not in ('p1', 'p2', 'p3'):
        p_req = user.get('default_profile', 'p1')
    if p_req == 'menu':
        p_req = 'p1'
    if not user.get(p_req, {}).get('active'):
        p_req = 'p1'
    p = user.get(p_req, {}) or {}
    full_name = (p.get('name') or user.get('nome') or slug).strip()
    role = (p.get('role') or '').strip()
    company = (p.get('company') or '').strip()
    bio = (p.get('bio') or '').strip()
    office_phone = (p.get('office_phone') or '').strip()
    address = (p.get('address') or '').strip()
    pec = (p.get('pec') or '').strip()
    piva = (p.get('piva') or '').strip()
    cod_sdi = (p.get('cod_sdi') or '').strip()
    mobiles = [str(x).strip() for x in (p.get('mobiles') or []) if str(x).strip()]
    emails = [str(x).strip() for x in (p.get('emails') or []) if str(x).strip()]
    websites = [normalize_web_url(x) for x in (p.get('websites') or []) if str(x).strip()]
    socials = [normalize_web_url((s or {}).get('url', '')) for s in (p.get('socials') or []) if normalize_web_url((s or {}).get('url', ''))]
    photo_url = absolute_url(p.get('foto') or '')
    card_url = f"{CARD_BASE_URL}/card/{slug}?p={p_req}"
    gallery_img = [absolute_url(x) for x in (p.get('gallery_img') or []) if absolute_url(x)]
    gallery_vid = [absolute_url(x) for x in (p.get('gallery_vid') or []) if absolute_url(x)]
    gallery_pdf = [absolute_url((x or {}).get('path', '')) for x in (p.get('gallery_pdf') or []) if absolute_url((x or {}).get('path', ''))]
    notes = []
    if bio:
        notes.append('Bio: ' + bio)
    if piva:
        notes.append('P.IVA: ' + piva)
    if cod_sdi:
        notes.append('SDI: ' + cod_sdi)
    if pec:
        notes.append('PEC: ' + pec)
    notes.append('Card Digitale Pay4You: ' + card_url)
    if gallery_img:
        notes.append('Foto galleria:')
        for x in gallery_img[:30]:
            notes.append('- ' + x)
    if gallery_vid:
        notes.append('Video galleria:')
        for x in gallery_vid[:10]:
            notes.append('- ' + x)
    if gallery_pdf:
        notes.append('PDF galleria:')
        for x in gallery_pdf[:12]:
            notes.append('- ' + x)
    vcf_lines = [
        'BEGIN:VCARD', 'VERSION:3.0',
        f"N:{vcf_escape(full_name)};;;;",
        f"FN:{vcf_escape(full_name)}",
    ]
    if company:
        vcf_lines.append(f"ORG:{vcf_escape(company)}")
    if role:
        vcf_lines.append(f"TITLE:{vcf_escape(role)}")
    if photo_url:
        vcf_lines.append(f"PHOTO;VALUE=URI:{vcf_escape(photo_url)}")
    for m in mobiles:
        nm = normalize_phone(m)
        if nm:
            vcf_lines.append(f"TEL;TYPE=CELL:{vcf_escape(nm)}")
    if office_phone:
        no = normalize_phone(office_phone)
        if no:
            vcf_lines.append(f"TEL;TYPE=WORK,VOICE:{vcf_escape(no)}")
    for e in emails:
        vcf_lines.append(f"EMAIL;TYPE=INTERNET,WORK:{vcf_escape(e)}")
    if pec:
        vcf_lines.append(f"EMAIL;TYPE=INTERNET:{vcf_escape(pec)}")
    for w in websites:
        vcf_lines.append(f"URL;TYPE=WORK:{vcf_escape(w)}")
    for s in socials:
        vcf_lines.append(f"URL;TYPE=SOCIAL:{vcf_escape(s)}")
    vcf_lines.append(f"URL;TYPE=CARD:{vcf_escape(card_url)}")
    if address:
        vcf_lines.append(f"ADR;TYPE=WORK:;;{vcf_escape(address)};;;;")
    if notes:
        vcf_lines.append(f"NOTE:{vcf_escape(chr(10).join(notes))}")
    vcf_lines.append('END:VCARD')
    vcf_content = '\r\n'.join(vcf_lines) + '\r\n'
    filename = f"{slug}-{p_req}.vcf"
    resp = make_response(vcf_content)
    resp.headers['Content-Type'] = 'text/vcard; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


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
    lang = detect_lang_from_request()
    ui = ui_labels_for_lang(lang)
    if p_req == 'menu':
        return render_template('menu_card.html', user=user, slug=slug, lang=lang, ui=ui)
    if not user.get(p_req, {}).get('active'):
        p_req = 'p1'
    p = user[p_req]
    ag = {
        'name': p.get('name'),
        'role': translated_value(p, lang, 'role'),
        'company': p.get('company'),
        'bio': translated_value(p, lang, 'bio'),
        'photo_url': p.get('foto'),
        'logo_url': p.get('logo'),
        'personal_url': p.get('personal_foto'),
        'slug': slug,
        'piva': p.get('piva'),
        'pec': p.get('pec'),
        'cod_sdi': p.get('cod_sdi'),
        'office_phone': p.get('office_phone'),
        'address': p.get('address'),
        'fx_rotate_logo': p.get('fx_rotate_logo'),
        'fx_rotate_agent': p.get('fx_rotate_agent'),
        'fx_interaction': p.get('fx_interaction'),
        'fx_back': p.get('fx_back_content'),
        'photo_pos_x': p.get('pos_x', 0),
        'photo_pos_y': p.get('pos_y', 0),
        'photo_zoom': p.get('zoom', 1.0),
        'trans': p.get('trans', {})
    }
    return render_template('card.html', lang=lang, ui=ui, ag=ag, mobiles=p.get('mobiles', []), emails=p.get('emails', []), websites=p.get('websites', []), socials=p.get('socials', []), p_data=p, profile=p_req, p2_enabled=user['p2']['active'], p3_enabled=user['p3']['active'])


@app.route('/<slug>')
def legacy_card_redirect(slug):
    reserved = {'area', 'master', 'uploads', 'static', 'favicon.ico', 'reset-tutto', 'vcf', 'card'}
    if slug in reserved:
        return redirect(url_for('home'))
    clienti = load_db()
    user = next((c for c in clienti if c.get('slug') == slug), None)
    if user:
        p = request.args.get('p', '')
        if p:
            return redirect(url_for('view_card', slug=slug, p=p), code=301)
        return redirect(url_for('view_card', slug=slug), code=301)
    return "<h1>Card non trovata</h1>", 404


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
        except Exception:
            pass
    return "DB PULITO"


if __name__ == '__main__':
    app.run(debug=True)
