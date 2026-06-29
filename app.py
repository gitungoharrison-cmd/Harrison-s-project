import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime

# Initialize Core App Framework
app = Flask(__name__)
app.config['SECRET_KEY'] = 'NPS_SECURE_JWT_SIGNING_KEY_2026_TRACK_SYSTEM'

# Fix the Render PostgreSQL URL prefix dialect issue dynamically
raw_db_url = os.environ.get('DATABASE_URL', 'sqlite:///dpobcms.db')
if raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = raw_db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB Max Upload Size

db = SQLAlchemy(app)

# Ensure upload directory exists securely
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# -------------------------------------------------------------------------
# DATABASE MODELS (SCHEMA ARCHITECTURE)
# -------------------------------------------------------------------------

class User(db.Model):
    id = db.id = db.Column(db.Integer, primary_key=True)
    service_number = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    rank = db.Column(db.String(50), nullable=False)
    station = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='Officer', nullable=False) # Admin, Investigator, Officer
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class OccurrenceBook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ob_number = db.Column(db.String(30), unique=True, nullable=False)
    date_time = db.Column(db.DateTime, default=datetime.utcnow)
    complainant_name = db.Column(db.String(100), nullable=False)
    complainant_phone = db.Column(db.String(20), nullable=False)
    nature_of_offence = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default='Pending Investigation') # Pending, Active, Closed
    recorded_by = db.Column(db.String(50), nullable=False) # Service Number

class CaseFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_number = db.Column(db.String(30), unique=True, nullable=False)
    ob_number = db.Column(db.String(30), db.ForeignKey('occurrence_book.ob_number'), nullable=False)
    investigator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    suspect_name = db.Column(db.String(100), nullable=True)
    suspect_id_passport = db.Column(db.String(50), nullable=True)
    case_status = db.Column(db.String(30), default='Under Investigation') # Under Investigation, Forwarded to ODPP, Court Stage, Concluded
    diary_entries = db.relationship('CaseDiary', backref='case_file', lazy=True)
    evidence_files = db.relationship('Evidence', backref='case_file', lazy=True)

class CaseDiary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case_file.id'), nullable=False)
    entry_date = db.Column(db.DateTime, default=datetime.utcnow)
    activity_details = db.Column(db.Text, nullable=False)
    recorded_by = db.Column(db.String(50), nullable=False)

