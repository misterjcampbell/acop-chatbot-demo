// --------------------------------------
// ACOP Chat — Enhanced Messaging Logic
// --------------------------------------

let sessionId = null;
let verificationCodeInputActive = false;

const chatWrapper  = document.getElementById("chat-wrapper");
const chatMessages = document.getElementById("chat-messages");
const chatInput    = document.getElementById("chat-input");
const chatSend     = document.getElementById("chat-send");
const chatLauncher = document.getElementById("chat-launcher");
const chatClose    = document.getElementById("chat-close");

// --------------------------------------
// OPEN / CLOSE
// --------------------------------------

chatLauncher.onclick = () => {
  chatWrapper.classList.remove("hidden");
  chatLauncher.style.display = "none";

  if (chatMessages.children.length === 0) {
    displayBotMessage("Hi! I'm here to help you book an assessment call. What's your name?");
  }

  chatInput.focus();
};

chatClose.onclick = () => {
  chatWrapper.classList.add("hidden");
  chatLauncher.style.display = "block";
};

// --------------------------------------
// SCROLL
// --------------------------------------

function scrollChat() {
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// --------------------------------------
// STAGE DETECTION
// --------------------------------------

function detectStage(botMessage) {
  const msg = botMessage.toLowerCase();

  if (msg.includes("verification code") && msg.includes("enter")) return "email_verify";
  if (msg.includes("email verified") || msg.includes("✓"))         return "phone";
  if (msg.includes("phone number"))                                 return "phone";
  if (msg.includes("which date"))                                   return "date";
  if (msg.includes("available") && msg.includes("time"))            return "time";
  return null;
}

// --------------------------------------
// VERIFICATION CODE INPUT
// --------------------------------------

function createVerificationInput() {
  const wrapper = document.createElement("div");
  wrapper.className = "verification-input-wrapper";
  wrapper.id = "verification-wrapper";

  for (let i = 0; i < 6; i++) {
    const input = document.createElement("input");
    input.type = "text";
    input.maxLength = 1;
    input.className = "verification-input";
    input.dataset.index = i;
    input.inputMode = "numeric";
    input.pattern = "[0-9]";

    input.addEventListener("input", (e) => {
      const value = e.target.value;
      if (value.length === 1 && i < 5) {
        const nextInput = wrapper.querySelector(`[data-index="${i + 1}"]`);
        if (nextInput) nextInput.focus();
      }
      e.target.classList.add("filled");
      checkAndSubmitCode(wrapper);
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && !e.target.value && i > 0) {
        const prevInput = wrapper.querySelector(`[data-index="${i - 1}"]`);
        if (prevInput) {
          prevInput.focus();
          prevInput.value = "";
          prevInput.classList.remove("filled");
        }
      }
    });

    input.addEventListener("keypress", (e) => {
      if (!/[0-9]/.test(e.key)) e.preventDefault();
    });

    wrapper.appendChild(input);
  }

  return wrapper;
}

function checkAndSubmitCode(wrapper) {
  const inputs = wrapper.querySelectorAll(".verification-input");
  const code = Array.from(inputs).map(input => input.value).join("");
  if (code.length === 6) {
    setTimeout(() => sendMessage(code, false), 300);
  }
}

function showVerificationError(wrapper) {
  const inputs = wrapper.querySelectorAll(".verification-input");
  inputs.forEach(input => {
    input.classList.add("error");
    setTimeout(() => {
      input.classList.remove("error");
      input.value = "";
      input.classList.remove("filled");
    }, 500);
  });
  inputs[0].focus();
}

// --------------------------------------
// PHONE FORMAT HINT
// --------------------------------------

function addPhoneFormatHint() {
  const hint = document.createElement("div");
  hint.className = "format-hint";
  hint.innerHTML = `
    <strong>Accepted formats:</strong><br>
    • Mobile: 0412 345 678<br>
    • Landline: 02 9876 5432<br>
    • International: +61 412 345 678
  `;
  return hint;
}

// --------------------------------------
// MESSAGE RENDERING
// --------------------------------------

function displayBotMessage(text, buttons) {
  const msgDiv = document.createElement("div");
  msgDiv.className = "message bot-message";

  const contentDiv = document.createElement("div");
  contentDiv.className = "message-content";
  contentDiv.textContent = text;
  msgDiv.appendChild(contentDiv);

  chatMessages.appendChild(msgDiv);

  const stage = detectStage(text);

  if (stage === "email_verify") {
    const verificationInput = createVerificationInput();
    msgDiv.appendChild(verificationInput);
    verificationCodeInputActive = true;

    chatInput.style.display = "none";
    chatSend.style.display  = "none";
    setTimeout(() => {
      verificationInput.querySelector('[data-index="0"]').focus();
    }, 100);

  } else if (stage === "phone") {
    chatInput.style.display = "block";
    chatSend.style.display  = "block";
    verificationCodeInputActive = false;
    msgDiv.appendChild(addPhoneFormatHint());

  } else if (verificationCodeInputActive && text.includes("incorrect")) {
    const wrapper = document.getElementById("verification-wrapper");
    if (wrapper) showVerificationError(wrapper);

  } else if (verificationCodeInputActive && (text.includes("verified") || text.includes("✓"))) {
    chatInput.style.display = "block";
    chatSend.style.display  = "block";
    verificationCodeInputActive = false;
  }

  if (buttons && buttons.length > 0) {
    const btnContainer = document.createElement("div");
    btnContainer.className = "button-container";
    buttons.forEach(btn => {
      const button = document.createElement("button");
      button.className = "chat-button";
      button.textContent = btn.label;
      button.onclick = () => sendMessage(btn.value, true);
      btnContainer.appendChild(button);
    });
    msgDiv.appendChild(btnContainer);
  }

  scrollChat();
}

function displayUserMessage(text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = "message user-message";

  const contentDiv = document.createElement("div");
  contentDiv.className = "message-content";
  contentDiv.textContent = text;
  msgDiv.appendChild(contentDiv);

  chatMessages.appendChild(msgDiv);
  scrollChat();
}

// --------------------------------------
// SEND MESSAGE
// --------------------------------------

async function sendMessage(message, fromButton = false) {
  if (!message && !fromButton) return;
  const text = message || chatInput.value.trim();
  if (!text) return;

  // Don't echo the 6-digit code as a user bubble
  if (!verificationCodeInputActive || text.length !== 6) {
    displayUserMessage(text);
  }

  chatInput.value    = "";
  chatInput.disabled = true;
  chatSend.disabled  = true;

  try {
    const response = await fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
        from_button: fromButton
      })
    });

    const data = await response.json();
    sessionId = data.session_id;
    displayBotMessage(data.reply, data.buttons || []);

  } catch (error) {
    console.error("Error:", error);
    displayBotMessage("Sorry, something went wrong. Please try again.");
  } finally {
    chatInput.disabled = false;
    chatSend.disabled  = false;
    if (!verificationCodeInputActive) chatInput.focus();
  }
}

// --------------------------------------
// EVENT LISTENERS
// --------------------------------------

chatSend.onclick = () => sendMessage(chatInput.value);
chatInput.onkeypress = (e) => { if (e.key === "Enter") sendMessage(chatInput.value); };
