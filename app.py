import os
import json
import shutil
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash

app = Flask(__name__)
app.secret_key = "pay4you_2026_pro_master"

# --- 1. CONFIGURAZIONE DISCO ---
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
    DB_FILE = '/var/data/clients.json' # Il file dove salviamo i clienti
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')
    DB_FILE = os.path.join(os.getcwd(), 'static', 'clients.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- CREDENZIALI MASTER ADMIN ---
MASTER_USER = "master"
MASTER_PASS = "pay2026"

# --- 2. GESTIONE DATABASE (JSON) ---
def load_db():
    # Se il file non esiste, lo creiamo con l'Admin di base
    if not os.path.exists(DB_FILE):
        default_db = [{
            "id": 1, "username": "admin", "password": "password123", "slug": "giuseppe",
            "nome": "Giuseppe Di Lisio", "azienda": "Pay4You", "scadenza": "31/12/2030", "stato": "Attivo",
            "p1": {
                "active": True, "name": "Giuseppe Di Lisio", "role": "CEO", "company": "Pay4You",
                "foto": "/static/pay4you-logo.png", "cover": "", "bio": "Card Digitale Admin",
                "mobiles": ["+39 333 1234567"], "emails": ["info@pay4you.it"], "websites": ["www.pay4you.it"],
                "socials": []
            },
            "p2": {"active": False}, "p3": {"active": False}
        }]
        save_db(default_db)
        return default_db
    
    try:
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- 3. ROTTE MASTER (Control Room) ---
@app.route('/master', methods=['GET', 'POST'])
def master_login():
    # Login Master
    if 'is_master' not in session:
        error = None
        if request.method == 'POST':
            if request.form.get('username') == MASTER_USER and request.form.get('password') == MASTER_PASS:
                session['is_master'] = True
                return redirect(url_for('master_login'))
            else:
                error = "Password Errata"
        return render_template('master_login.html', error=error)
    
    # Dashboard Master
    clienti = load_db()
    return render_template('master_dashboard.html', clienti=clienti)

@app.route('/master/add', methods=['POST'])
def master_add():
    if 'is_master' not in session: return redirect(url_for('master_login'))
    
    clienti = load_db()
    new_id = max([c['id'] for c in clienti], default=0) + 1
    
    # Dati dal form
    new_client = {
        "id": new_id,
        "username": request.form.get('username'),
        "password": request.form.get('password'),
        "slug": request.form.get('slug'), # QUI DECIDI TU LO SLUG
        "nome": request.form.get('nome'),
        "azienda": "Nuova Azienda",
        "scadenza": "31/12/2026",
        "stato": "Attivo",
        "p1": { # Struttura vuota pronta
            "active": True, "name": request.form.get('nome'), "role": "", "company": "",
            "foto": "", "cover": "", "bio": "", "mobiles": [], "emails": [], "websites": [], "socials": []
        },
        "p2": {"active": False}, "p3": {"active": False}
    }
    
    clienti.append(new_client)
    save_db(clienti)
    return redirect(url_for('master_login'))

@app.route('/master/delete/<int:id>')
def master_delete(id):
    if 'is_master' not in session: return redirect(url_for('master_login'))
    clienti = load_db()
    clienti = [c for c in clienti if c['id'] != id] # Rimuove il cliente
    save_db(clienti)
    return redirect(url_for('master_login'))

@app.route('/master/impersonate/<int:id>')
def master_impersonate(id):
    # TI LOGGA COME SE FOSSI IL CLIENTE
    if 'is_master' not in session: return redirect(url_for('master_login'))
    session['logged_in'] = True
    session['user_id'] = id
    return redirect(url_for('area'))

@app.route('/master/logout')
def master_logout():
    session.pop('is_master', None)
    return redirect(url_for('master_login'))

# --- 4. ROTTE CLIENTE (Fix 500) ---
@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        clienti = load_db()
        user = next((c for c in clienti if c['username'] == u and c['password'] == p), None)
        if user:
            session['logged_in'] = True
            session['user_id'] = user['id']
            return redirect(url_for('area'))
        else:
            error = "Credenziali errate"
    return render_template('login.html', error=error)

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    clienti = load_db()
    user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    
    # Se l'utente non esiste più (cancellato da master), logout
    if not user: 
        session.clear()
        return redirect(url_for('login'))
        
    return render_template('dashboard.html', user=user)

# --- 5. CARD PUBBLICA ---
def dummy_t(k): return "SALVA CONTATTO"

@app.route('/card/<slug>')
def view_card(slug):
    clienti = load_db()
    user = next((c for c in clienti if c['slug'] == slug), None)
    if not user: return "<h1>Card non trovata</h1>", 404
    
    p1 = user.get('p1', {})
    # Dati sicuri per evitare errori
    ag = {
        "name": p1.get('name', user['nome']),
        "role": p1.get('role', ''),
        "company": p1.get('company', user['azienda']),
        "bio": p1.get('bio', ''),
        "photo_url": p1.get('foto', ''),
        "cover_url": p1.get('cover', ''),
        "slug": slug,
        "photo_pos_x": 50, "photo_pos_y": 50, "photo_zoom": 1
    }
    return render_template('card.html', lang='it', ag=ag, 
                           mobiles=p1.get('mobiles', []), emails=p1.get('emails', []), 
                           websites=p1.get('websites', []), socials=p1.get('socials', []), 
                           t_func=dummy_t, profile='p1', p2_enabled=0, p3_enabled=0)

# --- UTILITÀ ---
@app.route('/favicon.ico')
def favicon(): return send_from_directory('static', 'favicon.ico')
@app.route('/area/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/uploads/<filename>')
def uploaded_file(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Gestione errori
@app.errorhandler(500)
def server_error(e): return f"<h1>Errore Interno (500)</h1><p>{e}</p>", 500

if __name__ == '__main__':
    app.run(debug=True)
