document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('chat-toggle');
  const popup = document.getElementById('chat-popup');
  const close = document.getElementById('close-chat');
  const box = document.getElementById('chat-box');
  const input = document.getElementById('txt');
  const send = document.getElementById('send');

  toggle.onclick = () => { popup.style.display='flex'; input.focus(); };
  close.onclick = () => popup.style.display='none';

  function addMessage(text, sender){
    const div = document.createElement('div');
    div.className = 'msg ' + sender;
    div.textContent = text; // safe
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function ensureSid(){
    let sid = localStorage.getItem('acop_sid');
    if(!sid){ sid = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36)+Math.random().toString(36).slice(2); localStorage.setItem('acop_sid', sid); }
    return sid;
  }

  async function sendMessage(){
    const txt = input.value.trim();
    if(!txt) return;
    addMessage(txt, 'user'); input.value='';
    const typ = document.createElement('div'); typ.className='msg bot'; typ.textContent='Typing...'; typ.id='typing'; box.appendChild(typ); box.scrollTop = box.scrollHeight;

    try {
      const sid = ensureSid();
      const res = await fetch('/api/message', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({message: txt, session_id: sid})
      });
      typ.remove();
      if(!res.ok){ addMessage('Server error. Please try again.', 'bot'); return; }
      const data = await res.json();
      if(data.session_id) localStorage.setItem('acop_sid', data.session_id);
      addMessage(data.reply || 'No response', 'bot');
    } catch (e) {
      typ.remove(); addMessage('Connection error. Please try again.', 'bot');
    }
  }

  send.onclick = sendMessage;
  input.addEventListener('keypress', (e)=>{ if(e.key==='Enter') sendMessage(); });
});
