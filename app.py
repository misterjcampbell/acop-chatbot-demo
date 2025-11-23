# ================================================
# app.py – ACOP Assessment Booking Chatbot (FINAL)
# Live at: https://acop-chatbot-demo-vxow.onrender.com
# ================================================
import os
import uuid
import sqlite3
import smtplib
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import Flask, request, jsonify, make_response
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event

app = Flask(__name__)
DB_FILE = "bookings.db"

# Sydney timezone
SYDNEY_TZ = ZoneInfo("Australia/Sydney")
TIME_SLOTS = ["09:00", "11:00", "15:30"]

# Mailtrap (sandbox)
SMTP_SERVER = "sandbox.smtp.mailtrap.io"
SMTP_PORT = 2525
SMTP_USERNAME = "17d873b3a11a38"
SMTP_PASSWORD = "453b9c740a0729"
FROM_EMAIL = "enquiries@acop.edu.au"
ADMIN_EMAIL = "johnc@acop.edu.au"

# In-memory sessions
SESSIONS = {}

# ================================================
# DATABASE
# ================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, email TEXT, date TEXT, time TEXT
    )""")
    conn.commit()
    conn.close()

def save_booking(name, email, date, time):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO bookings (name,email,date,time) VALUES (?,?,?,?)",
                (name, email, date, time))
    conn.commit()
    conn.close()

def get_booked_times(date_str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT time FROM bookings WHERE date=?", (date_str,))
    booked = [row[0] for row in cur.fetchall()]
    conn.close()
    return booked

# ================================================
# SMART AVAILABILITY (Sydney time + same-day cutoff)
# ================================================
def get_available_slots_for_date(date_str):
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    now_sydney = datetime.now(SYDNEY_TZ)
    today_str = now_sydney.strftime("%Y-%m-%d")

    booked = get_booked_times(date_str)
    available = []

    for slot in TIME_SLOTS:
        if slot in booked:
            continue
        # Same-day cutoff
        if date_str == today_str:
            slot_dt = datetime.strptime(f"{date_str} {slot}", "%Y-%m-%d %H:%M")
            slot_dt = slot_dt.replace(tzinfo=SYDNEY_TZ)
            if slot_dt <= now_sydney:
                continue
        available.append(slot)
    return available

# ================================================
# ICS + EMAIL (with your branded template)
# ================================================
def build_ics(name, date_str, time_str):
    event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    event_dt = event_dt.replace(tzinfo=SYDNEY_TZ)
    cal = Calendar()
    cal.add('prodid', '-//ACOP Booking//')
    cal.add('version', '2.0')
    event = Event()
    event.add('summary', 'ACOP Assessment Call')
    event.add('dtstart', event_dt)
    event.add('dtend', event_dt + timedelta(minutes=60))  # Your change to 60 min
    event.add('description', f"Assessment call with {name}")
    cal.add_component(event)
    return cal.to_ical()

def send_email_with_ics(name, email, date, time_str):
    ics_data = build_ics(name, date, time_str)

    # Your branded HTML template
    html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>ACOP Assessment Booking</title>
  <style>
    body {
      margin: 0;
      padding: 0;
      background: #f2f2f2;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      color: #2d3748;
    }
    .container {
      max-width: 600px;
      margin: 20px auto;
      background: #ffffff;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
    }
    .header {
      background: #004cbf; /* ACOP Navy */
      color: white;
      padding: 30px 20px;
      text-align: center;
    }
    .header img {
      height: 50px;
      margin-bottom: 10px;
    }
    .header h1 {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
    }
    .content {
      padding: 30px;
      line-height: 1.7;
    }
    .booking-details {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 20px;
      margin: 20px 0;
      font-size: 16px;
    }
    .booking-details strong {
      color: #1a365d;
    }
    .btn {
      display: inline-block;
      background: #0098ea;
      color: white !important;
      padding: 14px 28px;
      text-decoration: none;
      border-radius: 8px;
      font-weight: 600;
      margin: 20px 0;
      font-size: 16px;
    }
    .btn:hover {
      background: #004cbf;
    }
    .footer {
      background: #004cbf;
      color: #ffffff;
      padding: 20px;
      text-align: center;
      font-size: 13px;
    }
    .footer a {
      color: #ffffff;
      text-decoration: none;
    }
    @media (max-width: 480px) {
      .container { margin: 10px; border-radius: 8px; }
      .header, .content { padding: 20px; }
    }
  </style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <img src="https://mailsend-email-assets.mailtrap.io/b3ggvuuwep32geyb8s8dwn7qzh6o.png" alt="ACOP Logo" />
      <h1>Assessment Call Confirmed</h1>
    </div>

    <!-- Content -->
    <div class="content">
      <p>Hi <strong>{name}</strong>,</p>
      <p>Great news! Your <strong>assessment call</strong> with ACOP has been successfully booked.</p>

      <div class="booking-details">
        <p><strong>Date:</strong> {date}</p>
        <p><strong>Time:</strong> {time_str}</p>
        <p><strong>Duration:</strong> 60 minutes</p>
      </div>

      <p>An <strong>ICS calendar file</strong> is attached below — just click to add it to your Google Calendar, Outlook, or Apple Calendar.</p>

      <p style="text-align: center;">
        <a href="#" class="btn">Add to Calendar</a>
      </p>

      <p><strong>Need to reschedule?</strong><br>
      Reply to this email or call us at <strong>1300 123 456</strong>.</p>

      <p>We look forward to speaking with you!</p>
      <p><em>— The ACOP Team</em></p>
    </div>

    <!-- Footer -->
    <div class="footer">
      <p>Australian College of Professionals | <a href="https://acop.edu.au">acop.edu.au</a></p>
      <p>Level 2, 464 Kent Street, Sydney NSW 2000 | enquiries@acop.edu.au</p>
      <p>&copy; 2025 ACOP. All rights reserved.</p>
    </div>
  </div>
</body>
</html>
    """.format(name=name, date=datetime.strptime(date, "%Y-%m-%d").strftime("%A %d %B %Y"), time_str=time_str)

    # Send to Student
    msg = EmailMessage()
    msg["Subject"] = "Your Assessment Booking — ACOP"
    msg["From"] = FROM_EMAIL
    msg["To"] = email
    msg.set_content("Your assessment call has been booked. Check the HTML version for details.")
    msg.add_alternative(html_template, subtype='html')
    msg.add_attachment(ics_data, maintype="application", subtype="ics", filename="booking.ics")

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(msg)

    time.sleep(2)

    # Admin copy (plain text)
    admin_msg = EmailMessage()
    admin_msg["Subject"] = "New Assessment Booking (Admin Copy)"
    admin_msg["From"] = FROM_EMAIL
    admin_msg["To"] = ADMIN_EMAIL
    admin_msg.set_content(f"""
New booking received:
Name: {name}
Email: {email}
Date: {date}
Time: {time_str}
    """)
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(admin_msg)

    return True, None

