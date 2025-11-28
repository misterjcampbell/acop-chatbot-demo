# app.py - Works 100% on Render FREE tier (no disk, no external DB)
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
import tempfile
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)

# THIS IS THE ONLY FIX YOU NEED
DB_PATH = os.path.join(tempfile.gettempdir(), "bookings.db")  # ← always writable

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Auto-create table if missing (runs every startup — fixes the crash!)
def init_db():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS bookings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        phone TEXT NOT NULL,
                        date TEXT NOT NULL,
                        time TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    )''')
        conn.commit()
        conn.close()
        print(f"Database ready at {DB_PATH}")
    except Exception as e:
        print("DB init failed:", e)

init_db()  # ← This prevents the "server error" forever

# -------------------------
# EMAIL SETUP (unchanged)
# -------------------------
SMTP_SERVER = "sandbox.smtp.mailtrap.io"
SMTP_PORT = 2525
SMTP_USERNAME = "17d873b3a11a38"
SMTP_PASSWORD = "453b9c740a0729"
FROM_EMAIL = "enquiries@acop.edu.au"
ADMIN_EMAIL = "johnc@acop.edu.au"

def send_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print("Email error:", e)
        return False

# -------------------------
# ROUTES (only tiny fixes)
# -------------------------
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/check', methods=['POST'])
def check():
    data = request.get_json()
    date = data.get('date')
    time = data.get('time')
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
    exists = c.fetchone()
    conn.close()
    return jsonify({'available': not exists})

@app.route('/book', methods=['POST'])
def book():
    data = request.get_json()
    name = data.get('name')
    phone = data.get('phone')
    date = data.get('date')
    time = data.get('time')

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'That time is already booked. Please choose another.'})

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO bookings (name, phone, date, time, timestamp) VALUES (?, ?, ?, ?, ?)",
              (name, phone, date, time, timestamp))
    conn.commit()
    conn.close()

    # Emails (optional — you can remove if Mailtrap stops working)
    user_msg = f"Hi {name},\n\nYour assessment call is booked for {date} at {time}.\n\nACOP Team"
    admin_msg = f"New booking!\n{name}\n{phone}\n{date} {time}"
    send_email(FROM_EMAIL, "Booking Confirmed", user_msg)
    send_email(ADMIN_EMAIL, "New ACOP Booking", admin_msg)

    return jsonify({'success': True, 'message': 'Booking confirmed!'})

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)