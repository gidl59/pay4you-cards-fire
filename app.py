import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_secret_fixed"

# --- CONFIGURAZIONE CARTELLE ---
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- CREDENZIALI MASTER ADMIN (Solo per te) ---
MASTER_USER = "master"
MASTER_PASS = "pay2026"  # <--- QUESTA È LA TUA PASSWORD SPECIALE

# --- DATABASE CLIENTI (Simulazione di tutte le card vendute) ---
CLIENTI_DB = [
    {
        "id": 1, "username": "admin", "password": "password123",
        "nome": "Giuseppe Di Lisio", "azienda": "Pay4You",
        "scadenza": "31/12/2030", "stato": "Attivo",
        "p1": {"active": True, "slug": "giuseppe"},
        "p2": {"active": False}, "p3": {"active": False}
    },
    {
        "id": 2, "username": "cliente2", "password": "cliente123",
        "nome": "Mario Rossi", "azienda": "Rossi Immobiliare",
        "scadenza": "15/06/2026", "stato": "Attivo",
        "p1": {"active": True, "slug": "mario-rossi"},
        "p2": {"active": True}, "p3": {"active": False}
    },
    {
        "id": 3, "username": "cliente3", "password": "cliente123",
        "nome": "Luca Bianchi", "azienda": "Eventi Roma",
        "scadenza": "01/01/2025", "stato": "Scaduto",
        "p1": {"active": True, "slug": "luca-eventi"},
        "p2": {"active": False}, "p3": {"active": False}
    }
]

# --- ROTTE MASTER ADMIN (Nuove) ---

@app.route('/master', methods=['GET', 'POST'])
def master_login():
    # Se sei già loggato come master, vai alla dashboard
    if session.get('is_master'):
        return render_template('master_dashboard.html', clienti=CLIENTI_DB)
    
    # Altrimenti mostra il login
    error = None
    if request.method == 'POST':
        if request.form.get('username') == MASTER_USER and request.form.get('password') == MASTER_PASS:
            session['is_master'] = True
            return redirect(url_for('master_login'))
        else:
            error = "Accesso Negato: Password Master errata."
    
    return render_template('master_login.html', error=error)

@app.route('/master/logout')
def master_logout():
    session.pop('is_master', None)
    return redirect(url_for('master_login'))

# --- ROTTE CLIENTE (Quelle di prima) ---

@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    # Simuliamo il login cercando nel database clienti
    error = None
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        # Cerca il cliente nella lista
        user_found = next((c for c in CLIENTI_DB if c['username'] == u and c['password'] == p), None)
        
        if user_found:
            session['logged_in'] = True
            session['user_id'] = user_found['id'] # Ricordiamo chi è
            return redirect(url_for('area'))
        else:
            error = "Credenziali errate!"
    return render_template('login.html', error=error)

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    # Recupera i dati del cliente loggato
    current_user = next((c for c in CLIENTI_DB if c['id'] == session.get('user_id')), CLIENT_DB[0])
    return render_template('dashboard.html', user=current_user)

# Rotte di servizio (Apri, Modifica, ecc...)
@app.route('/card/<slug>')
def view_card(slug): return f"<h1>Card: {slug}</h1>"

@app.route('/area/edit/<p_id>')
def edit_profile(p_id): return render_template('edit_card.html', p_id=p_id)

@app.route('/area/forgot')
def forgot(): return render_template('forgot.html')

@app.route('/privacy')
def privacy(): return render_template('privacy.html')

@app.route('/cookie')
def cookie(): return render_template('cookie.html')

@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
