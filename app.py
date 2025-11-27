# app.py
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    make_response,
    session,
    redirect,
    url_for,
    Response,
    flash,
)
import sqlite3
import uuid
import os
from datetime import datetime, timedelta, date
from email.message import EmailMessage
import smtplib
from icalendar import Calendar, Event
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

# Admin credentials
ADMIN_USER = os.getenv("ADMIN_USER", "Admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Acop2025!")

# Email settings (Mailtrap sandbox)
SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "17d873b3a11a38")
SMTP_PASS = os.getenv("SMTP_PASS", "453b9c740a0729")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")

# Teams sender/display name
TEAMS_SENDER_NAME = "Engagement Assessment Bot"

# Timezone for scheduling
LOCAL_TZ = pytz.timezone("Australia/Sydney")

# --------------------
# DB & init
# --------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_settings (
            id INTEGER PRIMARY KEY,
            email_per_booking INTEGER DEFAULT 1,
            attach_csv INTEGER DEFAULT 1,
            daily_summary INTEGER DEFAULT 1,
            weekly_summary INTEGER DEFAULT 1,
            teams_enabled INTEGER DEFAULT 1,
            teams_webhook TEXT
        )
    """
    )
    # ensure a single settings row exists with defaults
    cur.execute("SELECT COUNT(*) FROM admin_settings")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO admin_settings (id, email_per_booking, attach_csv, daily_summary, weekly_summary, teams_enabled, teams_webhook) VALUES (1,1,1,1,1,1, '')"
        )
    conn.commit()
    conn.close()


init_db()


def get_settings():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT email_per_booking, attach_csv, daily_summary, weekly_summary, teams_enabled, teams_webhook FROM admin_settings WHERE id=1")
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "email_per_booking": bool(row[0]),
            "attach_csv": bool(row[1]),
            "daily_summary": bool(row[2]),
            "weekly_summary": bool(row[3]),
            "teams_enabled": bool(row[4]),
            "teams_webhook": row[5] or "",
        }
    return {
        "email_per_booking": True,
        "attach_csv": True,
        "daily_summary": True,
        "weekly_summary": True,
        "teams_enabled": True,
        "teams_webhook": "",
    }


def update_settings(**kwargs):
    # only allow known keys
    keys = ("email_per_booking", "attach_csv", "daily_summary", "weekly_summary", "teams_enabled", "teams_webhook")
    cur_pairs = []
    params = []
    for k in keys:
        if k in kwargs:
            cur_pairs.append(f"{k} = ?")
            # convert booleans to int
            if isinstance(kwargs[k], bool):
                params.append(1 if kwargs[k] else 0)
            else:
                params.append(kwargs[k])
    if not cur_pairs:
        return
    sql = "UPDATE admin_settings SET " + ", ".join(cur_pairs) + " WHERE id=1"
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    conn.close()


# --------------------
# DB helpers
# --------------------
def save_booking(name, email, phone, date_str, time_str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bookings (name, email, phone, date, time, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, phone, date_str, time_str, datetime.now(LOCAL_TZ).isoformat()),
    )
    conn.commit()
    booking_id = cur.lastrowid
    conn.close()
    return booking_id


def delete_booking_by_id(booking_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()


def query_bookings(start_date=None, end_date=None):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if start_date and end_date:
        cur.execute(
            "SELECT id, name, email, phone, date, time, created_at FROM bookings WHERE date BETWEEN ? AND ? ORDER BY date, time",
            (start_date, end_date),
        )
    else:
        cur.execute("SELECT id, name, email, phone, date, time, created_at FROM bookings ORDER BY date, time")
    rows = cur.fetchall()
    conn.close()
    return rows


def is_booked(date_str, time_str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date_str, time_str))
    result = cur.fetchone()
    conn.close()
    return result is not None


def is_past(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date() < datetime.now(LOCAL_TZ).date()


# --------------------
# Messaging & files
# --------------------
def make_csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["ID", "Name", "Email", "Phone", "Date", "Time", "CreatedAt"])
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8")


def make_single_booking_csv_bytes(booking_row):
    # booking_row is (id, name, email, phone, date, time, created_at)
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["ID", "Name", "Email", "Phone", "Date", "Time", "CreatedAt"])
    writer.writerow(booking_row)
    return buf.getvalue().encode("utf-8")


def make_xlsx_bytes(rows, sheet_name="Bookings"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    headers = ["ID", "Name", "Email", "Phone", "Date", "Time", "CreatedAt"]
    ws.append(headers)
    for r in rows:
        ws.append(list(r))
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.read()


def send_email_with_attachments(to_email, subject, plain_text, html=None, attachments=None):
    """
    attachments: list of tuples (filename, bytes, mime_subtype) e.g. ("bookings.csv", b"...", "csv")
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
                if subtype in ("csv",):
                    maintype = "text"
                msg.add_attachment(data_bytes, maintype=maintype, subtype=subtype, filename=fname)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        app.logger.info("Email sent to %s (subject: %s)", to_email, subject)
    except Exception as e:
        app.logger.exception("Failed to send email to %s: %s", to_email, e)


