// Events page: client-side search + clickable filter chips / tag badges.
// Externalized from an inline <script> so it runs under the site CSP
// (script-src 'self'); inline scripts are blocked by design.
(function () {
  var input  = document.getElementById('event-search');
  if (!input) return;
  var wrap   = input.closest('.dealsearch');
  var clear  = document.getElementById('event-search-clear');
  var status = document.getElementById('event-search-status');
  var tagbar = document.getElementById('event-tagbar');
  var cards  = [].slice.call(document.querySelectorAll('.event'));
  var chips  = tagbar ? [].slice.call(tagbar.querySelectorAll('.tagchip')) : [];

  // Search + filter chips are JS-only — reveal them now that they work.
  if (wrap) wrap.hidden = false;
  if (tagbar) tagbar.hidden = false;
  cards.forEach(function (c) {
    c._hay = (c.getAttribute('data-search') || c.textContent || '').toLowerCase();
  });

  function apply() {
    var raw = input.value.trim();
    var q = raw.toLowerCase();
    clear.hidden = raw === '';
    // Light up whichever chip matches the active query.
    chips.forEach(function (chip) {
      chip.classList.toggle('active',
        q !== '' && chip.getAttribute('data-q').toLowerCase() === q);
    });

    if (!q) {
      cards.forEach(function (c) { c.hidden = false; });
      status.hidden = true;
      return;
    }
    var hits = 0;
    cards.forEach(function (c) {
      var hit = c._hay.indexOf(q) !== -1;
      c.hidden = !hit;
      if (hit) hits++;
    });
    status.hidden = false;
    status.textContent = hits === 0
      ? 'No events match “' + raw + '”.'
      : hits + (hits === 1 ? ' event' : ' events') + ' match “' + raw + '”.';
  }

  function setQuery(q) {
    // Clicking the already-active tag clears it (toggle off).
    input.value = (input.value.trim().toLowerCase() === q.toLowerCase()) ? '' : q;
    apply();
  }

  input.addEventListener('input', apply);
  clear.addEventListener('click', function () { input.value = ''; apply(); input.focus(); });

  // Clickable filter chips and on-card tag badges (anything with data-q).
  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-q]');
    if (!el) return;
    e.preventDefault();
    setQuery(el.getAttribute('data-q'));
    // If triggered from a badge deep in the list, scroll the search into view.
    if (el.closest('.event') && wrap) {
      wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
})();
