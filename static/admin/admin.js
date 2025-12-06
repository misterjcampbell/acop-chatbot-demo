document.addEventListener('DOMContentLoaded', function () {
  const API_EVENTS = '/admin/events';
  const API_TOGGLE_DATE = '/admin/toggle-date';
  const API_TOGGLE_RANGE = '/admin/toggle-range';
  const API_BLOCK_SELECTED = '/admin/block-selected';
  const API_UNBLOCK_SELECTED = '/admin/unblock-selected';

  const calendarEl = document.getElementById('calendar');
  const blockRangeBtn = document.getElementById('blockRangeBtn');
  const unblockRangeBtn = document.getElementById('unblockRangeBtn');
  const blockBtn = document.getElementById('blockBtn');
  const unblockBtn = document.getElementById('unblockBtn');
  const refreshBtn = document.getElementById('refreshBtn');

  let selectedDate = null;
  let selectedRange = null;

  function toast(msg, isError=false) {
    // simple console + title trick (non-intrusive); replace with nicer UI when desired
    console[isError ? 'error' : 'log']('ADMIN:', msg);
  }

  function fixSticky(btn) {
    if (!btn) return;
    ['mouseup','mouseleave','touchend','touchcancel'].forEach(ev => {
      btn.addEventListener(ev, () => { btn.blur(); btn.classList.remove('active'); });
    });
  }
  [blockRangeBtn, unblockRangeBtn, blockBtn, unblockBtn, refreshBtn].forEach(fixSticky);

  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: 'dayGridMonth',
    height: 'auto',
    selectable: true,
    selectMirror: true,
    headerToolbar: false,
    dayMaxEventRows: 3,
    dateClick: function(info) {
      selectedDate = info.dateStr;
      selectedRange = null;
      // highlight selection visually
      calendar.getEvents().filter(e => e.id && e.id.startsWith('sel-')).forEach(e => e.remove());
      calendar.addEvent({ id: 'sel-' + selectedDate, start: selectedDate, allDay: true, display: 'background', backgroundColor: 'rgba(0,123,255,0.12)' });
      toast('Selected ' + selectedDate);
    },
    select: function(info) {
      // FullCalendar v6 returns an exclusive end date — convert to inclusive
      const start = info.startStr.split('T')[0];
      // calculate inclusive end
      const endDate = new Date(info.end);
      endDate.setDate(endDate.getDate() - 1);
      const end = endDate.toISOString().split('T')[0];

      selectedRange = { start, end };
      selectedDate = null;
      calendar.getEvents().filter(e => e.id && e.id.startsWith('sel-')).forEach(e => e.remove());
      toast(`Selected range: ${start} → ${end}`);
    },
    unselect: function() {
      selectedDate = null; selectedRange = null;
      calendar.getEvents().filter(e => e.id && e.id.startsWith('sel-')).forEach(e => e.remove());
      const view = calendar.view; if (view) { /* keep view title */ }
    },
    events: API_EVENTS,
    datesSet: function() {
      const view = calendar.view;
      // optionally update a title element
    },
    eventDidMount: function(arg) {
      if (arg.el) arg.el.setAttribute('title', arg.event.title || 'Event');
    }
  });

  calendar.render();

  refreshBtn.addEventListener('click', () => calendar.refetchEvents());

  blockBtn.addEventListener('click', async () => {
    if (!selectedDate) { toast('Click a day first', true); return; }
    try {
      const res = await fetch(API_TOGGLE_DATE, { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ date: selectedDate })});
      if (res.ok) { toast('Toggled block for ' + selectedDate); calendar.refetchEvents(); }
      else { toast('Server error', true); }
    } catch (err) { toast('Server error', true); console.error(err); }
  });

  unblockBtn.addEventListener('click', async () => {
    if (!selectedDate) { toast('Click a day first', true); return; }
    try {
      // your backend toggle_date handles both block/unblock; we use the same endpoint for single day
      const res = await fetch(API_TOGGLE_DATE, { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ date: selectedDate })});
      if (res.ok) { toast('Toggled block for ' + selectedDate); calendar.refetchEvents(); }
      else { toast('Server error', true); }
    } catch (err) { toast('Server error', true); console.error(err); }
  });

  blockRangeBtn.addEventListener('click', async () => {
    if (!selectedRange) { toast('Drag-select a range first', true); return; }
    try {
      const res = await fetch(API_TOGGLE_RANGE, { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ start: selectedRange.start, end: selectedRange.end, action:'block' })});
      if (res.ok) { toast('Blocked range'); calendar.refetchEvents(); selectedRange = null; }
      else { toast('Server error', true); }
    } catch (err) { toast('Server error', true); console.error(err); }
  });

  unblockRangeBtn.addEventListener('click', async () => {
    if (!selectedRange) { toast('Drag-select a range first', true); return; }
    try {
      const res = await fetch(API_TOGGLE_RANGE, { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ start: selectedRange.start, end: selectedRange.end, action:'unblock' })});
      if (res.ok) { toast('Unblocked range'); calendar.refetchEvents(); selectedRange = null; }
      else { toast('Server error', true); }
    } catch (err) { toast('Server error', true); console.error(err); }
  });
});
