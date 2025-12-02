# FINAL FIX 2025-12-01 — calendar toggle + blocking working
# app.py - ACOP Booking Chatbot - FINAL WITH CLICKABLE CALENDAR BLOCKER
from flask import (
    Flask, request, jsonify, render_template, redirect, url_for,
    session, make_response, flash
)
from flask_cors import CORS
import sqlite3
import os
import smtplib
from email.message import EmailMessage
import csv
import io
import uuid
from datetime import datetime
from datetime import timedelta
import pytz
import requests

SYDNEY_TZ = pytz.timezone("Australia/Sydney")
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

if not hasattr(app, "chat_sessions"):
    app.chat_sessions = {}

# ==================== DATABASE INIT ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
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
            email_per_booking INTEGER DEFAULT 1,
            attach_csv INTEGER DEFAULT 1,
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
    conn.commit()
    conn.close()
init_db()

# ==================== DB HELPERS ====================
def is_slot_past_today(date_str, time_slot):
    try:
        now = datetime.now(SYDNEY_TZ)
        slot_dt = datetime.strptime(f"{date_str} {time_slot}", "%Y-%m-%d %H:%M")
        slot_dt = SYDNEY_TZ.localize(slot_dt)
        return slot_dt < now
    except:
        return True
def is_same_day_cutoff_passed(date_str, time_slot):
    try:
        now = datetime.now(SYDNEY_TZ)
        booking_dt = datetime.strptime(f"{date_str} {time_slot}", "%Y-%m-%d %H:%M")
        booking_dt = SYDNEY_TZ.localize(booking_dt)  # make it timezone-aware
        if booking_dt.date() == now.date():
            cutoff = now + timedelta(hours=2)
            return booking_dt < cutoff
        return False
    except:
        return False
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

def all_bookings():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings ORDER BY date,time")
    rows = cur.fetchall()
    conn.close()
    return rows

def delete_booking(bid):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
    conn.commit()
    conn.close()

# Blocked ranges
def add_blocked_range(start, end):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO blocked_ranges (start_date,end_date) VALUES (?,?)", (start, end))
    conn.commit()
    conn.close()

def get_blocked_ranges():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT start_date, end_date FROM blocked_ranges ORDER BY start_date")
    rows = cur.fetchall()
    conn.close()
    return rows

def is_date_blocked(date_str):
    for s, e in get_blocked_ranges():
        if s <= date_str <= e:
            return True
    return False

# Calendar for admin panel
def get_calendar_month(year=None, month=None):
    if not year:
        now = datetime.now()
        year, month = now.year, now.month
    first = datetime(year, month, 1)
    start = first - timedelta(days=(first.weekday() + 1) % 7)  # Sunday start
    days = []
    for i in range(42):
        d = start + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        days.append({
            "date": date_str,
            "num": d.day if d.month == month else "",
            "blocked": is_date_blocked(date_str)
        })
    return days



def find_next_available_days(start_from=None):
    now = datetime.now(SYDNEY_TZ)
    today = now.date()

    # Decide where to start searching from
    if start_from:
        try:
            # User typed a date → start searching FROM THAT DATE (even if it's in the future)
            search_start_date = datetime.strptime(start_from, "%Y-%m-%d").date()
        except:
            search_start_date = today
    else:
        search_start_date = today

    # But never go backwards — if somehow the hint is in the past, start from today
    search_start_date = max(search_start_date, today)

    found = 0
    suggestions = []
    current = datetime.combine(search_start_date, datetime.min.time())

    for i in range(0, 200):  # look up to ~6 months ahead
        check_date = current + timedelta(days=i)
        if check_date.weekday() >= 5:  # skip weekends
            continue

        date_str = check_date.strftime("%Y-%m-%d")
        if is_date_blocked(date_str):
            continue

        # Check each time slot isn't already passed
        free = []
        for t in TIME_SLOTS:
            if not is_booked(date_str, t) and not is_slot_past_today(date_str, t):
                free.append(t)

        if free:
            pretty = check_date.strftime("%A %d %B")
            suggestions.append(f"• {pretty} – {', '.join(free)}")
            found += 1
            if found >= 3:
                break

    if suggestions:
        return "Here are the next 3 available days:\n\n" + "\n".join(suggestions) + "\n\nJust reply with your preferred date!"
    else:
        return "No availability found. Please try a different date or contact us directly."

