# app.py — ACOP Booking Chatbot (Patched, Full - Option B)
import os
import re
import io
import csv
import json
import uuid
import sqlite3
import smtplib
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
            if isinstance(v, bool):
                params.append(1 if v else 0)
            else:
                params.append(v)
    if not sets:
        return
    sql = "UPDATE admin_settings SET " + ", ".join(sets) + " WHERE id=1"
    conn = get_conn(); cur = conn.cursor()
    cur.execute(sql, params); conn.commit(); conn.close()

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
    # if start_date is today or future, begin search the next day if start is blocked/invalid
    # We'll iterate up to 1 year to be safe
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
    try:
        msg = EmailMessage()
        msg["From"] = FROM_EMAIL; msg["To"] = to_email; msg["Subject"] = subject
        msg.set_content(plain_text)
        if html: msg.add_alternative(html, subtype="html")
        if attachments:
            for fname, data_bytes, subtype in attachments:
                maintype = "text" if subtype == "csv" else "application"
                msg.add_attachment(data_bytes, maintype=maintype, subtype=subtype, filename=fname)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
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
    settings = get_settings()
    pretty = datetime.strptime(booking_row[4], "%Y-%m-%d").strftime("%d %B %Y")
    text = f"New booking: {booking_row[1]} — {pretty} {booking_row[5]}\nEmail: {booking_row[2]}\nPhone: {booking_row[3]}"
    if settings.get("email_per_booking"):
        attachments = []
        if settings.get("attach_csv"):
            buf = io.StringIO(); w = csv.writer(buf); w.writerow(["ID","Name","Email","Phone","Date","Time","Created"]); w.writerow(booking_row); attachments.append(("booking.csv", buf.getvalue().encode('utf-8'), "csv"))
        send_email_with_attachments(ADMIN_EMAIL, f"New Booking: {booking_row[1]}", text, html=None, attachments=attachments if attachments else None)
    webhook = settings.get("teams_webhook") or TEAMS_WEBHOOK_ENV
    if settings.get("teams_enabled") and webhook:
        try: requests.post(webhook, json={"text": text}, timeout=6)
        except Exception: app.logger.exception("teams failed")

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

# Mode B endpoints: admin selects a date in the calendar UI and then presses a button to block/unblock
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
    if not session.get("admin"):
        return redirect("/admin/login")

    if request.method == "GET":
        # load settings from DB
        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM settings")
        rows = cur.fetchall()
        conn.close()

        settings = {
            "email_per_booking": False,
            "attach_csv": False,
            "daily_summary": False,
            "weekly_summary": False,
            "teams_enabled": False,
            "teams_webhook": "",
        }

        for k, v in rows:
            if v.lower() in ("true", "1", "yes"):
                settings[k] = True
            else:
                settings[k] = v

        return render_template("admin_settings.html", settings=settings)

    # POST (AJAX JSON)
    data = request.get_json()

    to_save = {
        "email_per_booking": "true" if data.get("email_per_booking") else "false",
        "attach_csv": "true" if data.get("attach_csv") else "false",
        "daily_summary": "true" if data.get("daily_summary") else "false",
        "weekly_summary": "true" if data.get("weekly_summary") else "false",
        "teams_enabled": "true" if data.get("teams_enabled") else "false",
        "teams_webhook": data.get("teams_webhook", ""),
    }

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    for key, value in to_save.items():
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    conn.commit()
    conn.close()

    return jsonify({"success": True})

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
    except: return "FAIL"

