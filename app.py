# app.py - ACOP Booking Chatbot - Final Production Version
from flask import (
    Flask, request, jsonify, render_template, redirect, url_for,
    send_file, session, flash, make_response
)
from flask_cors import CORS
import sqlite3
import os
import smtplib
from email.message import EmailMessage
import csv
import io
import uuid
from datetime import datetime, timedelta
import requests
import pytz
from icalendar import Calendar, Event
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "acop-2025-final")
CORS(app)

# ==================== CONFIG ====================
DB_FILE = "bookings.db"
TIME_SLOTS = ["09:00", "11:00", "15:30"]
LOCAL_TZ = pytz.timezone("Australia/Sydney")

SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "17d873b3a11a38")
SMTP_PASS = os.getenv("SMTP_PASS", "453b9c740a0729")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")
TEAMS_WEBHOOK = os.getenv("TEAMS_WEBHOOK", "")

ADMIN_USER = os.getenv("ADMIN_USER", "Admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Acop2025!")

# In-memory chat sessions (resets on deploy — acceptable for this scale)
if not hasattr(app, "chat_sessions"):
    app.chat_sessions = {}

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,
        date TEXT NOT NULL, time TEXT NOT NULL, created_at TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS admin_settings (
        id INTEGER PRIMARY KEY,
        email_per_booking INTEGER DEFAULT 1, attach_csv INTEGER DEFAULT 1,
        daily_summary INTEGER DEFAULT 1, weekly_summary INTEGER DEFAULT 1,
        teams_enabled INTEGER DEFAULT 1, teams_webhook TEXT DEFAULT '')""")
    cur.execute("INSERT OR IGNORE INTO admin_settings (id) VALUES (1)")
    conn.commit()
    conn.close()
init_db()
conn = sqlite3.connect(DB_FILE)
conn.execute("""
    CREATE TABLE IF NOT EXISTS blocked_ranges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL
    )
