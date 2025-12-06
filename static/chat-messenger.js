document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('chat-toggle');
  const popup = document.getElementById('chat-popup');
  const closeBtn = document.getElementById('close-chat');
  const box = document.getElementById('chat-box');
  const input = document.getElementById('txt');
  const sendBtn = document.getElementById('send');

  // session id persisted
  let sid = localStorage.getItem('acop_sid');
  if (!sid) {
    sid = (crypto && crypto.randomUUID) ? crypto.randomUUID() : 's_' + Date.now().toString(36);
    localStorage.setItem('acop_sid', sid);
  }
function scrollChat() {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      box.scrollTop = box.scrollHeight;
    });
  });
}
  function openChat() {
    popup.style.display = 'block';
    popup.setAttribute('aria-hidden', 'false');
    input.focus();
    // ensure last message visible
    box.scrollTop = box.scrollHeight;
  }
  function closeChat() {
    popup.style.display = 'none';
    popup.setAttribute('aria-hidden', 'true');
    toggle.focus();
  }

  toggle.addEventListener('click', openChat);
  closeBtn.addEventListener('click', closeChat);

  function addMessage(text, who='bot') {
    const wrapper = document.createElement('div');
    wrapper.className = 'msg ' + (who === 'user' ? 'user' : 'bot');

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = text.replace(/\n/g,'<br>');
    wrapper.appendChild(bubble);

    box.appendChild(wrapper);
    // scroll to bottom with small delay for layout
    setTimeout(()=> { box.scrollTop = box.scrollHeight; }, 50);
  }

  function showTyping() {
    const t = document.createElement('div');
    t.className = 'msg bot typing';
    t.id = 'typing-ind';
    t.innerHTML = '<div class="bubble">Typing…</div>';
    box.appendChild(t);
    box.scrollTop = box.scrollHeight;
  }
  function hideTyping() {
    const t = document.getElementById('typing-ind');
    if (t) t.remove();
  }

  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;
    addMessage(text, 'user');
    input.value = '';
    showTyping();

    try {
      const res = await fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sid })
      });
      const data = await res.json();
      hideTyping();
      if (data && data.reply) {
        addMessage(data.reply, 'bot');
      } else {
        addMessage('Server error. Please try again.', 'bot');
      }
      if (data && data.session_id) {
        sid = data.session_id;
        localStorage.setItem('acop_sid', sid);
      }
    } catch (err) {
      hideTyping();
      addMessage('Network error — please try again.', 'bot');
      console.error('Chat send error', err);
    }
  }

  sendBtn.addEventListener('click', (e) => { e.preventDefault(); sendMessage(); });
  input.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });

  // Accessibility: ESC closes
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeChat(); });
});