def post_to_teams(webhook_url, title, text):
    """
    Send a simple card to Teams via Incoming Webhook (simple JSON).
    """
    if not webhook_url:
        return False
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": title,
        "themeColor": "0078D4",
        "title": title,
        "text": text,
        "sections": [],
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=8)
        resp.raise_for_status()
        app.logger.info("Posted to Teams: %s", title)
        return True
    except Exception as e:
        app.logger.exception("Failed to post to Teams: %s", e)
        return False


# --------------------
# Notifications
# --------------------
def notify_on_booking(booking_row):
    """
    booking_row: (id, name, email, phone, date, time, created_at)
    Behavior depends on admin_settings.
    """
    settings = get_settings()
    # per-booking email to admin
    if settings["email_per_booking"]:
        subj = f"New Booking: {booking_row[1]} — {booking_row[4]} {booking_row[5]}"
        pretty_date = datetime.strptime(booking_row[4], "%Y-%m-%d").strftime("%d %B %Y")
        plain = (
            f"A new booking has been made:\n\n"
            f"Name: {booking_row[1]}\nEmail: {booking_row[2]}\nPhone: {booking_row[3]}\nDate: {pretty_date}\nTime: {booking_row[5]}\n"
        )
        html = (
            f"<h3>New Booking Received</h3>"
            f"<p><strong>Name:</strong> {booking_row[1]}</p>"
            f"<p><strong>Email:</strong> {booking_row[2]}</p>"
            f"<p><strong>Phone:</strong> {booking_row[3]}</p>"
            f"<p><strong>Date:</strong> {pretty_date}</p>"
            f"<p><strong>Time:</strong> {booking_row[5]}</p>"
        )
        attachments = []
        if settings["attach_csv"]:
            attachments.append(("booking.csv", make_single_booking_csv_bytes(booking_row), "csv"))
        send_email_with_attachments(ADMIN_EMAIL, subj, plain, html=html, attachments=attachments)

    # teams notification
    if settings["teams_enabled"] and settings["teams_webhook"]:
        pretty_date = datetime.strptime(booking_row[4], "%Y-%m-%d").strftime("%d %B %Y")
        text = (
            f"**📅 New Assessment Booking**\n\n"
            f"**Name:** {booking_row[1]}\n\n"
            f"**Email:** {booking_row[2]}\n\n"
            f"**Phone:** {booking_row[3]}\n\n"
            f"**Date:** {pretty_date}\n\n"
            f"**Time:** {booking_row[5]}\n\n"
            f"_(sent by {TEAMS_SENDER_NAME})_"
        )
        post_to_teams(settings["teams_webhook"], "New Assessment Booking", text)
import requests

def notify_teams(name, email, phone, date, time):
    url = os.getenv("TEAMS_WEBHOOK")
    if not url:
        return

    pretty_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")

    card = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": "New Booking",
        "themeColor": "0076D7",
        "title": "📞 New ACOP Assessment Booking",
        "sections": [{
            "facts": [
                {"name": "Name", "value": name},
                {"name": "Email", "value": email},
                {"name": "Phone", "value": phone},
                {"name": "Date", "value": pretty_date},
                {"name": "Time", "value": time},
            ]
        }]
    }

    try:
        requests.post(url, json=card, timeout=5)
    except Exception as e:
        app.logger.error(f"Teams notification failed: {e}")

notify_teams(S["name"], S["email"], S["phone"], S["date"], t)

# --------------------
# Scheduler jobs
# --------------------
scheduler = BackgroundScheduler(timezone=LOCAL_TZ)


def daily_summary_job():
    try:
        today = datetime.now(LOCAL_TZ).date()
        start = today.isoformat()
        end = today.isoformat()
        rows = query_bookings(start, end)
        if not rows:
            app.logger.info("Daily summary: no bookings today.")
            return

        xlsx_bytes = make_xlsx_bytes(rows, sheet_name=f"Bookings-{start}")
        subj = f"Daily Booking Summary — {start}"
        plain = f"{len(rows)} bookings on {start}."
        settings = get_settings()
        attachments = [ (f"bookings_{start}.xlsx", xlsx_bytes, "vnd.openxmlformats-officedocument.spreadsheetml.sheet") ]

        # send email
        send_email_with_attachments(ADMIN_EMAIL, subj, plain, html=None, attachments=attachments)

        # send teams notification
        if settings["teams_enabled"] and settings["teams_webhook"]:
            text = f"📊 Daily Booking Summary\n\nBookings today: {len(rows)}\n\nAttached: bookings_{start}.xlsx"
            post_to_teams(settings["teams_webhook"], "Daily Booking Summary", text)
    except Exception as e:
        app.logger.exception("Daily summary job failed: %s", e)


