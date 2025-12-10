// static/chat-messenger.js
document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('chat-toggle');
  const popup = document.getElementById('chat-popup');
  const closeBtn = document.getElementById('close-chat');
  const box = document.getElementById('chat-box');
  const inputEl = document.getElementById('txt');
  const sendBtn = document.getElementById('send');

  // Pick or generate session id
  let session_id = localStorage.getItem('acop_sid');
  if (!session_id) {
    session_id = (crypto && crypto.randomUUID) ? crypto.randomUUID() : ('s_' + Date.now().toString(36) + Math.random().toString(36).slice(2));
    localStorage.setItem('acop_sid', session_id);
  }

  function open() { popup.style.display = 'block'; inputEl.focus(); popup.setAttribute('aria-hidden','false'); }
  function close() { popup.style.display = 'none'; popup.setAttribute('aria-hidden','true'); toggle.focus(); }

  toggle.addEventListener('click', open);
  closeBtn.addEventListener('click', close);

  function createMsgElement(text, who='bot') {
    const wrapper = document.createElement('div');
    wrapper.className = 'msg ' + (who === 'user' ? 'user' : 'bot');

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = String(text).replace(/\n/g, '<br>');
    wrapper.appendChild(bubble);

    return { wrapper, bubble };
  }

  function addMessage(text, who='bot', buttons=null) {
    const { wrapper } = createMsgElement(text, who);
    box.appendChild(wrapper);

    if (buttons && Array.isArray(buttons) && buttons.length) {
      const row = document.createElement('div');
      row.className = 'quick-buttons';
      buttons.forEach(btn => {
        const b = document.createElement('button');
        b.className = 'quick-button';
        b.type = 'button';
        b.textContent = btn.label || btn;
        b.onclick = () => {
          addMessage(btn.label || btn, 'user');
          // send the button's value to the backend
          sendMessage(btn.value || btn, true);
          // remove quick buttons after click
          row.remove();
        };
        row.appendChild(b);
      });
      box.appendChild(row);
    }

    box.scrollTop = box.scrollHeight;
  }

  function showTyping() {
    const { wrapper } = createMsgElement('Typing...', 'bot');
    wrapper.id = 'typing-ind';
    box.appendChild(wrapper);
    box.scrollTop = box.scrollHeight;
  }
  function hideTyping() {
    const el = document.getElementById('typing-ind');
    if (el) el.remove();
  }

  async function sendMessage(override=null, fromButton=false) {
    const text = (override !== null && override !== undefined) ? String(override).trim() : inputEl.value.trim();
    if (!text) return;

    if (!fromButton) {
      addMessage(text, 'user');
      inputEl.value = '';
    }

    showTyping();

    try {
      const res = await fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: session_id })
      });

      const data = await res.json().catch(()=>null);
      hideTyping();

      if (!data || typeof data.reply === 'undefined') {
        addMessage('Server error. Please try again.', 'bot');
        return;
      }

      if (data.session_id) {
        session_id = data.session_id;
        localStorage.setItem('acop_sid', session_id);
      }

      addMessage(String(data.reply || ''), 'bot', data.buttons || null);
    } catch (err) {
      hideTyping();
      addMessage('Network error — please try again.', 'bot');
      console.error('Chat error', err);
    }
  }

  sendBtn.addEventListener('click', (e) => { e.preventDefault(); sendMessage(); });
  inputEl.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); sendMessage(); } });

  // ensure chat auto-scrolls when user manually scrolls after messages
  box.addEventListener('scroll', () => { /* placeholder if you want to implement "user scrolled" behaviour */ });

  // open chat if user arrives from a query param ?openchat=1
  if (new URLSearchParams(window.location.search).get('openchat') === '1') open();
});