# ---------------- Chat session persistence ----------------
def load_session(sid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT state FROM chat_sessions WHERE sid=?", (sid,))
    row = cur.fetchone(); conn.close()
    if not row:
        return {"stage":"name"}
    try:
        return json.loads(row[0])
    except:
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
        raw = data.get("message", "") or ""
        msg = raw.strip()
        sid = data.get("session_id") or request.cookies.get("sid") or str(uuid.uuid4())

        state = load_session(sid)
        if "stage" not in state: state["stage"] = "name"
        reply = ""

        # cancel
        if msg.lower() == "cancel" and state.get("date"):
            conn = get_conn(); cur = conn.cursor()
            cur.execute("DELETE FROM bookings WHERE email=? AND date=?", (state.get("email"), state.get("date")))
            conn.commit(); conn.close()
            state = {"stage":"name"}; save_session(sid, state)
            reply = "Booking cancelled. Hi — what's your name?"
            resp = make_response(jsonify({"reply": reply, "session_id": sid})); resp.set_cookie("sid", sid, httponly=True, samesite="Lax"); return resp

        # name
        if state["stage"] == "name":
            if len(msg) < 2 or any(c.isdigit() for c in msg):
                reply = "Please enter a valid name."
            else:
                state["name"] = msg.title(); state["stage"] = "email"; save_session(sid, state)
                reply = f"Thanks {state['name']}! What's your email?"

        elif state["stage"] == "email":
            if "@" not in msg or "." not in msg:
                reply = "Please enter a valid email."
            else:
                state["email"] = msg.lower(); state["stage"] = "phone"; save_session(sid, state)
                reply = "Your phone number?"

        elif state["stage"] == "phone":
            cleaned = "".join(c for c in msg if c.isdigit() or c in "+ -")
            if len(cleaned.replace(" ", "").replace("-", "")) < 8:
                reply = "Please enter a valid phone number."
            else:
                state["phone"] = msg; state["stage"] = "date"; save_session(sid, state)
                reply = "Which date? (e.g. 27/11/2025)"

        elif state["stage"] == "date":
            parsed = parse_date(msg)
            if not parsed:
                reply = "Use DD/MM/YYYY or YYYY-MM-DD."
            else:
                if is_weekend(parsed):
                    # suggest next 3 available
                    next3 = next_available_dates(parsed)
                    if next3:
                        pretty = [datetime.strptime(d, "%Y-%m-%d").strftime("%d %B %Y") for d in next3]
                        reply = "Bookings are only available on weekdays (Mon–Fri).\n\nNext available dates:\n" + "\n".join(f"- {p}" for p in pretty)
                    else:
                        reply = "Bookings are only available on weekdays (Mon–Fri) and no future dates are currently open."
                elif is_past_date(parsed):
                    next3 = next_available_dates(datetime.now(LOCAL_TZ).date().isoformat())
                    pretty = [datetime.strptime(d, "%Y-%m-%d").strftime("%d %B %Y") for d in next3]
                    reply = "You cannot book a past date.\n\nNext available dates:\n" + "\n".join(f"- {p}" for p in pretty)
                elif parsed in get_blocked_dates():
                    next3 = next_available_dates(parsed)
                    if next3:
                        pretty = [datetime.strptime(d, "%Y-%m-%d").strftime("%d %B %Y") for d in next3]
                        reply = "That date is not available.\n\nNext available dates:\n" + "\n".join(f"- {p}" for p in pretty)
                    else:
                        reply = "That date is not available. No future dates currently open."
                else:
                    # enforce lead time for same-day late bookings: handled later when selecting time, but we can also present slots now
                    free = [t for t in TIME_SLOTS if not is_booked(parsed, t)]
                    if not free:
                        next3 = next_available_dates(parsed)
                        if next3:
                            pretty = [datetime.strptime(d, "%Y-%m-%d").strftime("%d %B %Y") for d in next3]
                            reply = "That day is fully booked.\n\nNext available dates:\n" + "\n".join(f"- {p}" for p in pretty)
                        else:
                            reply = "That day is fully booked and no future dates are currently open."
                    else:
                        state["date"] = parsed; state["stage"] = "time"; state["available"] = free; save_session(sid, state)
                        human = datetime.strptime(parsed, "%Y-%m-%d").strftime("%d %B %Y")
                        reply = f"Available on {human}: {', '.join(free)}"

        elif state["stage"] == "time":
            tnorm = normalize_time(msg) or msg.replace(".", ":")
            if tnorm not in TIME_SLOTS:
                reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
            elif is_booked(state.get("date"), tnorm):
                reply = "That time is now taken. Please choose another."
            elif not meets_lead_time(state.get("date"), tnorm):
                # suggest next available dates/times
                next3 = next_available_dates(state.get("date"))
                if next3:
                    pretty = []
                    for d in next3:
                        free = [t for t in TIME_SLOTS if not is_booked(d, t)]
                        if free:
                            pretty.append(f"{datetime.strptime(d, '%Y-%m-%d').strftime('%d %B %Y')} — {', '.join(free)}")
                            if len(pretty) >= 3:
                                break
                    reply = f"Too late to book that time — you need at least {LEAD_TIME_MINUTES} minutes notice.\n\nNext available:\n" + "\n".join(f"- {p}" for p in pretty)
                else:
                    reply = f"Too late to book that time — you need at least {LEAD_TIME_MINUTES} minutes notice. No other dates currently available."
            else:
                bid = save_booking(state.get("name"), state.get("email"), state.get("phone"), state.get("date"), tnorm)
                booking_row = get_booking(bid)
                try:
                    send_confirmation_email(state.get("name"), state.get("email"), state.get("phone"), state.get("date"), tnorm)
                except Exception:
                    app.logger.exception("confirmation email failed")
                try:
                    notify_on_booking(booking_row)
                except Exception:
                    app.logger.exception("admin notify failed")
                human = datetime.strptime(state.get("date"), "%Y-%m-%d").strftime("%d %B %Y")
                reply = f"Confirmed! Your call is on {human} at {tnorm}\n\nType 'cancel' to change."
                delete_session(sid)
        else:
            reply = "Sorry — something went wrong. Please try again."

        save_session(sid, state)
        resp = make_response(jsonify({"reply": reply, "session_id": sid}))
        resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
        return resp

    except Exception as e:
        app.logger.exception("chat error: %s", e)
        return jsonify({"reply": "Server error. Please try again."}), 500

# ---------------- Run ----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