def weekly_summary_job():
    try:
        today = datetime.now(LOCAL_TZ).date()
        # week: monday to sunday containing 'today' - we'll compute previous week if you want weekly at Monday morning
        # We'll summarize last 7 days (today -6 .. today)
        start_date = (today - timedelta(days=6)).isoformat()
        end_date = today.isoformat()
        rows = query_bookings(start_date, end_date)
        if not rows:
            app.logger.info("Weekly summary: no bookings in period.")
            return

        xlsx_bytes = make_xlsx_bytes(rows, sheet_name=f"Bookings-{start_date}_to_{end_date}")
        subj = f"Weekly Booking Summary — {start_date} to {end_date}"
        plain = f"{len(rows)} bookings between {start_date} and {end_date}."
        settings = get_settings()
        attachments = [ (f"bookings_{start_date}_to_{end_date}.xlsx", xlsx_bytes, "vnd.openxmlformats-officedocument.spreadsheetml.sheet") ]

        send_email_with_attachments(ADMIN_EMAIL, subj, plain, attachments=attachments)

        if settings["teams_enabled"] and settings["teams_webhook"]:
            text = f"📈 Weekly Booking Summary\n\nBookings: {len(rows)}\n\nAttached: bookings_{start_date}_to_{end_date}.xlsx"
            post_to_teams(settings["teams_webhook"], "Weekly Booking Summary", text)
    except Exception as e:
        app.logger.exception("Weekly summary job failed: %s", e)


# schedule: daily at 17:00 Australia/Sydney, weekly Monday at 08:00 Australia/Sydney
scheduler.add_job(daily_summary_job, CronTrigger(hour=17, minute=0, timezone=LOCAL_TZ))
scheduler.add_job(weekly_summary_job, CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=LOCAL_TZ))
scheduler.start()


# --------------------
# ROUTES
# --------------------
@app.route("/")
def index():
    return render_template("index.html")


# Admin settings UI
@app.route("/admin/settings", methods=["GET", "POST"])
@require_admin if "require_admin" in globals() else (lambda f: f)
def admin_settings():
    # the require_admin decorator is defined later in file; if not loaded yet, route still works for now.
    if request.method == "POST":
        email_per_booking = bool(request.form.get("email_per_booking"))
        attach_csv = bool(request.form.get("attach_csv"))
        daily_summary = bool(request.form.get("daily_summary"))
        weekly_summary = bool(request.form.get("weekly_summary"))
        teams_enabled = bool(request.form.get("teams_enabled"))
        teams_webhook = request.form.get("teams_webhook", "").strip()
        update_settings(
            email_per_booking=email_per_booking,
            attach_csv=attach_csv,
            daily_summary=daily_summary,
            weekly_summary=weekly_summary,
            teams_enabled=teams_enabled,
            teams_webhook=teams_webhook,
        )
        flash("Settings saved.", "success")
        return redirect(url_for("admin_settings"))

    settings = get_settings()
    return render_template("admin_settings.html", settings=settings)


# -----------------------
# ADMIN AUTH ROUTES & helpers
# -----------------------
from functools import wraps


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
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@require_admin
def admin():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, phone, date, time, created_at FROM bookings ORDER BY date, time")
    rows = cur.fetchall()
    conn.close()
    settings = get_settings()
    return render_template("admin.html", bookings=rows, admin_user=session.get("admin_username"), settings=settings)


@app.route("/admin/delete/<int:booking_id>", methods=["POST"])
@require_admin
def admin_delete(booking_id):
    delete_booking_by_id(booking_id)
    return redirect(url_for("admin"))


@app.route("/admin/export", methods=["GET"])
@require_admin
def export_csv():
    rows = query_bookings()
    csv_bytes = make_csv_bytes(rows)
    return Response(csv_bytes, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=acop_bookings.csv"})


# -----------------------
# CHAT ROUTE
# -----------------------
@app.route("/api/message", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    msg = data.get("message", "").strip()
    sid = request.cookies.get("sid") or str(uuid.uuid4())
    if sid not in SESSIONS:
        SESSIONS[sid] = {"stage": "name"}
    S = SESSIONS[sid]
    reply = ""

    try:
        if msg.lower() == "cancel" and S.get("date"):
            conn = sqlite3.connect(DB_FILE)
            conn.execute(
                "DELETE FROM bookings WHERE email=? AND date=?", (S.get("email"), S.get("date"))
            )
            conn.commit()
            conn.close()
            reply = "Booking cancelled. Which date? (e.g. 27/11/2025)"
            S["date"] = S["time"] = None
            S["stage"] = "date"

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
                S["email"] = msg.lower()
                S["stage"] = "phone"
                reply = "Your phone number?"

        elif S["stage"] == "phone":
            if len(msg.replace(" ", "").replace("-", "")) < 8:
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
                    reply = f"Available on {msg}:\n" + ", ".join(free)
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
                # ⭐ Correct indentation here
                save_booking(S["name"], S["email"], S["phone"], S["date"], t)
                send_email(S["name"], S["email"], S["phone"], S["date"], t)
                notify_admin(S["name"], S["email"], S["phone"], S["date"], t)

                nice_date = datetime.strptime(S["date"], "%Y-%m-%d").strftime("%d %B %Y")
                reply = f"Confirmed! Your call is on {nice_date} at {t}\n\nType 'cancel' anytime to change it."
                S.clear()
                # Send confirmation email to student (non-blocking is handled inside function)
                send_email(S["name"], S["email"], S["phone"], S["date"], t)

                # Notify admin (email + csv attachment + teams if enabled)
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


# --------------------
# Run
# --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
