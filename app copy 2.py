# -------------------------------------------------
# app.py  –  Complete ACOP Booking Chatbot
# -------------------------------------------------
import os
import uuid
import sqlite3
import smtplib
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import Flask, request, jsonify, render_template, make_response
from icalendar import Calendar, Event
from flask_cors import CORS

# -------------------------------------------------
# Flask & Config
# -------------------------------------------------
app = Flask(__name__)
CORS(app, origins=["https://acop.edu.au"])
DB_FILE = "bookings.db"

# ----- Email (Mailtrap sandbox) -----
SMTP_SERVER = "sandbox.smtp.mailtrap.io"
SMTP_PORT = 2525
SMTP_USERNAME = "17d873b3a11a38"
SMTP_PASSWORD = "453b9c740a0729"
FROM_EMAIL = "enquiries@acop.edu.au"
ADMIN_EMAIL = "johnc@acop.edu.au"

# -------------------------------------------------
# In-memory session store (cookie-based)
# -------------------------------------------------
SESSIONS = {}
TIME_SLOTS = ["09:00", "11:00", "15:30"]

# -------------------------------------------------
# ---- DATABASE -------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            date TEXT,
            time TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_booking(name, email, date, time_slot):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO bookings (name, email, date, time)
        VALUES (?, ?, ?, ?)
    """, (name, email, date, time_slot))
    conn.commit()
    conn.close()

def is_time_booked(date, time_slot):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date = ? AND time = ?", (date, time_slot))
    exists = cur.fetchone() is not None
    conn.close()
    return exists

def get_booked_times(date):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT time FROM bookings WHERE date = ?", (date,))
    booked = [row[0] for row in cur.fetchall()]
    conn.close()
    return booked

# -------------------------------------------------
# ---- ICS CALENDAR ---------------------------------------------
def build_ics(name, date_str, time_str):
    event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    cal = Calendar()
    cal.add("prodid", "-//ACOP Booking//")
    cal.add("version", "2.0")
    event = Event()
    event.add("summary", "Assessment Call — ACOP")
    event.add("dtstart", event_dt)
    event.add("dtend", event_dt + timedelta(minutes=30))
    event.add("description", f"Assessment call for {name}")
    cal.add_component(event)
    return cal.to_ical()

# -------------------------------------------------
# ---- EMAIL ----------------------------------------------------
# ---- EMAIL ----------------------------------------------------
def send_email_with_ics(name, email, date, time_str):
    ics_data = build_ics(name, date, time_str)

    # ---- To student ----
    msg = EmailMessage()
    msg["Subject"] = "Your Assessment Booking — ACOP"
    msg["From"] = FROM_EMAIL
    msg["To"] = email
    msg.set_content(f"""
Hi {name},

Your assessment call has been booked.

Date: {date}
Time: {time_str}

An ICS file is attached – add it to your calendar.

If you need to reschedule, please contact us.

Kind regards,
ACOP Team
""")
    msg.add_attachment(
        ics_data,
        maintype="application",
        subtype="ics",
        filename="booking.ics"
    )

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(msg)

    # --- DELAY BEFORE ADMIN EMAIL (prevents 550 error) ---
    time.sleep(2)   # 2-second gap – safe for free Mailtrap plan

    # ---- Admin copy ----
    admin_msg = EmailMessage()
    admin_msg["Subject"] = "New Assessment Booking (Admin Copy)"
    admin_msg["From"] = FROM_EMAIL
    admin_msg["To"] = ADMIN_EMAIL
    admin_msg.set_content(f"""
New booking:

