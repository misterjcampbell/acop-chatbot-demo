# app.py – FINAL WORKING VERSION (Render free tier + correct chatbot responses)
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
import tempfile
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Render-proof database
DB_PATH = os.path.join(tempfile.gettempdir(), "bookings.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = get_db()
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

# ================ CHATBOT ENDPOINT (this is what was missing) ================
@app.route('/api/message', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    
    # Simple conversation flow
    if "name" in user_message.lower() or not data.get("context"):
        # First message or asking for name
        return jsonify({
            "messages": [{"text": "Hi! I'm here to help you book your assessment call. What's your name?"}]
        })
    
    context = data.get("context", {})
    if not context.get("name"):
        # Capture name
        return jsonify({
            "messages": [{"text": f"Nice to meet you, {user_message}! What's your phone number?"}],
            "context": {"name": user_message}
        })
    
    if not context.get("phone"):
        # Capture phone
        return jsonify({
            "messages": [{"text": "Perfect! Now please choose a date and time for your assessment call."}],
            "context": {**context, "phone": user_message}
        })

    # Everything collected → let the frontend handle booking
    return jsonify({
        "messages": [{"text": "Great! Please select your preferred date and time from the calendar."}],
        "context": context
    })

# Your existing booking endpoints
@app.route('/check', methods=['POST'])
def check():
    data = request.get_json()
    date = data.get('date')
    time = data.get('time')
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
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

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM bookings WHERE date=? AND time=?", (date, time))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'That slot is no longer available. Please choose another.'})

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO bookings (name, phone, date, time, timestamp) VALUES (?, ?, ?, ?, ?)",
              (name, phone, date, time, timestamp))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message': f"Perfect, {name}! Your assessment call is booked for {date} at {time}. We'll send you a confirmation shortly."
    })

@app.route('/')
def home():
    return render_template('index.html')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)