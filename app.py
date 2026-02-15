import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "pay4you_master_key_2026"

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# DATABASE SIMULATO (Dashboard Cliente)
USER_DATA = {
    "username": "admin",
    "password": "password123",
    "nome": "Giuseppe Di Lisio",
    "avatar": "/static/uploads/avatar.jpg", # Foto profilo generale
    "p1": {"name": "Profilo Personale", "active": True, "foto": "/static/uploads/agente1.jpg", "tipo": "Principale"},
    "p2": {"name": "Profilo Business", "active": False, "foto": "/static/uploads/agente2.jpg", "tipo": "Secondario"},
    "p3": {"name": "Profilo Eventi", "active": False, "foto": "/static/uploads/agente3.jpg", "tipo": "Secondario"}
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

@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
