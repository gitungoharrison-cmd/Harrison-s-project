from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import io
import random
import pandas as pd  # Ensure 'pandas' and 'openpyxl' are in requirements.txt

app = Flask(__name__)
app.secret_key = 'nps_dpobcms_secure_cipher_token'

# Database Configuration
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
    recorded_by = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(30), default='Under Investigation')

# ==========================================
# ROUTING SYSTEMS & PATH CONTROLLERS
# ==========================================

@app.route('/', methods=['GET'])
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        service_number = request.form.get('service_number').strip().upper()
        password = request.form.get('password')
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

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
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

# --- OB ENTRY MANAGEMENT ---
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
        flash(f'Record successfully generated. Serial: {generated_ob}', 'success')
        return redirect(url_for('view_ob'))
        
    return render_template('register_ob.html')

@app.route('/ob/view')
def view_ob():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    entries = OccurrenceBook.query.order_by(OccurrenceBook.date_time.desc()).all()
    return render_template('view_ob.html', entries=entries)

# --- CASES INTEL DISPATCHER ---
@app.route('/cases')
def cases():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    entries = OccurrenceBook.query.filter_by(status='Under Investigation').all()
    return render_template('cases.html', entries=entries)

@app.route('/cases/update/<int:id>', methods=['POST'])
def update_case(id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    entry = OccurrenceBook.query.get_or_404(id)
    entry.status = request.form.get('status')
    db.session.commit()
    flash('Case parameter status updated within the ledger framework.', 'success')
    return redirect(url_for('cases'))

# --- FORCE MANAGEMENT ---
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
        flash('Service Number already provisioned.', 'danger')
        return redirect(url_for('admin_users'))
        
    new_officer = Officer(service_number=service_number, password=password, name=name, role=role)
    db.session.add(new_officer)
    db.session.commit()
    return redirect(url_for('admin_users'))

# --- SYSTEM EXTRACTION CHANNELS ---
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
                "Nature of Offence": entry.nature_of_offence,
                "Current Status": entry.status
            } for entry in ob_entries]
        
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Core_OB_Ledger')
        output.seek(0)
        return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name="NPS_Core_Ledger_Extract.xlsx")
    except Exception as e:
        flash(f"Data extraction matrix failure: {str(e)}", "danger")
        return redirect(url_for('reports'))

@app.route('/public-portal', methods=['GET', 'POST'])
def public_portal():
    search_result = None
    searched = False
    error_msg = None
    if request.method == 'POST':
        searched = True
        query_string = request.form.get('query_string', '').strip()
        search_result = OccurrenceBook.query.filter_by(ob_number=query_string).first()
        if not search_result:
            error_msg = f"No record matching reference token '{query_string}' could be located."
    return render_template('public_portal.html', result=search_result, searched=searched, error_msg=error_msg)

# --- AUXILIARY AUDIT TRACE ROUTERS ---
@app.route('/audit-logs')
def audit_logs():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return "<h5>Security Audit Logging Infrastructure: Active Protocol Stream Monitor Enclosure</h5><p><a href='/dashboard'>Return to Matrix</a></p>"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Officer.query.filter_by(service_number='KP-ADMIN').first():
            db.session.add(Officer(service_number='KP-ADMIN', password='adminpasscipher', name='Chief Superintendent Administrator', role='Admin'))
            db.session.commit()
    app.run(debug=True)
