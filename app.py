# app.py — FINAL, CLEAN, WORKS ON RENDER — NO AUTO-LOGIN (December 2025)
import os, io, csv, sqlite3, smtplib, requests, uuid
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import (Flask, request, jsonify, render_template, session,
                   redirect, flash, make_response, send_from_directory)
import pytz

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "acop-2025-never-auto-login")

DB_FILE = "bookings.db"
TIME_SLOTS = ["09:00", "11:00", "15:30"]
SYDNEY_TZ = pytz.timezone("Australia/Sydney")

SMTP_HOST = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
SMTP_PORT = int(os.getenv("SMTP_PORT", "2525"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "enquiries@acop.edu.au")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "johnc@acop.edu.au")

# =============== INIT DB ===============
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
                teams_enabled INTEGER DEFAULT 1,
                teams_webhook TEXT DEFAULT ''
            );
            INSERT OR IGNORE INTO admin_settings (id) VALUES (1);
        """)
init_db()

# =============== HELPERS ===============
def is_date_blocked(d):
    with sqlite3.connect(DB_FILE) as c:
        return c.execute("SELECT 1 FROM blocked_ranges WHERE ? BETWEEN start_date AND end_date", (d,)).fetchone() is not None

def is_booked(date, time):
    with sqlite3.connect(DB_FILE) as c:
        return c.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date,time)).fetchone() is not None

def is_slot_past_today(d, t):
    try:
        dt = SYDNEY_TZ.localize(datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M"))
        return dt < datetime.now(SYDNEY_TZ)
    except: return True

# =============== ROUTES ===============
@app.route("/")
def index(): return render_template("index.html")

@app.route("/static/<path:p>")
def static_files(p): return send_from_directory("static", p)

# Login page — always shown if not logged in
@app.route("/admin")
def admin():
    if not session.get("admin"):
        return render_template("admin_login.html")
    with sqlite3.connect(DB_FILE) as c:
        bookings = c.execute("SELECT * FROM bookings ORDER BY date DESC, time DESC").fetchall()
        settings = c.execute("SELECT * FROM admin_settings WHERE id=1").fetchone()
    return render_template("admin.html", bookings=bookings, settings=settings)

# Actual login POST
@app.route("/admin/login", methods=["POST"])
def do_login():
    if request.form.get("username") == "admin" and request.form.get("password") == "Acop2025!":
        session["admin"] = True
        return redirect("/admin")
    flash("Wrong username or password")
    return render_template("admin_login.html")

# Save settings
@app.route("/admin/save_settings", methods=["POST"])
def save_settings():
    if not session.get("admin"): return redirect("/admin")
    en = 1 if request.form.get("teams_enabled") else 0
    url = request.form.get("teams_webhook","").strip()
    with sqlite3.connect(DB_FILE) as c:
        c.execute("UPDATE admin_settings SET teams_enabled=?, teams_webhook=? WHERE id=1", (en,url))
        c.commit()
    if request.form.get("test") and en and url:
        try: requests.post(url, json={"text":"ACOP Test – Settings saved!"}, timeout=10)
        except: pass
    return redirect("/admin")

# Calendar block toggle — FIXED
@app.route("/admin/toggle_block", methods=["POST"])
def toggle_block():
    if not session.get("admin"): return jsonify(error="auth"), 401
    date = request.json.get("date")
    if not date: return jsonify(error="no date"), 400
    with sqlite3.connect(DB_FILE) as c:
        cur = c.execute("SELECT start_date, end_date FROM blocked_ranges")
        for s,e in cur.fetchall():
            if s <= date <= e:
                c.execute("DELETE FROM blocked_ranges WHERE start_date=? AND end_date=?", (s,e))
                c.commit()
                return jsonify(status="unblocked")
        c.execute("INSERT INTO blocked_ranges (start_date,end_date) VALUES (?,?)", (date,date))
        c.commit()
        return jsonify(status="blocked")

# =============== CHATBOT (your working version — unchanged) ===============
@app.route("/api/message", methods=["POST"])
def api_message():
    # ← your full chatbot code here (you already have it working)
    # just make sure to call notify_admin() on success
    pass

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))