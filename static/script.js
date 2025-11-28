document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('chat-toggle');
    const popup = document.getElementById('chat-popup');
    const close = document.getElementById('close-chat');
    const box = document.getElementById('chat-box');
    const input = document.getElementById('txt');
    const send = document.getElementById('send');

    toggle.onclick = () => {
        popup.style.display = 'flex';
        input.focus();
    };
    close.onclick = () => popup.style.display = 'none';

    function addMessage(text, sender) {
        const div = document.createElement('div');
        div.className = `msg ${sender}`;
        div.innerHTML = text.replace(/\n/g, '<br>');
        box.appendChild(div);
        box.scrollTop = box.scrollHeight;
    }

    async function sendMessage() {
        let text = input.value.trim();
        if (!text) return;
        addMessage(text, 'user');
        input.value = '';

        const typing = document.createElement('div');
        typing.className = 'msg bot';
        typing.textContent = 'Typing...';
        typing.id = 'typing';
        box.appendChild(typing);

        try {
            const res = await fetch('/api/message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });
            typing.remove();
            const data = await res.json();
            addMessage(data.reply, 'bot');
        } catch (e) {
            typing.remove();
            addMessage('Connection error. Please try again.', 'bot');
        }
    }

    send.onclick = sendMessage;
    input.onkeypress = e => { if (e.key === 'Enter') sendMessage(); };
});