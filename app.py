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

# --- DATI UTENTE (CREDENZIALI) ---
USER_DATA = {
    "username": "admin",       # <--- RIMESSO ADMIN
    "password": "password123", # <--- PASSWORD STANDARD
    "nome": "Giuseppe Di Lisio",
    "avatar": "/static/pay4you-logo.png", 
    "p1": {"active": True, "name": "Profilo Personale", "foto": "", "slug": "giuseppe"},
    "p2": {"active": False, "name": "", "foto": "", "slug": ""},
    "p3": {"active": False, "name": "", "foto": "", "slug": ""}
}

@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username_inserito = request.form.get('username')
        password_inserita = request.form.get('password')
        
        # Controllo credenziali
        if username_inserito == USER_DATA['username'] and password_inserita == USER_DATA['password']:
            session['logged_in'] = True
            return redirect(url_for('area'))
        else:
            error = "Credenziali errate! Riprova."
            
    return render_template('login.html', error=error)

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('dashboard.html', user=USER_DATA)

# --- ALTRE ROTTE ---
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
