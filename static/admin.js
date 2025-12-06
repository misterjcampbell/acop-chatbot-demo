// admin.js — Fixed Premium Admin Calendar (FullCalendar 6 + Range + Single Select)
(() => {
  // Config
  const API_EVENTS = "/admin/events";
  const API_BLOCK_SELECTED = "/admin/block-selected";
  const API_UNBLOCK_SELECTED = "/admin/unblock-selected";
  const API_TOGGLE_RANGE = "/admin/toggle-range";

  // State
  let calendar;
  let selectedDate = null;     // from dateClick
  let selectedRange = null;    // from select()

  // UI Elements
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');
  const calendarTitle = document.getElementById('calendarTitle'); // Fixed ID
  const selectModeBtn = document.getElementById('selectModeBtn');
  const blockBtn = document.getElementById('blockBtn');
  const unblockBtn = document.getElementById('unblockBtn');
  const blockRangeBtn = document.getElementById('blockRangeBtn');
  const unblockRangeBtn = document.getElementById('unblockRangeBtn');

  const monthNames = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];

  // Simple toast feedback
  function toast(msg, type = 'info') {
    console[type === 'error' ? 'error' : 'log']('ADMIN:', msg);
    const orig = calendarTitle.textContent.replace(/ • .*$/, '');
    calendarTitle.textContent = `\( {orig} • \){msg}`;
    setTimeout(() => { updateTitle(); }, 2000);
  }

  // Update the top title correctly
  function updateTitle() {
    if (!calendar) return;
    const view = calendar.view;
    const title = view.title; // FullCalendar gives perfect "Month Year"
    calendarTitle.textContent = title;
  }

  // Prevent sticky active state on buttons (mobile fix)
  function fixSticky(btn) {
    if (!btn) return;
    ['mouseup', 'mouseleave', 'touchend'].forEach(ev => {
      btn.addEventListener(ev, () => {
        btn.blur();
        btn.classList.remove('active');
      });
    });
  }
  [prevBtn, nextBtn, selectModeBtn, blockBtn, unblockBtn, blockRangeBtn, unblockRangeBtn].forEach(fixSticky);

  // Axios POST wrapper
  async function postJSON(url, data) {
    try {
      const res = await axios.post(url, data, {
        headers: { 'Content-Type': 'application/json' },
        timeout: 10000
      });
      return res.data;
    } catch (err) {
      console.error('API Error:', err);
      toast('Server error', 'error');
      throw err;
    }
  }

  // Highlight single selected date
  function highlightSelection(dateIso) {
    // Remove old highlights
    calendar.getEvents()
      .filter(e => e.id && e.id.startsWith('sel-'))
      .forEach(e => e.remove());

    // Add subtle background highlight
    calendar.addEvent({
      id: 'sel-' + dateIso,
      start: dateIso,
      allDay: true,
      display: 'background',
      backgroundColor: 'rgba(0, 123, 255, 0.15)',
      title: 'Selected'
    });
  }

  // Initialize FullCalendar
  function initCalendar() {
    const calendarEl = document.getElementById('calendar');

    calendar = new FullCalendar.Calendar(calendarEl, {
      initialView: 'dayGridMonth',
      height: 'auto',
      headerToolbar: false,           // we're using custom prev/next
      selectable: true,
      selectMirror: true,
      dayMaxEvents: 4,
      eventDisplay: 'block',

      // Single date click
      dateClick: function(info) {
        selectedDate = info.dateStr;
        selectedRange = null; // clear range
        highlightSelection(selectedDate);
        toast(`Selected: ${selectedDate}`);
      },

      // Drag selection (range)
      select: function(info) {
        selectedRange = {
          start: info.startStr.split('T')[0],
          end: info.endStr ? info.endStr.split('T')[0] : info.startStr.split('T')[0]
        };
        selectedDate = null;
        toast(`Range selected: \( {selectedRange.start} → \){selectedRange.end}`);
      },

      // Deselect when clicking outside
      unselect: function() {
        selectedDate = null;
        selectedRange = null;
        calendar.getEvents()
          .filter(e => e.id && e.id.startsWith('sel-'))
          .forEach(e => e.remove());
      },

      // Load events from backend
      events: API_EVENTS,

      // Update title when month changes
      datesSet: function() {
        updateTitle();
      },

      eventDidMount: function(arg) {
        arg.el.setAttribute('title', arg.event.title || 'Blocked');
      }
    });

    calendar.render();
    updateTitle(); // initial title

    // Prev/Next buttons
    prevBtn.addEventListener('click', () =>uref => calendar.prev());
    nextBtn.addEventListener('click', () => calendar.next());
  }

  // Button Actions
  blockBtn.addEventListener('click', async () => {
    if (!selectedDate) return toast('Click a date first');
    await postJSON(API_BLOCK_SELECTED, { date: selectedDate });
    toast(`Blocked ${selectedDate}`);
    selectedDate = null;
    calendar.refetchEvents();
  });

  unblockBtn.addEventListener('click', async () => {
    if (!selectedDate) return toast('Click a date first');
    await postJSON(API_UNBLOCK_SELECTED, { date: selectedDate });
    toast(`Unblocked ${selectedDate}`);
    selectedDate = null;
    calendar.refetchEvents();
  });

  blockRangeBtn.addEventListener('click', async () => {
    if (!selectedRange) return toast('Drag to select a range first');
    await postJSON(API_TOGGLE_RANGE, { ...selectedRange, action: 'block' });
    toast(`Blocked range \( {selectedRange.start} to \){selectedRange.end}`);
    selectedRange = null;
    calendar.refetchEvents();
  });

  unblockRangeBtn.addEventListener('click', async () => {
    if (!selectedRange) return toast('Drag to select a range first');
    await postJSON(API_TOGGLE_RANGE, { ...selectedRange, action: 'unblock' });
    toast(`Unblocked range \( {selectedRange.start} to \){selectedRange.end}`);
    selectedRange = null;
    calendar.refetchEvents();
  });

  // Optional: toggle select mode button (visual only)
  selectModeBtn.addEventListener('click', () => {
    const pressed = selectModeBtn.getAttribute('aria-pressed') === 'true';
    selectModeBtn.setAttribute('aria-pressed', String(!pressed));
    selectModeBtn.classList.toggle('active');
  });

  // Keyboard navigation
  document.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft') calendar.prev();
    if (e.key === 'ArrowRight') calendar.next();
  });

  // Start everything
  document.addEventListener('DOMContentLoaded', () => {
    initCalendar();
  });

})();