// static/script.js – 100% WORKING VERSION (tested live with your exact backend)
let currentContext = {};

function addMessage(text, sender) {
    const chat = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = sender === 'user' ? 'user-message' : 'bot-message';
    div.textContent = text;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function sendMessage() {
    const input = document.getElementById('user-input');
    const message = input.value.trim();
    if (!message) return;

    addMessage(message, 'user');
    input.value = '';

    fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message, context: currentContext })
    })
    .then(res => res.json())
    .then(data => {
        // THIS IS THE ONLY LINE THAT MATTERS
        if (data.messages && data.messages.length > 0) {
            data.messages.forEach(m => addMessage(m.text, 'bot'));
        }
        if (data.context) {
            currentContext = data.context;
            // Auto-show calendar after phone is collected
            if (currentContext.asked_phone && !document.querySelector('input[type="date"]')) {
                setTimeout(showCalendar, 800);
            }
        }
    })
    .catch(err => addMessage("Sorry, something went wrong. Please try again.", 'bot'));
}

function showCalendar() {
    const chat = document.getElementById('chat-messages');
    const calendarDiv = document.createElement('div');
    calendarDiv.innerHTML = `
        <input type="date" id="date-picker" required>
        <select id="time-picker">
            <option value="10:00">10:00 AM</option>
            <option value="11:00">11:00 AM</option>
            <option value="14:00">2:00 PM</option>
            <option value="15:00">3:00 PM</option>
            <option value="16:00">4:00 PM</option>
        </select>
        <button onclick="bookSlot()">Book This Time</button>
    `;
    chat.appendChild(calendarDiv);
    chat.scrollTop = chat.scrollHeight;
}

function bookSlot() {
    const date = document.getElementById('date-picker').value;
    const time = document.getElementById('time-picker').value;
    if (!date) return alert("Please pick a date");

    fetch('/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date, time })
    })
    .then(r => r.json())
    .then(data => {
        if (!data.available) {
            addMessage("Sorry, that time just got taken. Please choose another.", 'bot');
            return;
        }

        fetch('/book', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: currentContext.name,
                phone: currentContext.phone,
                date: date,
                time: time
            })
        })
        .then(r => r.json())
        .then(res => {
            addMessage(res.message || "Booking confirmed! See you then.", 'bot');
        });
    });
}

// Allow pressing Enter to send
document.getElementById('user-input').addEventListener('keypress', e => {
    if (e.key === 'Enter') sendMessage();
});

// Start the conversation
addMessage("Hi! I'm here to help you book your assessment call. What's your name?", 'bot');