class Evidence(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case_file.id'), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

# -------------------------------------------------------------------------
# INITIAL DATA SEEDING (SQUARE ONE SEED ENGINE)
# -------------------------------------------------------------------------
def seed_system_architecture_matrices():
    db.create_all()
    # Check if Master Admin profile exists
    admin = User.query.filter_by(service_number='NPS/ADMIN/2026').first()
    if not admin:
        hashed_pwd = generate_password_hash('AdminMaster2026!')
        master_admin = User(
            service_number='NPS/ADMIN/2026',
            name='National Police Service Administrator',
            rank='Commissioner',
            station='NPS Headquarters',
            password_hash=hashed_pwd,
            role='Admin'
        )
        db.session.add(master_admin)
        db.session.commit()
        print("[SYSTEM SEED] Singular Genesis Point Logged: Master Admin Created.")

# -------------------------------------------------------------------------
# WEB APP INTERFACE ROUTING ENGINE
# -------------------------------------------------------------------------

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    service_num = request.form.get('service_number').strip()
    password = request.form.get('password')
    
    user = User.query.filter_by(service_number=service_num).first()
    if user and check_password_hash(user.password_hash, password):
        session['user_id'] = user.id
        session['user_name'] = user.name
        session['user_role'] = user.role
        session['user_station'] = user.station
        session['service_number'] = user.service_number
        flash('Authentication verified successfully.', 'success')
        return redirect(url_for('dashboard'))
    
    flash('Invalid Service Number or Secure Access Key Password.', 'danger')
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Session securely terminated.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    # Core system counter matrix calculations
    total_ob = OccurrenceBook.query.count()
    active_cases = CaseFile.query.filter(CaseFile.case_status != 'Concluded').count()
    total_officers = User.query.filter(User.role != 'Admin').count()
    
    recent_ob = OccurrenceBook.query.order_by(OccurrenceBook.date_time.desc()).limit(5).all()
    return render_template('dashboard.html', total_ob=total_ob, active_cases=active_cases, total_officers=total_officers, recent_ob=recent_ob)

@app.route('/ob/register', methods=['GET', 'POST'])
def register_ob():
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        complainant = request.form.get('complainant_name')
        phone = request.form.get('complainant_phone')
        offence = request.form.get('nature_of_offence')
        details = request.form.get('details')
        
        # Generation design rule for KRA/NPS standard OB strings
        timestamp_str = datetime.now().strftime("%Y%m%d/%H%M")
        random_suffix = str(os.getpid() % 100).zfill(2)
        generated_ob_num = f"NPS/OB/{timestamp_str}/{random_suffix}"
        
        new_entry = OccurrenceBook(
            ob_number=generated_ob_num,
            complainant_name=complainant,
            complainant_phone=phone,
            nature_of_offence=offence,
            details=details,
            recorded_by=session['service_number']
        )
        db.session.add(new_entry)
        db.session.commit()
        flash(f'Occurrence Entry successfully logged as {generated_ob_num}', 'success')
        return redirect(url_for('dashboard'))
        
    return render_template('register_ob.html')

@app.route('/ob/view')
def view_ob():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    all_entries = OccurrenceBook.query.order_by(OccurrenceBook.date_time.desc()).all()
    return render_template('view_ob.html', entries=all_entries)

@app.route('/cases')
def manage_cases():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    all_cases = CaseFile.query.all()
    investigators = User.query.filter(User.role.in_(['Investigator', 'Admin'])).all()
    return render_template('cases.html', cases=all_cases, investigators=investigators)

@app.route('/cases/create/<ob_number>', methods=['POST'])
def generate_case(ob_number):
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    existing_case = CaseFile.query.filter_by(ob_number=ob_number).first()
    if existing_case:
        flash('A structural case file registry already exists for this OB number.', 'warning')
        return redirect(url_for('manage_cases'))
        
    case_id_string = f"CRIM/CASE/{datetime.now().strftime('%Y')}/{str(os.getpid() % 1000).zfill(3)}"
    
    new_case = CaseFile(
        case_number=case_id_string,
        ob_number=ob_number
    )
    
    ob_entry = OccurrenceBook.query.filter_by(ob_number=ob_number).first()
    if ob_entry:
        ob_entry.status = 'Case Investigation Initiated'
        
    db.session.add(new_case)
    db.session.commit()
    flash(f'Case File Matrix initiated: {case_id_string}', 'success')
    return redirect(url_for('manage_cases'))

@app.route('/cases/assign/<int:case_id>', methods=['POST'])
def assign_investigator(case_id):
    if session.get('user_role') not in ['Admin', 'Investigator']:
        flash('Access Denied: Insufficient authorization clearing vectors.', 'danger')
        return redirect(url_for('dashboard'))
        
    inv_id = request.form.get('investigator_id')
    case = CaseFile.query.get_or_404(case_id)
    case.investigator_id = inv_id
    db.session.commit()
    flash('Investigator structural resource successfully bound to case ledger.', 'success')
    return redirect(url_for('manage_cases'))

@app.route('/cases/update/<int:case_id>', methods=['POST'])
def update_case_meta(case_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    case = CaseFile.query.get_or_404(case_id)
    case.suspect_name = request.form.get('suspect_name')
    case.suspect_id_passport = request.form.get('suspect_id')
    case.case_status = request.form.get('status')
    db.session.commit()
    flash('Case suspect profile metrics compiled successfully.', 'success')
    return redirect(url_for('manage_cases'))

@app.route('/cases/diary/<int:case_id>', methods=['POST'])
def add_diary_log(case_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    details = request.form.get('activity_details')
    new_log = CaseDiary(
        case_id=case_id,
        activity_details=details,
        recorded_by=session['service_number']
    )
    db.session.add(new_log)
    db.session.commit()
    flash('Investigation milestone compiled into Case Diary timeline.', 'success')
    return redirect(url_for('manage_cases'))

@app.route('/cases/evidence/upload/<int:case_id>', methods=['POST'])
def upload_evidence(case_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    if 'evidence_file' not in request.files:
        flash('No file partition present inside upload package metadata.', 'danger')
        return redirect(url_for('manage_cases'))
        
    file = request.files['evidence_file']
    description = request.form.get('description')
    
    if file.filename == '':
        flash('Target file cannot possess zero-length string descriptor.', 'danger')
        return redirect(url_for('manage_cases'))
        
    if file:
        safe_filename = secure_filename(f"{case_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        file_save_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
        file.save(file_save_path)
        
        new_evidence = Evidence(
            case_id=case_id,
            description=description,
            filename=safe_filename,
            mime_type=file.content_type or 'application/octet-stream'
        )
        db.session.add(new_evidence)
        db.session.commit()
        flash('Binary file entity structured and archived inside Evidence vault securely.', 'success')
        
    return redirect(url_for('manage_cases'))

@app.route('/admin/users', methods=['GET', 'POST'])
def manage_users():
    if session.get('user_role') != 'Admin':
        flash('Critical Access Violation Refusal.', 'danger')
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        service_num = request.form.get('service_number').strip()
        name = request.form.get('name')
        rank = request.form.get('rank')
        station = request.form.get('station')
        role = request.form.get('role')
        password = request.form.get('password')
        
        existing = User.query.filter_by(service_number=service_num).first()
        if existing:
            flash('Target personnel node record key collision: Service Number already active.', 'warning')
        else:
            hashed_pwd = generate_password_hash(password)
            new_user = User(
                service_number=service_num,
                name=name,
                rank=rank,
                station=station,
                role=role,
                password_hash=hashed_pwd
            )
            db.session.add(new_user)
            db.session.commit()
            flash('Personnel authentication identity node registry compiled securely.', 'success')
            
    all_users = User.query.filter(User.service_number != 'NPS/ADMIN/2026').all()
    return render_template('admin_users.html', users=all_users)

# -------------------------------------------------------------------------
# EXECUTION LIFECYCLE CONTROLLER
# -------------------------------------------------------------------------
if __name__ == '__main__':
    with app.app_context():
        seed_system_architecture_matrices()
    # Read Render's assigned port dynamically, or fallback to 5000 locally
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)