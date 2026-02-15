import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_2026_super_secret_key"

# --- CONFIGURAZIONE ---
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- CREDENZIALI MASTER ---
MASTER_USER = "master"
MASTER_PASS = "pay2026"

# --- IL TUO DATABASE CLIENTI ---
# Qui devi reinserire i tuoi clienti. Ho messo Giuseppe + spazi vuoti per gli altri.
CLIENTI_DB = [
    # CLIENTE 1 (TU)
    {
        "id": 1,
        "username": "admin",
        "password": "password123",
        "slug": "giuseppe",
        "nome": "Giuseppe Di Lisio",
        "azienda": "Pay4You",
        "scadenza": "31/12/2030",
        "stato": "Attivo",
        "p1": {
            "active": True, "name": "Giuseppe Di Lisio", "role": "CEO", "company": "Pay4You",
            "foto": "/static/uploads/foto_giuseppe.jpg", "cover": "", "bio": "Digital Cards Expert",
            "mobiles": ["+39 333 1234567"], "emails": ["info@pay4you.it"], "websites": ["www.pay4you.it"],
            "socials": [{"label": "Facebook", "url": "#"}]
        },
        "p2": {"active": False}, "p3": {"active": False}
    },
    # CLIENTE 2 (Esempio - Modificalo con un tuo cliente vero)
    {
        "id": 2,
        "username": "cliente2",
        "password": "123",
        "slug": "mario-rossi",
        "nome": "Mario Rossi",
        "azienda": "Immobiliare Rossi",
        "scadenza": "30/06/2026",
        "stato": "Attivo",
        "p1": {
            "active": True, "name": "Mario Rossi", "role": "Agente", "company": "Immobiliare Rossi",
            "foto": "", "cover": "", "bio": "Vendo case belle.",
            "mobiles": ["+39 333 0000000"], "emails": ["mario@rossi.it"], "websites": [],
            "socials": []
        },
        "p2": {"active": False}, "p3": {"active": False}
    }
    # QUI SOTTO PUOI INCOLLARE GLI ALTRI 18 CLIENTI COPIANDO IL BLOCCO SOPRA
    # Ricordati di cambiare ID, username e slug per ognuno!
]

# --- 1. ROTTA FAVICON ---
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

# --- 2. MASTER ADMIN ---
@app.route('/master', methods=['GET', 'POST'])
def master_login():
    if session.get('is_master'):
        return render_template('master_dashboard.html', clienti=CLIENTI_DB)
    error = None
    if request.method == 'POST':
        if request.form.get('username') == MASTER_USER and request.form.get('password') == MASTER_PASS:
            session['is_master'] = True
            return redirect(url_for('master_login'))
        else:
            error = "Password Master Errata"
    return render_template('master_login.html', error=error)

@app.route('/master/logout')
def master_logout():
    session.pop('is_master', None)
    return redirect(url_for('master_login'))

# --- 3. LOGIN CLIENTE ---
@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        # Cerca nel database
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
    user_id = session.get('user_id')
    user = next((c for c in CLIENTI_DB if c['id'] == user_id), None)
    if not user: return redirect(url_for('logout'))
    return render_template('dashboard.html', user=user)

# --- 4. VISUALIZZAZIONE CARD ---
def dummy_t(k): return "SALVA CONTATTO"

@app.route('/card/<slug>')
def view_card(slug):
    user = next((c for c in CLIENTI_DB if c['slug'] == slug), None)
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
    
    return render_template('card.html', 
                           lang='it', ag=ag, 
                           mobiles=p1.get('mobiles', []),
                           emails=p1.get('emails', []),
                           websites=p1.get('websites', []),
                           socials=p1.get('socials', []),
                           t_func=dummy_t, profile='p1',
                           p2_enabled=0, p3_enabled=0)

# --- ALTRE ROTTE ---
@app.route('/area/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/area/forgot')
def forgot(): return render_template('forgot.html')
@app.route('/privacy')
def privacy(): return render_template('privacy.html')
@app.route('/cookie')
def cookie(): return render_template('cookie.html')
@app.route('/area/edit/<pid>')
def edit_profile(pid): return render_template('edit_card.html', p_id=pid) if os.path.exists('templates/edit_card.html') else "File edit mancante"
@app.route('/area/activate/<pid>')
def activate_profile(pid): return "Attivazione..."

if __name__ == '__main__':
    app.run(debug=True)