# ================================================
# MAIN CHAT ROUTE (THIS WAS MISSING!)
# ================================================
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
    /* Reset & Base */
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background: #f5f7fa;
      color: #333;
      height: 100vh;
    }

    /* Chat Toggle Button */
    #chat-toggle {
      position: fixed;
      bottom: 20px;
      right: 20px;
      width: 62px;
      height: 62px;
      background: #007bff;
      color: white;
      border: none;
      border-radius: 50%;
      font-size: 26px;
      font-weight: bold;
      cursor: pointer;
      box-shadow: 0 6px 16px rgba(0,123,255,0.3);
      z-index: 1000;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.3s ease;
    }
    #chat-toggle:hover {
      background: #0056b3;
      transform: translateY(-3px);
      box-shadow: 0 8px 20px rgba(0,123,255,0.4);
    }

    /* Chat Popup */
    #chat-popup {
      position: fixed;
      bottom: 92px;
      right: 20px;
      width: 380px;
      max-width: 92vw;
      height: 580px;
      background: white;
      border-radius: 18px;
      box-shadow: 0 12px 40px rgba(0,0,0,0.15);
      z-index: 999;
      display: none;
      flex-direction: column;
      overflow: hidden;
      animation: popIn 0.35s ease-out;
    }
    @keyframes popIn {
      from { opacity: 0; transform: scale(0.9) translateY(20px); }
      to { opacity: 1; transform: scale(1) translateY(0); }
    }

    /* Header */
    #chat-header {
      background: #007bff;
      color: white;
      padding: 16px 18px;
      font-weight: 600;
      font-size: 17px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    #close-chat {
      background: none;
      border: none;
      color: white;
      font-size: 24px;
      cursor: pointer;
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
      transition: background 0.2s;
    }
    #close-chat:hover { background: rgba(255,255,255,0.2); }

    /* Chat Box */
    #chat-box {
      flex: 1;
      padding: 18px;
      overflow-y: auto;
      background: #f8f9fa;
    }
    .msg {
      margin: 12px 0;
      padding: 11px 16px;
      border-radius: 20px;
      max-width: 80%;
      word-wrap: break-word;
      line-height: 1.5;
      font-size: 15px;
    }
    .bot {
      background: white;
      color: #2c3e50;
      border: 1px solid #e2e8f0;
      align-self: flex-start;
    }
    .user {
      background: #007bff;
      color: white;
      margin-left: auto;
      align-self: flex-end;
    }
    .typing {
      font-style: italic;
      color: #718096;
      font-size: 14px;
    }

    /* Input Area */
    #chat-input {
      display: flex;
      border-top: 1px solid #e2e8f0;
      background: white;
    }
    #txt {
      flex: 1;
      padding: 16px;
      border: none;
      font-size: 15px;
      outline: none;
      resize: none;
    }
    #send {
      padding: 0 22px;
      background: #007bff;
      color: white;
      border: none;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
    }
    #send:hover { background: #0056b3; }

    /* Mobile */
    @media (max-width: 480px) {
      #chat-popup {
        width: 95vw;
        height: 78vh;
        bottom: 80px;
        right: 10px;
        left: 10px;
        margin: 0 auto;
      }
      #chat-toggle { bottom: 15px; right: 15px; }
    }
  </style>
