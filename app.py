import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_2026_key"

# --- CONFIGURAZIONE CARICAMENTI ---
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'ico'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- ROTTA SPECIFICA PER LA FAVICON ---
# Questa funzione risolve il problema dell'icona mancante
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

# --- DATI ADMIN ---
USER_DATA = {
    "username": "admin",
    "password": "tua_password_qui", 
    "nome": "Giuseppe Di Lisio",
    "slug": "giuseppe",
    "avatar": "/static/uploads/avatar.jpg",
    "p1_active": True, "p2_active": False, "p3_active": False,
    "p1_fotos": [], "p1_videos": [], "p1_pdfs": []
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
        flash("Credenziali errate!", "error")
    return render_template('login.html')

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('dashboard.html', user=USER_DATA)

@app.route('/upload/<p_id>/<type>', methods=['POST'])
def upload(p_id, type):
    if 'file' not in request.files: return redirect(request.url)
    file = request.files['file']
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        flash(f"{type.capitalize()} caricato!", "success")
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
