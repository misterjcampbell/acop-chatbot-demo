# app.py — ACOP Booking Chatbot (Final Clean Build)

from flask import (
    Flask, request, jsonify, render_template,
    redirect, url_for, session, send_file, flash, make_response
)
from flask_cors import CORS
import sqlite3
import os
import csv
import io
import uuid
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
import pytz
import requests
from functools import wraps

# ---------------------------------------------------
# FLASK SETUP
# ---------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "acop-2025-final")
CORS(app)

DB_FILE = "bookings.db"
TIME_SLOTS = ["09:00", "11:00", "15:30"]
LOCAL_TZ = pytz.timezone("Australia/Sydney")

# ---------------------------------------------------
# MAIL / TEAMS CONFIG
# ---------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "17d873b3a11a38")
SMTP_PASS = os.getenv("SMTP_PASS", "453b9c740a0729")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")
TEAMS_WEBHOOK = os.getenv("TEAMS_WEBHOOK", "")

ADMIN_USER = os.getenv("ADMIN_USER", "Admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Acop2025!")

# Chat state per user session
chat_sessions = {}

# ---------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # Bookings
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

    # Admin Settings
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_settings (
            id INTEGER PRIMARY KEY,
            email_per_booking INTEGER DEFAULT 1,
            attach_csv INTEGER DEFAULT 1,
            teams_enabled INTEGER DEFAULT 1,
            teams_webhook TEXT DEFAULT ''
        )
    """)
    cur.execute("INSERT OR IGNORE INTO admin_settings (id) VALUES (1)")

    # Blocked Dates
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocked_dates (
            date TEXT PRIMARY KEY
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------
# DATABASE HELPERS
# ---------------------------------------------------
def get_blocked_dates():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT date FROM blocked_dates")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows

def block_date(date):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR IGNORE INTO blocked_dates (date) VALUES (?)", (date,))
    conn.commit()
    conn.close()

def unblock_date(date):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM blocked_dates WHERE date=?", (date,))
    conn.commit()
    conn.close()

def all_bookings():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id,name,email,phone,date,time,created_at FROM bookings ORDER BY date,time")
    rows = cur.fetchall()
    conn.close()
    return rows

def is_booked(date, time):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
    res = cur.fetchone() is not None
    conn.close()
    return res

def save_booking(name, email, phone, date, time):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bookings (name,email,phone,date,time,created_at) VALUES (?,?,?,?,?,?)",
        (name, email, phone, date, time, datetime.now(LOCAL_TZ).isoformat())
    )
    conn.commit()
    bid = cur.lastrowid
    conn.close()
    return bid

def get_booking(bid):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM bookings WHERE id=?", (bid,))
    row = cur.fetchone()
    conn.close()
    return row

# ---------------------------------------------------
# EMAIL / TEAMS
# ---------------------------------------------------
def send_email(to, subject, text, attachments=None):
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)

    if attachments:
        for fname, data, subtype in attachments:
            msg.add_attachment(data, maintype="text", subtype=subtype, filename=fname)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        print("Email error:", e)
        return False

def notify_admin(booking):
    if not booking:
        return
    _, name, email, phone, date, time, _ = booking

    # Email
    body = f"New ACOP Booking:\n{name}\n{email}\n{phone}\n{date} at {time}"
    send_email(ADMIN_EMAIL, "New ACOP Booking", body)

    # Teams
    if TEAMS_WEBHOOK:
        try:
            requests.post(TEAMS_WEBHOOK, json={"text": body})
        except:
            print("Teams notification failed")

# ---------------------------------------------------
# ADMIN AUTH DECORATOR
# ---------------------------------------------------
def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

# ---------------------------------------------------
# ADMIN ROUTES
# ---------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["admin_logged_in"] = True
            return redirect("/admin")
        flash("Invalid login")

    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")

@app.route("/admin")
@require_admin
def admin():
    bookings = all_bookings()
    blocked = get_blocked_dates()
    return render_template("admin.html", bookings=bookings, blocked_dates=blocked)

@app.route("/admin/block", methods=["POST"])
@require_admin
def admin_block():
    date = request.form.get("date")
    if date:
        block_date(date)
    return redirect("/admin")

@app.route("/admin/unblock", methods=["POST"])
@require_admin
def admin_unblock():
    date = request.form.get("date")
    if date:
        unblock_date(date)
    return redirect("/admin")

# ---------------------------------------------------
# API: CHATBOT
# ---------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/message", methods=["POST"])
def api_message():
    data = request.get_json()
    msg = data.get("message", "").strip()
    sid = request.cookies.get("sid") or str(uuid.uuid4())

    S = chat_sessions.setdefault(
        sid, {"stage": "name", "name": None, "email": None, "phone": None, "date": None}
    )

    # FLOW
    if S["stage"] == "name":
        S["name"] = msg.title()
        S["stage"] = "email"
        reply = f"Thanks {S['name']}! What's your email?"

    elif S["stage"] == "email":
        S["email"] = msg.lower()
        S["stage"] = "phone"
        reply = "Your phone number?"

    elif S["stage"] == "phone":
        S["phone"] = msg
        S["stage"] = "date"
        reply = "Which date? (DD/MM/YYYY)"

    elif S["stage"] == "date":
        try:
            d = datetime.strptime(msg, "%d/%m/%Y")
            date = d.strftime("%Y-%m-%d")

            if date in get_blocked_dates():
                reply = "That day is not available. Please choose another."
            else:
                free = [t for t in TIME_SLOTS if not is_booked(date, t)]
                if not free:
                    reply = "No available times. Try another date."
                else:
                    S["date"] = date
                    S["stage"] = "time"
                    reply = "Available: " + ", ".join(free)
        except:
            reply = "Please use DD/MM/YYYY"

    elif S["stage"] == "time":
        t = msg.replace(".", ":")
        if t not in TIME_SLOTS:
            reply = "Please pick a time from: " + ", ".join(TIME_SLOTS)
        elif is_booked(S["date"], t):
            reply = "That time was just taken. Try another."
        else:
            bid = save_booking(S["name"], S["email"], S["phone"], S["date"], t)
            notify_admin(get_booking(bid))
            reply = f"Your booking is confirmed! {S['date']} at {t}"
            chat_sessions.pop(sid)

    else:
        reply = "Something went wrong."

    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("sid", sid, httponly=True)
    return resp


# ---------------------------------------------------
# RUN
# ---------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)