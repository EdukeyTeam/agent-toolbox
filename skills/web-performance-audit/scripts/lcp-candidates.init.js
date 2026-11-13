// Init script: logs every LCP candidate, FCP and the moment a component initializes.
// Pass to `chrome-devtools navigate_page <id> --url <url> --initScript "$(cat lcp-candidates.init.js)"`,
// then read `window.__lcpLog` with evaluate_script. Edit INIT_SELECTOR to the class that marks
// the suspected component as initialized (for example a slider's `.slick-initialized`).
(() => {
  const INIT_SELECTOR = window.__lcpInitSelector || '.slick-initialized, .swiper-initialized, [data-initialized]';
  const log = { lcp: [], paint: [], componentInit: null, domContentLoaded: null };
  window.__lcpLog = log;
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) {
      log.lcp.push({
        t: Math.round(e.startTime),
        size: e.size,
        url: (e.url || '').split('/').pop().slice(0, 80),
        tag: e.element ? e.element.tagName : null,
        width: e.element ? Math.round(e.element.getBoundingClientRect().width) : null,
      });
    }
  }).observe({ type: 'largest-contentful-paint', buffered: true });
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) log.paint.push({ name: e.name, t: Math.round(e.startTime) });
  }).observe({ type: 'paint', buffered: true });
  document.addEventListener('DOMContentLoaded', () => { log.domContentLoaded = Math.round(performance.now()); });
  const observer = new MutationObserver(() => {
    if (log.componentInit === null && document.querySelector(INIT_SELECTOR)) {
      log.componentInit = Math.round(performance.now());
      observer.disconnect();
    }
  });
  observer.observe(document, { attributes: true, attributeFilter: ['class', 'data-initialized'], subtree: true, childList: true });
})();
