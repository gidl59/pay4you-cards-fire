import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_secret_fixed"

# CONFIGURAZIONE CARTELLE
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# DATI UTENTE
USER_DATA = {
    "username": "admin",
    "password": "password123",
    "nome": "Giuseppe Di Lisio",
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
        if request.form.get('username') == USER_DATA['username'] and request.form.get('password') == USER_DATA['password']:
            session['logged_in'] = True
            return redirect(url_for('area'))
        else:
            error = "Credenziali errate!"
    return render_template('login.html', error=error)

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('dashboard.html', user=USER_DATA)

# --- NUOVE ROTTE PER I TASTI ---

# 1. TASTO APRI P1 (Visualizza la Card)
@app.route('/card/<slug>')
def view_card(slug):
    # Per ora mostriamo una pagina semplice, poi metteremo la grafica vera
    return f"<h1>Card di {slug}</h1><p>Qui vedrai la tua card digitale completa.</p>"

# 2. TASTO MODIFICA P1 (Pagina Modifica)
@app.route('/area/edit/<p_id>')
def edit_profile(p_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('edit_card.html', p_id=p_id)

# 3. ATTIVA P2/P3
@app.route('/area/activate/<p_id>')
def activate_profile(p_id):
    return f"<h1>Attiva Profilo {p_id}</h1><p>Qui compili i dati per P{p_id}</p><a href='/area'>Torna indietro</a>"

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
