import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_2026_super_key"

# --- CONFIGURAZIONE DISCO RENDER ---
# Questo blocco evita l'errore "Timed Out" su Render
if os.path.exists('/var/data'):
    # Se siamo su Render col disco montato
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    # Se siamo in locale o il disco non c'è ancora
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

# Crea la cartella se non esiste (senza far crashare l'app)
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except Exception as e:
    print(f"Attenzione: Impossibile creare cartella uploads: {e}")

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- LOGICA MULTILINGUA (Che mi avevi chiesto) ---
def get_texts():
    # Rileva lingua telefono: IT, EN, ES, FR
    lang = request.accept_languages.best_match(['it', 'en', 'es', 'fr']) or 'it'
    
    translations = {
        'it': {'login': 'Area riservata', 'sub': 'Accedi per gestire le tue card', 'user': 'Username', 'pass': 'Password', 'btn': 'Accedi ora'},
        'en': {'login': 'Reserved Area', 'sub': 'Login to manage your cards', 'user': 'Username', 'pass': 'Password', 'btn': 'Login Now'},
        'es': {'login': 'Área reservada', 'sub': 'Accede para gestionar tus tarjetas', 'user': 'Usuario', 'pass': 'Contraseña', 'btn': 'Entrar'},
        'fr': {'login': 'Espace réservé', 'sub': 'Connectez-vous pour gérer vos cartes', 'user': 'Identifiant', 'pass': 'Mot de passe', 'btn': 'Se connecter'}
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

# Rotta per mostrare le immagini salvate sul Disco Render
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    texts = get_texts()
    if request.method == 'POST':
        # Qui potrai mettere il controllo database vero in futuro
        if request.form.get('username') == USER_DATA['username'] and request.form.get('password') == USER_DATA['password']:
            session['logged_in'] = True
            return redirect(url_for('area'))
        flash("Credenziali non valide", "error")
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
