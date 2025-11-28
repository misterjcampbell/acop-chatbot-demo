# app.py
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

# -------------------------
# DATABASE SETUP (Render-safe)
# -------------------------

# On Render, the filesystem is read-only except /tmp
# So we force the SQLite DB into the temp directory
if os.environ.get('RENDER') or os.environ.get('RAILWAY') or os.environ.get('FLY_APP_NAME'):
    DATABASE_PATH = os.path.join(tempfile.gettempdir(), 'bookings.db')
else:
    DATABASE_PATH = os.path.join(os.getcwd(), 'bookings.db')

# Optional: Print where DB is stored (helpful for debugging)
print(f"Using database at: {DATABASE_PATH}")

def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
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
    print("Database initialized successfully.")

# Initialize DB on startup
init_db()

# -------------------------
# EMAIL SETUP (Mailtrap Sandbox)
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
        print(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"Email failed to {to_email}: {e}")
        return False

# -------------------------
# ROUTES
# -------------------------

@app.route('/')
def home():
    return render_template('index.html')

# Check availability
@app.route('/check', methods=['POST'])
def check():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'available': False, 'error': 'No data received'}), 400

        date = data.get('date')
        time = data.get('time')

        if not date or not time:
            return jsonify({'available': False, 'error': 'Date and time required'}), 400

        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM bookings WHERE date = ? AND time = ?", (date, time))
        exists = c.fetchone() is not None
        conn.close()

        return jsonify({'available': not exists})
    
    except Exception as e:
        print(f"Error in /check: {e}")
        return jsonify({'available': False, 'error': 'Server error'}), 500

# Save a booking
@app.route('/book', methods=['POST'])
def book():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400

        name = data.get('name')
        phone = data.get('phone')
        date = data.get('date')
        time = data.get('time')

        if not all([name, phone, date, time]):
            return jsonify({'success': False, 'message': 'All fields are required'}), 400

        # Double-check availability (race condition protection)
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM bookings WHERE date = ? AND time = ?", (date, time))
        if c.fetchone():
            conn.close()
            return jsonify({
                'success': False,
                'message': 'That time is already booked. Please select another time or call the College on 1300-88-48-10.'
            }), 409

        # Save booking
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute('''INSERT INTO bookings (name, phone, date, time, timestamp)
                     VALUES (?, ?, ?, ?, ?)''', (name, phone, date, time, timestamp))
        conn.commit()
        conn.close()

        # Send emails
        user_msg = f"Hi {name},\n\nYour Engagement Assessment call has been booked for {date} at {time}.\n\nIf you need to make changes, please call us on 1300-88-48-10.\n\nThank you,\nACOP Team"
        
        admin_msg = f"New Assessment Booking!\n\nName: {name}\nPhone: {phone}\nDate: {date}\nTime: {time}\nBooked at: {timestamp}"

        user_sent = send_email(FROM_EMAIL, "Your ACOP Assessment Call Booking Confirmed", user_msg)
        admin_sent = send_email(ADMIN_EMAIL, "New Booking - ACOP Assessment Call", admin_msg)

        if user_sent and admin_sent:
            return jsonify({'success': True, 'message': 'Booking confirmed! Confirmation email sent.'})
        else:
            return jsonify({'success': True, 'message': 'Booking saved! (Email delivery issue – admin notified manually if needed)'})

    except Exception as e:
        print(f"Error in /book: {e}")
        return jsonify({'success': False, 'message': 'Server error. Please try again or call 1300-88-48-10.'}), 500

# -------------------------
# RUN APP
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
