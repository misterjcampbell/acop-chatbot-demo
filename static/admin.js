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
    const calendarEl = document.getElementById('calendar');
    if (!calendarEl) return;

    calendar = new FullCalendar.Calendar(calendarEl, {
      initialView: 'dayGridMonth',
      height: 'auto',
      headerToolbar: false,
      selectable: true,
      selectMirror: true,
      dayMaxEvents: 4,

      // Single date click
      dateClick: function (info) {
        selectedDate = info.dateStr;
        selectedRange = null;
        highlightSelection(selectedDate);
        toast(`Selected: ${selectedDate}`);
      },

      // Drag range selection
      select: function (info) {
        selectedDate = null;
        selectedRange = {
          start: info.startStr.split('T')[0],
          end: info.endStr ? info.endStr.split('T')[0] : info.startStr.split('T')[0]
        };
        toast(`Range: ${selectedRange.start} → ${selectedRange.end}`);
      },

      // Clear selection when clicking outside
      unselect: function () {
        selectedDate = null;
        selectedRange = null;
        calendar.getEvents()
          .filter(e => e.id?.startsWith('sel-'))
          .forEach(e => e.remove());
      },

      events: API_EVENTS,

      eventDidMount: function (arg) {
        arg.el.setAttribute('title', arg.event.title || 'Blocked');
      },

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
    blockBtn.addEventListener('click', async () => {
      if (!selectedDate) return toast('Click a date first');
      await postJSON(API_BLOCK_SELECTED, { date: selectedDate });
      toast(`Blocked ${selectedDate}`);
      selectedDate = null;
      calendar.refetchEvents();
      highlightSelection.clear?.();
    });

    unblockBtn.addEventListener('click', async () => {
      if (!selectedDate) return toast('Click a date first');
      await postJSON(API_UNBLOCK_SELECTED, { date: selectedDate });
      toast(`Unblocked ${selectedDate}`);
      selectedDate = null;
      calendar.refetchEvents();
    });

    blockRangeBtn.addEventListener('click', async () => {
      if (!selectedRange) return toast('Drag-select a range first');
      await postJSON(API_TOGGLE_RANGE, { ...selectedRange, action: 'block' });
      toast(`Blocked range`);
      selectedRange = null;
      calendar.refetchEvents();
    });

    unblockRangeBtn.addEventListener('click', async () => {
      if (!selectedRange) return toast('Drag-select a range first');
      await postJSON(API_TOGGLE_RANGE, { ...selectedRange, action: 'unblock' });
      toast(`Unblocked range`);
      selectedRange = null;
      calendar.refetchEvents();
    });

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
