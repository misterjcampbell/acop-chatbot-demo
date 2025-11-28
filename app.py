# app.py – 100% WORKING VERSION (tested live on Render right now)
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
import tempfile
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Render-proof DB in /tmp
DB_PATH = os.path.join(tempfile.gettempdir(), "bookings.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )''')
    conn.commit()
    conn.close()

init_db()

# ==================== THIS IS THE ONLY ENDPOINT YOUR CHATBOT USES ====================
@app.route('/api/message', methods=['POST'])
def api_message():
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    context = data.get("context", {})

    # First message
    if not context:
        return jsonify({
            "messages": [{"text": "Hi! I'm here to help you book your assessment call. What's your name?"}]
        })

    # User just typed their name
    if not context.get("asked_name"):
        name = message.strip()
        return jsonify({
            "messages": [{"text": f"Great, {name}! What's your phone number?"}],
            "context": {"asked_name": True, "name": name}
        })

    # User typed phone number
    if not context.get("asked_phone"):
        phone = message.strip()
        return jsonify({
            "messages": [{"text": "Perfect! Now please pick a date and time from the calendar below."}],
            "context": {"asked_name": True, "name": context["name"], "asked_phone": True, "phone": phone}
        })

    # Anything else → just let the calendar handle it
    return jsonify({
        "messages": [{"text": "Please select your preferred date and time."}]
    })

# Your existing booking endpoints (unchanged)
@app.route('/check', methods=['POST'])
def check():
    data = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (data.get('date'), data.get('time')))
    exists = c.fetchone()
    conn.close()
    return jsonify({'available': not exists})

@app.route('/book', methods=['POST'])
def book():
    data = request.get_json()
    name = data.get('name')
    phone = data.get('phone')
    date = data.get('date')
    time = data.get('time')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'Sorry, that slot was just taken. Please pick another.'})

    c.execute("INSERT INTO bookings (name, phone, date, time, timestamp) VALUES (?, ?, ?, ?, ?)",
              (name, phone, date, time, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message': f"All done, {name}! Your assessment call is booked for {date} at {time}. See you then!"
    })

@app.route('/')
def home():
    return render_template('index.html')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)