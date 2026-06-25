// Deals page: client-side search over steals + store deal tables.
// Externalized from an inline <script> so it runs under the site CSP
// (script-src 'self'); inline scripts are blocked by design.
(function () {
  var input = document.getElementById('deal-search');
  if (!input) return;
  var wrap   = input.closest('.dealsearch');
  var clear  = document.getElementById('deal-search-clear');
  var status = document.getElementById('deal-search-status');

  var stealsWrap    = document.querySelector('.steals');
  var stealsSection = stealsWrap ? stealsWrap.closest('.section') : null;
  var rows          = [].slice.call(document.querySelectorAll('table.deals tbody tr'));
  var storeBlocks   = [].slice.call(document.querySelectorAll('.store-block'));
  var bestStore     = document.getElementById('best-store');
  var byStoreHead   = document.getElementById('bystore-head');

  // Search is JS-only — reveal it now that it can actually work.
  if (wrap) wrap.hidden = false;

  function hay(el) {
    return (el.getAttribute('data-search') || el.textContent || '').toLowerCase();
  }
  rows.forEach(function (r) { r._hay = hay(r); });

  function apply() {
    var raw = input.value.trim();
    var q = raw.toLowerCase();
    clear.hidden = raw === '';

    // Hide the curated callouts while searching — the "Best store this week"
    // banner and the Top Steals / Editor's Picks grid are highlights, not
    // search results, and they crowd out what you're looking for. Every steal
    // also appears in its store's table below, so no match is lost.
    if (bestStore) bestStore.hidden = q !== '';
    if (stealsSection) stealsSection.hidden = q !== '';
    // The "Every deal, by store" heading labels the full list; during a search
    // the list below it is just the matches, so the heading no longer fits.
    if (byStoreHead) byStoreHead.hidden = q !== '';

    if (!q) {
      rows.forEach(function (r) { r.hidden = false; });
      storeBlocks.forEach(function (b) { b.hidden = false; });
      status.hidden = true;
      return;
    }

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
