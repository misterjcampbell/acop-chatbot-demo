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

app = Flask(__name__)
CORS(app)

# Logging
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# -------------------------
# DATABASE SETUP
# -------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "bookings.db")

def init_db():
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            # Help concurrency on platforms like Render
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except Exception:
                logger.debug("Could not set WAL journal mode (may be unsupported).")

            conn.execute(
                """CREATE TABLE IF NOT EXISTS bookings (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT NOT NULL,
                       email TEXT NOT NULL,
                       phone TEXT NOT NULL,
                       date TEXT NOT NULL,
                       time TEXT NOT NULL,
                       timestamp TEXT NOT NULL
                   )"""
            )
            # Ensure uniqueness of a date+time pair (create index if table existed)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS bookings_date_time_idx ON bookings(date, time)"
            )
            conn.commit()
    except Exception:
        logger.exception("DB init error")

init_db()

# -------------------------
# EMAIL / ADMIN SETUP
# -------------------------
# Defaults preserved from your original file (Mailtrap sandbox). Override via env vars for Render.
SMTP_SERVER = os.environ.get("SMTP_SERVER", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.environ.get("SMTP_PORT", os.environ.get("MAILPORT", 2525)))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "17d873b3a11a38")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "453b9c740a0729")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "johnc@acop.edu.au")

def send_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            # Try to login if credentials present (Mailtrap sandbox may accept these)
            if SMTP_USERNAME and SMTP_PASSWORD:
                try:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                except Exception:
                    logger.debug("SMTP login failed (continuing).")
            server.send_message(msg)
        return True
    except Exception:
        logger.exception("Email error:")
        return False

# -------------------------
# Helpers: validation & allowed times
# -------------------------
ALLOWED_TIMES = {"09:00", "11:00", "15:30"}  # only these three slots allowed

def parse_date_time(date_str: str, time_str: str):
    """
    Try to parse input date and time; returns a datetime if successful, else None.
    Accepts:
      date: YYYY-MM-DD
      time: H:M or H:MM or H.MM or H:MM am/pm
    Normalize result to a datetime object (naive, server timezone).
    """
    date_str = (date_str or "").strip()
    time_str = (time_str or "").strip()

    if not date_str or not time_str:
        return None

    # Try a few time formats
    time_formats = ["%H:%M", "%H.%M", "%I:%M %p", "%I:%M%p", "%I %p"]
    for tf in time_formats:
        try:
            combined = f"{date_str} {time_str}"
            dt = datetime.strptime(combined, f"%Y-%m-%d {tf}")
            return dt
        except Exception:
            continue

    # Try strict combined ISO style (YYYY-MM-DD HH:MM)
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return dt
    except Exception:
        return None

def is_weekday(dt: datetime):
    # Monday=0 .. Sunday=6; weekday only allowed
    return 0 <= dt.weekday() <= 4

def is_allowed_time(dt: datetime):
    return dt.strftime("%H:%M") in ALLOWED_TIMES

def not_in_past(dt: datetime):
    now = datetime.now()
    return dt > now  # strictly future

# -------------------------
# ROUTES
# -------------------------
@app.route("/")
def home():
    try:
        return render_template("index.html")
    except Exception:
        logger.exception("Template error")
        return "Template error", 500

# Check availability
@app.route("/check", methods=["POST"])
def check():
    data = request.get_json(silent=True) or {}
    date = data.get("date")
    time = data.get("time")

    if not date or not time:
        return jsonify({"available": False, "error": "Missing date or time"}), 400

    dt = parse_date_time(date, time)
    if not dt:
        return jsonify({"available": False, "error": "Invalid date/time format"}), 400

    if not is_weekday(dt):
        return jsonify({"available": False, "error": "Bookings allowed only on weekdays (Mon–Fri)."}), 400

    if not is_allowed_time(dt):
        return (
            jsonify(
                {
                    "available": False,
                    "error": "Only 09:00, 11:00 and 15:30 are available for booking.",
                }
            ),
            400,
        )

    if not not_in_past(dt):
        return jsonify({"available": False, "error": "Cannot book a past date/time."}), 400

    date_norm = dt.strftime("%Y-%m-%d")
    time_norm = dt.strftime("%H:%M")

    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM bookings WHERE date=? AND time=? LIMIT 1", (date_norm, time_norm))
            exists = c.fetchone()
    except Exception:
        logger.exception("DB check error")
        return jsonify({"available": False, "error": "Database error"}), 500

    return jsonify({"available": not bool(exists)})

# Save a booking
@app.route("/book", methods=["POST"])
def book():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    email = data.get("email")
    phone = data.get("phone")
    date = data.get("date")
    time = data.get("time")

    # Basic required fields
    if not all([name, email, phone, date, time]):
        return jsonify({"success": False, "message": "All fields are required"}), 400

    dt = parse_date_time(date, time)
    if not dt:
        return jsonify({"success": False, "message": "Invalid date/time format"}), 400

    if not is_weekday(dt):
        return jsonify({"success": False, "message": "Bookings allowed only on weekdays (Mon–Fri)."}), 400

    if not is_allowed_time(dt):
        return jsonify(
            {
                "success": False,
                "message": "Only 09:00, 11:00 and 15:30 are available for booking.",
            }
        ), 400

    if not not_in_past(dt):
        return jsonify({"success": False, "message": "Cannot book a past date/time."}), 400

    date_norm = dt.strftime("%Y-%m-%d")
    time_norm = dt.strftime("%H:%M")

    # Insert booking; unique index will prevent duplicates from concurrent requests
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            c = conn.cursor()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                c.execute(
                    """INSERT INTO bookings (name, email, phone, date, time, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, email, phone, date_norm, time_norm, timestamp),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # unique constraint violated
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "That time is already booked. Please select another time or call the College on 1300-88-48-10.",
                        }
                    ),
                    409,
                )
    except Exception:
        logger.exception("DB booking error")
        return jsonify({"success": False, "message": "Database error"}), 500

    # Send the emails (same wording as your original file)
    user_msg = f"Hi {name},\n\nYour Engagement Assessment call has been booked for {date_norm} at {time_norm}.\nIf you need to make changes, call us on 1300-88-48-10.\n\nACOP Team"
    admin_msg = f"New booking:\nName: {name}\nEmail: {email}\nPhone: {phone}\nDate: {date_norm}\nTime: {time_norm}\nTimestamp: {timestamp}"

    user_email_sent = send_email(email, "Your Assessment Booking", user_msg)
    admin_email_sent = send_email(ADMIN_EMAIL, "New Assessment Booking", admin_msg)

    if not user_email_sent or not admin_email_sent:
        # keep original behavior: booking saved but email failed
        return jsonify(
            {"success": True, "message": "Booking saved but failed to send email notifications."}
        )

    return jsonify({"success": True, "message": "Booking confirmed and emails sent successfully."})

# Example webhook endpoint forwarding/preservation:
# If you had custom webhook routes configured, keep them here.
@app.route("/webhook", methods=["POST"])
def webhook():
    # Preserve your webhook endpoint (no destructive changes).
    # This is a minimal pass-through that logs the payload and returns 200.
    payload = request.get_json(silent=True)
    logger.info("Received webhook payload: %s", payload)
    # If you previously had specific behavior here, let me know and I'll restore it exactly.
    return jsonify({"received": True}), 200

# -------------------------
# RUN APP
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)