document.addEventListener("DOMContentLoaded", () => {
  let selectedDate = null;
  let selectedRange = null;

  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");
  const titleEl = document.getElementById("calendarTitle");

  const blockBtn = document.getElementById("blockBtn");
  const unblockBtn = document.getElementById("unblockBtn");
  const blockRangeBtn = document.getElementById("blockRangeBtn");
  const unblockRangeBtn = document.getElementById("unblockRangeBtn");

  const calendar = new FullCalendar.Calendar(document.getElementById("calendar"), {
    initialView: "dayGridMonth",
    selectable: true,
    height: "auto",
    events: "/admin/events",

    dateClick(info) {
      selectedDate = info.dateStr;
      selectedRange = null;
    },

    select(info) {
      selectedDate = null;
      selectedRange = {
        start: info.startStr.split("T")[0],
        end: info.endStr.split("T")[0],
      };
    },

    datesSet(info) {
      titleEl.textContent = info.view.title;
    },
  });

  calendar.render();

  prevBtn.onclick = () => calendar.prev();
  nextBtn.onclick = () => calendar.next();

  async function post(url, payload) {
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    calendar.refetchEvents();
  }

  blockBtn.onclick = () => {
    if (!selectedDate) return alert("Select a date first");
    post("/admin/toggle-date", { date: selectedDate, action: "block" });
  };

  unblockBtn.onclick = () => {
    if (!selectedDate) return alert("Select a date first");
    post("/admin/toggle-date", { date: selectedDate, action: "unblock" });
  };

  blockRangeBtn.onclick = () => {
    if (!selectedRange) return alert("Select a range first");
    post("/admin/toggle-range", { ...selectedRange, action: "block" });
  };

  unblockRangeBtn.onclick = () => {
    if (!selectedRange) return alert("Select a range first");
    post("/admin/toggle-range", { ...selectedRange, action: "unblock" });
  };
});
document.getElementById("testEmailBtn")?.addEventListener("click", async () => {
    const resultEl = document.getElementById("testEmailResult");
    resultEl.textContent = "Sending...";
    resultEl.style.color = "#555";

    try {
        const r = await fetch("/admin/test-email");
        const t = await r.text();

        if (t.trim() === "OK") {
            resultEl.textContent = "Email sent successfully!";
            resultEl.style.color = "green";
        } else {
            resultEl.textContent = "Email FAILED: " + t;
            resultEl.style.color = "red";
        }
    } catch (e) {
        resultEl.textContent = "Network error — could not send.";
        resultEl.style.color = "red";
    }
});
