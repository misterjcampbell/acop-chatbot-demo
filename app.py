# app.py - Complete, deploy-ready (Mailtrap + Teams + Admin + Chat)
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

# ---------- App config ----------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "acop-2025-final")
CORS(app)

# ---------- Defaults / Constants ----------
DB_FILE = "bookings.db"
TIME_SLOTS = ["09:00", "11:00", "15:30"]
LOCAL_TZ = pytz.timezone(os.getenv("LOCAL_TZ", "Australia/Sydney"))

# Mailtrap default (you confirmed these)
SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "17d873b3a11a38")
SMTP_PASS = os.getenv("SMTP_PASS", "453b9c740a0729")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")

# Teams
TEAMS_WEBHOOK_ENV = os.getenv("TEAMS_WEBHOOK", "")

# Admin credentials (override via env if desired)
ADMIN_USER = os.getenv("ADMIN_USER", "Admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Acop2025!")

# ---------- DB init ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # bookings table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            date TEXT NOT NULL,    -- YYYY-MM-DD
            time TEXT NOT NULL,    -- HH:MM
            created_at TEXT NOT NULL
        )
    """)
    # admin settings table (single-row)
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
    cur.execute("SELECT COUNT(*) FROM admin_settings")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO admin_settings (id,email_per_booking,attach_csv,daily_summary,weekly_summary,teams_enabled,teams_webhook) VALUES (1,1,1,1,1,1,'')"
        )
    conn.commit()
    conn.close()

init_db()

# ---------- Settings helpers ----------
def get_settings():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT email_per_booking, attach_csv, daily_summary, weekly_summary, teams_enabled, teams_webhook FROM admin_settings WHERE id=1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return {
            "email_per_booking": True,
            "attach_csv": True,
            "daily_summary": True,
            "weekly_summary": True,
            "teams_enabled": True,
            "teams_webhook": "",
        }
    return {
        "email_per_booking": bool(row[0]),
        "attach_csv": bool(row[1]),
        "daily_summary": bool(row[2]),
        "weekly_summary": bool(row[3]),
        "teams_enabled": bool(row[4]),
        "teams_webhook": row[5] or "",
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
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    conn.close()

# ---------- DB helpers ----------
def save_booking(name, email, phone, date_str, time_str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bookings (name, email, phone, date, time, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, phone, date_str, time_str, datetime.now(LOCAL_TZ).isoformat())
    )
    conn.commit()
    booking_id = cur.lastrowid
    conn.close()
    return booking_id

def query_bookings(start_date=None, end_date=None):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if start_date and end_date:
        cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings WHERE date BETWEEN ? AND ? ORDER BY date,time", (start_date, end_date))
    else:
        cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings ORDER BY date,time")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_booking(booking_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings WHERE id=?", (booking_id,))
    row = cur.fetchone()
    conn.close()
    return row

def delete_booking_by_id(booking_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()

def is_booked(date_str, time_str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date_str, time_str))
    r = cur.fetchone()
    conn.close()
    return r is not None

def is_past(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date() < datetime.now(LOCAL_TZ).date()

# ---------- Email & Teams helpers ----------
def make_single_booking_csv_bytes(row):
    # row: (id,name,email,phone,date,time,created_at)
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    w.writerow(["ID","Name","Email","Phone","Date","Time","CreatedAt"])
    w.writerow(row)
    return buf.getvalue().encode("utf-8")

def send_email_with_attachments(to_email, subject, plain_text, html=None, attachments=None):
    """
    attachments: list of tuples (filename, bytes, mime_subtype)
    mime_subtype examples: "csv" or "vnd.openxmlformats-officedocument.spreadsheetml.sheet" or "ics"
    """
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
                maintype = "application"
                if subtype == "csv":
                    maintype = "text"
                msg.add_attachment(data_bytes, maintype=maintype, subtype=subtype, filename=fname)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        app.logger.info("Email sent to %s (subject: %s)", to_email, subject)
        return True
    except Exception as e:
        app.logger.exception("Failed to send email to %s: %s", to_email, e)
        return False

def send_confirmation_email(name, email, phone, date_str, time_str, attach_ics=True):
    try:
        subj = "Your ACOP Assessment Call is Confirmed"
        pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %B %Y")
        plain = f"Hi {name},\n\nYour call is on {pretty_date} at {time_str}.\n\n— ACOP Team"
        html = f"<h3>Hi {name}!</h3><p>Your call is on {pretty_date} at {time_str}.</p><p>— ACOP Team</p>"

        attachments = []
        if attach_ics:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            cal = Calendar()
            cal.add('prodid', '-//ACOP//')
            cal.add('version', '2.0')
            event = Event()
            event.add('summary', 'ACOP Assessment Call')
            event.add('dtstart', dt)
            event.add('dtend', dt + timedelta(minutes=60))
            event.add('description', f'Call with {name}')
            cal.add_component(event)
            attachments.append(("ACOP-Call.ics", cal.to_ical(), "ics"))

        return send_email_with_attachments(email, subj, plain, html=html, attachments=attachments if attachments else None)
    except Exception as e:
        app.logger.exception("Failed to prepare confirmation email to %s: %s", email, e)
        return False

def post_to_teams(webhook_url, text):
    if not webhook_url:
        app.logger.warning("post_to_teams: no webhook_url provided")
        return False
    payload = {"text": text}
    try:
        resp = requests.post(webhook_url, json=payload, timeout=8)
        resp.raise_for_status()
        app.logger.info("Posted to Teams webhook")
        return True
    except Exception as e:
        app.logger.exception("Failed to post to Teams: %s", e)
        return False

# notify admin (email + attach csv optionally + teams if enabled)
def notify_on_booking(booking_row):
    try:
        settings = get_settings()
        pretty_date = datetime.strptime(booking_row[4], "%Y-%m-%d").strftime("%d %B %Y")
        if settings["email_per_booking"]:
            subj = f"New Booking: {booking_row[1]} — {pretty_date} {booking_row[5]}"
            plain = (
                "A new booking has been made:\n\n"
                f"Name: {booking_row[1]}\n"
                f"Email: {booking_row[2]}\n"
                f"Phone: {booking_row[3]}\n"
                f"Date: {pretty_date}\n"
                f"Time: {booking_row[5]}\n"
            )
            html = (
                "<h3>New Booking</h3>"
                f"<p><strong>Name:</strong> {booking_row[1]}</p>"
                f"<p><strong>Email:</strong> {booking_row[2]}</p>"
                f"<p><strong>Phone:</strong> {booking_row[3]}</p>"
                f"<p><strong>Date:</strong> {pretty_date}</p>"
                f"<p><strong>Time:</strong> {booking_row[5]}</p>"
            )
            attachments = []
            if settings["attach_csv"]:
                attachments.append(("booking.csv", make_single_booking_csv_bytes(booking_row), "csv"))
            send_email_with_attachments(ADMIN_EMAIL, subj, plain, html=html, attachments=attachments if attachments else None)

        # Teams
        settings = get_settings()
        webhook = settings.get("teams_webhook") or TEAMS_WEBHOOK_ENV
        if settings["teams_enabled"] and webhook:
            text = (
                f"📅 New Assessment Booking\n\n"
                f"Name: {booking_row[1]}\n"
                f"Email: {booking_row[2]}\n"
                f"Phone: {booking_row[3]}\n"
                f"Date: {pretty_date}\n"
                f"Time: {booking_row[5]}\n"
            )
            post_to_teams(webhook, text)
    except Exception as e:
        app.logger.exception("notify_on_booking failed: %s", e)

# ---------- Admin auth decorator ----------
def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

# ---------- Admin routes ----------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["admin_logged_in"] = True
            session["admin_username"] = username
            return redirect(url_for("admin"))
        else:
            error = "Invalid credentials"
    # simple login form (replace with template if you want)
    return (
        "<h2>Admin Login</h2>"
        + (f"<p style='color:red'>{error}</p>" if error else "")
        + "<form method='POST'>"
        + "User: <input name='username'><br>"
        + "Pass: <input name='password' type='password'><br>"
        + "<button>Login</button></form>"
    )

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@require_admin
def admin():
    rows = query_bookings()
    settings = get_settings()
    # minimal admin page to view bookings and navigate
    html = "<h2>Admin — Bookings</h2>"
    html += f"<p>Logged in as: {session.get('admin_username')}</p>"
    html += "<a href='/admin/settings'>Settings</a> | <a href='/admin/export'>Export CSV</a> | <a href='/admin/logout'>Logout</a><br><br>"
    html += "<table border='1' cellpadding='6'><tr><th>ID</th><th>Name</th><th>Email</th><th>Phone</th><th>Date</th><th>Time</th><th>Created</th><th>Delete</th></tr>"
    for r in rows:
        html += "<tr>"
        html += f"<td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td><td>{r[5]}</td><td>{r[6]}</td>"
        html += f"<td><form method='POST' action='/admin/delete/{r[0]}' onsubmit='return confirm(\"Delete booking?\");'><button type='submit'>Delete</button></form></td>"
        html += "</tr>"
    html += "</table>"
    # Manual create booking form
    html += "<h3>Create booking</h3>"
    html += "<form method='POST' action='/admin/create'>"
    html += "Name: <input name='name'><br>Email: <input name='email'><br>Phone: <input name='phone'><br>Date (YYYY-MM-DD): <input name='date'><br>Time (HH:MM): <input name='time'><br>"
    html += "<button type='submit'>Create</button></form>"
    return html

@app.route("/admin/create", methods=["POST"])
@require_admin
def admin_create():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    date = request.form.get("date", "").strip()
    time = request.form.get("time", "").strip()
    # basic validation
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except:
        flash("Date must be YYYY-MM-DD")
        return redirect(url_for("admin"))
    if is_booked(date, time):
        flash("Slot already booked")
        return redirect(url_for("admin"))
    booking_id = save_booking(name, email, phone, date, time)
    booking_row = get_booking(booking_id)
    # notify admin / teams
    notify_on_booking(booking_row)
    # send confirmation to client
    send_confirmation_email(name, email, phone, date, time, attach_ics=True)
    flash("Booking created")
    return redirect(url_for("admin"))

@app.route("/admin/delete/<int:booking_id>", methods=["POST"])
@require_admin
def admin_delete(booking_id):
    delete_booking_by_id(booking_id)
    return redirect(url_for("admin"))

@app.route("/admin/export")
@require_admin
def admin_export():
    rows = query_bookings()
    # build CSV bytes
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID","Name","Email","Phone","Date","Time","CreatedAt"])
    for r in rows:
        writer.writerow(r)
    csv_bytes = buf.getvalue().encode("utf-8")
    return send_file(io.BytesIO(csv_bytes), download_name="acop_bookings.csv", as_attachment=True, mimetype="text/csv")

@app.route("/admin/settings", methods=["GET", "POST"])
@require_admin
def admin_settings():
    if request.method == "POST":
        email_per_booking = bool(request.form.get("email_per_booking"))
        attach_csv = bool(request.form.get("attach_csv"))
        daily_summary = bool(request.form.get("daily_summary"))
        weekly_summary = bool(request.form.get("weekly_summary"))
        teams_enabled = bool(request.form.get("teams_enabled"))
        teams_webhook = request.form.get("teams_webhook", "").strip()
        update_settings(email_per_booking=email_per_booking, attach_csv=attach_csv, daily_summary=daily_summary, weekly_summary=weekly_summary, teams_enabled=teams_enabled, teams_webhook=teams_webhook)
        flash("Settings saved.")
        return redirect(url_for("admin_settings"))

    settings = get_settings()
    # render a simple settings form
    html = "<h2>Admin Settings</h2>"
    html += "<form method='POST'>"
    html += f"Email per booking: <input type='checkbox' name='email_per_booking' {'checked' if settings['email_per_booking'] else ''}><br>"
    html += f"Attach CSV to admin email: <input type='checkbox' name='attach_csv' {'checked' if settings['attach_csv'] else ''}><br>"
    html += f"Daily summary enabled: <input type='checkbox' name='daily_summary' {'checked' if settings['daily_summary'] else ''}><br>"
    html += f"Weekly summary enabled: <input type='checkbox' name='weekly_summary' {'checked' if settings['weekly_summary'] else ''}><br>"
    html += f"Teams enabled: <input type='checkbox' name='teams_enabled' {'checked' if settings['teams_enabled'] else ''}><br>"
    html += f"Teams webhook URL: <input name='teams_webhook' value='{settings['teams_webhook']}' style='width:600px'><br>"
    html += "<button type='submit'>Save settings</button></form>"
    html += "<br><button onclick=\"fetch('/admin/test-email').then(r=>r.text()).then(t=>alert(t))\">Send test email</button>"
    html += "&nbsp;<button onclick=\"fetch('/admin/test-teams').then(r=>r.text()).then(t=>alert(t))\">Send test Teams</button>"
    html += "<br><br><a href='/admin'>Back to admin</a>"
    return html

@app.route("/admin/test-email")
@require_admin
def admin_test_email():
    ok = send_email_with_attachments(ADMIN_EMAIL, "ACOP Test Email", "This is a test email from ACOP booking system.")
    return "Test email sent." if ok else "Failed to send test email."

@app.route("/admin/test-teams")
@require_admin
def admin_test_teams():
    settings = get_settings()
    webhook = settings.get("teams_webhook") or TEAMS_WEBHOOK_ENV
    if not webhook:
        return "No Teams webhook configured."
    ok = post_to_teams(webhook, "ACOP Chatbot Test: Teams webhook is working.")
    return "Test Teams message sent." if ok else "Failed to send Teams message."

# ---------- Chat endpoint ----------
@app.route("/api/message", methods=["POST"])
def api_message():
    """
    Expected JSON:
    { "session_id": "<sid>", "message": "<user text>" }
    If session_id omitted, one will be generated and returned in cookie.
    """
    try:
        data = request.get_json(silent=True) or {}
        msg = data.get("message", "").strip()
        sid = data.get("session_id") or request.cookies.get("sid") or str(uuid.uuid4())

        # create session if missing
        if sid not in session:
            # we keep a small session store on server in DB-less structure (reasonable for small app)
            pass

        # We'll implement a simple per-sid in-memory state using a separate dict (not Flask session)
        if "chat_sessions" not in app.config:
            app.config["chat_sessions"] = {}
        SESS = app.config["chat_sessions"]
        if sid not in SESS:
            SESS[sid] = {"stage": "name"}

        S = SESS[sid]
        reply = ""

        # cancel
        if msg.lower() == "cancel" and S.get("date"):
            conn = sqlite3.connect(DB_FILE)
            conn.execute("DELETE FROM bookings WHERE email=? AND date=?", (S.get("email"), S.get("date")))
            conn.commit()
            conn.close()
            S["date"] = S["time"] = None
            S["stage"] = "date"
            reply = "Booking cancelled. Which date? (e.g. 27/11/2025)"
        elif S["stage"] == "name":
            if len(msg) < 2 or any(c.isdigit() for c in msg):
                reply = "Please enter a valid name."
            else:
                S["name"] = msg.title()
                S["stage"] = "email"
                reply = "Hi! I'm here to help you book your assessment call. What's your email?"
        elif S["stage"] == "email":
            if "@" not in msg or "." not in msg:
                reply = "Please enter a valid email."
            else:
                S["email"] = msg.lower()
                S["stage"] = "phone"
                reply = "Your phone number?"
        elif S["stage"] == "phone":
            if len(msg.replace(" ","").replace("-","")) < 8:
                reply = "Please enter a valid phone number."
            else:
                S["phone"] = msg
                S["stage"] = "date"
                reply = "Which date? (e.g. 27/11/2025)"
        elif S["stage"] == "date":
            try:
                d = datetime.strptime(msg, "%d/%m/%Y")
                if d.weekday() >= 5 or is_past(d.strftime("%Y-%m-%d")):
                    raise ValueError
                S["date"] = d.strftime("%Y-%m-%d")
                free = [t for t in TIME_SLOTS if not is_booked(S["date"], t)]
                if not free:
                    reply = "That day is fully booked. Another date?"
                    S["date"] = None
                else:
                    S["stage"] = "time"
                    human_date = d.strftime("%d %B %Y")
                    reply = f"Available on {human_date}: " + ", ".join(free)
            except:
                reply = "Use DD/MM/YYYY and choose a future weekday."
        elif S["stage"] == "time":
            t_input = msg.strip().upper().replace(" ", "").replace(".", ":")
            if ":" not in t_input:
                t_input = t_input + ":00"
            if len(t_input) == 4:
                t_input = "0" + t_input
            t = t_input[:5]
            if t not in TIME_SLOTS:
                reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
            elif is_booked(S["date"], t):
                reply = "That time is now taken. Please choose another."
            else:
                # save booking
                booking_id = save_booking(S["name"], S["email"], S["phone"], S["date"], t)
                booking_row = get_booking(booking_id)
                # send confirmation to client (Mailtrap)
                send_confirmation_email(S["name"], S["email"], S["phone"], S["date"], t, attach_ics=True)
                # notify admin (email + csv + teams depending on settings)
                notify_on_booking(booking_row)
                nice_date = datetime.strptime(S["date"], "%Y-%m-%d").strftime("%d %B %Y")
                reply = f"Confirmed! Your call is on {nice_date} at {t}\n\nType 'cancel' anytime to change it."
                # clear session
                SESS.pop(sid, None)

        # Build response
        resp = make_response(jsonify({"reply": reply, "session_id": sid}))
        resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
        return resp
    except Exception as e:
        app.logger.exception("Error in chat flow: %s", e)
        return jsonify({"reply": "Sorry — server error. Please try again."}), 500

@app.route("/")
def index():
    # Ensure you have templates/index.html
    return render_template("index.html")

# ---------- Render / Run ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Do not run in debug mode on Render production — keep debug False
    app.run(host="0.0.0.0", port=port, debug=False)