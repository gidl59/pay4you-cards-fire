import os
import json
import shutil
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_2026_recovery_mode"

# --- CONFIGURAZIONE DISCO ---
if os.path.exists('/var/data'):
    BASE_DIR = '/var/data'
else:
    BASE_DIR = os.path.join(os.getcwd(), 'static')

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_FILE = os.path.join(BASE_DIR, 'clients.json')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- CREDENZIALI MASTER ---
MASTER_USER = "master"
MASTER_PASS = "pay2026"

# --- DATABASE ---
def load_db():
    if not os.path.exists(DB_FILE): return []
    try:
        with open(DB_FILE, 'r') as f: return json.load(f)
    except: return []

def save_db(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f, indent=4)

# --- ROTTE MASTER AGGIORNATE (Con File Manager) ---
@app.route('/master', methods=['GET', 'POST'])
def master_login():
    if session.get('is_master'):
        clienti = load_db()
        
        # LEGGE I FILE DAL DISCO PER FARTELI VEDERE
        try:
            files_sul_disco = os.listdir(app.config['UPLOAD_FOLDER'])
        except:
            files_sul_disco = []
            
        return render_template('master_dashboard.html', clienti=clienti, files=files_sul_disco)
    
    if request.method == 'POST':
        if request.form.get('username') == MASTER_USER and request.form.get('password') == MASTER_PASS:
            session['is_master'] = True
            return redirect(url_for('master_login'))
    return render_template('master_login.html')

@app.route('/master/add', methods=['POST'])
def master_add():
    clienti = load_db()
    new_id = max([c['id'] for c in clienti], default=0) + 1
    new_c = {
        "id": new_id, "username": request.form.get('username'), "password": request.form.get('password'),
        "slug": request.form.get('slug'), "nome": request.form.get('nome'), "azienda": "New", "scadenza": "2026", "stato": "Attivo",
        "p1": {"active": True, "name": request.form.get('nome'), "role": "", "company": "", "foto": "", "mobiles": [], "emails": [], "websites": [], "socials": []},
        "p2": {"active": False}, "p3": {"active": False}
    }
    clienti.append(new_c); save_db(clienti); return redirect(url_for('master_login'))

@app.route('/master/impersonate/<int:id>')
def master_impersonate(id): session['logged_in']=True; session['user_id']=id; return redirect(url_for('area'))
@app.route('/master/logout')
def master_logout(): session.pop('is_master', None); return redirect(url_for('master_login'))
@app.route('/master/delete/<int:id>')
def master_delete(id):
    clienti = [c for c in load_db() if c['id'] != id]; save_db(clienti); return redirect(url_for('master_login'))

# --- ROTTE CLIENTE ---
@app.route('/')
def home(): return redirect(url_for('login'))
@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username'); p = request.form.get('password')
        user = next((c for c in load_db() if c['username'] == u and c['password'] == p), None)
        if user: session['logged_in']=True; session['user_id']=user['id']; return redirect(url_for('area'))
    return render_template('login.html')

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    user = next((c for c in load_db() if c['id'] == session.get('user_id')), None)
    return render_template('dashboard.html', user=user)

# --- MODIFICA E ATTIVAZIONE ---
@app.route('/area/edit/<p_id>', methods=['GET', 'POST'])
def edit_profile(p_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    clienti = load_db()
    user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    p_key = 'p' + p_id
    if request.method == 'POST':
        # Salva testi
        user[p_key]['name'] = request.form.get('name')
        user[p_key]['role'] = request.form.get('role')
        user[p_key]['company'] = request.form.get('company')
        user[p_key]['bio'] = request.form.get('bio')
        user[p_key]['mobiles'] = [request.form.get('mobile')]
        user[p_key]['emails'] = [request.form.get('email')]
        user[p_key]['websites'] = [request.form.get('website')]
        
        # Salva Foto (Upload)
        if 'foto' in request.files:
            file = request.files['foto']
            if file.filename != '':
                filename = secure_filename(f"user_{user['id']}_{p_id}_foto.jpg")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                user[p_key]['foto'] = f"/uploads/{filename}"
                
        # SE L'UTENTE INCOLLA UN PERCORSO VECCHIO (Recupero)
        if request.form.get('foto_path_manual'):
             user[p_key]['foto'] = request.form.get('foto_path_manual')

        if 'cover' in request.files:
            file = request.files['cover']
            if file.filename != '':
                filename = secure_filename(f"user_{user['id']}_{p_id}_cover.jpg")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                user[p_key]['cover'] = f"/uploads/{filename}"

        save_db(clienti)
        return redirect(url_for('area'))
    return render_template('edit_card.html', p=user[p_key], p_id=p_id)

@app.route('/area/activate/<p_id>')
def activate_profile(p_id):
    clienti = load_db()
    user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    user['p'+p_id]['active'] = True
    save_db(clienti)
    return redirect(url_for('area'))

# --- VISUALIZZAZIONE CARD ---
def dummy_t(k): return "SALVA CONTATTO"
@app.route('/card/<slug>')
def view_card(slug):
    user = next((c for c in load_db() if c['slug'] == slug), None)
    if not user: return "<h1>Card non trovata</h1>", 404
    p_req = request.args.get('p', 'p1')
    if not user.get(p_req, {}).get('active'): p_req = 'p1'
    p = user[p_req]
    ag = {"name": p.get('name'), "role": p.get('role'), "company": p.get('company'), "bio": p.get('bio'), "photo_url": p.get('foto'), "cover_url": p.get('cover'), "slug": slug, "photo_pos_x":50, "photo_pos_y":50, "photo_zoom":1}
    return render_template('card.html', lang='it', ag=ag, mobiles=p.get('mobiles',[]), emails=p.get('emails',[]), websites=p.get('websites',[]), socials=p.get('socials',[]), t_func=dummy_t, profile=p_req, p2_enabled=user['p2']['active'], p3_enabled=user['p3']['active'])

# --- UTILITÀ ---
@app.route('/uploads/<filename>')
def uploaded_file(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
@app.route('/favicon.ico')
def favicon(): return send_from_directory('static', 'favicon.ico')
@app.route('/area/logout')
def logout(): session.clear(); return redirect(url_for('login'))

if __name__ == '__main__': app.run(debug=True)
