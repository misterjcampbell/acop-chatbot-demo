// static/script.js
(function () {
  const openBtn = document.getElementById("openChatBtn");
  const closeBtn = document.getElementById("closeChatBtn");
  const popup = document.getElementById("chatPopup");
  const messagesEl = document.getElementById("chatMessages");
  const userInput = document.getElementById("userInput");
  const sendBtn = document.getElementById("sendBtn");

  let chatStarted = false;

  function appendMessage(sender, text) {
    const el = document.createElement("div");
    el.className = sender === "user" ? "msg user" : "msg bot";
    el.innerText = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function openChat() {
    popup.style.display = "flex";
    popup.setAttribute("aria-hidden", "false");
    userInput.focus();
    if (!chatStarted) {
      // initial greeting
      setTimeout(() => {
        appendMessage("bot", "Hi! I'm here to help you book your assessment call. What's your name?");
        chatStarted = true;
      }, 200);
    }
  }

  function closeChat() {
    popup.style.display = "none";
    popup.setAttribute("aria-hidden", "true");
  }

  openBtn.addEventListener("click", openChat);
  closeBtn.addEventListener("click", closeChat);

  // allow Enter key to send
  userInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);

  async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;
    appendMessage("user", text);
    userInput.value = "";

    try {
      const res = await fetch("/api/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text })
      });
      if (!res.ok) {
        appendMessage("bot", "Sorry — server error. Please try again.");
        return;
      }
      const data = await res.json();
      appendMessage("bot", data.reply || "No reply.");
    } catch (err) {
      appendMessage("bot", "Network error. Please try again.");
      console.error(err);
    }
  }

  // Expose for debugging (optional)
  window.acopChat = { openChat, closeChat, appendMessage };
})();