</head>
<body>

  <!-- Floating Chat Button -->
  <button id="chat-toggle">Chat</button>

  <!-- Chat Popup Window -->
  <div id="chat-popup">
    <div id="chat-header">
      <span>ACOP Booking Assistant</span>
      <button id="close-chat">×</button>
    </div>

    <div id="chat-box">
      <div class="msg bot">Hi! I'm here to help you book your assessment call. What's your name?</div>
    </div>

    <div id="chat-input">
      <input id="txt" type="text" placeholder="Type your message..." autocomplete="off" />
      <button id="send">Send</button>
    </div>
  </div>

  <script>
    document.addEventListener('DOMContentLoaded', () => {
      const toggle = document.getElementById('chat-toggle');
      const popup = document.getElementById('chat-popup');
      const close = document.getElementById('close-chat');
      const box = document.getElementById('chat-box');
      const input = document.getElementById('txt');
      const send = document.getElementById('send');

      toggle.addEventListener('click', () => {
        popup.style.display = 'flex';
        setTimeout(() => input.focus(), 150);
      });
      close.addEventListener('click', () => {
        popup.style.display = 'none';
      });

      function addMessage(text, sender) {
        const msg = document.createElement('div');
        msg.className = `msg ${sender}`;
        msg.textContent = text;
        box.appendChild(msg);
        box.scrollTop = box.scrollHeight;
      }

      async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;

        addMessage(text, 'user');
        input.value = '';

        const typing = document.createElement('div');
        typing.className = 'msg bot typing';
        typing.id = 'typing';
        typing.textContent = 'Typing...';
        box.appendChild(typing);

        try {
          const res = await fetch('/api/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
          });

          document.getElementById('typing')?.remove();

          if (res.ok) {
            const data = await res.json();
            addMessage(data.reply, 'bot');
          } else {
            addMessage('Sorry, something went wrong. Please try again.', 'bot');
          }
        } catch (err) {
          document.getElementById('typing')?.remove();
          addMessage('Connection failed. Check your internet.', 'bot');
          console.error('Chat error:', err);
        }
      }

      send.addEventListener('click', sendMessage);
      input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          sendMessage();
        }
      });
    });
  </script>
