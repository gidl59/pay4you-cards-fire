import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_2026_fire"

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- CREDENZIALI DI ACCESSO ---
USER_DATA = {
    "username": "admin",
    "password": "password123", # <--- USA QUESTA ORA
    "nome": "Giuseppe Di Lisio",
    "slug": "giuseppe",
    "avatar": "/static/uploads/avatar.jpg",
    "p1_active": True, "p2_active": False, "p3_active": False,
    "p1_fotos": [], "p1_videos": [], "p1_pdfs": []
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

# --- FIX PASSWORD DIMENTICATA ---
@app.route('/area/forgot')
def forgot():
    return render_template('forgot.html')

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('dashboard.html', user=USER_DATA)

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
