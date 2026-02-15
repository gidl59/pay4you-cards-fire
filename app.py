import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

app = Flask(__name__)
app.secret_key = "pay4you_pro_2026"

# Configurazione Cartelle
if os.path.exists('/var/data'):
    UPLOAD_FOLDER = '/var/data/uploads'
else:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- DATABASE REALE (GIUSEPPE) ---
CLIENTI_DB = [
    {
        "id": 1, 
        "username": "admin", 
        "password": "password123", 
        "slug": "giuseppe", # <--- La tua card sarà su /card/giuseppe
        "nome": "Giuseppe Di Lisio", 
        "azienda": "Pay4You",
        "stato": "Attivo",
        
        # DATI PER LA CARD (P1)
        "p1": {
            "active": True, 
            "name": "Giuseppe Di Lisio", 
            "role": "CEO & Founder",
            "company": "Pay4You Digital",
            # Se non hai ancora le foto, uso dei segnaposto colorati
            "foto": "https://placehold.co/200x200/0088cc/fff?text=GDL", 
            "cover": "https://placehold.co/600x200/111/00ffc8?text=Cover+Pay4You",
            "bio": "Aiuto professionisti e aziende a digitalizzare la loro immagine con Card NFC.",
            
            # LISTE DATI (Come vuole il tuo HTML)
            "mobiles": ["+39 333 1234567"],
            "emails": ["info@pay4you.it"],
            "websites": ["www.pay4you.it"],
            "socials": [
                {"label": "Facebook", "url": "#"},
                {"label": "Instagram", "url": "#"}
            ]
        },
        "p2": {"active": False}, "p3": {"active": False}
    }
]

# Funzione per tradurre le etichette della card
def dummy_translate(key):
    return "SALVA CONTATTO" if key == 'save_contact' else key

# --- ROTTA CARD (Qui avviene la magia) ---
@app.route('/card/<slug>')
def view_card(slug):
    # Cerca il cliente nel database
    user = next((c for c in CLIENTI_DB if c['slug'] == slug), None)
    if not user: return "Card non trovata", 404

    # Prepara i dati per il tuo HTML (variabile 'ag')
    p1 = user['p1']
    ag = {
        "name": p1['name'],
        "role": p1.get('role', ''),
        "company": p1.get('company', ''),
        "bio": p1.get('bio', ''),
        "photo_url": p1['foto'],
        "cover_url": p1.get('cover', ''),
        "photo_pos_x": 50, "photo_pos_y": 50, "photo_zoom": 1,
        "slug": slug
    }

    # Renderizza il TUO file card.html
    return render_template('card.html', 
                           lang='it',
                           ag=ag,
                           mobiles=p1.get('mobiles', []),
                           emails=p1.get('emails', []),
                           websites=p1.get('websites', []),
                           socials=p1.get('socials', []),
                           t_func=dummy_translate,
                           profile='p1',
                           p2_enabled=0, p3_enabled=0)

# --- ROTTE ADMIN / DASHBOARD ---
@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        user = next((c for c in CLIENTI_DB if c['username'] == u and c['password'] == p), None)
        if user:
            session['logged_in'] = True
            session['user_id'] = user['id']
            return redirect(url_for('area'))
    return render_template('login.html')

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    user = next((c for c in CLIENTI_DB if c['id'] == session.get('user_id')), None)
    return render_template('dashboard.html', user=user)

# Rotte extra per evitare errori
@app.route('/favicon.ico')
def favicon(): return send_from_directory('static', 'favicon.ico')
@app.route('/area/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/area/edit/<pid>') 
def edit(pid): return "Pagina Modifica"

if __name__ == '__main__':
    app.run(debug=True)
