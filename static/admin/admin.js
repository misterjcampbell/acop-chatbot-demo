document.addEventListener('DOMContentLoaded', function () {
  const API_EVENTS = '/admin/events';
  const API_TOGGLE_DATE = '/admin/toggle-date';
  const API_TOGGLE_RANGE = '/admin/toggle-range';
  const API_BLOCK_SELECTED = '/admin/block-selected';
  const API_UNBLOCK_SELECTED = '/admin/unblock-selected';

  const calendarEl = document.getElementById('calendar');
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');
  const calendarTitle = document.getElementById('calendarTitle');
  const blockRangeBtn = document.getElementById('blockRangeBtn');
  const unblockRangeBtn = document.getElementById('unblockRangeBtn');
  const blockBtn = document.getElementById('blockBtn');
  const unblockBtn = document.getElementById('unblockBtn');
  const refreshBtn = document.getElementById('refreshBtn');

  let selectedDate = null;
  let selectedRange = null;

  function toast(msg, level = 'info') {
    console[level === 'error' ? 'error' : 'log']('ADMIN:', msg);
    calendarTitle.textContent = msg;
    setTimeout(() => {
      const view = calendar.view;
      if (view) calendarTitle.textContent = view.title;
    }, 1600);
  }

  function fixSticky(btn) {
    if (!btn) return;
    ['mouseup', 'mouseleave', 'touchend'].forEach(ev => { btn.addEventListener(ev, ()=> { btn.blur(); btn.classList.remove('active'); }); });
  }
  [blockRangeBtn, unblockRangeBtn, blockBtn, unblockBtn, prevBtn, nextBtn, refreshBtn].forEach(fixSticky);

  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: 'dayGridMonth',
    height: 'auto',
    selectable: true,
    selectMirror: true,
    dayMaxEvents: 3,
    headerToolbar: false,
    dateClick: function(info) {
      selectedDate = info.dateStr; selectedRange = null;
      calendar.getEvents().filter(e => e.id && e.id.startsWith('sel-')).forEach(e => e.remove());
      calendar.addEvent({ id: 'sel-' + selectedDate, start: selectedDate, allDay: true, display: 'background', backgroundColor: 'rgba(0,123,255,0.12)' });
      toast('Selected: ' + selectedDate);
    },
    select: function(info) {
      selectedRange = { start: info.startStr.split('T')[0], end: info.endStr ? info.endStr.split('T')[0] : info.startStr.split('T')[0] };
      selectedDate = null;
      calendar.getEvents().filter(e => e.id && e.id.startsWith('sel-')).forEach(e => e.remove());
      toast(`Selected range: ${selectedRange.start} → ${selectedRange.end}`);
    },
    unselect: function() { selectedDate = null; selectedRange = null; calendar.getEvents().filter(e => e.id && e.id.startsWith('sel-')).forEach(e => e.remove()); const view = calendar.view; if (view) calendarTitle.textContent = view.title; },
    events: API_EVENTS,
    datesSet: function() { const view = calendar.view; if (view) calendarTitle.textContent = view.title; },
    eventDidMount: function(arg) { if (arg.el) arg.el.setAttribute('title', arg.event.title || 'Blocked'); }
  });

  calendar.render();

  prevBtn.addEventListener('click', () => calendar.prev());
  nextBtn.addEventListener('click', () => calendar.next());
  refreshBtn.addEventListener('click', () => calendar.refetchEvents());

  blockBtn.addEventListener('click', async () => {
    if (!selectedDate) return toast('Click a date first', 'error');
    try {
      const res = await fetch(API_BLOCK_SELECTED, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ date: selectedDate })});
      if (res.ok) { toast('Blocked ' + selectedDate); calendar.refetchEvents(); }
    } catch (err) { toast('Server error', 'error'); }
  });

  unblockBtn.addEventListener('click', async () => {
    if (!selectedDate) return toast('Click a date first', 'error');
    try {
      const res = await fetch(API_UNBLOCK_SELECTED, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ date: selectedDate })});
      if (res.ok) { toast('Unblocked ' + selectedDate); calendar.refetchEvents(); }
    } catch (err) { toast('Server error', 'error'); }
  });

  blockRangeBtn.addEventListener('click', async () => {
    if (!selectedRange) return toast('Drag-select a range first', 'error');
    try {
      const res = await fetch(API_TOGGLE_RANGE, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ start: selectedRange.start, end: selectedRange.end, action: 'block' })});
      if (res.ok) { toast('Blocked range'); calendar.refetchEvents(); }
    } catch (err) { toast('Server error', 'error'); }
  });

  unblockRangeBtn.addEventListener('click', async () => {
    if (!selectedRange) return toast('Drag-select a range first', 'error');
    try {
      const res = await fetch(API_TOGGLE_RANGE, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ start: selectedRange.start, end: selectedRange.end, action: 'unblock' })});
      if (res.ok) { toast('Unblocked range'); calendar.refetchEvents(); }
    } catch (err) { toast('Server error', 'error'); }
  });
});
