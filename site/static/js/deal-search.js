// Deals page: client-side search over steals + store deal tables.
// Externalized from an inline <script> so it runs under the site CSP
// (script-src 'self'); inline scripts are blocked by design.
(function () {
  var input = document.getElementById('deal-search');
  if (!input) return;
  var wrap   = input.closest('.dealsearch');
  var clear  = document.getElementById('deal-search-clear');
  var status = document.getElementById('deal-search-status');

  var steals        = [].slice.call(document.querySelectorAll('.steal'));
  var stealsWrap    = document.querySelector('.steals');
  var stealsSection = stealsWrap ? stealsWrap.closest('.section') : null;
  var rows          = [].slice.call(document.querySelectorAll('table.deals tbody tr'));
  var storeBlocks   = [].slice.call(document.querySelectorAll('.store-block'));
  var bestStore     = document.getElementById('best-store');

  // Search is JS-only — reveal it now that it can actually work.
  if (wrap) wrap.hidden = false;

  function hay(el) {
    return (el.getAttribute('data-search') || el.textContent || '').toLowerCase();
  }
  steals.forEach(function (s) { s._hay = hay(s); });
  rows.forEach(function (r) { r._hay = hay(r); });

  function apply() {
    var raw = input.value.trim();
    var q = raw.toLowerCase();
    clear.hidden = raw === '';

    // Tuck away the "Best store this week" callout while searching — it
    // competes with the results for attention.
    if (bestStore) bestStore.hidden = q !== '';

    if (!q) {
      steals.forEach(function (s) { s.hidden = false; });
      rows.forEach(function (r) { r.hidden = false; });
      storeBlocks.forEach(function (b) { b.hidden = false; });
      if (stealsSection) stealsSection.hidden = false;
      status.hidden = true;
      return;
    }

    var stealHits = 0;
    steals.forEach(function (s) {
      var hit = s._hay.indexOf(q) !== -1;
      s.hidden = !hit;
      if (hit) stealHits++;
    });
    if (stealsSection) stealsSection.hidden = stealHits === 0;

    var hits = 0;
    rows.forEach(function (r) {
      var hit = r._hay.indexOf(q) !== -1;
      r.hidden = !hit;
      if (hit) hits++;
    });
    storeBlocks.forEach(function (b) {
      b.hidden = b.querySelectorAll('table.deals tbody tr:not([hidden])').length === 0;
    });

    status.hidden = false;
    status.textContent = hits === 0
      ? 'No deals match “' + raw + '”.'
      : hits + (hits === 1 ? ' deal' : ' deals') + ' match “' + raw + '”.';
  }

  input.addEventListener('input', apply);
  clear.addEventListener('click', function () {
    input.value = '';
    apply();
    input.focus();
  });
})();
