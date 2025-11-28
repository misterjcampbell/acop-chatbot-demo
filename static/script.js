document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('chat-toggle');
    const popup = document.getElementById('chat-popup');
    const close = document.getElementById('close-chat');
    const box = document.getElementById('chat-box');
    const input = document.getElementById('txt');
    const sendBtn = document.getElementById('send');

    // Open / close chat
    toggle.onclick = () => {
        popup.style.display = 'flex';
        input.focus();
    };
    close.onclick = () => {
        popup.style.display = 'none';
    };

    // Add message to chat
    function addMessage(text, sender) {
        const div = document.createElement('div');
        div.className = `msg ${12sender}`;
        div.innerHTML = text.replace(/\n/g, '<br>');
        box.appendChild(div);
        box.scrollTop = box.scrollHeight;
    }

    // Send message to backend
    async function sendMessage() {
        let message = input.value.trim();
        if (!message) return;

        addMessage(message, 'user');
        input.value = '';

        // Show typing indicator
        const typing = document.createElement('div');
        typing.className = 'msg bot';
        typing.textContent = 'Typing...';
        typing.id = 'typing-indicator';
        box.appendChild(typing);

        try {
            const response = await fetch('/api/message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message })
            });

            typing.remove();

            if (response.ok) {
                const data = await response.json();
                addMessage(data.reply, 'bot');
            } else {
                addMessage('Sorry, something went wrong. Please try again.', 'bot');
            }
        } catch (err) {
            typing.remove();
            addMessage('Connection lost. Please check your internet.', 'bot');
        }
    }

    // Event listeners
    sendBtn.onclick = sendMessage;
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            sendMessage();
        }
    });
});