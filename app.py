import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_fixed_2026"

# Configurazione Cartelle
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# DATI CLIENTE (P2 e P3 sono Inattivi/Vuoti)
USER_DATA = {
    "username": "cliente",
    "password": "password123",
    "nome": "Giuseppe Di Lisio",
    "avatar": "/static/uploads/avatar.jpg", # Assicurati che esista o usa placeholder
    "p1": {"active": True, "name": "Profilo Personale", "foto": "/static/uploads/p1.jpg", "slug": "giuseppe"},
    "p2": {"active": False, "name": "", "foto": "", "slug": ""}, # Vuoto
    "p3": {"active": False, "name": "", "foto": "", "slug": ""}  # Vuoto
}

@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == USER_DATA['username'] and request.form.get('password') == USER_DATA['password']:
            session['logged_in'] = True
            return redirect(url_for('area'))
    return render_template('login.html')

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('dashboard.html', user=USER_DATA)

@app.route('/area/activate/<p_id>')
def activate_profile(p_id):
    # Qui attiverai il profilo (logica futura)
    return f"<h1>Attivazione Profilo {p_id}</h1><p>Qui si apre la scheda vuota da compilare.</p><a href='/area'>Torna indietro</a>"

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
