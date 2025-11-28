# app.py
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)

# -------------------------
# DATABASE SETUP
# -------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), 'bookings.db')

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS bookings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        phone TEXT NOT NULL,
                        date TEXT NOT NULL,
                        time TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    )''')
        conn.commit()
    except Exception as e:
        print("DB init error:", e)
    finally:
        conn.close()

init_db()

# -------------------------
# EMAIL SETUP
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
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print("Email error:", e)
        return False

# -------------------------
# ROUTES
# -------------------------
@app.route('/')
def home():
    try:
        return render_template('index.html')
    except Exception as e:
        return f"Template error: {e}", 500

# Check availability
@app.route('/check', methods=['POST'])
def check():
    data = request.json or {}
    date = data.get('date')
    time = data.get('time')

    if not date or not time:
        return jsonify({'available': False, 'error': 'Missing date or time'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM bookings WHERE date=? AND time=?", (date, time))
        exists = c.fetchone()
    except Exception as e:
        print("DB check error:", e)
        return jsonify({'available': False, 'error': 'Database error'}), 500
    finally:
        conn.close()

    return jsonify({'available': not bool(exists)})

# Save a booking
@app.route('/book', methods=['POST'])
def book():
    data = request.json or {}
    name = data.get('name')
    email = data.get('email')
    phone = data.get('phone')
    date = data.get('date')
    time = data.get('time')

    # Validate inputs
    if not all([name, email, phone, date, time]):
        return jsonify({'success': False, 'message': 'All fields are required'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Check for conflict
        c.execute("SELECT * FROM bookings WHERE date=? AND time=?", (date, time))
        exists = c.fetchone()
        if exists:
            return jsonify({
                'success': False,
                'message': 'That time is already booked. Please select another time or call the College on 1300-88-48-10.'
            })

        # Insert booking
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute('''INSERT INTO bookings (name, email, phone, date, time, timestamp)
                     VALUES (?, ?, ?, ?, ?, ?)''', (name, email, phone, date, time, timestamp))
        conn.commit()
    except Exception as e:
        print("DB booking error:", e)
        return jsonify({'success': False, 'message': 'Database error'}), 500
    finally:
        conn.close()

    # Send emails
    user_msg = f"Hi {name},\n\nYour Engagement Assessment call has been booked for {date} at {time}.\nIf you need to make changes, call us on 1300-88-48-10.\n\nACOP Team"
    admin_msg = f"New booking:\nName: {name}\nEmail: {email}\nPhone: {phone}\nDate: {date}\nTime: {time}\nTimestamp: {timestamp}"

    user_email_sent = send_email(email, "Your Assessment Booking", user_msg)
    admin_email_sent = send_email(ADMIN_EMAIL, "New Assessment Booking", admin_msg)

    if not user_email_sent or not admin_email_sent:
        return jsonify({
            'success': True,
            'message': 'Booking saved but failed to send email notifications.'
        })

    return jsonify({'success': True, 'message': 'Booking confirmed and emails sent successfully.'})

# -------------------------
# RUN APP
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)