import os
import json
import random
import string
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_2026_fixed_final"

# --- CONFIGURAZIONE ---
if os.path.exists('/var/data'):
    BASE_DIR = '/var/data'
else:
    BASE_DIR = os.path.join(os.getcwd(), 'static')

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_FILE = os.path.join(BASE_DIR, 'clients.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# --- GESTIONE DB (Syntax Error Fix) ---
def load_db():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_db(data):
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Errore salvataggio DB: {e}")

def save_file(file, prefix):
    if file and file.filename:
        filename = secure_filename(f"{prefix}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return f"/uploads/{filename}"
    return None

# --- RIPARAZIONE UTENTE (Evita Errore 500) ---
def repair_user(user):
    dirty = False
    
    # Crea profili P1, P2, P3 se mancano
    for pid in ['p1', 'p2', 'p3']:
        if pid not in user:
            user[pid] = {'active': False}
            dirty = True
        
        p = user[pid]
        # Valori di default
        defaults = {
            'name': '', 'role': '', 'company': '', 'bio': '',
            'foto': '', 'logo': '', 'personal_foto': '',
            'mobiles': [], 'emails': [], 'websites': [], 'socials': [],
            'gallery_img': [], 'gallery_vid': [], 'gallery_pdf': [],
            'piva': '', 'cod_sdi': '', 'pec': '',
            'fx_rotate_logo': 'off', 'fx_rotate_agent': 'off',
            'fx_interaction': 'tap', 'fx_back_content': 'logo',
            'pos_x': 50, 'pos_y': 50, 'zoom': 1,
            'trans': {
                'en': {'role':'', 'bio':''}, 'fr': {'role':'', 'bio':''},
                'es': {'role':'', 'bio':''}, 'de': {'role':'', 'bio':''}
            }
        }
        
        for k, v in defaults.items():
            if k not in p:
                p[k] = v
                dirty = True
                
        # Fix liste None
        if p.get('socials') is None: p['socials'] = []; dirty = True
        if p.get('trans') is None: p['trans'] = defaults['trans']; dirty = True

    return dirty

# --- ROTTA MODIFICA ---
@app.route('/area/edit/<p_id>', methods=['GET', 'POST'])
def edit_profile(p_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    clienti = load_db()
    user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    
    if not user: return redirect(url_for('logout'))

    # RIPARA PRIMA DI TUTTO
    if repair_user(user):
        save_db(clienti)

    p_key = 'p' + p_id
    # Se il profilo non è attivo (es. P2 nuovo), attivalo vuoto per modificarlo
    if not user[p_key].get('active'):
        user[p_key]['active'] = True
        save_db(clienti)
    
    if request.method == 'POST':
        p = user[p_key]
        prefix = f"u{user['id']}_{p_id}"
        
        # Testi
        p['name'] = request.form.get('name')
        p['role'] = request.form.get('role')
        p['company'] = request.form.get('company')
        p['bio'] = request.form.get('bio')
        p['piva'] = request.form.get('piva')
        p['cod_sdi'] = request.form.get('cod_sdi')
        p['pec'] = request.form.get('pec')
        
        # Contatti
        p['mobiles'] = [x for x in [request.form.get('mobile1'), request.form.get('mobile2')] if x]
        p['emails'] = [x for x in [request.form.get('email1'), request.form.get('email2')] if x]
        p['websites'] = [x for x in [request.form.get('website')] if x]

        # Socials
        socials = []
        for soc in ['Facebook', 'Instagram', 'Linkedin', 'TikTok', 'Spotify', 'Telegram', 'YouTube']:
            url = request.form.get(soc.lower())
            if url: socials.append({'label': soc, 'url': url})
        p['socials'] = socials

        # Grafica & Effetti
        p['fx_rotate_logo'] = 'on' if request.form.get('fx_rotate_logo') else 'off'
        p['fx_rotate_agent'] = 'on' if request.form.get('fx_rotate_agent') else 'off'
        p['fx_interaction'] = request.form.get('fx_interaction', 'tap')
        p['fx_back_content'] = request.form.get('fx_back_content', 'logo')
        p['pos_x'] = request.form.get('pos_x', 50)
        p['pos_y'] = request.form.get('pos_y', 50)
        p['zoom'] = request.form.get('zoom', 1)

        # Traduzioni
        p['trans'] = {
            'en': {'role': request.form.get('role_en'), 'bio': request.form.get('bio_en')},
            'fr': {'role': request.form.get('role_fr'), 'bio': request.form.get('bio_fr')},
            'es': {'role': request.form.get('role_es'), 'bio': request.form.get('bio_es')},
            'de': {'role': request.form.get('role_de'), 'bio': request.form.get('bio_de')}
        }

        # Files
        if 'foto' in request.files: 
            path = save_file(request.files['foto'], f"{prefix}_foto")
            if path: p['foto'] = path
        if request.form.get('foto_manual'): p['foto'] = request.form.get('foto_manual')
        
        if 'logo' in request.files:
            path = save_file(request.files['logo'], f"{prefix}_logo")
            if path: p['logo'] = path
            
        if 'personal_foto' in request.files:
            path = save_file(request.files['personal_foto'], f"{prefix}_pers")
            if path: p['personal_foto'] = path

        # Gallerie
        if 'gallery_img' in request.files:
            for f in request.files.getlist('gallery_img'):
                path = save_file(f, f"{prefix}_gimg")
                if path: p['gallery_img'].append(path)
        
        if 'gallery_pdf' in request.files:
            for f in request.files.getlist('gallery_pdf'):
                path = save_file(f, f"{prefix}_gpdf")
                if path: p['gallery_pdf'].append({'path': path, 'name': f.filename})

        if 'gallery_vid' in request.files:
            for f in request.files.getlist('gallery_vid'):
                path = save_file(f, f"{prefix}_gvid")
                if path: p['gallery_vid'].append(path)
        
        # Cancella Media
        if request.form.get('delete_media'):
            to_del = request.form.getlist('delete_media')
            p['gallery_img'] = [x for x in p.get('gallery_img',[]) if x not in to_del]
            p['gallery_pdf'] = [x for x in p.get('gallery_pdf',[]) if x['path'] not in to_del]
            p['gallery_vid'] = [x for x in p.get('gallery_vid',[]) if x not in to_del]

        save_db(clienti)
        return redirect(url_for('area'))
        
    return render_template('edit_card.html', p=user[p_key], p_id=p_id)

# --- MASTER ADMIN ---
@app.route('/master', methods=['GET', 'POST'])
def master_login():
    if session.get('is_master'):
        try: files = os.listdir(app.config['UPLOAD_FOLDER'])
        except: files = []
        return render_template('master_dashboard.html', clienti=load_db(), files=files)
    
    if request.method == 'POST' and request.form.get('password') == "pay2026":
        session['is_master'] = True
        return redirect(url_for('master_login'))
    return render_template('master_login.html')

@app.route('/master/add', methods=['POST'])
def master_add():
    clienti = load_db()
    new_id = 1
    if len(clienti) > 0:
        new_id = max([c['id'] for c in clienti]) + 1
    
    # Password Complessa
    pwd_chars = string.ascii_letters + string.digits + "!@#$%"
    auto_pass = ''.join(random.choices(pwd_chars, k=10))
    
    form_pass = request.form.get('password')
    final_pass = form_pass if form_pass else auto_pass

    slug = request.form.get('slug')
    if not slug: slug = f"card-{new_id}"

    new_c = {
        "id": new_id,
        "username": request.form.get('username') or f"user{new_id}",
        "password": final_pass,
        "slug": slug,
        "nome": request.form.get('nome') or "Nuovo Cliente",
        "azienda": "New",
        "p1": {"active": True, "name": request.form.get('nome') or "Nuovo Cliente"},
        "p2": {"active": False}, "p3": {"active": False}
    }
    repair_user(new_c)
    
    clienti.append(new_c)
    save_db(clienti)
    return redirect(url_for('master_login'))

# --- CARD PUBBLICA ---
def dummy_t(k): return "SALVA CONTATTO"

@app.route('/card/<slug>')
def view_card(slug):
    clienti = load_db()
    user = next((c for c in clienti if c['slug'] == slug), None)
    if not user: return "<h1>Card non trovata</h1>", 404
    
    if repair_user(user): save_db(clienti)

    p_req = request.args.get('p', 'p1')
    if not user.get(p_req, {}).get('active'): p_req = 'p1'
    p = user[p_req]
    
    ag = {
        "name": p.get('name'), "role": p.get('role'), "company": p.get('company'),
        "bio": p.get('bio'), "photo_url": p.get('foto'), "logo_url": p.get('logo'),
        "personal_url": p.get('personal_foto'), "slug": slug,
        "piva": p.get('piva'), "pec": p.get('pec'), "cod_sdi": p.get('cod_sdi'),
        "fx_rotate_logo": p.get('fx_rotate_logo'), "fx_rotate_agent": p.get('fx_rotate_agent'),
        "fx_interaction": p.get('fx_interaction'), "fx_back": p.get('fx_back_content'),
        "photo_pos_x": p.get('pos_x', 50), "photo_pos_y": p.get('pos_y', 50), "photo_zoom": p.get('zoom', 1),
        "trans": p.get('trans', {})
    }
    
    return render_template('card.html', lang='it', ag=ag, 
                           mobiles=p.get('mobiles', []), emails=p.get('emails', []), 
                           websites=p.get('websites', []), socials=p.get('socials', []), 
                           p_data=p, # Passa tutto l'oggetto p per gallerie
                           t_func=dummy_t, profile=p_req, 
                           p2_enabled=user['p2']['active'], p3_enabled=user['p3']['active'])

# --- ALTRE ROTTE ---
@app.route('/master/delete/<int:id>')
def master_delete(id): save_db([c for c in load_db() if c['id'] != id]); return redirect(url_for('master_login'))
@app.route('/master/impersonate/<int:id>')
def master_impersonate(id): session['logged_in']=True; session['user_id']=id; return redirect(url_for('area'))
@app.route('/master/logout')
def master_logout(): session.pop('is_master', None); return redirect(url_for('master_login'))
@app.route('/')
def home(): return redirect(url_for('login'))
@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if request.method=='POST':
        u=request.form.get('username'); p=request.form.get('password'); clienti=load_db()
        user=next((c for c in clienti if c['username']==u and c['password']==p), None)
        if user: session['logged_in']=True; session['user_id']=user['id']; return redirect(url_for('area'))
    return render_template('login.html')
@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    user = next((c for c in load_db() if c['id'] == session.get('user_id')), None)
    if not user: return redirect(url_for('logout'))
    if repair_user(user): save_db(load_db())
    return render_template('dashboard.html', user=user)
@app.route('/area/activate/<p_id>')
def activate_profile(p_id):
    clienti=load_db(); user=next((c for c in clienti if c['id']==session.get('user_id')), None)
    user['p'+p_id]['active']=True; repair_user(user); save_db(clienti); return redirect(url_for('area'))
@app.route('/uploads/<filename>')
def uploaded_file(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
@app.route('/favicon.ico')
def favicon(): return send_from_directory('static', 'favicon.ico')
@app.route('/area/logout')
def logout(): session.clear(); return redirect(url_for('login'))

if __name__ == '__main__': app.run(debug=True)
