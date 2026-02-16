import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, make_response
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.jinja_env.add_extension('jinja2.ext.do')
app.secret_key = "pay4you_2026_final_stable_v9"

# CONFIG
if os.path.exists('/var/data'):
    BASE_DIR = '/var/data'
else:
    BASE_DIR = os.path.join(os.getcwd(), 'static')

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_FILE = os.path.join(BASE_DIR, 'clients.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024 

# DB LOAD (Sintassi sicura)
def load_db():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

# DB SAVE (Sintassi sicura)
def save_db(data):
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Errore DB: {e}")

def save_file(file, prefix):
    if file and file.filename:
        filename = secure_filename(f"{prefix}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return f"/uploads/{filename}"
    return None

def repair_user(user):
    dirty = False
    if 'default_profile' not in user:
        user['default_profile'] = 'p1'
        dirty = True
    for pid in ['p1', 'p2', 'p3']:
        if pid not in user:
            user[pid] = {'active': False}
            dirty = True
        p = user[pid]
        defaults = {
            'name':'', 'role':'', 'company':'', 'bio':'', 'foto':'', 'logo':'', 'personal_foto':'',
            'office_phone': '', 'address': '', 
            'mobiles':[], 'emails':[], 'websites':[], 'socials':[],
            'gallery_img':[], 'gallery_vid':[], 'gallery_pdf':[],
            'piva':'', 'cod_sdi':'', 'pec':'',
            'fx_rotate_logo':'off', 'fx_rotate_agent':'off',
            'fx_interaction':'tap', 'fx_back_content':'logo',
            'pos_x':50, 'pos_y':50, 'zoom':1,
            'trans': {'en':{}, 'fr':{}, 'es':{}, 'de':{}}
        }
        for k, v in defaults.items():
            if k not in p:
                p[k] = v
                dirty = True
        if not isinstance(p.get('emails'), list): p['emails'] = []
        if not isinstance(p.get('websites'), list): p['websites'] = []
        if p.get('socials') is None: p['socials'] = []; dirty = True
        if p.get('gallery_img') is None: p['gallery_img'] = []; dirty = True
    return dirty

# VCF GENERATOR (Apple Optimized)
@app.route('/vcf/<slug>')
def download_vcf(slug):
    clienti = load_db()
    user = next((c for c in clienti if c['slug'] == slug), None)
    if not user: return "Errore", 404
    
    p_req = request.args.get('p', user.get('default_profile', 'p1'))
    if p_req == 'menu': p_req = 'p1'
    if not user.get(p_req, {}).get('active'): p_req = 'p1'
    p = user[p_req]

    # Costruzione Linea per Linea
    lines = []
    lines.append("BEGIN:VCARD")
    lines.append("VERSION:3.0")
    
    n_val = p.get('name', 'Contatto').strip()
    lines.append(f"FN:{n_val}")
    lines.append(f"N:;{n_val};;;")
    
    if p.get('company'): lines.append(f"ORG:{p.get('company')}")
    if p.get('role'): lines.append(f"TITLE:{p.get('role')}")
    
    for m in p.get('mobiles', []):
        if m: lines.append(f"TEL;type=CELL;type=VOICE:{m}")
    if p.get('office_phone'):
        lines.append(f"TEL;type=WORK;type=VOICE:{p.get('office_phone')}")
        
    for e_list in p.get('emails', []):
        for e in e_list.split(','):
            if e.strip(): lines.append(f"EMAIL;type=INTERNET;type=WORK:{e.strip()}")
            
    for w_list in p.get('websites', []):
        for w in w_list.split(','):
            if w.strip(): lines.append(f"URL;type=WORK:{w.strip()}")
            
    # Link Card Digitale
    card_url = f"https://pay4you-cards-fire.onrender.com/card/{slug}"
    lines.append(f"item1.URL:{card_url}")
    lines.append(f"item1.X-ABLabel:CARD DIGITALE PAY4YOU")

    # Note
    notes = []
    if p.get('piva'): notes.append(f"P.IVA: {p.get('piva')}")
    if p.get('cod_sdi'): notes.append(f"SDI: {p.get('cod_sdi')}")
    if p.get('pec'): notes.append(f"PEC: {p.get('pec')}")
    if p.get('bio'): notes.append(str(p.get('bio')).replace('\n', ' '))
    
    if notes:
        note_str = " - ".join(notes)
        lines.append(f"NOTE:{note_str}")

    lines.append("END:VCARD")
    
    vcf_content = "\r\n".join(lines)
    response = make_response(vcf_content)
    response.headers["Content-Disposition"] = f"attachment; filename={slug}.vcf"
    response.headers["Content-Type"] = "text/x-vcard; charset=utf-8"
    return response

# ROUTES
@app.route('/')
def home(): return redirect(url_for('login'))
@app.route('/area/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        clienti = load_db()
        user = next((c for c in clienti if c['username'] == request.form.get('username') and c['password'] == request.form.get('password')), None)
        if user:
            session['logged_in']=True; session['user_id']=user['id']
            repair_user(user); save_db(clienti)
            return redirect(url_for('area'))
    return render_template('login.html')

@app.route('/area')
def area():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('dashboard.html', user=next((c for c in load_db() if c['id'] == session.get('user_id')), None))

@app.route('/area/activate/<p_id>')
def activate_profile(p_id):
    clienti = load_db(); user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    user['p'+p_id]['active'] = True; save_db(clienti); return redirect(url_for('area'))

@app.route('/area/deactivate/<p_id>')
def deactivate_profile(p_id):
    if p_id == '1': return "No"; 
    clienti = load_db(); user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    user['p'+p_id]['active'] = False; save_db(clienti); return redirect(url_for('area'))

@app.route('/area/set_default/<mode>')
def set_default_profile(mode):
    clienti = load_db(); user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    if mode.startswith('p') and user[mode]['active']: user['default_profile'] = mode
    elif mode == 'menu': user['default_profile'] = 'menu'
    save_db(clienti); return redirect(url_for('area'))

@app.route('/area/edit/<p_id>', methods=['GET', 'POST'])
def edit_profile(p_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    clienti = load_db(); user = next((c for c in clienti if c['id'] == session.get('user_id')), None)
    if not user: return redirect(url_for('logout'))
    repair_user(user); p_key = 'p' + p_id
    if not user[p_key].get('active'): user[p_key]['active'] = True; save_db(clienti)
    
    if request.method == 'POST':
        p = user[p_key]; prefix = f"u{user['id']}_{p_id}"
        p['name'] = request.form.get('name'); p['role'] = request.form.get('role')
        p['company'] = request.form.get('company'); p['bio'] = request.form.get('bio')
        p['piva'] = request.form.get('piva'); p['cod_sdi'] = request.form.get('cod_sdi'); p['pec'] = request.form.get('pec')
        p['office_phone'] = request.form.get('office_phone'); p['address'] = request.form.get('address')
        p['mobiles'] = [x for x in [request.form.get('mobile1'), request.form.get('mobile2')] if x]
        p['emails'] = [x for x in [request.form.get('email1')] if x]
        p['websites'] = [x for x in [request.form.get('website')] if x]
        
        socials = []
        for soc in ['Facebook', 'Instagram', 'Linkedin', 'TikTok', 'Spotify', 'Telegram', 'YouTube']:
            url = request.form.get(soc.lower()); 
            if url: socials.append({'label': soc, 'url': url})
        p['socials'] = socials

        p['fx_rotate_logo'] = 'on' if request.form.get('fx_rotate_logo') else 'off'
        p['fx_rotate_agent'] = 'on' if request.form.get('fx_rotate_agent') else 'off'
        p['fx_interaction'] = request.form.get('fx_interaction', 'tap')
        p['fx_back_content'] = request.form.get('fx_back_content', 'logo')
        
        p['pos_x'] = request.form.get('pos_x', 50); p['pos_y'] = request.form.get('pos_y', 50); p['zoom'] = request.form.get('zoom', 1)

        p['trans'] = {
            'en': {'role': request.form.get('role_en'), 'bio': request.form.get('bio_en')},
            'fr': {'role': request.form.get('role_fr'), 'bio': request.form.get('bio_fr')},
            'es': {'role': request.form.get('role_es'), 'bio': request.form.get('bio_es')},
            'de': {'role': request.form.get('role_de'), 'bio': request.form.get('bio_de')}
        }

        if 'foto' in request.files: p['foto'] = save_file(request.files['foto'], f"{prefix}_foto") or p['foto']
        if 'logo' in request.files: p['logo'] = save_file(request.files['logo'], f"{prefix}_logo") or p['logo']
        if 'personal_foto' in request.files: p['personal_foto'] = save_file(request.files['personal_foto'], f"{prefix}_pers") or p['personal_foto']

        if 'gallery_img' in request.files:
            for f in request.files.getlist('gallery_img'): path = save_file(f, f"{prefix}_gimg"); 
            if path: p['gallery_img'].append(path)
        if 'gallery_pdf' in request.files:
            for f in request.files.getlist('gallery_pdf'): path = save_file(f, f"{prefix}_gpdf"); 
            if path: p['gallery_pdf'].append({'path': path, 'name': f.filename})
        if 'gallery_vid' in request.files:
            for f in request.files.getlist('gallery_vid'): path = save_file(f, f"{prefix}_gvid"); 
            if path: p['gallery_vid'].append(path)
        
        if request.form.get('delete_media'):
            to_del = request.form.getlist('delete_media')
            p['gallery_img'] = [x for x in p.get('gallery_img',[]) if x not in to_del]
            p['gallery_pdf'] = [x for x in p.get('gallery_pdf',[]) if x['path'] not in to_del]
            p['gallery_vid'] = [x for x in p.get('gallery_vid',[]) if x not in to_del]

        save_db(clienti); return redirect(url_for('area'))
    return render_template('edit_card.html', p=user[p_key], p_id=p_id)

@app.route('/master', methods=['GET', 'POST'])
def master_login():
    if session.get('is_master'): return render_template('master_dashboard.html', clienti=load_db(), files=[])
    if request.method=='POST' and request.form.get('password')=="pay2026": session['is_master']=True; return redirect(url_for('master_login'))
    return render_template('master_login.html')
@app.route('/master/add', methods=['POST'])
def master_add():
    clienti = load_db(); new_id = max([c['id'] for c in clienti], default=0) + 1
    chars = string.ascii_letters + string.digits + "!@#"; auto_pass = ''.join(random.choices(chars, k=10))
    final_pass = request.form.get('password') if request.form.get('password') else auto_pass
    slug = request.form.get('slug') or f"card-{new_id}"
    new_c = {"id": new_id, "username": request.form.get('username') or f"user{new_id}", "password": final_pass, "slug": slug, "nome": request.form.get('nome') or "Nuovo", "azienda": "New", "p1": {"active": True}, "p2": {"active": False}, "p3": {"active": False}, "default_profile": "p1"}
    repair_user(new_c); clienti.append(new_c); save_db(clienti); return redirect(url_for('master_login'))

@app.route('/card/<slug>')
def view_card(slug):
    clienti = load_db(); user = next((c for c in clienti if c['slug'] == slug), None)
    if not user: return "<h1>Card non trovata</h1>", 404
    if repair_user(user): save_db(clienti)
    default_p = user.get('default_profile', 'p1'); p_req = request.args.get('p')
    if not p_req: p_req = default_p
    if p_req == 'menu': return render_template('menu_card.html', user=user, slug=slug)
    if not user.get(p_req, {}).get('active'): p_req = 'p1'
    p = user[p_req]
    ag = {
        "name": p.get('name'), "role": p.get('role'), "company": p.get('company'),
        "bio": p.get('bio'), "photo_url": p.get('foto'), "logo_url": p.get('logo'),
        "personal_url": p.get('personal_foto'), "slug": slug,
        "piva": p.get('piva'), "pec": p.get('pec'), "cod_sdi": p.get('cod_sdi'),
        "office_phone": p.get('office_phone'), "address": p.get('address'),
        "fx_rotate_logo": p.get('fx_rotate_logo'), "fx_rotate_agent": p.get('fx_rotate_agent'),
        "fx_interaction": p.get('fx_interaction'), "fx_back": p.get('fx_back_content'),
        "photo_pos_x": p.get('pos_x', 50), "photo_pos_y": p.get('pos_y', 50), "photo_zoom": p.get('zoom', 1),
        "trans": p.get('trans', {})
    }
    return render_template('card.html', lang='it', ag=ag, mobiles=p.get('mobiles', []), emails=p.get('emails', []), websites=p.get('websites', []), socials=p.get('socials', []), p_data=p, profile=p_req, p2_enabled=user['p2']['active'], p3_enabled=user['p3']['active'])

@app.route('/master/delete/<int:id>')
def master_delete(id): save_db([c for c in load_db() if c['id'] != id]); return redirect(url_for('master_login'))
@app.route('/master/impersonate/<int:id>')
def master_impersonate(id): session['logged_in']=True; session['user_id']=id; return redirect(url_for('area'))
@app.route('/master/logout')
def master_logout(): session.pop('is_master', None); return redirect(url_for('master_login'))
@app.route('/area/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/uploads/<filename>')
def uploaded_file(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
@app.route('/favicon.ico')
def favicon(): return send_from_directory('static', 'favicon.ico')
@app.route('/reset-tutto')
def reset_db_emergency():
    if os.path.exists(DB_FILE):
        try: os.remove(DB_FILE); return "DB CANCELLATO"
        except: pass
    return "DB PULITO"

if __name__ == '__main__': app.run(debug=True)