Name: {name}
Email: {email}
Date: {date}
Time: {time_str}
""")
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(admin_msg)

    return True
# -------------------------------------------------
# ---- HELPERS --------------------------------------------------
def next_available_dates():
    """Return up to 3 future weekdays with at least one free slot."""
    results = []
    today = datetime.now().date()
    for i in range(1, 31):
        day = today + timedelta(days=i)
        if day.weekday() >= 5:   # skip Sat/Sun
            continue
        date_str = day.strftime("%Y-%m-%d")
        booked = get_booked_times(date_str)
        if len(booked) < len(TIME_SLOTS):
            results.append(date_str)
        if len(results) == 3:
            break
    return results

# -------------------------------------------------
# ---- ROUTES ---------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/message", methods=["POST"])
@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>ACOP Booking Assistant</title>
  <style>
    /* [Paste the full CSS from my earlier HTML response here - the entire <style> block] */
  </style>
</head>
<body>
  <!-- [Paste the full body HTML from my earlier response here - button + popup + script] -->
</body>
</html>
"""
def api_message():
    user_input = request.json.get("message", "").strip()
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())

    # initialise session if new
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "stage": "name",
            "name": None,
            "email": None,
            "date": None,
            "time": None,
        }
    S = SESSIONS[session_id]

    reply = ""

    # ---------- STAGE: name ----------
    if S["stage"] == "name":
        S["name"] = user_input
        S["stage"] = "email"
        reply = f"Thanks, {S['name']}! What's your email address?"

    # ---------- STAGE: email ----------
    elif S["stage"] == "email":
        S["email"] = user_input
        S["stage"] = "date"
        reply = "Which day would you like to book? (e.g. 23/11/2025) – weekdays only."

    # ---------- STAGE: date ----------
    elif S["stage"] == "date":
        try:
            parsed = datetime.strptime(user_input, "%d/%m/%Y")
        except ValueError:
            reply = "Please use DD/MM/YYYY format."
        else:
            if parsed.weekday() >= 5:
                reply = "Weekends are not available. Choose a weekday."
            else:
                S["date"] = parsed.strftime("%Y-%m-%d")
                booked = get_booked_times(S["date"])
                free = [t for t in TIME_SLOTS if t not in booked]
                if not free:
                    alt = next_available_dates()
                    msg = "That day is fully booked.\n\n"
                    if alt:
                        msg += "Next available dates:\n" + "\n".join(alt) + "\n\n"
                    msg += "Please pick another date."
                    reply = msg
                else:
                    S["stage"] = "time"
                    reply = f"Great! Available times: {', '.join(free)}"

    # ---------- STAGE: time ----------
    elif S["stage"] == "time":
        # normalise input
        t = user_input.strip().upper()
        t = t.replace(" ", "").replace(".", ":").replace("AM", "").replace("PM", "")
        if ":" not in t:
            t += ":00"
        if len(t) == 4:
            t = "0" + t

        if t not in TIME_SLOTS:
            reply = f"Invalid time. Choose from: {', '.join(TIME_SLOTS)}"
        elif is_time_booked(S["date"], t):
            booked = get_booked_times(S["date"])
            free = [slot for slot in TIME_SLOTS if slot not in booked]
            if not free:
                alt = next_available_dates()
                msg = "That time is taken and the day is now full.\n\n"
                if alt:
                    msg += "Next available dates:\n" + "\n".join(alt) + "\n"
                msg += "Please choose a new date."
                S["stage"] = "date"
                reply = msg
            else:
                reply = f"That time is taken. Free slots: {', '.join(free)}"
        else:
            S["time"] = t
            save_booking(S["name"], S["email"], S["date"], S["time"])
            try:
                send_email_with_ics(S["name"], S["email"], S["date"], S["time"])
            except Exception as e:
                print("Email error:", e)
            reply = (f"Thank you {S['name']}! "
                     f"Your booking for **{S['date']} at {S['time']}** is confirmed. "
                     "Check your email for the calendar invite.")
            SESSIONS.pop(session_id, None)

    # ----- send response with cookie -----
    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("session_id", session_id, httponly=True, samesite="Lax")
    return resp