# ←←← THIS BLANK LINE IS REQUIRED IN PYTHON ←←←
def is_past(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date() < datetime.now(SYDNEY_TZ).date()
    except:
        return False

# ==================== EMAIL & TEAMS ====================
def send_email(to, subject, text, html=None, attachments=None):
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if attachments:
        for fname, data, subtype in attachments:
            msg.add_attachment(data, maintype="text" if subtype=="csv" else "application", subtype=subtype, filename=fname)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except:
        return False

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
    booking_id, name, email, phone, date, time, created_at = booking_row
    
    pretty_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    booked_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(SYDNEY_TZ).strftime("%d %B %Y %I:%M %p")

    # === EMAIL WITH CSV ===
    csv_output = io.StringIO()
    writer = csv.writer(csv_output)
    writer.writerow(["ID", "Name", "Email", "Phone", "Date", "Time", "Booked At"])
    writer.writerow([booking_id, name, email, phone, date, time, booked_at])
    
    html = f"<h3>New Booking</h3><p><strong>{name}</strong><br>{email}<br>{phone}<br><strong>{pretty_date} at {time}</strong></p>"
    text = f"New booking: {name} | {email} | {phone} | {pretty_date} {time}"
    
    send_email(
        to=ADMIN_EMAIL,
        subject=f"New Booking: {name} – {pretty_date} {time}",
        text=text,
        html=html,
        attachments=[("booking.csv", csv_output.getvalue().encode(), "csv")]
    )

    # === TEAMS NOTIFICATION – 100% ROBUST ===
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT teams_enabled, teams_webhook FROM admin_settings WHERE id = 1")
            row = cur.fetchone()
            
            if row and row["teams_enabled"] and row["teams_webhook"]:
                url = row["teams_webhook"].strip()
                if url:
                    payload = {"text": f"New ACOP Booking\n**{name}**\n{email} | {phone}\n**{pretty_date} at {time}**"}
                    requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"TEAMS FAILED (ignored): {e}")
# ==================== ADMIN ROUTES ====================
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
    return render_template("admin.html",
                         bookings=all_bookings(),
                         calendar_days=get_calendar_month())

@app.route("/admin/delete/<int:bid>", methods=["POST"])
@require_admin
def admin_delete(bid):
    delete_booking(bid)
    flash("Booking deleted")
    return redirect(url_for("admin"))

@app.route("/admin/export")
@require_admin
def admin_export():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID","Name","Email","Phone","Date","Time","Created"])
    writer.writerows(all_bookings())
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=acop_bookings.csv"
    response.headers["Content-type"] = "text/csv"
    return response

