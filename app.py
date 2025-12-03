# app.py — ACOP Booking Bot — FINAL & PERFECT (Your Way — December 2025)
import os
import io
import csv
import sqlite3
import smtplib
import requests
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import Flask, request, jsonify, render_template, make_response, session
from flask import send_from_directory
import pytz
import uuid

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "acop-secret-2025-forever")

# ==================== CONFIG ====================
DB_FILE = "bookings.db"
TIME_SLOTS = ["09:00", "11:00", "15:30"]
SYDNEY_TZ = pytz.timezone("Australia/Sydney")

SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")

if not hasattr(app, "chat_sessions"):
    app.chat_sessions = {}

# ==================== DATABASE INIT ====================
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, email TEXT, phone TEXT, date TEXT, time TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS blocked_ranges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_date TEXT, end_date TEXT
            );
            CREATE TABLE IF NOT EXISTS admin_settings (
                id INTEGER PRIMARY KEY,
                email_per_booking INTEGER DEFAULT 1,
                attach_csv INTEGER DEFAULT 1,
                teams_enabled INTEGER DEFAULT 1,
                teams_webhook TEXT DEFAULT ''
            );
            INSERT OR IGNORE INTO admin_settings (id) VALUES (1);
        """)
init_db()

# ==================== HELPERS ====================
def is_date_blocked(date_str):
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute("SELECT 1 FROM blocked_ranges WHERE ? BETWEEN start_date AND end_date", (date_str,))
        return cur.fetchone() is not None

def is_booked(date, time):
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
        return cur.fetchone() is not None

def is_past(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date() < datetime.now(SYDNEY_TZ).date()
    except:
        return False

def is_same_day_cutoff_passed(date_str, time_slot):
    try:
        now = datetime.now(SYDNEY_TZ)
        dt = datetime.strptime(f"{date_str} {time_slot}", "%Y-%m-%d %H:%M")
        dt = SYDNEY_TZ.localize(dt)
        return dt.date() == now.date() and dt < now + timedelta(hours=2)
    except:
        return False

def is_slot_past_today(date_str, time_slot):
    try:
        now = datetime.now(SYDNEY_TZ)
        dt = datetime.strptime(f"{date_str} {time_slot}", "%Y-%m-%d %H:%M")
        dt = SYDNEY_TZ.localize(dt)
        return dt < now
    except:
        return True

def save_booking(name, email, phone, date, time):
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO bookings (name,email,phone,date,time,created_at) VALUES (?,?,?,?,?,?)",
                    (name, email, phone, date, time, datetime.now(SYDNEY_TZ).isoformat()))
        conn.commit()
        return cur.lastrowid

def all_bookings():
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute("SELECT * FROM bookings ORDER BY date DESC, time DESC").fetchall()

# ==================== SMART NEXT DAYS ====================
def find_next_available_days(start_from=None):
    now = datetime.now(SYDNEY_TZ)
    today = now.date()
    if start_from:
        try:
            hint = datetime.strptime(start_from, "%Y-%m-%d").date()
            search_start = max(hint, today)
        except:
            search_start = today
    else:
        search_start = today

    suggestions = []
    check = datetime.combine(search_start, datetime.min.time())
    for i in range(200):
        day = check + timedelta(days=i)
        if day.weekday() >= 5: continue
        dstr = day.strftime("%Y-%m-%d")
        if is_date_blocked(dstr): continue
        free = [t for t in TIME_SLOTS if not is_booked(dstr, t) and not is_slot_past_today(dstr, t)]
        if free:
            pretty = day.strftime("%A %d %B")
            suggestions.append(f"• {pretty} – {', '.join(free)}")
            if len(suggestions) >= 3: break
    return "Here are the next 3 available days:\n\n" + "\n".join(suggestions) + "\n\nJust reply with your preferred date!" if suggestions else "No availability found."

# ==================== CALENDAR ====================
def get_three_months():
    now = datetime.now(SYDNEY_TZ)
    months = []
    for offset in [0,1,2]:
        y, m = now.year, now.month + offset
        while m > 12: m -= 12; y += 1
        first = datetime(y, m, 1)
        start = first - timedelta(days=first.weekday())
        days = []
        for i in range(42):
            d = start + timedelta(days=i)
            dstr = d.strftime("%Y-%m-%d")
            days.append({"date": dstr, "num": d.day if d.month == m else "", "blocked": is_date_blocked(dstr)})
        months.append({"name": first.strftime("%B %Y"), "days": days})
    return months

@app.context_processor
def inject_calendar():
    return {"calendar_months": get_three_months()}

# ==================== EMAIL & NOTIFY ====================
def send_email(to, subject, text, html=None, attachments=None):
    if not SMTP_USER or not SMTP_PASS: return
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html: msg.add_alternative(html, subtype="html")
    if attachments:
        for fname, data, ctype in attachments:
            msg.add_attachment(data, maintype="text" if ctype == "csv" else "application", subtype=ctype, filename=fname)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except: pass

def send_confirmation(name, email, phone, date, time):
    pretty = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    text = f"Hi {name},\n\nYour call is confirmed for {pretty} at {time}.\n\nThank you!"
    html = f"<h3>Hi {name}!</h3><p>Your call is confirmed for <strong>{pretty} at {time}</strong>.</p>"
    send_email(email, "ACOP Call Confirmed", text, html)

def notify_admin(booking_row):
    bid, name, email, phone, date, time, created = booking_row
    pretty = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    booked_at = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(SYDNEY_TZ).strftime("%d %B %Y %I:%M %p")

    csv_io = io.StringIO()
    writer = csv.writer(csv_io)
    writer.writerow(["ID","Name","Email","Phone","Date","Time","Booked At"])
    writer.writerow([bid, name, email, phone, date, time, booked_at])

    send_email(
        ADMIN_EMAIL,
        f"New Booking: {name} – {pretty} {time}",
        f"New booking from {name}",
        f"<h3>New Booking</h3><p><strong>{name}</strong><br>{email}<br>{phone}<br>{pretty} at {time}</p>",
        [("booking.csv", csv_io.getvalue().encode(), "csv")]
    )

    try:
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute("SELECT teams_enabled, teams_webhook FROM admin_settings WHERE id=1").fetchone()
            if row and row[0] and row[1]:
                url = row[1].strip()
                if url:
                    requests.post(url, json={"text": f"New ACOP Booking\n**{name}**\n{email} | {phone}\n**{pretty} at {time}**"}, timeout=10)
    except Exception as e:
        print(f"Teams failed: {e}")

# ==================== ROUTES ====================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("static", path)

@app.route("/admin/save_settings", methods=["POST"])
def save_settings():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    
    teams_enabled = 1 if request.form.get("teams_enabled") else 0
    webhook = request.form.get("teams_webhook", "").strip()
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE admin_settings SET teams_enabled=?, teams_webhook=? WHERE id=1", (teams_enabled, webhook))
        conn.commit()
    
    if request.form.get("test"):
        if teams_enabled and webhook:
            try:
                requests.post(webhook, json={"text": "Test from ACOP bot — working!"}, timeout=10)
                flash("Test message sent!")
            except:
                flash("Test failed — check URL")
    
    return redirect("/admin?password=Acop2025!")


# ADMIN — YOUR WAY (simple password in URL)
@app.route("/admin")
def admin_page():
    if request.args.get("password") != "Acop2025!" and not session.get("admin"):
        return '''
        <h2>ACOP Admin</h2>
        <p>Access denied.</p>
        <p>Use: <strong>?password=Acop2025!</strong> in the URL</p>
        <p><a href="?password=Acop2025!">Click here to log in</a></p>
        ''', 403
    
    session["admin"] = True
    with sqlite3.connect(DB_FILE) as conn:
        bookings = conn.execute("SELECT * FROM bookings ORDER BY date DESC, time DESC").fetchall()
        settings = conn.execute("SELECT * FROM admin_settings WHERE id=1").fetchone() or (1,1,1,1,"")
        blocked = conn.execute("SELECT start_date, end_date FROM blocked_ranges ORDER BY start_date").fetchall()
    return render_template("admin.html", bookings=bookings, settings=settings, blocked=blocked)

@app.route("/admin/toggle_block", methods=["POST"])
def toggle_block():
    date = request.json.get("date")
    if not date: return jsonify(error="no date"), 400
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute("SELECT start_date, end_date FROM blocked279_ranges")
        for s, e in cur.fetchall():
            if s <= date <= e:
                conn.execute("DELETE FROM blocked_ranges WHERE start_date=? AND end_date=?", (s, e))
                return jsonify(status="unblocked")
        conn.execute("INSERT INTO blocked_ranges (start_date,end_date) VALUES (?,?)", (date, date))
        return jsonify(status="blocked")

# ==================== CHATBOT ====================
@app.route("/api/message", methods=["POST"])
def api_message():
    data = request.get_json() or {}
    msg = data.get("message", "").strip()
    sid = request.cookies.get("sid") or str(uuid.uuid4())
    if sid not in app.chat_sessions:
        app.chat_sessions[sid] = {"stage": "start"}
    S = app.chat_sessions[sid]
    reply = ""

    if S["stage"] == "start":
        reply = "Hi! I'm here to help you book your assessment call.\n\nWhat's your name?"
        S["stage"] = "name"
    elif S["stage"] == "name":
        S["name"] = msg.strip()
        reply = f"Thanks {S['name']}! What's your email?"
        S["stage"] = "email"
    elif S["stage"] == "email":
        S["email"] = msg.strip().lower()
        reply = "Your phone number?"
        S["stage"] = "phone"
    elif S["stage"] == "phone":
        S["phone"] = msg.strip()
        reply = "Great! Which date would you like?\nPlease use DD/MM/YYYY format (e.g. 15/01/2026)"
        S["stage"] = "date"
    elif S["stage"] == "date":
        try:
            d = datetime.strptime(msg.strip(), "%d/%m/%Y")
            date_str = d.strftime("%Y-%m-%d")
            if is_past(date_str):
                reply = "That date is in the past.\n\n" + find_next_available_days()
            elif d.weekday() >= 5:
                reply = "We are closed on weekends.\n\n" + find_next_available_days(date_str)
            elif is_date_blocked(date_str):
                reply = "That date is not available.\n\n" + find_next_available_days(date_str)
            else:
                free = [t for t in TIME_SLOTS if not is_booked(date_str, t) and not is_slot_past_today(date_str, t)]
                if not free:
                    reply = "That day is fully booked.\n\n" + find_next_available_days(date_str)
                else:
                    S["date"] = date_str
                    S["stage"] = "time"
                    reply = f"Available on {d.strftime('%d %B %Y')}:\n" + ", ".join(free)
        except:
            reply = "Please use DD/MM/YYYY format"
    elif S["stage"] == "time":
        t = msg.strip().upper().replace(".", "").replace(" ", "")
        norm = {"9":"09:00","11":"11:00","330":"15:30","1530":"15:30","3:30":"15:30"}
        t = norm.get(t, t)
        if t not in TIME_SLOTS:
            reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
        elif is_booked(S["date"], t) or is_same_day_cutoff_passed(S["date"], t) or is_slot_past_today(S["date"], t):
            reply = "That time is no longer available.\n\n" + find_next_available_days()
        else:
            save_booking(S["name"], S["email"], S["phone"], S["date"], t)
            send_confirmation(S["name"], S["email"], S["phone"], S["date"], t)
            notify_admin(all_bookings()[0])
            pretty = datetime.strptime(S["date"], "%Y-%m-%d").strftime("%d %B %Y")
            reply = f"Confirmed! Your call is on {pretty} at {t}\n\nThank you!"
            app.chat_sessions.pop(sid, None)

    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("sid", sid, httponly=True, samesite="Lax", max_age=86400)
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))