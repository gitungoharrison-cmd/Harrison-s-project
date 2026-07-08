import os
import base64
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'nps_core_infrastructure_secure_encryption_vector_key'

# ==========================================
# PRODUCTION RENDER PERSISTENT DISK ARCHITECTURE
# ==========================================
if os.path.exists('/data'):
    UPLOAD_FOLDER = '/data/uploads'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/dpobcms_core.db'
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR, 'dpobcms_core.db')}"

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'xlsx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ==========================================
# DATABASE SCHEMATIC LAYER MODELS
# ==========================================

class SystemUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_number = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    rank = db.Column(db.String(50), nullable=False)
    station = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), nullable=False)  
    password_hash = db.Column(db.String(128), nullable=False)

class OccurrenceBook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ob_number = db.Column(db.String(50), unique=True, nullable=False)
    date_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    jurisdiction = db.Column(db.String(100), nullable=False)
    complainant_name = db.Column(db.String(100), nullable=False)
    complainant_phone = db.Column(db.String(50), nullable=False)
    nature_of_offence = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='PENDING REVIEW', nullable=False) 
    recorded_by = db.Column(db.String(50), nullable=False)
    suspect_photo = db.Column(db.Text, nullable=True)  
    evidence_file = db.Column(db.String(255), nullable=True)  

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    operator = db.Column(db.String(50), nullable=False)
    action = db.Column(db.Text, nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)

def commit_audit(action_desc):
    operator = session.get('service_number', 'SYSTEM-DAEMON')
    ip = request.remote_addr or '127.0.0.1'
    log_entry = AuditLog(operator=operator, action=action_desc, ip_address=ip)
    db.session.add(log_entry)
    db.session.commit()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))

# ==========================================
# SYSTEM FUNCTIONAL ROUTES LAYER
# ==========================================

@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        srv_num = request.form['service_number'].strip().upper()
        pwd = request.form['password']
        
        user = SystemUser.query.filter_by(service_number=srv_num).first()
        if user and user.password_hash == pwd:
            session['logged_in'] = True
            session['user_id'] = user.id
            session['service_number'] = user.service_number
            session['user_name'] = user.name
            session['role'] = user.role
            session['station'] = user.station
            
            commit_audit(f"User Session Authenticated safely. Authorization role vector granted: [{user.role}]")
            return redirect(url_for('dashboard'))
        
        flash('Invalid Service Number credentials or hardware authorization handshake mismatch.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    commit_audit("Session termination manually executed by connected user station node.")
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    total_ob = OccurrenceBook.query.count()
    active_cases = OccurrenceBook.query.filter(OccurrenceBook.status.in_(['PENDING REVIEW', 'INVESTIGATING'])).count()
    concluded = OccurrenceBook.query.filter(OccurrenceBook.status.in_(['CLOSED', 'PROVEN INNOCENT'])).count()
    return render_template('dashboard.html', total_ob=total_ob, active_cases=active_cases, concluded=concluded)

# -------------------------------------------------------------
# DUAL OB ENDPOINTS TO RECONCILE ALL JINJA TEMPLATE LINKS
# -------------------------------------------------------------
@app.route('/ob/view', methods=['GET', 'POST'])
def register_ob():
    """Handles references to url_for('register_ob')"""
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        count = OccurrenceBook.query.count() + 1
        ob_serial = f"OB/{datetime.now().year}/{count:06d}"
        
        new_entry = OccurrenceBook(
            ob_number=ob_serial,
            jurisdiction=session.get('station', 'Nyeri Central Police Station'),
            complainant_name=request.form['complainant_name'].strip(),
            complainant_phone=request.form['complainant_phone'].strip(),
            nature_of_offence=request.form['nature_of_offence'].strip(),
            details=request.form['details'].strip(),
            recorded_by=session.get('service_number', 'NPS-DESK')
        )
        db.session.add(new_entry)
        db.session.commit()
        commit_audit(f"New occurrence record compiled successfully into local node data storage arrays: [{ob_serial}]")
        return redirect(url_for('register_ob'))
        
    entries = OccurrenceBook.query.order_by(OccurrenceBook.date_time.desc()).all()
    return render_template('view_ob.html', entries=entries)

@app.route('/ob/view-legacy-bridge')
def view_ob():
    """Handles references to url_for('view_ob') without changing template files"""
    return redirect(url_for('register_ob'))
# -------------------------------------------------------------

@app.route('/ob/receipt/<int:id>')
def print_receipt(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    entry = OccurrenceBook.query.get_or_404(id)
    return render_template('receipt.html', entry=entry)

@app.route('/cases')
def cases():
    if not session.get('logged_in'): return redirect(url_for('login'))
    entries = OccurrenceBook.query.filter(OccurrenceBook.status.in_(['PENDING REVIEW', 'INVESTIGATING'])).all()
    return render_template('cases.html', entries=entries
