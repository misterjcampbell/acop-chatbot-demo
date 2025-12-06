// admin.js — Fixed & Production-Ready Admin Calendar
(() => {
  // Config
  const API_EVENTS = "/admin/events";
  const API_BLOCK_SELECTED = "/admin/block-selected";
  const API_UNBLOCK_SELECTED = "/admin/unblock-selected";
  const API_TOGGLE_RANGE = "/admin/toggle-range";

  // State
  let calendar = null;
  let selectedDate = null;
  let selectedRange = null;

  // Will be populated after DOM loads
  let prevBtn, nextBtn, calendarTitle;
  let selectModeBtn, blockBtn, unblockBtn;
  let blockRangeBtn, unblockRangeBtn;

  // Simple toast using the title bar
  function toast(msg, type = 'info') {
    if (!calendarTitle) return;
    console[type === 'error' ? 'error' : 'log']('ADMIN:', msg);
    const orig = calendarTitle.dataset.original || calendarTitle.textContent;
    calendarTitle.dataset.original = orig;
    calendarTitle.textContent = `${orig} • ${msg}`;
    setTimeout(() => {
      if (calendarTitle.dataset.original) {
        calendarTitle.textContent = calendarTitle.dataset.original;
      }
    }, 2000);
  }

  // Prevent mobile button "stuck active" state
  function fixSticky(btn) {
    if (!btn) return;
    ['mouseup', 'mouseleave', 'touchend'].forEach(ev => {
      btn.addEventListener(ev, () => {
        btn.blur();
        btn.classList.remove('active');
      });
    });
  }

  // Axios POST helper
  async function postJSON(url, payload) {
    try {
      const res = await axios.post(url, payload, {
        headers: { 'Content-Type': 'application/json' },
        timeout: 10000
      });
      return res.data;
    } catch (err) {
      console.error('API error', err);
      toast('Server error', 'error');
      throw err;
    }
  }

  // Highlight single clicked date
  function highlightSelection(dateIso) {
    calendar.getEvents()
      .filter(e => e.id?.startsWith('sel-'))
      .forEach(e => e.remove());

    calendar.addEvent({
      id: 'sel-' + dateIso,
      start: dateIso,
      allDay: true,
      display: 'background',
      backgroundColor: 'rgba(0, 123, 255, 0.18)',
      className: 'fc-highlight-selection'
    });
  }

  // Initialize FullCalendar
  function initCalendar() {
   const calendar = new FullCalendar.Calendar(calendarEl, {
  initialView: 'dayGridMonth',
  selectable: true,
  selectMirror: true,
  height: 'auto',

  headerToolbar: {
    left: 'prev,next today',
    center: 'title',
    right: ''
  },

  dateClick(info) {
    selectedDate = info.dateStr;
    selectedRange = null;

    calendar.removeAllEvents();
    calendar.addEvent({
      id: 'selected',
      start: selectedDate,
      allDay: true,
      display: 'background',
      backgroundColor: 'rgba(0,123,255,0.2)'
    });

    console.log("Selected single date:", selectedDate);
  },

  select(info) {
    const start = info.startStr.split("T")[0];

    const endObj = new Date(info.end);
    endObj.setDate(endObj.getDate() - 1);
    const end = endObj.toISOString().split("T")[0];

    selectedRange = { start, end };
    selectedDate = null;

    calendar.removeAllEvents();
    calendar.addEvent({
      id: 'selected-range',
      start,
      end: info.endStr,
      display: 'background',
      backgroundColor: 'rgba(0,123,255,0.25)'
    });

    console.log("Selected range:", selectedRange);
  },

  unselect() {
    // LESS AGGRESSIVE – DO NOT REMOVE SELECTION
    console.log("Unselect ignored to prevent clearing selection.");
  },

  events: '/admin/events'
});
      // Update month title
      datesSet: function () {
        const view = calendar.view;
        calendarTitle.textContent = view.title; // FullCalendar gives perfect "Month Year"
        calendarTitle.dataset.original = view.title;
      }
    });

    calendar.render();

    // Wire prev/next buttons
    prevBtn.addEventListener('click', () => calendar.prev());
    nextBtn.addEventListener('click', () => calendar.next());
  }

  // Button Actions
  function setupButtons() {
blockBtn.onclick = async () => {
  if (!selectedDate) return alert("Select a day first.");

  const res = await fetch("/admin/toggle-date", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: selectedDate, action: "block" })
  });

  calendar.refetchEvents();
};

unblockBtn.onclick = async () => {
  if (!selectedDate) return alert("Select a day first.");

  const res = await fetch("/admin/toggle-date", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: selectedDate, action: "unblock" })
  });

  calendar.refetchEvents();
};


  blockRangeBtn.onclick = async () => {
  if (!selectedRange) return alert("Select a range first.");

  await fetch("/admin/toggle-range", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ 
      start: selectedRange.start,
      end: selectedRange.end,
      action: "block"
    })
  });

  calendar.refetchEvents();
};

unblockRangeBtn.onclick = async () => {
  if (!selectedRange) return alert("Select a range first.");

  await fetch("/admin/toggle-range", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ 
      start: selectedRange.start,
      end: selectedRange.end,
      action: "unblock"
    })
  });

  calendar.refetchEvents();
};


    // Visual toggle (optional)
    selectModeBtn.addEventListener('click', () => {
      const pressed = selectModeBtn.getAttribute('aria-pressed') === 'true';
      selectModeBtn.setAttribute('aria-pressed', String(!pressed));
      selectModeBtn.classList.toggle('active');
    });

    // Fix sticky buttons
    [prevBtn, nextBtn, blockBtn, unblockBtn, blockRangeBtn, unblockRangeBtn, selectModeBtn]
      .forEach(fixSticky);
  }

  // Keyboard navigation
  document.addEventListener('keydown', e => {
    if (!calendar) return;
    if (e.key === 'ArrowLeft') calendar.prev();
    if (e.key === 'ArrowRight') calendar.next();
  });

  // DOM Ready — Safe to grab elements now!
  document.addEventListener('DOMContentLoaded', () => {
    // Grab all elements only now
    prevBtn = document.getElementById('prevBtn');
    nextBtn = document.getElementById('nextBtn');
    calendarTitle = document.getElementById('calendarTitle');
    selectModeBtn = document.getElementById('selectModeBtn');
    blockBtn = document.getElementById('blockBtn');
    unblockBtn = document.getElementById('unblockBtn');
    blockRangeBtn = document.getElementById('blockRangeBtn');
    unblockRangeBtn = document.getElementById('unblockRangeBtn');

    initCalendar();
    setupButtons();
  });

})();
