import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_2026_global_disk"

# --- CONFIGURAZIONE DISCO RENDER (/var/data) ---
# Usiamo /var/data per i file persistenti e static per i file di sistema
UPLOAD_FOLDER = '/var/data/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- LOGICA MULTILINGUA ---
def get_texts():
    lang = request.accept_languages.best_match(['it', 'en', 'es', 'fr']) or 'it'
    translations = {
        'it': {'login': 'Area riservata', 'user': 'Username', 'pass': 'Password', 'btn': 'Accedi ora'},
        'en': {'login': 'Reserved Area', 'user': 'Username', 'pass': 'Password', 'btn': 'Login Now'},
        'es': {'login': 'Área reservada', 'user': 'Usuario', 'pass': 'Contraseña', 'btn': 'Entrar ahora'},
        'fr': {'login': 'Espace réservé', 'user': 'Identifiant', 'pass': 'Mot de passe', 'btn': 'Se connecter'}
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

# Rotta per servire i file dal disco esterno di Render
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    texts = get_texts()
    if request.method == 'POST':
        if request.form['username'] == USER_DATA['username'] and request.form['password'] == USER_DATA['password']:
            session['logged_in'] = True
            return redirect(url_for('area'))
        flash("Errore login", "error")
    return render_template('login.html', t=texts)

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('dashboard.html', user=USER_DATA)

@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
