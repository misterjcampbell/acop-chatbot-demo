// Toggle chat popup
const chatButton = document.getElementById("chatButton");
const chatPopup = document.getElementById("chatPopup");

chatButton.onclick = () => {
    chatPopup.style.display =
        chatPopup.style.display === "none" || chatPopup.style.display === "" 
        ? "flex" 
        : "none";
};

// DOM Elements
const chatMessages = document.getElementById("chatMessages");
const userInput = document.getElementById("userInput");
const sendBtn = document.getElementById("sendBtn");

// Send user message
sendBtn.onclick = () => {
    const text = userInput.value.trim();
    if (!text) return;

    addMessage(text, "user");
    userInput.value = "";
    sendToBot(text);
};

// Press Enter to send
userInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendBtn.click();
});

// Display messages
function addMessage(text, sender) {
    const div = document.createElement("div");
    div.classList.add("message", sender);
    div.innerText = text;

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Send message to backend AI
function sendToBot(message) {
    fetch("/api/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message })
    })
    .then(res => res.json())
    .then(data => {
        addMessage(data.response, "bot");
    })
    .catch(err => {
        console.error(err);
        addMessage("Sorry — server error. Please try again later.", "bot");
    });
}