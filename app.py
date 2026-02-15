import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_secret_fixed_v2"

# --- CONFIGURAZIONE CARTELLE ---
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- CREDENZIALI MASTER ADMIN (Tua password segreta) ---
MASTER_USER = "master"
MASTER_PASS = "pay2026"

# --- DATABASE CLIENTI (Ecco i tuoi vecchi dati!) ---
# Qui ho rimesso i tuoi dati come ID 1, così il login admin/password123 funziona
CLIENTI_DB = [
    {
        "id": 1, 
        "username": "admin", 
        "password": "password123", # Le tue vecchie credenziali
        "nome": "Giuseppe Di Lisio", 
        "azienda": "Pay4You",
        "avatar": "/static/pay4you-logo.png",
        "scadenza": "31/12/2030", 
        "stato": "Attivo",
        # I tuoi profili
        "p1": {"active": True, "name": "Profilo Personale", "slug": "giuseppe", "foto": "/static/uploads/foto_giuseppe.jpg"},
        "p2": {"active": False, "name": "", "slug": "", "foto": ""}, 
        "p3": {"active": False, "name": "", "slug": "", "foto": ""}
    },
    {
        "id": 2, 
        "username": "mario", 
        "password": "123",
        "nome": "Mario Rossi", 
        "azienda": "Rossi Immobiliare",
        "avatar": "",
        "scadenza": "15/06/2026", 
        "stato": "Attivo",
        "p1": {"active": True, "name": "Agente Immobiliare", "slug": "mario-rossi", "foto": ""},
        "p2": {"active": True, "name": "Ufficio", "slug": "rossi-agency", "foto": ""}, 
        "p3": {"active": False, "name": "", "slug": "", "foto": ""}
    }
]

# --- ROTTA FAVICON (Risolve icona mancante) ---
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

# --- ROTTE MASTER ADMIN ---
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

# --- ROTTE CLIENTE (Fix Errore 500) ---
@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        
        # Cerca l'utente dentro la lista CLIENTI_DB
        user_found = None
        for cliente in CLIENTI_DB:
            if cliente['username'] == u and cliente['password'] == p:
                user_found = cliente
                break
        
        if user_found:
            session['logged_in'] = True
            session['user_id'] = user_found['id'] # Salviamo l'ID per trovarlo dopo
            return redirect(url_for('area'))
        else:
            error = "Credenziali errate!"
            
    return render_template('login.html', error=error)

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    # Recupera i dati dell'utente loggato usando l'ID
    user_id = session.get('user_id')
    current_user = None
    
    for cliente in CLIENTI_DB:
        if cliente['id'] == user_id:
            current_user = cliente
            break
            
    if not current_user:
        # Se c'è un errore e non trova l'utente, torna al login
        return redirect(url_for('logout'))

    return render_template('dashboard.html', user=current_user)

# --- ROTTE DI SERVIZIO ---
@app.route('/card/<slug>')
def view_card(slug):
    # Qui ci sarà la tua CARD VERA. Per ora testo, ma il link funziona.
    return f"<h1>Card di {slug}</h1><p>La tua card è salva, stiamo lavorando solo sul pannello di controllo!</p>"

@app.route('/area/edit/<p_id>')
def edit_profile(p_id): return render_template('edit_card.html', p_id=p_id)

@app.route('/area/activate/<p_id>')
def activate_profile(p_id): return f"Attivazione {p_id}"

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
