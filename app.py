# app.py — ACOP Booking Chatbot (Enhanced with Email Verification & Phone Validation)
import os
import re
import io
import csv
import json
import uuid
import sqlite3
import smtplib
import random
from email.message import EmailMessage
from datetime import datetime, timedelta
from functools import wraps

import pytz
import requests
from icalendar import Calendar, Event
from flask import (
    Flask, request, jsonify, render_template, redirect, url_for,
    session, flash, send_file, make_response
)
from flask_cors import CORS

# ---------------- CONFIG ----------------
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET", "acop-2025-final")
CORS(app)

DB_FILE = os.getenv("DB_FILE", "bookings.db")
LOCAL_TZ = pytz.timezone(os.getenv("LOCAL_TZ", "Australia/Sydney"))

# Time slots and lead time
TIME_SLOTS = ["09:00", "11:00", "15:30"]
LEAD_TIME_MINUTES = int(os.getenv("LEAD_TIME_MINUTES", "120"))  # e.g. 120 minutes

# Email verification settings
EMAIL_VERIFICATION_EXPIRY_MINUTES = 10
EMAIL_VERIFICATION_MAX_ATTEMPTS = 3

# SMTP / Mailtrap defaults (override via Render env)
SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "17d873b3a11a38")
SMTP_PASS = os.getenv("SMTP_PASS", "453b9c740a0729")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")

# Teams
TEAMS_WEBHOOK_ENV = os.getenv("TEAMS_WEBHOOK", "")

# Admin credentials
ADMIN_USER = os.getenv("ADMIN_USER", "Admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Acop2025!")

