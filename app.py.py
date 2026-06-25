import os
import io
import enum
from datetime import datetime, date, timedelta, time
from functools import wraps
import json

from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, SelectField, TextAreaField, DateField
from wtforms.validators import DataRequired, Email, Length, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# FastAPI REST Routing Subsystem Integration
from fastapi import APIRouter, Depends, HTTPException, status as fastapi_status
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Date, Time, DateTime, Boolean, ForeignKey, Text, Numeric, Enum
from sqlalchemy.orm import relationship

# ReportLab and QR Code Engine
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import qrcode
import openpyxl

app = Flask(__name__)
app.config['SECRET_KEY'] = '9c91ee0a905a5a1f274a77bc3a9e64e9a039ff0123e4d82b'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///dpobcms.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static/uploads')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
Base = db.Model  # Map declarative Base directly to Flask-SQLAlchemy wrapper

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


# --- ADVANCED ENUMS FOR CUSTODY & SECURITY ---
class CellStatus(enum.Enum):
    AVAILABLE = "Available"
    OCCUPIED = "Occupied"
    FULL = "Full"
    UNDER_MAINTENANCE = "Under Maintenance"
    CLOSED = "Closed"

class MovementReason(enum.Enum):
    COURT = "Court Appearance"
    MEDICAL = "Medical Treatment"
    INTERVIEW = "Investigation Interview"
    TRANSFER = "Cell Transfer"
    RELEASE = "Release"

class MealType(enum.Enum):
    BREAKFAST = "Breakfast"
    LUNCH = "Lunch"
    DINNER = "Dinner"


# --- SECURITY UTILITIES & AUDIT HOOK ---
def log_audit(action, ip_address=None):
    user_id = current_user.id if current_user.is_authenticated else None
    station_id = current_user.officer.station_id if (current_user.is_authenticated and current_user.officer) else None
    if not ip_address:
        ip_address = request.remote_addr if request else "0.0.0.0"
    log = AuditLog(
        user_id=user_id,
        station_id=station_id,
        action=action,
        ip_address=ip_address
    )
    db.session.add(log)
    db.session.commit()

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                log_audit(f"ACCESS DENIED: Attempted to access {request.path}")
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# --- SYSTEM CORE ORM MODELS ---

class Station(Base):
    __tablename__ = 'stations'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(10), unique=True, nullable=False)
    officers = relationship('Officer', backref='station', lazy=True)
    ob_entries = relationship('OBEntry', backref='station', lazy=True)
    audit_logs = relationship('AuditLog', backref='station', lazy=True)

class User(Base, UserMixin):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(50), nullable=False) # 'Administrator', 'OCS', 'Desk Officer', 'Investigator'
    is_active = Column(Boolean, default=True)
    officer = relationship('Officer', backref='user', uselist=False, lazy=True)
    audit_logs = relationship('AuditLog', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Officer(Base):
    __tablename__ = 'officers'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    station_id = Column(Integer, ForeignKey('stations.id'), nullable=False)
    service_number = Column(String(50), unique=True, nullable=False)
    rank = Column(String(50), nullable=False)
    full_name = Column(String(100), nullable=False)
    department = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=False)
    ob_entries_recorded = relationship('OBEntry', backref='recording_officer', lazy=True)
    investigations_assigned = relationship('Investigation', backref='investigator', lazy=True)

suspect_cases = db.Table('suspect_cases',
    Column('suspect_id', Integer, ForeignKey('suspects.id'), primary_key=True),
    Column('ob_entry_id', Integer, ForeignKey('ob_entries.id'), primary_key=True)
)

