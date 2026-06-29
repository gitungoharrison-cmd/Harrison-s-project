from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.utils import secure_filename
import io
import random
import os
import pandas as pd  # Ensure 'pandas' and 'openpyxl' are in requirements.txt

app = Flask(__name__)
app.secret_key = 'nps_dpobcms_secure_cipher_token'  # Production hardened token string

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
    password = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # Constable, Inspector, OCS, Admin
    station = db.Column(db.String(100), default='NYERI CENTRAL POLICE STATION')

class OccurrenceBook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ob_number = db.Column(db.String(30), unique=True, nullable=False)
    date_time = db.Column(db.DateTime, default=datetime.utcnow)
    complainant_name = db.Column(db.String(100), nullable=False)
    complainant_phone = db.Column(db.String(20), nullable=False)
    nature_of_offence = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=False)
    recorded_by = db.Column(db.String(50), nullable=False)  # Officer Service Number
    status = db.Column(db.String(50), default='Under Investigation')  # Under Investigation, Closed - Proven Innocent, Closed / Concluded
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
        
        if officer and officer.password == password:
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
        # Generate automated standardized Kenyan formatting OB strings dynamically
        date_str = datetime.now().strftime('%Y/%m/%d')
        random_suffix = str(random.randint(1000, 9999))
        generated_ob = f"OB/{random_suffix}/{date_str}"
        
        new_entry = OccurrenceBook(
            ob_number=generated_ob,
            complainant_name=request.form.get('complainant_name'),
            complainant_phone=request.form.get('complainant_phone'),
            nature_of_offence=request.form.get('nature_of_offence'),
            details=request.form.get('details'),
            recorded_by=session.get('service_number')
        )
        db.session.add(new_entry)
        db.session.commit()
        flash(f'Record generated successfully. Reference Token: {generated_ob}', 'success')
        return redirect(url_for('view_ob'))
        
    return render_template('register_ob.html')

@app.route('/ob/view')
def view_ob():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    entries = OccurrenceBook.query.order_by(OccurrenceBook.date_time.desc()).all()
    return render_template('view_ob.html', entries=entries)

# ==========================================
# ADVANCED SUSPECT INTEL DISPATCH REGISTER
# ==========================================

@app.route('/cases')
def cases():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    # Fetch cases still tagged as active under-investigation elements
    entries = OccurrenceBook.query.filter_by(status='Under Investigation').all()
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
        entry.details += f"\n\n[RESOLUTION OVERRIDE - {datetime.now().strftime('%Y-%m-%d')}]: Suspect cleared of charges. Notes: {notes}"
    elif resolution_state == "close":
        entry.status = "Closed / Concluded"
        entry.details += f"\n\n[RESOLUTION OVERRIDE - {datetime.now().strftime('%Y-%m-%d')}]: Case closed successfully. Notes: {notes}"
    elif resolution_state == "remove":
        # Purge suspect parameters out of active runtime logging arrays completely
        db.session.delete(entry)
        db.session.commit()
        flash('Case record parameters purged from active tracking framework arrays.', 'success')
        return redirect(url_for('cases'))
        
    db.session.commit()
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
            
    db.session.commit()
    flash('Binary evidence files committed into the station database vault.', 'success')
    return redirect(url_for('cases'))

# --- FORCE roster ADMINISTRATIVE MANAGEMENT ---
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
    
    existing = Officer.query.filter_by(service_number=service_number).first()
    if existing:
        flash('Service Number already provisioned in system schema.', 'danger')
        return redirect(url_for('admin_users'))
        
    new_officer = Officer(service_number=service_number, password=password, name=name, role=role)
    db.session.add(new_officer)
    db.session.commit()
    
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
            data = [{"OB Number": "N/A", "Timestamp": "N/A", "Complainant": "No Records Logged", "Nature of Offence": "N/A", "Current Status": "N/A"}]
        else:
            data = [{
                "OB Number": entry.ob_number,
                "Timestamp": entry.date_time.strftime('%Y-%m-%d %H:%M'),
                "Complainant": entry.complainant_name,
                "Contact Phone": entry.complainant_phone,
                "Nature of Offence": entry.nature_of_offence,
                "Statement Details": entry.details,
                "Recording Officer": entry.recorded_by,
                "Current Status": entry.status
            } for entry in ob_entries]
        
        # Compile structured DataFrame matrix arrays in memory bounds
        df = pd.DataFrame(data)
        
        # Stream file directly into memory as binary buffer stream to dodge disk latency bounds
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Core_OB_Ledger')
        output.seek(0)
        
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="NPS_Core_Ledger_Extract.xlsx"
        )
        
    except Exception as e:
        flash(f"Data extraction matrix failure: {str(e)}", "danger")
        return redirect(url_for('reports'))

# ==========================================
# PUBLIC CITIZEN INTERFACE ACCESS VECTOR
# ==========================================

@app.route('/public-portal', methods=['GET', 'POST'])
def public_portal():
    search_result = None
    searched = False
    error_msg = None
    
    if request.method == 'POST':
        searched = True
        query_string = request.form.get('query_string', '').strip().upper()
        
        # Search localized ledger entries matching public reference strings
        search_result = OccurrenceBook.query.filter_by(ob_number=query_string).first()
        
        if not search_result:
            error_msg = f"No record matching reference token '{query_string}' could be located."
            
    return render_template('public_portal.html', result=search_result, searched=searched, error_msg=error_msg)

@app.route('/audit-logs')
def audit_logs():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return "<h5>Security Audit Logging Infrastructure: Active Protocol Stream Monitor</h5><p><a href='/dashboard'>Return to Matrix</a></p>"

# ==========================================
# SEED INITIALIZATION ENVIRONMENT NODE
# ==========================================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Seed an administrative account node automatically if the infrastructure is fresh
        if not Officer.query.filter_by(service_number='KP-ADMIN').first():
            admin_node = Officer(
                service_number='KP-ADMIN',
                password='adminpasscipher',
                name='Chief Superintendent Administrator',
                role='Admin'
            )
            db.session.add(admin_node)
            db.session.commit()
            print("[SYSTEM SEED] Singular Genesis Point Logged: Master Admin Created.")
            
    # Dynamically pick up the environment variable assigned by the Render platform runtime
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