# -------------------------------------------------
# ---- CREATE index.html AUTOMATICALLY (first run) -----
def create_index_html():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ACOP Booking Bot</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0; background: #f8f9fa; }
  /* Chat Button */
  #chat-toggle {
    position: fixed;
    bottom: 20px;
    right: 20px;
    width: 60px;
    height: 60px;
    background: #007bff;
    color: white;
    border: none;
    border-radius: 50%;
    font-size: 28px;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.3s;
  }
  #chat-toggle:hover { background: #0056b3; transform: scale(1.05); }

  /* Chat Popup */
  #chat-popup {
    position: fixed;
    bottom: 90px;
    right: 20px;
    width: 380px;
    max-width: 90vw;
    height: 580px;
    background: white;
    border-radius: 16px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.15);
    z-index: 999;
    display: none;
    flex-direction: column;
    overflow: hidden;
    animation: fadeIn 0.3s ease;
  }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }

  #chat-header {
    background: #007bff;
    color: white;
    padding: 16px;
    font-weight: bold;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  #close-chat { background: none; border: none; color: white; font-size: 20px; cursor: pointer; }

  #chat-box {
    flex: 1;
    padding: 16px;
    overflow-y: auto;
    background: #f8f9fa;
  }
  .msg {
    margin: 10px 0;
    padding: 10px 14px;
    border-radius: 18px;
    max-width: 80%;
    word-wrap: break-word;
    line-height: 1.4;
  }
  .user {
    background: #007bff;
    color: white;
    margin-left: auto;
  }
  .bot {
    background: white;
    color: #333;
    border: 1px solid #e0e0e0;
  }
  .typing { font-style: italic; color: #666; }

  #chat-input {
    display: flex;
    border-top: 1px solid #eee;
    background: white;
  }
  #txt {
    flex: 1;
    padding: 14px;
    border: none;
    font-size: 15px;
    outline: none;
  }
  #send {
    padding: 0 18px;
    background: #007bff;
    color: white;
    border: none;
    font-weight: bold;
    cursor: pointer;
  }
  #send:hover { background: #0056b3; }

  @media (max-width: 480px) {
    #chat-popup { width: 95vw; height: 80vh; bottom: 80px; right: 10px; }
  }
</style>
</head>
<body>

<!-- Chat Toggle Button -->
<button id="chat-toggle">Chat</button>

<!-- Chat Popup -->
<div id="chat-popup">
  <div id="chat-header">
    <span>ACOP Booking Assistant</span>
    <button id="close-chat">×</button>
  </div>
  <div id="chat-box">
    <div class="msg bot">Hi! I'm here to help you book your assessment call. What's your name?</div>
  </div>
  <div id="chat-input">
    <input id="txt" placeholder="Type a message..." autocomplete="off">
    <button id="send">Send</button>
  </div>
</div>

<script>
  window.onload = function() {
    const toggle = document.getElementById('chat-toggle');
    const popup = document.getElementById('chat-popup');
    const close = document.getElementById('close-chat');
    const box = document.getElementById('chat-box');
    const txt = document.getElementById('txt');
    const send = document.getElementById('send');

    // Show/hide popup
    toggle.onclick = () => {
      popup.style.display = 'flex';
      setTimeout(() => txt.focus(), 100);
    };
    close.onclick = () => popup.style.display = 'none';

    // Add message
    function add(msg, type) {
      const div = document.createElement('div');
      div.className = 'msg ' + type;
      div.textContent = msg;
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
    }

    // Send message
    async function sendMsg() {
      const msg = txt.value.trim();
      if (!msg) return;
      add(msg, 'user');
      txt.value = '';

      const typing = document.createElement('div');
      typing.className = 'msg bot typing';
      typing.id = 'typing';
      typing.textContent = 'Typing...';
      box.appendChild(typing);

      try {
        const r = await fetch('/api/message', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg })
        });
        document.getElementById('typing')?.remove();
        if (r.ok) {
          const j = await r.json();
          add(j.reply, 'bot');
        } else {
          add('Sorry, something went wrong.', 'bot');
        }
      } catch (e) {
        document.getElementById('typing')?.remove();
        add('Connection error.', 'bot');
        console.error(e);
      }
    }

    send.onclick = sendMsg;
    txt.onkeydown = e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMsg();
      }
    };
  };
</script>
</body>
</html>"""
    os.makedirs("templates", exist_ok=True)
    with open("templates/index.html", "w", encoding="utf-8") as f:
        f.write(html)
# -------------------------------------------------
# ---- MAIN ----------------------------------------------------
if __name__ == "__main__":
    init_db()
    if not os.path.exists("templates/index.html"):
        create_index_html()
        print("Created templates/index.html")
    app.run(debug=True)

# Secure secret key for sessions
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me-in-prod')

# Production-ready run
if __name__ == "__main__":
    init_db()
    if not os.path.exists("templates/index.html"):
        create_index_html()
        print("Created templates/index.html")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)