class OBEntry(Base):
    __tablename__ = 'ob_entries'
    id = Column(Integer, primary_key=True)
    ob_number = Column(String(30), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    station_id = Column(Integer, ForeignKey('stations.id'), nullable=False)
    complainant_name = Column(String(100), nullable=False)
    national_id = Column(String(50), nullable=False)
    phone_number = Column(String(20), nullable=False)
    gender = Column(String(10), nullable=False)
    address = Column(Text, nullable=False)
    incident_location = Column(String(200), nullable=False)
    crime_category = Column(String(100), nullable=False)
    suspect_details = Column(Text, nullable=True)
    narrative_statement = Column(Text, nullable=False)
    recording_officer_id = Column(Integer, ForeignKey('officers.id'), nullable=False)
    status = Column(String(50), default='Pending Review')
    investigation = relationship('Investigation', backref='ob_entry', uselist=False, lazy=True)
    evidence_files = relationship('Evidence', backref='ob_entry', lazy=True)
    suspects = relationship('Suspect', secondary=suspect_cases, backref='ob_entries', lazy=True)

class Investigation(Base):
    __tablename__ = 'investigations'
    id = Column(Integer, primary_key=True)
    ob_entry_id = Column(Integer, ForeignKey('ob_entries.id'), unique=True, nullable=False)
    investigator_id = Column(Integer, ForeignKey('officers.id'), nullable=True)
    assigned_date = Column(DateTime, default=datetime.utcnow)
    notes = relationship('InvestigationNote', backref='investigation', lazy=True)

class InvestigationNote(Base):
    __tablename__ = 'investigation_notes'
    id = Column(Integer, primary_key=True)
    investigation_id = Column(Integer, ForeignKey('investigations.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    note_type = Column(String(50), nullable=False)
    entry_title = Column(String(200), nullable=False)
    statement_body = Column(Text, nullable=False)

class Suspect(Base):
    __tablename__ = 'suspects'
    id = Column(Integer, primary_key=True)
    full_name = Column(String(100), nullable=False)
    national_id = Column(String(50), unique=True, nullable=False)
    date_of_birth = Column(Date, nullable=False)
    gender = Column(String(10), nullable=False)
    address = Column(Text, nullable=False)
    phone_number = Column(String(20), nullable=False)
    arrest_history = Column(Text, nullable=True)

class Evidence(Base):
    __tablename__ = 'evidence'
    id = Column(Integer, primary_key=True)
    ob_entry_id = Column(Integer, ForeignKey('ob_entries.id'), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(100), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    uploaded_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    uploader = relationship('User', foreign_keys=[uploaded_by_user_id])

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    station_id = Column(Integer, ForeignKey('stations.id'), nullable=True)
    action = Column(String(255), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(50), nullable=False)


# --- CELL INFRASTRUCTURE & ALLOCATION MODELS ---
class CellBlock(Base):
    __tablename__ = 'cell_blocks'
    id = Column(Integer, primary_key=True)
    block_name = Column(String(50), unique=True, nullable=False)
    gender_category = Column(String(30), nullable=False)
    cells = relationship("Cell", back_populates="block")

class Cell(Base):
    __tablename__ = 'cells'
    id = Column(Integer, primary_key=True)
    block_id = Column(Integer, ForeignKey('cell_blocks.id'), nullable=False)
    cell_number = Column(String(10), nullable=False)
    capacity = Column(Integer, default=6)
    current_occupancy = Column(Integer, default=0)
    status = Column(Enum(CellStatus), default=CellStatus.AVAILABLE)

    block = relationship("CellBlock", back_populates="cells")
    prisoners = relationship("Prisoner", back_populates="cell")
    maintenance_records = relationship("CellMaintenance", back_populates="cell")

class CellMaintenance(Base):
    __tablename__ = 'cell_maintenance'
    id = Column(Integer, primary_key=True)
    cell_id = Column(Integer, ForeignKey('cells.id'), nullable=False)
    issue_description = Column(Text, nullable=False)
    reported_date = Column(DateTime, default=datetime.utcnow)
    resolved_date = Column(DateTime, nullable=True)
    status = Column(String(30), default="Pending")

    cell = relationship("Cell", back_populates="maintenance_records")


# --- CORE PRISONER CORE LEDGER ---
class Prisoner(Base):
    __tablename__ = 'prisoners'
    id = Column(Integer, primary_key=True)
    prisoner_number = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    national_id = Column(String(20), unique=True, nullable=True)
    dob = Column(Date, nullable=False)
    gender = Column(String(20), nullable=False)
    address = Column(Text)
    phone_number = Column(String(20))
    nationality = Column(String(50), default="Kenyan")
    marital_status = Column(String(20))
    occupation = Column(String(50))
    
    arrest_date = Column(Date, default=date.today)
    arrest_time = Column(Time, default=lambda: datetime.now().time())
    assigning_officer = Column(String(100), nullable=True)
    arresting_officer = Column(String(100), nullable=False)
    ob_number = Column(String(50), nullable=False)
    case_number = Column(String(50))
    
    cell_block_id = Column(Integer, ForeignKey('cell_blocks.id'))
    cell_id = Column(Integer, ForeignKey('cells.id'))
    bed_number = Column(String(10))
    custody_status = Column(String(30), default="In Custody") 
    risk_classification = Column(String(20), default="Medium") 

    cell = relationship("Cell", back_populates="prisoners")
    biometrics = relationship("PrisonerBiometric", uselist=False, back_populates="prisoner")
    property_items = relationship("PrisonerProperty", back_populates="prisoner")
    medical_assessments = relationship("MedicalAssessment", back_populates="prisoner")
    meal_logs = relationship("MealLog", back_populates="prisoner")
    visitor_logs = relationship("VisitorLog", back_populates="prisoner")
    movements = relationship("PrisonerMovement", back_populates="prisoner")
    court_productions = relationship("CourtProduction", back_populates="prisoner")
    release_record = relationship("ReleaseRecord", uselist=False, back_populates="prisoner")
    emergency_contacts = relationship("EmergencyContact", back_populates="prisoner")

class EmergencyContact(Base):
    __tablename__ = 'emergency_contacts'
    id = Column(Integer, primary_key=True)
    prisoner_id = Column(Integer, ForeignKey('prisoners.id'), nullable=False)
    name = Column(String(100), nullable=False)
    relationship_to_prisoner = Column(String(50), nullable=False)
    phone_number = Column(String(20), nullable=False)

    prisoner = relationship("Prisoner", back_populates="emergency_contacts")

class PrisonerBiometric(Base):
    __tablename__ = 'prisoner_biometrics'
    id = Column(Integer, primary_key=True)
    prisoner_id = Column(Integer, ForeignKey('prisoners.id'), unique=True, nullable=False)
    fingerprint_reg_number = Column(String(50), unique=True)
    biometric_id_number = Column(String(50), unique=True)
    mugshot_url = Column(String(255))
    signature_url = Column(String(255))
    registration_date = Column(DateTime, default=datetime.utcnow)
    registration_officer = Column(String(100))

    prisoner = relationship("Prisoner", back_populates="biometrics")

class PrisonerProperty(Base):
    __tablename__ = 'prisoner_property'
    id = Column(Integer, primary_key=True)
    property_receipt_number = Column(String(50), unique=True, nullable=False)
    prisoner_id = Column(Integer, ForeignKey('prisoners.id'), nullable=False)
    description = Column(String(255), nullable=False) 
    quantity = Column(Integer, default=1)
    condition = Column(String(100))
    date_received = Column(DateTime, default=datetime.utcnow)
    receiving_officer = Column(String(100))
    return_status = Column(Boolean, default=False)
    return_date = Column(DateTime, nullable=True)

    prisoner = relationship("Prisoner", back_populates="property_items")


# --- HEALTH, MEALS & VISITORS ---
class MedicalAssessment(Base):
    __tablename__ = 'medical_assessments'
    id = Column(Integer, primary_key=True)
    prisoner_id = Column(Integer, ForeignKey('prisoners.id'), nullable=False)
    initial_assessment = Column(Text)
    existing_conditions = Column(Text)
    medications_required = Column(Text)
    disability_status = Column(String(100))
    mental_health_assessment = Column(Text)
    medical_officer_notes = Column(Text)
    assessment_date = Column(DateTime, default=datetime.utcnow)

    prisoner = relationship("Prisoner", back_populates="medical_assessments")

class MealLog(Base):
    __tablename__ = 'meal_logs'
    id = Column(Integer, primary_key=True)
    prisoner_id = Column(Integer, ForeignKey('prisoners.id'), nullable=False)
    meal_date = Column(Date, default=date.today)
    meal_type = Column(Enum(MealType), nullable=False)
    served_by = Column(String(100))
    welfare_notes = Column(Text)

    prisoner = relationship("Prisoner", back_populates="meal_logs")

class VisitorLog(Base):
    __tablename__ = 'visitor_logs'
    id = Column(Integer, primary_key=True)
    prisoner_id = Column(Integer, ForeignKey('prisoners.id'), nullable=False)
    visitor_name = Column(String(100), nullable=False)
    national_id = Column(String(20), nullable=False)
    phone_number = Column(String(20))
    visitor_relationship = Column(String(50))
    visit_date = Column(Date, default=date.today)
    visit_time = Column(Time, default=lambda: datetime.now().time())
    approved_by = Column(String(100))

    prisoner = relationship("Prisoner", back_populates="visitor_logs")


# --- LIFECYCLE FLOW LOG TRACKING ---
class PrisonerMovement(Base):
    __tablename__ = 'prisoner_movements'
    id = Column(Integer, primary_key=True)
    movement_number = Column(String(50), unique=True, nullable=False)
    prisoner_id = Column(Integer, ForeignKey('prisoners.id'), nullable=False)
    previous_cell = Column(String(50))
    new_cell = Column(String(50))
    movement_reason = Column(Enum(MovementReason), nullable=False)
    movement_date = Column(DateTime, default=datetime.utcnow)
    authorizing_officer = Column(String(100))

    prisoner = relationship("Prisoner", back_populates="movements")

class CourtProduction(Base):
    __tablename__ = 'court_productions'
    id = Column(Integer, primary_key=True)
    prisoner_id = Column(Integer, ForeignKey('prisoners.id'), nullable=False)
    court_file_number = Column(String(50), nullable=False)
    court_name = Column(String(100), nullable=False)
    court_date = Column(Date, nullable=False)
    court_time = Column(Time, nullable=False)
    escort_officer = Column(String(100))
    transport_details = Column(String(255))
    court_outcome = Column(Text)

    prisoner = relationship("Prisoner", back_populates="court_productions")

class ReleaseRecord(Base):
    __tablename__ = 'release_records'
    id = Column(Integer, primary_key=True)
    release_number = Column(String(50), unique=True, nullable=False)
    prisoner_id = Column(Integer, ForeignKey('prisoners.id'), unique=True, nullable=False)
    release_date = Column(Date, default=date.today)
    release_time = Column(Time, default=lambda: datetime.now().time())
    release_reason = Column(String(50), nullable=False)
    authorizing_officer = Column(String(100))
    property_returned_status = Column(Boolean, default=False)
    final_remarks = Column(Text)

    prisoner = relationship("Prisoner", back_populates="release_record")


# --- EXTERNAL OPERATIONAL SERVICES MODULES ---
class PoliceBondBail(Base):
    __tablename__ = 'bonds_bails'
    id = Column(Integer, primary_key=True)
    bond_number = Column(String(50), unique=True, nullable=True)
    bail_number = Column(String(50), unique=True, nullable=True)
    prisoner_number = Column(String(50), nullable=False)
    ob_number = Column(String(50), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    guarantor_name = Column(String(100))
    guarantor_national_id = Column(String(20))
    guarantor_phone_number = Column(String(20))
    approval_officer = Column(String(100))
    bond_issue_date = Column(DateTime, default=datetime.utcnow)
    bail_release_date = Column(DateTime, nullable=True)
    court_date = Column(Date)
    status = Column(String(30), default="Active")

class MissingPerson(Base):
    __tablename__ = 'missing_persons'
    id = Column(Integer, primary_key=True)
    missing_person_number = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    gender = Column(String(20))
    age = Column(Integer)
    national_id = Column(String(20))
    photograph_url = Column(String(255))
    last_seen_location = Column(String(255))
    date_missing = Column(Date, nullable=False)
    reporting_person = Column(String(100))
    contact_information = Column(String(100))
    status = Column(String(30), default="Missing")

class GBVCase(Base):
    __tablename__ = 'gbv_cases'
    id = Column(Integer, primary_key=True)
    case_number = Column(String(50), unique=True, nullable=False)
    victim_information = Column(Text, nullable=False)  
    suspect_information = Column(Text)
    incident_details = Column(Text, nullable=False)
    risk_assessment = Column(Text)
    protection_order_status = Column(String(100))
    referral_information = Column(Text)
    counseling_notes = Column(Text)
    restricted_access_flag = Column(Boolean, default=True)

class TrafficCase(Base):
    __tablename__ = 'traffic_cases'
    id = Column(Integer, primary_key=True)
    vehicle_registration_number = Column(String(20), nullable=False)
    vehicle_owner = Column(String(100))
    driver_details = Column(Text)
    driving_licence_number = Column(String(20))
    insurance_information = Column(String(100))
    accident_location = Column(String(255))
    traffic_offence = Column(String(255))
    investigating_officer = Column(String(100))
    impound_status = Column(Boolean, default=False)
    fine_amount = Column(Numeric(10, 2))
    fine_status = Column(String(30), default="Unpaid")

class ChainOfCustody(Base):
    __tablename__ = 'chain_of_custody'
    id = Column(Integer, primary_key=True)
    evidence_number = Column(String(50), unique=True, nullable=False)
    collection_date = Column(DateTime, default=datetime.utcnow)
    collection_officer = Column(String(100), nullable=False)
    current_custodian = Column(String(100), nullable=False)
    storage_location = Column(String(100))
    transfer_history = Column(Text)  
    court_submission_status = Column(Boolean, default=False)

class ForensicReport(Base):
    __tablename__ = 'forensics'
    id = Column(Integer, primary_key=True)
    report_id = Column(String(50), unique=True, nullable=False)
    case_number = Column(String(50), nullable=False)
    ob_number = Column(String(50), nullable=False)
    suspect_reference = Column(String(50))
    fingerprint_reports = Column(Text)
    dna_analysis_reports = Column(Text)
    ballistic_reports = Column(Text)
    digital_forensic_reports = Column(Text)
    laboratory_results = Column(Text)

class NotificationLog(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    recipient_user_id = Column(Integer, nullable=False)
    message = Column(Text, nullable=False)
    channel = Column(String(20)) 
    timestamp = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)

class CommunityReport(Base):
    __tablename__ = 'community_reports'
    id = Column(Integer, primary_key=True)
    report_type = Column(String(50)) 
    content = Column(Text, nullable=False)
    logged_date = Column(DateTime, default=datetime.utcnow)

class PatrolLog(Base):
    __tablename__ = 'patrols'
    id = Column(Integer, primary_key=True)
    patrol_unit = Column(String(100), nullable=False)
    assignment_details = Column(Text)
    activity_logs = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

class PoliceUnitAssignment(Base):
    __tablename__ = 'police_units'
    id = Column(Integer, primary_key=True)
    officer_name = Column(String(100), nullable=False)
    service_branch = Column(String(50), nullable=False) 
    assigned_unit = Column(String(100), nullable=False) 


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --- FORMS FRAMEWORK ---

class LoginForm(FlaskForm):
    email = StringField('Service Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Authenticate')

class OBEntryForm(FlaskForm):
    complainant_name = StringField('Complainant Full Name', validators=[DataRequired()])
    national_id = StringField('National ID / Passport Number', validators=[DataRequired()])
    phone_number = StringField('Phone Number', validators=[DataRequired()])
    gender = SelectField('Gender', choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')], validators=[DataRequired()])
    address = TextAreaField('Residential Address', validators=[DataRequired()])
    incident_location = StringField('Exact Incident Location', validators=[DataRequired()])
    crime_category = SelectField('Crime Classification', choices=[
        ('Robbery', 'Robbery'), ('Assault', 'Assault'), ('Theft', 'Theft'),
        ('Homicide', 'Homicide'), ('Fraud', 'Fraud'), ('Cybercrime', 'Cybercrime'),
        ('Domestic Violence', 'Domestic Violence'), ('Other', 'Other Authorized Offense')
    ], validators=[DataRequired()])
    suspect_details = TextAreaField('Suspect Physical Description & Details')
    narrative_statement = TextAreaField('Detailed Narrative Statement', validators=[DataRequired()])
    submit = SubmitField('Log Occurrence Entry')

class AssignInvestigatorForm(FlaskForm):
    investigator_id = SelectField('Assign Investigation Officer', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Commit Assignment')

class InvestigationNoteForm(FlaskForm):
    note_type = SelectField('Log Entry Classification', choices=[
        ('Timeline', 'Timeline Milestones'),
        ('Witness Statement', 'Official Witness Statement'),
        ('Arrest Record', 'Arrest Processing Record'),
        ('General', 'General Investigation Journal Entry')
    ], validators=[DataRequired()])
    entry_title = StringField('Entry Title / Activity Name', validators=[DataRequired()])
    statement_body = TextAreaField('Detailed Entry Content / Deposition', validators=[DataRequired()])
    case_status = SelectField('Update Case Operational Status', choices=[
        ('Under Investigation', 'Under Investigation'),
        ('Arrest Made', 'Arrest Made'),
        ('Court Process', 'Case Forwarded to Court Process'),
        ('Closed', 'Close Case / Authorize Archive')
    ], validators=[DataRequired()])
    submit = SubmitField('Append Case Record')

class EvidenceUploadForm(FlaskForm):
    evidence_file = FileField('Select Digital Evidence File', validators=[
        DataRequired(),
        FileAllowed(['jpg', 'jpeg', 'png', 'mp4', 'pdf', 'docx'], 'Authorized Digital Formats Only.')
    ])
    submit = SubmitField('Upload Asset')

class SuspectForm(FlaskForm):
    full_name = StringField('Suspect Full Name', validators=[DataRequired()])
    national_id = StringField('National ID Number', validators=[DataRequired()])
    date_of_birth = DateField('Date of Birth', format='%Y-%m-%d', validators=[DataRequired()])
    gender = SelectField('Gender', choices=[('Male', 'Male'), ('Female', 'Female')], validators=[DataRequired()])
    address = TextAreaField('Last Known Address', validators=[DataRequired()])
    phone_number = StringField('Contact Phone Number', validators=[DataRequired()])
    arrest_history = TextAreaField('Known Prior Criminal Record / Arrest History')
    submit = SubmitField('Register Suspect Profile')

class OfficerForm(FlaskForm):
    email = StringField('Service Email Address', validators=[DataRequired(), Email()])
    password = PasswordField('System Security Access Password', validators=[DataRequired(), Length(min=8)])
    role = SelectField('System Operational Access Role', choices=[
        ('Desk Officer', 'Desk Officer'),
        ('Investigator', 'Investigation Officer'),
        ('OCS', 'Officer Commanding Station (OCS)'),
        ('Administrator', 'System Architect / Administrator')
    ], validators=[DataRequired()])
    station_id = SelectField('Assigned Base Police Station', coerce=int, validators=[DataRequired()])
    service_number = StringField('Official Police Service Number', validators=[DataRequired()])
    rank = SelectField('Official Rank Mandate', choices=[
        ('Constable', 'Police Constable'), ('Corporal', 'Police Corporal'),
        ('Sergeant', 'Police Sergeant'), ('Inspector', 'Inspector of Police'),
        ('Chief Inspector', 'Chief Inspector (OCS)'), ('Superintendent', 'Superintendent')
    ], validators=[DataRequired()])
    full_name = StringField('Officer Legal Full Name', validators=[DataRequired()])
    department = StringField('Assigned Division / Bureau', validators=[DataRequired()])
    phone_number = StringField('Official Communications Mobile', validators=[DataRequired()])
    submit = SubmitField('Commission Officer Profile')


# --- APPLICATION ROUTING SYSTEM ---

@app.route('/')
def home():
    return redirect(url_for('public_portal'))

@app.route('/public-portal', methods=['GET', 'POST'])
def public_portal():
    search_result = None
    ob_num = request.args.get('ob_number')
    if ob_num:
        search_result = OBEntry.query.filter_by(ob_number=ob_num.strip()).first()
        log_audit(f"PUBLIC QUERY: Searched OB Number {ob_num}")
    return render_template('public_portal.html', result=search_result, ob_number=ob_num)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.is_active and user.check_password(form.password.data):
            login_user(user)
            log_audit("AUTH SUCCESS: User Session Established")
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        else:
            log_audit(f"AUTH FAILED: Attempt on account {form.email.data}")
            flash('Invalid official authorization metrics or deactivated account credentials.', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    log_audit("AUTH LOGOUT: Session Explicitly Destroyed")
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    st_id = current_user.officer.station_id
    if current_user.role == 'Administrator':
        ob_query = OBEntry.query
        inv_query = Investigation.query
        off_query = Officer.query
        ev_query = Evidence.query
    else:
        ob_query = OBEntry.query.filter_by(station_id=st_id)
        inv_query = Investigation.query.join(OBEntry).filter(OBEntry.station_id == st_id)
        off_query = Officer.query.filter_by(station_id=st_id)
        ev_query = Evidence.query.join(OBEntry).filter(OBEntry.station_id == st_id)

    stats = {
        'total_ob': ob_query.count(),
        'open_cases': ob_query.filter(OBEntry.status.in_(['Pending Review', 'Under Investigation'])).count(),
        'closed_cases': ob_query.filter_by(status='Closed').count(),
        'under_inv': ob_query.filter_by(status='Under Investigation').count(),
        'arrests_made': ob_query.filter_by(status='Arrest Made').count(),
        'total_officers': off_query.count(),
        'total_evidence': ev_query.count()
    }

    categories = ['Robbery', 'Assault', 'Theft', 'Homicide', 'Fraud', 'Cybercrime', 'Domestic Violence', 'Other']
    cat_counts = [ob_query.filter_by(crime_category=cat).count() for cat in categories]
    
    statuses = ['Pending Review', 'Under Investigation', 'Arrest Made', 'Court Process', 'Closed']
    status_counts = [ob_query.filter_by(status=st).count() for st in statuses]

    months_labels = []
    months_counts = []
    for i in range(5, -1, -1):
        target_date = datetime.utcnow() - timedelta(days=i*30)
        months_labels.append(target_date.strftime('%B %Y'))
        m_start = datetime(target_date.year, target_date.month, 1)
        if target_date.month == 12:
            m_end = datetime(target_date.year + 1, 1, 1)
        else:
            m_end = datetime(target_date.year, target_date.month + 1, 1)
        months_counts.append(ob_query.filter(OBEntry.created_at >= m_start, OBEntry.created_at < m_end).count())

    chart_data = {
        'cat_labels': categories, 'cat_values': cat_counts,
        'status_labels': statuses, 'status_values': status_counts,
        'trend_labels': months_labels, 'trend_values': months_counts
    }

    return render_template('dashboard.html', stats=stats, chart_data=json.dumps(chart_data))

@app.route('/ob')
@login_required
def ob_list():
    st_id = current_user.officer.station_id
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()
    
    query = OBEntry.query if current_user.role == 'Administrator' else OBEntry.query.filter_by(station_id=st_id)
    
    if search:
        query = query.filter((OBEntry.ob_number.ilike(f"%{search}%")) | (OBEntry.complainant_name.ilike(f"%{search}%")) | (OBEntry.national_id.ilike(f"%{search}%")))
    if status_filter:
        query = query.filter_by(status=status_filter)
        
    entries = query.order_by(OBEntry.created_at.desc()).all()
    return render_template('ob_list.html', entries=entries)

@app.route('/ob/new', methods=['GET', 'POST'])
@login_required
@role_required(['Administrator', 'OCS', 'Desk Officer'])
def ob_create():
    form = OBEntryForm()
    if form.validate_on_submit():
        st = current_user.officer.station
        current_year = datetime.utcnow().year
        
        base_count = OBEntry.query.filter(OBEntry.ob_number.like(f"OB/{current_year}/%")).count()
        next_sequence = str(base_count + 1).zfill(6)
        ob_number_string = f"OB/{current_year}/{next_sequence}"

        entry = OBEntry(
            ob_number=ob_number_string,
            station_id=st.id,
            complainant_name=form.complainant_name.data,
            national_id=form.national_id.data,
            phone_number=form.phone_number.data,
            gender=form.gender.data,
            address=form.address.data,
            incident_location=form.incident_location.data,
            crime_category=form.crime_category.data,
            suspect_details=form.suspect_details.data,
            narrative_statement=form.narrative_statement.data,
            recording_officer_id=current_user.officer.id,
            status='Pending Review'
        )
        db.session.add(entry)
        db.session.flush()

        investigation = Investigation(ob_entry_id=entry.id)
        db.session.add(investigation)
        db.session.commit()

        log_audit(f"OB REGISTERED: Generated Record {entry.ob_number}")
        flash(f"Occurrence Entry Serialized Successfully: {entry.ob_number}", 'success')
        return redirect(url_for('ob_list'))
    return render_template('ob_form.html', form=form, title="Create New OB Entry")

@app.route('/ob/<int:entry_id>')
@login_required
def ob_detail(entry_id):
    entry = db.session.get(OBEntry, entry_id)
    if not entry or (current_user.role != 'Administrator' and entry.station_id != current_user.officer.station_id):
        abort(404)
    
    station_officers = Officer.query.filter_by(station_id=current_user.officer.station_id).all()
    assign_form = AssignInvestigatorForm()
    assign_form.investigator_id.choices = [(o.id, f"{o.rank} {o.full_name} ({o.service_number})") for o in station_officers]
    
    note_form = InvestigationNoteForm()
    evidence_form = EvidenceUploadForm()
    
    if entry.investigation and entry.investigation.investigator_id:
        assign_form.investigator_id.data = entry.investigation.investigator_id

    unlinked_suspects = Suspect.query.filter(~Suspect.ob_entries.any(OBEntry.id == entry.id)).all()

    return render_template('ob_detail.html', entry=entry, assign_form=assign_form, note_form=note_form, evidence_form=evidence_form, unlinked_suspects=unlinked_suspects)

@app.route('/ob/<int:entry_id>/assign', methods=['POST'])
@login_required
@role_required(['Administrator', 'OCS'])
def assign_investigator(entry_id):
    entry = db.session.get(OBEntry, entry_id)
    if not entry or (current_user.role != 'Administrator' and entry.station_id != current_user.officer.station_id):
        abort(404)
    
    station_officers = Officer.query.filter_by(station_id=current_user.officer.station_id).all()
    form = AssignInvestigatorForm()
    form.investigator_id.choices = [(o.id, o.full_name) for o in station_officers]
    
    if form.validate_on_submit():
        if not entry.investigation:
            entry.investigation = Investigation(ob_entry_id=entry.id)
        entry.investigation.investigator_id = form.investigator_id.data
        entry.status = 'Under Investigation'
        
        note = InvestigationNote(
            investigation_id=entry.investigation.id,
            note_type='Timeline',
            entry_title='Investigator Assigned Portfolio',
            statement_body=f"Case file transferred to Investigator {entry.investigation.investigator.rank} {entry.investigation.investigator.full_name}."
        )
        db.session.add(note)
        db.session.commit()
        log_audit(f"CASE ASSIGNED: OB {entry.ob_number} assigned to IO ID: {form.investigator_id.data}")
        flash("Investigator assigned and case dossier status promoted to Active.", "success")
    return redirect(url_for('ob_detail', entry_id=entry.id))

@app.route('/ob/<int:entry_id>/note', methods=['POST'])
@login_required
@role_required(['Administrator', 'OCS', 'Investigator'])
def add_investigation_note(entry_id):
    entry = db.session.get(OBEntry, entry_id)
    if not entry or (current_user.role != 'Administrator' and entry.station_id != current_user.officer.station_id):
        abort(404)
        
    form = InvestigationNoteForm()
    if form.validate_on_submit():
        note = InvestigationNote(
            investigation_id=entry.investigation.id,
            note_type=form.note_type.data,
            entry_title=form.entry_title.data,
            statement_body=form.statement_body.data
        )
        entry.status = form.case_status.data
        db.session.add(note)
        db.session.commit()
        log_audit(f"DOSSIER UPDATE: Modified case {entry.ob_number} status to {entry.status}")
        flash("Investigation journal repository extended successfully.", "success")
    return redirect(url_for('ob_detail', entry_id=entry.id))

@app.route('/ob/<int:entry_id>/evidence', methods=['POST'])
@login_required
def upload_evidence(entry_id):
    entry = db.session.get(OBEntry, entry_id)
    if not entry or (current_user.role != 'Administrator' and entry.station_id != current_user.officer.station_id):
        abort(404)
    form = EvidenceUploadForm()
    if form.validate_on_submit():
        file = form.evidence_file.data
        filename = secure_filename(f"{entry.id}_{int(datetime.utcnow().timestamp())}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        evidence = Evidence(
            ob_entry_id=entry.id,
            file_name=filename,
            file_type=file.filename.split('.')[-1].upper(),
            uploaded_by_user_id=current_user.id
        )
        db.session.add(evidence)
        db.session.commit()
        log_audit(f"EVIDENCE ESCROW: Secure upload committed for Case {entry.ob_number}")
        flash("Digital structural evidence element safely secured.", "success")
    return redirect(url_for('ob_detail', entry_id=entry.id))

@app.route('/ob/<int:entry_id>/link-suspect', methods=['POST'])
@login_required
@role_required(['Administrator', 'OCS', 'Investigator'])
def link_suspect(entry_id):
    entry = db.session.get(OBEntry, entry_id)
    suspect_id = request.form.get('suspect_id')
    suspect = db.session.get(Suspect, suspect_id)
    if entry and suspect:
        if entry.station_id == current_user.officer.station_id or current_user.role == 'Administrator':
            entry.suspects.append(suspect)
            db.session.commit()
            log_audit(f"SUSPECT LINKED: Linked suspect {suspect.full_name} to case {entry.ob_number}")
            flash("Suspect mapped to operational file registry.", "success")
    return redirect(url_for('ob_detail', entry_id=entry.id))

@app.route('/ob/<int:entry_id>/unlink-suspect/<int:suspect_id>', methods=['POST'])
@login_required
@role_required(['Administrator', 'OCS', 'Investigator'])
def unlink_suspect(entry_id, suspect_id):
    entry = db.session.get(OBEntry, entry_id)
    suspect = db.session.get(Suspect, suspect_id)
    if entry and suspect:
        if entry.station_id == current_user.officer.station_id or current_user.role == 'Administrator':
            if suspect in entry.suspects:
                entry.suspects.remove(suspect)
                db.session.commit()
                log_audit(f"SUSPECT UNLINKED: Disconnected suspect {suspect.full_name} from case {entry.ob_number}")
                flash("Suspect profile safely isolated and unlinked from active file record.", "success")
    return redirect(url_for('ob_detail', entry_id=entry.id))


# --- SUSPECT REGISTRY LOGISTICS ---

@app.route('/suspects', methods=['GET', 'POST'])
@login_required
def suspect_registry():
    form = SuspectForm()
    if form.validate_on_submit():
        suspect = Suspect(
            full_name=form.full_name.data,
            national_id=form.national_id.data,
            date_of_birth=form.date_of_birth.data,
            gender=form.gender.data,
            address=form.address.data,
            phone_number=form.phone_number.data,
            arrest_history=form.arrest_history.data
        )
        db.session.add(suspect)
        db.session.commit()
        log_audit(f"SUSPECT PROFILE GENERATED: Identity record {suspect.national_id}")
        flash("Criminal suspect infrastructure profile mapped successfully.", "success")
        return redirect(url_for('suspect_registry'))
    
    suspects = Suspect.query.order_by(Suspect.full_name.asc()).all()
    return render_template('suspect_registry.html', suspects=suspects, form=form)


# --- OFFICERS & STATIONS MANAGEMENT ---

@app.route('/officers', methods=['GET', 'POST'])
@login_required
@role_required(['Administrator'])
def officer_registry():
    form = OfficerForm()
    form.station_id.choices = [(s.id, s.name) for s in Station.query.order_by(Station.name.asc()).all()]
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash("Account operational criteria conflict: Email exists.", "danger")
            return redirect(url_for('officer_registry'))
            
        user = User(email=form.email.data, role=form.role.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        
        officer = Officer(
            user_id=user.id,
            station_id=form.station_id.data,
            service_number=form.service_number.data,
            rank=form.rank.data,
            full_name=form.full_name.data,
            department=form.department.data,
            phone_number=form.phone_number.data
        )
        db.session.add(officer)
        db.session.commit()
        log_audit(f"OFFICER COMMISSIONED: Added Service Account {officer.service_number}")
        flash("New Active Service Command Profile generated successfully.", "success")
        return redirect(url_for('officer_registry'))
        
    officers = Officer.query.all()
    return render_template('officer_registry.html', officers=officers, form=form)

@app.route('/officers/<int:off_id>/toggle', methods=['POST'])
@login_required
@role_required(['Administrator'])
def toggle_officer(off_id):
    off = db.session.get(Officer, off_id)
    if off and off.user_id != current_user.id:
        off.user.is_active = not off.user.is_active
        db.session.commit()
        log_audit(f"OFFICER STATUS MUTATION: Account identity toggled for ID {off.service_number}")
        flash("Identity execution credentials access mapped successfully.", "success")
    return redirect(url_for('officer_registry'))

@app.route('/audit-logs')
@login_required
@role_required(['Administrator', 'OCS'])
def view_audit_logs():
    st_id = current_user.officer.station_id
    if current_user.role == 'Administrator':
        logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(500).all()
    else:
        logs = AuditLog.query.filter_by(station_id=st_id).order_by(AuditLog.timestamp.desc()).limit(200).all()
    return render_template('audit_logs.html', logs=logs)


# --- FASTAPI REST ROUTING SUBSYSTEM ---

router = APIRouter(prefix="/api/v1/police", tags=["National Police Management REST Components"])

class BookingPayload(BaseModel):
    prisoner_number: str
    full_name: str
    dob: date
    gender: str
    arresting_officer: str
    ob_number: str
    cell_id: int
    bed_number: str

@router.post("/custody/book-prisoner", status_code=fastapi_status.HTTP_201_CREATED)
def process_prisoner_booking(payload: BookingPayload, db_session: Session = Depends(lambda: db.session)):
    cell = db_session.query(Cell).filter(Cell.id == payload.cell_id).first()
    if not cell:
        raise HTTPException(status_code=404, detail="The designated cell assignment target was not found.")
        
    if cell.current_occupancy >= cell.capacity:
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST, 
            detail=f"Capacity Alert: Target Cell {cell.cell_number} is full ({cell.current_occupancy}/{cell.capacity})."
        )
        
    new_prisoner = Prisoner(**payload.dict(), custody_status="In Custody")
    cell.current_occupancy += 1
    if cell.current_occupancy >= cell.capacity:
        cell.status = CellStatus.FULL
    else:
        cell.status = CellStatus.OCCUPIED
        
    db_session.add(new_prisoner)
    db_session.commit()
    return {"status": "Success", "message": "Prisoner registered and safely assigned to holding space allocation."}

@router.post("/custody/release-prisoner/{prisoner_id}")
def process_prisoner_release(prisoner_id: int, authorizing_officer: str, reason: str, db_session: Session = Depends(lambda: db.session)):
    prisoner = db_session.query(Prisoner).filter(Prisoner.id == prisoner_id).first()
    if not prisoner:
        raise HTTPException(status_code=404, detail="Targeted detainee reference index not found.")
        
    unreturned_items = db_session.query(PrisonerProperty).filter(
        PrisonerProperty.prisoner_id == prisoner_id,
        PrisonerProperty.return_status == False
    ).count()
    
    if unreturned_items > 0:
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST,
            detail=f"Release Denied: Detainee has {unreturned_items} unreturned property items in inventory storage."
        )

    prisoner.custody_status = "Released"
    if prisoner.cell:
        prisoner.cell.current_occupancy = max(0, prisoner.cell.current_occupancy - 1)
        prisoner.cell.status = CellStatus.AVAILABLE if prisoner.cell.current_occupancy < prisoner.cell.capacity else CellStatus.FULL

    new_release = ReleaseRecord(
        release_number=f"REL-{prisoner.prisoner_number}",
        prisoner_id=prisoner.id,
        release_reason=reason,
        authorizing_officer=authorizing_officer,
        property_returned_status=True
    )
    db_session.add(new_release)
    db_session.commit()
    return {"status": "Success", "message": "Detainee properties cleared and release documentation initialized."}


# --- REPORT ENGINE AND PDF COMPILER UTILITIES ---

@app.route('/reports')
@login_required
def reports_dashboard():
    return render_template('reports.html')

@app.route('/reports/export/excel')
@login_required
def export_excel_report():
    st_id = current_user.officer.station_id
    query = OBEntry.query if current_user.role == 'Administrator' else OBEntry.query.filter_by(station_id=st_id)
    entries = query.order_by(OBEntry.created_at.desc()).all()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Station Occurrence Book Digest"
    
    headers = ["OB Number", "Timestamp", "Complainant Name", "National ID", "Category", "Incident Location", "Status"]
    ws.append(headers)
    
    for entry in entries:
        ws.append([
            entry.ob_number,
            entry.created_at.strftime('%Y-%m-%d %H:%M'),
            entry.complainant_name,
            entry.national_id,
            entry.crime_category,
            entry.incident_location,
            entry.status
        ])
        
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    log_audit("REPORT COMPILED: Exported Comprehensive Excel Dataset Ledger")
    return send_file(output, download_name=f"OB_Ledger_{date.today()}.xlsx", as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route('/ob/<int:entry_id>/abstract-pdf')
@login_required
def export_abstract_pdf(entry_id):
    entry = db.session.get(OBEntry, entry_id)
    if not entry or (current_user.role != 'Administrator' and entry.station_id != current_user.officer.station_id):
        abort(404)
        
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'],
        fontName='Helvetica-Bold', fontSize=18, leading=22,
        textColor=colors.HexColor('#0B132B'), alignment=1, spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        'DocSub', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=10, leading=14,
        textColor=colors.HexColor('#E5A93C'), alignment=1, spaceAfter=15
    )
    section_heading = ParagraphStyle(
        'SectionHeading', parent=styles['Heading2'],
        fontName='Helvetica-Bold', fontSize=12, leading=16,
        textColor=colors.HexColor('#1C2541'), spaceBefore=12, spaceAfter=6
    )
    body_style = ParagraphStyle(
        'TableBody', parent=styles['Normal'],
        fontName='Helvetica', fontSize=10, leading=14,
        textColor=colors.HexColor('#000000') # Solid black dashboard text rules preserved
    )
    bold_body_style = ParagraphStyle(
        'TableBodyBold', parent=body_style,
        fontName='Helvetica-Bold'
    )

    story.append(Paragraph("POLICE SERVICE DEPLOYMENT PORTAL", title_style))
    story.append(Paragraph(f"OFFICIAL OCCURRENCE BOOK ABSTRACT // STATION: {entry.station.name.upper()}", subtitle_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph("1. CASE METRICS & TRACKING REFERENCE", section_heading))
    meta_data = [
        [Paragraph("Occurrence Book Num:", bold_body_style), Paragraph(entry.ob_number, body_style)],
        [Paragraph("Registration Date/Time:", bold_body_style), Paragraph(entry.created_at.strftime('%Y-%m-%d %H:%M UTC'), body_style)],
        [Paragraph("Operational Status:", bold_body_style), Paragraph(entry.status, body_style)],
        [Paragraph("Crime Classification:", bold_body_style), Paragraph(entry.crime_category, body_style)]
    ]
    t1 = Table(meta_data, colWidths=[150, 380])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8F9FA')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(t1)
    story.append(Spacer(1, 10))

    story.append(Paragraph("2. COMPLAINANT STATEMENT DATA MATRIX", section_heading))
    complainant_data = [
        [Paragraph("Full Name:", bold_body_style), Paragraph(entry.complainant_name, body_style)],
        [Paragraph("National ID/Passport ID:", bold_body_style), Paragraph(entry.national_id, body_style)],
        [Paragraph("Contact Number:", bold_body_style), Paragraph(entry.phone_number, body_style)],
        [Paragraph("Residential Address:", bold_body_style), Paragraph(entry.address, body_style)]
    ]
    t2 = Table(complainant_data, colWidths=[150, 380])
    t2.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t2)
    story.append(Spacer(1, 10))

    story.append(Paragraph("3. DETAILED NARRATIVE DEPOSITION & EVIDENCE INCIDENT REPORT", section_heading))
    narrative_p = Paragraph(entry.narrative_statement, body_style)
    t3 = Table([[narrative_p]], colWidths=[530])
    t3.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8F9FA')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(t3)
    story.append(Spacer(1, 15))

    qr_data = f"OB_VERIFY:{entry.ob_number}|STATION:{entry.station.code}|STATUS:{entry.status}"
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    qr_bytes = io.BytesIO()
    qr_img.save(qr_bytes, format='PNG')
    qr_bytes.seek(0)
    rl_qr_img = RLImage(qr_bytes, width=70, height=70)

    sig_text = f"Compiled By: {entry.recording_officer.rank} {entry.recording_officer.full_name}<br/>Service Number: {entry.recording_officer.service_number}<br/>Generated On: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    footer_table_data = [
        [Paragraph(sig_text, body_style), rl_qr_img]
    ]
    footer_table = Table(footer_table_data, colWidths=[450, 80])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    
    story.append(KeepTogether([
        Spacer(1, 10),
        Paragraph("4. SECURE VERIFICATION FOOTPRINT", section_heading),
        footer_table
    ]))

    doc.build(story)
    buffer.seek(0)
    log_audit(f"PDF GENERATED: Abstract compiled for {entry.ob_number}")
    return send_file(buffer, download_name=f"Abstract_{entry.ob_number.replace('/', '_')}.pdf", as_attachment=True, mimetype="application/pdf")


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)