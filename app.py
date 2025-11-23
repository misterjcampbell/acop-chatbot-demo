# ================================================
# app.py – ACOP Assessment Booking Chatbot – FINAL WORKING VERSION
# Live URL: https://acop-chatbot-demo-vxow.onrender.com
# ================================================
import os
import uuid
import sqlite3
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import Flask, request, jsonify, make_response
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event

app = Flask(__name__)
DB_FILE = "bookings.db"
SYDNEY_TZ = ZoneInfo("Australia/Sydney")
TIME_SLOTS = ["09:00", "11:00", "15:30"]

# Mailtrap sandbox
SMTP_SERVER = "sandbox.smtp.mailtrap.io"
SMTP_PORT = 2525
SMTP_USERNAME = "17d873b3a11a38"
SMTP_PASSWORD = "453b9c740a0729"
FROM_EMAIL = "enquiries@acop.edu.au"
ADMIN_EMAIL = "johnc@acop.edu.au"

SESSIONS = {}

# ================================================
# DB
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
# AVAILABILITY
# ================================================
def get_available_slots_for_date(date_str):
    target = datetime.strptime(date_str, "Y%-m-%d").date()
    now = datetime.now(SYDNEY_TZ)
    today = now.strftime("Y%-m-%d")
    booked = get_booked_times(date_str)
    available = []
    for slot in TIME_SLOTS:
        if slot in booked: continue
        if date_str == today:
            slot_dt = datetime.strptime(f"{date_str} {slot}", "Y%-m-%d H%:M%")
            slot_dt = slot_dt.replace(tzinfo=SYDNEY_TZ)
            if slot_dt <= now: continue
        available.append(slot)
    return available

