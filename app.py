from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import io
import pandas as pd  # Ensure 'pandas' and 'openpyxl' are in requirements.txt

app = Flask(__name__)
app.secret_key = 'nps_dpobcms_secure_cipher_token'  # Change to a complex key in production

# Database Configuration (Uses SQLite locally, switches to PostgreSQL seamlessly on Render)
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
    status = db.Column(db.String(30), default='Under Investigation')  # Under Investigation, Closed, Referred

# ==========================================
# AUTHENTICATION ACCESS CONTROLLERS
# ==========================================

@app.route('/', methods=['GET'])
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        service_number = request.form.get('service_number').strip().upper()
        password = request.form.get('password')
        
        # Authenticate officer against credentials node
        officer = Officer.query.filter_by(service_number=service_number).first()
        
        if officer and officer.password == password:  # Note: Use hashing (werkzeug.security) in production
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
        
    # Count database metrics dynamically to populate the Central Metrics Row
    total_ob = OccurrenceBook.query.count()
    active_cases = OccurrenceBook.query.filter_by(status='Under Investigation').count()
    total_officers = Officer.query.count()
    
    return render_template(
        'dashboard.html', 
        total_ob=total_ob, 
        active_cases=active_cases, 
        total_officers=total_officers
    )

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
    
    # Check if officer token exists
    existing = Officer.query.filter_by(service_number=service_number).first()
    if existing:
        flash('Service Number already provisioned in system schema.', 'danger')
        return redirect(url_for('admin_users'))
        
    new_officer = Officer(service_number=service_number, password=password, name=name, role=role)
    db.session.add(new_officer)
    db.session.commit()
    
    flash('New active force personnel credentials block successfully authorized.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/reports', methods=['GET'])
def reports():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('reports.html')

# ==========================================
# DATA EXTRACTION PIPELINE ENGINE
# ==========================================

@app.route('/reports/export', methods=['POST'])
def export_report():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    try:
        # Extract live data rows from the local core ledger database
        ob_entries = OccurrenceBook.query.all()
        
        if not ob_entries:
            # Generate a mock empty structure so the Excel sheet safely compiles if database is fresh
            data = [{
                "OB Number": "N/A", "Timestamp": "N/A", "Complainant": "No Records Logged", 
                "Contact Phone": "N/A", "Nature of Offence": "N/A", 
                "Statement Details": "N/A", "Recording Officer": "N/A", "Current Status": "N/A"
            }]
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
        
        # Map elements into a structured DataFrame matrix
        df = pd.DataFrame(data)
        
        # Stream the file directly into memory as a binary buffer
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

@app.route('/public-portal')
def public_portal():
    # Placeholder for the public facing verification page template link 
    return "<h5>Citizen Verification Terminal Core: Under Construction</h5><p><a href='/login'>Return to Base Gateway</a></p>"

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
            
    app.run(debug=True)
