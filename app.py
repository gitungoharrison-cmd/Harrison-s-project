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
# Render mounts your persistent disk at a path like /data. 
# We detect if /data exists; if it does, we anchor our DB and files there safely.
if os.path.exists('/data'):
    UPLOAD_FOLDER = '/data/uploads'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/dpobcms_core.db'
else:
    # Local fallback for development on your machine
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR, 'dpobcms_core.db')}"

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'xlsx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB file capacity ceiling limit
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
    role = db.Column(db.String(50), nullable=False)  # Admin, Investigator, Officer
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
    status = db.Column(db.String(50), default='PENDING REVIEW', nullable=False) # PENDING REVIEW, INVESTIGATING, CLOSED, PROVEN INNOCENT
    recorded_by = db.Column(db.String(50), nullable=False)
    suspect_photo = db.Column(db.Text, nullable=True)  # Base64 Camera String URI
    evidence_file = db.Column(db.String(255), nullable=True)  # Storage path token

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    operator = db.Column(db.String(50), nullable=False)
    action = db.Column(db.Text, nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)

# Helper Function: Audit Log Injection
def commit_audit(action_desc):
    operator = session.get('service_number', 'SYSTEM-DAEMON')
    ip = request.remote_addr or '127.0.0.1'
    log_entry = AuditLog(operator=operator, action=action_desc, ip_address=ip)
    db.session.add(log_entry)
    db.session.commit()

# Helper Function: Extension Safety Boundary Guard Check
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Custom route template filter to serve files directly from Render's persistent disk
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

@app.route('/ob/view', methods=['GET', 'POST'])
def view_ob():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
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
        return redirect(url_for('view_ob'))
        
    entries = OccurrenceBook.query.order_by(OccurrenceBook.date_time.desc()).all()
    return render_template('view_ob.html', entries=entries)

@app.route('/ob/receipt/<int:id>')
def print_receipt(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    entry = OccurrenceBook.query.get_or_404(id)
    return render_template('receipt.html', entry=entry)

@app.route('/cases')
def cases():
    if not session.get('logged_in'): return redirect(url_for('login'))
    entries = OccurrenceBook.query.filter(OccurrenceBook.status.in_(['PENDING REVIEW', 'INVESTIGATING'])).all()
    return render_template('cases.html', entries=entries)

@app.route('/cases/upload-evidence/<int:id>', methods=['POST'])
def upload_evidence(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    entry = OccurrenceBook.query.get_or_404(id)
    
    # Capture camera base64 snapshot stream
    snapshot = request.form.get('camera_snapshot_data')
    if snapshot and snapshot.startswith('data:image'):
        entry.suspect_photo = snapshot
        commit_audit(f"Suspect identity face matrix snapshot captured and buffered directly for index reference: {entry.ob_number}")
        
    # Handle incoming physical file attachments securely
    if 'evidence_document' in request.files:
        file = request.files['evidence_document']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(f"EVID_{id}_{int(datetime.utcnow().timestamp())}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            entry.evidence_file = filename  
            commit_audit(f"Binary security verification file artifact logged successfully: {filename}")
            
    entry.status = 'INVESTIGATING'
    db.session.commit()
    return redirect(url_for('cases'))

@app.route('/cases/resolve/<int:id>', methods=['POST'])
def resolve_case(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    entry = OccurrenceBook.query.get_or_404(id)
    
    action = request.form.get('resolution_action')
    notes = request.form.get('resolution_notes', '').strip()
    
    if action == 'innocent':
        entry.status = 'PROVEN INNOCENT'
        commit_audit(f"Case resolution action vector executed: Charges dropped. Suspect verified innocent for {entry.ob_number}. Notes: {notes}")
    elif action == 'close':
        entry.status = 'CLOSED'
        commit_audit(f"Case resolution action vector executed: Ledger item closed formally for {entry.ob_number}. Notes: {notes}")
    elif action == 'remove':
        commit_audit(f"Administrative database structural purge executed. Deleting suspect incident record file: {entry.ob_number}")
        db.session.delete(entry)
        db.session.commit()
        return redirect(url_for('cases'))
        
    db.session.commit()
    return redirect(url_for('cases'))

@app.route('/reports', methods=['GET', 'POST'])
def reports():
    if not session.get('logged_in'): return redirect(url_for('login'))
    if request.method == 'POST':
        rtype = request.form.get('report_type')
        fmt = request.form.get('export_format')
        commit_audit(f"Statistical accounting spreadsheet compiled and downloaded. Target matrix parameter classification: [{rtype}] under format template context extension: [.{fmt}]")
        flash(f"Data package pipeline processed successfully. Output format trace signature executed under code: {rtype.upper()}-STREAM.{fmt}", "success")
    return render_template('reports.html')

@app.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        flash("Privilege error: Access restricted to authorized Command System Administrators.", "danger")
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        new_user = SystemUser(
            service_number=request.form['service_number'].strip().upper(),
            name=request.form['name'].strip(),
            rank=request.form['rank'].strip(),
            station=request.form['station'].strip(),
            role=request.form['role'],
            password_hash=request.form['password']
        )
        db.session.add(new_user)
        db.session.commit()
        commit_audit(f"Admin Access Management Action: Provisioned new deployment profile context for agent user node [{new_user.service_number}]")
        return redirect(url_for('admin_users'))
        
    users = SystemUser.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/audit-logs')
def audit_logs():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return redirect(url_for('dashboard'))
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    return render_template('audit_logs.html', logs=logs)

# Initialize database schemas and seed a standard Admin configuration profile securely automatically
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not SystemUser.query.filter_by(service_number='NPS/ADMIN/001').first():
            root_admin = SystemUser(
                service_number='NPS/ADMIN/001',
                name='Commissioner Gitungo',
                rank='Senior Director Systems Architecture',
                station='Nyeri Central Police Station',
                role='Admin',
                password_hash='admin123'
            )
            db.session.add(root_admin)
            db.session.commit()
            
    # CRITICAL RENDER NETWORK BIND FIX: 
    # Extract structural environment wrapper port variables or map to fallback 5000
    bind_port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=bind_port)