</body>
</html>
"""

@app.route("/api/message", methods=["POST"])
def api_message():
    user_input = request.json.get("message", "").strip()
    session_id = request.cookies.get("session_id") or str(uuid.uuid4())
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"stage":"name","name":None,"email":None,"date":None,"time":None,"awaiting_alt":False}
    S = SESSIONS[session_id]
    reply = ""

    if S["stage"] == "name":
        S["name"] = user_input.title()
        S["stage"] = "email"
        reply = f"Thanks {S['name']}! What's your email address?"

    elif S["stage"] == "email":
        S["email"] = user_input.lower()
        S["stage"] = "date"
        reply = "Which date would you like? (e.g. 24/11/2025) – weekdays only"

    elif S["stage"] == "date":
        try:
            d = datetime.strptime(user_input, "%d/%m/%Y")
            if d.weekday() >= 5:
                reply = "We only accept bookings Monday–Friday. Please choose a weekday."
            else:
                date_str = d.strftime("%Y-%m-%d")
                available = get_available_slots_for_date(date_str)
                if not available:
                    reply = f"Sorry, {d.strftime('%A %d %B')} is fully booked or all times have passed.\n\nPlease pick another date."
                else:
                    S["date"] = date_str
                    S["stage"] = "time"
                    reply = f"Perfect! Available times on {d.strftime('%A %d %B')}:\n" + ", ".join(available)
        except ValueError:
            reply = "Please use DD/MM/YYYY format (e.g. 24/11/2025)"

    elif S["stage"] == "time":
        t = user_input.strip().upper().replace(" ","").replace(".":":").replace("AM","").replace("PM","")
        if ":" not in t: t += ":00"
        if len(t) == 4: t = "0" + t

        if t not in TIME_SLOTS:
            reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
        else:
            available = get_available_slots_for_date(S["date"])
            if t not in available:
                remaining = [s for s in available if s != t]
                if remaining:
                    S["awaiting_alt"] = True
                    reply = f"Sorry, {t} is no longer available.\n\nWould you like another time on the same day ({', '.join(remaining)}) or a different date?"
                else:
                    reply = "That day is now fully booked. Please choose another date."
                    S["stage"] = "date"
            else:
                S["time"] = t
                save_booking(S["name"], S["email"], S["date"], t)
                try:
                    send_email_with_ics(S["name"], S["email"], S["date"], t)
                except Exception as e:
                    print("Email error:", e)
                pretty = datetime.strptime(S["date"], "%Y-%m-%d").strftime("%A %d %B %Y")
                reply = f"All done! {S['name']}, your call is confirmed for {pretty} at {t} (Sydney time).\n\nCheck your email for the calendar invite!"
                SESSIONS.pop(session_id, None)

    elif S.get("awaiting_alt"):
        if any(x in user_input.lower() for x in ["another", "same day", "yes", "other time"]):
            remaining = get_available_slots_for_date(S["date"])
            if remaining:
                reply = f"No problem! Available times on that day: {', '.join(remaining)}"
                S["stage"] = "time"
            else:
                reply = "Actually that day is now full. Please pick a new date."
                S["stage"] = "date"
        else:
            reply = "Okay, please choose a different date."
            S["stage"] = "date"
        S["awaiting_alt"] = False

    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("session_id", session_id, httponly=True, samesite="Lax")
    return resp

# ================================================
# RUN
# ================================================
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key")
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)