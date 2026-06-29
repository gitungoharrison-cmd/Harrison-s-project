import os
import qrcode
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ReportLab Components for PDF Generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

app = Flask(__name__)
app.config['SECRET_KEY'] = 'NPS_KENYA_SECURE_HIGH_LEVEL_DECRYPT_KEY_2026'

# --- ABSOLUTE PATH ENGINE RESOLUTION (FOR PRODUCTION STABILITY) ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR, 'dpobcms.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Absolute static upload folder setup
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- SECURITY UTILITIES & FILE VALIDATION ---
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'mp4', 'avi', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_abstract_pdf(ob, destination_path):
    doc = SimpleDocTemplate(destination_path, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    styles = getSampleStyleSheet()
    
    # Custom Styles for High Contrast Output
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=14, leading=18, alignment=1, textColor=colors.HexColor('#0B132B'))
    sub_style = ParagraphStyle('SubStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=14, alignment=1, textColor=colors.HexColor('#1C2541'))
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13)
    bold_body = ParagraphStyle('BoldBody', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=13)

    # Header section
    story.append(Paragraph("NATIONAL POLICE SERVICE — REPUBLIC OF KENYA", title_style))
    story.append(Paragraph(f"{ob.station.name.upper()} | OFFICIAL STATION ABSTRACT REPORT", sub_style))
    story.append(Spacer(1, 15))
    
    # QR Code Generation (Embedded Verification Matrix)
    qr_data = f"OB_VERIFY:{ob.ob_number}|Station:{ob.station.name}|Status:{ob.status}"
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img_path = destination_path.replace('.pdf', '_qr.png')
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(qr_img_path)
    
    # Table Grid Layout
    data = [
        [Paragraph("<b>OB Number:</b>", body_style), Paragraph(ob.ob_number, bold_body), Paragraph("", body_style), Image(qr_img_path, width=65, height=65)],
        [Paragraph("<b>Date & Time Logged:</b>", body_style), Paragraph(ob.created_at.strftime('%Y-%m-%d %H:%M'), body_style), "", ""],
        [Paragraph("<b>Complainant Name:</b>", body_style), Paragraph(ob.complainant_name, body_style), Paragraph("<b>National ID:</b>", body_style), Paragraph(ob.complainant_id, body_style)],
        [Paragraph("<b>Phone Number:</b>", body_style), Paragraph(ob.complainant_phone, body_style), Paragraph("<b>Incident Location:</b>", body_style), Paragraph(ob.incident_location, body_style)],
        [Paragraph("<b>Crime Category:</b>", body_style), Paragraph(ob.crime_category, bold_body), Paragraph("<b>Current Status:</b>", body_style), Paragraph(ob.status, body_style)]
    ]
    
    t = Table(data, colWidths=[110, 160, 100, 160])
    t.setStyle(TableStyle([
        ('SPAN', (1,0), (2,0)),
        ('SPAN', (3,0), (3,1)),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LINEBELOW', (0,4), (-1,4), 1, colors.HexColor('#0B132B'))
    ]))
    story.append(t)
    story.append(Spacer(1, 15))
    
    # Narrative Statement
    story.append(Paragraph("<b>INCIDENT STATEMENT NARRATIVE / DESCRIPTION</b>", sub_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(ob.narrative, body_style))
    story.append(Spacer(1, 45))
    
    # Verification Signature & Seal Lines
    sig_data = [
        [Paragraph("____________________________<br/>Recording Officer Signature", body_style), 
         Paragraph("____________________________<br/>Official Station Stamp Area", body_style)]
    ]
    sig_table = Table(sig_data, colWidths=[265, 265])
    story.append(sig_table)
    
    doc.build(story)
    
    # Remove transient file artifacts
    if os.path.exists(qr_img_path):
        os.remove(qr_img_path)

# --- DATABASE SCHEMAS & RELATIONSHIP MODELS ---
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
    rank = db.Column(db.String(50), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False) # Administrator, OCS, Desk Officer, Investigator
    is_active = db.Column(db.Boolean, default=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id'), nullable=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Suspect(db.Model):
    __tablename__ = 'suspects'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    national_id = db.Column(db.String(50), unique=True, nullable=True)
    dob = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(10), nullable=False)
    address = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    arrest_history = db.Column(db.Text, nullable=True)

class OBEntry(db.Model):
    __tablename__ = 'ob_entries'
    id = db.Column(db.Integer, primary_key=True)
    ob_number = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    complainant_name = db.Column(db.String(100), nullable=False)
    complainant_id = db.Column(db.String(50), nullable=False)
    complainant_phone = db.Column(db.String(20), nullable=False)
    complainant_gender = db.Column(db.String(10), nullable=False)
    complainant_address = db.Column(db.Text, nullable=False)
    incident_location = db.Column(db.String(200), nullable=False)
    crime_category = db.Column(db.String(100), nullable=False)
    suspect_details = db.Column(db.Text, nullable=True)
    narrative = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Pending Review') 
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id'), nullable=False)
    reporting_officer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    reporting_officer = db.relationship('User', foreign_keys=[reporting_officer_id])
    investigation = db.relationship('Investigation', backref='ob_entry', uselist=False, lazy=True)
    evidence_files = db.relationship('Evidence', backref='ob_entry', lazy=True)

class Investigation(db.Model):
    __tablename__ = 'investigations'
    id = db.Column(db.Integer, primary_key=True)
    ob_entry_id = db.Column(db.Integer, db.ForeignKey('ob_entries.id'), unique=True, nullable=False)
    investigator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    investigator = db.relationship('User', foreign_keys=[investigator_id])
    notes = db.relationship('InvestigationNote', backref='investigation', lazy=True)

class InvestigationNote(db.Model):
    __tablename__ = 'investigation_notes'
    id = db.Column(db.Integer, primary_key=True)
    investigation_id = db.Column(db.Integer, db.ForeignKey('investigations.id'), nullable=False)
    note_type = db.Column(db.String(50), nullable=False) 
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    recorded_by = db.Column(db.String(100), nullable=False)

class Evidence(db.Model):
    __tablename__ = 'evidence'
    id = db.Column(db.Integer, primary_key=True)
    ob_entry_id = db.Column(db.Integer, db.ForeignKey('ob_entries.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by = db.Column(db.String(100), nullable=False)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    action = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50), nullable=True)

# --- SECURE AUTHENTICATION FORMS ---
class LoginForm(FlaskForm):
    service_number = StringField('Service Number', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Secure Authenticate')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def log_audit(action):
    user_identifier = current_user.full_name if current_user.is_authenticated else "Anonymous/Public"
    log = AuditLog(username=user_identifier, action=action, ip_address=request.remote_addr)
    db.session.add(log)
    db.session.commit()

# --- WEB & ROUTING CONTROLLERS ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(service_number=form.service_number.data, is_active=True).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            log_audit("User security verification success - logged in.")
            return redirect(url_for('dashboard'))
        flash('Invalid Service Credentials or Disabled Profile Exception', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    log_audit("User initialized regular log out process.")
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'Administrator':
        obs = OBEntry.query.all()
        cases_open = OBEntry.query.filter(OBEntry.status != 'Closed').count()
        cases_closed = OBEntry.query.filter_by(status='Closed').count()
        cases_investigation = OBEntry.query.filter_by(status='Under Investigation').count()
        total_officers = User.query.count()
    else:
        obs = OBEntry.query.filter_by(station_id=current_user.station_id).all()
        cases_open = OBEntry.query.filter(OBEntry.id.in_([o.id for o in obs]), OBEntry.status != 'Closed').count()
        cases_closed = OBEntry.query.filter(OBEntry.id.in_([o.id for o in obs]), OBEntry.status == 'Closed').count()
        cases_investigation = OBEntry.query.filter(OBEntry.id.in_([o.id for o in obs]), OBEntry.status == 'Under Investigation').count()
        total_officers = User.query.filter_by(station_id=current_user.station_id).count()

    total_ob = len(obs)
    evidence_count = Evidence.query.filter(Evidence.ob_entry_id.in_([o.id for o in obs])).count() if obs else 0
    arrests = OBEntry.query.filter(OBEntry.id.in_([o.id for o in obs]), OBEntry.status == 'Arrest Made').count() if obs else 0
    
    return render_template('dashboard.html', total_ob=total_ob, cases_open=cases_open, 
                           cases_closed=cases_closed, cases_investigation=cases_investigation, 
                           total_officers=total_officers, evidence_count=evidence_count, arrests=arrests)

@app.route('/ob', methods=['GET', 'POST'])
@login_required
def ob_management():
    if request.method == 'POST':
        year = datetime.utcnow().year
        last_entry = OBEntry.query.filter(OBEntry.ob_number.like(f"OB/{year}/%")).order_by(OBEntry.id.desc()).first()
        next_id = 1 if not last_entry else int(last_entry.ob_number.split('/')[-1]) + 1
        ob_num = f"OB/{year}/{str(next_id).zfill(6)}"
        
        new_ob = OBEntry(
            ob_number=ob_num,
            complainant_name=request.form['complainant_name'],
            complainant_id=request.form['complainant_id'],
            complainant_phone=request.form['complainant_phone'],
            complainant_gender=request.form['complainant_gender'],
            complainant_address=request.form['complainant_address'],
            incident_location=request.form['incident_location'],
            crime_category=request.form['crime_category'],
            suspect_details=request.form.get('suspect_details', ''),
            narrative=request.form['narrative'],
            station_id=current_user.station_id,
            reporting_officer_id=current_user.id
        )
        db.session.add(new_ob)
        db.session.commit()
        
        new_inv = Investigation(ob_entry_id=new_ob.id)
        db.session.add(new_inv)
        db.session.commit()
        
        base_note = InvestigationNote(
            investigation_id=new_inv.id,
            note_type='Timeline Update',
            content='Case Reported and Primary Occurrence Entry Authorized.',
            recorded_by=current_user.full_name
        )
        db.session.add(base_note)
        db.session.commit()
        
        log_audit(f"Created new entry {ob_num}")
        flash(f'Occurrence Record registered successfully: {ob_num}', 'success')
        return redirect(url_for('ob_management'))

    if current_user.role == 'Administrator':
        entries = OBEntry.query.all()
    else:
        entries = OBEntry.query.filter_by(station_id=current_user.station_id).all()
    return render_template('ob_list.html', entries=entries)

@app.route('/ob/<int:id>', methods=['GET', 'POST'])
@login_required
def ob_detail(id):
    entry = OBEntry.query.get_or_404(id)
    if current_user.role != 'Administrator' and entry.station_id != current_user.station_id:
        return "Access Violation Exception", 403
        
    investigators = User.query.filter_by(station_id=current_user.station_id, role='Investigator').all()
    return render_template('ob_detail.html', ob=entry, investigators=investigators)

@app.route('/ob/<int:id>/update_status', methods=['POST'])
@login_required
def update_ob_status(id):
    entry = OBEntry.query.get_or_404(id)
    if current_user.role != 'Administrator' and entry.station_id != current_user.station_id:
        return "Access Violation Exception", 403
    
    old_status = entry.status
    new_status = request.form['status']
    entry.status = new_status
    db.session.commit()
    
    note = InvestigationNote(
        investigation_id=entry.investigation.id,
        note_type='Timeline Update',
        content=f"Case classification changed from '{old_status}' to '{new_status}' status.",
        recorded_by=current_user.full_name
    )
    db.session.add(note)
    db.session.commit()
    
    log_audit(f"Updated status of {entry.ob_number} to {new_status}")
    flash("Status structural workflow matrix updated.", "success")
    return redirect(url_for('ob_detail', id=entry.id))

@app.route('/ob/<int:id>/assign_investigator', methods=['POST'])
@login_required
def assign_investigator(id):
    entry = OBEntry.query.get_or_404(id)
    inv_id = request.form['investigator_id']
    entry.investigation.investigator_id = inv_id
    entry.status = 'Under Investigation'
    
    officer = User.query.get(inv_id)
    note = InvestigationNote(
        investigation_id=entry.investigation.id,
        note_type='Timeline Update',
        content=f"Case file transferred to dedicated investigator: {officer.rank} {officer.full_name}.",
        recorded_by=current_user.full_name
    )
    db.session.add(note)
    db.session.commit()
    log_audit(f"Assigned {entry.ob_number} to investigator code {inv_id}")
    return redirect(url_for('ob_detail', id=entry.id))

@app.route('/ob/<int:id>/add_note', methods=['POST'])
@login_required
def add_investigation_note(id):
    entry = OBEntry.query.get_or_404(id)
    note = InvestigationNote(
        investigation_id=entry.investigation.id,
        note_type=request.form['note_type'],
        content=request.form['content'],
        recorded_by=current_user.full_name
    )
    db.session.add(note)
    db.session.commit()
    log_audit(f"Added operational tracking entry note to {entry.ob_number}")
    return redirect(url_for('ob_detail', id=entry.id))

@app.route('/ob/<int:id>/upload_evidence', methods=['POST'])
@login_required
def upload_evidence(id):
    entry = OBEntry.query.get_or_404(id)
    if 'file' not in request.files:
        flash('No file partition detected.', 'danger')
        return redirect(url_for('ob_detail', id=entry.id))
    file = request.files['file']
    if file.filename == '':
        return redirect(url_for('ob_detail', id=entry.id))
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_name = f"{entry.id}_{int(datetime.utcnow().timestamp())}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
        
        ev = Evidence(
            ob_entry_id=entry.id,
            filename=unique_name,
            file_type=filename.rsplit('.', 1)[1].lower(),
            uploaded_by=current_user.full_name
        )
        db.session.add(ev)
        
        note = InvestigationNote(
            investigation_id=entry.investigation.id,
            note_type='General Note',
            content=f"New cryptographic evidentiary object attachment logged: {filename}",
            recorded_by=current_user.full_name
        )
        db.session.add(note)
        db.session.commit()
        log_audit(f"Attached objective evidence file {filename} to {entry.ob_number}")
    return redirect(url_for('ob_detail', id=entry.id))

@app.route('/ob/<int:id>/download_abstract')
@login_required
def download_abstract(id):
    entry = OBEntry.query.get_or_404(id)
    filename = f"Abstract_{entry.ob_number.replace('/', '_')}.pdf"
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    generate_abstract_pdf(entry, pdf_path)
    log_audit(f"Compiled signature abstract PDF mapping token {entry.ob_number}")
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/public_track', methods=['GET', 'POST'])
def public_track():
    entry = None
    searched = False
    if request.method == 'POST':
        ob_num = request.form['ob_number'].strip()
        entry = OBEntry.query.filter_by(ob_number=ob_num).first()
        searched = True
    return render_template('public_track.html', entry=entry, searched=searched)

@app.route('/suspects', methods=['GET', 'POST'])
@login_required
def suspects():
    if request.method == 'POST':
        dob_val = datetime.strptime(request.form['dob'], '%Y-%m-%d').date() if request.form['dob'] else None
        s = Suspect(
            full_name=request.form['full_name'],
            national_id=request.form['national_id'],
            dob=dob_val,
            gender=request.form['gender'],
            address=request.form['address'],
            phone=request.form['phone'],
            arrest_history=request.form['arrest_history']
        )
        db.session.add(s)
        db.session.commit()
        log_audit(f"Registered suspect entry identifier {s.full_name}")
        return redirect(url_for('suspects'))
    suspect_list = Suspect.query.all()
    return render_template('suspects.html', suspects=suspect_list)

@app.route('/officers', methods=['GET', 'POST'])
@login_required
def officer_registry():
    if current_user.role != 'Administrator':
        return "Access Control Privilege Level Rejection Error", 403
    if request.method == 'POST':
        u = User(
            service_number=request.form['service_number'],
            rank=request.form['rank'],
            full_name=request.form['full_name'],
            email=request.form['email'],
            phone=request.form['phone'],
            role=request.form['role'],
            station_id=request.form['station_id']
        )
        u.set_password(request.form['password'])
        db.session.add(u)
        db.session.commit()
        log_audit(f"Admin provisioned new security personnel account: {u.service_number}")
        return redirect(url_for('officer_registry'))
        
    officers = User.query.all()
    stations = Station.query.all()
    return render_template('officers.html', officers=officers, stations=stations)

# --- SYSTEM INITIALIZATION & SEED ENGINE ---
def seed_database():
    db.create_all()
    if not Station.query.first():
        stns = [
            Station(name="Nyeri Central Police Station", code="NYR_CEN"),
            Station(name="Karatina Police Station", code="KRT_STN"),
            Station(name="Othaya Police Station", code="OTH_STN"),
            Station(name="Mukurweini Police Station", code="MKR_STN"),
            Station(name="Nanyuki Police Station", code="NYK_STN")
        ]
        db.session.add_all(stns)
        db.session.commit()
        
        admin = User(
            service_number="NPS/ADMIN/2026",
            rank="Senior Commissioner",
            full_name="System Super Administrator",
            email="admin@police.go.ke",
            phone="+254700000000",
            role="Administrator",
            station_id=1
        )
        admin.set_password("NpsAdminSecure2026!")
        db.session.add(admin)
        
        test_officer = User(
            service_number="NPS/OFFICER/001",
            rank="Inspector of Police",
            full_name="John Kiprop",
            email="kiprop@police.go.ke",
            phone="+254711223344",
            role="Investigator",
            station_id=1
        )
        test_officer.set_password("OfficerPass123!")
        db.session.add(test_officer)
        db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        seed_database()
    app.run(debug=True, host='0.0.0.0', port=5000)