""")
conn.commit()
conn.close()
def get_settings():
    conn = sqlite3.connect()
    cur = conn.cursor()
    cur.execute("SELECT email_per_booking,attach_csv,daily_summary,weekly_summary,teams_enabled,teams_webhook FROM admin_settings WHERE id=1")
    row = cur.fetchone()
    conn.close()
    defaults = {"email_per_booking":1,"attach_csv":1,"daily_summary":1,"weekly_summary":1,"teams_enabled":1,"teams_webbook":""}
    if row:
        defaults.update(dict(zip(["email_per_booking","attach_csv","daily_summary","weekly_summary","teams_enabled","teams_webhook"], row)))
    return {k: bool(v) if k != "teams_webhook" else (v or "") for k,v in defaults.items()}

def update_settings(**kwargs):
    allowed = ("email_per_booking","attach_csv","daily_summary","weekly_summary","teams_enabled","teams_webhook")
    sets, params = [], []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k}=?")
            params.append(1 if kwargs[k] and k != "teams_webhook" else (kwargs[k] if k == "teams_webhook" else 0))
    if sets:
        sql = f"UPDATE admin_settings SET {', '.join(sets)} WHERE id=1"
        conn = sqlite3.connect(DB_FILE)
        conn.execute(sql, params)
        conn.commit()
        conn.close()

# DB Helpers
def save_booking(name, email, phone, date, time):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO bookings (name,email,phone,date,time,created_at) VALUES (?,?,?,?,?,?)",
                (name, email, phone, date, time, datetime.now(LOCAL_TZ).isoformat()))
    conn.commit()
    booking_id = cur.lastrowid
    conn.close()
    return booking_id

def is_booked(date, time):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
    result = cur.fetchone() is not None
    conn.close()
    return result

def is_past(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date() < datetime.now(LOCAL_TZ).date()

def get_booking(booking_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings WHERE id=?", (booking_id,))
    row = cur.fetchone()
    conn.close()
    return row

def delete_booking(booking_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()

def all_bookings():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings ORDER BY date,time")
    rows = cur.fetchall()
    conn.close()
    return rows
# === BLOCKED DATE RANGES ===
def add_blocked_range(start, end):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO blocked_ranges (start_date, end_date) VALUES (?, ?)", (start, end))
    conn.commit()
    conn.close()

def get_blocked_ranges():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT start_date, end_date FROM blocked_ranges ORDER BY start_date")
    rows = cur.fetchall()
    conn.close()
    return rows

def is_date_blocked(date_str):  # date_str = '2025-12-24'
    blocked = get_blocked_ranges()
    for start, end in blocked:
        if start <= date_str <= end:
            return True
    return False
# ==================== EMAIL & TEAMS ====================
def send_email(to, subject, text, html=None, attachments=None):
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html: msg.add_alternative(html, subtype="html")
    if attachments:
        for fname, data, subtype in attachments:
            main = "text" if subtype == "csv" else "application"
            msg.add_attachment(data, maintype=main, subtype=subtype, filename=fname)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except: return False

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
    html = f"<h3>Hi {name}!</h3><p>Your call is on <strong>{pretty} at {time}</strong>.</p><p>— ACOP Team</p>"

    send_email(email, "Your ACOP Call is Confirmed", text, html,
               [("ACOP-Call.ics", cal.to_ical(), "ics")])

def notify_admin(booking_row):
    settings = get_settings()
    if not settings["email_per_booking"] and not settings["teams_enabled"]:
        return
    name, email, phone, date, time = booking_row[1:6]
    pretty = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    text = f"New booking:\nName: {name}\nEmail: {email}\nPhone: {phone}\nDate: {pretty}\nTime: {time}"
    html = f"<h3>New Booking</h3><p><strong>{name}</strong><br>{email}<br>{phone}<br>{pretty} at {time}</p>"

    attachments = []
    if settings["attach_csv"]:
        csv_data = io.StringIO()
        writer = csv.writer(csv_data)
        writer.writerow(["ID","Name","Email","Phone","Date","Time","Created"])
        writer.writerow(booking_row)
        attachments.append(("booking.csv", csv_data.getvalue().encode(), "csv"))

    if settings["email_per_booking"]:
        send_email(ADMIN_EMAIL, f"New Booking: {name} - {pretty} {time}", text, html, attachments)

    webhook = settings["teams_webhook"] or TEAMS_WEBHOOK
    if settings["teams_enabled"] and webhook:
        requests.post(webhook, json={"text": f"New ACOP Booking\n{name}\n{email}\n{phone}\n{pretty} {time}"}, timeout=5)

# ==================== ADMIN ====================
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
        return redirect(url_for("admin"))
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        flash("Invalid credentials")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@require_admin
def admin():
    bookings = all_bookings()          # This function returns list of tuples
    return render_template("admin.html", bookings=bookings)

@app.route("/admin/delete/<int:bid>", methods=["POST"])
@require_admin
def admin_delete(bid):
    delete_booking(bid)
    flash("Booking deleted")
    return redirect(url_for("admin"))

@app.route("/admin/export")
@require_admin
def admin_export():
    bookings = all_bookings()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID","Name","Email","Phone","Date","Time","Created"])
    writer.writerows(bookings)
    return send_file(io.BytesIO(output.getvalue().encode()), download_name="acop_bookings.csv", as_attachment=True)

@app.route("/admin/settings", methods=["GET", "POST"])
@require_admin
def admin_settings():
    if request.method == "POST":
        update_settings(
            email_per_booking="email_per_booking" in request.form,
            attach_csv="attach_csv" in request.form,
            teams_enabled="teams_enabled" in request.form,
            teams_webhook=request.form.get("teams_webhook","").strip()
        )
        flash("Settings saved")
    settings = get_settings()
    return render_template("admin_settings.html", settings=settings)

# ==================== CHAT ====================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/message", methods=["POST"])
def api_message():
    data = request.get_json() or {}
    msg = data.get("message", "").strip().lower()
    sid = data.get("session_id") or request.cookies.get("sid") or str(uuid.uuid4())
    S = app.chat_sessions.setdefault(sid, {"stage": "name"})
    reply = ""

    if msg == "cancel" and S.get("date"):
        conn = sqlite3.connect(DB_FILE)
        conn.execute("DELETE FROM bookings WHERE email=? AND date=?", (S.get("email"), S.get("date")))
        conn.commit()
        conn.close()
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
        cleaned = "".join(c for c in msg if c.isdigit() or c in " -+")
        if len(cleaned) < 8:
            reply = "Please enter a valid phone number."
        else:
            S["phone"] = msg
            S["stage"] = "date"
            reply = "Which date? (e.g. 27/11/2025)"

    elif S["stage"] == "date":
    try:
        d = datetime.strptime(msg, "%d/%m/%Y")
        date_str = d.strftime("%Y-%m-%d")
        if d.weekday() >= 5 or is_past(date_str) or is_date_blocked(date_str):
            reply = "Sorry, that date is not available. Please choose another."
        else:
            free = [t for t in TIME_SLOTS if not is_booked(date_str, t)]
            if not free:
                reply = "That day is fully booked. Another date?"
            else:
                S["date"] = date_str
                S["stage"] = "time"
                reply = f"Available on {d.strftime('%d %B %Y')}: {', '.join(free)}"
    except:
        reply = "Please use DD/MM/YYYY format."

    elif S["stage"] == "time":
        t = msg.strip().upper().replace(" ","").replace(".","")
        if t in ["9","9AM","900"]: t = "09:00"
        elif t in ["11","11AM","1100"]: t = "11:00"
        elif t in ["330","3:30","15:30"]: t = "15:30"
        if t not in TIME_SLOTS:
            reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
        elif is_booked(S["date"], t):
            reply = "That time was just taken. Please choose another."
        else:
            bid = save_booking(S["name"], S["email"], S["phone"], S["date"], t)
            send_confirmation(S["name"], S["email"], S["phone"], S["date"], t)
            notify_admin(get_booking(bid))
            nice = datetime.strptime(S["date"], "%Y-%m-%d").strftime("%d %B %Y")
            reply = f"Confirmed! Your call is on {nice} at {t}\n\nType 'cancel' to change."
            app.chat_sessions.pop(sid, None)

    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
    return resp
@app.route("/admin/block", methods=["POST"])
@require_admin
def admin_block():
    start = request.form["start"]
    end = request.form["end"]
    if start <= end:
        add_blocked_range(start, end)
    return redirect(url_for("admin"))

@app.route("/admin/unblock/<int:idx>", methods=["POST"])
@require_admin
def admin_unblock(idx):
    ranges = get_blocked_ranges()
    if 0 <= idx < len(ranges):
        conn = sqlite3.connect(DB_FILE)
        conn.execute("DELETE FROM blocked_ranges WHERE rowid = (SELECT rowid FROM blocked_ranges LIMIT 1 OFFSET ?)", (idx,))
        conn.commit()
        conn.close()
    return redirect(url_for("admin"))

@app.context_processor
def inject_blocked():
    return dict(blocked_ranges=get_blocked_ranges())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
