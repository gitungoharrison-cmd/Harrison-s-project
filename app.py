import os
import io
import datetime
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, flash, abort, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SelectField, TextAreaField, SubmitField, DateField
from wtforms.validators import DataRequired, Email, Length, ValidationError, EqualTo
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Report Generation Imports
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import qrcode
import openpyxl

# Initialize Core App Framework
app = Flask(__name__)
app.config['SECRET_KEY'] = 'NPS_SECURE_JWT_SIGNING_KEY_2026_TRACK_SYSTEM'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///dpobcms.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB Max Upload Size

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# ==========================================
# DATABASE MODELS & RELATIONSHIPS
# ==========================================

class Station(db.Model):
    __tablename__ = 'stations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(10), unique=True, nullable=False)
    users = db.relationship('User', backref='station', lazy=True)
    ob_entries = db.relationship('OBEntry', backref='station', lazy=True)

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    service_number = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # Administrator, OCS, Desk Officer, Investigator
    full_name = db.Column(db.String(100), nullable=False)
    rank = db.Column(db.String(50), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id'), nullable=False)
    
    audit_logs = db.relationship('AuditLog', backref='user', lazy=True)
    assigned_cases = db.relationship('Investigation', backref='investigator', lazy=True)

class Suspect(db.Model):
    __tablename__ = 'suspects'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    national_id = db.Column(db.String(50), unique=True, nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(10), nullable=False)
    address = db.Column(db.Text, nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    arrest_history = db.Column(db.Text, nullable=True)

# Many-to-Many Linking Table for Suspects and OB Entries
suspect_case_link = db.Table('suspect_case_link',
    db.Column('suspect_id', db.Integer, db.ForeignKey('suspects.id'), primary_key=True),
    db.Column('ob_entry_id', db.Integer, db.ForeignKey('ob_entries.id'), primary_key=True)
)

class OBEntry(db.Model):
    __tablename__ = 'ob_entries'
    id = db.Column(db.Integer, primary_key=True)
    ob_number = db.Column(db.String(50), unique=True, nullable=False)
    date_created = db.Column(db.Date, default=datetime.date.today, nullable=False)
    time_created = db.Column(db.Time, default=lambda: datetime.datetime.now().time(), nullable=False)
    complainant_name = db.Column(db.String(100), nullable=False)
    national_id = db.Column(db.String(50), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    address = db.Column(db.Text, nullable=False)
    incident_location = db.Column(db.String(255), nullable=False)
    crime_category = db.Column(db.String(100), nullable=False)
    narrative_statement = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Pending Review', nullable=False)
    reporting_officer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id'), nullable=False)
    
    reporting_officer = db.relationship('User', foreign_keys=[reporting_officer_id])
    investigation = db.relationship('Investigation', backref='ob_entry', uselist=False, cascade="all, delete-orphan")
    evidence_files = db.relationship('Evidence', backref='ob_entry', lazy=True, cascade="all, delete-orphan")
    suspects = db.relationship('Suspect', secondary=suspect_case_link, backref=db.backref('ob_entries', lazy='dynamic'))

class Investigation(db.Model):
    __tablename__ = 'investigations'
    id = db.Column(db.Integer, primary_key=True)
    ob_entry_id = db.Column(db.Integer, db.ForeignKey('ob_entries.id'), unique=True, nullable=False)
    investigator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    date_assigned = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    witness_statements = db.Column(db.Text, nullable=True)
    arrest_records = db.Column(db.Text, nullable=True)
    notes = db.relationship('InvestigationNote', backref='investigation', lazy=True, cascade="all, delete-orphan")

class InvestigationNote(db.Model):
    __tablename__ = 'investigation_notes'
    id = db.Column(db.Integer, primary_key=True)
    investigation_id = db.Column(db.Integer, db.ForeignKey('investigations.id'), nullable=False)
    note_text = db.Column(db.Text, nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    created_by = db.Column(db.String(100), nullable=False)

class Evidence(db.Model):
    __tablename__ = 'evidence'
    id = db.Column(db.Integer, primary_key=True)
    ob_entry_id = db.Column(db.Integer, db.ForeignKey('ob_entries.id'), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    uploaded_by = db.Column(db.String(100), nullable=False)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    u = db.session.get(User, int(user_id))
    if u and u.is_active:
        return u
    return None

def log_audit(action, user_id=None):
    ip = request.remote_addr or '127.0.0.1'
    uid = user_id if user_id else (current_user.id if current_user.is_authenticated else None)
    log = AuditLog(user_id=uid, action=action, ip_address=ip)
    db.session.add(log)
    db.session.commit()

# ==========================================
# AUTHENTICATION AND ROLE GUARDS
# ==========================================

def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('Access denied: Unauthorized operational clearing level.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Scope control checking to isolate multi-station data leakage
def verify_station_clearance(target_station_id):
    if current_user.role != 'Administrator' and current_user.station_id != target_station_id:
        abort(403, description="Cross-Station Context Violation Intercepted.")

# ==========================================
# SECURITY INPUT FORMS (WTFORMS)
# ==========================================

class LoginForm(FlaskForm):
    service_number = StringField('Service Number', validators=[DataRequired(), Length(max=50)])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Authenticate')

class RegistrationForm(FlaskForm):
    service_number = StringField('Service Number', validators=[DataRequired(), Length(max=50)])
    email = StringField('Official Email', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Full Name', validators=[DataRequired(), Length(max=100)])
    rank = SelectField('Rank', choices=[('Constable', 'Constable'), ('Corporal', 'Corporal'), ('Sergeant', 'Sergeant'), ('Inspector', 'Inspector'), ('OCS', 'Officer Commanding Station (OCS)'), ('Commissioner', 'Commissioner')], validators=[DataRequired()])
    role = SelectField('System Role', choices=[('Desk Officer', 'Desk Officer'), ('Investigator', 'Investigator'), ('OCS', 'OCS'), ('Administrator', 'Administrator')], validators=[DataRequired()])
    phone_number = StringField('Phone Number', validators=[DataRequired(), Length(max=20)])
    department = StringField('Department/Division', validators=[DataRequired(), Length(max=100)])
    station_id = SelectField('Assigned Station', coerce=int, validators=[DataRequired()])
    password = PasswordField('Access Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register Personnel Asset')

    def validate_service_number(self, service_number):
        if User.query.filter_by(service_number=service_number.data).first():
            raise ValidationError('Service number already provisioned inside system architecture.')

class OBEntryForm(FlaskForm):
    complainant_name = StringField('Complainant Full Name', validators=[DataRequired()])
    national_id = StringField('National ID / Passport No', validators=[DataRequired()])
    phone_number = StringField('Phone Number', validators=[DataRequired()])
    gender = SelectField('Gender', choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')], validators=[DataRequired()])
    address = TextAreaField('Residential Address', validators=[DataRequired()])
    incident_location = StringField('Exact Incident Location', validators=[DataRequired()])
    crime_category = SelectField('Crime Category', choices=[
        ('Robbery & Theft', 'Robbery & Theft'),
        ('Assault & Violent Crimes', 'Assault & Violent Crimes'),
        ('Financial Fraud & Cybercrime', 'Financial Fraud & Cybercrime'),
        ('Narcotics & Contraband', 'Narcotics & Contraband'),
        ('Domestic & Gender-Based Violence', 'Domestic & Gender-Based Violence'),
        ('Homicide Investigations', 'Homicide Investigations'),
        ('General Misconduct & Traffic', 'General Misconduct & Traffic')
    ], validators=[DataRequired()])
    narrative_statement = TextAreaField('Comprehensive Narrative Statement', validators=[DataRequired()])
    submit = SubmitField('Log Occurrence Entry')

class InvestigationUpdateForm(FlaskForm):
    investigator_id = SelectField('Assign Investigator', coerce=int)
    status = SelectField('Case Status Evolution', choices=[
        ('Pending Review', 'Pending Review'),
        ('Under Investigation', 'Under Investigation'),
        ('Arrest Made', 'Arrest Made'),
        ('Court Process', 'Court Process'),
        ('Closed', 'Closed')
    ])
    witness_statements = TextAreaField('Witness Statement Depositions')
    arrest_records = TextAreaField('Arrest Log Records')
    new_note = TextAreaField('Append Field Investigation Note')
    submit = SubmitField('Commit Operational Intelligence Updates')

class EvidenceUploadForm(FlaskForm):
    evidence_file = FileField('Select Digital Asset File', validators=[
        DataRequired(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'pdf', 'mp4', 'avi', 'doc', 'docx'], 'Authorized Forensic Formats Only')
    ])
    submit = SubmitField('Securely Upload Asset')

class SuspectForm(FlaskForm):
    full_name = StringField('Suspect Full Name', validators=[DataRequired()])
    national_id = StringField('National ID Number')
    date_of_birth = DateField('Date of Birth', format='%Y-%m-%d', validators=[DataRequired()])
    gender = SelectField('Gender', choices=[('Male', 'Male'), ('Female', 'Female')], validators=[DataRequired()])
    address = TextAreaField('Last Known Address')
    phone_number = StringField('Contact Phone Number')
    arrest_history = TextAreaField('Prior Arrest & Booking Architecture Record')
    submit = SubmitField('Catalog Suspect Profile')

# ==========================================
# SYSTEM CORE UTILITY ROUTINES
# ==========================================

def generate_ob_sequence_number(station_id):
    current_year = datetime.date.today().year
    prefix = f"OB/{current_year}/"
    count = OBEntry.query.filter(OBEntry.station_id == station_id, OBEntry.ob_number.like(f"{prefix}%")).count()
    return f"{prefix}{str(count + 1).zfill(6)}"

# ==========================================
# APPARATUS SYSTEM ROUTING ENGINE
# ==========================================

@app.route('/')
def index():
    return render_template_string(BASE_TEMPLATE, content=PUBLIC_PORTAL_VIEW)

@app.route('/public-tracking', methods=['POST'])
def public_tracking():
    ob_no = request.form.get('ob_number', '').strip()
    entry = OBEntry.query.filter_by(ob_number=ob_no).first()
    if not entry:
        return render_template_string(BASE_TEMPLATE, content=f'''
        <div class="max-w-4xl mx-auto my-12 p-8 bg-white rounded-lg shadow-md border-t-4 border-red-600">
            <h2 class="text-2xl font-bold text-gray-900 mb-4">No Record Located</h2>
            <p class="text-gray-600">The requested Occurrence Book Number <strong>{ob_no}</strong> is not indexed in the central registry system.</p>
            <a href="{url_for('index')}" class="mt-6 inline-block bg-navy text-white px-4 py-2 rounded">Return to Portal</a>
        </div>
        ''')
    
    inv_name = "Not Assigned"
    if entry.investigation and entry.investigation.investigator:
        inv_name = f"{entry.investigation.investigator.rank} {entry.investigation.investigator.full_name}"
        
    return render_template_string(BASE_TEMPLATE, content=f'''
    <div class="max-w-4xl mx-auto my-12 p-8 bg-white rounded-lg shadow-md border-t-4 border-gold">
        <div class="flex justify-between items-center border-b pb-4 mb-6">
            <div>
                <h2 class="text-2xl font-bold text-navy">National Police Tracking Node</h2>
                <p class="text-sm text-gray-500">System Reference: {entry.ob_number}</p>
            </div>
            <span class="px-3 py-1 text-sm font-semibold rounded-full bg-blue-100 text-blue-800">{entry.status}</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div>
                <h3 class="text-xs font-bold uppercase text-gray-400 tracking-wider">Station Domain</h3>
                <p class="text-gray-800 font-medium">{entry.station.name}</p>
            </div>
            <div>
                <h3 class="text-xs font-bold uppercase text-gray-400 tracking-wider">Filing Timestamp</h3>
                <p class="text-gray-800 font-medium">{entry.date_created.strftime('%d %B %Y')} - {entry.time_created.strftime('%H:%M')}</p>
            </div>
            <div>
                <h3 class="text-xs font-bold uppercase text-gray-400 tracking-wider">Complainant File Identity</h3>
                <p class="text-gray-800 font-medium">{entry.complainant_name[0]}*** {entry.complainant_name[-1]} (Masked for Security)</p>
            </div>
            <div>
                <h3 class="text-xs font-bold uppercase text-gray-400 tracking-wider">Assigned Operational Detective</h3>
                <p class="text-gray-800 font-medium">{inv_name}</p>
            </div>
        </div>
        <div class="border-t pt-4 flex justify-between">
            <a href="{url_for('index')}" class="bg-gray-200 text-gray-800 px-4 py-2 rounded text-sm font-medium hover:bg-gray-300">Back</a>
            <a href="{url_for('download_abstract_pdf', ob_id=entry.id)}" class="bg-navy text-white px-4 py-2 rounded text-sm font-medium hover:bg-slate-800">Download Verified Abstract PDF</a>
        </div>
    </div>
    ''')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(service_number=form.service_number.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            if not user.is_active:
                flash('This personnel account has been administratively disabled.', 'danger')
                return redirect(url_for('login'))
            login_user(user)
            log_audit("User Authentication Successful")
            flash(f'Authentication verified. Welcome back Officer {user.full_name}.', 'success')
            return redirect(url_for('dashboard'))
        else:
            log_audit(f"Failed Authentication Attempt for Service ID: {form.service_number.data}")
            flash('Invalid Operational Credentials.', 'danger')
    return render_template_string(BASE_TEMPLATE, content=LOGIN_VIEW, form=form)

@app.route('/logout')
@login_required
def logout():
    log_audit("User Disconnected Session")
    logout_user()
    flash('Session securely terminated.', 'success')
    return redirect(url_for('login'))

# ==========================================
# SECURE INTERNAL DASHBOARD SYSTEM
# ==========================================

@app.route('/dashboard')
@login_required
def dashboard():
    station_id = current_user.station_id
    is_admin = current_user.role == 'Administrator'
    
    # Apply global vs localized queries depending on access scope
    def scope_query(model_class):
        if is_admin:
            return model_class.query
        return model_class.query.filter_by(station_id=station_id)

    total_ob = scope_query(OBEntry).count()
    open_cases = scope_query(OBEntry).filter(OBEntry.status.in_(['Pending Review', 'Under Investigation'])).count()
    closed_cases = scope_query(OBEntry).filter_by(status='Closed').count()
    court_cases = scope_query(OBEntry).filter_by(status='Court Process').count()
    arrests = scope_query(OBEntry).filter_by(status='Arrest Made').count()
    
    total_officers = User.query.count() if is_admin else User.query.filter_by(station_id=station_id).count()
    
    if is_admin:
        total_evidence = Evidence.query.count()
    else:
        total_evidence = Evidence.query.join(OBEntry).filter(OBEntry.station_id == station_id).count()

    # Dynamic metrics processing for downstream ChartJS elements
    categories_raw = db.session.query(OBEntry.crime_category, db.func.count(OBEntry.id))
    if not is_admin:
        categories_raw = categories_raw.filter(OBEntry.station_id == station_id)
    categories_data = categories_raw.group_by(OBEntry.crime_category).all()
    
    chart_labels = [c[0] for c in categories_data]
    chart_values = [c[1] for c in categories_data]

    recent_entries = scope_query(OBEntry).order_by(OBEntry.id.desc()).limit(5).all()

    return render_template_string(
        BASE_TEMPLATE, 
        content=DASHBOARD_VIEW, 
        total_ob=total_ob, 
        open_cases=open_cases, 
        closed_cases=closed_cases, 
        court_cases=court_cases, 
        arrests=arrests, 
        total_officers=total_officers, 
        total_evidence=total_evidence,
        chart_labels=chart_labels,
        chart_values=chart_values,
        recent_entries=recent_entries
    )

# ==========================================
# DIGITAL OCCURRENCE BOOK BLUEPRINTS
# ==========================================

@app.route('/ob', methods=['GET', 'POST'])
@login_required
def ob_management():
    form = OBEntryForm()
    is_admin = current_user.role == 'Administrator'
    
    if form.validate_on_submit():
        generated_ob = generate_ob_sequence_number(current_user.station_id)
        new_entry = OBEntry(
            ob_number=generated_ob,
            complainant_name=form.complainant_name.data,
            national_id=form.national_id.data,
            phone_number=form.phone_number.data,
            gender=form.gender.data,
            address=form.address.data,
            incident_location=form.incident_location.data,
            crime_category=form.crime_category.data,
            narrative_statement=form.narrative_statement.data,
            reporting_officer_id=current_user.id,
            station_id=current_user.station_id,
            status='Pending Review'
        )
        db.session.add(new_entry)
        db.session.flush() # Populate entry ID for downstream linkages
        
        # Instantiate base investigation shell attached to this entry
        investigation_shell = Investigation(ob_entry_id=new_entry.id)
        db.session.add(investigation_shell)
        
        db.session.commit()
        log_audit(f"Logged New Digital Occurrence Record: {generated_ob}")
        flash(f"Occurrence Registry Serial {generated_ob} successfully initialized.", "success")
        return redirect(url_for('ob_management'))

    search_query = request.args.get('search', '').strip()
    filter_status = request.args.get('status', '').strip()

    query = OBEntry.query if is_admin else OBEntry.query.filter_by(station_id=current_user.station_id)
    
    if search_query:
        query = query.filter((OBEntry.ob_number.ilike(f"%{search_query}%")) | (OBEntry.complainant_name.ilike(f"%{search_query}%")) | (OBEntry.national_id.ilike(f"%{search_query}%")))
    if filter_status:
        query = query.filter_by(status=filter_status)

    entries = query.order_by(OBEntry.id.desc()).all()
    return render_template_string(BASE_TEMPLATE, content=OB_MANAGEMENT_VIEW, form=form, entries=entries)

@app.route('/ob/<int:entry_id>', methods=['GET'])
@login_required
def ob_detail(entry_id):
    entry = OBEntry.query.get_or_4000_or_abort(entry_id)
    verify_station_clearance(entry.station_id)
    return render_template_string(BASE_TEMPLATE, content=OB_DETAIL_VIEW, entry=entry)

def OBEntry_query_get_or_4000_or_abort(entry_id):
    res = db.session.get(OBEntry, entry_id)
    if not res: abort(404)
    return res
OBEntry.query.get_or_4000_or_abort = OBEntry_query_get_or_4000_or_abort

# ==========================================
# INVESTIGATION OPERATIONS MODULE
# ==========================================

@app.route('/investigations', methods=['GET'])
@login_required
def investigation_list():
    is_admin = current_user.role == 'Administrator'
    query = Investigation.query.join(OBEntry)
    
    if not is_admin:
        query = query.filter(OBEntry.station_id == current_user.station_id)
    
    investigations = query.order_by(OBEntry.id.desc()).all()
    return render_template_string(BASE_TEMPLATE, content=INVESTIGATION_LIST_VIEW, investigations=investigations)

@app.route('/investigations/<int:inv_id>', methods=['GET', 'POST'])
@login_required
def investigation_detail(inv_id):
    inv = db.session.get(Investigation, inv_id)
    if not inv: abort(404)
    verify_station_clearance(inv.ob_entry.station_id)
    
    form = InvestigationUpdateForm()
    
    # Populate personnel assignable lists based on hierarchy access limits
    officers_query = User.query.filter_by(role='Investigator')
    if current_user.role != 'Administrator':
        officers_query = officers_query.filter_by(station_id=current_user.station_id)
    
    officers = officers_query.all()
    form.investigator_id.choices = [(0, 'Unassigned / Pending Allocations')] + [(o.id, f"{o.rank} {o.full_name}") for o in officers]

    if request.method == 'GET':
        form.investigator_id.data = inv.investigator_id if inv.investigator_id else 0
        form.status.data = inv.ob_entry.status
        form.witness_statements.data = inv.witness_statements
        form.arrest_records.data = inv.arrest_records

    if form.validate_on_submit():
        if current_user.role in ['Administrator', 'OCS', 'Investigator']:
            inv_id_val = form.investigator_id.data
            inv.investigator_id = None if inv_id_val == 0 else inv_id_val
            inv.ob_entry.status = form.status.data
            inv.witness_statements = form.witness_statements.data
            inv.arrest_records = form.arrest_records.data
            
            if form.new_note.data.strip():
                note = InvestigationNote(
                    investigation_id=inv.id,
                    note_text=form.new_note.data.strip(),
                    created_by=f"{current_user.rank} {current_user.full_name}"
                )
                db.session.add(note)
            
            db.session.commit()
            log_audit(f"Updated Intelligence File for Case: {inv.ob_entry.ob_number}")
            flash('Operational intelligence dossier modifications saved successfully.', 'success')
            return redirect(url_for('investigation_detail', inv_id=inv.id))
        else:
            flash('Privilege level execution error.', 'danger')

    evidence_form = EvidenceUploadForm()
    return render_template_string(BASE_TEMPLATE, content=INVESTIGATION_DETAIL_VIEW, inv=inv, form=form, evidence_form=evidence_form)

# ==========================================
# FORENSIC EVIDENCE ARTIFACT GALLERY
# ==========================================

@app.route('/investigations/<int:inv_id>/upload-evidence', methods=['POST'])
@login_required
def upload_evidence(inv_id):
    inv = db.session.get(Investigation, inv_id)
    if not inv: abort(404)
    verify_station_clearance(inv.ob_entry.station_id)
    
    form = EvidenceUploadForm()
    if form.validate_on_submit():
        f = form.evidence_file.data
        filename = secure_filename(f.filename)
        unique_prefix = f"{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_"
        stored_filename = unique_prefix + filename
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
        f.save(file_path)
        
        evidence_record = Evidence(
            ob_entry_id=inv.ob_entry_id,
            file_name=filename,
            stored_filename=stored_filename,
            file_type=filename.split('.')[-1].lower(),
            uploaded_by=f"{current_user.rank} {current_user.full_name}"
        )
        db.session.add(evidence_record)
        db.session.commit()
        log_audit(f"Uploaded Forensic File {filename} linked to entry {inv.ob_entry.ob_number}")
        flash('Digital evidence profile integrated successfully.', 'success')
    return redirect(url_for('investigation_detail', inv_id=inv.id))

@app.route('/evidence/download/<int:ev_id>')
@login_required
def download_evidence_file(ev_id):
    ev = db.session.get(Evidence, ev_id)
    if not ev: abort(404)
    verify_station_clearance(ev.ob_entry.station_id)
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], ev.stored_filename), as_attachment=True, download_name=ev.file_name)

# ==========================================
# SUSPECT ARCHIVE CONTROL PORTAL
# ==========================================

@app.route('/suspects', methods=['GET', 'POST'])
@login_required
def suspect_registry():
    form = SuspectForm()
    if form.validate_on_submit():
        new_suspect = Suspect(
            full_name=form.full_name.data,
            national_id=form.national_id.data or None,
            date_of_birth=form.date_of_birth.data,
            gender=form.gender.data,
            address=form.address.data,
            phone_number=form.phone_number.data,
            arrest_history=form.arrest_history.data
        )
        db.session.add(new_suspect)
        db.session.commit()
        log_audit(f"Cataloged New Suspect Profile: {new_suspect.full_name}")
        flash('Suspect dossier registered within central index framework.', 'success')
        return redirect(url_for('suspect_registry'))
        
    suspects = Suspect.query.order_by(Suspect.id.desc()).all()
    return render_template_string(BASE_TEMPLATE, content=SUSPECT_REGISTRY_VIEW, form=form, suspects=suspects)

@app.route('/suspects/link/<int:suspect_id>', methods=['POST'])
@login_required
def link_suspect_to_case(suspect_id):
    suspect = db.session.get(Suspect, suspect_id)
    if not suspect: abort(404)
    ob_no = request.form.get('ob_number_link', '').strip()
    entry = OBEntry.query.filter_by(ob_number=ob_no).first()
    
    if not entry:
        flash(f"Verification Failure: {ob_no} does not map to active structures.", "danger")
    else:
        verify_station_clearance(entry.station_id)
        if entry not in suspect.ob_entries:
            suspect.ob_entries.append(entry)
            db.session.commit()
            log_audit(f"Linked Suspect {suspect.full_name} with case reference {entry.ob_number}")
            flash('Case linkage mapped successfully.', 'success')
        else:
            flash('Identity binding already mapped.', 'warning')
            
    return redirect(url_for('suspect_registry'))

# ==========================================
# RECOGNIZED OFFICERS & ACCOUNT MANAGEMENT
# ==========================================

@app.route('/officers', methods=['GET', 'POST'])
@login_required
@roles_required('Administrator', 'OCS')
def officer_management():
    form = RegistrationForm()
    form.station_id.choices = [(s.id, s.name) for s in Station.query.all()]
    
    if form.validate_on_submit():
        hashed_pwd = generate_password_hash(form.password.data)
        new_user = User(
            service_number=form.service_number.data,
            email=form.email.data,
            password_hash=hashed_pwd,
            role=form.role.data,
            full_name=form.full_name.data,
            rank=form.rank.data,
            phone_number=form.phone_number.data,
            department=form.department.data,
            station_id=form.station_id.data,
            is_active=True
        )
        db.session.add(new_user)
        db.session.commit()
        log_audit(f"Provisioned New Security Account Profile: {new_user.service_number}")
        flash(f'Personnel profile {new_user.service_number} activated inside platform structural matrices.', 'success')
        return redirect(url_for('officer_management'))

    query = User.query
    if current_user.role != 'Administrator':
        query = query.filter_by(station_id=current_user.station_id)
        
    officers = query.all()
    return render_template_string(BASE_TEMPLATE, content=OFFICER_MANAGEMENT_VIEW, form=form, officers=officers)

@app.route('/officers/toggle/<int:user_id>')
@login_required
@roles_required('Administrator', 'OCS')
def toggle_officer_status(user_id):
    user_profile = db.session.get(User, user_id)
    if not user_profile: abort(404)
    if current_user.role != 'Administrator' and current_user.station_id != user_profile.station_id:
        abort(403)
        
    if user_profile.id == current_user.id:
        flash('Self-lockout execution blocked.', 'danger')
        return redirect(url_for('officer_management'))
        
    user_profile.is_active = not user_profile.is_active
    db.session.commit()
    log_audit(f"Toggled Account Execution Flag for Identity: {user_profile.service_number} to State: {user_profile.is_active}")
    flash(f"Security Clearance Lifecycle State Updated.", 'success')
    return redirect(url_for('officer_management'))

# ==========================================
# SYSTEM AUDIT LOG RETRIEVAL 
# ==========================================

@app.route('/audit-logs')
@login_required
@roles_required('Administrator', 'OCS')
def view_audit_logs():
    if current_user.role == 'Administrator':
        logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(250).all()
    else:
        logs = AuditLog.query.join(User).filter(User.station_id == current_user.station_id).order_by(AuditLog.timestamp.desc()).limit(250).all()
    return render_template_string(BASE_TEMPLATE, content=AUDIT_LOGS_VIEW, logs=logs)

# ==========================================
# DEFENSE CRYPTO REPORT GENERATION ENGINES
# ==========================================

@app.route('/reports')
@login_required
def intelligence_reports():
    return render_template_string(BASE_TEMPLATE, content=REPORTS_DASHBOARD_VIEW)

@app.route('/reports/export/<string:report_type>/<string:fmt>')
@login_required
def export_crime_reports(report_type, fmt):
    is_admin = current_user.role == 'Administrator'
    query = OBEntry.query if is_admin else OBEntry.query.filter_by(station_id=current_user.station_id)
    
    # Process relative time matrices
    today = datetime.date.today()
    if report_type == 'daily':
        query = query.filter(OBEntry.date_created == today)
        title = "Daily Occurrence Matrix Report"
    elif report_type == 'weekly':
        start_week = today - datetime.timedelta(days=7)
        query = query.filter(OBEntry.date_created >= start_week)
        title = "Weekly Strategic Crime Analytics"
    elif report_type == 'monthly':
        start_month = today - datetime.timedelta(days=30)
        query = query.filter(OBEntry.date_created >= start_month)
        title = "Monthly Intelligence Briefing"
    else:
        title = "Annual Comprehensive Jurisdictional Report"

    records = query.order_by(OBEntry.id.desc()).all()

    if fmt == 'excel':
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Incident Ledger Matrix"
        ws.append(["OB Number", "Date", "Time", "Complainant ID Name", "Category", "Location", "Resolution Status"])
        
        for r in records:
            ws.append([r.ob_number, str(r.date_created), str(r.time_created), r.complainant_name, r.crime_category, r.incident_location, r.status])
            
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        log_audit(f"Exported Structured Excel Intelligence Matrix: {title}")
        return Response(out.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment;filename={report_type}_report.xlsx"})

    # Fallback to robust ReportLab structural execution engine
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    story = []
    header_style = ParagraphStyle('RepHeader', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0B132B'), spaceAfter=12)
    story.append(Paragraph("NATIONAL POLICE SERVICE DIGITAL INTELLIGENCE LEDGER", header_style))
    story.append(Paragraph(f"Scope Architecture Matrix: {title} | Extracted: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 15))
    
    table_data = [["OB Reference", "Date Ledger", "Incident Categorization", "Locality Space", "Status Vector"]]
    for r in records:
        table_data.append([r.ob_number, str(r.date_created), r.crime_category, r.incident_location, r.status])
        
    t = Table(table_data, colWidths=[100, 70, 150, 120, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0B132B')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#F4F5F7')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#1C2541')),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    story.append(t)
    doc.build(story)
    buffer.seek(0)
    log_audit(f"Exported Cryptographic PDF Intelligence Ledger: {title}")
    return send_file(buffer, as_attachment=True, download_name=f"{report_type}_report.pdf", mimetype='application/pdf')

@app.route('/ob/abstract/<int:ob_id>')
def download_abstract_pdf(ob_id):
    entry = db.session.get(OBEntry, ob_id)
    if not entry: abort(404)
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('AbstractTitle', fontName='Helvetica-Bold', fontSize=18, leading=22, alignment=1, textColor=colors.HexColor('#0B132B'))
    subtitle_style = ParagraphStyle('AbstractSub', fontName='Helvetica', fontSize=10, leading=14, alignment=1, textColor=colors.HexColor('#1C2541'))
    
    story.append(Paragraph("NATIONAL POLICE SERVICE", title_style))
    story.append(Paragraph(f"OFFICIAL POLICE ABSTRACT - {entry.station.name.upper()}", subtitle_style))
    story.append(Spacer(1, 20))
    
    # Render embedded tracking verification QR Engine Matrix
    qr_uri = f"https://nps.go.ke/verify/ob?id={entry.ob_number}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(qr_uri)
    qr.make(fit=True)
    img_qr = qr.make_image(fill_color="black", back_color="white")
    
    qr_buffer = io.BytesIO()
    img_qr.save(qr_buffer, format='PNG')
    qr_buffer.seek(0)
    
    from reportlab.platypus import Image as RLImage
    rl_qr_img = RLImage(qr_buffer, width=90, height=90)
    
    summary_data = [
        [Paragraph("<b>OCCURRENCE BOOK REF:</b>", styles['Normal']), Paragraph(entry.ob_number, styles['Normal']), rl_qr_img],
        [Paragraph("<b>DATE OF FILING:</b>", styles['Normal']), Paragraph(str(entry.date_created), styles['Normal']), ""],
        [Paragraph("<b>COMPLAINANT IDENTITY:</b>", styles['Normal']), Paragraph(entry.complainant_name, styles['Normal']), ""],
        [Paragraph("<b>NATIONAL ID/PASS:</b>", styles['Normal']), Paragraph(entry.national_id, styles['Normal']), ""],
        [Paragraph("<b>CRIME CATEGORY:</b>", styles['Normal']), Paragraph(entry.crime_category, styles['Normal']), ""],
        [Paragraph("<b>GEOGRAPHIC SPACE:</b>", styles['Normal']), Paragraph(entry.incident_location, styles['Normal']), ""],
    ]
    
    summary_table = Table(summary_data, colWidths=[150, 230, 100])
    summary_table.setStyle(TableStyle([
        ('SPAN', (2,0), (2,5)),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 15))
    
    story.append(Paragraph("<b>COMPREHENSIVE CASE STATEMENT INTELLECT:</b>", styles['Normal']))
    story.append(Spacer(1, 5))
    story.append(Paragraph(entry.narrative_statement, styles['BodyText']))
    story.append(Spacer(1, 40))
    
    sig_data = [
        [Paragraph("............................................................<br/><b>RECORDING OFFICER SIGNATURE</b>", styles['Normal']),
         Paragraph("............................................................<br/><b>STAMP / OCS APPROVAL AREA</b>", styles['Normal'])]
    ]
    sig_table = Table(sig_data, colWidths=[260, 260])
    story.append(sig_table)
    
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=False, download_name=f"abstract_{entry.ob_number}.pdf", mimetype='application/pdf')

# ==========================================
# COMPREHENSIVE RESPONSIVE DESIGN TEMPLATES
# ==========================================

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DPOBCMS - National Police Service Node</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        navy: '#0B132B',
                        securityblue: '#1C2541',
                        gold: '#E5A93C',
                        slatewhite: '#F4F5F7'
                    }
                }
            }
        }
    </script>
</head>
<body class="bg-slatewhite font-sans text-gray-900 flex flex-col min-h-screen">

    <header class="bg-navy border-b-4 border-gold text-white px-6 py-4 flex flex-wrap justify-between items-center shadow-lg">
        <div class="flex items-center space-x-3">
            <div class="w-10 h-10 bg-gold rounded-full flex items-center justify-center font-bold text-navy tracking-tighter text-lg">NPS</div>
            <div>
                <h1 class="text-xl font-bold tracking-wide">DIGITAL POLICE OCCURRENCE BOOK</h1>
                <p class="text-xs text-gray-400 font-mono tracking-widest">NATIONAL ENFORCEMENT SYSTEMS NETWORK</p>
            </div>
        </div>
        <nav class="flex space-x-2 mt-4 lg:mt-0">
            {% if current_user.is_authenticated %}
                <a href="{{ url_for('dashboard') }}" class="px-3 py-2 rounded text-sm font-medium hover:bg-securityblue text-gray-200">Dashboard</a>
                <a href="{{ url_for('ob_management') }}" class="px-3 py-2 rounded text-sm font-medium hover:bg-securityblue text-gray-200">Occurrence Ledger</a>
                <a href="{{ url_for('investigation_list') }}" class="px-3 py-2 rounded text-sm font-medium hover:bg-securityblue text-gray-200">Dossiers</a>
                <a href="{{ url_for('suspect_registry') }}" class="px-3 py-2 rounded text-sm font-medium hover:bg-securityblue text-gray-200">Suspects</a>
                {% if current_user.role in ['Administrator', 'OCS'] %}
                    <a href="{{ url_for('officer_management') }}" class="px-3 py-2 rounded text-sm font-medium hover:bg-securityblue text-gray-200">Personnel</a>
                    <a href="{{ url_for('view_audit_logs') }}" class="px-3 py-2 rounded text-sm font-medium hover:bg-securityblue text-gray-200">Audits</a>
                {% endif %}
                <a href="{{ url_for('intelligence_reports') }}" class="px-3 py-2 rounded text-sm font-medium hover:bg-securityblue text-gray-200">Reports</a>
                <a href="{{ url_for('logout') }}" class="bg-red-700 px-3 py-2 rounded text-sm font-medium hover:bg-red-800 text-white">Disconnect</a>
            {% else %}
                <a href="{{ url_for('index') }}" class="px-3 py-2 rounded text-sm font-medium hover:bg-securityblue text-gray-200">Public Portal</a>
                <a href="{{ url_for('login') }}" class="bg-gold px-4 py-2 rounded text-sm font-bold text-navy hover:bg-yellow-600">Personnel Login</a>
            {% endif %}
        </nav>
    </header>

    <main class="flex-grow p-6">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="mb-6 p-4 rounded-lg font-medium border text-sm {% if category == 'danger' %} bg-red-100 border-red-400 text-red-800 {% else %} bg-green-100 border-green-400 text-green-800 {% endif %}">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {{ content | safe }}
    </main>

    <footer class="bg-navy text-gray-400 text-center py-4 text-xs border-t border-gray-800 font-mono">
        SECURE GOVERNMENT ARCHITECTURE SYSTEM // DIGITAL REGISTRY SYNC CONNECTED // YEAR 2026 CLASSIFIED INFORMATION
    </footer>

</body>
</html>
'''

PUBLIC_PORTAL_VIEW = '''
<div class="max-w-4xl mx-auto my-12 text-center">
    <h2 class="text-4xl font-extrabold text-navy tracking-tight mb-4">National Citizen Case Tracking Portal</h2>
    <p class="text-gray-600 mb-8 max-w-xl mx-auto">Verify incident classification records, view progress reports dynamically, and access authenticated Police Abstracts using structural OB sequence tokens.</p>
    
    <div class="bg-white p-8 rounded-xl shadow-xl border border-gray-200 max-w-md mx-auto text-left">
        <form action="/public-tracking" methods="POST" method="POST">
            <div class="mb-5">
                <label class="block text-sm font-bold text-gray-700 uppercase tracking-wider mb-2">Occurrence Book (OB) Reference Number</label>
                <input type="text" name="ob_number" placeholder="e.g., OB/2026/000001" class="w-full px-4 py-3 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-navy font-mono" required>
            </div>
            <button type="submit" class="w-full bg-navy text-white font-bold py-3 rounded-lg uppercase tracking-widest hover:bg-securityblue transition-colors">Query Registry Ledger</button>
        </form>
    </div>
</div>
'''

LOGIN_VIEW = '''
<div class="max-w-md mx-auto my-16 bg-white rounded-xl shadow-2xl border border-gray-200 overflow-hidden">
    <div class="bg-navy p-6 text-center border-b-4 border-gold">
        <h2 class="text-xl font-bold text-white uppercase tracking-widest">Enforcement Authentication</h2>
        <p class="text-xs text-gray-400 mt-1">Authorized Agency Personnel Interlock Gateway</p>
    </div>
    <form method="POST" class="p-6 space-y-4">
        {{ form.hidden_tag() }}
        <div>
            <label class="block text-xs font-bold uppercase tracking-wider text-gray-600 mb-1">Service Number</label>
            {{ form.service_number(class="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-navy") }}
        </div>
        <div>
            <label class="block text-xs font-bold uppercase tracking-wider text-gray-600 mb-1">Access Password</label>
            {{ form.password(class="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-navy") }}
        </div>
        <div class="pt-2">
            {{ form.submit(class="w-full bg-navy text-white font-bold py-2 rounded uppercase tracking-wider hover:bg-securityblue cursor-pointer") }}
        </div>
    </form>
</div>
'''

DASHBOARD_VIEW = '''
<div class="space-y-6">
    <div class="flex justify-between items-center border-b pb-4">
        <div>
            <h2 class="text-2xl font-black text-navy uppercase tracking-tight">Command Control Dashboard</h2>
            <p class="text-sm text-gray-500 font-medium">Station Context Domain: <span class="text-gold font-bold">{{ current_user.station.name }}</span></p>
        </div>
        <span class="bg-navy text-white px-3 py-1 text-xs font-bold font-mono tracking-widest rounded">ROLE: {{ current_user.role.upper() }}</span>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
        <div class="bg-white p-4 rounded-xl shadow border-l-4 border-navy"><p class="text-xs font-bold text-gray-400 uppercase">Total OB</p><p class="text-2xl font-bold text-navy">{{ total_ob }}</p></div>
        <div class="bg-white p-4 rounded-xl shadow border-l-4 border-yellow-500"><p class="text-xs font-bold text-gray-400 uppercase">Open Cases</p><p class="text-2xl font-bold text-yellow-600">{{ open_cases }}</p></div>
        <div class="bg-white p-4 rounded-xl shadow border-l-4 border-green-600"><p class="text-xs font-bold text-gray-400 uppercase">Closed Matrix</p><p class="text-2xl font-bold text-green-600">{{ closed_cases }}</p></div>
        <div class="bg-white p-4 rounded-xl shadow border-l-4 border-blue-600"><p class="text-xs font-bold text-gray-400 uppercase">Court Bound</p><p class="text-2xl font-bold text-blue-600">{{ court_cases }}</p></div>
        <div class="bg-white p-4 rounded-xl shadow border-l-4 border-red-600"><p class="text-xs font-bold text-gray-400 uppercase">Arrests</p><p class="text-2xl font-bold text-red-600">{{ arrests }}</p></div>
        <div class="bg-white p-4 rounded-xl shadow border-l-4 border-purple-600"><p class="text-xs font-bold text-gray-400 uppercase">Personnel</p><p class="text-2xl font-bold text-purple-600">{{ total_officers }}</p></div>
        <div class="bg-white p-4 rounded-xl shadow border-l-4 border-gold"><p class="text-xs font-bold text-gray-400 uppercase">Evidence Files</p><p class="text-2xl font-bold text-gold">{{ total_evidence }}</p></div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="bg-white p-6 rounded-xl shadow">
            <h3 class="text-sm font-bold text-gray-700 uppercase tracking-wider mb-4">Crime Distribution Metrics</h3>
            <div class="max-h-64 flex justify-center"><canvas id="categoryChart"></canvas></div>
        </div>
        <div class="bg-white p-6 rounded-xl shadow">
            <h3 class="text-sm font-bold text-gray-700 uppercase tracking-wider mb-4">Recent Station Incident Stream</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse text-xs">
                    <thead>
                        <tr class="bg-gray-100 text-gray-600 font-bold uppercase tracking-wider border-b">
                            <th class="p-2">OB Reference</th>
                            <th class="p-2">Category</th>
                            <th class="p-2">Complainant</th>
                            <th class="p-2">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for r in recent_entries %}
                        <tr class="border-b hover:bg-gray-50">
                            <td class="p-2 font-mono font-bold text-navy"><a href="/ob/{{r.id}}" class="underline">{{ r.ob_number }}</a></td>
                            <td class="p-2">{{ r.crime_category }}</td>
                            <td class="p-2">{{ r.complainant_name }}</td>
                            <td class="p-2"><span class="px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 font-medium">{{ r.status }}</span></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>

<script>
    const ctxCategory = document.getElementById('categoryChart').getContext('2d');
    new Chart(ctxCategory, {
        type: 'pie',
        data: {
            labels: {{ chart_labels | tojson }},
            datasets: [{
                data: {{ chart_values | tojson }},
                backgroundColor: ['#0B132B', '#1C2541', '#E5A93C', '#4A5568', '#A0AEC0', '#3182CE', '#E53E3E']
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });
</script>
'''

OB_MANAGEMENT_VIEW = '''
<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="bg-white p-6 rounded-xl shadow border-t-4 border-navy">
        <h3 class="text-lg font-black text-navy uppercase tracking-tight mb-4">Log New Incident Manifest</h3>
        <form method="POST" class="space-y-3 text-sm">
            {{ form.hidden_tag() }}
            <div><label class="block font-semibold text-gray-700 mb-1">Complainant Full Name</label>{{ form.complainant_name(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            <div class="grid grid-cols-2 gap-2">
                <div><label class="block font-semibold text-gray-700 mb-1">National ID / Passport</label>{{ form.national_id(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
                <div><label class="block font-semibold text-gray-700 mb-1">Contact Phone</label>{{ form.phone_number(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            </div>
            <div><label class="block font-semibold text-gray-700 mb-1">Gender Variant</label>{{ form.gender(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            <div><label class="block font-semibold text-gray-700 mb-1">Residential Coordinates / Address</label>{{ form.address(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy", rows=2) }}</div>
            <div><label class="block font-semibold text-gray-700 mb-1">Geographic Scene Location</label>{{ form.incident_location(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            <div><label class="block font-semibold text-gray-700 mb-1">Classification Matrix</label>{{ form.crime_category(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            <div><label class="block font-semibold text-gray-700 mb-1">Comprehensive Evidence Narrative Statement</label>{{ form.narrative_statement(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy", rows=4) }}</div>
            {{ form.submit(class="w-full bg-navy text-white font-bold py-2 rounded uppercase tracking-wider hover:bg-securityblue mt-2 cursor-pointer") }}
        </form>
    </div>

    <div class="lg:col-span-2 bg-white p-6 rounded-xl shadow">
        <div class="flex flex-wrap justify-between items-center mb-4 border-b pb-2">
            <h3 class="text-lg font-black text-navy uppercase tracking-tight">Occurrence Book Continuous Log</h3>
            <form method="GET" class="flex space-x-2 mt-2 sm:mt-0">
                <input type="text" name="search" placeholder="Search Serial / Complainant / ID" class="px-2 py-1 border rounded text-xs focus:ring-1 focus:ring-navy">
                <button type="submit" class="bg-navy text-white text-xs px-3 py-1 rounded">Query</button>
            </form>
        </div>

        <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse text-xs">
                <thead>
                    <tr class="bg-gray-100 border-b font-bold uppercase tracking-wider text-gray-600">
                        <th class="p-3">OB Sequence</th>
                        <th class="p-3">Date/Time Ledger</th>
                        <th class="p-3">Categorization Space</th>
                        <th class="p-3">Complainant File</th>
                        <th class="p-3">System State</th>
                        <th class="p-3 text-right">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for e in entries %}
                    <tr class="border-b hover:bg-gray-50 font-medium">
                        <td class="p-3 font-mono font-bold text-navy">{{ e.ob_number }}</td>
                        <td class="p-3 text-gray-500">{{ e.date_created.strftime('%Y-%m-%d') }}<br/>{{ e.time_created.strftime('%H:%M') }}</td>
                        <td class="p-3 text-gray-800">{{ e.crime_category }}</td>
                        <td class="p-3">{{ e.complainant_name }}<br/><span class="text-gray-400">{{ e.national_id }}</span></td>
                        <td class="p-3"><span class="px-2 py-0.5 rounded-full font-bold text-xs bg-gray-200 text-gray-800">{{ e.status }}</span></td>
                        <td class="p-3 text-right space-y-1">
                            <a href="/ob/{{ e.id }}" class="block text-blue-600 hover:underline font-bold">Inspect Profile</a>
                            <a href="/investigations/{{ e.investigation.id }}" class="block text-yellow-600 hover:underline font-bold">Dossier Workspace</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
'''

OB_DETAIL_VIEW = '''
<div class="max-w-5xl mx-auto bg-white rounded-xl shadow-md border-t-4 border-gold p-8 space-y-6">
    <div class="flex justify-between items-center border-b pb-4">
        <div>
            <h2 class="text-2xl font-black text-navy uppercase tracking-tight">Occurrence Record Blueprint</h2>
            <p class="font-mono text-sm text-gray-500 font-bold">Serial Vector: {{ entry.ob_number }}</p>
        </div>
        <a href="/ob/abstract/{{ entry.id }}" target="_blank" class="bg-navy text-white text-xs font-bold uppercase px-4 py-2 rounded tracking-wider hover:bg-securityblue">Print Validated Abstract</a>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
        <div><h4 class="font-bold text-gray-400 uppercase text-xs tracking-widest">Incident Chronology</h4><p class="font-medium mt-1">{{ entry.date_created }} @ {{ entry.time_created }}</p></div>
        <div><h4 class="font-bold text-gray-400 uppercase text-xs tracking-widest">Station Context</h4><p class="font-medium mt-1">{{ entry.station.name }}</p></div>
        <div><h4 class="font-bold text-gray-400 uppercase text-xs tracking-widest">Structural Resolution Status</h4><p class="font-medium mt-1 text-gold font-bold">{{ entry.status }}</p></div>
    </div>

    <div class="border-t pt-4 grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
        <div>
            <h3 class="text-xs font-bold text-navy uppercase tracking-widest border-b pb-1 mb-2">Complainant Core Identification</h3>
            <p class="mb-1"><strong>Name:</strong> {{ entry.complainant_name }}</p>
            <p class="mb-1"><strong>National Token Identity:</strong> {{ entry.national_id }}</p>
            <p class="mb-1"><strong>Communications Array:</strong> {{ entry.phone_number }}</p>
            <p class="mb-1"><strong>Gender Context:</strong> {{ entry.gender }}</p>
            <p><strong>Resident Coordinates:</strong> {{ entry.address }}</p>
        </div>
        <div>
            <h3 class="text-xs font-bold text-navy uppercase tracking-widest border-b pb-1 mb-2">Incident Operational Framework</h3>
            <p class="mb-1"><strong>Categorization Matrix:</strong> {{ entry.crime_category }}</p>
            <p class="mb-1"><strong>Geographic Locus Space:</strong> {{ entry.incident_location }}</p>
            <p><strong>Filing Officer Asset:</strong> {{ entry.reporting_officer.rank }} {{ entry.reporting_officer.full_name }} ({{ entry.reporting_officer.service_number }})</p>
        </div>
    </div>

    <div class="border-t pt-4">
        <h3 class="text-xs font-bold text-navy uppercase tracking-widest mb-2">Official Narrative Deposition Ledger</h3>
        <div class="bg-slatewhite p-4 rounded-lg border font-mono text-xs whitespace-pre-wrap leading-relaxed text-gray-800">{{ entry.narrative_statement }}</div>
    </div>
</div>
'''

INVESTIGATION_LIST_VIEW = '''
<div class="bg-white p-6 rounded-xl shadow">
    <div class="border-b pb-4 mb-4">
        <h2 class="text-2xl font-black text-navy uppercase tracking-tight">Active Operations Investigation Ledger</h2>
        <p class="text-xs text-gray-500">Cross-linking occurrence book evidence parameters dynamically with intelligence investigators.</p>
    </div>
    <div class="overflow-x-auto">
        <table class="w-full text-left border-collapse text-xs">
            <thead>
                <tr class="bg-gray-100 text-gray-600 font-bold uppercase border-b">
                    <th class="p-3">OB Blueprint</th>
                    <th class="p-3">Category Matrix</th>
                    <th class="p-3">Assigned Operative</th>
                    <th class="p-3">Dossier State</th>
                    <th class="p-3">Chronology Allocation</th>
                    <th class="p-3 text-right">Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for i in investigations %}
                <tr class="border-b hover:bg-gray-50 font-medium">
                    <td class="p-3 font-mono font-bold text-navy">{{ i.ob_entry.ob_number }}</td>
                    <td class="p-3">{{ i.ob_entry.crime_category }}</td>
                    <td class="p-3">
                        {% if i.investigator %}
                            <span class="font-bold text-gray-800">{{ i.investigator.rank }} {{ i.investigator.full_name }}</span>
                        {% else %}
                            <span class="text-red-600 font-bold tracking-pulse">PENDING OFFICER ASSIGNMENT</span>
                        {% endif %}
                    </td>
                    <td class="p-3"><span class="px-2 py-0.5 rounded-full bg-blue-100 text-blue-900 font-bold">{{ i.ob_entry.status }}</span></td>
                    <td class="p-3 text-gray-400">{{ i.date_assigned.strftime('%Y-%m-%d %H:%M') }}</td>
                    <td class="p-3 text-right"><a href="/investigations/{{ i.id }}" class="bg-navy text-white font-bold px-3 py-1 rounded text-2xs uppercase tracking-wider hover:bg-securityblue">Access Workspace</a></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
'''

INVESTIGATION_DETAIL_VIEW = '''
<div class="space-y-6">
    <div class="flex justify-between items-center border-b pb-4">
        <div>
            <h2 class="text-2xl font-black text-navy uppercase tracking-tight">Intelligence Investigation Case File Workspace</h2>
            <p class="font-mono text-sm text-gray-500">Target File Matrix: <span class="text-gold font-bold font-mono">{{ inv.ob_entry.ob_number }}</span></p>
        </div>
        <a href="/ob/{{ inv.ob_entry.id }}" class="text-navy font-bold text-xs underline">View Source OB Record</a>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="bg-white p-6 rounded-xl shadow space-y-4">
            <h3 class="text-xs font-bold text-navy uppercase tracking-widest border-b pb-2">Command Matrix Update Control</h3>
            <form method="POST" class="space-y-3 text-xs">
                {{ form.hidden_tag() }}
                <div><label class="block font-bold text-gray-700 mb-1">Operational Case Officer Assignment</label>{{ form.investigator_id(class="w-full p-2 border rounded text-xs") }}</div>
                <div><label class="block font-bold text-gray-700 mb-1">Dossier Advancement Lifecycle State</label>{{ form.status(class="w-full p-2 border rounded text-xs") }}</div>
                <div><label class="block font-bold text-gray-700 mb-1">Witness Depositions Core Log</label>{{ form.witness_statements(class="w-full p-2 border rounded text-xs", rows=3) }}</div>
                <div><label class="block font-bold text-gray-700 mb-1">Arrest Booking Ledger Parameters</label>{{ form.arrest_records(class="w-full p-2 border rounded text-xs", rows=3) }}</div>
                <div class="border-t pt-2"><label class="block font-bold text-navy mb-1">Append New Intelligence Chronicle Note</label>{{ form.new_note(class="w-full p-2 border rounded text-xs border-blue-300", rows=3, placeholder="Input factual structural chronological findings...") }}</div>
                {{ form.submit(class="w-full bg-navy text-white font-bold py-2 rounded text-xs uppercase tracking-wider hover:bg-securityblue cursor-pointer") }}
            </form>
        </div>

        <div class="bg-white p-6 rounded-xl shadow space-y-4">
            <h3 class="text-xs font-bold text-navy uppercase tracking-widest border-b pb-2">Investigation Chronology Timeline Log</h3>
            <div class="space-y-4 max-h-[450px] overflow-y-auto pr-2">
                <div class="border-l-2 border-gold pl-4 relative">
                    <span class="absolute w-2.5 h-2.5 bg-gold rounded-full -left-[6px] top-1"></span>
                    <p class="text-2xs font-bold text-gray-400">{{ inv.ob_entry.date_created.strftime('%d %B %Y') }}</p>
                    <p class="text-xs font-bold text-navy">Initial Genesis Point Logged</p>
                    <p class="text-2xs text-gray-600">Filing executed inside official occurrence architecture book matrix.</p>
                </div>
                {% for n in inv.notes | sort(attribute='date_created') %}
                <div class="border-l-2 border-navy pl-4 relative">
                    <span class="absolute w-2.5 h-2.5 bg-navy rounded-full -left-[6px] top-1"></span>
                    <p class="text-2xs font-bold text-gray-400">{{ n.date_created.strftime('%d %B %Y %H:%M') }}</p>
                    <p class="text-xs font-bold text-navy">{{ n.created_by }}</p>
                    <p class="text-2xs text-gray-600 italic">"{{ n.note_text }}"</p>
                </div>
                {% endfor %}
            </div>
        </div>

        <div class="bg-white p-6 rounded-xl shadow space-y-4">
            <h3 class="text-xs font-bold text-navy uppercase tracking-widest border-b pb-2">Forensic Digital Evidence Artifact Vault</h3>
            
            <form method="POST" action="/investigations/{{ inv.id }}/upload-evidence" enctype="multipart/form-data" class="bg-slatewhite p-3 border rounded space-y-2 text-xs">
                {{ evidence_form.hidden_tag() }}
                <label class="block font-bold text-gray-700">Integrate Digital Forensic Artifact</label>
                {{ evidence_form.evidence_file(class="w-full text-2xs") }}
                {{ evidence_form.submit(class="w-full bg-gold text-navy font-bold py-1 rounded text-2xs uppercase cursor-pointer hover:bg-yellow-600") }}
            </form>

            <div class="space-y-2 max-h-64 overflow-y-auto">
                {% for e in inv.ob_entry.evidence_files %}
                <div class="p-2 border rounded bg-gray-50 flex justify-between items-center text-xs">
                    <div>
                        <p class="font-mono text-navy font-bold truncate max-w-[150px]">{{ e.file_name }}</p>
                        <p class="text-3xs text-gray-400">By: {{ e.uploaded_by }}</p>
                    </div>
                    <a href="/evidence/download/{{ e.id }}" class="bg-navy text-white text-3xs px-2 py-1 rounded uppercase font-bold tracking-wider">Extract</a>
                </div>
                {% else %}
                <p class="text-xs text-gray-400 text-center py-4 italic">No dynamic digital assets linked within current folder structural matrices.</p>
                {% endfor %}
            </div>
        </div>
    </div>
</div>
'''

SUSPECT_REGISTRY_VIEW = '''
<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="bg-white p-6 rounded-xl shadow border-t-4 border-red-600">
        <h3 class="text-base font-black text-navy uppercase tracking-tight mb-4">Catalog Suspect Asset Identity</h3>
        <form method="POST" class="space-y-3 text-xs">
            {{ form.hidden_tag() }}
            <div><label class="block font-bold text-gray-700 mb-1">Full Identity Name</label>{{ form.full_name(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">National ID Token</label>{{ form.national_id(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">Date of Birth Matrix</label>{{ form.date_of_birth(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">Gender Class Axis</label>{{ form.gender(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">Last Known Geographic Address</label>{{ form.address(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy", rows=2) }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">Phone Link</label>{{ form.phone_number(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy") }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">Prior Arrest Architectural History Logs</label>{{ form.arrest_history(class="w-full p-2 border rounded focus:ring-1 focus:ring-navy", rows=3) }}</div>
            {{ form.submit(class="w-full bg-red-700 text-white font-bold py-2 rounded uppercase tracking-wider hover:bg-red-800 cursor-pointer") }}
        </form>
    </div>

    <div class="lg:col-span-2 bg-white p-6 rounded-xl shadow space-y-4">
        <h3 class="text-lg font-black text-navy uppercase tracking-tight border-b pb-2">National Biometric Suspect Index</h3>
        <div class="space-y-4">
            {% for s in suspects %}
            <div class="p-4 border rounded-lg bg-gray-50 grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-medium">
                <div>
                    <h4 class="text-sm font-black text-navy uppercase mb-1">{{ s.full_name }}</h4>
                    <p class="text-gray-500">ID Vector: <span class="font-mono text-gray-800 font-bold">{{ s.national_id or 'UNKNOWN' }}</span></p>
                    <p class="text-gray-500">Gender Variant Axis: <span class="text-gray-800">{{ s.gender }}</span></p>
                    <p class="text-gray-500">DOB Ledger: <span class="text-gray-800">{{ s.date_of_birth }}</span></p>
                </div>
                <div>
                    <h5 class="text-2xs font-bold uppercase tracking-widest text-gray-400 mb-1">Bound Active Case Log Connections</h5>
                    <ul class="space-y-1 max-h-20 overflow-y-auto font-mono text-3xs font-bold text-navy">
                        {% for c in s.ob_entries %}
                            <li><a href="/ob/{{c.id}}" class="underline">{{ c.ob_number }}</a> ({{ c.status }})</li>
                        {% else %}
                            <li class="text-gray-400 italic font-normal">No dynamic bindings active.</li>
                        {% endfor %}
                    </ul>
                    
                    <form action="/suspects/link/{{ s.id }}" method="POST" class="mt-2 flex space-x-1">
                        <input type="text" name="ob_number_link" placeholder="Map OB Serial Reference" class="px-2 py-0.5 border rounded text-3xs max-w-[120px] font-mono" required>
                        <button type="submit" class="bg-navy text-white text-3xs px-2 py-0.5 rounded font-bold uppercase">Bind</button>
                    </form>
                </div>
                <div>
                    <h5 class="text-2xs font-bold uppercase tracking-widest text-gray-400 mb-1">Historical Criminal Profiles Ledger</h5>
                    <div class="bg-white p-2 border rounded h-24 overflow-y-auto text-3xs whitespace-pre-wrap leading-tight text-gray-600 font-mono">{{ s.arrest_history or 'Clear historical ledger.' }}</div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
</div>
'''

OFFICER_MANAGEMENT_VIEW = '''
<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="bg-white p-6 rounded-xl shadow border-t-4 border-navy">
        <h3 class="text-base font-black text-navy uppercase tracking-tight mb-4">Provision Operational System Personnel Account</h3>
        <form method="POST" class="space-y-3 text-xs">
            {{ form.hidden_tag() }}
            <div><label class="block font-bold text-gray-700 mb-1">Service Number ID Vector</label>{{ form.service_number(class="w-full p-2 border rounded") }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">Official Communications Email</label>{{ form.email(class="w-full p-2 border rounded") }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">Full Identity Name</label>{{ form.full_name(class="w-full p-2 border rounded") }}</div>
            <div class="grid grid-cols-2 gap-2">
                <div><label class="block font-bold text-gray-700 mb-1">Rank Structure</label>{{ form.rank(class="w-full p-2 border rounded") }}</div>
                <div><label class="block font-bold text-gray-700 mb-1">System Operational Role</label>{{ form.role(class="w-full p-2 border rounded") }}</div>
            </div>
            <div><label class="block font-bold text-gray-700 mb-1">Phone Line Array</label>{{ form.phone_number(class="w-full p-2 border rounded") }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">Department / Division Vector</label>{{ form.department(class="w-full p-2 border rounded") }}</div>
            <div><label class="block font-bold text-gray-700 mb-1">Assigned Station Domain</label>{{ form.station_id(class="w-full p-2 border rounded") }}</div>
            <div class="grid grid-cols-2 gap-2 border-t pt-2">
                <div><label class="block font-bold text-gray-700 mb-1">Access Password</label>{{ form.password(class="w-full p-2 border rounded") }}</div>
                <div><label class="block font-bold text-gray-700 mb-1">Confirm Identity Verification</label>{{ form.confirm_password(class="w-full p-2 border rounded") }}</div>
            </div>
            {{ form.submit(class="w-full bg-navy text-white font-bold py-2 rounded uppercase tracking-wider hover:bg-securityblue mt-2 cursor-pointer") }}
        </form>
    </div>

    <div class="lg:col-span-2 bg-white p-6 rounded-xl shadow">
        <h3 class="text-lg font-black text-navy uppercase tracking-tight border-b pb-2 mb-4">Station Asset Roster Architecture Ledger</h3>
        <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse text-xs">
                <thead>
                    <tr class="bg-gray-100 font-bold uppercase tracking-wider text-gray-600 border-b">
                        <th class="p-3">Service Num ID</th>
                        <th class="p-3">Identity / Rank</th>
                        <th class="p-3">Assigned Station</th>
                        <th class="p-3">Clearance Access Level</th>
                        <th class="p-3">Lifecycle State</th>
                        <th class="p-3 text-right">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for o in officers %}
                    <tr class="border-b hover:bg-gray-50 font-medium">
                        <td class="p-3 font-mono font-bold text-navy">{{ o.service_number }}</td>
                        <td class="p-3"><strong>{{ o.rank }} {{ o.full_name }}</strong><br/><span class="text-gray-400 font-mono">{{ o.email }}</span></td>
                        <td class="p-3 text-gray-600">{{ o.station.name }}</td>
                        <td class="p-3 text-gray-800 font-bold text-2xs">{{ o.role.upper() }}</td>
                        <td class="p-3">
                            {% if o.is_active %}
                                <span class="px-2 py-0.5 rounded bg-green-100 text-green-800 font-bold text-2xs">ACTIVE</span>
                            {% else %}
                                <span class="px-2 py-0.5 rounded bg-red-100 text-red-800 font-bold text-2xs">REVOKED</span>
                            {% endif %}
                        </td>
                        <td class="p-3 text-right">
                            <a href="/officers/toggle/{{ o.id }}" class="text-xs font-bold {% if o.is_active %} text-red-600 hover:underline {% else %} text-green-600 hover:underline {% endif %}">
                                {% if o.is_active %} Revoke Clearances {% else %} Re-Activate Assumed Identity {% endif %}
                            </a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
'''

AUDIT_LOGS_VIEW = '''
<div class="bg-white p-6 rounded-xl shadow">
    <div class="border-b pb-4 mb-4">
        <h2 class="text-2xl font-black text-navy uppercase tracking-tight">Immutable System Audit Trail Architecture Log</h2>
        <p class="text-xs text-gray-500">Cryptographically isolated stream monitoring transactional execution commands.</p>
    </div>
    <div class="overflow-x-auto max-h-[600px] overflow-y-auto">
        <table class="w-full text-left border-collapse font-mono text-2xs">
            <thead>
                <tr class="bg-navy text-white font-bold uppercase tracking-wider border-b sticky top-0">
                    <th class="p-2">Chronology Vector Timestamp</th>
                    <th class="p-2">Personnel Asset Operator</th>
                    <th class="p-2">Executed System Action Statement</th>
                    <th class="p-2">Network Socket IP Locus Address</th>
                </tr>
            </thead>
            <tbody>
                {% for l in logs %}
                <tr class="border-b hover:bg-gray-50 text-gray-700">
                    <td class="p-2 text-gray-400">{{ l.timestamp.strftime('%Y-%m-%d %H:%M:%S') }}</td>
                    <td class="p-2 font-bold text-navy">
                        {% if l.user %}
                            {{ l.user.rank }} {{ l.user.full_name }} ({{ l.user.service_number }})
                        {% else %}
                            SYSTEM GATEWAY LAYER ANONYMOUS INTERCEPT
                        {% endif %}
                    </td>
                    <td class="p-2 font-medium text-gray-900">{{ l.action }}</td>
                    <td class="p-2 text-blue-700 font-bold">{{ l.ip_address }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
'''

REPORTS_DASHBOARD_VIEW = '''
<div class="max-w-4xl mx-auto bg-white p-8 rounded-xl shadow">
    <div class="border-b pb-4 mb-6">
        <h2 class="text-2xl font-black text-navy uppercase tracking-tight">Strategic Intelligence Export Control Module</h2>
        <p class="text-xs text-gray-500">Compile aggregated tactical data into signed structural PDF matrices or raw relational analytical structural Excel spreadsheets.</p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        {% for scope in ['daily', 'weekly', 'monthly', 'annual'] %}
        <div class="p-4 border rounded-xl bg-gray-50 flex justify-between items-center font-medium">
            <div>
                <h4 class="text-sm font-black text-navy uppercase tracking-wide">{{ scope.upper() }} CRIME INTELLIGENCE LEDGER</h4>
                <p class="text-3xs text-gray-400 mt-0.5 font-mono">Scope boundaries targeted contextually relative to current session clearing state timestamp.</p>
            </div>
            <div class="flex space-x-1 text-2xs">
                <a href="/reports/export/{{ scope }}/pdf" class="bg-navy text-white px-3 py-1.5 font-bold uppercase tracking-wider rounded shadow hover:bg-securityblue">PDF</a>
                <a href="/reports/export/{{ scope }}/excel" class="bg-gold text-navy px-3 py-1.5 font-black uppercase tracking-wider rounded shadow hover:bg-yellow-600">XLSX</a>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
'''

# ==========================================
# SEED CORES & EXECUTION APPARATUS
# ==========================================

def seed_system_architecture_matrices():
    db.create_all()
    if Station.query.count() == 0:
        s1 = Station(name="Nyeri Central Police Station", code="NYR01")
        s2 = Station(name="Karatina Police Station", code="KRT02")
        s3 = Station(name="Othaya Police Station", code="OTH03")
        s4 = Station(name="Mukurweini Police Station", code="MKR04")
        s5 = Station(name="Nanyuki Police Station", code="NYK05")
        db.session.add_all([s1, s2, s3, s4, s5])
        db.session.commit()
        
    if User.query.count() == 0:
        nyeri_station = Station.query.filter_by(code="NYR01").first()
        admin_user = User(
            service_number="NPS/ADMIN/2026",
            email="admin@nps.go.ke",
            password_hash=generate_password_hash("AdminMaster2026!"),
            role="Administrator",
            full_name="System Administration Node",
            rank="Commissioner",
            phone_number="+254700000000",
            department="HQ Systems Development Command",
            station_id=nyeri_station.id,
            is_active=True
        )
        db.session.add(admin_user)
        db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        seed_system_architecture_matrices()
    app.run(host='0.0.0.0', port=5000, debug=True)