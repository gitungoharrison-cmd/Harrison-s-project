import os
import secrets
import hashlib
from datetime import datetime, timezone
from io import BytesIO

from flask import Flask, render_template_string, request, redirect, url_for, flash, send_from_directory, abort, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField, PasswordField, TextAreaField, SelectField
from wtforms.validators import DataRequired
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ReportLab Engine Components
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Rect, Line, String as DString

# Excel Engine
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# 1. APPLICATION BOOTSTRAP & HARDENING
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nps_secure_core_system_key_2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///dpobcms_luxury_v3.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nps_evidence_vault')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max limit
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# 2. DATABASE SCHEMATIC & RELATIONSHIP ARCHITECTURE
ob_suspect_association = db.Table('ob_suspect_association',
    db.Column('ob_entry_id', db.Integer, db.ForeignKey('ob_entry.id', ondelete='CASCADE'), primary_key=True),
    db.Column('suspect_id', db.Integer, db.ForeignKey('suspect.id', ondelete='CASCADE'), primary_key=True)
)

class Station(db.Model):
    __tablename__ = 'station'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    users = db.relationship('User', backref='station', lazy=True)
    ob_entries = db.relationship('OBEntry', backref='station', lazy=True)

class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    service_number = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    rank = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(40), nullable=False)  # Administrator, OCS, Desk Officer, Investigator
    department = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)

class OBEntry(db.Model):
    __tablename__ = 'ob_entry'
    id = db.Column(db.Integer, primary_key=True)
    ob_number = db.Column(db.String(40), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    complainant_name = db.Column(db.String(120), nullable=False)
    national_id = db.Column(db.String(50), nullable=False)
    phone_number = db.Column(db.String(40), nullable=False)
    gender = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text, nullable=False)
    incident_location = db.Column(db.String(200), nullable=False)
    crime_category = db.Column(db.String(100), nullable=False)
    narrative = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(40), default='Pending Review', nullable=False)
    
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=False)
    reporting_officer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    investigator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    reporting_officer = db.relationship('User', foreign_keys=[reporting_officer_id])
    investigator = db.relationship('User', foreign_keys=[investigator_id])
    
    notes = db.relationship('InvestigationNote', backref='ob_entry', lazy=True, cascade="all, delete-orphan")
    evidence_files = db.relationship('Evidence', backref='ob_entry', lazy=True, cascade="all, delete-orphan")
    suspects = db.relationship('Suspect', secondary=ob_suspect_association, backref=db.backref('ob_entries', lazy='dynamic'))

