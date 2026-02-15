import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_2026_full_power_v2"

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

# --- DATABASE (Corretto: Niente più righe appiccicate!) ---
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

# --- FUNZIONE SALVATAGGIO FILE ---
def save_file(file, prefix):
    if file and file.filename:
        filename = secure_filename(f"{prefix}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return f"/uploads/{filename}"
    return None

# --- MODIFICA COMPLETA (SALVATAGGIO DATI AVANZATI) ---
@app.route('/area/edit/<p_id>', methods=['GET', 'POST'])
def edit_profile(p_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    clienti = load_db()
    user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    
    if not user:
        return redirect(url_for('logout'))

    p_key = 'p' + p_id
    
    # Se il profilo non è attivo, lo attiviamo vuoto
    if not user[p_key].get('active'):
        user[p_key] = {
            "active": True, "name": "", "role": "", "company": "", "foto": "", 
            "logo": "", "personal_foto": "", "bio": "", 
            "mobiles": [], "emails": [], "websites": [], "socials": [],
            "gallery_img": [], "gallery_vid": [], "gallery_pdf": []
        }
        save_db(clienti)
    
    if request.method == 'POST':
        p = user[p_key]
        prefix = f"u{user['id']}_{p_id}"
        
        # 1. TESTI BASE
        p['name'] = request.form.get('name')
        p['role'] = request.form.get('role')
        p['company'] = request.form.get('company')
        p['bio'] = request.form.get('bio')
        
        # Dati fiscali
        p['piva'] = request.form.get('piva')
        p['cod_sdi'] = request.form.get('cod_sdi')
        p['pec'] = request.form.get('pec')
        
        # 2. CONTATTI MULTIPLI
        p['mobiles'] = []
        if request.form.get('mobile1'): p['mobiles'].append(request.form.get('mobile1'))
        if request.form.get('mobile2'): p['mobiles'].append(request.form.get('mobile2'))

        p['emails'] = []
        if request.form.get('email1'): p['emails'].append(request.form.get('email1'))
        if request.form.get('email2'): p['emails'].append(request.form.get('email2'))

        p['websites'] = []
        if request.form.get('website'): p['websites'].append(request.form.get('website'))

        # 3. SOCIAL NETWORK (7 Social)
        socials = []
        for soc in ['Facebook', 'Instagram', 'Linkedin', 'TikTok', 'Spotify', 'Telegram', 'YouTube']:
            url = request.form.get(soc.lower())
            if url:
                socials.append({'label': soc, 'url': url})
        p['socials'] = socials

        # 4. IMMAGINI PRINCIPALI
        if 'foto' in request.files:
            path = save_file(request.files['foto'], f"{prefix}_foto")
            if path: p['foto'] = path
            
        if 'logo' in request.files:
            path = save_file(request.files['logo'], f"{prefix}_logo")
            if path: p['logo'] = path
            
        if 'personal_foto' in request.files:
            path = save_file(request.files['personal_foto'], f"{prefix}_pers")
            if path: p['personal_foto'] = path

        # Recupero manuale
        if request.form.get('foto_manual'):
            p['foto'] = request.form.get('foto_manual')

        # 5. EFFETTI GRAFICI
        p['fx_rotate_logo'] = 'on' if request.form.get('fx_rotate_logo') else 'off'
        p['fx_rotate_agent'] = 'on' if request.form.get('fx_rotate_agent') else 'off'
        p['fx_interaction'] = request.form.get('fx_interaction', 'tap')
        p['fx_back_content'] = request.form.get('fx_back_content', 'logo')

        # 6. TRADUZIONI
        p['trans'] = {
            'en': {'role': request.form.get('role_en'), 'bio': request.form.get('bio_en')},
            'fr': {'role': request.form.get('role_fr'), 'bio': request.form.get('bio_fr')},
            'es': {'role': request.form.get('role_es'), 'bio': request.form.get('bio_es')},
            'de': {'role': request.form.get('role_de'), 'bio': request.form.get('bio_de')}
        }

        # 7. GALLERIE MEDIA
        if 'gallery_img' in request.files:
            files = request.files.getlist('gallery_img')
            for f in files:
                if len(p.get('gallery_img', [])) < 30:
                    path = save_file(f, f"{prefix}_gimg")
                    if path:
                        if 'gallery_img' not in p: p['gallery_img'] = []
                        p['gallery_img'].append(path)

        if 'gallery_pdf' in request.files:
            files = request.files.getlist('gallery_pdf')
            for f in files:
                if len(p.get('gallery_pdf', [])) < 12:
                    path = save_file(f, f"{prefix}_gpdf")
                    if path:
                        if 'gallery_pdf' not in p: p['gallery_pdf'] = []
                        p['gallery_pdf'].append({'path': path, 'name': f.filename})

        if 'gallery_vid' in request.files:
            files = request.files.getlist('gallery_vid')
            for f in files:
                if len(p.get('gallery_vid', [])) < 10:
                    path = save_file(f, f"{prefix}_gvid")
                    if path:
                        if 'gallery_vid' not in p: p['gallery_vid'] = []
                        p['gallery_vid'].append(path)

        # CANCELLAZIONE MEDIA
        if request.form.get('delete_media'):
            to_delete = request.form.getlist('delete_media')
            p['gallery_img'] = [x for x in p.get('gallery_img',[]) if x not in to_delete]
            p['gallery_pdf'] = [x for x in p.get('gallery_pdf',[]) if x['path'] not in to_delete]
            p['gallery_vid'] = [x for x in p.get('gallery_vid',[]) if x not in to_delete]

        save_db(clienti)
        return redirect(url_for('area'))
        
    return render_template('edit_card.html', p=user[p_key], p_id=p_id)

# --- VISUALIZZAZIONE CARD ---
def dummy_t(k): return "SALVA CONTATTO"

@app.route('/card/<slug>')
def view_card(slug):
    clienti = load_db()
    user = next((c for c in clienti if c['slug'] == slug), None)
    if not user: return "<h1>Card non trovata</h1>", 404
    
    p_req = request.args.get('p', 'p1')
    if not user.get(p_req, {}).get('active'):
        p_req = 'p1'
    
    p = user[p_req]
    
    ag = {
        "name": p.get('name'), "role": p.get('role'), "company": p.get('company'), 
        "bio": p.get('bio'), "photo_url": p.get('foto'), "logo_url": p.get('logo'),
        "personal_url": p.get('personal_foto'), "slug": slug,
        "piva": p.get('piva'), "pec": p.get('pec'),
        "fx_rotate_logo": p.get('fx_rotate_logo'), 
        "fx_rotate_agent": p.get('fx_rotate_agent'),
        "fx_interaction": p.get('fx_interaction'), 
        "fx_back": p.get('fx_back_content')
    }
    
    return render_template('card.html', lang='it', ag=ag, 
                           mobiles=p.get('mobiles', []), emails=p.get('emails', []), 
                           websites=p.get('websites', []), socials=p.get('socials', []), 
                           t_func=dummy_t, profile=p_req, 
                           p2_enabled=user['p2']['active'], p3_enabled=user['p3']['active'])

# --- MASTER ADMIN ---
@app.route('/master', methods=['GET', 'POST'])
def master_login():
    if session.get('is_master'): 
        try:
            files = os.listdir(app.config['UPLOAD_FOLDER'])
        except:
            files = []
        return render_template('master_dashboard.html', clienti=load_db(), files=files)
        
    if request.method == 'POST' and request.form.get('password') == "pay2026": 
        session['is_master'] = True
        return redirect(url_for('master_login'))
    
    return render_template('master_login.html')

@app.route('/master/add', methods=['POST'])
def master_add():
    clienti = load_db()
    
    if len(clienti) > 0:
        new_id = max([c['id'] for c in clienti]) + 1
    else:
        new_id = 1

    clienti.append({
        "id": new_id, 
        "username": request.form.get('username'), 
        "password": request.form.get('password'), 
        "slug": request.form.get('slug'), 
        "nome": request.form.get('nome'), 
        "azienda": "New", 
        "p1": {
            "active": True, "name": request.form.get('nome'), 
            "socials": [], "gallery_img": [], "gallery_vid": [], "gallery_pdf": []
        },
        "p2": {"active": False}, "p3": {"active": False}
    })
    save_db(clienti)
    return redirect(url_for('master_login'))

@app.route('/master/delete/<int:id>')
def master_delete(id):
    clienti = [c for c in load_db() if c['id'] != id]
    save_db(clienti)
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

# --- LOGIN CLIENTE ---
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        clienti = load_db()
        user = next((c for c in clienti if c['username'] == u and c['password'] == p), None)
        
        if user:
            session['logged_in'] = True
            session['user_id'] = user['id']
            return redirect(url_for('area'))
            
    return render_template('login.html')

@app.route('/area')
def area():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    user = next((c for c in load_db() if c['id'] == session.get('user_id')), None)
    if not user:
        return redirect(url_for('logout'))
        
    return render_template('dashboard.html', user=user)

@app.route('/area/activate/<p_id>')
def activate_profile(p_id):
    clienti = load_db()
    user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    
    user['p' + p_id]['active'] = True
    # Inizializza liste vuote
    if 'socials' not in user['p'+p_id]:
        user['p'+p_id]['socials'] = []
        user['p'+p_id]['gallery_img'] = []
        
    save_db(clienti)
    return redirect(url_for('area'))

# --- UTILITÀ ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico')

@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
