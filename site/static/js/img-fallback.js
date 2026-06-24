// Hide images that fail to load. Replaces inline onerror="" handlers, which
// the site CSP (script-src 'self') blocks. Loaded with defer, so the DOM is
// parsed; images may still be loading, so we both check already-failed ones
// and listen for future errors.
(function () {
  function hide(img) { img.style.display = 'none'; }
  [].slice.call(document.querySelectorAll('img')).forEach(function (img) {
    if (img.complete && img.naturalWidth === 0) hide(img);
    img.addEventListener('error', function () { hide(img); });
  });
})();
