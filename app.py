from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import io
import random
import os
import pandas as pd  # Ensure 'pandas' and 'openpyxl' are in requirements.txt

app = Flask(__name__)
app.secret_key = 'nps_dpobcms_secure_cipher_token_2026'  # Production hardened token string

# Configuration Boundaries for Binary Upload Vaults
UPLOAD_FOLDER = 'static/evidence_vault'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'docx', 'xlsx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Strict 16MB file limit constraint

# Ensure upload repository directory paths exist safely inside environment memory bounds
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database Configuration (Bi-compatible SQLite Local / PostgreSQL Production Add-on)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///dpobcms_core.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ==========================================
# DATABASE SCHEMAS (CORE COMPLIANCE STACK)
# ==========================================

class Officer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_number = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False) # Upgraded length to support secure hashing
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # Constable, Inspector, OCS, Admin
    station = db.Column(db.String(100), default='NYERI CENTRAL POLICE STATION')

class OccurrenceBook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ob_number = db.Column(db.String(50), unique=True, nullable=False) # Format matched: OB/2026/000001
    date_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False) # Filing Timestamp
    jurisdiction = db.Column(db.String(150), default='Nyeri Central Police Station', nullable=False) # Station Jurisdiction
    complainant_name = db.Column(db.String(100), nullable=False) # Complainant Legal Name
    complainant_phone = db.Column(db.String(20), nullable=False) # Contact Phone
    nature_of_offence = db.Column(db.String(100), nullable=False) # Crime Category Classification
    details = db.Column(db.Text, nullable=False) # Statement Details
    recorded_by = db.Column(db.String(50), nullable=False)  # Officer Service Number (Reporting Agent Token)
    status = db.Column(db.String(50), default='Pending Review', nullable=False)  # Lifecycle State Phase
    evidence_file = db.Column(db.String(200), nullable=True)  # File paths targeting documents
    suspect_photo = db.Column(db.Text, nullable=True)  # Holds Base64 Captured Camera Data Stream

