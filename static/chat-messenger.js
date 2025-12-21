// --------------------------------------
// ACOP Chat Launcher + Messaging Logic
// --------------------------------------

let sessionId = null;

const launcher = document.getElementById("chat-launcher");
const wrapper = document.getElementById("chat-wrapper");
const chatBox = document.getElementById("chat-messages");
const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("chat-send");

// --------------------------------------
// OPEN / CLOSE
// --------------------------------------

launcher.onclick = () => {
  wrapper.classList.remove("hidden");
  setTimeout(() => wrapper.classList.add("open"), 10);
  launcher.style.display = "none";
  startChat();
};

document.getElementById("chat-close").onclick = () => {
  wrapper.classList.remove("open");
  setTimeout(() => {
    wrapper.classList.add("hidden");
    launcher.style.display = "block";
  }, 300);
};

// --------------------------------------
// SCROLL
// --------------------------------------

function scrollChat() {
  chatBox.scrollTop = chatBox.scrollHeight;
}

// --------------------------------------
// MESSAGE RENDERING
// --------------------------------------

function addMessage(text, type = "bot") {
  const row = document.createElement("div");
  row.className = type === "user" ? "msg-row user" : "msg-row bot";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerText = text;

  row.appendChild(bubble);

  if (type === "user") {
    const receipt = document.createElement("span");
    receipt.className = "read-receipt";
    receipt.innerText = "✓";
    row.appendChild(receipt);
    row.dataset.receipt = "sent";
  }

  chatBox.appendChild(row);
  scrollChat();
}

// --------------------------------------
// BUTTONS (CHIPS)
// --------------------------------------

function addButtons(buttons) {
  const row = document.createElement("div");
  row.className = "msg-row bot";

  buttons.forEach(btn => {
    const b = document.createElement("button");
    b.className = "bot-button";
    b.innerText = btn.label;
    b.onclick = () => sendMessage(btn.value, true);
    row.appendChild(b);
  });

  chatBox.appendChild(row);
  scrollChat();
}

// --------------------------------------
// TYPING INDICATOR
// --------------------------------------

let typingBubble = null;
let typingStart = 0;
const MIN_TYPING_TIME = 700;

function showTyping() {
  if (typingBubble) return;

  typingStart = Date.now();
  typingBubble = document.createElement("div");
  typingBubble.className = "msg-row bot";

  const bubble = document.createElement("div");
  bubble.className = "bubble typing";
  bubble.innerHTML = "<span></span><span></span><span></span>";

  typingBubble.appendChild(bubble);
  chatBox.appendChild(typingBubble);
  scrollChat();
}

function hideTyping(callback) {
  const elapsed = Date.now() - typingStart;
  const delay = Math.max(0, MIN_TYPING_TIME - elapsed);

  setTimeout(() => {
    if (typingBubble) {
      typingBubble.remove();
      typingBubble = null;
    }
    if (callback) callback();
  }, delay);
}

// --------------------------------------
// SEND MESSAGE
// --------------------------------------

async function sendMessage(override = null, fromButton = false) {
  const text = override || input.value.trim();
  if (!text) return;

  if (!fromButton) addMessage(text, "user");
  input.value = "";

  showTyping();

  const payload = { message: text };
  if (sessionId) payload.session_id = sessionId;

  try {
    const res = await fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    hideTyping(() => {
      if (data.session_id) sessionId = data.session_id;
      if (data.reply) addMessage(data.reply, "bot");
      if (data.buttons) addButtons(data.buttons);

      document.querySelectorAll("[data-receipt='sent']").forEach(el => {
        el.querySelector(".read-receipt").innerText = "✓✓";
        el.dataset.receipt = "read";
      });
    });

  } catch {
    hideTyping(() => addMessage("Sorry, something went wrong.", "bot"));
  }
}

sendBtn.onclick = () => sendMessage();
input.onkeydown = e => { if (e.key === "Enter") sendMessage(); };

// --------------------------------------
// INITIAL MESSAGE
// --------------------------------------

function startChat() {
  chatBox.innerHTML = "";
  sessionId = null;
  addMessage(
    "Hi there! I can help you book your assessment call.\n\nWhat's your name?",
    "bot"
  );
}

