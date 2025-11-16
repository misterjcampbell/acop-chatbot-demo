from flask import Flask, request, jsonify, render_template
from email.message import EmailMessage
from datetime import datetime, timedelta
import smtplib, os, json, dateparser, traceback
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# Config (via .env)
MAIL_HOST = os.getenv('MAILTRAP_HOST', 'sandbox.smtp.mailtrap.io')
MAIL_PORT = int(os.getenv('MAILTRAP_PORT', 2525))
MAIL_USER = os.getenv('MAILTRAP_USER', '17d873b3a11a38')
MAIL_PASS = os.getenv('MAILTRAP_PASS', '17d873b3a11a38')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'johnc@acop.edu.au')

BOT_NAME = 'Engagement Assessment'
COLLEGE_PHONE = '1300-88-48-10'

# Slots and storage
ALLOWED_SLOTS = ['09:00', '11:00', '15:30']
BOOKINGS_FILE = os.path.join(os.path.dirname(__file__), 'bookings.json')

# Ensure bookings file exists
if not os.path.exists(BOOKINGS_FILE):
    with open(BOOKINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f, indent=2)

def load_bookings():
    with open(BOOKINGS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_bookings(bookings):
    with open(BOOKINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(bookings, f, indent=2)

def normalize_date(user_text):
    # Use dateparser to convert flexible date input into ISO date (YYYY-MM-DD).
    settings = {
        'PREFER_DATES_FROM': 'future',
        'RELATIVE_BASE': datetime.now()
    }
    dt = dateparser.parse(user_text, settings=settings)
    if not dt:
        return None
    return dt.date().isoformat()

def parse_date_allow_variants(user_text):
    try:
        try:
            d = datetime.fromisoformat(user_text)
            return d.date().isoformat()
        except Exception:
            pass
        parsed = dateparser.parse(user_text, settings={'PREFER_DATES_FROM':'future'})
        if not parsed:
            return None
        return parsed.date().isoformat()
    except Exception:
        return None

def is_weekday_iso(iso_date):
    d = datetime.fromisoformat(iso_date)
    return d.weekday() < 5

def slot_available(date_iso, time_str):
    bookings = load_bookings()
    for b in bookings:
        if b['date'] == date_iso and b['time'] == time_str:
            return False
    return True

def create_ics(student_name, student_email, date_iso, time_str):
    start = datetime.fromisoformat(f"{date_iso}T{time_str}")
    end = start + timedelta(minutes=30)
    dtstamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    ics = '\r\n'.join([
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Engagement Assessment//Chatbot Booking//EN',
        'BEGIN:VEVENT',
        f'UID:{student_email}-{date_iso}-{time_str}',
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:Assessment Call - {student_name}",
        f"DESCRIPTION:Assessment call booked via {BOT_NAME}\nPhone: {COLLEGE_PHONE}",
        'END:VEVENT',
        'END:VCALENDAR',
        ''
    ])
    return ics

def send_mail(student_name, student_email, date_iso, time_str):
    subject = f"Assessment Call Confirmation - {date_iso} {time_str}"
    body = f"""Hello {student_name},

Your assessment call is confirmed for {date_iso} at {time_str}.

If you need to reschedule, please call the College on {COLLEGE_PHONE}.

Regards,
{BOT_NAME}
"""
    try:
        msg = EmailMessage()
        msg['From'] = MAIL_USER if MAIL_USER else ADMIN_EMAIL
        msg['To'] = student_email
        msg['Subject'] = subject
        msg.set_content(body)
        ics = create_ics(student_name, student_email, date_iso, time_str)
        msg.add_attachment(ics.encode('utf-8'), maintype='text', subtype='calendar', filename='booking.ics')

        with smtplib.SMTP(MAIL_HOST, MAIL_PORT, timeout=15) as smtp:
            smtp.login(MAIL_USER, MAIL_PASS)
            smtp.send_message(msg)
        print('Email sent to', student_email)
        return True, None
    except Exception as e:
        tb = traceback.format_exc()
        print('Email sending failed:', e, tb)
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html', bot_name=BOT_NAME, phone=COLLEGE_PHONE, slots=ALLOWED_SLOTS)

@app.route('/api/book', methods=['POST'])
def api_book():
    try:
        payload = request.get_json(force=True)
        name = payload.get('name', '').strip()
        email = payload.get('email', '').strip()
        date_input = payload.get('date', '').strip()
        time_choice = payload.get('time', '').strip()

        if not (name and email and date_input and time_choice):
            return jsonify({'status':'error','message':'Please provide name, email, date and time.'}), 400

        date_iso = parse_date_allow_variants(date_input)
        if not date_iso:
            return jsonify({'status':'error','message':'Couldn\'t understand that date. Try \"14 Nov\", \"next Tue\", or \"2025-11-14\".'}), 400

        if not is_weekday_iso(date_iso):
            return jsonify({'status':'error','message':'Bookings are only available Monday to Friday. Please choose another date.'}), 400

        if time_choice.lower() == 'call':
            return jsonify({'status':'call','message':f'Please call the College on {COLLEGE_PHONE} to arrange another time.'})

        if time_choice not in ALLOWED_SLOTS:
            return jsonify({'status':'error','message':'Invalid time slot. Choose one of the displayed slots.'}), 400

        dt_choice = datetime.fromisoformat(f"{date_iso}T{time_choice}")
        if dt_choice < datetime.now():
            return jsonify({'status':'error','message':'That time has already passed. Please choose a future slot.'}), 400

        if not slot_available(date_iso, time_choice):
            return jsonify({'status':'full','message':'Sorry, that slot is already booked. Please call the College.'}), 409

        bookings = load_bookings()
        bookings.append({'name': name,'email': email,'date': date_iso,'time': time_choice})
        save_bookings(bookings)
        print(f"Saved booking: {name} {email} {date_iso} {time_choice}")

        ok, err = send_mail(name, email, date_iso, time_choice)
        if not ok:
            return jsonify({'status':'partial','message':'Booking saved but failed to send email.','error': err}), 207

        return jsonify({'status':'success','message':f'Booking confirmed for {date_iso} at {time_choice}. A confirmation email has been sent.'})

    except Exception as e:
        tb = traceback.format_exc()
        print('Server error in /api/book:', e, tb)
        return jsonify({'status':'error','message':'Server error','error': str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
from flask import Flask, render_template, request, jsonify, make_response

app = Flask(__name__)

@app.after_request
def add_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response
from flask import Flask, render_template, request, jsonify
import json
import re
from datetime import datetime
from email.mime.text import MIMEText
import smtplib

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

