# app.py

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)

# -------------------------
# DATABASE SETUP
# -------------------------

def init_db():
    conn = sqlite3.connect('bookings.db')
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
    return render_template('index.html')

# Check availability
@app.route('/check', methods=['POST'])
def check():
    data = request.json
    date = data.get('date')
    time = data.get('time')

    conn = sqlite3.connect('bookings.db')
    c = conn.cursor()
    c.execute("SELECT * FROM bookings WHERE date=? AND time=?", (date, time))
    exists = c.fetchone()
    conn.close()

    if exists:
        return jsonify({'available': False})
    else:
        return jsonify({'available': True})

# Save a booking
@app.route('/book', methods=['POST'])
def book():
    data = request.json
    name = data.get('name')
    phone = data.get('phone')
    date = data.get('date')
    time = data.get('time')

    # Check again here
    conn = sqlite3.connect('bookings.db')
    c = conn.cursor()
    c.execute("SELECT * FROM bookings WHERE date=? AND time=?", (date, time))
    exists = c.fetchone()

    if exists:
        conn.close()
        return jsonify({
            'success': False,
            'message': 'That time is already booked. Please select another time or call the College on 1300-88-48-10.'
        })

    # Save booking
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO bookings (name, phone, date, time, timestamp) 
                 VALUES (?, ?, ?, ?, ?)''', (name, phone, date, time, timestamp))
    conn.commit()
    conn.close()

    # Send emails
    user_msg = f"Hi {name},\n\nYour Engagement Assessment call has been booked for {date} at {time}.\nIf you need to make changes, call us on 1300-88-48-10.\n\nACOP Team"
    admin_msg = f"New booking:\nName: {name}\nPhone: {phone}\nDate: {date}\nTime: {time}\nTimestamp: {timestamp}"

    user_email_sent = send_email(FROM_EMAIL, "Your Assessment Booking", user_msg)
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
    app.run(host="0.0.0.0", port=port, debug=False)
