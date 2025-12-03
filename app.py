# app.py — final production-ready ACOP chatbot backend (Option A)
# Uses templates: templates/index.html, templates/admin.html,
# templates/admin_login.html, templates/admin_settings.html
#
# Features:
#  - persistent chat sessions (SQLite)
#  - robust date/time parsing
#  - Mailtrap email sending (admin + client, .ics)
#  - Teams webhook notifications (configurable via admin settings)
#  - Admin panel (login/logout, view, create, delete, export, settings, test email/teams)
#  - Safe error handling + logging
#  - Render-compatible (binds 0.0.0.0 to PORT)
import os
import re
import io
import json
import csv
import uuid
import logging
from datetime import datetime, timedelta
from functools import wraps
from email.message import EmailMessage

import pytz
import requests
from icalendar import Calendar, Event

from flask import (
    Flask, request, jsonify, make_response, redirect, url_for,
    session, flash, send_file, render_template
)
from flask_cors import CORS
import sqlite3
import smtplib

# ---------- App setup ----------
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET", "acop-2025-final")
CORS(app)
logging.basicConfig(level=logging.INFO)

# ---------- Config ----------
DB_FILE = os.getenv("DB_FILE", "bookings.db")
LOCAL_TZ = pytz.timezone(os.getenv("LOCAL_TZ", "Australia/Sydney"))
TIME_SLOTS = ["09:00", "11:00", "15:30"]

# Mailtrap defaults you confirmed (override via env)
SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "17d873b3a11a38")
SMTP_PASS = os.getenv("SMTP_PASS", "453b9c740a0729")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")

# Teams default (can be configured in admin settings)
TEAMS_WEBHOOK_ENV = os.getenv("TEAMS_WEBHOOK", "")

# Admin auth (override via env if desired)
ADMIN_USER = os.getenv("ADMIN_USER", "Admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Acop2025!")