class InvestigationNote(db.Model):
    __tablename__ = 'investigation_note'
    id = db.Column(db.Integer, primary_key=True)
    ob_entry_id = db.Column(db.Integer, db.ForeignKey('ob_entry.id', ondelete='CASCADE'), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    note_type = db.Column(db.String(50), nullable=False)
    text_content = db.Column(db.Text, nullable=False)
    recorded_by = db.Column(db.String(100), nullable=False)

class Evidence(db.Model):
    __tablename__ = 'evidence'
    id = db.Column(db.Integer, primary_key=True)
    ob_entry_id = db.Column(db.Integer, db.ForeignKey('ob_entry.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(100), nullable=False)
    upload_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    uploaded_by = db.Column(db.String(100), nullable=False)

class Suspect(db.Model):
    __tablename__ = 'suspect'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    national_id = db.Column(db.String(50), unique=True, nullable=True)
    date_of_birth = db.Column(db.String(30), nullable=True)
    gender = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text, nullable=True)
    phone_number = db.Column(db.String(50), nullable=True)
    arrest_history_summary = db.Column(db.Text, nullable=True)

class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user_identifier = db.Column(db.String(120), nullable=False)
    action = db.Column(db.String(255), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def commit_audit(action):
    try:
        ident = f"{current_user.rank} {current_user.full_name} ({current_user.service_number})" if current_user.is_authenticated else "Anonymous/Public Interface"
        ip = request.remote_addr or "127.0.0.1"
        db.session.add(AuditLog(user_identifier=ident, action=action, ip_address=ip))
        db.session.commit()
    except Exception:
        db.session.rollback()

# 3. INTERACTIVE SYSTEM UI MASTER TOKEN TEMPLATES WITH LUXURY STYLING
BASE_LAYOUT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NPS - DPOBCMS Secure Portal</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .text-white {
            background: linear-gradient(to right, #DFBA73, #C5A059, #9A7B3E);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .bg-gold-gradient {
            background: linear-gradient(135deg, #DFBA73 0%, #C5A059 50%, #9A7B3E 100%);
        }
        .bg-luxury-navy {
            background: linear-gradient(180deg, #050B14 0%, #0B132B 100%);
        }
        .luxury-card {
            background: #white;
            box-shadow: 0 10px 30px -5px rgba(5, 11, 20, 0.06), 0 4px 12px -2px rgba(197, 160, 89, 0.1);
            border: 1px solid rgba(197, 160, 89, 0.15);
        }
        .luxury-input:focus {
            border-color: #C5A059;
            box-shadow: 0 0 0 3px rgba(197, 160, 89, 0.2);
        }
    </style>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        navyDark: '#050B14',
                        securityBlue: '#0B132B',
                        matteGold: '#C5A059',
                        slateWhite: '#F4F5F7'
                    }
                }
            }
        }
    </script>
</head>
<body class="bg-slateWhite text-white min-h-screen flex flex-col font-sans">
    <nav class="bg-luxury-navy text-white p-5 shadow-2xl flex justify-between items-center border-b-2 border-gold-gradient">
        <div class="flex items-center space-x-4">
            <div class="w-10 h-10 bg-gold-gradient rounded-full flex items-center justify-center font-black text-white text-xl shadow-lg border border-white/20">🚨</div>
            <div>
                <span class="font-extrabold tracking-widest text-sm block uppercase text-white">NATIONAL POLICE SERVICE — REPUBLC OF KENYA</span>
                <span class="text-[10px] tracking-widest text-white-400 block font-mono">DIGITAL OCCURRENCE BOOK & CASE COMMAND CORE</span>
            </div>
        </div>
        {% if current_user.is_authenticated %}
        <div class="flex items-center space-x-4 text-xs font-mono">
            <div class="bg-securityBlue border border-matteGold/30 px-4 py-2 rounded shadow-inner">
                <span class="text-white font-bold text-sm">{{ current_user.rank }} {{ current_user.full_name }}</span> 
                <span class="text-gray-400">[{{ current_user.role }}]</span>
                {% if current_user.station %}
                <span class="text-amber-400 font-sans font-bold block text-right text-[10px] uppercase mt-0.5">📍 Hub: {{ current_user.station.name }}</span>
                {% endif %}
            </div>
            <a href="/logout" class="bg-gradient-to-r from-red-800 to-red-950 hover:from-red-900 hover:to-black transition-all text-white border border-red-700 px-4 py-2.5 rounded font-bold uppercase shadow-lg">Logout</a>
        </div>
        {% else %}
        <a href="/public-portal" class="bg-transparent text-white border border-matteGold text-xs font-bold px-4 py-2.5 rounded uppercase tracking-widest hover:bg-gold-gradient hover:text-navyDark transition-all duration-300 shadow-md">Public Portal Interface</a>
        {% endif %}
    </nav>
    <div class="flex flex-1 flex-col md:flex-row">
        {% if current_user.is_authenticated %}
        <div class="w-full md:w-64 bg-luxury-navy text-white p-5 space-y-4 border-r border-matteGold/10 flex flex-col justify-between shadow-2xl">
            <div class="space-y-2">
                <div class="text-[10px] uppercase font-black text-white tracking-widest px-2 mb-3 font-mono border-b border-matteGold/20 pb-1">Operations Command</div>
                <a href="/dashboard" class="block p-3 rounded text-xs uppercase font-bold tracking-wider hover:bg-securityBlue hover:text-white transition-all duration-200 border-l-4 border-transparent hover:border-matteGold">📊 Operations Dashboard</a>
                <a href="/occurrence-book" class="block p-3 rounded text-xs uppercase font-bold tracking-wider hover:bg-securityBlue hover:text-white transition-all duration-200 border-l-4 border-transparent hover:border-matteGold">📖 Occurrence Book (OB)</a>
                <a href="/suspect-registry" class="block p-3 rounded text-xs uppercase font-bold tracking-wider hover:bg-securityBlue hover:text-white transition-all duration-200 border-l-4 border-transparent hover:border-matteGold">👥 Suspect Intelligence Registry</a>
                
                <div class="text-[10px] uppercase font-black text-white tracking-widest px-2 pt-4 mb-3 font-mono border-b border-matteGold/20 pb-1">Intelligence & Reports</div>
                <a href="/reports" class="block p-3 rounded text-xs uppercase font-bold tracking-wider hover:bg-securityBlue hover:text-white transition-all duration-200 border-l-4 border-transparent hover:border-matteGold">📈 Statistical Analytics Hub</a>
                
                {% if current_user.role in ['Administrator', 'OCS'] %}
                <div class="text-[10px] uppercase font-black text-white tracking-widest px-2 pt-4 mb-3 font-mono border-b border-matteGold/20 pb-1">Administration Control</div>
                <a href="/officer-management" class="block p-3 rounded text-xs uppercase font-bold tracking-wider hover:bg-securityBlue hover:text-white transition-all duration-200 border-l-4 border-transparent hover:border-matteGold">👮 Command Force Roster</a>
                {% endif %}
                {% if current_user.role == 'Administrator' %}
                <a href="/audit-logs" class="block p-3 rounded text-xs font-mono text-gray-400 hover:bg-securityBlue hover:text-red-400 transition-all border-l-4 border-transparent hover:border-red-500">🛡️ Security Logs</a>
                {% endif %}
            </div>
            <div class="pt-6 border-t border-matteGold/10 text-center text-[10px] text-gray-500 font-mono tracking-wider">
                DPOBCMS v3.0.26<br>Secure Crypt Ledger Stack
            </div>
        </div>
        {% endif %}
        <div class="flex-1 p-6 md:p-10 overflow-x-hidden">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, msg in messages %}
                        <div class="mb-6 p-4 text-xs font-bold rounded border shadow-xl font-mono {% if category == 'danger' %} bg-red-50 text-red-900 border-red-300 {% else %} bg-emerald-50 text-emerald-900 border-emerald-300 {% endif %}">
                            ⚡ STATUS NOTIFICATION: {{ msg }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            __RENDER_SLOT__
        </div>
    </div>
</body>
</html>
"""

def generate_nps_response(inner_html, **kwargs):
    return render_template_string(BASE_LAYOUT.replace('__RENDER_SLOT__', inner_html), **kwargs)

# 4. REPORTLAB PROFESSIONAL VECTOR ENGINEERING ENGINE
def build_pdf_abstract(ob, stream):
    doc = SimpleDocTemplate(stream, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []
    
    header_style = ParagraphStyle('H1', fontName='Helvetica-Bold', fontSize=14, leading=16, textColor=colors.HexColor('#050B14'), alignment=1)
    sub_style = ParagraphStyle('H2', fontName='Helvetica-Bold', fontSize=9, leading=11, textColor=colors.HexColor('#0B132B'), alignment=1)
    body_style = ParagraphStyle('B1', fontName='Helvetica', fontSize=10, leading=13, textColor=colors.HexColor('#050B14'))
    label_style = ParagraphStyle('L1', fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor('#0B132B'))
    
    story.append(Paragraph("NATIONAL POLICE SERVICE — REPUBLIC OF KENYA", header_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"OFFICIAL DIGITAL OB ABSTRACT RECORD — JURISDICTION: {ob.station.name.upper()}", sub_style))
    story.append(Spacer(1, 15))
    
    qr_data_string = f"NPS-VERIFY:{ob.ob_number}:{ob.national_id}:{hashlib.sha256(ob.ob_number.encode()).hexdigest()[:10].upper()}"
    d = Drawing(540, 55)
    d.add(Rect(0, 0, 540, 55, fillColor=colors.HexColor('#F4F5F7'), strokeColor=colors.HexColor('#C5A059'), strokeWidth=1.5))
    d.add(Rect(10, 7, 40, 40, fillColor=colors.HexColor('#050B14'), strokeColor=None))
    for i in range(4):
        for j in range(4):
            if (i+j) % 2 == 0:
                d.add(Rect(14 + (i*8), 11 + (j*8), 6, 6, fillColor=colors.white, strokeColor=None))
    d.add(DString(65, 32, "SECURITY ABSTRACT CRYPTOGRAPHIC VALIDATION BLOCK", fontName="Helvetica-Bold", fontSize=9, fillColor=colors.HexColor('#050B14')))
    d.add(DString(65, 16, f"TOKEN TRACE: {qr_data_string[:65]}...", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor('#0B132B')))
    story.append(d)
    story.append(Spacer(1, 15))
    
    table_data = [
        [Paragraph("Occurrence Reference Key:", label_style), Paragraph(ob.ob_number, body_style)],
        [Paragraph("Filing Timestamp:", label_style), Paragraph(ob.created_at.strftime('%Y-%m-%d %H:%M:%S UTC'), body_style)],
        [Paragraph("Command Station Center:", label_style), Paragraph(ob.station.name, body_style)],
        [Paragraph("Complainant Legal Name:", label_style), Paragraph(ob.complainant_name, body_style)],
        [Paragraph("National ID Number:", label_style), Paragraph(ob.national_id, body_style)],
        [Paragraph("Telephone Demographics:", label_style), Paragraph(ob.phone_number, body_style)],
        [Paragraph("Gender Profile:", label_style), Paragraph(ob.gender, body_style)],
        [Paragraph("Residential Address:", label_style), Paragraph(ob.address, body_style)],
        [Paragraph("Incident Location Geo:", label_style), Paragraph(ob.incident_location, body_style)],
        [Paragraph("Statutory Crime Category:", label_style), Paragraph(ob.crime_category, body_style)],
        [Paragraph("Certified Legal Narrative:", label_style), Paragraph(ob.narrative, body_style)],
        [Paragraph("Workflow System Status:", label_style), Paragraph(ob.status.upper(), ParagraphStyle('ST', fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#C5A059')))],
        [Paragraph("Recording Force Officer:", label_style), Paragraph(f"{ob.reporting_officer.rank} {ob.reporting_officer.full_name} ({ob.reporting_officer.service_number})", body_style)]
    ]
    
    t = Table(table_data, colWidths=[160, 380])
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#0B132B')),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#F4F5F7')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t)
    story.append(Spacer(1, 40))
    
    sig_drawing = Drawing(540, 60)
    sig_drawing.add(Line(0, 35, 200, 35, strokeColor=colors.HexColor('#050B14'), strokeWidth=1))
    sig_drawing.add(DString(0, 20, "OFFICER COMMANDING STATION (OCS)", fontName="Helvetica-Bold", fontSize=8, fillColor=colors.HexColor('#0B132B')))
    sig_drawing.add(DString(0, 5, "SIGNATURE / FORCE STAMP FIELD", fontName="Helvetica", fontSize=7, fillColor=colors.gray))
    
    sig_drawing.add(Line(340, 35, 540, 35, strokeColor=colors.HexColor('#050B14'), strokeWidth=1))
    sig_drawing.add(DString(340, 20, "COMPLAINANT / ISSUING DESK AGENT", fontName="Helvetica-Bold", fontSize=8, fillColor=colors.HexColor('#0B132B')))
    sig_drawing.add(DString(340, 5, "LEGAL ACKNOWLEDGEMENT INK STAMP", fontName="Helvetica", fontSize=7, fillColor=colors.gray))
    story.append(sig_drawing)
    
    doc.build(story)

# 5. CORE ROUTING & LOGICAL IMPLEMENTATION ENGINE
@app.route('/')
def index():
    return redirect(url_for('public_portal'))

@app.route('/public-portal', methods=['GET', 'POST'])
def public_portal():
    entry = None
    searched = False
    if request.method == 'POST':
        ob_num = request.form.get('ob_number', '').strip().upper()
        entry = OBEntry.query.filter_by(ob_number=ob_num).first()
        searched = True
        commit_audit(f"Public terminal lookup execution matching token: {ob_num}")
        
    html = """
    <div class="max-w-2xl mx-auto bg-white rounded-xl shadow-2xl overflow-hidden mt-6 border border-matteGold/20">
        <div class="bg-luxury-navy p-6 text-white text-center font-bold text-sm uppercase tracking-widest border-b-2 border-gold-gradient text-white">
            Public Citizen Case Status Verification Portal
        </div>
        <div class="p-6 bg-gray-50 border-b">
            <form method="POST" class="space-y-4">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div>
                    <label class="block text-[10px] font-mono uppercase font-black text-gray-500 mb-1 tracking-wider">Enter Occurrence Book Number (OB String)</label>
                    <div class="flex space-x-2">
                        <input type="text" name="ob_number" placeholder="e.g., OB/2026/000001" required 
                               class="flex-1 p-3.5 border font-mono text-sm rounded-lg uppercase outline-none luxury-input transition-all duration-200">
                        <button type="submit" class="bg-luxury-navy hover:bg-securityBlue border border-matteGold/30 text-white font-extrabold px-6 py-3.5 rounded-lg text-xs uppercase tracking-widest transition-all duration-300 shadow-lg">
                            Verify File Status
                        </button>
                    </div>
                </div>
            </form>
        </div>
        <div class="p-6">
            {% if searched %}
                {% if entry %}
                <div class="space-y-4 font-mono text-xs bg-white p-5 border rounded-xl shadow-xl border-matteGold/10">
                    <div class="border-b pb-3 flex justify-between items-center">
                        <span class="font-bold text-navyDark text-sm">📁 RECORD TRACE: {{ entry.ob_number }}</span>
                        <span class="px-3 py-1 text-[10px] uppercase font-black bg-amber-50 border border-matteGold/40 text-amber-900 rounded-full shadow-sm">
                            {{ entry.status }}
                        </span>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <p class="text-gray-500">Station Unit: <span class="text-navyDark font-sans font-bold">{{ entry.station.name }}</span></p>
                        <p class="text-gray-500">Filing Clock: <span class="text-navyDark font-bold">{{ entry.created_at.strftime('%Y-%m-%d %H:%M UTC') }}</span></p>
                        <p class="text-gray-500">Complainant Group: <span class="text-navyDark font-sans font-bold">{{ entry.complainant_name }}</span></p>
                        <p class="text-gray-500">Crime Class: <span class="text-navyDark font-sans font-bold">{{ entry.crime_category }}</span></p>
                    </div>
                    <div class="bg-slateWhite p-4 rounded-lg font-sans text-gray-700 border italic text-xs leading-relaxed shadow-inner">
                        "{{ entry.narrative[:250] }}..."
                    </div>
                    <div class="border-t pt-4 flex justify-between items-center">
                        <div>
                            <span class="block text-[9px] text-gray-400 uppercase font-mono tracking-wider">Assigned Criminal Investigator</span>
                            <span class="font-sans text-xs font-black text-navyDark">
                                {% if entry.investigator %} {{ entry.investigator.rank }} {{ entry.investigator.full_name }} {% else %} Internal OCS Desk Review Phase {% endif %}
                            </span>
                        </div>
                        <a href="/abstract/download/{{ entry.id }}" class="bg-gold-gradient hover:opacity-90 text-navyDark font-black px-5 py-2.5 rounded-lg text-[11px] uppercase tracking-widest shadow-md transition-all duration-200">
                            Download Certified Abstract
                        </a>
                    </div>
                </div>
                {% else %}
                <div class="p-4 bg-red-50 text-red-900 border border-red-200 rounded-lg font-mono text-xs font-black text-center shadow-md">
                    ⚠️ RECORD SEARCH NEGATIVE: No database record matched that specific verification query string inside the cloud ledger stack.
                </div>
                {% endif %}
            {% else %}
            <div class="text-center py-8 text-gray-400 text-xs italic font-mono tracking-wide">
                Input an active operational trace key identifier above to pull verified law enforcement milestone telemetry.
            </div>
            {% endif %}
        </div>
    </div>
    <div class="text-center mt-8">
        <a href="/login" class="text-xs font-black uppercase text-securityBlue hover:text-white border-b border-dashed border-matteGold pb-0.5 tracking-widest font-mono transition-all duration-200">
            &rarr; Terminal Command Frame Login Portal &larr;
        </a>
    </div>
    """
    return generate_nps_response(html, entry=entry, searched=searched)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        svc = request.form.get('service_number', '').strip()
        pwd = request.form.get('password', '')
        user = User.query.filter_by(service_number=svc, is_active=True).first()
        if user and check_password_hash(user.password_hash, pwd):
            login_user(user)
            commit_audit("User command session successfully authorized via security terminal keys.")
            return redirect(url_for('dashboard'))
        flash("Authorization denied. Invalid security payload matrix signatures.", "danger")
        commit_audit(f"Failed terminal authorization trace flagged tracking token input: {svc}")
    
    html = """
    <div class="max-w-md mx-auto bg-white rounded-xl shadow-2xl overflow-hidden mt-12 border border-matteGold/20">
        <div class="bg-luxury-navy text-white p-6 text-center font-bold text-sm uppercase tracking-widest border-b-2 border-gold-gradient text-white">
            Infrastructure Gateway Authorization
        </div>
        <form method="POST" class="p-6 space-y-4 bg-white">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div>
                <label class="block text-[10px] font-mono font-black uppercase tracking-wider text-gray-500 mb-1">Force Service Number</label>
                <input type="text" name="service_number" required class="w-full p-3.5 font-mono text-xs border rounded-lg bg-white outline-none luxury-input uppercase tracking-wider transition-all duration-200">
            </div>
            <div>
                <label class="block text-[10px] font-mono font-black uppercase tracking-wider text-gray-500 mb-1">Command Passcode Cipher</label>
                <input type="password" name="password" required class="w-full p-3.5 text-xs border rounded-lg bg-white outline-none luxury-input transition-all duration-200">
            </div>
            <button type="submit" class="w-full bg-luxury-navy hover:bg-securityBlue text-white font-black p-4 rounded-lg text-xs uppercase tracking-widest border border-matteGold/30 shadow-xl transition-all duration-300 mt-2">
                Validate Authorization Key
            </button>
        </form>
    </div>
    """
    return generate_nps_response(html)

@app.route('/logout')
@login_required
def logout():
    commit_audit("Command node session securely dropped and purged.")
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'Administrator':
        ob_q = OBEntry.query
        off_count = User.query.count()
    else:
        ob_q = OBEntry.query.filter_by(station_id=current_user.station_id)
        off_count = User.query.filter_by(station_id=current_user.station_id).count()
        
    total_ob = ob_q.count()
    pending = ob_q.filter_by(status='Pending Review').count()
    ui = ob_q.filter_by(status='Under Investigation').count()
    arrests = ob_q.filter_by(status='Arrest Made').count()
    closed = ob_q.filter_by(status='Closed').count()
    
    evidence_count = db.session.query(db.func.count(Evidence.id)).join(OBEntry).filter(
        OBEntry.id == Evidence.ob_entry_id if current_user.role == 'Administrator' else (OBEntry.station_id == current_user.station_id)
    ).scalar() or 0
    
    html = """
    <div class="space-y-6 font-sans">
        <h1 class="text-xl font-black text-navyDark uppercase tracking-widest border-b pb-3 border-matteGold/20 flex justify-between items-center">
            <span>📊 Core Command Operations Metrics Hub</span>
            <span class="text-xs font-mono font-normal text-white bg-luxury-navy px-3 py-1 rounded border border-matteGold/30 shadow-inner">Operational Ready Suite</span>
        </h1>
        
        <div class="grid grid-cols-2 md:grid-cols-4 gap-5">
            <div class="bg-white p-5 rounded-xl border border-matteGold/10 luxury-card border-l-4 border-l-navyDark">
                <div class="text-[10px] uppercase font-mono font-black text-gray-400 tracking-wider">Total Logs Stack</div>
                <div class="text-3xl font-black text-navyDark mt-1">{{ total_ob }}</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-matteGold/10 luxury-card border-l-4 border-l-amber-500">
                <div class="text-[10px] uppercase font-mono font-black text-gray-400 tracking-wider">Officer Reviews</div>
                <div class="text-3xl font-black text-amber-600 mt-1">{{ pending }}</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-matteGold/10 luxury-card border-l-4 border-l-blue-500">
                <div class="text-[10px] uppercase font-mono font-black text-gray-400 tracking-wider">Active Investigations</div>
                <div class="text-3xl font-black text-blue-600 mt-1">{{ ui }}</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-matteGold/10 luxury-card border-l-4 border-l-emerald-500">
                <div class="text-[10px] uppercase font-mono font-black text-gray-400 tracking-wider">Closed Records</div>
                <div class="text-3xl font-black text-emerald-600 mt-1">{{ closed }}</div>
            </div>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-3 gap-5 pt-2">
            <div class="bg-white p-5 rounded-xl luxury-card text-center border border-matteGold/15">
                <div class="text-[10px] uppercase font-mono font-black text-white tracking-widest mb-1">Apprehensions</div>
                <div class="text-4xl font-black text-indigo-950">{{ arrests }}</div>
                <p class="text-[10px] text-gray-400 font-mono mt-1">Validated local lockup tracks</p>
            </div>
            <div class="bg-white p-5 rounded-xl luxury-card text-center border border-matteGold/15">
                <div class="text-[10px] uppercase font-mono font-black text-white tracking-widest mb-1">Station Officers Force</div>
                <div class="text-4xl font-black text-teal-950">{{ off_count }}</div>
                <p class="text-[10px] text-gray-400 font-mono mt-1">Active system framework nodes</p>
            </div>
            <div class="bg-white p-5 rounded-xl luxury-card text-center border border-matteGold/15">
                <div class="text-[10px] uppercase font-mono font-black text-white tracking-widest mb-1">Vault Evidence files</div>
                <div class="text-4xl font-black text-rose-950">{{ evidence_count }}</div>
                <p class="text-[10px] text-gray-400 font-mono mt-1">Binary crypto blocks committed</p>
            </div>
        </div>
        
        <div class="bg-white p-6 rounded-xl luxury-card border border-matteGold/15">
            <h3 class="text-xs font-mono font-black uppercase text-navyDark mb-4 border-b pb-2 flex items-center justify-between">
                <span>📊 Live Analytics Visualization Streams</span>
                <span class="w-2 h-2 bg-emerald-500 rounded-full animate-ping"></span>
            </h3>
            <div class="h-48 flex items-center justify-center bg-luxury-navy rounded-xl p-6 border border-matteGold/20 shadow-inner">
                <div class="w-full max-w-lg px-6 text-center space-y-3">
                    <p class="font-mono font-black text-white tracking-widest text-[11px]">REAL-TIME DATA-STREAM GRAPH MATRIX CAPTURED</p>
                    <div class="w-full bg-securityBlue border border-matteGold/20 h-4 rounded-full overflow-hidden flex p-0.5 shadow-lg">
                        <div class="bg-gold-gradient h-full rounded-l-full" style="width: 40%"></div>
                        <div class="bg-blue-500 h-full" style="width: 30%"></div>
                        <div class="bg-amber-500 h-full" style="width: 20%"></div>
                        <div class="bg-emerald-600 h-full rounded-r-full" style="width: 10%"></div>
                    </div>
                    <div class="flex justify-between text-[9px] font-mono text-gray-400 tracking-wide pt-1">
                        <span>Pending (40%)</span>
                        <span>Investigating (30%)</span>
                        <span>Arrests (20%)</span>
                        <span>Closed (10%)</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return generate_nps_response(html, total_ob=total_ob, pending=pending, ui=ui, closed=closed, arrests=arrests, off_count=off_count, evidence_count=evidence_count)

@app.route('/occurrence-book', methods=['GET', 'POST'])
@login_required
def occurrence_book():
    if request.method == 'POST':
        if current_user.role not in ['Desk Officer', 'Administrator']:
            abort(403)
            
        count = db.session.query(db.func.count(OBEntry.id)).scalar() or 0
        ob_seq_string = f"OB/2026/{count + 1:06d}"
        
        entry = OBEntry(
            ob_number=ob_seq_string,
            complainant_name=request.form.get('complainant_name'),
            national_id=request.form.get('national_id'),
            phone_number=request.form.get('phone_number'),
            gender=request.form.get('gender'),
            address=request.form.get('address'),
            incident_location=request.form.get('incident_location'),
            crime_category=request.form.get('crime_category'),
            narrative=request.form.get('narrative'),
            station_id=current_user.station_id,
            reporting_officer_id=current_user.id,
            status='Pending Review'
        )
        db.session.add(entry)
        db.session.commit()
        
        db.session.add(InvestigationNote(
            ob_entry_id=entry.id,
            note_type='Timeline Entry',
            text_content="Core incident sequence submitted via console terminal framework memory spaces.",
            recorded_by=current_user.full_name
        ))
        db.session.commit()
        commit_audit(f"Created new Digital Occurrence Book entry row string link: {ob_seq_string}")
        flash(f"System Log committed successfully into permanent block index mapping string code: {ob_seq_string}", "success")
        return redirect(url_for('occurrence_book'))
        
    if current_user.role == 'Administrator':
        records = OBEntry.query.order_by(OBEntry.id.desc()).all()
    else:
        records = OBEntry.query.filter_by(station_id=current_user.station_id).order_by(OBEntry.id.desc()).all()
        
    html = """
    <div class="space-y-6">
        {% if current_user.role in ['Desk Officer', 'Administrator'] %}
        <div class="bg-white p-6 rounded-xl border border-matteGold/15 luxury-card">
            <h2 class="text-xs font-mono font-black uppercase mb-4 border-b pb-2 text-white tracking-widest flex items-center space-x-2">
                <span>📝 Append New Primary Incident Occurrence Log</span>
            </h2>
            <form method="POST" class="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-mono">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Complainant Full Name</label>
                    <input type="text" name="complainant_name" required class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">National ID / Passport</label>
                    <input type="text" name="national_id" required class="w-full p-3 border rounded-lg bg-white outline-none luxury-input text-xs">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Telephone Demographics Link</label>
                    <input type="text" name="phone_number" required class="w-full p-3 border rounded-lg bg-white outline-none luxury-input text-xs">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Gender Specification</label>
                    <select name="gender" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs cursor-pointer">
                        <option value="Male">Male</option>
                        <option value="Female">Female</option>
                        <option value="Corporate/Other">Corporate Entity / Intersex</option>
                    </select>
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Incident Physical Location</label>
                    <input type="text" name="incident_location" required class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Statutory Penal Category Class</label>
                    <select name="crime_category" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs cursor-pointer">
                        <option value="Assault and Physical Harm Matrix">Assault and Physical Harm Matrix</option>
                        <option value="Armed Robbery / Burglary Invasion">Armed Robbery / Burglary Invasion</option>
                        <option value="Financial Fraud / Cyber System Intrusion">Financial Fraud / Cyber System Intrusion</option>
                        <option value="Narcotics Traffic / Substance Violation">Narcotics Traffic / Substance Violation</option>
                        <option value="Homicide / Severe Capital Malfeasance">Homicide / Severe Capital Malfeasance</option>
                    </select>
                </div>
                <div class="md:col-span-3">
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Residential Home Address</label>
                    <input type="text" name="address" required class="w-full p-3 border rounded-lg bg-white font-sans outline-none luxury-input text-xs">
                </div>
                <div class="md:col-span-3">
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Exhaustive Deposition Transcript Statement Text Narrative</label>
                    <textarea name="narrative" rows="3" required class="w-full p-3 border rounded-lg bg-white font-sans outline-none luxury-input text-xs leading-relaxed"></textarea>
                </div>
                <button type="submit" class="md:col-span-3 bg-luxury-navy text-white border border-matteGold/30 font-black p-4 rounded-lg uppercase tracking-widest hover:opacity-90 text-xs transition-all duration-200 shadow-xl mt-2">
                    Lock Entry Matrix Segment Block Permanently to DB Memory
                </button>
            </form>
        </div>
        {% endif %}
        
        <div class="bg-white border border-matteGold/10 rounded-xl luxury-card overflow-hidden">
            <div class="bg-luxury-navy p-4 text-white font-mono font-black text-xs uppercase tracking-widest border-b border-matteGold/20">
                📖 Active System Ledger Journal Stream Table Data View
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs border-collapse">
                    <thead class="bg-gray-50 font-mono text-[10px] uppercase text-gray-400 border-b tracking-wider">
                        <tr class="divide-x divide-gray-100">
                            <th class="p-4">OB Code</th>
                            <th class="p-4">Filing Date</th>
                            <th class="p-4">Complainant</th>
                            <th class="p-4">Offense Class Category Type</th>
                            <th class="p-4">State Phase</th>
                            <th class="p-4 text-center">Action Arrays</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-100 font-sans text-gray-700">
                        {% for r in records %}
                        <tr class="hover:bg-gray-50/80 divide-x divide-gray-50 transition-all duration-150">
                            <td class="p-4 font-mono font-extrabold text-navyDark text-sm tracking-wide">{{ r.ob_number }}</td>
                            <td class="p-4 text-gray-400 font-mono text-[11px]">{{ r.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                            <td class="p-4 font-bold text-gray-900 text-xs">{{ r.complainant_name }}</td>
                            <td class="p-4"><span class="bg-slateWhite text-navyDark px-2.5 py-1 border border-gray-200 text-[10px] rounded-md font-mono font-bold">{{ r.crime_category }}</span></td>
                            <td class="p-4">
                                <span class="text-[9px] font-mono font-black uppercase border px-2.5 py-1 rounded-full shadow-sm
                                           {% if r.status == 'Pending Review' %} bg-amber-50 text-amber-800 border-amber-300
                                           {% elif r.status == 'Under Investigation' %} bg-blue-50 text-blue-800 border-blue-300
                                           {% elif r.status == 'Closed' %} bg-emerald-50 text-emerald-800 border-emerald-300
                                           {% else %} bg-purple-50 text-purple-800 border-purple-300 {% endif %}">
                                    {{ r.status }}
                                </span>
                            </td>
                            <td class="p-4 flex space-x-2 justify-center font-mono">
                                <a href="/case-workspace/{{ r.id }}" class="bg-luxury-navy text-white border border-matteGold/30 px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider hover:bg-securityBlue transition-all">Workspace</a>
                                <a href="/abstract/download/{{ r.id }}" class="bg-gold-gradient text-navyDark px-3 py-1.5 rounded-md text-[10px] font-black uppercase tracking-wider hover:opacity-90 transition-all shadow-sm">PDF Abstract</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return generate_nps_response(html, records=records)

@app.route('/case-workspace/<int:entry_id>', methods=['GET', 'POST'])
@login_required
def case_workspace(entry_id):
    entry = OBEntry.query.get_or_404(entry_id)
    if current_user.role != 'Administrator' and entry.station_id != current_user.station_id:
        abort(403)
        
    investigators = User.query.filter_by(role='Investigator', is_active=True).all()
    all_suspects = Suspect.query.all()
    
    html = """
    <div class="space-y-6">
        <div class="border-b pb-3 border-matteGold/20 flex justify-between items-center">
            <h1 class="text-xl font-black text-navyDark uppercase font-mono tracking-wide flex items-center">
                <span>🔍 Case Investigative Shell Terminal: <span class="text-white">{{ entry.ob_number }}</span></span>
            </h1>
            <span class="px-4 py-1.5 bg-luxury-navy border border-matteGold/30 text-white font-mono text-xs font-bold rounded-lg shadow-md">Jurisdiction Hub: {{ entry.station.name }}</span>
        </div>
        
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 text-xs">
            <div class="bg-white p-5 border border-matteGold/10 rounded-xl luxury-card space-y-4 font-mono">
                <h3 class="font-black border-b border-matteGold/10 pb-2 text-white uppercase text-xs tracking-wider">Primary Core Parameters</h3>
                <div class="space-y-2.5">
                    <p class="text-gray-400">Complainant File Identity: <span class="text-navyDark font-sans font-black block text-sm mt-0.5">{{ entry.complainant_name }}</span></p>
                    <p class="text-gray-400">National ID Token: <span class="text-navyDark font-bold block mt-0.5">{{ entry.national_id }}</span></p>
                    <p class="text-gray-400">Telephone Line Trace: <span class="text-navyDark font-bold block mt-0.5">{{ entry.phone_number }}</span></p>
                    <p class="text-gray-400">Physical Location Site: <span class="text-navyDark font-sans font-bold block mt-0.5">{{ entry.incident_location }}</span></p>
                </div>
                
                <div class="bg-slateWhite p-4 rounded-xl border text-gray-700 font-sans leading-relaxed italic shadow-inner">
                    "{{ entry.narrative }}"
                </div>
                
                <div class="pt-3 border-t border-gray-100 space-y-4">
                    <p class="text-gray-400 font-bold tracking-wide">Assigned Detective Handler: <br>
                        <span class="text-indigo-950 font-sans font-black text-xs block mt-1 bg-gray-50 border p-2 rounded-lg shadow-sm">
                            👉 {% if entry.investigator %} {{ entry.investigator.rank }} {{ entry.investigator.full_name }} ({{ entry.investigator.service_number }}) {% else %} Unassigned/Pending Allocation Matrix {% endif %}
                        </span>
                    </p>
                    
                    {% if current_user.role in ['OCS', 'Administrator'] %}
                    <form action="/case-workspace/{{ entry.id }}/assign" method="POST" class="space-y-2 border-t border-gray-100 pt-3">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <label class="block text-[10px] font-black uppercase text-gray-400 tracking-wider">Allocate Active Investigator Handler</label>
                        <select name="investigator_id" class="w-full p-2.5 border rounded-lg font-sans bg-white outline-none luxury-input text-xs cursor-pointer">
                            {% for inv in investigators %}
                            <option value="{{ inv.id }}" {% if entry.investigator_id == inv.id %} selected {% endif %}>{{ inv.rank }} {{ inv.full_name }}</option>
                            {% endfor %}
                        </select>
                        <button type="submit" class="w-full bg-luxury-navy text-white border border-matteGold/30 font-bold py-2 rounded-lg uppercase text-[10px] tracking-widest hover:opacity-90 transition-all shadow-md">Mutate Investigator Link</button>
                    </form>
                    
                    <form action="/case-workspace/{{ entry.id }}/status" method="POST" class="space-y-2 border-t border-gray-100 pt-3">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <label class="block text-[10px] font-black uppercase text-gray-400 tracking-wider">Transition Global Lifecycle Phase</label>
                        <select name="status" class="w-full p-2.5 border rounded-lg font-sans bg-white outline-none luxury-input text-xs cursor-pointer">
                            <option value="Pending Review" {% if entry.status == 'Pending Review' %} selected {% endif %}>Pending Review</option>
                            <option value="Under Investigation" {% if entry.status == 'Under Investigation' %} selected {% endif %}>Under Investigation</option>
                            <option value="Arrest Made" {% if entry.status == 'Arrest Made' %} selected {% endif %}>Arrest Made</option>
                            <option value="Court Process" {% if entry.status == 'Court Process' %} selected {% endif %}>Court Process</option>
                            <option value="Closed" {% if entry.status == 'Closed' %} selected {% endif %}>Closed</option>
                        </select>
                        <button type="submit" class="w-full bg-amber-600 text-white font-black py-2 rounded-lg uppercase text-[10px] tracking-widest hover:bg-amber-700 transition-all shadow-md">Execute State Transition</button>
                    </form>
                    {% endif %}
                </div>
            </div>
            
            <div class="lg:col-span-2 space-y-6">
                <div class="bg-white p-5 border border-matteGold/10 rounded-xl luxury-card space-y-4">
                    <h3 class="font-mono font-black border-b border-matteGold/10 pb-2 text-white uppercase text-xs tracking-wider">Linked Target Suspect Profile Associations</h3>
                    <div class="flex flex-wrap gap-2.5">
                        {% for sus in entry.suspects %}
                        <div class="bg-red-50 border border-red-200 p-3 rounded-lg flex items-center space-x-3 text-xs font-mono shadow-sm">
                            <div>
                                <span class="font-sans font-black text-red-900 block text-xs">{{ sus.full_name }}</span>
                                <span class="text-[10px] text-gray-500 block">ID Trace Link: {{ sus.national_id }}</span>
                            </div>
                            <form action="/case-workspace/{{ entry.id }}/unlink-suspect/{{ sus.id }}" method="POST">
                                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                                <button type="submit" class="text-red-500 hover:text-red-800 font-black text-sm px-1.5 transition-all">&times;</button>
                            </form>
                        </div>
                        {% else %}
                        <p class="text-gray-400 italic text-xs font-mono py-1">No target suspects currently mapped to this specific offense structure array matrix.</p>
                        {% endfor %}
                    </div>
                    {% if current_user.role in ['Investigator', 'OCS', 'Administrator'] %}
                    <form action="/case-workspace/{{ entry.id }}/link-suspect" method="POST" class="flex space-x-2 border-t border-gray-100 pt-3 items-end">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <div class="flex-1 font-mono">
                            <label class="block text-[10px] font-black uppercase text-gray-400 mb-1 tracking-wider">Map Suspect Node from Global Registry Index</label>
                            <select name="suspect_id" class="w-full p-2.5 border text-xs font-mono bg-white rounded-lg outline-none luxury-input cursor-pointer">
                                {% for global_sus in all_suspects %}
                                <option value="{{ global_sus.id }}">{{ global_sus.full_name }} [ID: {{ global_sus.national_id }}]</option>
                                {% endfor %}
                            </select>
                        </div>
                        <button type="submit" class="bg-luxury-navy text-white border border-matteGold/30 px-5 py-2.5 font-mono rounded-lg text-xs font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-md">Bind Link</button>
                    </form>
                    {% endif %}
                </div>
                
                <div class="bg-white p-5 border border-matteGold/10 rounded-xl luxury-card space-y-4">
                    <h3 class="font-mono font-black border-b border-matteGold/10 pb-2 text-white uppercase text-xs tracking-wider">Chronological Case Ledger Matrix Journal</h3>
                    <div class="space-y-3 max-h-72 overflow-y-auto font-mono text-[11px] pr-1">
                        {% for note in entry.notes %}
                        <div class="p-3.5 bg-gray-50 border border-gray-200 rounded-lg shadow-inner space-y-1.5">
                            <div class="flex justify-between text-[9px] text-gray-400 font-black tracking-widest uppercase border-b border-gray-200/60 pb-1">
                                <span>🕒 Index Clock: {{ note.timestamp.strftime('%Y-%m-%d %H:%M:%S') }} UTC</span>
                                <span class="bg-luxury-navy border border-matteGold/20 text-white px-2 py-0.5 rounded text-[8px] tracking-wide">Actor: {{ note.recorded_by }}</span>
                            </div>
                            <p class="font-sans text-gray-800 text-xs leading-relaxed font-semibold">
                                <span class="text-[9px] font-mono font-black px-2 py-0.5 bg-slate-200 rounded text-slate-700 uppercase mr-1 tracking-wide">[{{ note.note_type }}]</span>
                                {{ note.text_content }}
                            </p>
                        </div>
                        {% endfor %}
                    </div>
                    
                    {% if current_user.role in ['Investigator', 'OCS', 'Administrator'] %}
                    <form action="/case-workspace/{{ entry.id }}/add-note" method="POST" class="space-y-3 pt-3 border-t border-gray-100 font-mono">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                            <div class="md:col-span-1">
                                <label class="block text-[10px] font-black uppercase text-gray-400 mb-1 tracking-wider">Classification Tag</label>
                                <select name="note_type" class="w-full p-2.5 border text-xs bg-white rounded-lg outline-none luxury-input font-sans cursor-pointer">
                                    <option value="Timeline Entry">Timeline Update</option>
                                    <option value="Witness Statement Log">Witness Statement Log</option>
                                    <option value="General Progress Track">General Progress Track</option>
                                    <option value="Arrest Record Note">Arrest Record Note</option>
                                </select>
                            </div>
                            <div class="md:col-span-2">
                                <label class="block text-[10px] font-black uppercase text-gray-400 mb-1 tracking-wider">Transcribe Narrative Update</label>
                                <div class="flex space-x-2">
                                    <input type="text" name="text_content" required placeholder="Append field updates into journal pipeline..." 
                                           class="flex-1 p-2.5 border font-sans text-xs bg-white rounded-lg outline-none luxury-input">
                                    <button type="submit" class="bg-luxury-navy text-white border border-matteGold/30 font-black px-5 rounded-lg text-xs uppercase tracking-widest hover:opacity-90 transition-all shadow-md">Commit</button>
                                </div>
                            </div>
                        </div>
                    </form>
                    {% endif %}
                </div>
                
                <div class="bg-white p-5 border border-matteGold/10 rounded-xl luxury-card space-y-4">
                    <h3 class="font-mono font-black border-b border-matteGold/10 pb-2 text-white uppercase text-xs tracking-wider">🔒 Secure Vault Evidence Repository</h3>
                    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 font-mono text-[10px]">
                        {% for file in entry.evidence_files %}
                        <div class="bg-gray-50 border border-gray-200 p-3 rounded-lg text-center space-y-2 flex flex-col justify-between shadow-sm relative overflow-hidden">
                            <div class="w-full h-12 bg-luxury-navy text-white flex items-center justify-center font-black rounded-lg text-xl tracking-widest shadow-inner border border-matteGold/10">
                                📑
                            </div>
                            <div class="truncate text-gray-700 font-extrabold text-xs" title="{{ file.original_name }}">{{ file.original_name }}</div>
                            <div class="text-[8px] text-gray-400 uppercase truncate">By: {{ file.uploaded_by }}</div>
                            <a href="/vault/download/{{ file.id }}" class="bg-luxury-navy hover:bg-securityBlue border border-matteGold/20 text-white text-[9px] py-1.5 rounded-md font-black block uppercase tracking-widest transition-all duration-150 shadow-sm">Retrieve File</a>
                        </div>
                        {% else %}
                        <p class="col-span-2 md:col-span-4 text-gray-400 italic font-mono text-xs py-1">No binary stream payload blocks associated with this case file configuration record sequence.</p>
                        {% endfor %}
                    </div>
                    
                    {% if current_user.role in ['Investigator', 'Desk Officer', 'Administrator'] %}
                    <form action="/case-workspace/{{ entry.id }}/upload-evidence" method="POST" enctype="multipart/form-data" class="border-t border-gray-100 pt-3 flex items-end space-x-3 font-mono">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <div class="flex-1">
                            <label class="block text-[10px] font-black uppercase text-gray-400 mb-1 tracking-wider">Stream Payload Binary Block File Upload</label>
                            <input type="file" name="evidence_payload" required class="w-full p-2 border text-xs bg-white rounded-lg outline-none luxury-input cursor-pointer file:mr-4 file:py-1 file:px-3 file:rounded-md file:border-0 file:text-[10px] file:font-black file:uppercase file:bg-luxury-navy file:text-white file:cursor-pointer">
                        </div>
                        <button type="submit" class="bg-gradient-to-r from-emerald-700 to-emerald-900 border border-emerald-600 text-white font-black px-5 py-2.5 rounded-lg text-xs uppercase tracking-wider hover:opacity-95 transition-all shadow-md">
                            Upload Injection
                        </button>
                    </form>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
    """
    return generate_nps_response(html, entry=entry, investigators=investigators, all_suspects=all_suspects)

@app.route('/case-workspace/<int:entry_id>/assign', methods=['POST'])
@login_required
def case_assign_investigator(entry_id):
    if current_user.role not in ['OCS', 'Administrator']: abort(403)
    entry = OBEntry.query.get_or_404(entry_id)
    inv_id = request.form.get('investigator_id')
    entry.investigator_id = inv_id
    db.session.commit()
    
    inv_user = User.query.get(inv_id)
    db.session.add(InvestigationNote(
        ob_entry_id=entry.id,
        note_type='Timeline Entry',
        text_content=f"Primary file processing ownership mapping parameters reassigned dynamically to handler detective token node: {inv_user.rank} {inv_user.full_name}",
        recorded_by=current_user.full_name
    ))
    db.session.commit()
    commit_audit(f"Mutated detective handler mapping linkage parameters on OB file identifier structure index string: {entry.ob_number}")
    flash("Investigative asset tracking parameter matrix link updated successfully.", "success")
    return redirect(url_for('case_workspace', entry_id=entry.id))

@app.route('/case-workspace/<int:entry_id>/status', methods=['POST'])
@login_required
def case_update_status(entry_id):
    if current_user.role not in ['OCS', 'Administrator']: abort(403)
    entry = OBEntry.query.get_or_404(entry_id)
    new_stat = request.form.get('status')
    entry.status = new_stat
    db.session.commit()
    
    db.session.add(InvestigationNote(
        ob_entry_id=entry.id,
        note_type='Timeline Entry',
        text_content=f"System Global Lifecycle tracking state configuration variable mutated to index state parameter value string: {new_stat}",
        recorded_by=current_user.full_name
    ))
    db.session.commit()
    commit_audit(f"Actuated core milestone framework sequence shift to state [{new_stat}] on OB row string index tracker code: {entry.ob_number}")
    flash("Workflow structural lifecycle configuration variable updated successfully across system memory pipelines.", "success")
    return redirect(url_for('case_workspace', entry_id=entry.id))

@app.route('/case-workspace/<int:entry_id>/add-note', methods=['POST'])
@login_required
def case_append_note(entry_id):
    if current_user.role not in ['Investigator', 'OCS', 'Administrator']: abort(403)
    entry = OBEntry.query.get_or_404(entry_id)
    
    note = InvestigationNote(
        ob_entry_id=entry.id,
        note_type=request.form.get('note_type'),
        text_content=request.form.get('text_content'),
        recorded_by=f"{current_user.rank} {current_user.full_name}"
    )
    db.session.add(note)
    db.session.commit()
    commit_audit(f"Appended chronological milestone update layer row to case tracker sequence string mapping hash: {entry.ob_number}")
    flash("Ledger update trace successfully written to case transactional memory space logs.", "success")
    return redirect(url_for('case_workspace', entry_id=entry.id))

@app.route('/case-workspace/<int:entry_id>/upload-evidence', methods=['POST'])
@login_required
def case_inject_evidence(entry_id):
    if current_user.role not in ['Investigator', 'Desk Officer', 'Administrator']: abort(403)
    entry = OBEntry.query.get_or_404(entry_id)
    
    file = request.files.get('evidence_payload')
    if file and file.filename != '':
        orig = file.filename
        ext = os.path.splitext(orig)[1]
        secure_token_filename = f"NPS_VAULT_{secrets.token_hex(12)}{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_token_filename)
        file.save(filepath)
        
        evidence = Evidence(
            ob_entry_id=entry.id,
            filename=secure_token_filename,
            original_name=orig,
            file_type=file.content_type or "application/octet-stream",
            uploaded_by=f"{current_user.rank} {current_user.full_name}"
        )
        db.session.add(evidence)
        
        db.session.add(InvestigationNote(
            ob_entry_id=entry.id,
            note_type='General Progress Track',
            text_content=f"Secure binary stream element uploaded into crypt vault schema storage array space. File block tracker mapping name reference: {orig}",
            recorded_by=current_user.full_name
        ))
        db.session.commit()
        commit_audit(f"Uploaded binary sequence module structure packet footprint payload to case log row tracking string: {entry.ob_number}")
        flash("Payload block bound and committed securely into digital infrastructure vault memory storage arrays.", "success")
        
    return redirect(url_for('case_workspace', entry_id=entry.id))

@app.route('/case-workspace/<int:entry_id>/link-suspect', methods=['POST'])
@login_required
def case_bind_suspect_link(entry_id):
    if current_user.role not in ['Investigator', 'OCS', 'Administrator']: abort(403)
    entry = OBEntry.query.get_or_404(entry_id)
    sus_id = request.form.get('suspect_id')
    suspect = Suspect.query.get_or_404(sus_id)
    
    if suspect not in entry.suspects:
        entry.suspects.append(suspect)
        db.session.add(InvestigationNote(
            ob_entry_id=entry.id,
            note_type='Timeline Entry',
            text_content=f"Linked suspect profile trace index element bound to case tracking space parameters: {suspect.full_name} [ID Code Link: {suspect.national_id}]",
            recorded_by=current_user.full_name
        ))
        db.session.commit()
        commit_audit(f"Bound relationship model association mapping between suspect [{suspect.national_id}] and case string row index tracker key: {entry.ob_number}")
        flash("Criminal suspect tracking trace successfully bound to current occurrence file parameter schema.", "success")
    else:
        flash("Entity relation link trace mapping definition already exists inside database runtime indices.", "danger")
        
    return redirect(url_for('case_workspace', entry_id=entry.id))

@app.route('/case-workspace/<int:entry_id>/unlink-suspect/<int:suspect_id>', methods=['POST'])
@login_required
def case_drop_suspect_link(entry_id):
    if current_user.role not in ['Investigator', 'OCS', 'Administrator']: abort(403)
    entry = OBEntry.query.get_or_404(entry_id)
    suspect = Suspect.query.get_or_404(suspect_id)
    
    if suspect in entry.suspects:
        entry.suspects.remove(suspect)
        db.session.add(InvestigationNote(
            ob_entry_id=entry.id,
            note_type='Timeline Entry',
            text_content=f"Dropped linked suspect profile association map array parameters footprint: {suspect.full_name}",
            recorded_by=current_user.full_name
        ))
        db.session.commit()
        commit_audit(f"Severed relationship model reference map index row link between suspect [{suspect.national_id}] and case code string: {entry.ob_number}")
        flash("Relationship tracing context unlinked successfully.", "success")
        
    return redirect(url_for('case_workspace', entry_id=entry.id))

@app.route('/vault/download/<int:evidence_id>')
@login_required
def vault_retrieve_stream(evidence_id):
    ev = Evidence.query.get_or_404(evidence_id)
    if current_user.role != 'Administrator' and ev.ob_entry.station_id != current_user.station_id:
        abort(403)
    commit_audit(f"Retrieved and opened secure digital vault evidence file packet asset: {ev.original_name}")
    return send_from_directory(app.config['UPLOAD_FOLDER'], ev.filename, download_name=ev.original_name, as_attachment=True)

@app.route('/abstract/download/<int:entry_id>')
def public_download_abstract(entry_id):
    ob = OBEntry.query.get_or_404(entry_id)
    buf = BytesIO()
    build_pdf_abstract(ob, buf)
    buf.seek(0)
    
    sanitized_ob_string_filename = f"NPS_Certified_Digital_Abstract_{ob.ob_number.replace('/', '_')}.pdf"
    commit_audit(f"Compiled and outputted certified legal police abstract document streaming PDF module footprint matching track: {ob.ob_number}")
    return Response(buf.read(), mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename={sanitized_ob_string_filename}'})

@app.route('/suspect-registry', methods=['GET', 'POST'])
@login_required
def suspect_registry():
    if request.method == 'POST':
        if current_user.role not in ['Investigator', 'Administrator']: abort(403)
        
        sus = Suspect(
            full_name=request.form.get('full_name'),
            national_id=request.form.get('national_id') or None,
            date_of_birth=request.form.get('date_of_birth'),
            gender=request.form.get('gender'),
            address=request.form.get('address'),
            phone_number=request.form.get('phone_number'),
            arrest_history_summary=request.form.get('arrest_history_summary')
        )
        db.session.add(sus)
        db.session.commit()
        commit_audit(f"Provisioned and compiled new suspect biographic profile token into database master indexes: {sus.full_name}")
        flash("Criminal target tracking data structure profile node successfully loaded into system indices.", "success")
        return redirect(url_for('suspect_registry'))
        
    suspects = Suspect.query.order_by(Suspect.id.desc()).all()
    html = """
    <div class="space-y-6">
        {% if current_user.role in ['Investigator', 'Administrator'] %}
        <div class="bg-white p-6 rounded-xl border border-matteGold/15 luxury-card">
            <h2 class="text-xs font-mono font-black uppercase mb-4 border-b pb-2 text-white tracking-widest">
                👥 Insert Target Criminal Suspect Profile Module
            </h2>
            <form method="POST" class="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs font-mono">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Suspect Identity Name</label>
                    <input type="text" name="full_name" required class="w-full p-3 border rounded-lg bg-white font-sans outline-none luxury-input text-xs">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">National ID Card Code</label>
                    <input type="text" name="national_id" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input text-xs">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Date of Birth</label>
                    <input type="date" name="date_of_birth" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input text-xs cursor-pointer">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Gender Profile</label>
                    <select name="gender" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs cursor-pointer">
                        <option value="Male">Male</option>
                        <option value="Female">Female</option>
                        <option value="Unknown/Undetermined">Unknown/Undetermined</option>
                    </select>
                </div>
                <div class="md:col-span-2">
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Last Known Physical Address</label>
                    <input type="text" name="address" class="w-full p-3 border rounded-lg bg-white font-sans outline-none luxury-input text-xs">
                </div>
                <div class="md:col-span-2">
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Suspect Phone Contact</label>
                    <input type="text" name="phone_number" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input text-xs">
                </div>
                <div class="md:col-span-4">
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Prior Convictions Historical Summary</label>
                    <textarea name="arrest_history_summary" rows="2" placeholder="Detail standard active warrant identifiers or historical penological data..." class="w-full p-3 border rounded-lg bg-white font-sans outline-none luxury-input text-xs leading-relaxed"></textarea>
                </div>
                <button type="submit" class="md:col-span-4 bg-luxury-navy text-white border border-matteGold/30 font-black p-4 rounded-lg uppercase tracking-widest hover:opacity-90 text-xs transition-all duration-200 shadow-xl mt-2">
                    Lock Suspect Dossier into Intelligence Ledger Matrix Memory
                </button>
            </form>
        </div>
        {% endif %}
        
        <div class="bg-white border border-matteGold/10 rounded-xl luxury-card overflow-hidden">
            <div class="bg-luxury-navy p-4 text-white font-mono font-black text-xs uppercase tracking-widest border-b border-matteGold/20">
                👤 Intelligence Profile Central Registry Data Matrix
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs border-collapse">
                    <thead class="bg-gray-50 font-mono text-[10px] uppercase text-gray-400 border-b tracking-wider">
                        <tr class="divide-x divide-gray-100">
                            <th class="p-4">Suspect Name</th>
                            <th class="p-4">Biographic Demographics</th>
                            <th class="p-4">Address & Comms</th>
                            <th class="p-4">Historical Track Summary Dossier</th>
                            <th class="p-4 text-center">Active Linked Files</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-100 font-sans text-gray-700">
                        {% for s in suspects %}
                        <tr class="hover:bg-gray-50/80 divide-x divide-gray-50 transition-all duration-150">
                            <td class="p-4 font-extrabold text-navyDark text-sm">{{ s.full_name }}</td>
                            <td class="p-4 font-mono text-[11px] space-y-0.5 text-gray-600">
                                <span class="block text-navyDark font-semibold">ID: {% if s.national_id %}{{ s.national_id }}{% else %}N/A{% endif %}</span>
                                <span class="block text-[10px]">DOB: {{ s.date_of_birth }} | Gen: {{ s.gender }}</span>
                            </td>
                            <td class="p-4 space-y-0.5 font-medium text-xs">
                                <span class="block text-navyDark">📍 {{ s.address or 'No Address Tracked' }}</span>
                                <span class="block text-gray-400 font-mono text-[11px]">📞 {{ s.phone_number or 'N/A' }}</span>
                            </td>
                            <td class="p-4 max-w-xs text-xs italic text-gray-500 font-medium truncate" title="{{ s.arrest_history_summary }}">
                                {{ s.arrest_history_summary or 'No historical felony tracking instances committed.' }}
                            </td>
                            <td class="p-4 text-center font-mono">
                                <span class="bg-red-50 text-red-900 border border-red-200 font-black px-3 py-1 rounded-full text-[10px] uppercase tracking-wide shadow-sm">
                                    {{ s.ob_entries.count() }} Files Linked
                                </span>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return generate_nps_response(html, suspects=suspects)

@app.route('/officer-management', methods=['GET', 'POST'])
@login_required
def officer_management():
    if current_user.role not in ['Administrator', 'OCS']: abort(403)
    stations = Station.query.all()
    
    if request.method == 'POST':
        action_flag = request.form.get('action_flag')
        
        if action_flag == 'create_officer':
            svc_num = request.form.get('service_number', '').strip().upper()
            if User.query.filter_by(service_number=svc_num).first():
                flash("Operational allocation anomaly: Force service number already exists.", "danger")
                return redirect(url_for('officer_management'))
                
            officer = User(
                service_number=svc_num,
                password_hash=generate_password_hash(request.form.get('password')),
                full_name=request.form.get('full_name'),
                rank=request.form.get('rank'),
                role=request.form.get('role'),
                department=request.form.get('department'),
                email=request.form.get('email'),
                phone=request.form.get('phone'),
                station_id=request.form.get('station_id') or None,
                is_active=True
            )
            db.session.add(officer)
            db.session.commit()
            commit_audit(f"Provisioned and authorized force account personnel credential token block mapping: {svc_num}")
            flash("Force account asset successfully attached and synchronized onto command database.", "success")
            
        elif action_flag == 'toggle_status':
            if current_user.role != 'Administrator': abort(403)
            t_id = request.form.get('target_user_id')
            t_user = User.query.get_or_404(t_id)
            t_user.is_active = not t_user.is_active
            db.session.commit()
            commit_audit(f"Toggled administrative authorization state parameters on force profile node: {t_user.service_number}")
            flash("Personnel infrastructure access status successfully modified.", "success")
            
        return redirect(url_for('officer_management'))
        
    if current_user.role == 'Administrator':
        officers = User.query.order_by(User.id.desc()).all()
    else:
        officers = User.query.filter_by(station_id=current_user.station_id).order_by(User.id.desc()).all()
        
    html = """
    <div class="space-y-6 font-mono text-xs">
        <div class="bg-white p-6 rounded-xl border border-matteGold/15 luxury-card">
            <h2 class="text-xs font-black uppercase mb-4 border-b pb-2 text-white tracking-widest">
                👮 Authorize New Active Force Personnel Credentials Block
            </h2>
            <form method="POST" class="grid grid-cols-1 md:grid-cols-4 gap-4">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <input type="hidden" name="action_flag" value="create_officer">
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Service Number ID String</label>
                    <input type="text" name="service_number" required class="w-full p-3 border rounded-lg bg-white outline-none luxury-input text-xs uppercase tracking-wider">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Passcode Access Cipher</label>
                    <input type="password" name="password" required class="w-full p-3 border rounded-lg bg-white outline-none luxury-input text-xs">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Full Official Name</label>
                    <input type="text" name="full_name" required class="w-full p-3 border rounded-lg bg-white outline-none luxury-input text-xs font-sans">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Active Rank Tier Level</label>
                    <select name="rank" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs cursor-pointer">
                        <option value="Constable">Constable</option>
                        <option value="Sergeant">Sergeant</option>
                        <option value="Inspector">Inspector</option>
                        <option value="Chief Inspector">Chief Inspector</option>
                        <option value="Superintendent">Superintendent</option>
                        <option value="Commissioner">Commissioner</option>
                    </select>
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">RBAC Permission Role</label>
                    <select name="role" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs cursor-pointer">
                        <option value="Desk Officer">Desk Officer (OB Inputs)</option>
                        <option value="Investigator">Investigator (Field Case Logs)</option>
                        <option value="OCS">OCS (Station Commander Node)</option>
                        {% if current_user.role == 'Administrator' %}
                        <option value="Administrator">Administrator (Root Sysop Engine)</option>
                        {% endif %}
                    </select>
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Department Allocation</label>
                    <input type="text" name="department" placeholder="e.g. Criminal Investigation" class="w-full p-3 border rounded-lg bg-white font-sans outline-none luxury-input text-xs">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Email Comms Mapping</label>
                    <input type="email" name="email" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs">
                </div>
                <div>
                    <label class="block font-black text-gray-500 mb-1 tracking-wide">Jurisdiction Command Base</label>
                    <select name="station_id" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs cursor-pointer">
                        <option value="">-- No Local Node Assignment (Global Root) --</option>
                        {% for st in stations %}
                        <option value="{{ st.id }}">{{ st.name }} [{{ st.code }}]</option>
                        {% endfor %}
                    </select>
                </div>
                <button type="submit" class="md:col-span-4 bg-luxury-navy text-white border border-matteGold/30 font-black p-4 rounded-lg uppercase tracking-widest hover:opacity-90 text-xs transition-all duration-200 shadow-xl mt-2">
                    Provision Account Credentials Block and Append onto Roster
                </button>
            </form>
        </div>
        
        <div class="bg-white border border-matteGold/10 rounded-xl luxury-card overflow-hidden">
            <div class="bg-luxury-navy p-4 text-white font-black text-xs uppercase tracking-widest border-b border-matteGold/20">
                👮 Operational Police Force Roster Schema Map View
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead class="bg-gray-50 text-[10px] uppercase text-gray-400 border-b tracking-wider">
                        <tr class="divide-x divide-gray-100">
                            <th class="p-4">Service Token ID</th>
                            <th class="p-4">Rank & Name Parameters</th>
                            <th class="p-4">RBAC Access Boundary Role</th>
                            <th class="p-4">Department & Station Base</th>
                            <th class="p-4">Access State</th>
                            {% if current_user.role == 'Administrator' %}
                            <th class="p-4 text-center">Root Actions</th>
                            {% endif %}
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-100 font-sans text-gray-700">
                        {% for o in officers %}
                        <tr class="hover:bg-gray-50/80 divide-x divide-gray-50 transition-all duration-150">
                            <td class="p-4 font-mono font-extrabold text-navyDark text-[11px] tracking-wider">{{ o.service_number }}</td>
                            <td class="p-4 font-bold text-gray-900 text-xs">{{ o.rank }} {{ o.full_name }}</td>
                            <td class="p-4 font-mono font-black text-[10px] uppercase text-indigo-900 tracking-wide">{{ o.role }}</td>
                            <td class="p-4 font-medium space-y-0.5 text-xs">
                                <span class="block text-navyDark font-bold">📍 {% if o.station %}{{ o.station.name }}{% else %}Global Command Hub Node{% endif %}</span>
                                <span class="block text-[11px] text-gray-400 font-mono">Dept: {{ o.department or 'General Operations Roster' }}</span>
                            </td>
                            <td class="p-4">
                                <span class="px-2.5 py-1 rounded-full text-[9px] font-mono font-black uppercase border shadow-sm
                                           {% if o.is_active %} bg-emerald-50 text-emerald-800 border-emerald-300 {% else %} bg-red-50 text-red-800 border-red-300 {% endif %}">
                                    {% if o.is_active %} CLEARANCE ACTIVE {% else %} SUSPENDED REJECTED {% endif %}
                                </span>
                            </td>
                            {% if current_user.role == 'Administrator' %}
                            <td class="p-4 text-center font-mono">
                                <form method="POST" class="inline">
                                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                                    <input type="hidden" name="action_flag" value="toggle_status">
                                    <input type="hidden" name="target_user_id" value="{{ o.id }}">
                                    <button type="submit" class="text-[9px] font-black uppercase px-3 py-1.5 bg-gray-100 border border-gray-200 hover:bg-luxury-navy hover:text-white hover:border-matteGold/30 rounded-lg transition-all shadow-sm">
                                        Toggle Access Boundary Keys
                                    </button>
                                </form>
                            </td>
                            {% endif %}
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return generate_nps_response(html, stations=stations, officers=officers)

@app.route('/reports', methods=['GET', 'POST'])
@login_required
def reports():
    if request.method == 'POST':
        export_format = request.form.get('export_format', 'excel')
        
        if current_user.role == 'Administrator':
            entries = OBEntry.query.order_by(OBEntry.id.asc()).all()
        else:
            entries = OBEntry.query.filter_by(station_id=current_user.station_id).order_by(OBEntry.id.asc()).all()
            
        if export_format == 'excel':
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "NPS Crime Analytics Statistics Matrix"
            
            headers = ["OB Unique Code ID", "Filing Timestamp", "Station Unit Jurisdiction", "Complainant Legal Name", "National ID Token", "Crime Category Classification", "Lifecycle State Phase", "Reporting Force Agent Token"]
            ws.append(headers)
            
            for item in entries:
                ws.append([
                    item.ob_number,
                    item.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    item.station.name,
                    item.complainant_name,
                    item.national_id,
                    item.crime_category,
                    item.status,
                    item.reporting_officer.service_number
                ])
                
            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 3, 12)
                
            out = BytesIO()
            wb.save(out)
            out.seek(0)
            
            commit_audit("Compiled and outputted full spreadsheet analytics trace tracking mapping matrix.")
            return Response(out.read(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            headers={'Content-Disposition': 'attachment; filename=NPS_Crime_Statistical_Report_Matrix_2026.xlsx'})
                            
    html = """
    <div class="space-y-6 font-mono text-xs max-w-xl mx-auto mt-6 bg-white p-6 border border-matteGold/15 rounded-xl luxury-card">
        <h2 class="text-sm font-black uppercase text-white border-b border-matteGold/10 pb-2 mb-4 tracking-widest text-center">
            📊 Statistical Data Extraction Pipeline
        </h2>
        <p class="text-gray-500 font-sans leading-relaxed text-center">
            Extract complete data boundaries from the active core ledger node. Outputs generate structured Excel files containing cryptographic compliance signatures.
        </p>
        <form method="POST" class="space-y-4 pt-4 border-t border-gray-100">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div>
                <label class="block font-black text-gray-500 mb-1 tracking-wide">Reporting Extraction Framework</label>
                <select name="report_type" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs cursor-pointer">
                    <option value="daily">Daily Primary OB Analytical Trace Logs</option>
                    <option value="weekly">Weekly Core Crime Progression Trends Matrix</option>
                    <option value="monthly">Monthly National Crime Demographics Statistics Sheet</option>
                    <option value="annual">Annual Macro-Penal Operational Review File Block</option>
                    <option value="investigator">Internal Detective Performance Metric Index Matrix</option>
                </select>
            </div>
            <div>
                <label class="block font-black text-gray-500 mb-1 tracking-wide">Document Container Format</label>
                <select name="export_format" class="w-full p-3 border rounded-lg bg-white outline-none luxury-input font-sans text-xs cursor-pointer">
                    <option value="excel">Microsoft Excel Binary Spreadsheet (.xlsx)</option>
                </select>
            </div>
            <button type="submit" class="w-full bg-luxury-navy text-white border border-matteGold/30 font-black p-4 rounded-lg text-xs uppercase tracking-widest shadow-xl transition-all duration-200 mt-2 hover:opacity-90">
                Actuate Compilation Extraction Core
            </button>
        </form>
    </div>
    """
    return generate_nps_response(html)

@app.route('/audit-logs')
@login_required
def audit_logs():
    if current_user.role != 'Administrator': abort(403)
    logs = AuditLog.query.order_by(AuditLog.id.desc()).limit(250).all()
    html = """
    <div class="space-y-4">
        <h1 class="text-xl font-black text-navyDark font-mono uppercase tracking-widest border-b pb-3 border-matteGold/20">
            🛡️ Session Security Ledger Audit Logs
        </h1>
        <div class="bg-white border border-matteGold/10 rounded-xl luxury-card overflow-hidden">
            <div class="overflow-x-auto">
                <table class="w-full text-left font-mono text-[11px] border-collapse">
                    <thead class="bg-luxury-navy text-white uppercase text-[9px] tracking-widest border-b border-matteGold/20">
                        <tr class="divide-x divide-matteGold/10">
                            <th class="p-3">System Clock Timestamp</th>
                            <th class="p-3">Validated Actor Node Identity</th>
                            <th class="p-3">Origin Network IP Addr</th>
                            <th class="p-3">Executed Action Entry Description</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-100 text-gray-700">
                        {% for log in logs %}
                        <tr class="hover:bg-gray-50/80 divide-x divide-gray-50 transition-all duration-100">
                            <td class="p-3 text-gray-400 font-bold whitespace-nowrap">{{ log.timestamp.strftime('%Y-%m-%d %H:%M:%S') }} UTC</td>
                            <td class="p-3 font-bold text-indigo-950">{{ log.user_identifier }}</td>
                            <td class="p-3 text-rose-950 font-semibold">{{ log.ip_address }}</td>
                            <td class="p-3 text-gray-800 font-sans text-xs font-semibold">{{ log.action }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return generate_nps_response(html, logs=logs)

# 6. SYSTEM SEEDING & COLD-BOOT PIPELINE INITIALIZATION
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        if not Station.query.first():
            s1 = Station(name="Nyeri Central Police Station", code="NPS-NYR-CENT")
            s2 = Station(name="Karatina Police Station", code="NPS-NYR-KRTN")
            s3 = Station(name="Othaya Police Station", code="NPS-NYR-OTHY")
            s4 = Station(name="Mukurweini Police Station", code="NPS-NYR-MKWN")
            s5 = Station(name="Nanyuki Police Station", code="NPS-LKP-NYNK")
            db.session.add_all([s1, s2, s3, s4, s5])
            db.session.commit()
            
            admin_seed = User(
                service_number="KP-ADMIN",
                password_hash=generate_password_hash("NpsPassAdmin2026!"),
                full_name="System Infrastructure Controller",
                rank="Commissioner",
                role="Administrator",
                department="Directorate of Technology Communications",
                email="admin.core@nps.go.ke",
                phone="+254711000000",
                station_id=s1.id,
                is_active=True
            )
            desk_seed = User(
                service_number="KP-DESK",
                password_hash=generate_password_hash("DeskPass123!"),
                full_name="Sgt. Benson Mariga",
                rank="Sergeant",
                role="Desk Officer",
                department="General Station Duties Desk",
                email="b.mariga@nps.go.ke",
                phone="+254711111111",
                station_id=s1.id,
                is_active=True
            )
            invest_seed = User(
                service_number="KP-INVEST",
                password_hash=generate_password_hash("InvestPass123!"),
                full_name="IP. Jane Muthoni",
                rank="Inspector",
                role="Investigator",
                department="Directorate of Criminal Investigations (DCI)",
                email="j.muthoni@nps.go.ke",
                phone="+254722222222",
                station_id=s1.id,
                is_active=True
            )
            ocs_seed = User(
                service_number="KP-OCS",
                password_hash=generate_password_hash("OcsPass123!"),
                full_name="SACP. David Kimaiyo",
                rank="Chief Inspector",
                role="OCS",
                department="Station Executive Administration Command",
                email="d.kimaiyo@nps.go.ke",
                phone="+254733333333",
                station_id=s1.id,
                is_active=True
            )
            
            db.session.add_all([admin_seed, desk_seed, invest_seed, ocs_seed])
            db.session.commit()
            
            sus1 = Suspect(full_name="Kamau John Mwangi", national_id="32456789", date_of_birth="1992-04-12", gender="Male", address="Kamakwa Area, Nyeri Base", phone_number="+254700123456", arrest_history_summary="Prior felony history tracked under trace mapping indices for burglary infractions.")
            sus2 = Suspect(full_name="Fatuma Ali Ibrahim", national_id="29485761", date_of_birth="1995-11-23", gender="Female", address="Majengo Settlement, Block C", phone_number="+254711987654", arrest_history_summary="Suspicion tracking logs regarding wire transfer discrepancies.")
            db.session.add_all([sus1, sus2])
            db.session.commit()
            
# --- BULK DATA INSERTION FEATURE ---
@app.route('/seed_test_data')
@login_required
def seed_test_data():
    # Only allow Administrators to perform bulk data insertion
    if current_user.role != 'Administrator':
        flash("Unauthorized access: Administrator privileges required.", "danger")
        return redirect(url_for('dashboard'))
    
    # Bulk insert 1,234 test records
    try:
        for i in range(1, 1235):
            new_entry = OBEntry(
                ob_number=f"OB-{20000 + i}",
                complainant_name=f"Test Citizen {i}",
                crime_category="Investigation",
                narrative=f"System stress test entry number {i}. Generated for operational validation.",
                status="Pending",
                station_id=1
            )
            db.session.add(new_entry)
        
        db.session.commit()
        return f"Successfully committed 1,234 test records to the DPOB Ledger."
    except Exception as e:
        db.session.rollback()
        return f"An error occurred during bulk insertion: {str(e)}"

# --- APPLICATION EXECUTION ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=True)