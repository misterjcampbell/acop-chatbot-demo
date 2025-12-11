let sessionId = null;

const launcher = document.getElementById("chat-launcher");
const wrapper  = document.getElementById("chat-wrapper");

// ------------------------
// Launcher click → open widget
// ------------------------
launcher.onclick = () => {
    wrapper.classList.remove("hidden");
    launcher.style.display = "none";
    startChat();
};


// ------------------------
// DOM elements
// ------------------------
const chatBox = document.getElementById("chat-messages");
const input   = document.getElementById("chat-input");
const sendBtn = document.getElementById("chat-send");


// ------------------------
// Auto-scroll
// ------------------------
function scrollChat() {
    chatBox.scrollTop = chatBox.scrollHeight;
}


// ------------------------
// Add message bubble
// ------------------------
function addMessage(text, type = "bot") {
    const bubble = document.createElement("div");
    bubble.className = type === "user" ? "msg-user" : "msg-bot";
    bubble.innerText = text;
    chatBox.appendChild(bubble);
    scrollChat();
    setTimeout(scrollChat, 80);
}


// ------------------------
// Add bot buttons
// ------------------------
function addButtons(buttonArray) {
    const container = document.createElement("div");
    container.className = "msg-bot";

    buttonArray.forEach(btn => {
        const button = document.createElement("button");
        button.className = "bot-button";
        button.innerText = btn.label;
        button.onclick = () => sendMessage(btn.value, true);
        container.appendChild(button);
    });

    chatBox.appendChild(container);
    scrollChat();
}


// ------------------------
// Main message sender
// ------------------------
async function sendMessage(override = null, fromButton = false) {
    const text = override || input.value.trim();
    if (!text) return;

    if (!fromButton) addMessage(text, "user");
    input.value = "";

    const payload = { message: text };
    if (sessionId) payload.session_id = sessionId;

    const res = await fetch("/api/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (data.session_id) sessionId = data.session_id;
    if (data.reply) addMessage(data.reply, "bot");
    if (data.buttons) addButtons(data.buttons);
}

sendBtn.onclick = () => sendMessage();
input.onkeydown = e => { if (e.key === "Enter") sendMessage(); };


// ------------------------
// INITIAL GREETING (only after clicking launcher)
// ------------------------
function startChat() {
    addMessage(
        "Hi there! I can help you book your assessment call.\n\nWhat's your name?",
        "bot"
    );
}


// ------------------------
// Clear chat & session on page load
// ------------------------
window.onload = () => {
    sessionId = null;
    chatBox.innerHTML = "";
    // Chat remains CLOSED until user clicks launcher
};
