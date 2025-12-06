document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("chat-toggle");
  const popup = document.getElementById("chat-popup");
  const closeBtn = document.getElementById("close-chat");
  const box = document.getElementById("chat-box");
  const input = document.getElementById("txt");
  const sendBtn = document.getElementById("send");

  // --- SESSION ID ---
  let sid = localStorage.getItem("acop_sid");
  if (!sid) {
    sid = crypto?.randomUUID
      ? crypto.randomUUID()
      : "s_" + Date.now().toString(36);
    localStorage.setItem("acop_sid", sid);
  }

  // --- OPEN & CLOSE ---
  function openChat() {
    popup.style.display = "block";
    popup.setAttribute("aria-hidden", "false");
    setTimeout(() => input.focus(), 150);
  }
  function closeChat() {
    popup.style.display = "none";
    popup.setAttribute("aria-hidden", "true");
  }

  toggle.addEventListener("click", openChat);
  closeBtn.addEventListener("click", closeChat);

  // --- SCROLL FIX ---
  function scrollToBottom() {
    box.scrollTop = box.scrollHeight;
  }

  // --- MESSAGE RENDERING ---
  function addMsg(text, who = "bot") {
    const wrapper = document.createElement("div");
    wrapper.className = "msg " + (who === "user" ? "user" : "bot");

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = text.replace(/\n/g, "<br>");

    wrapper.appendChild(bubble);
    box.appendChild(wrapper);
    scrollToBottom();
  }

  function showTyping() {
    const t = document.createElement("div");
    t.className = "msg bot typing";
    t.id = "typing";
    t.innerHTML = `<div class="bubble">Typing…</div>`;
    box.appendChild(t);
    scrollToBottom();
  }

  function hideTyping() {
    const t = document.getElementById("typing");
    if (t) t.remove();
  }

  // --- SEND MESSAGE ---
  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;

    addMsg(text, "user");
    input.value = "";

    showTyping();

    try {
      const res = await fetch("/api/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sid }),
      });

      const data = await res.json().catch(() => null);
      hideTyping();

      if (!data || !data.reply) {
        addMsg("Server error. Please try again.", "bot");
        return;
      }

      if (data.session_id) {
        sid = data.session_id;
        localStorage.setItem("acop_sid", sid);
      }

      addMsg(data.reply, "bot");
    } catch (err) {
      hideTyping();
      addMsg("Network error — please try again.", "bot");
    }
  }

  sendBtn.addEventListener("click", sendMessage);
  input.addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendMessage();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeChat();
  });
});
