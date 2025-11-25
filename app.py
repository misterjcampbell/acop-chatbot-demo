# -------------------------------------------------
# ACOP BOOKING CHATBOT – FINAL BULLETPROOF VERSION
# -------------------------------------------------
import os
import uuid
import sqlite3
import smtplib
import csv
import io
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import Flask, request, jsonify, make_response, session, redirect, url_for
from functools import wraps
from textwrap import dedent

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "prod-key-change-me")
DB_FILE = "bookings.db"

# ----- Mailtrap (test) -----
SMTP_SERVER = "sandbox.smtp.mailtrap.io"
SMTP_PORT = 2525
SMTP_USERNAME = "17d873b3a11a38"
SMTP_PASSWORD = "453b9c740a0729"
FROM_EMAIL = "enquiries@acop.edu.au"
ADMIN_EMAIL = "johnc@acop.edu.au"

# ----- Admin Login -----
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "acopadmin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "YourStrongPass2025!")

# ----- Booking Rules -----
TIME_SLOTS = ["09:00", "11:00", "15:30"]
SESSIONS = {}

# -------------------------------------------------
# DATABASE
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, email TEXT, phone TEXT, date TEXT, time TEXT
    )""")
    conn.commit()
    conn.close()

# Add phone to save_booking
def save_booking(name, email, phone, date, time_slot):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO bookings (name, email, phone, date, time) VALUES (?, ?, ?, ?, ?)",
                (name, email, phone, date, time_slot))
    conn.commit()
    conn.close()

def is_time_booked(date, time_slot):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date = ? AND time = ?", (date, time_slot))
    result = cur.fetchone() is not None
    conn.close()
    return result

def get_booked_times(date):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT time FROM bookings WHERE date = ?", (date,))
    result = [row[0] for row in cur.fetchall()]
    conn.close()
    return result

# -------------------------------------------------
# PAST DATE BLOCKER
def is_past_date(date_str):
    try:
        selected = datetime.strptime(date_str, "%Y-%m-%d")
        today = datetime.now().date()
        return selected.date() < today
    except:
        return False

# -------------------------------------------------
# ICS + EMAIL (beautiful version)
def build_ics(name, date_str, time_str):
    from icalendar import Calendar, Event
    event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    cal = Calendar()
    cal.add("prodid", "-//ACOP Booking//")
    cal.add("version", "2.0")
    event = Event()
    event.add("summary", "Assessment Call — ACOP")
    event.add("dtstart", event_dt)
    event.add("dtend", event_dt + timedelta(minutes=60))
    event.add("description", f"Assessment call for {name}")
    cal.add_component(event)
    return cal.to_ical()

def send_email_with_ics(name, email, phone, date, time_str):
    ics_data = build_ics(name, date, time_str)
    display_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ margin:0; padding:0; background:#f0f4f8; font-family:Arial,sans-serif; }}
            .container {{ max-width:600px; margin:30px auto; background:white; border-radius:16px; overflow:hidden; box-shadow:0 10px 30px rgba(0,0,0,0.1); }}
            .header {{ background:#004cbf; color:white; padding:40px 20px; text-align:center; }}
            .header img {{ height:50px; margin-bottom:15px; }}
            .header h1 {{ margin:0; font-size:28px; }}
            .content {{ padding:40px 30px; color:#2d3748; line-height:1.7; }}
            .details {{ background:#f8fafc; border-radius:12px; padding:25px; margin:25px 0; border:1px solid #e2e8f0; }}
            .details p {{ margin:12px 0; font-size:16px; }}
            .btn {{ display:inline-block; background:#0098ea; color:white; padding:16px 32px; text-decoration:none; border-radius:50px; font-weight:600; font-size:17px; margin:20px 0; }}
            .footer {{ background:#004cbf; color:white; padding:25px; text-align:center; font-size:13px; }}
            .footer a {{ color:white; text-decoration:none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <img src="https://acop.edu.au/wp-content/uploads/2023/06/ACOP-Logo-White.png" alt="ACOP">
                <h1>Assessment Call Confirmed</h1>
            </div>
            <div class="content">
                <p>Hi <strong>{name}</strong>,</p>
                <p>Great news! Your assessment call with ACOP has been successfully booked.</p>
                <div class="details">
                    <p><strong>Date:</strong> {display_date}</p>
                    <p><strong>Time:</strong> {time_str}</p>
                    <p><strong>Duration:</strong> 60 minutes</p>
                </div>
                <p>An ICS calendar file is attached — just click to add it to your calendar.</p>
                <p style="text-align:center;"><a href="#" class="btn">Add to Calendar</a></p>
                <p><strong>Need to reschedule?</strong><br>Reply to this email or call us at <strong>1300 88 48 10</strong>.</p>
                <p>We look forward to speaking with you!</p>
                <p><em>— The ACOP Team</em></p>
            </div>
            <div class="footer">
                <p>Australian College of Professionals | <a href="https://acop.edu.au">acop.edu.au</a></p>
                <p>Level 2, 464 Kent Street, Sydney NSW 2000 | enquiries@acop.edu.au</p>
                <p>&copy; 2025 ACOP. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

    msg = EmailMessage()
    msg["Subject"] = "Your ACOP Assessment Call is Confirmed"
    msg["From"] = FROM_EMAIL
    msg["To"] = email
    msg.set_content("Your booking is confirmed.")
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(ics_data, maintype="application", subtype="ics", filename="ACOP-Assessment-Call.ics")

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(msg)

    # Admin copy
    admin_msg = EmailMessage()
    admin_msg["Subject"] = f"New Booking: {name} ({display_date} {time_str})"
    admin_msg["From"] = FROM_EMAIL
    admin_msg["To"] = ADMIN_EMAIL
    admin_msg.set_content(f"Name: {name}\nEmail: {email}\nPhone: {phone}\nDate: {display_date}\nTime: {time_str}")
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(admin_msg)

# -------------------------------------------------
# CHAT API – BULLETPROOF LOGIC
@app.route("/api/message", methods=["POST"])
def api_message():
    user_input = request.json.get("message", "").strip()
    session_id = request.cookies.get("session_id") or str(uuid.uuid4())

    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"stage": "name", "name": None, "email": None, "phone": None, "date": None, "time": None}
    S = SESSIONS[session_id]
    reply = ""

    # CANCEL (anytime)
    if user_input.lower() == "cancel":
        if S.get("name") and S.get("date") and S.get("time"):
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("DELETE FROM bookings WHERE email = ? AND date = ? AND time = ?", (S["email"], S["date"], S["time"]))
            conn.commit()
            conn.close()
            reply = "Your booking has been cancelled successfully.\n\nWhich date would you like to book? (e.g. 27/11/2025)"
            S["date"] = S["time"] = None
            S["stage"] = "date"
        else:
            reply = "No active booking. Which date would you like? (e.g. 27/11/2025)"
            S["stage"] = "date"
        resp = make_response(jsonify({"reply": reply}))
        resp.set_cookie("session_id", session_id, httponly=True, samesite="Lax")
        return resp

    # STAGE: NAME
    if S["stage"] == "name":
        if len(user_input) < 2 or any(c.isdigit() for c in user_input):
            reply = "Please enter a valid name (no numbers)."
        else:
            S["name"] = user_input.strip().title()
            S["stage"] = "email"
            reply = f"Thanks, {S['name']}! What's your email address?"

    # STAGE: EMAIL
    elif S["stage"] == "email":
        email = user_input.lower().strip()
        if "@" not in email or "." not in email or len(email) < 5:
            reply = "Please enter a valid email address (e.g. john@example.com)"
        else:
            S["email"] = email
            S["stage"] = "phone"
            reply = "And your contact number? (e.g. 0412 345 678)"

    # STAGE: PHONE
    elif S["stage"] == "phone":
        phone = user_input.strip()
        if len(phone.replace(" ", "").replace("-", "")) < 8:
            reply = "Please enter a valid phone number."
        else:
            S["phone"] = phone
            S["stage"] = "date"
            reply = "Which date would you like? (e.g. 27/11/2025)"

    # STAGE: DATE
    elif S["stage"] == "date":
        try:
            d = datetime.strptime(user_input.strip(), "%d/%m/%Y")
            if d.weekday() >= 5:
                reply = "We are closed on weekends. Please choose Monday–Friday."
            elif is_past_date(d.strftime("%Y-%m-%d")):
                reply = "You cannot book a date in the past. Please choose a future date."
            else:
                S["date"] = d.strftime("%Y-%m-%d")
                free = [t for t in TIME_SLOTS if not is_time_booked(S["date"], t)]
                if not free:
                    reply = "Sorry, that day is fully booked. Please choose another date."
                else:
                    S["stage"] = "time"
                    reply = f"Available times on {user_input}:\n{', '.join(free)}"
        except ValueError:
            reply = "Please use DD/MM/YYYY format (e.g. 27/11/2025)"

    # STAGE: TIME
    elif S["stage"] == "time":
        t = user_input.strip().upper().replace(" ", "").replace(".", ":").replace("AM", "").replace("PM", "")
        if ":" not in t: t += ":00"
        if len(t) == 4: t = "0" + t
        if t not in TIME_SLOTS:
            reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
        elif is_time_booked(S["date"], t):
            reply = "That time is no longer available. Please pick another or choose a different date."
            S["stage"] = "date"
        else:
            S["time"] = t
            save_booking(S["name"], S["email"], S["phone"], S["date"], S["time"])
            try:
                send_email_with_ics(S["name"], S["email"], S["phone"], S["date"], S["time"])
            except Exception as e:
                print("Email error:", e)
            display_date = datetime.strptime(S["date"], "%Y-%m-%d").strftime("%d %B %Y")
            reply = f"Confirmed! Your call is on {display_date} at {S['time']}.\n\nType 'cancel' anytime to reschedule."

    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("session_id", session_id, httponly=True, samesite="Lax")
    return resp

# -------------------------------------------------
# Keep your existing admin routes and index() as before
# (or switch to external templates later — this works perfectly now)

# ... [keep your @app.route("/"), admin routes, etc. from previous version]

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)