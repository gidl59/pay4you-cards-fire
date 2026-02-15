import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_real_data_2026"

# --- CONFIGURAZIONE CARTELLE ---
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- CREDENZIALI MASTER ---
MASTER_USER = "master"
MASTER_PASS = "pay2026"

# --- DATABASE REALE (Qui inseriamo i tuoi dati veri) ---
CLIENTI_DB = [
    {
        "id": 1, 
        "username": "admin", 
        "password": "password123", 
        "slug": "giuseppe-dilisio", # Questo è l'indirizzo della tua card
        "nome": "Giuseppe Di Lisio", 
        "azienda": "Pay4You",
        "scadenza": "31/12/2030", 
        "stato": "Attivo",
        
        # PROFILO P1 (Personale)
        "p1": {
            "active": True, 
            "name": "Giuseppe Di Lisio", 
            "role": "CEO & Founder",
            "foto": "/static/uploads/foto_giuseppe.jpg", # Assicurati che il file esista!
            "bio": "Aiuto professionisti e aziende a digitalizzare la loro immagine.",
            "email": "info@pay4you.it",
            "phone": "+39 333 1234567",
            "website": "www.pay4you.it"
        },
        # PROFILO P2 (Vuoto per ora)
        "p2": {"active": False, "name": "", "foto": ""}, 
        "p3": {"active": False, "name": "", "foto": ""}
    }
]

# --- FIX FAVICON (Forzatura) ---
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

# --- ROTTA VISUALIZZAZIONE CARD (Quella pubblica) ---
@app.route('/card/<slug>')
def view_card(slug):
    # Cerca nel database chi ha questo slug
    user_found = next((c for c in CLIENTI_DB if c['slug'] == slug), None)
    
    if user_found:
        # SE TROVATO: Mostra la card vera
        return render_template('card.html', user=user_found)
    else:
        return "<h1>Card non trovata</h1>", 404

# --- ROTTE LOGIN E DASHBOARD ---
@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        
        user_found = next((c for c in CLIENTI_DB if c['username'] == u and c['password'] == p), None)
        
        if user_found:
            session['logged_in'] = True
            session['user_id'] = user_found['id']
            return redirect(url_for('area'))
        else:
            error = "Credenziali errate!"
    return render_template('login.html', error=error)

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    user_id = session.get('user_id')
    current_user = next((c for c in CLIENTI_DB if c['id'] == user_id), None)
    if not current_user: return redirect(url_for('logout'))
    return render_template('dashboard.html', user=current_user)

@app.route('/master', methods=['GET', 'POST'])
def master_login():
    if session.get('is_master'): return render_template('master_dashboard.html', clienti=CLIENTI_DB)
    error = None
    if request.method == 'POST':
        if request.form.get('username') == MASTER_USER and request.form.get('password') == MASTER_PASS:
            session['is_master'] = True
            return redirect(url_for('master_login'))
        else: error = "Password Master Errata"
    return render_template('master_login.html', error=error)

@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/master/logout')
def master_logout():
    session.pop('is_master', None)
    return redirect(url_for('master_login'))

# Rotte file mancanti (per evitare errori)
@app.route('/area/edit/<p_id>')
def edit_profile(p_id): return "Pagina Modifica (In costruzione)"
@app.route('/area/activate/<p_id>')
def activate_profile(p_id): return "Pagina Attivazione"
@app.route('/privacy')
def privacy(): return render_template('privacy.html')
@app.route('/cookie')
def cookie(): return render_template('cookie.html')

if __name__ == '__main__':
    app.run(debug=True)
