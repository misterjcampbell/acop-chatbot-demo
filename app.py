# FINAL WORKING app.py — EVERYTHING FIXED (Dec 2025)
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, make_response, flash
from flask_cors import CORS
import sqlite3
import os
import csv
import io
import uuid
from datetime import datetime, timedelta
import pytz
import requests
from icalendar import Calendar, Event
import smtplib
from email.message import EmailMessage
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "acop-2025-final")
CORS(app)

# ==================== CONFIG ====================
DB_FILE = "bookings.db"
TIME_SLOTS = ["09:00", "11:00", "15:30"]
SYDNEY_TZ = pytz.timezone("Australia/Sydney")
LOCAL_TZ = SYDNEY_TZ

SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "17d873b3a11a38")
SMTP_PASS = os.getenv("SMTP_PASS", "453b9c740a0729")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")
ADMIN_USER = os.getenv("ADMIN_USER", "Admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Acop2025!")

app.chat_sessions = {}

# ==================== DATABASE ====================
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_settings (
                id INTEGER PRIMARY KEY,
                teams_enabled INTEGER DEFAULT 1,
                teams_webhook TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS blocked_ranges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL
            );
            INSERT OR IGNORE INTO admin_settings (id) VALUES (1);
        """)
init_db()

# ==================== HELPERS ====================
def save_booking(name, email, phone, date, time):
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO bookings (name,email,phone,date,time,created_at) VALUES (?,?,?,?,?,?)",
                    (name, email, phone, date, time, datetime.now(LOCAL_TZ).isoformat()))
        conn.commit()
        return cur.lastrowid

def is_booked(date, time):
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time)).fetchone() is not None

def is_date_blocked(date_str):
    with sqlite3.connect(DB_FILE) as conn:
        for s, e in conn.execute("SELECT start_date, end_date FROM blocked_ranges").fetchall():
            if s <= date_str <= e:
                return True
    return False

def is_slot_past_today(date_str, time_slot):
    try:
        slot_dt = SYDNEY_TZ.localize(datetime.strptime(f"{date_str} {time_slot}", "%Y-%m-%d %H:%M"))
        return slot_dt < datetime.now(SYDNEY_TZ)
    except:
        return True

def all_bookings():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM bookings ORDER BY date, time").fetchall()

# ==================== CALENDAR ====================
def get_calendar_month(year=None, month=None):
    if not year:
        now = datetime.now()
        year, month = now.year, now.month
    first = datetime(year, month, 1)
    start = first - timedelta(days=(first.weekday() + 1) % 7)
    days = []
    i = 0
    while len(days) < 42:
        d = start + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        days.append({
            "date": date_str,
            "num": d.day if d.month == month else "",
            "blocked": is_date_blocked(date_str)
        })
        i += 1
    return days

@app.context_processor
def inject_calendar():
    return dict(calendar_days=get_calendar_month())

# ==================== NOTIFICATIONS ====================
def send_email(to, subject, text, html=None, attachments=None):
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if attachments:
        for fname, data, ctype in attachments:
            msg.add_attachment(data, maintype="text" if ctype=="csv" else "application", subtype=ctype, filename=fname)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except Exception as e:
        print("Email error:", e)

def send_confirmation(name, email, phone, date, time):
    dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    cal = Calendar()
    cal.add('prodid', '-//ACOP//')
    cal.add('version', '2.0')
    event = Event()
    event.add('summary', 'ACOP Assessment Call')
    event.add('dtstart', dt)
    event.add('dtend', dt + timedelta(minutes=60))
    event.add('description', f'Call with {name}')
    cal.add_component(event)
    pretty = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    text = f"Hi {name},\n\nYour assessment call is confirmed for {pretty} at {time}.\n\n— ACOP Team"
    html = f"<h3>Hi {name}!</h3><p>Your call is on <strong>{pretty} at {time}</strong>.</p>"
    send_email(email, "Your ACOP Call is Confirmed", text, html,
               [("ACOP-Call.ics", cal.to_ical(), "ics")])

def notify_admin(booking_row):
    bid, name, email, phone, date, time, created_at = booking_row
    pretty_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    booked_at = datetime.fromisoformat(created_at.replace("Z", "+00:00") if "Z" in created_at else created_at) \
                .astimezone(SYDNEY_TZ).strftime("%d %B %Y %I:%M %p")

    csv_io = io.StringIO()
    writer = csv.writer(csv_io)
    writer.writerow(["ID","Name","Email","Phone","Date","Time","Booked At"])
    writer.writerow([bid, name, email, phone, date, time, booked_at])
    send_email(ADMIN_EMAIL,
               f"New Booking: {name} – {pretty_date} {time}",
               f"New booking: {name} | {email} | {phone} | {pretty_date} {time}",
               f"<h3>New Booking</h3><p><strong>{name}</strong><br>{email}<br>{phone}<br><strong>{pretty_date} at {time}</strong></p>",
               [("booking.csv", csv_io.getvalue().encode(), "csv")])

    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT teams_enabled, teams_webhook FROM admin_settings WHERE id=1").fetchone()
        if row and row["teams_enabled"] and row["teams_webhook"]:
            url = row["teams_webhook"].strip()
            if url:
                payload = {
                    "@type": "MessageCard",
                    "@context": "http://schema.org/extensions",
                    "themeColor": "0072C6",
                    "title": "New ACOP Booking",
                    "text": f"**{name}**\n{email} | {phone}\n**{pretty_date} at {time}**\nBooked: {booked_at}"
                }
                requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Teams error:", e)

# ==================== ADMIN AUTH ====================
def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_panel"))
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_panel"))
        flash("Invalid credentials", "error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@require_admin
def admin_panel():
    return render_template("admin.html", bookings=all_bookings())

# ==================== MAIN PAGES – THESE WERE MISSING! ====================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/admin/toggle_block", methods=["POST"])
@require_admin
def toggle_block():
    data = request.get_json()
    date = data.get("date")
    if not date:
        return jsonify(error="no date"), 400
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute("SELECT start_date, end_date FROM blocked_ranges")
        for s, e in cur.fetchall():
            if s <= date <= e:
                conn.execute("DELETE FROM blocked_ranges WHERE start_date=? AND end_date=?", (s, e))
                return jsonify(status="unblocked")
        conn.execute("INSERT INTO blocked_ranges (start_date, end_date) VALUES (?,?)", (date, date))
        return jsonify(status="blocked")

# ==================== CHATBOT – FULLY WORKING ====================
@app.route("/api/message", methods=["POST"])
def api_message():
    data = request.get_json() or {}
    msg = data.get("message", "").strip().lower()
    sid = data.get("session_id") or request.cookies.get("sid") or str(uuid.uuid4())
    S = app.chat_sessions.setdefault(sid, {"stage": "name"})
    reply = ""

    if msg == "cancel" and S.get("date"):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM bookings WHERE email=? AND date=?", (S.get("email"), S.get("date")))
        S.clear()
        S["stage"] = "name"
        reply = "Booking cancelled. Hi! What's your name?"

    elif S["stage"] == "name":
        if len(msg) < 2 or any(c.isdigit() for c in msg):
            reply = "Please enter a valid name."
        else:
            S["name"] = msg.title()
            S["stage"] = "email"
            reply = f"Thanks {S['name']}! What's your email?"

    elif S["stage"] == "email":
        if "@" not in msg or "." not in msg:
            reply = "Please enter a valid email."
        else:
            S["email"] = msg
            S["stage"] = "phone"
            reply = "Your phone number?"

    elif S["stage"] == "phone":
        if len("".join(c for c in msg if c.isdigit())) < 8:
            reply = "Please enter a valid phone number."
        else:
            S["phone"] = msg.strip()
            S["stage"] = "date"
            reply = "Which date? (DD/MM/YYYY)"

    elif S["stage"] == "date":
        try:
            d = datetime.strptime(msg.strip(), "%d/%m/%Y")
            date_str = d.strftime("%Y-%m-%d")
            if d.date() < datetime.now(SYDNEY_TZ).date():
                reply = "That date is in the past."
            elif d.weekday() >= 5:
                reply = "We are closed on weekends."
            elif is_date_blocked(date_str):
                reply = "That date is blocked."
            else:
                free = [t for t in TIME_SLOTS if not is_booked(date_str, t) and not is_slot_past_today(date_str, t)]
                if not free:
                    reply = "No times available."
                else:
                    S["date"] = date_str
                    S["stage"] = "time"
                    reply = f"Available on {d.strftime('%d %B %Y')}:\n" + ", ".join(free)
        except:
            reply = "Please use DD/MM/YYYY format."

    elif S["stage"] == "time":
        t = msg.strip().upper().replace(" ", "").replace(".", "")
        if t in ["9","9AM","900"]: t = "09:00"
        elif t in ["11","11AM","1100"]: t = "11:00"
        elif t in ["330","3:30","1530","15:30"]: t = "15:30"

        if t not in TIME_SLOTS:
            reply = f"Choose from: {', '.join(TIME_SLOTS)}"
        elif is_booked(S["date"], t):
            reply = "Just taken."
        elif is_slot_past_today(S["date"], t):
            reply = "Time passed."
        else:
            bid = save_booking(S["name"], S["email"], S["phone"], S["date"], t)
            created_at = datetime.now(LOCAL_TZ).isoformat()
            booking_row = (bid, S["name"], S["email"], S["phone"], S["date"], t, created_at)
            send_confirmation(S["name"], S["email"], S["phone"], S["date"], t)
            notify_admin(booking_row)

            nice_date = datetime.strptime(S["date"], "%Y-%m-%d").strftime("%d %B %Y")
            reply = f"Confirmed! Call on {nice_date} at {t}\nType 'cancel' to change."
            app.chat_sessions.pop(sid, None)

    resp = make_response(jsonify({"reply": reply or "Try again."}))
    resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
