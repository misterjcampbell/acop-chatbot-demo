document.addEventListener("DOMContentLoaded", () => {
  const chatBubble = document.createElement("div");
  chatBubble.id = "chat-bubble";
  chatBubble.textContent = "💬 Chat";
  document.body.appendChild(chatBubble);

  const chatBox = document.createElement("div");
  chatBox.id = "chat-box";
  chatBox.innerHTML = `
    <div id="chat-header">Engagement Assessment Bot</div>
    <div id="chat-messages"></div>
    <div id="chat-input">
      <input type="text" id="user-input" placeholder="Type your message..." autocomplete="off">
      <button id="send-btn">Send</button>
    </div>
  `;
  document.body.appendChild(chatBox);

  const chatMessages = document.getElementById("chat-messages");
  const userInput = document.getElementById("user-input");
  const sendBtn = document.getElementById("send-btn");

  // toggle chat window
  chatBubble.addEventListener("click", () => {
    chatBox.classList.toggle("open");
  });

  sendBtn.addEventListener("click", sendMessage);
  userInput.addEventListener("keypress", e => {
    if (e.key === "Enter") sendMessage();
  });

  function addMessage(sender, text) {
    const msg = document.createElement("div");
    msg.className = sender;
    msg.textContent = text;
    chatMessages.appendChild(msg);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;
    addMessage("user", text);
    userInput.value = "";

    try {
      const res = await fetch("/api/book", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text })
      });

      if (!res.ok) throw new Error("Network response was not ok");
      const data = await res.json();
      addMessage("bot", data.message || "Sorry, something went wrong.");
    } catch (err) {
      console.error("Chatbot error:", err);
      addMessage("bot", "Sorry, there was a server error. Please try again later.");
    }
  }
});