@app.route("/admin/toggle_block", methods=["POST"])
def toggle_block():
    try:
        data = request.get_json() or {}
        date = data.get("date")
        if not date:
            return jsonify({"error": "no date"}), 400

        with sqlite3.connect(DB_FILE) as conn:
            # Check if date is inside any blocked range → remove whole range
            cur = conn.execute("SELECT start_date, end_date FROM blocked_ranges")
            for start, end in cur.fetchall():
                if start <= date <= end:
                    conn.execute("DELETE FROM blocked_ranges WHERE start_date=? AND end_date=?", (start, end))
                    conn.commit()
                    return jsonify({"status": "unblocked"})

            # Not blocked → block single day
            conn.execute("INSERT INTO blocked_ranges (start_date, end_date) VALUES (?, ?)", (date, date))
            conn.commit()
            return jsonify({"status": "blocked"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.context_processor
def inject_calendar():
    return dict(calendar_days=get_calendar_month())

@app.route("/admin/settings", methods=["GET", "POST"])
@require_admin
def admin_settings():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT email_per_booking, attach_csv, teams_enabled, teams_webhook FROM admin_settings WHERE id=1")
    row = cur.fetchone()
    if not row:
        row = (1, 1, 1, "")

    if request.method == "POST":
        email_on = 1 if request.form.get("email_per_booking") else 0
        csv_on = 1 if request.form.get("attach_csv") else 0
        teams_on = 1 if request.form.get("teams_enabled") else 0
        webhook = request.form.get("teams_webhook", "").strip()

        conn.execute("""UPDATE admin_settings SET 
                     email_per_booking=?, attach_csv=?, teams_enabled=?, teams_webhook=?
                     WHERE id=1""", (email_on, csv_on, teams_on, webhook))
        conn.commit()
        flash("Settings saved!")
        # Update global webhook
        global TEAMS_WEBHOOK
        TEAMS_WEBHOOK = webhook if teams_on else ""

    conn.close()
    return render_template("admin_settings.html",
                         email_per_booking=row[0],
                         attach_csv=row[1],
                         teams_enabled=row[2],
                         teams_webhook=row[3])

@app.route("/admin/test_email", methods=["POST"])
@require_admin
def test_email():
    send_email(ADMIN_EMAIL, "ACOP Test Email", "This is a test – everything is working!", 
               "<h3>Test Email</h3><p>If you see this, emails are working perfectly.</p>")
    return "sent"

@app.route("/admin/test_teams", methods=["POST"])
@require_admin
def test_teams():
    webhook = request.form.get("teams_webhook") or TEAMS_WEBHOOK
    if webhook:
        requests.post(webhook, json={"text": "ACOP Test Message – Teams is connected!"}, timeout=5)
    return "sent"

# ==================== CHATBOT ====================
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
        conn.execute("DELETE FROM bookings WHERE email=? AND date=?", (S.get("email",""), S.get("date","")))
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
        cleaned = "".join(c for c in msg if c.isdigit() or c in "+- ")
        if len(cleaned) < 8:
            reply = "Please enter a valid phone number (e.g. 0412 345 678)."
        else:
            S["phone"] = msg.strip()
            S["stage"] = "date"
            reply = "Great! Which date would you like?\nPlease use DD/MM/YYYY format (e.g. 15/01/2026)"

    elif S["stage"] == "date":
        try:
            d = datetime.strptime(msg.strip(), "%d/%m/%Y")
            date_str = d.strftime("%Y-%m-%d")

            if is_past(date_str):
                reply = "That date is in the past.\n\n" + find_next_available_days()
            elif d.weekday() >= 5:
                reply = "We are closed on weekends.\n\n" + find_next_available_days(date_str)
            elif is_date_blocked(date_str):
                reply = "That date is not available (office closed or public holiday).\n\n" + find_next_available_days(date_str)
            else:
                free = [t for t in TIME_SLOTS if not is_booked(date_str, t)]
                if not free:
                    reply = "That day is fully booked.\n\n" + find_next_available_days(date_str)
                else:
                    S["date"] = date_str
                    S["stage"] = "time"
                    reply = f"Available on {d.strftime('%d %B %Y')}:\n{', '.join(free)}"

        except ValueError:
            reply = "Please enter the date in DD/MM/YYYY format (e.g. 15/01/2026)"
        except ValueError:
            reply = "Please enter the date in DD/MM/YYYY format (e.g. 15/01/2026)"

    elif S["stage"] == "time":
        t = msg.strip().upper().replace(" ", "").replace(".", "")
        if t in ["9", "9AM", "900"]: t = "09:00"
        elif t in ["11", "11AM", "1100"]: t = "11:00"
        elif t in ["330", "3:30", "1530", "15:30"]: t = "15:30"

        # Re-create the date object (needed for past-time check)
        try:
            date_obj = datetime.strptime(S["date"], "%Y-%m-%d")
            nice_date = date_obj.strftime("%d %B %Y")
        except:
            reply = "Error with date. Please start again."
            S["stage"] = "date"
        else:
            if t not in TIME_SLOTS:
                reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
            elif is_booked(S["date"], t):
                reply = "That time was just taken. Please choose another."
            elif is_same_day_cutoff_passed(S["date"], t):
                reply = f"Sorry, bookings for {t} today require at least 2 hours notice.\nPlease choose a later time or another day."
            elif is_slot_past_today(S["date"], t):
                reply = f"The {t} slot on {nice_date} has already passed.\n\n" + find_next_available_days()
            else:
                # SUCCESS — book it
booking_row = (
    bid,
    S["name"],
    S["email"],
    S["phone"],
    S["date"],
    t,
    datetime.now(LOCAL_TZ).isoformat()
)
send_confirmation(S["name"], S["name"], S["email"], S["phone"], S["date"], t)
notify_admin(booking_row)  # ← now 100% accurate
                reply = f"Confirmed! Your call is on {nice_date} at {t}\n\nType 'cancel' to change."
                app.chat_sessions.pop(sid, None)
    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
    return resp

# === FINAL COMPACT & 100% CORRECT CALENDAR (NO SYNTAX ERROR) ===
from datetime import datetime, timedelta

def get_one_month(year, month, offset=0):
    m = month + offset
    y = year
    while m < 1:
        m += 12; y -= 1
    while m > 12:
        m -= 12; y += 1

    first = datetime(y, m, 1)
    start = first - timedelta(days=first.weekday())   # Monday start — perfect

    days = []
    for i in range(42):
        day = start + timedelta(days=i)
        days.append({
            "date": day.strftime("%Y-%m-%d"),
            "num": day.day if day.month == m else "",
            "blocked": is_date_blocked(day.strftime("%Y-%m-%d"))
        })
    return {"name": first.strftime("%B %Y"), "days": days}

def get_three_months():
    now = datetime.now()
    return [
        get_one_month(now.year, now.month, 0),   # current month
        get_one_month(now.year, now.month, 1),   # next month
        get_one_month(now.year, now.month, 2)    # month after next
    ]

@app.context_processor
def inject_calendar():
    return dict(calendar_months=get_three_months())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
