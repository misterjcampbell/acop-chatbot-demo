# app.py (cleaned & corrected)
from flask import (
    Flask, render_template, request, jsonify, make_response, session,
    redirect, url_for, Response, flash
)
import sqlite3
import uuid
import os
from datetime import datetime, timedelta
from email.message import EmailMessage
import smtplib
import logging
import io
import csv
import requests
import pytz

# XLSX
from openpyxl import Workbook

# Scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "acop-2025-final")

DB_FILE = "bookings.db"
TIME_SLOTS = ["09:00", "11:00", "15:30"]
SESSIONS = {}

# Admin credentials (override via Render env)
ADMIN_USER = os.getenv("ADMIN_USER", "Admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Acop2025!")

# Mail settings (override via env)
SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "17d873b3a11a38")
SMTP_PASS = os.getenv("SMTP_PASS", "453b9c740a0729")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")

# Teams sender name
TEAMS_SENDER_NAME = "Engagement Assessment Bot"

# Timezone
LOCAL_TZ = pytz.timezone("Australia/Sydney")

# --------- Database init & helpers ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
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
            teams_webhook TEXT
        )
    """)
    cur.execute("SELECT COUNT(*) FROM admin_settings")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO admin_settings (id,email_per_booking,attach_csv,daily_summary,weekly_summary,teams_enabled,teams_webhook) VALUES (1,1,1,1,1,1,'')")
    conn.commit()
    conn.close()

init_db()

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
    to_set = []
    params = []
    for k in allowed:
        if k in kwargs:
            to_set.append(f"{k} = ?")
            val = kwargs[k]
            if isinstance(val, bool):
                params.append(1 if val else 0)
            else:
                params.append(val)
    if not to_set:
        return
    sql = "UPDATE admin_settings SET " + ", ".join(to_set) + " WHERE id=1"
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    conn.close()

def save_booking(name, email, phone, date_str, time_str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bookings (name,email,phone,date,time,created_at) VALUES (?,?,?,?,?,?)",
        (name, email, phone, date_str, time_str, datetime.now(LOCAL_TZ).isoformat())
    )
    conn.commit()
    bid = cur.lastrowid
    conn.close()
    return bid

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

def delete_booking_by_id(bid):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM bookings WHERE id=?", (bid,))
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

# --------- File builders & email helpers ----------
def make_csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["ID","Name","Email","Phone","Date","Time","CreatedAt"])
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8")

def make_single_booking_csv_bytes(row):
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["ID","Name","Email","Phone","Date","Time","CreatedAt"])
    writer.writerow(row)
    return buf.getvalue().encode("utf-8")

def make_xlsx_bytes(rows, sheet_name="Bookings"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    headers = ["ID","Name","Email","Phone","Date","Time","CreatedAt"]
    ws.append(headers)
    for r in rows:
        ws.append(list(r))
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.read()

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
            for fname, data, subtype in attachments:
                maintype = "application"
                if subtype == "csv":
                    maintype = "text"
                msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        app.logger.info("Email sent to %s", to_email)
    except Exception as e:
        app.logger.exception("Failed to send email to %s: %s", to_email, e)

def post_to_teams(webhook_url, title, text):
    if not webhook_url:
        return False
    payload = {
        "@type":"MessageCard",
        "@context":"http://schema.org/extensions",
        "summary": title,
        "themeColor":"0078D4",
        "title": title,
        "text": text
    }
    try:
        r = requests.post(webhook_url, json=payload, timeout=8)
        r.raise_for_status()
        app.logger.info("Posted to Teams")
        return True
    except Exception as e:
        app.logger.exception("Failed to post to Teams: %s", e)
        return False

# send student confirmation (with .ics)
def send_email(name, email, phone, date_str, time_str):
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        cal = Calendar()
        cal.add("prodid", "-//ACOP//")
        cal.add("version", "2.0")
        event = Event()
        event.add("summary", "ACOP Assessment Call")
        event.add("dtstart", dt)
        event.add("dtend", dt + timedelta(minutes=60))
        event.add("description", f"Call with {name}")
        cal.add_component(event)

        msg = EmailMessage()
        msg["From"] = FROM_EMAIL
        msg["To"] = email
        msg["Subject"] = "Your ACOP Assessment Call is Confirmed"
        msg.set_content("Confirmed!")
        html = f"<h3>Hi {name}!</h3><p>Your call: {datetime.strptime(date_str,'%Y-%m-%d').strftime('%d %B %Y')} at {time_str}.</p>"
        msg.add_alternative(html, subtype="html")
        msg.add_attachment(cal.to_ical(), maintype="application", subtype="ics", filename="ACOP-Call.ics")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        app.logger.info("Confirmation email sent to %s", email)
    except Exception as e:
        app.logger.exception("Failed to send confirmation email to %s: %s", email, e)

# notify admin (email + teams) based on settings
def notify_on_booking(booking_row):
    # booking_row: (id,name,email,phone,date,time,created_at)
    settings = get_settings()
    pretty_date = datetime.strptime(booking_row[4], "%Y-%m-%d").strftime("%d %B %Y")
    if settings["email_per_booking"]:
        subj = f"New Booking: {booking_row[1]} — {pretty_date} {booking_row[5]}"
        plain = f"New booking:\nName: {booking_row[1]}\nEmail: {booking_row[2]}\nPhone: {booking_row[3]}\nDate: {pretty_date}\nTime: {booking_row[5]}"
        html = f"<h3>New Booking</h3><p><strong>Name:</strong> {booking_row[1]}</p><p><strong>Email:</strong> {booking_row[2]}</p><p><strong>Phone:</strong> {booking_row[3]}</p><p><strong>Date:</strong> {pretty_date}</p><p><strong>Time:</strong> {booking_row[5]}</p>"
        attachments = []
        if settings["attach_csv"]:
            attachments.append(("booking.csv", make_single_booking_csv_bytes(booking_row), "csv"))
        send_email_with_attachments(ADMIN_EMAIL, subj, plain, html=html, attachments=attachments)
    if settings["teams_enabled"] and settings["teams_webhook"]:
        text = f"**📅 New Assessment Booking**\n\n**Name:** {booking_row[1]}\n**Email:** {booking_row[2]}\n**Phone:** {booking_row[3]}\n**Date:** {pretty_date}\n**Time:** {booking_row[5]}\n\n_(sent by {TEAMS_SENDER_NAME})_"
        post_to_teams(settings["teams_webhook"], "New Assessment Booking", text)

# --------- Scheduler jobs ----------
scheduler = BackgroundScheduler(timezone=LOCAL_TZ)

def daily_summary_job():
    try:
        today = datetime.now(LOCAL_TZ).date()
        start = today.isoformat()
        end = start
        rows = query_bookings(start, end)
        if not rows:
            app.logger.info("Daily summary: no bookings today.")
            return
        xlsx = make_xlsx_bytes(rows, sheet_name=f"Bookings-{start}")
        subj = f"Daily Booking Summary — {start}"
        plain = f"{len(rows)} bookings on {start}."
        send_email_with_attachments(ADMIN_EMAIL, subj, plain, attachments=[(f"bookings_{start}.xlsx", xlsx, "vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
        settings = get_settings()
        if settings["teams_enabled"] and settings["teams_webhook"]:
            post_to_teams(settings["teams_webhook"], "Daily Booking Summary", f"📊 Daily Booking Summary\n\nBookings today: {len(rows)}\n\nAttached: bookings_{start}.xlsx")
    except Exception as e:
        app.logger.exception("Daily summary job failed: %s", e)

def weekly_summary_job():
    try:
        today = datetime.now(LOCAL_TZ).date()
        start = (today - timedelta(days=6)).isoformat()
        end = today.isoformat()
        rows = query_bookings(start, end)
        if not rows:
            app.logger.info("Weekly summary: no bookings in period.")
            return
        xlsx = make_xlsx_bytes(rows, sheet_name=f"Bookings-{start}_to_{end}")
        subj = f"Weekly Booking Summary — {start} to {end}"
        plain = f"{len(rows)} bookings between {start} and {end}."
        send_email_with_attachments(ADMIN_EMAIL, subj, plain, attachments=[(f"bookings_{start}_to_{end}.xlsx", xlsx, "vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
        settings = get_settings()
        if settings["teams_enabled"] and settings["teams_webhook"]:
            post_to_teams(settings["teams_webhook"], "Weekly Booking Summary", f"📈 Weekly Booking Summary\n\nBookings: {len(rows)}\n\nAttached: bookings_{start}_to_{end}.xlsx")
    except Exception as e:
        app.logger.exception("Weekly summary job failed: %s", e)

scheduler.add_job(daily_summary_job, CronTrigger(hour=17, minute=0, timezone=LOCAL_TZ))
scheduler.add_job(weekly_summary_job, CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=LOCAL_TZ))
scheduler.start()

# --------- Admin auth helpers ----------
from functools import wraps
def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

# --------- Routes: admin + settings ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin"))
    error = None
    if request.method == "POST":
        username = request.form.get("username","")
        password = request.form.get("password","")
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["admin_logged_in"] = True
            session["admin_username"] = username
            return redirect(url_for("admin"))
        else:
            error = "Invalid credentials"
    return render_template("admin_login.html", error=error)

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
    return render_template("admin.html", bookings=rows, admin_user=session.get("admin_username"), settings=settings)

@app.route("/admin/settings", methods=["GET","POST"])
@require_admin
def admin_settings():
    if request.method == "POST":
        email_per_booking = bool(request.form.get("email_per_booking"))
        attach_csv = bool(request.form.get("attach_csv"))
        daily_summary = bool(request.form.get("daily_summary"))
        weekly_summary = bool(request.form.get("weekly_summary"))
        teams_enabled = bool(request.form.get("teams_enabled"))
        teams_webhook = request.form.get("teams_webhook","").strip()
        update_settings(email_per_booking=email_per_booking, attach_csv=attach_csv, daily_summary=daily_summary, weekly_summary=weekly_summary, teams_enabled=teams_enabled, teams_webhook=teams_webhook)
        flash("Settings saved.", "success")
        return redirect(url_for("admin_settings"))
    settings = get_settings()
    return render_template("admin_settings.html", settings=settings)

@app.route("/admin/delete/<int:booking_id>", methods=["POST"])
@require_admin
def admin_delete(booking_id):
    delete_booking_by_id(booking_id)
    return redirect(url_for("admin"))

@app.route("/admin/export", methods=["GET"])
@require_admin
def admin_export():
    rows = query_bookings()
    csv_bytes = make_csv_bytes(rows)
    return Response(csv_bytes, mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=acop_bookings.csv"})

@app.route("/admin/test-teams")
def admin_test_teams():
    webhook = os.getenv("TEAMS_WEBHOOK")
    if not webhook:
        return "TEAMS_WEBHOOK is not set", 500

    try:
        r = requests.post(webhook, json={"text": "ACOP Chatbot Test: Teams webhook is working."})
        if r.status_code in (200, 201, 204):
            return "Test message sent successfully!"
        else:
            return f"Teams returned an error: {r.status_code} – {r.text}"
    except Exception as e:
        return f"Request failed: {str(e)}"

# --------- Chat endpoint ----------
@app.route("/api/message", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    msg = data.get("message","").strip()
    sid = request.cookies.get("sid") or str(uuid.uuid4())
    if sid not in SESSIONS:
        SESSIONS[sid] = {"stage":"name"}
    S = SESSIONS[sid]
    reply = ""

    try:
        # Cancel
        if msg.lower() == "cancel" and S.get("date"):
            conn = sqlite3.connect(DB_FILE)
            conn.execute("DELETE FROM bookings WHERE email=? AND date=?", (S.get("email"), S.get("date")))
            conn.commit()
            conn.close()
            reply = "Booking cancelled. Which date? (e.g. 27/11/2025)"
            S["date"] = S["time"] = None
            S["stage"] = "date"
        # Name
        elif S["stage"] == "name":
            if len(msg) < 2 or any(c.isdigit() for c in msg):
                reply = "Please enter a valid name."
            else:
                S["name"] = msg.title()
                S["stage"] = "email"
                reply = f"Thanks {S['name']}! What's your email?"
        # Email
        elif S["stage"] == "email":
            if "@" not in msg or "." not in msg:
                reply = "Please enter a valid email."
            else:
                S["email"] = msg.lower()
                S["stage"] = "phone"
                reply = "Your phone number?"
        # Phone
        elif S["stage"] == "phone":
            if len(msg.replace(" ","").replace("-","")) < 8:
                reply = "Please enter a valid phone number."
            else:
                S["phone"] = msg
                S["stage"] = "date"
                reply = "Which date? (e.g. 27/11/2025)"
        # Date
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
                    reply = f"Available on {msg}:\n" + ", ".join(free)
            except:
                reply = "Use DD/MM/YYYY and choose a future weekday."
        # Time
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
                # Save booking
                booking_id = save_booking(S["name"], S["email"], S["phone"], S["date"], t)

                # Fetch booking row for notifications
                conn = sqlite3.connect(DB_FILE)
                cur = conn.cursor()
                cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings WHERE id=?", (booking_id,))
                booking_row = cur.fetchone()
                conn.close()

                # Send confirmation (student)
                send_email(S["name"], S["email"], S["phone"], S["date"], t)

                # Notify admin (email + CSV + Teams)
                notify_on_booking(booking_row)

                nice_date = datetime.strptime(S["date"], "%Y-%m-%d").strftime("%d %B %Y")
                reply = f"Confirmed! Your call is on {nice_date} at {t}\n\nType 'cancel' anytime to change it."
                S.clear()
    except Exception as e:
        app.logger.exception("Error in chat flow: %s", e)
        reply = "Sorry — something went wrong. Please try again."

    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
    return resp

# --------- Run ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
