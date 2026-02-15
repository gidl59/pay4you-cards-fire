import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_cards_2026_premium_fix"

# Configurazione Cartelle
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- DATABASE UTENTE (Dati Esempio) ---
USER_DATA = {
    "username": "admin",
    "password": "password123",
    "nome": "Giuseppe Di Lisio",
    "slug": "giuseppe",
    "avatar": "/static/uploads/avatar.jpg",
    # Profilo 1 (Sempre Attivo)
    "p1_name": "Profilo Personale",
    "p1_active": True,
    "p1_foto_agente": "/static/uploads/agente1.jpg",
    # Profilo 2
    "p2_name": "Profilo Business",
    "p2_active": False,
    "p2_foto_agente": "/static/uploads/agente2.jpg",
    # Profilo 3
    "p3_name": "Profilo Eventi",
    "p3_active": False,
    "p3_foto_agente": "/static/uploads/agente3.jpg"
}

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico')

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == USER_DATA['username'] and request.form['password'] == USER_DATA['password']:
            session['logged_in'] = True
            return redirect(url_for('area'))
        flash("Credenziali errate!", "error")
    return render_template('login.html')

@app.route('/area/forgot')
def forgot():
    return render_template('forgot.html')

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('dashboard.html', user=USER_DATA)

@app.route('/upload/<p_id>/<file_type>', methods=['POST'])
def upload(p_id, file_type):
    if 'file' not in request.files: return redirect(url_for('area'))
    file = request.files['file']
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        flash(f"{file_type.upper()} caricato con successo!", "success")
    return redirect(url_for('area'))

@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/privacy')
def privacy(): return render_template('privacy.html')

@app.route('/cookie')
def cookie(): return render_template('cookie.html')

if __name__ == '__main__':
    app.run(debug=True)
