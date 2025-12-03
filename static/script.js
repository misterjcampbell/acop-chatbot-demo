document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('chat-toggle');
    const popup = document.getElementById('chat-popup');
    const close = document.getElementById('close-chat');
    const box = document.getElementById('chat-box');
    const input = document.getElementById('txt');
    const send = document.getElementById('send');

    // --- persistent session ID ---
    let session_id = localStorage.getItem("acop_sid");
    if (!session_id) {
        session_id = Math.random().toString(36).substring(2);
        localStorage.setItem("acop_sid", session_id);
    }

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
                body: JSON.stringify({
                    message: text,
                    session_id: session_id
                })
            });

            const data = await res.json().catch(() => null);
            typing.remove();

            if (!data || !data.reply) {
                addMessage("Server error. Please try again.", 'bot');
                return;
            }

            addMessage(data.reply, 'bot');

        } catch (e) {
            typing.remove();
            addMessage('Connection error. Please try again.', 'bot');
        }
    }

    send.onclick = sendMessage;
    input.onkeypress = e => { if (e.key === 'Enter') sendMessage(); };
});
