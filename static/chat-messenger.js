// --------------------------------------
// ACOP Chat Launcher + Messaging Logic
// --------------------------------------

let sessionId = null;
const launcher = document.getElementById("chat-launcher");
const wrapper = document.getElementById("chat-wrapper");
// delay
let typingBubble = null;
let typingStartTime = 0;
const MIN_TYPING_TIME = 700; // ms (tweak 500–900 if you want)
// Open chat
launcher.onclick = () => {
    wrapper.classList.remove("hidden");
    setTimeout(() => wrapper.classList.add("open"), 10);
    launcher.style.display = "none";
    startChat();
};

// Bubble
let typingBubble = null;

function showTyping() {
    if (typingBubble) return;
    typingStartTime = Date.now();
    typingBubble = document.createElement("div");
    typingBubble.className = "msg-bot typing";
    typingBubble.innerHTML = "<span></span><span></span><span></span>";
    chatBox.appendChild(typingBubble);
    scrollChat();
}

function hideTyping(callback) {
    const elapsed = Date.now() - typingStartTime;
    const delay = Math.max(0, MIN_TYPING_TIME - elapsed);

    setTimeout(() => {
        if (typingBubble) {
            typingBubble.remove();
            typingBubble = null;
        }
        if (callback) callback();
    }, delay);
}


// DOM
const chatBox = document.getElementById("chat-messages");
const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("chat-send");

// Auto-scroll
function scrollChat() {
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Add message
function addMessage(text, type = "bot") {
    const wrapper = document.createElement("div");
    wrapper.className = type === "user" ? "msg-user-wrap" : "msg-bot";

    const bubble = document.createElement("div");
    bubble.className = type === "user" ? "msg-user" : "msg-bot";
    bubble.innerText = text;

    wrapper.appendChild(bubble);

    // Read receipt
    if (type === "user") {
        const receipt = document.createElement("span");
        receipt.className = "read-receipt";
        receipt.innerText = "✓";
        wrapper.appendChild(receipt);
        wrapper.dataset.receipt = "sent";
    }

    chatBox.appendChild(wrapper);
    scrollChat();
}


// Buttons (chips)
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

// SEND MESSAGE
async function sendMessage(override = null, fromButton = false) {
    const text = override || input.value.trim();
    if (!text) return;

    if (!fromButton) addMessage(text, "user");
    input.value = "";

    const payload = { message: text };
    if (sessionId) payload.session_id = sessionId;

    try {
        const res = await fetch("/api/message", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();

        if (data.session_id) sessionId = data.session_id;
        if (data.reply) addMessage(data.reply, "bot");
        document.querySelectorAll("[data-receipt='sent']").forEach(el => {
            el.querySelector(".read-receipt").innerText = "✓✓";
            el.dataset.receipt = "read";
        });
        if (data.buttons) addButtons(data.buttons);

    } catch (err) {
        addMessage("Sorry, something went wrong.", "bot");
    }
}

// Send on click + Enter
sendBtn.onclick = () => showTyping();sendMessage();hideTyping();hideTyping();
input.onkeydown = e => { if (e.key === "Enter") sendMessage(); };
hideTyping(() => {
    if (data.reply) addMessage(data.reply, "bot");
    if (data.buttons) addButtons(data.buttons);
});


// --------------------------------------
// INITIAL WELCOME MESSAGE
// --------------------------------------
function startChat() {
    chatBox.innerHTML = "";
    addMessage("Hi there! I can help you book your assessment call.\n\nWhat's your name?", "bot");
}
document.getElementById("chat-close").onclick = () => {
    wrapper.classList.remove("open");
    setTimeout(() => {
        wrapper.classList.add("hidden");
        launcher.style.display = "block";
    }, 300);
};

// --------------------------------------
// RESET on page load
// --------------------------------------
window.onload = () => {
    sessionId = null;
    chatBox.innerHTML = "";
};