# ================================================
# EMAIL + ICS
# ================================================
def send_email_with_ics(name, email, date, time_str):
    event_dt = datetime.strptime(f"{date} {time_str}", "Y%-m-%d H%:M%").replace(tzinfo=SYDNEY_TZ)
    cal = Calendar(); cal.add('prodid', '-//ACOP//'); cal.add('version', '2.0')
    e = Event(); e.add('summary', 'ACOP Assessment Call')
    e.add('dtstart', event_dt); e.add('dtend', event_dt + timedelta(minutes=60))
    e.add('description', f"Assessment call with {name}")
    cal.add_component(e)
    ics = cal.to_ical()

    pretty_date = datetime.strptime(date, "Y%-m-%d").strftime("%A %d %B %Y")
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><style>
        body{{font-family:'Segoe UI',sans-serif;background:#f2f2f2;color:#2d3748;margin:0}}
        .c{{max-width:600px;margin:20px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 8px 25px rgba(0,0,0,.1)}}
        .h{{background:#004cbf;color:#fff;padding:30px;text-align:center}}
        .h img{{height:50px;margin-bottom:10px}}
        .b{{padding:30px;line-height:1.7}}
        .d{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:20px;margin:20px 0}}
        .btn{{background:#0098ea;color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block}}
        .f{{background:#004cbf;color:#fff;padding:20px;text-align:center;font-size:13px}}
    </style></head><body>
        <div class="c"><div class="h"><img src="https://mailsend-email-assets.mailtrap.io/b3ggvuuwep32geyb8s8dwn7qzh6o.png"><h1>Assessment Call Confirmed</h1></div>
        <div class="b"><p>Hi <strong>{name}</strong>,</p><p>Your assessment call is booked!</p>
        <div class="d"><p><strong>Date:</strong> {pretty_date}</p><p><strong>Time:</strong> {time_str}</p><p><strong>Duration:</strong> 60 minutes</p></div>
        <p style="text-align:center"><a href="#" class="btn">Add to Calendar</a></p>
        <p>Need to reschedule? Reply or call <strong>1300 123 456</strong>.</p><p>— The ACOP Team</p></div>
        <div class="f"><p>Australian College of Professionals | <a href="https://acop.edu.au" style="color:#fff">acop.edu.au</a></p></div></div>
    </body></html>"""

    msg = EmailMessage()
    msg["Subject"] = "Your ACOP Assessment Call – Confirmed"
    msg["From"] = FROM_EMAIL
    msg["To"] = email
    msg.set_content("Booking confirmed")
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(ics, maintype="application", subtype="ics", filename="ACOP-Assessment.ics")
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
        s.login(SMTP_USERNAME, SMTP_PASSWORD)
        s.send_message(msg)

# ================================================
# FRONTEND + CHAT (FIXED & BEAUTIFUL)
# ================================================
@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ACOP Assessment Booking</title>
<style>
body{margin:0;font-family:'Segoe UI',sans-serif;background:#f5f7fa;color:#333}
.hero{background:linear-gradient(135deg,#004cbf,#007bff);color:#fff;text-align:center;padding:80px 20px}
.hero h1{font-size:2.8rem;margin:0 0 20px;font-weight:700}
.hero p{font-size:1.3rem;margin:0 0 30px;opacity:0.95}
.btn{background:#fff;color:#004cbf;padding:16px 40px;border:none;border-radius:50px;font-size:1.2rem;font-weight:600;cursor:pointer;box-shadow:0 8px 20px rgba(0,0,0,.2);transition:.3s}
.btn:hover{background:#f0f0f0;transform:translateY(-3px)}
#chat-toggle{position:fixed;bottom:20px;right:20px;width:66px;height:66px;background:#004cbf;color:#fff;border:none;border-radius:50%;font-size:28px;cursor:pointer;box-shadow:0 8px 25px rgba(0,76,191,.4);z-index:1000;display:flex;align-items:center;justify-content:center}
#chat-toggle:hover{transform:scale(1.1)}
#chat-popup{position:fixed;bottom:96px;right:20px;width:380px;max-width:92vw;height:620px;background:#fff;border-radius:20px;box-shadow:0 15px 40px rgba(0,0,0,.2);z-index:999;display:none;flex-direction:column;overflow:hidden}
#chat-header{background:#004cbf;color:#fff;padding:18px;font-weight:600;display:flex;justify-content:space-between;align-items:center}
#close-chat{background:none;border:none;color:#fff;font-size:28px;cursor:pointer}
#chat-box{flex:1;padding:20px;overflow-y:auto;background:#f9f9f9}
.msg{margin:12px 0;padding:12px 18px;border-radius:20px;max-width:82%;word-wrap:break-word;line-height:1.5;font-size:15px}
.bot{background:#fff;color:#333;border:1px solid #eee}
.user{background:#004cbf;color:#fff;margin-left:auto}
#chat-input{display:flex;border-top:1px solid #ddd;background:#fff}
#txt{flex:1;padding:16px;border:none;font-size:15px;outline:none}
#send{padding:0 24px;background:#004cbf;color:#fff;border:none;font-weight:600;cursor:pointer}
@media(max-width:480px){#chat-popup{width:95vw;height:80vh;bottom:80px;left:50%;transform:translateX(-50%)}}
</style>
</head>
<body>
<div class="hero">
  <h1>Book Your Free Assessment Call</h1>
  <p>Get personalised advice from the ACOP team – 100% free</p>
  <button class="btn" onclick="document.getElementById('chat-toggle').click()">Start Chat Now</button>
</div>

<button id="chat-toggle">Chat</button>
<div id="chat-popup">
  <div id="chat-header"><span>ACOP Assistant</span><button id="close-chat">×</button></div>
  <div id="chat-box"><div class="msg bot">Hi! I'm here to book your free 60-minute assessment call. What's your name?</div></div>
  <div id="chat-input"><input id="txt" placeholder="Type a message..." autocomplete="off"><button id="send">Send</button></div>
</div>

<script>
document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('chat-toggle');
  const popup = document.getElementById('chat-popup');
  const close = document.getElementById('close-chat');
  const box = document.getElementById('chat-box');
  const input = document.getElementById('txt');
  const send = document.getElementById('send');

  toggle.onclick = () => { popup.style.display = 'flex'; setTimeout(() => input.focus(), 200); };
  close.onclick = () => popup.style.display = 'none';

  function add(msg, type) {
    const div = document.createElement('div');
    div.className = 'msg ' + type;
    div.textContent = msg;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  async function sendMsg() {
    const text = input.value.trim();
    if (!text) return;
    add(text, 'user'); input.value = '';
    const typing = document.createElement('div'); typing.className = 'msg bot'; typing.textContent = 'Typing...'; box.appendChild(typing);

    try {
      const r = await fetch('/api/message', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});
      typing.remove();
      if (r.ok) { const j = await r.json(); add(j.reply, 'bot'); }
      else add('Sorry, something went wrong.', 'bot');
    } catch { typing.remove(); add('Network error.', 'bot'); }
  }

  send.onclick = sendMsg;
  input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); sendMsg(); }};
});
</script>
</body>
</html>
"""

# ================================================
# CHAT LOGIC
# ================================================
@app.route("/api/message", methods=["POST"])
def api_message():
    user_input = request.json.get("message", "").strip()
    sid = request.cookies.get("session_id") or str(uuid.uuid4())
    if sid not in SESSIONS:
        SESSIONS[sid] = {"stage":"name","name":None,"email":None,"date":None,"time":None,"awaiting_alt":False}
    S = SESSIONS[sid]
    reply = ""

    if S["stage"] == "name":
        S["name"] = user_input.title()
        S["stage"] = "email"
        reply = f"Thanks {S['name']}! What's your email?"

    elif S["stage"] == "email":
        S["email"] = user_input.lower()
        S["stage"] = "date"
        reply = "Which date would you like? (e.g. 24/11/2025) – weekdays only"

    elif S["stage"] == "date":
        try:
            d = datetime.strptime(user_input, "%d/%m/%Y")
            if d.weekday() >= 5:
                reply = "Sorry, we only take bookings Monday–Friday. Please pick a weekday."
            else:
                ds = d.strftime("Y%-m-%d")
                avail = get_available_slots_for_date(ds)
                if not avail:
                    reply = f"Sorry, {d.strftime('%A %d %B')} is fully booked or times have passed.\n\nPlease choose another date."
                else:
                    S["date"] = ds
                    S["stage"] = "time"
                    reply = f"Great! Available times on {d.strftime('%A %d %B')}:\n" + ", ".join(avail)
        except:
            reply = "Please use DD/MM/YYYY format (e.g. 24/11/2025)"

 elif S["stage"] == "time":
        t = user_input.strip().upper().replace(" ", "").replace(".", ":").replace("AM","").replace("PM","")
	if ":" not in t: t += ":00"
        if len(t)==4: t = "0"+t

        if t not in TIME_SLOTS:
            reply = f"Please choose from: {', '.join(TIME_SLOTS)}"
        else:
            avail = get_available_slots_for_date(S["date"])
            if t not in avail:
                remain = [s for s in avail if s != t]
                if remain:
                    S["awaiting_alt"] = True
                    reply = f"Sorry, {t} is taken.\n\nAnother time on the same day ({', '.join(remain)}) or a different date?"
                else:
                    reply = "That day is now full. Please pick another date."
                    S["stage"] = "date"
            else:
                S["time"] = t
                save_booking(S["name"], S["email"], S["date"], t)
                send_email_with_ics(S["name"], S["email"], S["date"], t)
                pretty = datetime.strptime(S["date"], "Y%-m-%d").strftime("%A %d %B %Y")
                reply = f"Confirmed! {S['name']}, your 60-minute call is booked for {pretty} at {t} (Sydney time).\n\nCheck your email for the calendar invite!"
                SESSIONS.pop(sid, None)

    elif S.get("awaiting_alt"):
        if any(x in user_input.lower() for x in ["another","same day","yes","other time"]):
            remain = get_available_slots_for_date(S["date"])
            reply = f"Available times: {', '.join(remain)}" if remain else "That day is now full. Please pick another date."
            S["stage"] = "time" if remain else "date"
        else:
            reply = "No problem, please choose a different date."
            S["stage"] = "date"
        S["awaiting_alt"] = False

    resp = make_response(jsonify({"reply": reply}))
    resp.set_cookie("session_id", sid, httponly=True, samesite="Lax")
    return resp

# ================================================
# RUN
  # ================================================
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)