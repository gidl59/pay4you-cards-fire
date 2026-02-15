from flask import Flask, render_template, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = "pay4you_secret_key_2026"

# Simulazione Database Utente
USER_DATA = {
    "username": "admin",
    "password": "password123",
    "nome": "Giuseppe Di Lisio",
    "slug": "giuseppe",
    "avatar": "/static/uploads/avatar.jpg",
    "p1_active": True,
    "p2_active": True,
    "p3_active": False,
    "p1_fotos": ["/static/uploads/f1.jpg", "/static/uploads/f2.jpg"],
    "p1_videos": [],
    "p1_pdfs": []
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
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html', user=USER_DATA)

# --- FIX PRIVACY E COOKIE ---
@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/cookie')
def cookie():
    return render_template('cookie.html')

@app.route('/area/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
