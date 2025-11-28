let currentContext = {};

function toggleChat() {
    const widget = document.getElementById('chat-widget');
    const launcher = document.getElementById('chat-launcher');
    if (widget.style.display === 'none' || widget.style.display === '') {
        widget.style.display = 'block';
        launcher.style.display = 'none';
        if (document.getElementById('chat-messages').children.length === 0) {
            addMessage("Hi! I'm here to help you book your assessment call. What's your name?", 'bot');
        }
    } else {
        widget.style.display = 'none';
        launcher.style.display = 'block';
    }
}

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
    .then(r => r.json())
    .then(data => {
        if (data.messages) {
            data.messages.forEach(m => addMessage(m.text, 'bot'));
        }
        if (data.context) {
            currentContext = data.context;
            if (currentContext.asked_phone && !document.getElementById('date-picker')) {
                setTimeout(showCalendar, 600);
            }
        }
    });
}

function showCalendar() {
    const chat = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.innerHTML = `
        <p><strong>Please select your preferred date and time:</strong></p>
        <input type="date" id="date-picker" required>
        <select id="time-picker">
            <option value="10:00">10:00 AM</option>
            <option value="11:00">11:00 AM</option>
            <option value="14:00">2:00 PM</option>
            <option value="15:00">3:00 PM</option>
            <option value="16:00">4:00 PM</option>
        </select>
        <button onclick="bookSlot()" style="margin-top:8px;">Book This Slot</button>
    `;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function bookSlot() {
    const date = document.getElementById('date-picker').value;
    const time = document.getElementById('time-picker').value;
    if (!date) return addMessage("Please choose a date first.", 'bot');

    fetch('/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date, time })
    })
    .then(r => r.json())
    .then(res => {
        if (!res.available) {
            addMessage("That slot was just taken. Please pick another time.", 'bot');
            return;
        }

        fetch('/book', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: currentContext.name,
                phone: currentContext.phone || currentContext.phone,
                date, time
            })
        })
        .then(r => r.json())
        .then(result => {
            addMessage(result.message || "Your booking is confirmed! Thank you.", 'bot');
        });
    });
}

// Send on Enter
document.getElementById('user-input')?.addEventListener('keypress', e => {
    if (e.key === 'Enter') sendMessage();
});