# app.py
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import threading
import re

# Configuration
app = Flask(__name__, template_folder='templates')
CORS(app, resources={r"/*": {"origins": os.environ.get('CORS_ORIGINS', '*')}})

# Logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# -------------------------
# DATABASE SETUP
# -------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), 'bookings.db')

def init_db():
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            # Improve concurrency mode
            try:
                conn.execute('PRAGMA journal_mode=WAL;')
            except Exception:
                logger.debug("Could not set WAL mode; continuing")
            conn.execute('''CREATE TABLE IF NOT EXISTS bookings (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL,
                            email TEXT NOT NULL,
                            phone TEXT NOT NULL,
                            date TEXT NOT NULL,
                            time TEXT NOT NULL,
                            timestamp TEXT NOT NULL,
                            UNIQUE(date, time)
                        )''')
            conn.commit()
    except Exception:
        logger.exception('DB init error')

init_db()

# -------------------------
# EMAIL SETUP (from environment for Render)
# -------------------------
SMTP_SERVER = os.environ.get('SMTP_SERVER')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 25))
SMTP_USERNAME = os.environ.get('17d873b3a11a38')
SMTP_PASSWORD = os.environ.get('453b9c740a0729')
SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
FROM_EMAIL = os.environ.get('FROM_EMAIL', 'enquiries@acop.edu.au')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'johnc@acop.edu.au')

def send_email(to_email, subject, body):
    if not SMTP_SERVER:
        logger.warning('SMTP server not configured; skipping email to %s', to_email)
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                try:
                    server.starttls()
                except Exception:
                    logger.debug('STARTTLS failed or not supported')
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info('Email sent to %s', to_email)
        return True
    except Exception:
        logger.exception('Email error when sending to %s', to_email)
        return False

def send_email_async(to_email, subject, body):
    thread = threading.Thread(target=send_email, args=(to_email, subject, body), daemon=True)
    thread.start()

# -------------------------
# Helpers / Validation
# -------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9 \-()+]{6,20}$")

def validate_date_time(date_str, time_str):
    # Expecting date YYYY-MM-DD and time HH:MM (24-hour)
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return dt
    except Exception:
        return None

# -------------------------
# ROUTES
# -------------------------
@app.route('/')
def home():
    try:
        return render_template('index.html')
    except Exception:
        logger.exception('Template render error')
        return "Template error", 500

# Check availability
@app.route('/check', methods=['POST'])
def check():
    data = request.get_json(silent=True) or {}
    date = data.get('date')
    time = data.get('time')

    if not date or not time:
        return jsonify({'available': False, 'error': 'Missing date or time'}), 400

    if not validate_date_time(date, time):
        return jsonify({'available': False, 'error': 'Invalid date/time format'}), 400

    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM bookings WHERE date=? AND time=? LIMIT 1", (date, time))
            exists = c.fetchone()
    except Exception:
        logger.exception('DB check error')
        return jsonify({'available': False, 'error': 'Database error'}), 500

    return jsonify({'available': not bool(exists)})

# Save a booking
@app.route('/book', methods=['POST'])
def book():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    phone = (data.get('phone') or '').strip()
    date = (data.get('date') or '').strip()
    time = (data.get('time') or '').strip()

    # Validate inputs
    if not all([name, email, phone, date, time]):
        return jsonify({'success': False, 'message': 'All fields are required'}), 400

    if not EMAIL_RE.match(email):
        return jsonify({'success': False, 'message': 'Invalid email format'}), 400

    if not PHONE_RE.match(phone):
        return jsonify({'success': False, 'message': 'Invalid phone format'}), 400

    dt = validate_date_time(date, time)
    if not dt:
        return jsonify({'success': False, 'message': 'Invalid date/time format. Expect YYYY-MM-DD and HH:MM'}), 400

    # Normalize date/time to store
    date_norm = dt.strftime('%Y-%m-%d')
    time_norm = dt.strftime('%H:%M')

    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            c = conn.cursor()
            # Insert booking (UNIQUE constraint will prevent duplicates)
            timestamp = datetime.utcnow().isoformat() + 'Z'
            try:
                c.execute('''INSERT INTO bookings (name, email, phone, date, time, timestamp)
                             VALUES (?, ?, ?, ?, ?, ?)''', (name, email, phone, date_norm, time_norm, timestamp))
                conn.commit()
            except sqlite3.IntegrityError:
                # Conflict on unique(date, time)
                return jsonify({
                    'success': False,
                    'message': 'That time is already booked. Please select another time or call the College on 1300-88-48-10.'
                }), 409
    except Exception:
        logger.exception('DB booking error')
        return jsonify({'success': False, 'message': 'Database error'}), 500

    # Prepare emails (send asynchronously so the request isn't blocked)
    user_msg = f"Hi {name},\n\nYour Engagement Assessment call has been booked for {date_norm} at {time_norm}.\nIf you need to make changes, call us on 1300-88-48-10.\n\nACOP Team"
    admin_msg = f"New booking:\nName: {name}\nEmail: {email}\nPhone: {phone}\nDate: {date_norm}\nTime: {time_norm}\nTimestamp: {timestamp}"

    try:
        send_email_async(email, "Your Assessment Booking", user_msg)
        send_email_async(ADMIN_EMAIL, "New Assessment Booking", admin_msg)
        email_note = 'Email notifications queued.'
    except Exception:
        logger.exception('Error queueing emails')
        email_note = 'Failed to queue email notifications.'

    return jsonify({'success': True, 'message': 'Booking confirmed.', 'note': email_note}), 201

# -------------------------
# RUN APP
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    app.run(host="0.0.0.0", port=port, debug=debug)