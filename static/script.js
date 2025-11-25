document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('chat-toggle');
    const popup = document.getElementById('chat-popup');
    const close = document.getElementById('close-chat');
    const box = document.getElementById('chat-box');
    const input = document.getElementById('txt');
    const send = document.getElementById('send');

    toggle.onclick = () => { popup.style.display = 'flex'; input.focus(); };
    close.onclick = () => { popup.style.display = 'none'; };

    function addMessage(text, sender) {
        const div = document.createElement('div');
        div.className = `msg ${sender}`;
        div.textContent = text;
        box.appendChild(div);
        box.scrollTop = box.scrollHeight;
    }

    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;
        addMessage(text, 'user');
        input.value = '';

        const typing = document.createElement('div');
        typing.className = 'msg bot typing';
        typing.textContent = 'Typing...';
        typing.id = 'typing';
        box.appendChild(typing);

        try {
            const res = await fetch('/api/message', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: text})
            });
            typing.remove();
            if (res.ok) {
                const data = await res.json();
                addMessage(data.reply, 'bot');
            } else {
                addMessage('Error. Try again.', 'bot');
            }
        } catch (e) {
            typing.remove();
            addMessage('Connection error.', 'bot');
        }
    }

    send.onclick = sendMessage;
    input.onkeypress = e => { if (e.key === 'Enter') { e.preventDefault(); sendMessage(); } };
});