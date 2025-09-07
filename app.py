# File: app.py
# Main application file for Poddar Enterprise

import os
import sqlite3
import pytz
from datetime import datetime, time, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler
import base64
import uuid
import math
from functools import wraps

# Get the absolute path of the directory containing this file
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'a-default-secret-key-for-dev')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

DATABASE_DIR = os.path.join(basedir, 'data')
DATABASE = os.path.join(DATABASE_DIR, 'business.db')
os.makedirs(DATABASE_DIR, exist_ok=True) # Ensure the directory exists

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ITEMS_PER_PAGE'] = 15

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join('static', 'img'), exist_ok=True)

IST = pytz.timezone('Asia/Kolkata')

@app.context_processor
def inject_now():
    return {'now': datetime.now(IST)}

# --- PWA Routes (Updated for Robustness) ---
@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory(os.path.join(basedir, 'static'), 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory(os.path.join(basedir, 'static'), 'sw.js', mimetype='application/javascript')


# --- User Session & Authentication ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'manager':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        db = get_db()
        g.user = db.execute('SELECT * FROM users WHERE id = ? AND is_active = 1', (user_id,)).fetchone()
        db.close()
        if g.user is None and 'user_id' in session:
            session.clear()

@app.template_filter('ist')
def _jinja2_filter_ist(date_obj, fmt='%Y-%m-%d %I:%M %p'):
    if not date_obj: return ''
    try:
        if isinstance(date_obj, str):
             # This is a fallback, but should not happen with the new get_db config
            if '.' in date_obj:
                 utc_dt = datetime.strptime(date_obj, '%Y-%m-%d %H:%M:%S.%f')
            else:
                 utc_dt = datetime.strptime(date_obj, '%Y-%m-%d %H:%M:%S')
        elif isinstance(date_obj, datetime):
            utc_dt = date_obj
        else:
            return date_obj # Should not happen
        
        if utc_dt.tzinfo is None:
            utc_dt = pytz.utc.localize(utc_dt)

        return utc_dt.astimezone(IST).strftime(fmt)
    except (ValueError, TypeError) as e:
        print(f"Error formatting date: {date_obj}, Error: {e}")
        return date_obj
        
# --- Core Logic ---
def calculate_employee_balance(db, employee_id):
    user = db.execute('SELECT daily_wage FROM users WHERE id = ?', (employee_id,)).fetchone()
    if not user: return { "earned_wages": 0, "total_paid": 0, "amount_due": 0 }
    
    daily_wage = user['daily_wage'] or 0
    all_events = db.execute("SELECT event_type, details, timestamp FROM attendance WHERE employee_id = ? AND event_type IN ('Start', 'End') ORDER BY timestamp", (employee_id,)).fetchall()

    earned_wages = 0
    work_days = {}
    for event in all_events:
        # Now event['timestamp'] is guaranteed to be a datetime object
        day_str = event['timestamp'].strftime('%Y-%m-%d')
        if day_str not in work_days:
            work_days[day_str] = {'Start': None, 'End': None, 'details': None}
        if event['event_type'] == 'Start' and not work_days[day_str]['Start']:
            work_days[day_str]['Start'] = event['timestamp']
        if event['event_type'] == 'End':
            work_days[day_str]['End'] = event['timestamp']
            work_days[day_str]['details'] = event['details']

    for day, events in work_days.items():
        if events['Start'] and events['End']:
            if events['details'] == 'Half Day':
                earned_wages += daily_wage / 2
            else:
                earned_wages += daily_wage
                
    total_paid = db.execute("SELECT SUM(amount) FROM payments WHERE employee_id = ?", (employee_id,)).fetchone()[0] or 0
    balance = earned_wages - total_paid
    
    return { "earned_wages": earned_wages, "total_paid": total_paid, "amount_due": balance }

def get_db():
    # PERMANENT FIX: This ensures timestamps are read as datetime objects
    db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    db.row_factory = sqlite3.Row
    # Register adapter to store datetime with microseconds
    sqlite3.register_adapter(datetime, lambda val: val.isoformat(" "))
    # Register converter to parse datetime
    sqlite3.register_converter("DATETIME", lambda val: datetime.fromisoformat(val.decode()))
    return db

def init_db():
    db = get_db()
    with app.open_resource('schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()
    db.execute("INSERT OR IGNORE INTO businesses (id, name, color) VALUES (1, 'Unassigned', '#6c757d')")
    db.execute("INSERT OR IGNORE INTO users (id, name, role, pin, business_id) VALUES (1, 'Admin', 'manager', '1234', 1)")
    db.commit()
    db.close()

@app.cli.command('initdb')
def initdb_command():
    init_db()
    print('Initialized the database.')

# --- Login & Logout Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        if g.user['role'] == 'manager': return redirect(url_for('dashboard'))
        else: return redirect(url_for('employee_dashboard'))

    db = get_db()
    users = db.execute('SELECT id, name, role FROM users WHERE is_active = 1 ORDER BY name').fetchall()
    db.close()

    if request.method == 'POST':
        user_id, pin = request.form.get('user_id'), request.form.get('pin')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id = ? AND pin = ? AND is_active = 1', (user_id, pin)).fetchone()
        db.close()
        if user:
            session.permanent = True
            session['user_id'], session['user_name'], session['role'] = user['id'], user['name'], user['role']
            if user['role'] == 'manager': return redirect(url_for('dashboard'))
            else: return redirect(url_for('employee_dashboard'))
        else:
            flash('Invalid PIN for active user.', 'danger')
    return render_template('login.html', users=users)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# --- Manager Pages ---
@app.route('/')
@login_required
@manager_required
def dashboard():
    db = get_db()
    
    # --- DASHBOARD IMPROVEMENT: Fetch all employee balances ---
    all_employees = db.execute("SELECT id, name FROM users WHERE role = 'employee' AND is_active = 1 ORDER BY name").fetchall()
    employee_balances = []
    for emp in all_employees:
        balance_info = calculate_employee_balance(db, emp['id'])
        employee_balances.append({
            'id': emp['id'],
            'name': emp['name'],
            'amount_due': balance_info['amount_due']
        })

    today_str = date.today().strftime('%Y-%m-%d')
    employees_present_q = db.execute("SELECT u.id, u.name, b.name as business_name, b.color FROM users u JOIN businesses b ON u.business_id = b.id WHERE u.role = 'employee' AND u.is_active = 1 AND u.id IN (SELECT employee_id FROM attendance WHERE DATE(timestamp) = ? AND event_type = 'Start')", (today_str,)).fetchall()
    all_employees_ids = {r['id'] for r in all_employees}
    present_ids = {e['id'] for e in employees_present_q}
    absent_ids = all_employees_ids - present_ids
    employees_absent_q = []
    if absent_ids:
        placeholders = ','.join('?' * len(absent_ids))
        employees_absent_q = db.execute(f"SELECT u.name, b.name as business_name, b.color FROM users u JOIN businesses b ON u.business_id = b.id WHERE u.is_active = 1 AND u.role = 'employee' AND u.id IN ({placeholders})", tuple(absent_ids)).fetchall()
    
    attendances_q = db.execute("SELECT a.id, u.name as employee_name, a.timestamp, a.event_type, a.details, a.photo_path, a.notes FROM attendance a JOIN users u ON a.employee_id = u.id ORDER BY a.timestamp DESC LIMIT 10").fetchall()
    db.close()
    
    return render_template('manager/dashboard.html', 
                           employees_present=employees_present_q, 
                           employees_absent=employees_absent_q, 
                           attendances=attendances_q,
                           employee_balances=employee_balances) # Pass new data to template

# --- NEW ROUTE: Pay Dues ---
@app.route('/pay_dues/<int:employee_id>', methods=['POST'])
@login_required
@manager_required
def pay_dues(employee_id):
    db = get_db()
    balance_info = calculate_employee_balance(db, employee_id)
    amount_due = balance_info['amount_due']

    if amount_due > 0:
        db.execute('INSERT INTO payments (employee_id, amount, payment_type, date, notes) VALUES (?, ?, ?, ?, ?)',
               (employee_id, amount_due, 'Wages Paid', date.today().strftime('%Y-%m-%d'), 'Full settlement from dashboard'))
        db.commit()
        user = db.execute('SELECT name FROM users WHERE id = ?', (employee_id,)).fetchone()
        flash(f'Successfully paid ₹{amount_due:.2f} to {user["name"]}.', 'success')
    else:
        flash('No payment necessary as there is no amount due.', 'info')
    
    db.close()
    return redirect(url_for('dashboard'))


# --- Remaining routes are unchanged... ---
@app.route('/users')
@login_required
@manager_required
def list_users():
    db = get_db()
    active_users = db.execute("SELECT u.id, u.name, u.phone, u.daily_wage, u.role, b.name as business_name, b.color FROM users u LEFT JOIN businesses b ON u.business_id = b.id WHERE u.is_active = 1 ORDER BY u.name").fetchall()
    inactive_users = db.execute("SELECT u.id, u.name, u.phone, u.daily_wage, u.role, b.name as business_name, b.color FROM users u LEFT JOIN businesses b ON u.business_id = b.id WHERE u.is_active = 0 ORDER BY u.name").fetchall()
    businesses = db.execute('SELECT * FROM businesses ORDER BY name').fetchall()
    db.close()
    return render_template('manager/users.html', active_users=active_users, inactive_users=inactive_users, businesses=businesses)

@app.route('/terminate_user/<int:id>', methods=['POST'])
@login_required
@manager_required
def terminate_user(id):
    db = get_db()
    db.execute('UPDATE users SET is_active = 0 WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash('User has been terminated.', 'success')
    return redirect(url_for('list_users'))

@app.route('/reactivate_user/<int:id>', methods=['POST'])
@login_required
@manager_required
def reactivate_user(id):
    db = get_db()
    db.execute('UPDATE users SET is_active = 1 WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash('User has been reactivated.', 'success')
    return redirect(url_for('list_users'))

@app.route('/delete_user/<int:id>', methods=['POST'])
@login_required
@manager_required
def delete_user(id):
    db = get_db()
    db.execute('DELETE FROM payments WHERE employee_id = ?', (id,))
    db.execute('DELETE FROM attendance WHERE employee_id = ?', (id,))
    db.execute('DELETE FROM users WHERE id = ?', (id,))
    db.commit()
    db.close()
    flash('User and all their associated data have been permanently deleted.', 'warning')
    return redirect(url_for('list_users'))
    
@app.route('/reports')
@login_required
@manager_required
def reports():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * app.config['ITEMS_PER_PAGE']
    count = db.execute('SELECT COUNT(id) FROM attendance').fetchone()[0]
    total_pages = math.ceil(count / app.config['ITEMS_PER_PAGE'])
    attendances = db.execute("SELECT a.*, u.name as employee_name FROM attendance a JOIN users u ON a.employee_id = u.id ORDER BY a.timestamp DESC LIMIT ? OFFSET ?", (app.config['ITEMS_PER_PAGE'], offset)).fetchall()
    db.close()
    return render_template('manager/reports.html', attendances=attendances, page=page, total_pages=total_pages)

@app.route('/employee/dashboard')
@login_required
def employee_dashboard():
    db = get_db()
    employee_id = session['user_id']
    balance_info = calculate_employee_balance(db, employee_id)
    today_str = date.today().strftime('%Y-%m-%d')
    started_rec = db.execute("SELECT id, notes FROM attendance WHERE employee_id = ? AND event_type = 'Start' AND DATE(timestamp) = ?", (employee_id, today_str)).fetchone()
    ended_rec = db.execute("SELECT 1 FROM attendance WHERE employee_id = ? AND event_type = 'End' AND DATE(timestamp) = ?", (employee_id, today_str)).fetchone()
    attendances_rec = db.execute('SELECT * FROM attendance WHERE employee_id = ? ORDER BY timestamp DESC LIMIT 5', (employee_id,)).fetchall()
    db.close()
    return render_template('employee/dashboard.html', 
                           balance_info=balance_info,
                           has_started=bool(started_rec),
                           has_ended=bool(ended_rec),
                           todays_note=started_rec['notes'] if started_rec else '',
                           attendances=attendances_rec)

@app.route('/mark_attendance', methods=['POST'])
@login_required
def mark_attendance():
    employee_id = session.get('user_id')
    event_type = request.form.get('event_type')
    photo_data = request.form.get('photo')
    
    filename = "auto"
    if photo_data and 'data:image' in photo_data:
        try:
            header, encoded = photo_data.split(",", 1)
            binary_data = base64.b64decode(encoded)
            filename = f"{uuid.uuid4().hex}.jpg"
            with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "wb") as f:
                f.write(binary_data)
        except Exception as e:
            flash(f'Error saving photo: {e}', 'danger')
            return redirect(url_for('employee_dashboard'))

    db = get_db()
    today_str = date.today().strftime('%Y-%m-%d')
    details = ""

    if event_type == 'End':
        start_record = db.execute("SELECT timestamp FROM attendance WHERE employee_id = ? AND event_type = 'Start' AND DATE(timestamp) = ? ORDER BY timestamp ASC LIMIT 1", (employee_id, today_str)).fetchone()
        if start_record:
            start_time_utc = start_record['timestamp'].replace(tzinfo=pytz.utc)
            end_time_utc = datetime.now(pytz.utc)
            duration = end_time_utc - start_time_utc
            details = "Half Day" if duration.total_seconds() < 5 * 3600 else "Full Day"
        else:
            details = "Full Day (No Start)"

    db.execute('INSERT INTO attendance (employee_id, event_type, photo_path, details, timestamp) VALUES (?, ?, ?, ?, ?)',
               (employee_id, event_type, filename, details, datetime.now(pytz.utc)))
    db.commit()
    db.close()
    flash(f'Attendance for "{event_type}" marked successfully!', 'success')
    return redirect(url_for('employee_dashboard'))

@app.route('/add_note', methods=['POST'])
@login_required
def add_note():
    employee_id = session.get('user_id')
    note_text = request.form.get('notes')
    today_str = date.today().strftime('%Y-%m-%d')
    db = get_db()
    start_record = db.execute("SELECT id FROM attendance WHERE employee_id = ? AND event_type = 'Start' AND DATE(timestamp) = ? ORDER BY timestamp ASC LIMIT 1", (employee_id, today_str)).fetchone()
    if start_record:
        db.execute("UPDATE attendance SET notes = ? WHERE id = ?", (note_text, start_record['id']))
        db.commit()
        flash('Your work note for today has been saved.', 'success')
    else:
        flash('Could not save note. Please mark your job start first.', 'warning')
    db.close()
    return redirect(url_for('employee_dashboard'))

@app.route('/add_user', methods=['POST'])
@login_required
@manager_required
def add_user():
    db = get_db()
    db.execute('INSERT INTO users (name, phone, business_id, daily_wage, role, pin) VALUES (?, ?, ?, ?, ?, ?)',
               (request.form['name'], request.form['phone'], request.form['business_id'],
                request.form.get('daily_wage', 0, type=float), request.form['role'], request.form.get('pin', '1234')))
    db.commit()
    db.close()
    flash('User added successfully!', 'success')
    return redirect(url_for('list_users'))

@app.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@login_required
@manager_required
def edit_user(id):
    db = get_db()
    if request.method == 'POST':
        db.execute('UPDATE users SET name=?, phone=?, business_id=?, daily_wage=?, role=? WHERE id=?', 
                      (request.form['name'], request.form['phone'], request.form['business_id'],
                      request.form.get('daily_wage', 0, type=float), request.form['role'], id))
        db.commit()
        db.close()
        flash('User details updated!', 'success')
        return redirect(url_for('list_users'))
    user = db.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()
    businesses = db.execute('SELECT * FROM businesses ORDER BY name').fetchall()
    db.close()
    return render_template('manager/edit_user.html', user=user, businesses=businesses)
    
@app.route('/user_profile/<int:id>')
@login_required
@manager_required
def user_profile(id):
    db = get_db()
    user = db.execute('SELECT u.*, b.name as business_name, b.color FROM users u LEFT JOIN businesses b ON u.business_id = b.id WHERE u.id = ?', (id,)).fetchone()
    balance_info = calculate_employee_balance(db, id)
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * app.config['ITEMS_PER_PAGE']
    count = db.execute('SELECT COUNT(id) FROM attendance WHERE employee_id = ?', (id,)).fetchone()[0]
    total_pages = math.ceil(count / app.config['ITEMS_PER_PAGE'])
    attendances = db.execute('SELECT * FROM attendance WHERE employee_id = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?', (id, app.config['ITEMS_PER_PAGE'], offset)).fetchall()
    db.close()
    return render_template('manager/user_profile.html', user=user, balance_info=balance_info, attendances=attendances, page=page, total_pages=total_pages)

@app.route('/pin_management', methods=['GET', 'POST'])
@login_required
@manager_required
def pin_management():
    db = get_db()
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        new_pin = request.form.get('new_pin')
        if len(new_pin) >= 4:
            db.execute('UPDATE users SET pin = ? WHERE id = ?', (new_pin, user_id))
            db.commit()
            flash('PIN updated successfully!', 'success')
        else:
            flash('PIN must be at least 4 digits.', 'danger')
    users = db.execute('SELECT id, name, role, pin FROM users ORDER BY role, name').fetchall()
    db.close()
    return render_template('manager/pin_management.html', users=users)
    
@app.route('/payments', methods=['GET', 'POST'])
@login_required
@manager_required
def payments():
    db = get_db()
    if request.method == 'POST':
        db.execute('INSERT INTO payments (employee_id, amount, payment_type, date, notes) VALUES (?, ?, ?, ?, ?)',
               (request.form['employee_id'], float(request.form['amount']), request.form['payment_type'], 
                request.form.get('date', date.today().strftime('%Y-%m-%d')), request.form.get('notes')))
        db.commit()
        flash(f"{request.form['payment_type']} of ₹{request.form['amount']} added!", 'success')
        return redirect(url_for('payments'))

    users_q = db.execute("SELECT id, name FROM users WHERE role = 'employee' AND is_active = 1 ORDER BY name").fetchall()
    employee_balances = [dict(id=u['id'], name=u['name'], amount_due=calculate_employee_balance(db, u['id'])['amount_due']) for u in users_q]
    transactions_q = db.execute("SELECT p.id, u.name as employee_name, p.amount, p.payment_type, p.date, p.notes FROM payments p JOIN users u ON p.employee_id = u.id ORDER BY p.date DESC, p.id DESC LIMIT 20").fetchall()
    db.close()
    return render_template('manager/payments.html', employee_balances=employee_balances, transactions=transactions_q, users=users_q)

@app.route('/businesses', methods=['GET'])
@login_required
@manager_required
def list_businesses():
    db = get_db()
    businesses = db.execute("SELECT b.id, b.name, b.color, COUNT(u.id) as employee_count FROM businesses b LEFT JOIN users u ON b.id = u.business_id AND u.role = 'employee' GROUP BY b.id, b.name, b.color ORDER BY b.name").fetchall()
    db.close()
    return render_template('manager/businesses.html', businesses=businesses)

@app.route('/add_business', methods=['POST'])
@login_required
@manager_required
def add_business():
    name, color = request.form.get('name'), request.form.get('color', '#cccccc')
    if name:
        db = get_db()
        db.execute('INSERT INTO businesses (name, color) VALUES (?, ?)', (name, color))
        db.commit()
        db.close()
        flash(f'Business "{name}" added!', 'success')
    return redirect(url_for('list_businesses'))
    
@app.route('/edit_business/<int:id>', methods=['GET', 'POST'])
@login_required
@manager_required
def edit_business(id):
    db = get_db()
    if request.method == 'POST':
        db.execute('UPDATE businesses SET name=?, color=? WHERE id=?', (request.form['name'], request.form['color'], id))
        db.commit()
        db.close()
        flash('Business details updated!', 'success')
        return redirect(url_for('list_businesses'))
    business = db.execute('SELECT * FROM businesses WHERE id = ?', (id,)).fetchone()
    db.close()
    return render_template('manager/edit_business.html', business=business)

@app.route('/api/monthly_attendance')
@login_required
@manager_required
def api_monthly_attendance():
    month_str = request.args.get('month', date.today().strftime('%Y-%m'))
    db = get_db()
    users = db.execute("SELECT id, name FROM users WHERE role = 'employee' AND is_active = 1 ORDER BY name").fetchall()
    recs = db.execute("SELECT employee_id, DATE(timestamp) as adate, details FROM attendance WHERE strftime('%Y-%m', timestamp) = ? AND event_type = 'End'", (month_str,)).fetchall()
    db.close()
    
    attendance_map = {}
    for rec in recs:
        if rec['adate'] not in attendance_map:
            attendance_map[rec['adate']] = {}
        status = 'H' if rec['details'] == 'Half Day' else 'P'
        attendance_map[rec['adate']][rec['employee_id']] = status

    user_list = [{'id': u['id'], 'name': u['name']} for u in users]
    return jsonify({'users': user_list, 'attendance': attendance_map})

@app.route('/api/payment_data')
@login_required
@manager_required
def api_payment_data():
    month_str, group_by = request.args.get('month', date.today().strftime('%Y-%m')), request.args.get('group_by', 'business')
    db = get_db()
    if group_by == 'employee':
        query = "SELECT u.name as label, SUM(p.amount) as total FROM payments p JOIN users u ON p.employee_id = u.id WHERE strftime('%Y-%m', p.date) = ? GROUP BY u.name ORDER BY total DESC"
    else:
        query = "SELECT b.name as label, SUM(p.amount) as total FROM payments p JOIN users u ON p.employee_id = u.id JOIN businesses b ON u.business_id = b.id WHERE strftime('%Y-%m', p.date) = ? GROUP BY b.name ORDER BY total DESC"
    data = db.execute(query, (month_str,)).fetchall()
    db.close()
    return jsonify({'labels': [r['label'] for r in data], 'values': [r['total'] for r in data]})
    
# --- Auto End Day Scheduler ---
def auto_end_day_job():
    with app.app_context():
        db = get_db()
        today_str = date.today().strftime('%Y-%m-%d')
        employees_to_end = db.execute("""
            SELECT id FROM users WHERE role = 'employee' AND is_active = 1 AND id IN 
            (SELECT employee_id FROM attendance WHERE DATE(timestamp) = ? AND event_type = 'Start') 
            AND id NOT IN 
            (SELECT employee_id FROM attendance WHERE DATE(timestamp) = ? AND event_type = 'End')
        """, (today_str, today_str)).fetchall()

        for user in employees_to_end:
            db.execute('INSERT INTO attendance (employee_id, event_type, photo_path, details, timestamp) VALUES (?, ?, ?, ?, ?)',
                       (user['id'], 'End', 'auto', 'Auto Ended', datetime.now(pytz.utc)))
        db.commit()
        db.close()
        if employees_to_end:
            print(f"Auto-ended day for {len(employees_to_end)} employees.")

scheduler = BackgroundScheduler(timezone=str(IST))
scheduler.add_job(auto_end_day_job, 'cron', hour=20, minute=0)

if __name__ == '__main__':
    # Initialize DB for local development if it doesn't exist
    if not os.path.exists(DATABASE):
        with app.app_context():
            init_db()
            print('Initialized the database for local development.')
            
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        if not scheduler.running:
            scheduler.start()
            print("Scheduler started.")
    app.run(host='0.0.0.0', port=5000)

