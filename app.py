import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_premium_2026"

# --- CONFIGURAZIONE RENDER PERSISTENCE ---
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- TRADUZIONI ---
TRANSLATIONS = {
    'it': {'welcome': 'Benvenuto', 'save': 'Salva', 'profile': 'Profilo Personale'},
    'en': {'welcome': 'Welcome', 'save': 'Save', 'profile': 'Personal Profile'},
    'es': {'welcome': 'Bienvenido', 'save': 'Guardar', 'profile': 'Perfil Personal'},
    'fr': {'welcome': 'Bienvenue', 'save': 'Enregistrer', 'profile': 'Profil Personnel'}
}

def get_locale():
    # Rileva la lingua del browser/telefono
    lang = request.accept_languages.best_match(['it', 'en', 'es', 'fr'])
    return lang or 'it'

# --- DATABASE CLIENTI ---
USER_DATA = {
    "username": "admin",
    "password": "password123",
    "nome": "Giuseppe Di Lisio",
    "avatar": "/static/uploads/avatar.jpg",
    "p1": {"name": "Profilo Personale", "active": True, "foto": "/static/uploads/agente1.jpg"},
    "p2": {"name": "Profilo Business", "active": False, "foto": "/static/uploads/agente2.jpg"},
    "p3": {"name": "Profilo Eventi", "active": False, "foto": "/static/uploads/agente3.jpg"}
}

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == USER_DATA['username'] and request.form['password'] == USER_DATA['password']:
            session['logged_in'] = True
            return redirect(url_for('area'))
        flash("Errore", "error")
    return render_template('login.html')

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    lang = get_locale()
    texts = TRANSLATIONS.get(lang, TRANSLATIONS['it'])
    return render_template('dashboard.html', user=USER_DATA, lang_text=texts)

@app.route('/area/forgot')
def forgot():
    return render_template('forgot.html')

@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
