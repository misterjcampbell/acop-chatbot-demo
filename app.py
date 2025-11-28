from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
import tempfile
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)

# Render-proof database in /tmp + auto-recreate
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

# === ADD THESE 3 ROUTES (fixes the 404 you're seeing right now) ===
@app.route('/api/message', methods=['POST'])
def api_message():
    data = request.get_json()
    user_message = data.get('message', '').strip().lower()
    if any(word in user_message for word in ['name', 'hi', 'hello', 'hey']):
        return jsonify({"response": "Hi! I'm here to help you book your assessment call. What's your name?"})
    return jsonify({"response": "Please tell me your name so we can get started!"})

# Your existing routes (unchanged)
@app.route('/')
def home():
    return render_template('index.html')

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
        return jsonify({'success': False, 'message': 'Slot taken, please choose another.'})

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO bookings (name, phone, date, time, timestamp) VALUES (?, ?, ?, ?, ?)",
              (name, phone, date, time, timestamp))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Booking confirmed!'})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)