# ---------------- DB helpers & init ----------------
def get_conn():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_settings (
        id INTEGER PRIMARY KEY,
        email_per_booking INTEGER DEFAULT 1,
        attach_csv INTEGER DEFAULT 1,
        daily_summary INTEGER DEFAULT 1,
        weekly_summary INTEGER DEFAULT 1,
        teams_enabled INTEGER DEFAULT 1,
        teams_webhook TEXT DEFAULT ''
    )
    """)
    cur.execute("INSERT OR IGNORE INTO admin_settings (id) VALUES (1)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS blocked_dates (
        date TEXT PRIMARY KEY
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_sessions (
        sid TEXT PRIMARY KEY,
        state TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    # Email verification codes table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS email_verification_codes (
        email TEXT PRIMARY KEY,
        code TEXT NOT NULL,
        created_at TEXT NOT NULL,
        attempts INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- Settings ----------------
def get_settings():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT email_per_booking,attach_csv,daily_summary,weekly_summary,teams_enabled,teams_webhook FROM admin_settings WHERE id=1")
    row = cur.fetchone(); conn.close()
    if not row:
        return {"email_per_booking": True, "attach_csv": True, "daily_summary": True, "weekly_summary": True, "teams_enabled": True, "teams_webhook": ""}
    return {
        "email_per_booking": bool(row[0]),
        "attach_csv": bool(row[1]),
        "daily_summary": bool(row[2]),
        "weekly_summary": bool(row[3]),
        "teams_enabled": bool(row[4]),
        "teams_webhook": row[5] or ""
    }

def update_settings(**kwargs):
    allowed = ("email_per_booking","attach_csv","daily_summary","weekly_summary","teams_enabled","teams_webhook")
    sets, params = [], []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k}=?")
            v = kwargs[k]
            if isinstance(v, bool) and k != "teams_webhook":
                params.append(1 if v else 0)
            else:
                params.append(v)
    if not sets:
        return
    sql = "UPDATE admin_settings SET " + ", ".join(sets) + " WHERE id=1"
    conn = get_conn(); cur = conn.cursor()
    cur.execute(sql, params); conn.commit(); conn.close()

# ---------------- Email Verification ----------------
def generate_verification_code():
    """Generate a 6-digit verification code"""
    return f"{random.randint(100000, 999999)}"

def store_verification_code(email, code):
    """Store verification code for email"""
    conn = get_conn(); cur = conn.cursor()
    now = datetime.now(LOCAL_TZ).isoformat()
    cur.execute("""
        INSERT OR REPLACE INTO email_verification_codes (email, code, created_at, attempts)
        VALUES (?, ?, ?, 0)
    """, (email.lower(), code, now))
    conn.commit(); conn.close()

def verify_code(email, code):
    """
    Verify code for email. Returns:
    - "valid" if code matches
    - "invalid" if code doesn't match (increments attempts)
    - "expired" if code is too old
    - "max_attempts" if too many failed attempts
    """
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT code, created_at, attempts FROM email_verification_codes WHERE email=?", (email.lower(),))
    row = cur.fetchone()
    
    if not row:
        conn.close()
        return "invalid"
    
    stored_code, created_at_str, attempts = row
    
    # Check expiry
    created_at = datetime.fromisoformat(created_at_str)
    now = datetime.now(LOCAL_TZ)
    if (now - created_at).total_seconds() > EMAIL_VERIFICATION_EXPIRY_MINUTES * 60:
        cur.execute("DELETE FROM email_verification_codes WHERE email=?", (email.lower(),))
        conn.commit(); conn.close()
        return "expired"
    
    # Check attempts
    if attempts >= EMAIL_VERIFICATION_MAX_ATTEMPTS:
        conn.close()
        return "max_attempts"
    
    # Verify code
    if stored_code == code.strip():
        # Valid - delete the code
        cur.execute("DELETE FROM email_verification_codes WHERE email=?", (email.lower(),))
        conn.commit(); conn.close()
        return "valid"
    else:
        # Invalid - increment attempts
        cur.execute("UPDATE email_verification_codes SET attempts = attempts + 1 WHERE email=?", (email.lower(),))
        conn.commit(); conn.close()
        return "invalid"

def send_verification_email(email, code):
    """Send verification code email"""
    subj = "Your ACOP Verification Code"
    text = f"Your verification code is: {code}\n\nThis code will expire in {EMAIL_VERIFICATION_EXPIRY_MINUTES} minutes."
    html = f"""
    <h3>Email Verification</h3>
    <p>Your verification code is:</p>
    <h2 style="background: #f0f0f0; padding: 15px; text-align: center; letter-spacing: 5px; font-family: monospace;">{code}</h2>
    <p>This code will expire in {EMAIL_VERIFICATION_EXPIRY_MINUTES} minutes.</p>
    <p>If you didn't request this code, please ignore this email.</p>
    """
    return send_email_with_attachments(email, subj, text, html=html, attachments=None)

# ---------------- Australian Phone Validation ----------------
def validate_australian_phone(phone):
    """
    Validate Australian phone numbers.
    Returns: (is_valid: bool, phone_type: str|None, formatted: str|None)
    
    Accepts:
    - Mobile: 04XX XXX XXX or +61 4XX XXX XXX
    - Landline: 02/03/07/08 XXXX XXXX or +61 2/3/7/8 XXXX XXXX
    - International: +XX XXXXXXXXXX (10-15 digits)
    """
    if not phone:
        return False, None, None
    
    # Remove spaces, dashes, parentheses
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    
    # Mobile patterns
    mobile_pattern = r'^(?:\+61|0)4\d{8}$'
    if re.match(mobile_pattern, cleaned):
        # Format: 04XX XXX XXX
        if cleaned.startswith('+61'):
            formatted = f"0{cleaned[3:5]} {cleaned[5:8]} {cleaned[8:]}"
        else:
            formatted = f"{cleaned[:4]} {cleaned[4:7]} {cleaned[7:]}"
        return True, "mobile", formatted
    
    # Landline patterns (02, 03, 07, 08)
    landline_pattern = r'^(?:\+61|0)[2378]\d{8}$'
    if re.match(landline_pattern, cleaned):
        # Format: 0X XXXX XXXX
        if cleaned.startswith('+61'):
            formatted = f"0{cleaned[3:4]} {cleaned[4:8]} {cleaned[8:]}"
        else:
            formatted = f"{cleaned[:2]} {cleaned[2:6]} {cleaned[6:]}"
        return True, "landline", formatted
    
    # International pattern
    international_pattern = r'^\+\d{10,15}$'
    if re.match(international_pattern, cleaned):
        return True, "international", cleaned
    
    return False, None, None

# ---------------- Blocked dates ----------------
def get_blocked_dates():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT date FROM blocked_dates")
    rows = [r[0] for r in cur.fetchall()]; conn.close(); return rows

def toggle_block(date_str):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM blocked_dates WHERE date=?", (date_str,))
    if cur.fetchone():
        cur.execute("DELETE FROM blocked_dates WHERE date=?", (date_str,))
        conn.commit(); conn.close(); return False
    else:
        cur.execute("INSERT INTO blocked_dates (date) VALUES (?)", (date_str,))
        conn.commit(); conn.close(); return True

def block_range(start_date, end_date):
    s = datetime.strptime(start_date, "%Y-%m-%d").date()
    e = datetime.strptime(end_date, "%Y-%m-%d").date()
    conn = get_conn(); cur = conn.cursor()
    d = s
    while d <= e:
        cur.execute("INSERT OR IGNORE INTO blocked_dates (date) VALUES (?)", (d.isoformat(),))
        d = d + timedelta(days=1)
    conn.commit(); conn.close()

def unblock_range(start_date, end_date):
    conn = get_conn(); cur = conn.cursor()
    conn.execute("DELETE FROM blocked_dates WHERE date BETWEEN ? AND ?", (start_date, end_date))
    conn.commit(); conn.close()

# ---------------- Bookings ----------------
def all_bookings(start=None, end=None):
    conn = get_conn(); cur = conn.cursor()
    if start and end:
        cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings WHERE date BETWEEN ? AND ? ORDER BY date,time", (start, end))
    else:
        cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings ORDER BY date,time")
    rows = cur.fetchall(); conn.close(); return rows

def is_booked(date_str, time_str):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date_str, time_str))
    r = cur.fetchone() is not None; conn.close(); return r

def save_booking(name, email, phone, date_str, time_str):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO bookings (name,email,phone,date,time,created_at) VALUES (?,?,?,?,?,?)", (name, email, phone, date_str, time_str, datetime.now(LOCAL_TZ).isoformat()))
    conn.commit(); bid = cur.lastrowid; conn.close(); return bid

def get_booking(bid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings WHERE id=?", (bid,))
    r = cur.fetchone(); conn.close(); return r

def delete_booking(bid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM bookings WHERE id=?", (bid,)); conn.commit(); conn.close()

def find_bookings_by_email(email):
    """Find all future bookings for an email address"""
    conn = get_conn(); cur = conn.cursor()
    today = datetime.now(LOCAL_TZ).date().isoformat()
    cur.execute("""
        SELECT id, name, email, phone, date, time, created_at 
        FROM bookings 
        WHERE email=? AND date >= ?
        ORDER BY date, time
    """, (email.lower(), today))
    rows = cur.fetchall(); conn.close()
    return rows

def send_cancellation_email(name, email, date_iso, time_str):
    """Send email confirmation of cancellation"""
    pretty = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%d %B %Y")
    subj = "ACOP Assessment Call - Cancelled"
    text = f"Hi {name},\n\nYour assessment call scheduled for {pretty} at {time_str} has been cancelled.\n\nIf you need to book a new appointment, please use the booking assistant.\n\n— ACOP Team"
    html = f"<h3>Hi {name}!</h3><p>Your assessment call scheduled for <strong>{pretty} at {time_str}</strong> has been cancelled.</p><p>If you need to book a new appointment, please use the booking assistant.</p>"
    return send_email_with_attachments(email, subj, text, html=html, attachments=None)

# ---------------- Date/time parsing & rules ----------------
_time_re = re.compile(r'^\s*(\d{1,2})(?::|\.|)?(\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?\s*$', re.I)
def normalize_time(s):
    if not s: return None
    s = s.strip().lower().replace(' ', '').replace('hrs','')
    if re.match(r'^\d{1,2}:\d{2}$', s):
        hh_mm = s
    elif re.match(r'^\d{3,4}$', s):
        hh_mm = ('0' + s)[-4:]; hh_mm = hh_mm[:2] + ':' + hh_mm[2:]
    else:
        m = _time_re.match(s)
        if not m:
            return None
        h = int(m.group(1)); mm = m.group(2) or '00'; ampm = (m.group(3) or '').lower()
        if ampm.startswith('p') and h < 12: h += 12
        if ampm.startswith('a') and h == 12: h = 0
        hh_mm = f"{h:02d}:{int(mm):02d}"
    return hh_mm if hh_mm in TIME_SLOTS else None

def parse_date(s):
    if not s: return None
    s = s.strip()
    for fmt in ("%d/%m/%Y","%d-%m-%Y","%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.isoformat()
        except:
            pass
    return None

def is_weekend(date_iso):
    d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    return d.weekday() >= 5

def is_past_date(date_iso):
    d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    return d < datetime.now(LOCAL_TZ).date()

def meets_lead_time(date_iso, time_str):
    appt = datetime.strptime(f"{date_iso} {time_str}", "%Y-%m-%d %H:%M")
    appt = LOCAL_TZ.localize(appt)
    now = datetime.now(LOCAL_TZ)
    diff = (appt - now).total_seconds() / 60.0
    return diff >= LEAD_TIME_MINUTES

# ---------------- Next available dates helper ----------------
def next_available_dates(start_date_iso, count=3):
    results = []
    try:
        d = datetime.strptime(start_date_iso, "%Y-%m-%d").date()
    except:
        d = datetime.now(LOCAL_TZ).date()
    for _ in range(365):
        d_str = d.isoformat()
        if (not is_weekend(d_str)
            and not is_past_date(d_str)
            and d_str not in get_blocked_dates()):
            free = [t for t in TIME_SLOTS if not is_booked(d_str, t)]
            if free:
                results.append(d_str)
                if len(results) >= count:
                    return results
        d = d + timedelta(days=1)
    return results

# ---------------- Email & Teams ----------------
def send_email_with_attachments(to_email, subject, plain_text, html=None, attachments=None):
    """
    Uses STARTTLS prior to login to be compatible with Mailtrap and TLS servers.
    attachments: list of (filename, bytes, subtype)
    """
    try:
        msg = EmailMessage()
        msg["From"] = FROM_EMAIL; msg["To"] = to_email; msg["Subject"] = subject
        msg.set_content(plain_text)
        if html: msg.add_alternative(html, subtype="html")
        if attachments:
            for fname, data_bytes, subtype in attachments:
                maintype = "text" if subtype == "csv" else "application"
                msg.add_attachment(data_bytes, maintype=maintype, subtype=subtype, filename=fname)

        # Use STARTTLS for compatibility
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            try:
                s.starttls()
            except Exception:
                app.logger.debug("starttls failed or not supported, continuing without TLS")
            if SMTP_USER and SMTP_PASS:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        app.logger.exception("email failed: %s", e)
        return False

def send_confirmation_email(name, email, phone, date_iso, time_str):
    pretty = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%d %B %Y")
    subj = "Your ACOP Assessment Call is Confirmed"
    text = f"Hi {name},\n\nYour call is on {pretty} at {time_str}.\n\n— ACOP Team"
    html = f"<h3>Hi {name}!</h3><p>Your call is on <strong>{pretty} at {time_str}</strong>.</p>"
    # ICS
    try:
        dt = datetime.strptime(f"{date_iso} {time_str}", "%Y-%m-%d %H:%M"); dt = LOCAL_TZ.localize(dt)
        cal = Calendar(); cal.add('prodid','-//ACOP//'); cal.add('version','2.0')
        ev = Event(); ev.add('summary','ACOP Assessment Call'); ev.add('dtstart', dt); ev.add('dtend', dt + timedelta(minutes=60)); ev.add('description', f'Call with {name}')
        cal.add_component(ev); attachments = [("ACOP-Call.ics", cal.to_ical(), "ics")]
    except Exception:
        attachments = None
    return send_email_with_attachments(email, subj, text, html=html, attachments=attachments)

def notify_on_booking(booking_row):
    """
    booking_row: (id, name, email, phone, date, time, created_at)
    """
    settings = get_settings()
    pretty = datetime.strptime(booking_row[4], "%Y-%m-%d").strftime("%d %B %Y")
    text = f"New booking: {booking_row[1]} — {pretty} {booking_row[5]}\nEmail: {booking_row[2]}\nPhone: {booking_row[3]}"
    # send admin email
    if settings.get("email_per_booking"):
        attachments = []
        if settings.get("attach_csv"):
            buf = io.StringIO(); w = csv.writer(buf); w.writerow(["ID","Name","Email","Phone","Date","Time","Created"]); w.writerow(booking_row); attachments.append(("booking.csv", buf.getvalue().encode('utf-8'), "csv"))
        try:
            send_email_with_attachments(ADMIN_EMAIL, f"New Booking: {booking_row[1]}", text, html=None, attachments=attachments if attachments else None)
        except Exception:
            app.logger.exception("admin email failed")
    # teams
    webhook = settings.get("teams_webhook") or TEAMS_WEBHOOK_ENV
    if settings.get("teams_enabled") and webhook:
        try:
            requests.post(webhook, json={"text": text}, timeout=8)
        except Exception:
            app.logger.exception("teams failed")

# ---------------- Admin auth ----------------
def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin"))
    error = None
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["admin_logged_in"] = True
            session["admin_username"] = request.form.get("username")
            return redirect(url_for("admin"))
        error = "Invalid credentials"; flash(error)
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None); session.pop("admin_username", None)
    return redirect(url_for("admin_login"))

# ---------------- Admin pages & API ----------------
@app.route("/admin")
@require_admin
def admin():
    rows = all_bookings(); blocked = get_blocked_dates(); settings = get_settings()
    return render_template("admin.html", bookings=rows, blocked_dates=blocked, settings=settings, admin_user=session.get("admin_username"))

@app.route("/admin/events")
@require_admin
def admin_events():
    events = []
    for r in all_bookings():
        start = f"{r[4]}T{r[5]}:00"
        events.append({"id": f"b{r[0]}", "title": f"{r[1]} ({r[5]})", "start": start, "allDay": False, "color": "#004cbf"})
    for d in get_blocked_dates():
        events.append({"id": f"x{d}", "title": "Blocked", "start": f"{d}T00:00:00", "allDay": True, "display": "background", "color": "#ffdddd"})
    return jsonify(events)

@app.route("/admin/toggle-date", methods=["POST"])
@require_admin
def admin_toggle_date():
    data = request.get_json() or {}; date = data.get("date")
    if not date: return jsonify({"ok": False, "error":"missing date"}), 400
    blocked = toggle_block(date)
    return jsonify({"ok": True, "blocked": blocked})

@app.route("/admin/toggle-range", methods=["POST"])
@require_admin
def admin_toggle_range():
    data = request.get_json() or {}
    start = data.get("start"); end = data.get("end"); action = data.get("action","block")
    if not start or not end: return jsonify({"ok": False}), 400
    if action == "block":
        block_range(start, end)
    else:
        unblock_range(start, end)
    return jsonify({"ok": True})

@app.route("/admin/block-selected", methods=["POST"])
@require_admin
def admin_block_selected():
    data = request.get_json() or {}
    date = data.get("date")
    if not date: return jsonify({"ok": False, "error":"missing date"}), 400
    block_range(date, date)
    return jsonify({"ok": True})

@app.route("/admin/unblock-selected", methods=["POST"])
@require_admin
def admin_unblock_selected():
    data = request.get_json() or {}
    date = data.get("date")
    if not date: return jsonify({"ok": False, "error":"missing date"}), 400
    unblock_range(date, date)
    return jsonify({"ok": True})

@app.route("/admin/delete-booking/<int:bid>", methods=["POST"])
@require_admin
def admin_delete_booking(bid):
    delete_booking(bid); flash("Deleted"); return redirect(url_for("admin"))

@app.route("/admin/export")
@require_admin
def admin_export():
    rows = all_bookings(); buf = io.StringIO(); w = csv.writer(buf); w.writerow(["ID","Name","Email","Phone","Date","Time","CreatedAt"])
    for r in rows: w.writerow(r)
    data = buf.getvalue().encode('utf-8'); return send_file(io.BytesIO(data), download_name="acop_bookings.csv", as_attachment=True, mimetype="text/csv")

@app.route("/admin/settings", methods=["GET","POST"])
@require_admin
def admin_settings():
    if request.method == "POST":
        update_settings(
            email_per_booking = "email_per_booking" in request.form,
            attach_csv = "attach_csv" in request.form,
            daily_summary = "daily_summary" in request.form,
            weekly_summary = "weekly_summary" in request.form,
            teams_enabled = "teams_enabled" in request.form,
            teams_webhook = request.form.get("teams_webhook","").strip()
        )
        flash("Settings saved"); return redirect(url_for("admin_settings"))
    settings = get_settings(); return render_template("admin_settings.html", settings=settings)

@app.route("/admin/test-email")
@require_admin
def admin_test_email():
    ok = send_email_with_attachments(ADMIN_EMAIL, "ACOP Test Email", "This is a test.")
    return "OK" if ok else "FAIL"

@app.route("/admin/test-teams")
@require_admin
def admin_test_teams():
    settings = get_settings(); webhook = settings.get("teams_webhook") or TEAMS_WEBHOOK_ENV
    if not webhook: return "No webhook"
    try: requests.post(webhook, json={"text":"ACOP test message"}, timeout=6); return "OK"
    except Exception:
        return "FAIL"

# ---------------- Chat session persistence (DB-backed) ----------------
def load_session(sid):
    if not sid:
        return {"stage":"name"}
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT state FROM chat_sessions WHERE sid=?", (sid,))
    row = cur.fetchone(); conn.close()
    if not row:
        return {"stage":"name"}
    try:
        return json.loads(row[0])
    except Exception:
        return {"stage":"name"}

def save_session(sid, state):
    now = datetime.now(LOCAL_TZ).isoformat(); text = json.dumps(state)
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO chat_sessions (sid,state,updated_at) VALUES (?,?,?)", (sid, text, now))
    conn.commit(); conn.close()

def delete_session(sid):
    conn = get_conn(); cur = conn.cursor(); cur.execute("DELETE FROM chat_sessions WHERE sid=?", (sid,)); conn.commit(); conn.close()

# ---------------- Chat API (enforce rules) ----------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/message", methods=["POST"])
def api_message():
    try:
        data = request.get_json(silent=True) or {}
        raw = data.get("message","") or ""
        from_button = bool(data.get("from_button", False))
        msg = raw.strip()
        session_id = data.get("session_id") or request.cookies.get("sid") or str(uuid.uuid4())

        # load persistent DB-backed session
        state = load_session(session_id)
        if "stage" not in state:
            state["stage"] = "name"

        reply = ""
        
        # Check for cancel/reschedule commands (can interrupt any stage)
        msg_lower = msg.lower().strip()
        if msg_lower in ("cancel", "reschedule", "change", "modify") and state["stage"] not in ("cancel_email", "cancel_confirm", "reschedule_confirm"):
            # Start cancel/reschedule flow
            state["cancel_action"] = "cancel" if msg_lower == "cancel" else "reschedule"
            state["stage"] = "cancel_email"
            state["previous_stage"] = state.get("stage", "name")  # Save where they were
            reply = "What's the email address for your booking?"
            save_session(session_id, state)
            resp = make_response(jsonify({"reply": reply, "session_id": session_id}))
            resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
            return resp
        
        # Check for restart command
        if msg_lower in ("restart", "start over", "begin again"):
            delete_session(session_id)
            state = {"stage": "name"}
            reply = "Let's start fresh! What's your name?"
            save_session(session_id, state)
            resp = make_response(jsonify({"reply": reply, "session_id": session_id}))
            resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
            return resp

        # STATE MACHINE WITH EMAIL VERIFICATION & PHONE VALIDATION
        if state["stage"] == "cancel_email":
            # Looking up booking by email
            if "@" not in msg or "." not in msg.split("@")[-1]:
                reply = "Please enter a valid email address."
            else:
                email = msg.lower().strip()
                bookings = find_bookings_by_email(email)
                
                if not bookings:
                    reply = f"No upcoming bookings found for {email}.\n\nWould you like to make a new booking instead? Type 'yes' or 'restart'."
                    state["stage"] = "name"  # Reset to start
                elif len(bookings) == 1:
                    # One booking found
                    booking = bookings[0]
                    state["cancel_booking_id"] = booking[0]
                    state["cancel_booking_data"] = {
                        "name": booking[1],
                        "email": booking[2],
                        "phone": booking[3],
                        "date": booking[4],
                        "time": booking[5]
                    }
                    pretty_date = datetime.strptime(booking[4], "%Y-%m-%d").strftime("%d %B %Y")
                    
                    action = state.get("cancel_action", "cancel")
                    if action == "cancel":
                        state["stage"] = "cancel_confirm"
                        buttons = [
                            {"label": "Yes, cancel it", "value": "confirm_cancel"},
                            {"label": "Keep booking", "value": "keep_booking"}
                        ]
                        save_session(session_id, state)
                        resp = make_response(jsonify({
                            "reply": f"Found your booking:\n{pretty_date} at {booking[5]}\n\nAre you sure you want to cancel?",
                            "buttons": buttons,
                            "session_id": session_id
                        }))
                        resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
                        return resp
                    else:  # reschedule
                        state["stage"] = "reschedule_confirm"
                        buttons = [
                            {"label": "Yes, pick new time", "value": "confirm_reschedule"},
                            {"label": "Keep current booking", "value": "keep_booking"}
                        ]
                        save_session(session_id, state)
                        resp = make_response(jsonify({
                            "reply": f"Your current booking:\n{pretty_date} at {booking[5]}\n\nWould you like to reschedule?",
                            "buttons": buttons,
                            "session_id": session_id
                        }))
                        resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
                        return resp
                else:
                    # Multiple bookings found
                    reply = f"Found {len(bookings)} bookings for {email}:\n\n"
                    for i, b in enumerate(bookings, 1):
                        pretty = datetime.strptime(b[4], "%Y-%m-%d").strftime("%d %B %Y")
                        reply += f"{i}. {pretty} at {b[5]}\n"
                    reply += "\nPlease contact us directly to manage multiple bookings."
                    state["stage"] = "name"  # Reset
        
        elif state["stage"] == "cancel_confirm":
            if msg.lower() == "confirm_cancel" or msg.lower() in ("yes", "confirm", "y"):
                # Actually cancel the booking
                booking_id = state.get("cancel_booking_id")
                booking_data = state.get("cancel_booking_data", {})
                
                if booking_id:
                    try:
                        # Delete from database
                        delete_booking(booking_id)
                        
                        # Send cancellation email
                        try:
                            send_cancellation_email(
                                booking_data.get("name"),
                                booking_data.get("email"),
                                booking_data.get("date"),
                                booking_data.get("time")
                            )
                        except Exception:
                            app.logger.exception("cancellation email failed")
                        
                        pretty_date = datetime.strptime(booking_data.get("date"), "%Y-%m-%d").strftime("%d %B %Y")
                        reply = f"✓ Your booking for {pretty_date} at {booking_data.get('time')} has been cancelled.\n\nYou'll receive a confirmation email shortly.\n\n(Type 'restart' to book a new appointment)"
                        
                        # Clear session
                        delete_session(session_id)
                        resp = make_response(jsonify({"reply": reply, "session_id": session_id}))
                        resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
                        return resp
                    except Exception as e:
                        app.logger.exception("cancel failed: %s", e)
                        reply = "Sorry, something went wrong. Please try again or contact us directly."
                        state["stage"] = "name"
                else:
                    reply = "Booking not found. Type 'cancel' to try again."
                    state["stage"] = "name"
            elif msg.lower() == "keep_booking" or msg.lower() in ("no", "n", "keep"):
                booking_data = state.get("cancel_booking_data", {})
                pretty_date = datetime.strptime(booking_data.get("date"), "%Y-%m-%d").strftime("%d %B %Y")
                reply = f"No problem! Your booking for {pretty_date} at {booking_data.get('time')} is still confirmed.\n\n(Type 'restart' if you need anything else)"
                delete_session(session_id)
                resp = make_response(jsonify({"reply": reply, "session_id": session_id}))
                resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
                return resp
            else:
                reply = "Please click a button or type 'yes' to confirm cancellation, or 'no' to keep your booking."
        
        elif state["stage"] == "reschedule_confirm":
            if msg.lower() == "confirm_reschedule" or msg.lower() in ("yes", "confirm", "y"):
                # Start reschedule flow - delete old booking and start new booking
                booking_id = state.get("cancel_booking_id")
                booking_data = state.get("cancel_booking_data", {})
                
                if booking_id:
                    try:
                        # Delete old booking
                        delete_booking(booking_id)
                        
                        # Prepare for new booking with saved data
                        state["name"] = booking_data.get("name")
                        state["email"] = booking_data.get("email")
                        state["phone"] = booking_data.get("phone")
                        state["stage"] = "date"
                        
                        reply = "Great! Let's pick a new date and time.\n\nWhich date would you like? (e.g., 27/11/2025)"
                        
                    except Exception as e:
                        app.logger.exception("reschedule failed: %s", e)
                        reply = "Sorry, something went wrong. Please try again."
                        state["stage"] = "name"
                else:
                    reply = "Booking not found. Type 'reschedule' to try again."
                    state["stage"] = "name"
            elif msg.lower() == "keep_booking" or msg.lower() in ("no", "n", "keep"):
                booking_data = state.get("cancel_booking_data", {})
                pretty_date = datetime.strptime(booking_data.get("date"), "%Y-%m-%d").strftime("%d %B %Y")
                reply = f"No problem! Your booking for {pretty_date} at {booking_data.get('time')} is still confirmed.\n\n(Type 'restart' if you need anything else)"
                delete_session(session_id)
                resp = make_response(jsonify({"reply": reply, "session_id": session_id}))
                resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
                return resp
            else:
                reply = "Please click a button or type 'yes' to reschedule, or 'no' to keep your current booking."
        
        elif state["stage"] == "name":
            if len(msg) < 2 or any(c.isdigit() for c in msg):
                reply = "Please enter a valid name (at least 2 characters, no numbers)."
            else:
                state["name"] = msg.title()
                state["stage"] = "email"
                reply = f"Thanks {state['name']}! What's your email address?"

        elif state["stage"] == "email":
            # Basic email validation
            if "@" not in msg or "." not in msg.split("@")[-1]:
                reply = "Please enter a valid email address."
            else:
                email = msg.lower().strip()
                
                # Generate and send verification code
                code = generate_verification_code()
                store_verification_code(email, code)
                
                # Send verification email
                try:
                    send_verification_email(email, code)
                    state["email"] = email
                    state["stage"] = "email_verify"
                    reply = f"I've sent a 6-digit verification code to {email}. Please enter the code:"
                except Exception as e:
                    app.logger.exception("Failed to send verification email: %s", e)
                    reply = "Sorry, I couldn't send the verification email. Please try again or use a different email address."

        elif state["stage"] == "email_verify":
            # Verify the code
            email = state.get("email")
            result = verify_code(email, msg)
            
            if result == "valid":
                state["stage"] = "phone"
                reply = "Email verified! ✓\n\nWhat's your phone number?\n\nAccepted formats:\n• Mobile: 04XX XXX XXX\n• Landline: 02 XXXX XXXX\n• International: +XX XXXXXXXXXX"
            elif result == "expired":
                # Code expired - send new one
                code = generate_verification_code()
                store_verification_code(email, code)
                try:
                    send_verification_email(email, code)
                    reply = f"That code has expired. I've sent you a new code to {email}. Please enter it:"
                except Exception:
                    reply = "The code has expired and I couldn't send a new one. Please start over."
                    state["stage"] = "email"
            elif result == "max_attempts":
                reply = "Too many failed attempts. Please start over with your email address."
                state["stage"] = "email"
            else:  # invalid
                reply = "That code is incorrect. Please try again:"

        elif state["stage"] == "phone":
            is_valid, phone_type, formatted = validate_australian_phone(msg)
            
            if not is_valid:
                reply = "Please enter a valid Australian phone number:\n\n• Mobile: 04XX XXX XXX (e.g., 0412 345 678)\n• Landline: 02/03/07/08 XXXX XXXX (e.g., 02 9876 5432)\n• International: +XX XXXXXXXXXX"
            else:
                state["phone"] = formatted or msg
                state["phone_type"] = phone_type
                state["stage"] = "date"
                reply = "Great! Which date would you like? (e.g., 27/11/2025 or DD/MM/YYYY)"

        elif state["stage"] == "date":
            parsed = parse_date(msg)
            if not parsed:
                reply = "Please use DD/MM/YYYY or YYYY-MM-DD format (e.g., 27/11/2025)."
            else:
                if is_weekend(parsed):
                    next3 = next_available_dates(parsed)
                    if next3:
                        pretty = [datetime.strptime(d, "%Y-%m-%d").strftime("%d %B %Y") for d in next3]
                        reply = "Bookings are only available on weekdays (Mon–Fri).\n\nNext available dates:\n" + "\n".join(f"• {p}" for p in pretty)
                    else:
                        reply = "Bookings are only available on weekdays (Mon–Fri)."
                elif is_past_date(parsed):
                    next3 = next_available_dates(datetime.now(LOCAL_TZ).date().isoformat())
                    pretty = [datetime.strptime(d, "%Y-%m-%d").strftime("%d %B %Y") for d in next3]
                    reply = "You cannot book a past date.\n\nNext available dates:\n" + "\n".join(f"• {p}" for p in pretty)
                elif parsed in get_blocked_dates():
                    next3 = next_available_dates(parsed)
                    if next3:
                        pretty = [datetime.strptime(d, "%Y-%m-%d").strftime("%d %B %Y") for d in next3]
                        reply = "That date is not available.\n\nNext available dates:\n" + "\n".join(f"• {p}" for p in pretty)
                    else:
                        reply = "That date is not available."
                else:
                    free = [t for t in TIME_SLOTS if not is_booked(parsed, t)]
                    if not free:
                        next3 = next_available_dates(parsed)
                        if next3:
                            pretty = [datetime.strptime(d, "%Y-%m-%d").strftime("%d %B %Y") for d in next3]
                            reply = "That day is fully booked.\n\nNext available dates:\n" + "\n".join(f"• {p}" for p in pretty)
                        else:
                            reply = "That day is fully booked."
                    else:
                        state["date"] = parsed; state["stage"] = "time"; state["available"] = free
                        human = datetime.strptime(parsed, "%Y-%m-%d").strftime("%d %B %Y")
                        buttons = [{"label": t, "value": t} for t in free]
                        save_session(session_id, state)
                        resp = make_response(jsonify({"reply": f"Available times on {human}:", "buttons": buttons, "session_id": session_id}))
                        resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
                        return resp

        elif state["stage"] == "time":
            tnorm = normalize_time(msg) or msg.replace(".", ":")
            if tnorm not in TIME_SLOTS:
                reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
            elif is_booked(state.get("date"), tnorm):
                reply = "That time is now taken. Please choose another."
            elif not meets_lead_time(state.get("date"), tnorm):
                next3 = next_available_dates(state.get("date"))
                if next3:
                    pretty = []
                    for d in next3:
                        free = [t for t in TIME_SLOTS if not is_booked(d, t)]
                        if free:
                            pretty.append(f"{datetime.strptime(d, '%Y-%m-%d').strftime('%d %B %Y')} — {', '.join(free)}")
                            if len(pretty) >= 3:
                                break
                    reply = f"Too late to book that time — you need at least {LEAD_TIME_MINUTES} minutes notice.\n\nNext available:\n" + "\n".join(f"• {p}" for p in pretty)
                else:
                    reply = f"Too late to book that time — you need at least {LEAD_TIME_MINUTES} minutes notice."
            else:
                # All good — create booking
                bid = save_booking(state.get("name"), state.get("email"), state.get("phone"), state.get("date"), tnorm)
                booking_row = get_booking(bid)
                # send confirmation email (non-fatal)
                try:
                    send_confirmation_email(state.get("name"), state.get("email"), state.get("phone"), state.get("date"), tnorm)
                except Exception:
                    app.logger.exception("confirmation email failed")
                # notify admin
                try:
                    notify_on_booking(booking_row)
                except Exception:
                    app.logger.exception("admin notify failed")
                human = datetime.strptime(state.get("date"), "%Y-%m-%d").strftime("%d %B %Y")
                reply = f"✓ Confirmed!\n\nYour assessment call is scheduled for:\n{human} at {tnorm}\n\nYou'll receive a confirmation email shortly.\n\n(Type 'cancel' if you need to change this)"
                # clear session from DB
                delete_session(session_id)
                # return response
                resp = make_response(jsonify({"reply": reply, "session_id": session_id}))
                resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
                return resp

        else:
            reply = "Sorry — something went wrong. Please type 'restart' to start over."

        # persist state
        save_session(session_id, state)

        # Build response
        if isinstance(reply, dict):
            response = {
                "reply": reply.get("text", ""),
                "buttons": reply.get("buttons", []),
                "session_id": session_id
            }
        else:
            response = {"reply": reply, "session_id": session_id}

        resp = make_response(jsonify(response))
        resp.set_cookie("sid", session_id, httponly=True, samesite="Lax")
        return resp

    except Exception as e:
        app.logger.exception("chat error: %s", e)
        return jsonify({"reply": "Server error. Please try again or type 'restart'."}), 500

# ---------------- Run ----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
