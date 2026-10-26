// Client side of the rendered performance report: tabs, charts (inline SVG), tooltips, to-do filters.
// Reads the report data from <script type="application/json" id="report-data">.
(() => {
  const D = JSON.parse(document.getElementById('report-data').textContent);
  const SER = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)'];
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 0) => Number(n).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const median = (a) => { const s = [...a].sort((x, y) => x - y); const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const status = (v, good, poor) => (v <= good ? 'good' : v <= poor ? 'warn' : 'poor');
  const STATUS_TEXT = { good: 'Good', warn: 'Needs improvement', poor: 'Poor' };
  const pill = (s) => `<span class="pill ${s}">${STATUS_TEXT[s]}</span>`;
  const svgEl = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (parent) parent.appendChild(e); return e; };
  const text = (parent, attrs, value) => { const t = svgEl('text', attrs, parent); t.textContent = value; return t; };
  const storeKey = 'perf-report:' + (D.meta && D.meta.url ? D.meta.url : location.pathname) + ':';
  const store = {
    get(k) { try { return localStorage.getItem(storeKey + k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(storeKey + k, v); } catch { /* storage unavailable */ } },
  };

  const tip = $('tip');
  const bindTip = (node, html) => {
    node.addEventListener('mousemove', (e) => {
      tip.innerHTML = html; tip.hidden = false;
      const r = tip.getBoundingClientRect(); let x = e.clientX + 14; let y = e.clientY + 14;
      if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
      if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 14;
      tip.style.left = x + 'px'; tip.style.top = y + 'px';
    });
    node.addEventListener('mouseleave', () => { tip.hidden = true; });
  };
  const toggleGroup = (attr, onChange) => {
    const buttons = [...document.querySelectorAll(`[${attr}]`)];
    buttons.forEach((b) => b.addEventListener('click', () => { buttons.forEach((x) => x.setAttribute('aria-pressed', String(x === b))); onChange(b.getAttribute(attr)); }));
  };
  const table = (id, head, rows) => {
    const node = $(id); if (!node) return;
    node.innerHTML = `<table><thead><tr>${head.map((h, i) => `<th${i ? ' class="num"' : ''}>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td${i ? ' class="num"' : ''}>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  };
  const legend = (id, keys) => { const n = $(id); if (n) n.innerHTML = keys.map((k, i) => `<span><i style="background:${SER[i]}"></i>${esc(k)}</span>`).join(''); };
  const niceTicks = (max) => { const step = Math.pow(10, Math.floor(Math.log10(max / 4))); const m = [1, 2, 2.5, 5, 10].find((k) => max / (k * step) <= 5) * step; const out = []; for (let t = 0; t <= max; t += m) out.push(t); return out; };

  // Tabs
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const select = (id) => {
    tabs.forEach((t) => { const on = t.getAttribute('aria-controls') === id; t.setAttribute('aria-selected', String(on)); $(t.getAttribute('aria-controls')).hidden = !on; });
    store.set('tab', id);
  };
  tabs.forEach((t) => t.addEventListener('click', () => { const id = t.getAttribute('aria-controls'); select(id); history.replaceState(null, '', '#' + id); }));
  const startTab = location.hash.slice(1) || store.get('tab');
  if (startTab && tabs.some((t) => t.getAttribute('aria-controls') === startTab)) select(startTab);

  // Horizontal bars
  const bars = (box, rows, { unit = 'ms', labelW = 210, W = 880, d = 0, color = 'var(--s1)' } = {}) => {
    if (!box) return; box.innerHTML = '';
    const R = 80, rowH = 30, H = rows.length * rowH + 4; const max = Math.max(...rows.map((r) => r[1]), 1) * 1.02;
    const x = (v) => labelW + (v / max) * (W - labelW - R);
    // role="img" hides the SVG text from screen readers, so the label carries every row and value.
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': rows.map(([k, v]) => `${k}: ${fmt(v, d)} ${unit}`).join('; ') }, box);
    rows.forEach(([k, v], i) => {
      const y = i * rowH + 4;
      text(svg, { x: 0, y: y + 14, class: 'lbl' }, k);
      svgEl('rect', { x: labelW, y, width: Math.max(x(v) - labelW, 2), height: 18, rx: 3, fill: color }, svg);
      text(svg, { x: x(v) + 6, y: y + 14, class: 'val' }, `${fmt(v, d)} ${unit}`);
      bindTip(svgEl('rect', { x: 0, y: y - 4, width: W, height: rowH, class: 'hit' }, svg), `<b>${esc(k)}</b><br><span class="mono">${fmt(v, d)} ${esc(unit)}</span>`);
    });
  };

  // Stacked horizontal bars (subparts). A row's optional `total` is the measured whole, shown instead of the
  // sum: CrUX p75 subparts are independent percentiles and do not add up to the p75 LCP.
  const stacked = (box, rows, keys, { pct = false, unit = 'ms', labelW = 230, refs = [] } = {}) => {
    if (!box) return; box.innerHTML = '';
    const W = 880, R = 74, rowH = 40, top = refs.length ? 22 : 6, H = top + rows.length * rowH + 22;
    const totals = rows.map((r) => r.v.reduce((a, b) => a + b, 0));
    const shown = rows.map((r, i) => r.total ?? totals[i]);
    const max = pct ? 100 : Math.max(...totals, ...refs.map((r) => r.v), 1) * 1.05;
    const x = (v) => labelW + (v / max) * (W - labelW - R);
    const described = rows.map((r, i) => `${r.label}: ${r.v.map((v, j) => `${keys[j]} ${fmt(v)} ${unit}`).join(', ')} (${r.total == null ? 'observed total' : 'measured'} ${fmt(shown[i])} ${unit})`);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': described.join('; ') }, box);
    (pct ? [0, 25, 50, 75, 100] : niceTicks(max)).forEach((t) => {
      svgEl('line', { x1: x(t), x2: x(t), y1: top - 2, y2: H - 20, class: 'grid' }, svg);
      text(svg, { x: x(t), y: H - 4, 'text-anchor': 'middle' }, pct ? t + '%' : fmt(t));
    });
    refs.forEach((r) => {
      svgEl('line', { x1: x(r.v), x2: x(r.v), y1: top - 6, y2: H - 20, stroke: 'var(--fg)', 'stroke-width': 1.5, 'stroke-dasharray': '4 3' }, svg);
      text(svg, { x: x(r.v) + 4, y: top - 8, class: 'val' }, r.label);
    });
    rows.forEach((r, i) => {
      const y = top + i * rowH + 6; const tot = totals[i] || 1; let acc = 0;
      // Shares of a sum of independent percentiles are meaningless, so a row with a measured total has none.
      const additive = r.total == null;
      text(svg, { x: 0, y: y + 18, class: 'lbl' }, r.label);
      if (pct && !additive) {
        text(svg, { x: labelW, y: y + 17, class: 'val' }, 'Percentiles do not add up: see Milliseconds');
        return;
      }
      r.v.forEach((v, j) => {
        const val = pct ? (v / tot) * 100 : v;
        if (val > 0) {
          const x0 = x(acc); const w = Math.max(x(acc + val) - x0 - 2, 1);
          svgEl('rect', { x: x0, y, width: w, height: 24, rx: 3, fill: SER[j] }, svg);
          bindTip(svgEl('rect', { x: x0, y: y - 4, width: Math.max(w, 6), height: 32, class: 'hit' }, svg), `<b>${esc(r.label)}</b><br>${esc(keys[j])}: <span class="mono">${fmt(v)} ${esc(unit)}</span>${additive ? ` (${fmt((v / tot) * 100)}%)` : ' (p75)'}`);
        }
        acc += val;
      });
      text(svg, { x: W - R + 8, y: y + 17, class: 'val' }, pct ? fmt((r.v[r.v.length - 1] / tot) * 100) + '%' : `${fmt(shown[i])} ${unit}`);
    });
  };

  // Lab: score tiles + dot plot per metric against thresholds
  const drawLab = (form) => {
    const lab = D.lab && D.lab[form]; if (!lab) return;
    $('score-tiles').innerHTML = Object.entries(lab.scores).map(([k, runs]) => {
      const m = median(runs); const s = m >= 90 ? 'good' : m >= 50 ? 'warn' : 'poor';
      return `<div class="tile"><span class="label">${esc(k)}</span><span class="value">${fmt(m)}</span><span class="sub">runs ${runs.map((v) => fmt(v)).join(' / ')}</span>${pill(s)}</div>`;
    }).join('');
    const box = $('lab-dots'); box.innerHTML = '';
    const names = Object.keys(lab.metrics).filter((k) => D.thresholds[k]);
    const W = 880, L = 150, R = 90, rowH = 46, H = names.length * rowH + 10;
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `Lab metrics (${form}) against thresholds` }, box);
    names.forEach((k, i) => {
      const runs = lab.metrics[k]; const [g, p] = D.thresholds[k]; const isMs = k !== 'CLS';
      const max = Math.max(p * 1.25, ...runs) * 1.02; const x = (v) => L + (v / max) * (W - L - R);
      const y = 10 + i * rowH; const cy = y + 16; const m = median(runs);
      const show = (v) => (isMs ? `${fmt(v)} ms` : v.toFixed(3));
      svgEl('rect', { x: x(0), y, width: x(g) - x(0), height: 32, fill: 'var(--band-good)', rx: 4 }, svg);
      svgEl('rect', { x: x(g), y, width: x(p) - x(g), height: 32, fill: 'var(--band-warn)' }, svg);
      svgEl('rect', { x: x(p), y, width: x(max) - x(p), height: 32, fill: 'var(--band-poor)', rx: 4 }, svg);
      text(svg, { x: 0, y: cy + 4, class: 'lbl' }, k);
      svgEl('line', { x1: x(m), x2: x(m), y1: y + 3, y2: y + 29, stroke: 'var(--fg)', 'stroke-width': 3, 'stroke-linecap': 'round' }, svg);
      runs.forEach((v, j) => {
        svgEl('circle', { cx: x(v), cy, r: 6, fill: 'var(--s1)', stroke: 'var(--surface)', 'stroke-width': 2 }, svg);
        bindTip(svgEl('circle', { cx: x(v), cy, r: 14, fill: 'transparent' }, svg), `<b>${esc(k)}, run ${j + 1}</b><br><span class="mono">${show(v)}</span><br>good &le; ${show(g)}, poor &gt; ${show(p)}`);
      });
      text(svg, { x: W - R + 10, y: cy + 4, class: 'val' }, show(m));
    });
    table('lab-table', [`Metric (${form})`, 'Median', 'Range', 'Good', 'Status'], names.map((k) => {
      const r = lab.metrics[k]; const f = (v) => (k === 'CLS' ? v.toFixed(3) : fmt(v));
      return [k, f(median(r)), `${f(Math.min(...r))} - ${f(Math.max(...r))}`, f(D.thresholds[k][0]), STATUS_TEXT[status(median(r), ...D.thresholds[k])]];
    }));
  };
  if ($('lab-dots')) { toggleGroup('data-form', drawLab); drawLab(Object.keys(D.lab)[0]); }

  // LCP subparts
  if (D.lcp && $('lcp-chart')) {
    const keys = ['TTFB', 'Load delay', 'Load duration', 'Render delay'];
    // Field rows carry the measured p75 LCP in `lcp`; a lab row's subparts come from one trace and do add up.
    const rows = D.lcp.rows.map((r) => ({ label: r.label, v: [r.ttfb, r.loadDelay, r.loadDuration, r.renderDelay], total: r.lcp }));
    legend('lcp-legend', keys);
    const draw = (mode) => stacked($('lcp-chart'), rows, keys, { pct: mode === 'pct', labelW: 250 });
    toggleGroup('data-lcpscale', draw); draw('pct');
    // Lab subparts come from the observed trace, while the scorecard's Lighthouse LCP is simulated; say which.
    table('lcp-table', ['Context', 'LCP ms (field p75 / lab observed)', ...keys, 'Render delay % (lab)'], rows.map((r) => { const t = r.v.reduce((a, b) => a + b, 0); return [r.label, fmt(r.total ?? t), ...r.v.map((v) => fmt(v)), r.total == null ? fmt((r.v[3] / t) * 100) + '%' : '-']; }));
  }

  if (D.mainThread) bars($('mt-chart'), D.mainThread, { labelW: 180, W: 600 });
  if (D.scripts) bars($('boot-chart'), D.scripts, { labelW: 220, W: 600 });

  // Third parties
  if (D.thirdParties && $('tp-chart')) {
    const tp = D.thirdParties;
    const draw = (mode) => {
      const box = $('tp-chart'); box.innerHTML = '';
      if (mode === 'main') {
        $('tp-legend').innerHTML = '<span><i style="background:var(--s1)"></i>Main-thread ms (state with most tags)</span>';
        bars(box, tp.map((t) => [t.vendor, t.mainMs]), { labelW: 230 });
        return;
      }
      $('tp-legend').innerHTML = `<span><i style="background:var(--s1)"></i>${esc(D.thirdPartyStates[0])}</span><span><i style="background:var(--s2)"></i>${esc(D.thirdPartyStates[1])}</span>`;
      const W = 880, labelW = 230, R = 80, rowH = 34, H = tp.length * rowH + 4;
      const max = Math.max(...tp.map((t) => Math.max(t.stateA_KB, t.stateB_KB)), 1) * 1.02;
      const x = (v) => labelW + (v / max) * (W - labelW - R);
      const kb = (v) => (v ? `${fmt(v)} KB` : 'not loaded');
      const label = tp.map((t) => `${t.vendor}: ${D.thirdPartyStates[0]} ${kb(t.stateA_KB)}, ${D.thirdPartyStates[1]} ${kb(t.stateB_KB)}`).join('; ');
      const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label }, box);
      tp.forEach((t, i) => {
        const y = i * rowH + 3;
        text(svg, { x: 0, y: y + 17, class: 'lbl' }, t.vendor);
        if (t.stateA_KB) svgEl('rect', { x: labelW, y, width: Math.max(x(t.stateA_KB) - labelW, 2), height: 12, rx: 3, fill: 'var(--s1)' }, svg);
        svgEl('rect', { x: labelW, y: y + 14, width: Math.max(x(t.stateB_KB) - labelW, 2), height: 12, rx: 3, fill: 'var(--s2)' }, svg);
        text(svg, { x: x(t.stateB_KB) + 6, y: y + 25, class: 'val' }, `${fmt(t.stateB_KB)} KB`);
        bindTip(svgEl('rect', { x: 0, y: y - 2, width: W, height: rowH, class: 'hit' }, svg), `<b>${esc(t.vendor)}</b><br>${esc(D.thirdPartyStates[0])}: <span class="mono">${t.stateA_KB ? fmt(t.stateA_KB) + ' KB' : 'not loaded'}</span><br>${esc(D.thirdPartyStates[1])}: <span class="mono">${fmt(t.stateB_KB)} KB</span>`);
      });
    };
    toggleGroup('data-tp', draw); draw('main');
    table('tp-table', ['Vendor', `${D.thirdPartyStates[0]} KB`, `${D.thirdPartyStates[1]} KB`, 'Main thread ms'], tp.map((t) => [t.vendor, t.stateA_KB ? fmt(t.stateA_KB) : '-', fmt(t.stateB_KB), fmt(t.mainMs)]));
  }

  // Budget
  if (D.budget && $('budget-chart')) {
    const box = $('budget-chart'); const W = 880, labelW = 210, R = 130, rowH = 36, H = D.budget.length * rowH + 24;
    const max = Math.max(...D.budget.map((b) => Math.max(b.budgetKiB, b.actualKiB))) * 1.05;
    const x = (v) => labelW + (v / max) * (W - labelW - R);
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Actual transfer size vs budget' }, box);
    niceTicks(max).forEach((t) => { svgEl('line', { x1: x(t), x2: x(t), y1: 0, y2: H - 20, class: 'grid' }, svg); text(svg, { x: x(t), y: H - 4, 'text-anchor': 'middle' }, `${fmt(t)} KiB`); });
    D.budget.forEach((b, i) => {
      const y = i * rowH + 6; const over = b.actualKiB > b.budgetKiB; const pct = fmt(((b.actualKiB - b.budgetKiB) / b.budgetKiB) * 100);
      text(svg, { x: 0, y: y + 15, class: 'lbl' }, b.resource);
      svgEl('rect', { x: labelW, y, width: Math.max(x(b.actualKiB) - labelW, 2), height: 20, rx: 3, fill: 'var(--s1)' }, svg);
      svgEl('line', { x1: x(b.budgetKiB), x2: x(b.budgetKiB), y1: y - 4, y2: y + 24, stroke: 'var(--fg)', 'stroke-width': 3, 'stroke-linecap': 'round' }, svg);
      text(svg, { x: x(Math.max(b.actualKiB, b.budgetKiB)) + 8, y: y + 15, class: 'val' }, `${fmt(b.actualKiB)} KiB ${over ? '+' + pct + '%' : 'OK'}`);
      bindTip(svgEl('rect', { x: 0, y: y - 6, width: W, height: rowH, class: 'hit' }, svg), `<b>${esc(b.resource)}</b><br>Actual <span class="mono">${fmt(b.actualKiB)} KiB</span>, budget <span class="mono">${fmt(b.budgetKiB)} KiB</span><br>${over ? 'Over budget by ' + pct + '%' : 'Within budget'}`);
    });
    table('budget-table', ['Resource', 'Budget KiB', 'Actual KiB', 'Over budget'], D.budget.map((b) => [b.resource, fmt(b.budgetKiB), fmt(b.actualKiB), b.actualKiB > b.budgetKiB ? '+' + fmt(((b.actualKiB - b.budgetKiB) / b.budgetKiB) * 100) + '%' : 'OK']));
  }

  // INP
  if (D.inp && $('inp-chart')) {
    const keys = ['Input delay', 'Processing', 'Presentation delay'];
    legend('inp-legend', keys);
    $('inp-legend').insertAdjacentHTML('beforeend', '<span><i style="background:var(--fg);width:3px;border-radius:1px"></i>200 ms good / 500 ms poor</span>');
    const rows = D.inp.rows.map((r) => ({ label: r.label, v: [r.inputDelay, r.processing, r.presentation] }));
    stacked($('inp-chart'), rows, keys, { labelW: 220, refs: [{ v: 200, label: '200' }, { v: 500, label: '500' }] });
    table('inp-table', ['Interaction', ...keys, 'Total ms'], rows.map((r) => [r.label, ...r.v.map((v) => fmt(v)), fmt(r.v.reduce((a, b) => a + b, 0))]));
  }

  if (D.memory && D.memory.retained) bars($('mem-chart'), D.memory.retained, { unit: 'MB', labelW: 270, d: 1 });

  // To-do: filters, done state, copy buttons
  const tasks = [...document.querySelectorAll('.task')];
  const progress = () => { const p = $('progress'); if (p) p.textContent = `${tasks.filter((t) => t.classList.contains('done')).length} / ${tasks.length} done`; };
  tasks.forEach((t) => {
    const cb = t.querySelector('.mark input'); if (!cb) return;
    if (store.get('done:' + t.dataset.id) === '1') { cb.checked = true; t.classList.add('done'); }
    cb.addEventListener('change', () => { t.classList.toggle('done', cb.checked); store.set('done:' + t.dataset.id, cb.checked ? '1' : '0'); progress(); });
  });
  progress();
  const chips = [...document.querySelectorAll('.chip')];
  chips.forEach((c) => c.addEventListener('click', () => {
    chips.forEach((x) => x.setAttribute('aria-pressed', String(x === c)));
    tasks.forEach((t) => { t.hidden = !(c.dataset.f === 'all' || t.dataset.p === c.dataset.f); });
  }));
  document.querySelectorAll('.code button').forEach((b) => b.addEventListener('click', async () => {
    const pre = b.nextElementSibling;
    try { await navigator.clipboard.writeText(pre.textContent); b.textContent = 'Copied'; } catch {
      const range = document.createRange(); range.selectNodeContents(pre); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range); b.textContent = 'Selected, press Ctrl+C';
    }
    setTimeout(() => { b.textContent = 'Copy'; }, 1800);
  }));
})();