# ---------- Database helpers ----------
def get_conn():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # bookings
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            date TEXT NOT NULL, -- YYYY-MM-DD
            time TEXT NOT NULL, -- HH:MM
            created_at TEXT NOT NULL
        )
    """)
    # admin settings (single row)
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
    # chat sessions (persistent)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            sid TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # ensure single settings row
    cur.execute("INSERT OR IGNORE INTO admin_settings (id) VALUES (1)")
    conn.commit()
    conn.close()

init_db()

# ---------- Settings helpers ----------
def get_settings():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT email_per_booking, attach_csv, daily_summary, weekly_summary, teams_enabled, teams_webhook FROM admin_settings WHERE id=1")
    row = cur.fetchone()
    conn.close()
    defaults = {
        "email_per_booking": True,
        "attach_csv": True,
        "daily_summary": True,
        "weekly_summary": True,
        "teams_enabled": True,
        "teams_webhook": ""
    }
    if not row:
        return defaults
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
    sets = []
    params = []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k} = ?")
            v = kwargs[k]
            if isinstance(v, bool):
                params.append(1 if v else 0)
            else:
                params.append(v)
    if not sets:
        return
    sql = "UPDATE admin_settings SET " + ", ".join(sets) + " WHERE id=1"
    conn = get_conn(); cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit(); conn.close()

# ---------- Chat session (persistent) ----------
def load_session(sid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT state FROM chat_sessions WHERE sid=?", (sid,))
    row = cur.fetchone(); conn.close()
    if not row:
        return {"stage": "name"}
    try:
        return json.loads(row[0])
    except Exception:
        return {"stage": "name"}

def save_session(sid, state):
    now = datetime.now(LOCAL_TZ).isoformat()
    text = json.dumps(state)
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO chat_sessions (sid, state, updated_at) VALUES (?, ?, ?)", (sid, text, now))
    conn.commit(); conn.close()

def delete_session(sid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM chat_sessions WHERE sid=?", (sid,))
    conn.commit(); conn.close()

# ---------- Bookings helpers ----------
def is_booked(date_str, time_str):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date_str, time_str))
    r = cur.fetchone(); conn.close()
    return r is not None

def save_booking(name, email, phone, date_str, time_str):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO bookings (name,email,phone,date,time,created_at) VALUES (?,?,?,?,?,?)",
                (name, email, phone, date_str, time_str, datetime.now(LOCAL_TZ).isoformat()))
    conn.commit()
    bid = cur.lastrowid
    conn.close()
    return bid

def get_booking(bid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings WHERE id=?", (bid,))
    row = cur.fetchone(); conn.close()
    return row

def all_bookings(start=None, end=None):
    conn = get_conn(); cur = conn.cursor()
    if start and end:
        cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings WHERE date BETWEEN ? AND ? ORDER BY date,time", (start, end))
    else:
        cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings ORDER BY date,time")
    rows = cur.fetchall(); conn.close()
    return rows

def delete_booking(bid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM bookings WHERE id=?", (bid,))
    conn.commit(); conn.close()

# ---------- Date / Time parsing ----------
_time_re = re.compile(r'^\s*(\d{1,2})(?::|\.|)?(\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?\s*$', re.I)
def normalize_time(s):
    if not s or not isinstance(s, str):
        return None
    s_clean = s.strip().lower().replace(' ', '').replace('hrs','')
    # direct hh:mm
    if re.match(r'^\d{1,2}:\d{2}$', s_clean):
        hh_mm = s_clean
    elif re.match(r'^\d{3,4}$', s_clean):  # 900, 1530
        if len(s_clean) == 3:
            hh_mm = '0' + s_clean[0] + ':' + s_clean[1:]
        else:
            hh_mm = s_clean[:2] + ':' + s_clean[2:]
    else:
        m = _time_re.match(s)
        if not m:
            return None
        h = int(m.group(1))
        mmin = m.group(2) or '00'
        ampm = (m.group(3) or '').lower()
        if ampm.startswith('p') and h < 12:
            h += 12
        if ampm.startswith('a') and h == 12:
            h = 0
        hh_mm = f"{h:02d}:{int(mmin):02d}"
    if hh_mm in TIME_SLOTS:
        return hh_mm
    # tolerances
    for ts in TIME_SLOTS:
        if hh_mm == ts:
            return ts
    return None

def parse_date_input(s):
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y","%d-%m-%Y","%d/%m/%y","%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt)
            return d.strftime("%Y-%m-%d")
        except:
            continue
    return None

def is_past(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date() < datetime.now(LOCAL_TZ).date()
    except:
        return False

# ---------- Email & Teams ----------
def send_email_with_attachments(to_email, subject, plain_text, html=None, attachments=None):
    try:
        msg = EmailMessage()
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(plain_text)
        if html:
            msg.add_alternative(html, subtype="html")
        if attachments:
            for fname, data_bytes, subtype in attachments:
                maintype = "text" if subtype == "csv" else "application"
                msg.add_attachment(data_bytes, maintype=maintype, subtype=subtype, filename=fname)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        app.logger.info("Email sent to %s subject=%s", to_email, subject)
        return True
    except Exception as e:
        app.logger.exception("Email send failed: %s", e)
        return False

def make_single_booking_csv_bytes(row):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID","Name","Email","Phone","Date","Time","CreatedAt"])
    w.writerow(row)
    return buf.getvalue().encode('utf-8')

def send_confirmation_email(name, email, phone, date_str, time_str):
    try:
        subj = "Your ACOP Assessment Call is Confirmed"
        pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %B %Y")
        text = f"Hi {name},\n\nYour call is on {pretty} at {time_str}.\n\n— ACOP Team"
        html = f"<h3>Hi {name}!</h3><p>Your call is on <strong>{pretty} at {time_str}</strong>.</p>"
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        dt = LOCAL_TZ.localize(dt)
        cal = Calendar(); cal.add('prodid','-//ACOP//'); cal.add('version','2.0')
        ev = Event()
        ev.add('summary','ACOP Assessment Call')
        ev.add('dtstart', dt)
        ev.add('dtend', dt + timedelta(minutes=60))
        ev.add('description', f'Call with {name}')
        cal.add_component(ev)
        attachments = [("ACOP-Call.ics", cal.to_ical(), "ics")]
        return send_email_with_attachments(email, subj, text, html=html, attachments=attachments)
    except Exception as e:
        app.logger.exception("send_confirmation_email failed: %s", e)
        return False

def post_to_teams(webhook, text):
    if not webhook:
        return False
    try:
        resp = requests.post(webhook, json={"text": text}, timeout=8)
        resp.raise_for_status()
        return True
    except Exception as e:
        app.logger.exception("post_to_teams failed: %s", e)
        return False

def notify_on_booking(booking_row):
    try:
        settings = get_settings()
        pretty = datetime.strptime(booking_row[4], "%Y-%m-%d").strftime("%d %B %Y")
        if settings.get("email_per_booking"):
            subj = f"New Booking: {booking_row[1]} — {pretty} {booking_row[5]}"
            plain = (
                f"A new booking has been made:\n\n"
                f"Name: {booking_row[1]}\nEmail: {booking_row[2]}\nPhone: {booking_row[3]}\nDate: {pretty}\nTime: {booking_row[5]}\n"
            )
            html = (
                f"<h3>New Booking</h3>"
                f"<p><strong>Name:</strong> {booking_row[1]}</p>"
                f"<p><strong>Email:</strong> {booking_row[2]}</p>"
                f"<p><strong>Phone:</strong> {booking_row[3]}</p>"
                f"<p><strong>Date:</strong> {pretty}</p>"
                f"<p><strong>Time:</strong> {booking_row[5]}</p>"
            )
            attachments = []
            if settings.get("attach_csv"):
                attachments.append(("booking.csv", make_single_booking_csv_bytes(booking_row), "csv"))
            send_email_with_attachments(ADMIN_EMAIL, subj, plain, html=html, attachments=attachments if attachments else None)
        webhook = settings.get("teams_webhook") or TEAMS_WEBHOOK_ENV
        if settings.get("teams_enabled") and webhook:
            text = f"📅 New Booking — {booking_row[1]} — {booking_row[4]} {booking_row[5]}"
            post_to_teams(webhook, text)
    except Exception as e:
        app.logger.exception("notify_on_booking failed: %s", e)

# ---------- Admin auth ----------
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
        u = request.form.get("username","")
        p = request.form.get("password","")
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["admin_logged_in"] = True
            session["admin_username"] = u
            return redirect(url_for("admin"))
        error = "Invalid credentials"
        flash(error)
    # Use your template file
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@require_admin
def admin():
    rows = all_bookings()
    settings = get_settings()
    return render_template("admin.html", bookings=rows, settings=settings, admin_user=session.get("admin_username"))

@app.route("/admin/create", methods=["POST"])
@require_admin
def admin_create():
    name = request.form.get("name","").strip()
    email = request.form.get("email","").strip()
    phone = request.form.get("phone","").strip()
    date = request.form.get("date","").strip()
    time = request.form.get("time","").strip()
    # basic validation
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except:
        flash("Invalid date format (use YYYY-MM-DD)")
        return redirect(url_for("admin"))
    if is_booked(date, time):
        flash("Slot already booked")
        return redirect(url_for("admin"))
    bid = save_booking(name, email, phone, date, time)
    notify_on_booking(get_booking(bid))
    send_confirmation_email(name, email, phone, date, time)
    flash("Booking created")
    return redirect(url_for("admin"))

@app.route("/admin/delete/<int:bid>", methods=["POST"])
@require_admin
def admin_delete(bid):
    delete_booking(bid)
    flash("Booking deleted")
    return redirect(url_for("admin"))

@app.route("/admin/export")
@require_admin
def admin_export():
    rows = all_bookings()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID","Name","Email","Phone","Date","Time","CreatedAt"])
    for r in rows:
        w.writerow(r)
    data = buf.getvalue().encode('utf-8')
    return send_file(io.BytesIO(data), download_name="acop_bookings.csv", as_attachment=True, mimetype="text/csv")

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
        flash("Settings saved")
        return redirect(url_for("admin_settings"))
    settings = get_settings()
    return render_template("admin_settings.html", settings=settings)

@app.route("/admin/test-email")
@require_admin
def admin_test_email():
    ok = send_email_with_attachments(ADMIN_EMAIL, "ACOP Test Email", "This is a test email from ACOP booking system.")
    return "Test email sent." if ok else "Test email failed."

@app.route("/admin/test-teams")
@require_admin
def admin_test_teams():
    settings = get_settings()
    webhook = settings.get("teams_webhook") or TEAMS_WEBHOOK_ENV
    if not webhook:
        return "No Teams webhook configured."
    ok = post_to_teams(webhook, "ACOP Chatbot Test message")
    return "Test teams sent." if ok else "Test teams failed."

# ---------- Chat endpoints ----------
@app.route("/")
def index():
    # serve the index from templates/index.html that you pasted earlier
    return render_template("index.html")

@app.route("/api/message", methods=["POST"])
def api_message():
    try:
        data = request.get_json(silent=True) or {}
        raw = data.get("message", "")
        if raw is None:
            raw = ""
        msg = raw.strip()
        sid = data.get("session_id") or request.cookies.get("sid") or str(uuid.uuid4())

        state = load_session(sid)
        if "stage" not in state:
            state["stage"] = "name"

        reply = ""

        # cancel
        if msg.lower() == "cancel" and state.get("date"):
            conn = get_conn(); cur = conn.cursor()
            cur.execute("DELETE FROM bookings WHERE email=? AND date=?", (state.get("email"), state.get("date")))
            conn.commit(); conn.close()
            state = {"stage": "name"}
            save_session(sid, state)
            reply = "Booking cancelled. Hi — what's your name?"
            resp = make_response(jsonify({"reply": reply, "session_id": sid}))
            resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
            return resp

        # name
        if state["stage"] == "name":
            if len(msg) < 2 or any(c.isdigit() for c in msg):
                reply = "Please enter a valid name."
            else:
                state["name"] = msg.title()
                state["stage"] = "email"
                save_session(sid, state)
                reply = f"Thanks {state['name']}! What's your email?"

        # email
        elif state["stage"] == "email":
            if "@" not in msg or "." not in msg:
                reply = "Please enter a valid email."
            else:
                state["email"] = msg.lower()
                state["stage"] = "phone"
                save_session(sid, state)
                reply = "Your phone number?"

        # phone
        elif state["stage"] == "phone":
            cleaned = "".join(c for c in msg if c.isdigit() or c in "+ -")
            if len(cleaned.replace(" ", "").replace("-", "")) < 8:
                reply = "Please enter a valid phone number."
            else:
                state["phone"] = msg
                state["stage"] = "date"
                save_session(sid, state)
                reply = "Which date? (e.g. 27/11/2025)"

        # date
        elif state["stage"] == "date":
            parsed = parse_date_input(msg)
            if not parsed:
                reply = "Use DD/MM/YYYY, DD-MM-YYYY, or YYYY-MM-DD."
            else:
                try:
                    dobj = datetime.strptime(parsed, "%Y-%m-%d")
                    if dobj.weekday() >= 5 or is_past(parsed):
                        reply = "Please pick a future weekday (Mon-Fri)."
                    else:
                        state["date"] = parsed
                        free = [t for t in TIME_SLOTS if not is_booked(parsed, t)]
                        if not free:
                            reply = "That day is fully booked. Choose another date."
                        else:
                            state["stage"] = "time"
                            state["available"] = free
                            save_session(sid, state)
                            human = dobj.strftime("%d %B %Y")
                            reply = f"Available on {human}: {', '.join(free)}"
                except Exception:
                    reply = "Invalid date — use DD/MM/YYYY."

        # time
        elif state["stage"] == "time":
            normalized = normalize_time(msg)
            if not normalized:
                reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
            elif is_booked(state.get("date"), normalized):
                reply = "That time is now taken. Please choose another."
            else:
                bid = save_booking(state.get("name"), state.get("email"), state.get("phone"), state.get("date"), normalized)
                booking_row = get_booking(bid)
                # attempt notifications but never crash user flow
                try:
                    send_confirmation_email(state.get("name"), state.get("email"), state.get("phone"), state.get("date"), normalized)
                except Exception as e:
                    app.logger.exception("Confirmation email failed: %s", e)
                try:
                    notify_on_booking(booking_row)
                except Exception as e:
                    app.logger.exception("Admin notify failed: %s", e)
                human = datetime.strptime(state.get("date"), "%Y-%m-%d").strftime("%d %B %Y")
                reply = f"Confirmed! Your call is on {human} at {normalized}\n\nType 'cancel' to change it."
                delete_session(sid)

        else:
            reply = "Sorry — something went wrong. Please try again."

        save_session(sid, state)
        resp = make_response(jsonify({"reply": reply, "session_id": sid}))
        resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
        return resp

    except Exception as e:
        app.logger.exception("Error in chat flow: %s", e)
        return jsonify({"reply": "Server error. Please try again."}), 500

# ---------- Run ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug False for Render production
    app.run(host="0.0.0.0", port=port, debug=False)