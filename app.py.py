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
from sqlalchemy.orm import relationship, Session # <-- IMPORTED Session FIXED HERE

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


# --- CORE PRISONER LEDGER ---
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
    visitor_relationship = Column(String(50), nullable=False) 
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
    id = Column(Integer, primary_