# ==========================================
# AUTHENTICATION ACCESS CONTROLLERS
# ==========================================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/', methods=['GET'])
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        service_number = request.form.get('service_number').strip().upper()
        password = request.form.get('password')
        
        # Validate credentials against registered personnel nodes
        officer = Officer.query.filter_by(service_number=service_number).first()
        
        if officer and check_password_hash(officer.password, password):
            session['logged_in'] = True
            session['user_id'] = officer.id
            session['service_number'] = officer.service_number
            session['user_name'] = officer.name
            session['user_role'] = officer.role
            session['user_station'] = officer.station
            return redirect(url_for('dashboard'))
        
        flash('Invalid Service Number ID or Command Passcode Cipher.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==========================================
# COMMAND MANAGEMENT OPERATION CONTROLLERS
# ==========================================

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    # Query database counts to compute dynamic matrix parameters for the central layout row
    total_ob = OccurrenceBook.query.count()
    active_cases = OccurrenceBook.query.filter_by(status='Under Investigation').count()
    total_officers = Officer.query.count()
    recent_ob = OccurrenceBook.query.order_by(OccurrenceBook.date_time.desc()).limit(5).all()
    
    return render_template(
        'dashboard.html', 
        total_ob=total_ob, 
        active_cases=active_cases, 
        total_officers=total_officers,
        recent_ob=recent_ob
    )

# --- OCCURRENCE BOOK INTAKE LOGIC ---
@app.route('/ob/register', methods=['GET', 'POST'])
def register_ob():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        # Generate automated standardized Kenyan formatting OB strings dynamically (e.g., OB/2026/000001)
        next_sequence = OccurrenceBook.query.count() + 1
        generated_ob = f"OB/2026/{next_sequence:06d}"
        
        new_entry = OccurrenceBook(
            ob_number=generated_ob,
            complainant_name=request.form.get('complainant_name'),
            complainant_phone=request.form.get('complainant_phone'),
            nature_of_offence=request.form.get('nature_of_offence'),
            details=request.form.get('details'),
            recorded_by=session.get('service_number'),
            jurisdiction=session.get('user_station', 'Nyeri Central Police Station'),
            status='Pending Review' # Align default state step with legal abstract specs
        )
        db.session.add(new_entry)
        db.session.commit() # Immediate persistence flush to protect against hardware system sleep drops
        
        flash(f'Record generated successfully. Reference Token: {generated_ob}', 'success')
        return redirect(url_for('view_ob'))
        
    return render_template('register_ob.html')

@app.route('/ob/view')
def view_ob():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    entries = OccurrenceBook.query.order_by(OccurrenceBook.date_time.desc()).all()
    return render_template('view_ob.html', entries=entries)

# --- LIVE TRANSCRIPT MODIFICATION ROUTE VECTOR ---
@app.route('/ob/update_statement/<int:id>', methods=['POST'])
def update_statement(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    entry = OccurrenceBook.query.get_or_404(id)
    new_statement = request.form.get('updated_details')
    
    if new_statement:
        # Timestamp and append accountability tracks to structural log fields
        timestamp_label = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
        operator_label = session.get('service_number', 'UNKNOWN')
        
        entry.details = new_statement + f"\n\n[AMENDMENT LOGGED BY {operator_label} ON {timestamp_label}]"
        db.session.commit() # Immediate persistence write out to hardware tracking partitions
        flash(f"Data layer synchronized. Statement details for {entry.ob_number} modified successfully.", "success")
    else:
        flash("Statement text body parameters cannot be initialized blank.", "danger")
        
    return redirect(url_for('view_ob'))

# ==========================================
# ADVANCED SUSPECT INTEL DISPATCH REGISTER
# ==========================================

@app.route('/cases')
def cases():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    # Fetch active cases still pending lifecycle closures
    entries = OccurrenceBook.query.filter(OccurrenceBook.status.in_(['Under Investigation', 'Pending Review'])).all()
    return render_template('cases.html', entries=entries)

@app.route('/cases/resolve/<int:id>', methods=['POST'])
def resolve_case(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    entry = OccurrenceBook.query.get_or_404(id)
    resolution_state = request.form.get('resolution_action')
    notes = request.form.get('resolution_notes', '')
    
    # Process specialized case termination routes safely
    if resolution_state == "innocent":
        entry.status = "Closed - Proven Innocent"
        entry.details += f"\n\n[RESOLUTION OVERRIDE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]: Suspect cleared of charges. Notes: {notes}"
    elif resolution_state == "close":
        entry.status = "Closed / Concluded"
        entry.details += f"\n\n[RESOLUTION OVERRIDE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]: Case closed successfully. Notes: {notes}"
    elif resolution_state == "investigate":
        entry.status = "Under Investigation"
        entry.details += f"\n\n[STATUS UPDATE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]: Elevated to active investigation phase. Notes: {notes}"
    elif resolution_state == "remove":
        # Purge suspect parameters out of active runtime logging arrays completely
        db.session.delete(entry)
        db.session.commit() # Immediate physical partition deletion commit
        flash('Case record parameters purged from active tracking framework arrays.', 'success')
        return redirect(url_for('cases'))
        
    db.session.commit() # Hard commit updates to disk track immediately
    flash('Case ledger settlement configuration state updated.', 'success')
    return redirect(url_for('cases'))

@app.route('/cases/upload-evidence/<int:id>', methods=['POST'])
def upload_evidence(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    entry = OccurrenceBook.query.get_or_404(id)
    
    # 1. Process Hardware Workstation Camera Snapshot Stream (Base64 string encoding data capture)
    camera_data = request.form.get('camera_snapshot_data')
    if camera_data and "base64," in camera_data:
        entry.suspect_photo = camera_data
        
    # 2. Process Standard Binary File Attachment Document Upload Matrix Pipeline
    if 'evidence_document' in request.files:
        file = request.files['evidence_document']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(f"OB_{entry.id}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            entry.evidence_file = filepath
            
    db.session.commit() # Hard flush to secure file paths against disk partitions
    flash('Binary evidence files committed into the station database vault.', 'success')
    return redirect(url_for('cases'))

# --- FORCE ROSTER ADMINISTRATIVE MANAGEMENT ---
@app.route('/admin/users', methods=['GET'])
def admin_users():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    officers = Officer.query.all()
    return render_template('officer_management.html', officers=officers)

@app.route('/admin/register-officer', methods=['POST'])
def register_officer():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    service_number = request.form.get('service_number').strip().upper()
    password = request.form.get('password')
    name = request.form.get('name').strip()
    role = request.form.get('role')
    station = request.form.get('station', 'NYERI CENTRAL POLICE STATION').strip().upper()
    
    existing = Officer.query.filter_by(service_number=service_number).first()
    if existing:
        flash('Service Number already provisioned in system schema.', 'danger')
        return redirect(url_for('admin_users'))
        
    # Applied cryptographically secure hashing configuration to save master passwords safely
    hashed_password = generate_password_hash(password)
    new_officer = Officer(service_number=service_number, password=hashed_password, name=name, role=role, station=station)
    db.session.add(new_officer) # Added correct session reference path here
    db.session.commit() # Hard flash synchronization logic
    
    flash('New personnel credentials blocks successfully authorized.', 'success')
    return redirect(url_for('admin_users'))

# ==========================================
# DATA EXTRACTION PIPELINE ENGINE (.XLSX)
# ==========================================

@app.route('/reports', methods=['GET'])
def reports():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('reports.html')

@app.route('/reports/export', methods=['POST'])
def export_report():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    try:
        ob_entries = OccurrenceBook.query.all()
        
        if not ob_entries:
            # Map clean matrix headers directly derived from official data tracking structures
            data = [{
                "OB Unique Code ID": "N/A", 
                "Filing Timestamp": "N/A", 
                "Station Unit Jurisdiction": "N/A", 
                "Complainant Legal Name": "No Records Logged", 
                "National ID Token": "N/A", 
                "Crime Category Classification": "N/A", 
                "Statement Details": "N/A", 
                "Reporting Force Agent Token": "N/A", 
                "Lifecycle State Phase": "N/A"
            }]
        else:
            data = [{
                "OB Unique Code ID": entry.ob_number,
                "Filing Timestamp": entry.date_time.strftime('%Y-%m-%d %H:%M:%S UTC'),
                "Station Unit Jurisdiction": entry.jurisdiction,
                "Complainant Legal Name": entry.complainant_name,
                "National ID Token": entry.complainant_phone, # Reused parameter mapping field cleanly
                "Crime Category Classification": entry.nature_of_offence,
                "Statement Details": entry.details,
                "Reporting Force Agent Token": entry.recorded_by,
                "Lifecycle State Phase": entry.status
            } for entry in ob_entries]
        
        # Compile structured DataFrame matrix arrays in memory bounds
        df = pd.DataFrame(data)
        
        # Stream file directly into memory as binary buffer stream to dodge disk latency bounds
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='NPS_Statistical_Matrix')
        output.seek(0)
        
        return send_file(
            output,
            mimetype="application/
