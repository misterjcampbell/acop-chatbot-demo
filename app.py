from flask import Flask, render_template, request, jsonify, make_response, session, redirect, url_for, flash
import sqlite3
import uuid
import os
from datetime import datetime, timedelta
from email.message import EmailMessage
import smtplib
from icalendar import Calendar, Event
import logging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
# keep this secret in Render secrets in production
app.secret_key = os.environ.get("FLASK_SECRET", "acop-2025-final")

DB_FILE = "bookings.db"
TIME_SLOTS = ["09:00", "11:00", "15:30"]
SESSIONS = {}

# Admin credentials: read from env, fallback to values you provided
ADMIN_USER = os.getenv("ADMIN_USER", "Admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Acop2025!")

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
            time TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_booking(name, email, phone, date, time):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO bookings (name, email, phone, date, time) VALUES (?, ?, ?, ?, ?)",
                (name, email, phone, date, time))
    conn.commit()
    conn.close()

def delete_booking_by_id(booking_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()

def is_booked(date, time):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
    result = cur.fetchone()
    conn.close()
    return result is not None

def is_past(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date() < datetime.now().date()

def send_email(name, email, phone, date, time):
    """
    Send confirmation email with .ics attachment.
    If email sending fails, log but do not break the booking flow.
    """
    try:
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

        msg = EmailMessage()
        msg["From"] = "enquiries@acop.edu.au"
        msg["To"] = email
        msg["Subject"] = "Your ACOP Assessment Call is Confirmed"
        msg.set_content("Confirmed!")

        html = f"""
            <h2>Hi {name}!</h2>
            <p>Your call is on {datetime.strptime(date,'%Y-%m-%d').strftime('%d %B %Y')} at {time}.</p>
            <p>— ACOP Team</p>
        """
        msg.add_alternative(html, subtype="html")
        msg.add_attachment(cal.to_ical(), maintype="application", subtype="ics", filename="ACOP-Call.ics")

        with smtplib.SMTP("sandbox.smtp.mailtrap.io", 2525) as s:
            s.login("17d873b3a11a38", "453b9c740a0729")
            s.send_message(msg)
        app.logger.info("Email sent to %s", email)
    except Exception as e:
        app.logger.exception("Failed to send email: %s", e)
def notify_admin(name, email, phone, date, time):
    msg = EmailMessage()
    msg["From"] = "enquiries@acop.edu.au"
    msg["To"] = "johnc@acop.edu.au"  # Admin email
    msg["Subject"] = "New ACOP Assessment Booking"

    pretty_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")

    content = (
        f"A new booking has been made:\n\n"
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Phone: {phone}\n"
        f"Date: {pretty_date}\n"
        f"Time: {time}\n\n"
        "Sent automatically by ACOP Booking Bot."
    )
    msg.set_content(content)

    # HTML version
    html = f"""
        <h2>New Booking Received</h2>
        <p><strong>Name:</strong> {name}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Phone:</strong> {phone}</p>
        <p><strong>Date:</strong> {pretty_date}</p>
        <p><strong>Time:</strong> {time}</p>
        <br>
        <p>This notification was sent automatically by the ACOP Booking System.</p>
    """
    msg.add_alternative(html, subtype="html")

    # Send via Mailtrap
    with smtplib.SMTP("sandbox.smtp.mailtrap.io", 2525) as s:
        s.login("17d873b3a11a38", "453b9c740a0729")
        s.send_message(msg)
# -----------------------
# ROUTES
# -----------------------
@app.route("/")
def index():
    return render_template("index.html")

# -----------------------
# ADMIN AUTH ROUTES
# -----------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    # if already logged in, send to /admin
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
            # no flash dependency required, render error directly

    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    return redirect(url_for("admin_login"))

def require_admin(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/admin")
@require_admin
def admin():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, phone, date, time FROM bookings ORDER BY date, time")
    rows = cur.fetchall()
    conn.close()
    return render_template("admin.html", bookings=rows, admin_user=session.get("admin_username"))

@app.route("/admin/delete/<int:booking_id>", methods=["POST"])
@require_admin
def admin_delete(booking_id):
    delete_booking_by_id(booking_id)
    return redirect(url_for("admin"))
import csv
from flask import Response

@app.route("/admin/export", methods=["GET"])
@require_admin
def export_csv():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, phone, date, time FROM bookings ORDER BY date, time")
    rows = cur.fetchall()
    conn.close()

    # Create CSV output in memory
    def generate():
        header = ["ID", "Name", "Email", "Phone", "Date", "Time"]
        yield ",".join(header) + "\n"
        for row in rows:
            yield ",".join(str(col) for col in row) + "\n"

    # Return as downloadable file
    return Response(
        generate(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=acop_bookings.csv"
        }
    )


# -----------------------
# CHAT ROUTE (unchanged)
# -----------------------
@app.route("/api/message", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    msg = data.get("message", "").strip()
    sid = request.cookies.get("sid") or str(uuid.uuid4())
    if sid not in SESSIONS:
        SESSIONS[sid] = {"stage":"name"}
    S = SESSIONS[sid]
    reply = ""

    try:
        if msg.lower() == "cancel" and S.get("date"):
            conn = sqlite3.connect(DB_FILE)
            conn.execute("DELETE FROM bookings WHERE email=? AND date=?", (S.get("email"), S.get("date")))
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
                save_booking(S["name"], S["email"], S["phone"], S["date"], t)
                send_email(S["name"], S["email"], S["phone"], S["date"], t)
                nice_date = datetime.strptime(S["date"], "%Y-%m-%d").strftime("%d %B %Y")
                reply = f"Confirmed! Your call is on {nice_date} at {t}\n\nType 'cancel' anytime to change it."
                S.clear()
    except Exception as e:
        app.logger.exception("Error in chat flow: %s", e)
        reply = "Sorry — something went wrong. Please try again."

    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))