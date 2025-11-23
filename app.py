# ================================================
# app.py – ACOP Assessment Booking Chatbot (FINAL)
# Live at: https://acop-chatbot-demo-vxow.onrender.com
# ================================================
import os
import uuid
import sqlite3
import smtplib
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import Flask, request, jsonify, make_response
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event

app = Flask(__name__)
DB_FILE = "bookings.db"

# Sydney timezone
SYDNEY_TZ = ZoneInfo("Australia/Sydney")
TIME_SLOTS = ["09:00", "11:00", "15:30"]

# Mailtrap (sandbox)
SMTP_SERVER = "sandbox.smtp.mailtrap.io"
SMTP_PORT = 2525
SMTP_USERNAME = "17d873b3a11a38"
SMTP_PASSWORD = "453b9c740a0729"
FROM_EMAIL = "enquiries@acop.edu.au"
ADMIN_EMAIL = "johnc@acop.edu.au"

# In-memory sessions
SESSIONS = {}

# ================================================
# DATABASE
# ================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, email TEXT, date TEXT, time TEXT
    )""")
    conn.commit()
    conn.close()

def save_booking(name, email, date, time):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO bookings (name,email,date,time) VALUES (?,?,?,?)",
                (name, email, date, time))
    conn.commit()
    conn.close()

def get_booked_times(date_str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT time FROM bookings WHERE date=?", (date_str,))
    booked = [row[0] for row in cur.fetchall()]
    conn.close()
    return booked

# ================================================
# SMART AVAILABILITY (Sydney time + same-day cutoff)
# ================================================
def get_available_slots_for_date(date_str):
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    now_sydney = datetime.now(SYDNEY_TZ)
    today_str = now_sydney.strftime("%Y-%m-%d")

    booked = get_booked_times(date_str)
    available = []

    for slot in TIME_SLOTS:
        if slot in booked:
            continue
        # Same-day cutoff
        if date_str == today_str:
            slot_dt = datetime.strptime(f"{date_str} {slot}", "%Y-%m-%d %H:%M")
            slot_dt = slot_dt.replace(tzinfo=SYDNEY_TZ)
            if slot_dt <= now_sydney:
                continue
        available.append(slot)
    return available

# ================================================
# ICS + EMAIL (with your branded template)
# ================================================
def build_ics(name, date_str, time_str):
    event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    event_dt = event_dt.replace(tzinfo=SYDNEY_TZ)
    cal = Calendar()
    cal.add('prodid', '-//ACOP Booking//')
    cal.add('version', '2.0')
    event = Event()
    event.add('summary', 'ACOP Assessment Call')
    event.add('dtstart', event_dt)
    event.add('dtend', event_dt + timedelta(minutes=60))  # Your change to 60 min
    event.add('description', f"Assessment call with {name}")
    cal.add_component(event)
    return cal.to_ical()

def send_email_with_ics(name, email, date, time_str):
    ics_data = build_ics(name, date, time_str)

    # Your branded HTML template
    html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>ACOP Assessment Booking</title>
  <style>
    body {
      margin: 0;
      padding: 0;
      background: #f2f2f2;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      color: #2d3748;
    }
    .container {
      max-width: 600px;
      margin: 20px auto;
      background: #ffffff;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
    }
    .header {
      background: #004cbf; /* ACOP Navy */
      color: white;
      padding: 30px 20px;
      text-align: center;
    }
    .header img {
      height: 50px;
      margin-bottom: 10px;
    }
    .header h1 {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
    }
    .content {
      padding: 30px;
      line-height: 1.7;
    }
    .booking-details {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 20px;
      margin: 20px 0;
      font-size: 16px;
    }
    .booking-details strong {
      color: #1a365d;
    }
    .btn {
      display: inline-block;
      background: #0098ea;
      color: white !important;
      padding: 14px 28px;
      text-decoration: none;
      border-radius: 8px;
      font-weight: 600;
      margin: 20px 0;
      font-size: 16px;
    }
    .btn:hover {
      background: #004cbf;
    }
    .footer {
      background: #004cbf;
      color: #ffffff;
      padding: 20px;
      text-align: center;
      font-size: 13px;
    }
    .footer a {
      color: #ffffff;
      text-decoration: none;
    }
    @media (max-width: 480px) {
      .container { margin: 10px; border-radius: 8px; }
      .header, .content { padding: 20px; }
    }
  </style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <img src="https://mailsend-email-assets.mailtrap.io/b3ggvuuwep32geyb8s8dwn7qzh6o.png" alt="ACOP Logo" />
      <h1>Assessment Call Confirmed</h1>
    </div>

    <!-- Content -->
    <div class="content">
      <p>Hi <strong>{name}</strong>,</p>
      <p>Great news! Your <strong>assessment call</strong> with ACOP has been successfully booked.</p>

      <div class="booking-details">
        <p><strong>Date:</strong> {date}</p>
        <p><strong>Time:</strong> {time_str}</p>
        <p><strong>Duration:</strong> 60 minutes</p>
      </div>

      <p>An <strong>ICS calendar file</strong> is attached below — just click to add it to your Google Calendar, Outlook, or Apple Calendar.</p>

      <p style="text-align: center;">
        <a href="#" class="btn">Add to Calendar</a>
      </p>

      <p><strong>Need to reschedule?</strong><br>
      Reply to this email or call us at <strong>1300 123 456</strong>.</p>

      <p>We look forward to speaking with you!</p>
      <p><em>— The ACOP Team</em></p>
    </div>

    <!-- Footer -->
    <div class="footer">
      <p>Australian College of Professionals | <a href="https://acop.edu.au">acop.edu.au</a></p>
      <p>Level 2, 464 Kent Street, Sydney NSW 2000 | enquiries@acop.edu.au</p>
      <p>&copy; 2025 ACOP. All rights reserved.</p>
    </div>
  </div>
</body>
</html>
    """.format(name=name, date=datetime.strptime(date, "%Y-%m-%d").strftime("%A %d %B %Y"), time_str=time_str)

    # Send to Student
    msg = EmailMessage()
    msg["Subject"] = "Your Assessment Booking — ACOP"
    msg["From"] = FROM_EMAIL
    msg["To"] = email
    msg.set_content("Your assessment call has been booked. Check the HTML version for details.")
    msg.add_alternative(html_template, subtype='html')
    msg.add_attachment(ics_data, maintype="application", subtype="ics", filename="booking.ics")

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(msg)

    time.sleep(2)

    # Admin copy (plain text)
    admin_msg = EmailMessage()
    admin_msg["Subject"] = "New Assessment Booking (Admin Copy)"
    admin_msg["From"] = FROM_EMAIL
    admin_msg["To"] = ADMIN_EMAIL
    admin_msg.set_content(f"""
New booking received:
Name: {name}
Email: {email}
Date: {date}
Time: {time_str}
    """)
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(admin_msg)

    return True, None

# ================================================
# RUN
# ================================================
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key")
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)