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