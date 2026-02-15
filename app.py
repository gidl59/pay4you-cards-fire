import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_2026_key"

# Configurazione Caricamenti
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# DATI ADMIN (Cambia password qui)
USER_DATA = {
    "username": "admin",
    "password": "tua_nuova_password", 
    "nome": "Giuseppe Di Lisio",
    "slug": "giuseppe",
    "avatar": "/static/uploads/avatar.jpg",
    "p1_active": True, "p2_active": False, "p3_active": False,
    "p1_fotos": [], "p1_videos": [], "p1_pdfs": []
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    if file and allowed_file(file.filename):
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
