let chatStarted = false;

function toggleChat() {
    const popup = document.getElementById("chat-popup");

    if (popup.classList.contains("hidden")) {
        popup.classList.remove("hidden");

        // Start the bot ONLY the first time
        if (!chatStarted) {
            showMessage("bot", "Hi! I'm here to help you book your assessment call. What's your name?");
            chatStarted = true;
        }
    } else {
        popup.classList.add("hidden");
    }
}

async function sendMessage() {
    const inputBox = document.getElementById("user-input");
    const msg = inputBox.value.trim();
    if (!msg) return;

    showMessage("user", msg);
    inputBox.value = "";

    const response = await fetch("/api/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg })
    });

    const data = await response.json();
    showMessage("bot", data.reply);
}

function showMessage(sender, text) {
    const chat = document.getElementById("messages");

    const bubble = document.createElement("div");
    bubble.className = sender === "user" ? "msg user" : "msg bot";
    bubble.innerText = text;

    chat.appendChild(bubble);
    chat.scrollTop = chat.scrollHeight;
}
