from flask import Flask, render_template, request, jsonify, make_response
import sqlite3
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage
import smtplib
from icalendar import Calendar, Event

app = Flask(__name__)
app.secret_key = "acop-2025-final"
DB_FILE = "bookings.db"
TIME_SLOTS = ["09:00", "11:00", "15:30"]
SESSIONS = {}

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("CREATE TABLE IF NOT EXISTS bookings (name TEXT, email TEXT, phone TEXT, date TEXT, time TEXT)")
    conn.commit()
    conn.close()
init_db()

def save_booking(name, email, phone, date, time):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO bookings VALUES (?, ?, ?, ?, ?)", (name, email, phone, date, time))
    conn.commit()
    conn.close()

def is_booked(date, time):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
    return cur.fetchone() is not None

def is_past(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date() < datetime.now().date()

def send_email(name, email, phone, date, time):
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
    html = f"<h2>Hi {name}!</h2><p>Your call is on {datetime.strptime(date,'%Y-%m-%d').strftime('%d %B %Y')} at {time}.</p><p>— ACOP Team</p>"
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(cal.to_ical(), maintype="application", subtype="ics", filename="ACOP-Call.ics")

    with smtplib.SMTP("sandbox.smtp.mailtrap.io", 2525) as s:
        s.login("17d873b3a11a38", "453b9c740a0729")
        s.send_message(msg)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/message", methods=["POST"])
def chat():
    msg = request.json.get("message", "").strip()
    sid = request.cookies.get("sid") or str(uuid.uuid4())
    if sid not in SESSIONS:
        SESSIONS[sid] = {"stage":"name"}
    S = SESSIONS[sid]
    reply = ""

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
            if d.weekday() >= 5: raise ValueError
            if is_past(d.strftime("%Y-%m-%d")): raise ValueError
            S["date"] = d.strftime("%Y-%m-%d")
            free = [t for t in TIME_SLOTS if not is_booked(S["date"], t)]
            if not free:
                reply = "That day is fully booked. Another date?"
                S["date"] = None
            else:
                S["stage"] = "time"
                reply = f"Available on {msg}:\n" + ", ".join(free)
        except:
            reply = "Use DD/MM/YYYY and a future weekday."
    elif S["stage"] == "time":
        t = msg.strip().upper().replace(" ","")
        if t not in TIME_SLOTS:
            reply = f"Choose from: {', '.join(TIME_SLOTS)}"
        elif is_booked(S["date"], t):
            reply = "Taken. Try another."
        else:
            save_booking(S["name"], S["email"], S["phone"], S["date"], t)
            send_email(S["name"], S["email"], S["phone"], S["date"], t)
            reply = f"Confirmed! {datetime.strptime(S['date'],'%Y-%m-%d').strftime('%d %B %Y')} at {t}\nType 'cancel' anytime."
            S.clear()

    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("sid", sid, httponly=True, samesite="Lax")
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
EOF