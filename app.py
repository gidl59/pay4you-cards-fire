import os
import json
import logging
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

# Configurazione Logging (per vedere gli errori su Render)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "pay4you_2026_ultra_secure"

# --- 1. CONFIGURAZIONE DISCO ---
# Controllo rigoroso del percorso
if os.path.exists('/var/data'):
    BASE_DIR = '/var/data'
    logger.info("Usando disco persistente Render: /var/data")
else:
    BASE_DIR = os.path.join(os.getcwd(), 'static')
    logger.info("Usando cartella locale static")

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_FILE = os.path.join(BASE_DIR, 'clients.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- CREDENZIALI MASTER ---
MASTER_USER = "master"
MASTER_PASS = "pay2026"

# --- 2. GESTIONE DATABASE (CON AUTORIPARAZIONE) ---
def get_default_db():
    return [{
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

def load_db():
    # Se il file non esiste, lo crea
    if not os.path.exists(DB_FILE):
        logger.info("Database non trovato. Creazione nuovo DB.")
        db = get_default_db()
        save_db(db)
        return db
    
    try:
        with open(DB_FILE, 'r') as f:
            data = json.load(f)
            if not isinstance(data, list): raise ValueError("Il DB non è una lista")
            return data
    except Exception as e:
        logger.error(f"ERRORE LETTURA DB: {e}. Ripristino database di default.")
        # Se il file è corrotto, lo resetta per evitare errore 500
        db = get_default_db()
        save_db(db)
        return db

def save_db(data):
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        logger.info("Database salvato correttamente.")
    except Exception as e:
        logger.error(f"ERRORE SCRITTURA DB: {e}")

# --- 3. ROTTE MASTER ---
@app.route('/master', methods=['GET', 'POST'])
def master_login():
    if session.get('is_master'):
        clienti = load_db()
        return render_template('master_dashboard.html', clienti=clienti)
    
    error = None
    if request.method == 'POST':
        if request.form.get('username') == MASTER_USER and request.form.get('password') == MASTER_PASS:
            session['is_master'] = True
            return redirect(url_for('master_login'))
        else:
            error = "Password Master Errata"
    return render_template('master_login.html', error=error)

@app.route('/master/add', methods=['POST'])
def master_add():
    if not session.get('is_master'): return redirect(url_for('master_login'))
    
    try:
        clienti = load_db()
        # Calcola nuovo ID
        new_id = 1
        if len(clienti) > 0:
            new_id = max(c['id'] for c in clienti) + 1
        
        # Crea nuovo cliente
        new_client = {
            "id": new_id,
            "username": request.form.get('username'),
            "password": request.form.get('password'),
            "slug": request.form.get('slug'),
            "nome": request.form.get('nome'),
            "azienda": "Nuova Azienda",
            "scadenza": "31/12/2026",
            "stato": "Attivo",
            "p1": {
                "active": True, "name": request.form.get('nome'), "role": "", "company": "",
                "foto": "", "cover": "", "bio": "", "mobiles": [], "emails": [], "websites": [], "socials": []
            },
            "p2": {"active": False}, "p3": {"active": False}
        }
        
        clienti.append(new_client)
        save_db(clienti)
        return redirect(url_for('master_login'))
    except Exception as e:
        return f"ERRORE CREAZIONE: {e}", 500

@app.route('/master/delete/<int:id>')
def master_delete(id):
    if not session.get('is_master'): return redirect(url_for('master_login'))
    if id == 1: return "Non puoi cancellare l'Admin principale"
    
    clienti = load_db()
    clienti = [c for c in clienti if c['id'] != id]
    save_db(clienti)
    return redirect(url_for('master_login'))

@app.route('/master/impersonate/<int:id>')
def master_impersonate(id):
    if not session.get('is_master'): return redirect(url_for('master_login'))
    session['logged_in'] = True
    session['user_id'] = id
    return redirect(url_for('area'))

@app.route('/master/logout')
def master_logout():
    session.pop('is_master', None)
    return redirect(url_for('master_login'))

# --- 4. ROTTE CLIENTE ---
@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        clienti = load_db()
        
        # Cerca utente
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

# Gestione errori (Mostra l'errore vero invece di 500 generico)
@app.errorhandler(500)
def server_error(e): return f"<h1>Errore Interno: {e}</h1>", 500

if __name__ == '__main__':
    # DEBUG ATTIVO: Se c'è un errore, te lo scrive sulla pagina
    app.run(debug=True)
