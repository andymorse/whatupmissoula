// YMCA page: one day at a time + a section filter (Pool / Classes / …).
// External file so it runs under the site CSP (script-src 'self'). Without JS
// the page still works — it's just every day in order.
(function () {
  var dayBar = document.getElementById('ymca-days');
  var secBar = document.getElementById('ymca-sections');
  if (!dayBar || !secBar) return;

  function iso(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') +
      '-' + String(d.getDate()).padStart(2, '0');
  }
  var now = new Date();
  var today = iso(now);
  var tomorrow = iso(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));

  // Past days are just noise. If the page has gone stale (every day is past),
  // keep them all rather than show nothing.
  var days = [].slice.call(document.querySelectorAll('.ymca-day'));
  var upcoming = days.filter(function (d) { return d.dataset.date >= today; });
  if (upcoming.length) {
    days.forEach(function (d) { if (d.dataset.date < today) d.remove(); });
    days = upcoming;
  }
  days = days.slice(0, 7);
  [].slice.call(document.querySelectorAll('.ymca-day')).forEach(function (d) {
    if (days.indexOf(d) === -1) d.remove();
  });

  var dayChips = days.map(function (d) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'tagchip';
    b.textContent = d.dataset.date === today ? 'Today'
      : d.dataset.date === tomorrow ? 'Tomorrow' : d.dataset.short;
    b.addEventListener('click', function () { pickDay(d); });
    dayBar.appendChild(b);
    // Each day gets an empty-state line for when the filter hides everything.
    var empty = document.createElement('p');
    empty.className = 'order-note ymca-empty';
    empty.hidden = true;
    d.appendChild(empty);
    return b;
  });
  var secChips = [].slice.call(secBar.querySelectorAll('.tagchip'));

  var KEY = 'wum-ymca-section';
  var section = '';
  try { section = localStorage.getItem(KEY) || ''; } catch (e) {}
  if (!secChips.some(function (c) { return c.dataset.section === section; })) section = '';

  function apply() {
    secChips.forEach(function (c) {
      c.classList.toggle('active', c.dataset.section === section);
    });
    days.forEach(function (d) {
      var shown = 0;
      [].slice.call(d.querySelectorAll('.ymca-sec')).forEach(function (s) {
        s.hidden = section !== '' && s.dataset.section !== section;
        if (!s.hidden) shown++;
      });
      var empty = d.querySelector('.ymca-empty');
      empty.hidden = shown > 0;
      empty.textContent = 'Nothing in ' + section + ' this day.';
    });
  }

  function pickDay(day) {
    days.forEach(function (d, i) {
      d.hidden = d !== day;
      dayChips[i].classList.toggle('active', d === day);
    });
  }

  secChips.forEach(function (c) {
    c.addEventListener('click', function () {
      section = c.dataset.section;
      try { localStorage.setItem(KEY, section); } catch (e) {}
      apply();
    });
  });

  // Today: grey out what's already over and mark what's happening now.
  function markNow() {
    var d = days[0];
    if (!d || d.dataset.date !== iso(new Date())) return;
    var t = new Date();
    var mins = t.getHours() * 60 + t.getMinutes();
    [].slice.call(d.querySelectorAll('.ymca-row')).forEach(function (r) {
      var s = +r.dataset.start, e = +r.dataset.end;
      r.classList.toggle('is-past', e <= mins);
      r.classList.toggle('is-now', s <= mins && mins < e);
    });
  }

  dayBar.hidden = false;
  secBar.hidden = false;
  apply();
  if (days.length) pickDay(days[0]);
  markNow();
  setInterval(markNow, 60000);
})();
