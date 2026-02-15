import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_2026_super_key"

# --- CONFIGURAZIONE DISCO RENDER ---
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except:
    pass

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- LOGICA TESTI MULTILINGUA ---
def get_texts():
    lang = request.accept_languages.best_match(['it', 'en', 'es', 'fr']) or 'it'
    translations = {
        'it': {'login': 'Area Riservata', 'sub': 'Gestione Card', 'user': 'Nome Utente', 'pass': 'Password', 'btn': 'ACCEDI'},
        'en': {'login': 'Reserved Area', 'sub': 'Card Management', 'user': 'Username', 'pass': 'Password', 'btn': 'LOGIN'},
        'es': {'login': 'Área Privada', 'sub': 'Gestión Tarjetas', 'user': 'Usuario', 'pass': 'Contraseña', 'btn': 'ENTRAR'},
        'fr': {'login': 'Espace Privé', 'sub': 'Gestion Cartes', 'user': 'Utilisateur', 'pass': 'Mot de passe', 'btn': 'CONNEXION'}
    }
    return translations[lang]

# --- DATI UTENTE ---
USER_DATA = {
    "username": "admin",
    "password": "password123",
    "nome": "Giuseppe Di Lisio",
    "avatar": "/uploads/avatar.jpg",
    "p1": {"name": "Profilo Personale", "active": True, "foto": "/uploads/agente1.jpg"},
    "p2": {"name": "Profilo Business", "active": False, "foto": "/uploads/agente2.jpg"},
    "p3": {"name": "Profilo Eventi", "active": False, "foto": "/uploads/agente3.jpg"}
}

# --- ROTTE FILE SYSTEM ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico')

# --- ROTTE PAGINE ---
@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    texts = get_texts()
    if request.method == 'POST':
        if request.form.get('username') == USER_DATA['username'] and request.form.get('password') == USER_DATA['password']:
            session['logged_in'] = True
            return redirect(url_for('area'))
        flash("Dati non validi", "error")
    return render_template('login.html', t=texts)

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('dashboard.html', user=USER_DATA)

@app.route('/area/forgot')
def forgot():
    # Se non hai ancora forgot.html, usa login per ora o crea il file
    return render_template('forgot.html') if os.path.exists('templates/forgot.html') else "Pagina recupero in costruzione (File mancante)"

@app.route('/privacy')
def privacy(): return render_template('privacy.html') if os.path.exists('templates/privacy.html') else "Pagina Privacy"

@app.route('/cookie')
def cookie(): return render_template('cookie.html') if os.path.exists('templates/cookie.html') else "Pagina Cookie"

@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
