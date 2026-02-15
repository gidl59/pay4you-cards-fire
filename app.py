import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_final_fix_2026"

# --- CONFIGURAZIONE CARTELLE ---
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- CREDENZIALI MASTER (Tua area riservata) ---
MASTER_USER = "master"
MASTER_PASS = "pay2026"

# --- DATABASE CLIENTI ---
# Qui ci sono i dati che alimentano sia la Dashboard che la Card
CLIENTI_DB = [
    {
        "id": 1,
        "username": "admin",        # Login Cliente
        "password": "password123",  # Password Cliente
        "slug": "giuseppe",         # Indirizzo card: /card/giuseppe
        "nome": "Giuseppe Di Lisio",
        "azienda": "Pay4You",
        "scadenza": "31/12/2030",
        "stato": "Attivo",
        
        # DATI PROFILO P1 (Usati nella tua card HTML)
        "p1": {
            "active": True,
            "name": "Giuseppe Di Lisio",
            "role": "CEO & Founder",
            "company": "Pay4You Digital",
            "foto": "/static/uploads/foto_giuseppe.jpg", # Assicurati che il file esista!
            "cover": "/static/uploads/cover.jpg",
            "bio": "Specialista in soluzioni digitali NFC.",
            
            # Liste per la tua card
            "mobiles": ["+39 333 1234567"],
            "emails": ["info@pay4you.it"],
            "websites": ["www.pay4you.it"],
            "socials": [
                {"label": "Facebook", "url": "#"},
                {"label": "Instagram", "url": "#"}
            ]
        },
        "p2": {"active": False}, "p3": {"active": False}
    }
]

# --- 1. ROTTA FAVICON (Fix Icona) ---
@app.route('/favicon.ico')
def favicon():
    # Cerca il file favicon.ico nella cartella static
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

# --- 2. ROTTE MASTER ADMIN (Fix 404) ---
@app.route('/master', methods=['GET', 'POST'])
def master_login():
    # Se sei già loggato master, vedi la lista
    if session.get('is_master'):
        return render_template('master_dashboard.html', clienti=CLIENTI_DB)
    
    error = None
    if request.method == 'POST':
        if request.form.get('username') == MASTER_USER and request.form.get('password') == MASTER_PASS:
            session['is_master'] = True
            return redirect(url_for('master_login'))
        else:
            error = "Password Master Errata"
    
    # Assicurati di avere il file templates/master_login.html
    return render_template('master_login.html', error=error)

@app.route('/master/logout')
def master_logout():
    session.pop('is_master', None)
    return redirect(url_for('master_login'))

# --- 3. ROTTE LOGIN CLIENTE (Fix 500) ---
@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        
        # Cerca utente nel DB
        user = next((c for c in CLIENTI_DB if c['username'] == u and c['password'] == p), None)
        
        if user:
            session['logged_in'] = True
            session['user_id'] = user['id']
            return redirect(url_for('area'))
        else:
            error = "Credenziali errate!"
            
    return render_template('login.html', error=error)

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    # Recupera utente corrente
    user_id = session.get('user_id')
    user = next((c for c in CLIENTI_DB if c['id'] == user_id), None)
    
    if not user: return redirect(url_for('logout'))
    return render_template('dashboard.html', user=user)

# --- 4. ROTTA CARD PUBBLICA (Visualizza la tua card HTML) ---
def dummy_translate(key): return "SALVA CONTATTO"

@app.route('/card/<slug>')
def view_card(slug):
    user = next((c for c in CLIENTI_DB if c['slug'] == slug), None)
    if not user: return "<h1>Card non trovata</h1>", 404
    
    # Prepara i dati per il TUO html originale
    p1 = user['p1']
    ag = {
        "name": p1.get('name', user['nome']),
        "photo_url": p1.get('foto', ''),
        "cover_url": p1.get('cover', ''),
        "photo_pos_x": 50, "photo_pos_y": 50, "photo_zoom": 1,
        "role": p1.get('role', ''),
        "company": p1.get('company', user['azienda']),
        "bio": p1.get('bio', ''),
        "slug": slug
    }
    
    return render_template('card.html', 
                           lang='it', ag=ag, 
                           mobiles=p1.get('mobiles', []),
                           emails=p1.get('emails', []),
                           websites=p1.get('websites', []),
                           socials=p1.get('socials', []),
                           t_func=dummy_translate,
                           profile='p1',
                           p2_enabled=0, p3_enabled=0)

# --- ALTRE ROTTE ---
@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/area/forgot')
def forgot(): return render_template('forgot.html')

@app.route('/privacy')
def privacy(): return render_template('privacy.html')

@app.route('/cookie')
def cookie(): return render_template('cookie.html')

# Rotte placeholder per evitare errori 404 sui tasti
@app.route('/area/edit/<pid>')
def edit_profile(pid): return "Pagina Modifica (In Costruzione)"
@app.route('/area/activate/<pid>')
def activate_profile(pid): return "Pagina Attivazione"

if __name__ == '__main__':
    app.run(debug=True)
