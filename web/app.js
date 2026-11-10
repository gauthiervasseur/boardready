// BoardReady: front end. Talks to app.py on 127.0.0.1.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { config: null, upload: null, file: null, personas: new Set(), actions: new Set(), job: null, timer: null };
  const CHECK = '<svg viewBox="0 0 16 16"><path d="M3 8.5 6.5 12 13 4.5" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const ICONS = {
    criticize: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><path d="M12 1.5v4M12 18.5v4M1.5 12h4M18.5 12h4"/></svg>',
    consistency: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M5 21h14M4 7h16"/><path d="M7 7 4 14a3 3 0 0 0 6 0L7 7zM17 7l-3 7a3 3 0 0 0 6 0l-3-7z"/></svg>',
    enrich: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>',
  };
  const ACTION_ACCENT = { criticize: '#B3261E', consistency: '#3C8C94', enrich: '#672A7D' };

  const remember = (k, v) => { try { localStorage.setItem('dr.' + k, JSON.stringify(v)); } catch (e) {} };
  const recall = (k, d) => { try { const v = localStorage.getItem('dr.' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } };

  const TOKEN = document.querySelector('meta[name="dr-token"]')?.content || '';
  async function api(path, body) {
    const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-DR-Token': TOKEN }, body: JSON.stringify(body) } : {});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
    return data;
  }
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const persona = (id) => state.config.personas.find((p) => p.id === id);

  // ---------- boot ----------
  async function boot() {
    state.config = await api('/api/config');
    showSettingsStatus();
    renderPersonas();
    renderActions();
    $('optSynthesis').checked = recall('synthesis', true);
    $('optPdf').checked = recall('pdf', true);
    if (!state.config.marp.available) {
      $('optPdf').checked = false; $('optPdf').disabled = true;
    }
    updateSummary();
    loadHistory();
  }

  function renderPersonas() {
    const saved = recall('personas', state.config.personas.map((p) => p.id));
    $('personaGrid').innerHTML = state.config.personas.map((p) => `
      <label class="persona" style="--accent-c:${p.accent}">
        <input type="checkbox" value="${p.id}" ${saved.includes(p.id) ? 'checked' : ''}>
        <span class="tick">${CHECK}</span>
        <img class="portrait" src="/web/portraits/${p.portrait}" alt="">
        <span class="p-name">${esc(p.name)}</span>
        <span class="p-title">${esc(p.tag)}</span>
        <span class="p-role">${esc(p.role)}</span>
        <span class="chips">${p.cares.map((c) => `<span class="chip">${esc(c)}</span>`).join('')}</span>
        <span class="p-blind"><b>Blind spot:</b> ${esc(p.blind_spot)}</span>
      </label>`).join('');
    $('personaGrid').querySelectorAll('input').forEach((i) => {
      if (i.checked) state.personas.add(i.value);
      i.addEventListener('change', () => { i.checked ? state.personas.add(i.value) : state.personas.delete(i.value); remember('personas', [...state.personas]); updateSummary(); });
    });
  }

  function renderActions() {
    const saved = recall('actions', ['criticize']);
    $('actionGrid').innerHTML = state.config.actions.map((a) => `
      <label class="action" style="--accent-c:${ACTION_ACCENT[a.id]}">
        <input type="checkbox" value="${a.id}" ${saved.includes(a.id) ? 'checked' : ''}>
        <span class="tick">${CHECK}</span>
        <span class="a-icon">${ICONS[a.id]}</span>
        <span class="a-label">${esc(a.label)}</span>
        <span class="a-blurb">${esc(a.blurb)}</span>
      </label>`).join('');
    $('actionGrid').querySelectorAll('input').forEach((i) => {
      if (i.checked) state.actions.add(i.value);
      i.addEventListener('change', () => { i.checked ? state.actions.add(i.value) : state.actions.delete(i.value); remember('actions', [...state.actions]); updateSummary(); });
    });
  }

  $('allPersonas').addEventListener('click', () => {
    const inputs = [...$('personaGrid').querySelectorAll('input')];
    const all = inputs.every((i) => i.checked);
    inputs.forEach((i) => { i.checked = !all; i.dispatchEvent(new Event('change')); });
  });
  $('optSynthesis').addEventListener('change', (e) => { remember('synthesis', e.target.checked); updateSummary(); });
  $('optPdf').addEventListener('change', (e) => remember('pdf', e.target.checked));

  function updateSummary() {
    const ps = [...state.personas], as = [...state.actions];
    const n = ps.length * as.length;
    const chairOn = $('optSynthesis').checked && n > 1;
    $('optSynthesis').disabled = n <= 1;
    $('panelFaces').innerHTML = ps.length
      ? state.config.personas.filter((p) => state.personas.has(p.id)).map((p) => `<img src="/web/portraits/${p.portrait}" alt="${esc(p.name)}" title="${esc(p.name)}">`).join('')
      : '<span class="empty">Pick at least one persona.</span>';
    const actionLabels = state.config.actions.filter((a) => state.actions.has(a.id)).map((a) => a.label);
    $('summary').innerHTML = `
      <li>Document <b>${esc(state.file?.name || '—')}</b></li>
      <li>Requests <b>${esc(actionLabels.join(', ') || '—')}</b></li>
      <li>Reviews <b>${n}${chairOn ? ' + chair' : ''}</b></li>`;
    const ready = state.config.settings.ready && state.upload && n > 0;
    $('runBtn').disabled = !ready || (state.job && state.job.state !== 'done' && state.job.state !== 'error');
    $('runBtn').textContent = n > 0 ? `Run ${n} review${n > 1 ? 's' : ''}` : 'Run the review';
    $('runHint').textContent = !state.config.settings.ready ? 'Add your API key in Settings first.'
      : !state.upload ? 'Drop a document to start.'
      : !ps.length ? 'Pick at least one persona.'
      : !as.length ? 'Pick at least one request.'
      : `The reviews run in parallel. Usually one to three minutes.`;
  }

  // ---------- settings ----------
  function showSettingsStatus() {
    const s = state.config.settings;
    const chip = $('statusChip');
    chip.classList.toggle('ok', s.ready); chip.classList.toggle('bad', !s.ready);
    $('statusText').textContent = s.ready ? `${s.model}` : 'No API key';
    chip.title = s.ready ? `${s.provider} · ${s.model} (click to change)` : 'Click to add your API key';
    $('envBanner').hidden = s.ready;
  }
  function openSettings() {
    const s = state.config.settings;
    $('setProvider').value = s.provider || 'anthropic';
    $('setModel').value = s.model || 'claude-sonnet-5-5';
    $('setKey').value = '';
    $('keyHint').textContent = s.has_key ? `A key ending ${s.key_hint || '(saved)'} is saved. Leave blank to keep it.` : 'Billed by your provider, separately from a ChatGPT or Claude subscription.';
    $('settingsWhere').textContent = `Saved on this Mac only, in ${s.env_path}`;
    $('settingsError').hidden = true;
    $('settingsModal').hidden = false;
    setTimeout(() => (s.has_key ? $('setModel') : $('setKey')).focus(), 50);
  }
  $('openSettings').addEventListener('click', openSettings);
  $('bannerSettings').addEventListener('click', openSettings);
  $('statusChip').addEventListener('click', openSettings);
  $('settingsClose').addEventListener('click', () => { $('settingsModal').hidden = true; });
  $('settingsModal').addEventListener('click', (e) => { if (e.target.id === 'settingsModal') $('settingsModal').hidden = true; });
  $('settingsForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const res = await api('/api/settings', { provider: $('setProvider').value, model: $('setModel').value, api_key: $('setKey').value });
      state.config.settings = res.settings;
      $('setKey').value = '';
      $('settingsModal').hidden = true;
      showSettingsStatus(); updateSummary();
    } catch (err) { $('settingsError').textContent = err.message; $('settingsError').hidden = false; }
  });

  // ---------- drag and drop ----------
  const dz = $('dropzone');
  let depth = 0;
  window.addEventListener('dragenter', (e) => { if (hasFiles(e)) { depth++; document.body.classList.add('dragging'); dz.classList.add('over'); } });
  window.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) { document.body.classList.remove('dragging'); dz.classList.remove('over'); } });
  window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener('drop', (e) => {
    e.preventDefault(); depth = 0; document.body.classList.remove('dragging'); dz.classList.remove('over');
    const f = e.dataTransfer?.files?.[0];
    if (f) loadFile(f);
  });
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
  $('fileInput').addEventListener('change', (e) => { if (e.target.files[0]) loadFile(e.target.files[0]); e.target.value = ''; });
  dz.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('fileInput').click(); } });
  $('replaceFile').addEventListener('click', () => $('fileInput').click());
  $('togglePreview').addEventListener('click', () => {
    const p = $('preview'); p.hidden = !p.hidden;
    $('togglePreview').textContent = p.hidden ? 'Preview text' : 'Hide text';
  });

  function readAsBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(',')[1] || '');
      r.onerror = () => reject(new Error('Could not read the file.'));
      r.readAsDataURL(file);
    });
  }

  async function loadFile(file) {
    $('fileError').hidden = true;
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!state.config.accept.includes(ext)) return showFileError(`${ext} files are not supported. Drop a Markdown, Word (.docx), Excel (.xlsx) or CSV file.`);
    if (file.size > 40 * 1024 * 1024) return showFileError('The file is larger than 40 MB.');
    dz.classList.add('busy');
    try {
      const data = await readAsBase64(file);
      showLoaded(await api('/api/extract', { name: file.name, data }), ext);
    } catch (err) {
      showFileError(err.message);
    } finally {
      dz.classList.remove('busy');
    }
  }

  async function loadSample() {
    $('fileError').hidden = true;
    try { showLoaded(await api('/api/sample', {}), '.md'); } catch (err) { showFileError(err.message); }
  }
  $('trySample').addEventListener('click', loadSample);

  function showLoaded(res, ext) {
    state.upload = res.upload; state.file = res;
    const kind = { '.md': 'md', '.markdown': 'md', '.txt': 'md', '.docx': 'docx', '.xlsx': 'xlsx', '.xlsm': 'xlsx', '.csv': 'csv' }[ext];
    $('fileType').className = `type big ${kind}`;
    $('fileType').textContent = kind.toUpperCase();
    $('fileName').textContent = res.name;
    const s = res.stats, bits = [`${res.kind}`, fmtSize(res.size), `${(s.words || 0).toLocaleString()} words`];
    if (s.sheets) bits.push(`${s.sheets} sheet${s.sheets > 1 ? 's' : ''}`);
    if (s.formulas) bits.push(`${s.formulas.toLocaleString()} formulas`);
    if (s.tables) bits.push(`${s.tables} table${s.tables > 1 ? 's' : ''}`);
    $('fileMeta').textContent = bits.join(' · ') + (res.notes.length ? ` · ${res.notes.join(' ')}` : '');
    $('preview').textContent = res.preview + (res.preview.length >= 6000 ? '\n…' : '');
    dz.hidden = true; $('fileCard').hidden = false; $('trySample').hidden = true;
    updateSummary();
  }
  function showFileError(msg) { $('fileError').textContent = msg; $('fileError').hidden = false; }
  const fmtSize = (n) => n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;

  // ---------- run ----------
  $('runBtn').addEventListener('click', async () => {
    $('runBtn').disabled = true;
    try {
      const job = await api('/api/review', {
        upload: state.upload, personas: [...state.personas], actions: [...state.actions],
        synthesis: $('optSynthesis').checked, pdf: $('optPdf').checked,
      });
      state.job = job;
      $('runCard').hidden = true; $('resultCard').hidden = true; $('progressCard').hidden = false;
      renderJob(job);
      poll();
    } catch (err) {
      $('runHint').textContent = err.message; $('runBtn').disabled = false;
    }
  });

  async function poll() {
    clearTimeout(state.timer);
    try {
      const job = await api(`/api/jobs/${state.job.id}`);
      state.job = job;
      renderJob(job);
      if (job.state === 'done' || job.state === 'error') return finish(job);
    } catch (err) { /* transient: keep polling */ }
    state.timer = setTimeout(poll, 800);
  }

  function renderJob(job) {
    const total = job.tasks.length + 1;
    const done = job.tasks.filter((t) => t.state === 'done' || t.state === 'error').length + (job.state === 'done' ? 1 : 0);
    $('barFill').style.width = `${Math.max(4, (done / total) * 100)}%`;
    $('timer').textContent = fmtTime(job.elapsed);
    $('progressTitle').textContent = job.state === 'rendering' ? 'Laying out the document…' : job.state === 'error' ? 'The review stopped' : job.state === 'done' ? 'Done' : 'Reviewing…';
    $('taskList').innerHTML = job.tasks.map((t) => {
      const p = t.persona ? persona(t.persona) : null;
      const face = p ? `<img src="/web/portraits/${p.portrait}" alt="">` : '<span class="chair">∑</span>';
      const [who, what] = t.label.split(' · ');
      const st = t.state === 'running' ? `<span class="spin" title="${fmtTime(t.seconds)}"></span>`
        : t.state === 'done' ? `✓ ${fmtTime(t.seconds)}` : t.state === 'error' ? 'Failed' : 'Waiting';
      return `<li class="${t.state}" title="${esc(t.error || '')}">${face}<span class="t-label">${esc(who)}<small>${esc(what || '')}${t.error ? ' — ' + esc(t.error) : ''}</small></span><span class="t-state">${st}</span></li>`;
    }).join('');
  }
  const fmtTime = (s) => s >= 60 ? `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, '0')}s` : `${Math.round(s)}s`;

  function finish(job) {
    loadHistory();
    if (job.state === 'error') {
      $('progressCard').hidden = false;
      $('taskList').insertAdjacentHTML('beforeend', `<li class="error"><span class="t-label">${esc(job.error)}</span></li>`);
      $('runCard').hidden = false;
      updateSummary();
      return;
    }
    setTimeout(() => {
      $('progressCard').hidden = true; $('resultCard').hidden = false;
      const o = job.outputs;
      $('resultName').textContent = o.md;
      $('resultActions').innerHTML = resultButtons(o);
      const failed = job.tasks.filter((t) => t.state === 'error').length;
      const warn = [failed ? `${failed} review${failed > 1 ? 's' : ''} failed and ${failed > 1 ? 'are' : 'is'} marked in the document.` : '', o.render_error ? `Export: ${o.render_error}` : ''].filter(Boolean).join(' ');
      $('resultWarn').hidden = !warn; $('resultWarn').textContent = warn;
    }, 450);
  }

  function resultButtons(o) {
    const b = [];
    if (o.html) b.push(`<button class="ghost featured" data-preview="${esc(o.html)}">Preview the review</button>`);
    if (o.pdf) b.push(`<button class="ghost" data-open="${esc(o.pdf)}">Open PDF</button>`);
    b.push(`<button class="ghost" data-open="${esc(o.md)}">Open Markdown</button>`);
    b.push(`<button class="ghost" data-reveal="${esc(o.md)}">Show in Finder</button>`);
    if (!state.config.native) b.push(`<a class="ghost" href="/outputs/${encodeURIComponent(o.pdf || o.md)}?download=1">Download</a>`);
    return b.join('');
  }

  $('newRun').addEventListener('click', () => {
    state.job = null; $('resultCard').hidden = true; $('progressCard').hidden = true; $('runCard').hidden = false; updateSummary();
  });

  // ---------- open, preview, history ----------
  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-open],[data-reveal],[data-preview]');
    if (!t) return;
    if (t.dataset.preview) return openPreview(t.dataset.preview);
    try { await api(t.dataset.open ? '/api/open' : '/api/reveal', { file: t.dataset.open || t.dataset.reveal }); } catch (err) { alertLine(err.message); }
  });
  function openPreview(file) {
    $('modalTitle').textContent = file;
    $('modalFrame').src = `/outputs/${encodeURIComponent(file)}`;
    $('modal').hidden = false;
  }
  $('modalClose').addEventListener('click', () => { $('modal').hidden = true; $('modalFrame').src = 'about:blank'; });
  $('modal').addEventListener('click', (e) => { if (e.target.id === 'modal') $('modalClose').click(); });
  document.addEventListener('keydown', (e) => { if (e.key !== 'Escape') return; if (!$('modal').hidden) $('modalClose').click(); $('settingsModal').hidden = true; });
  $('openFolder').addEventListener('click', () => api('/api/open-folder', {}));
  const alertLine = (m) => { $('runHint').textContent = m; };

  async function loadHistory() {
    const { items } = await api('/api/history').catch(() => ({ items: [] }));
    $('history').innerHTML = items.length ? items.map((i) => `
      <li><span class="h-main"><span class="h-title" title="${esc(i.md)}">${esc(i.title)}</span><span class="h-date">${esc(i.modified)}</span></span>
        ${i.html ? `<button data-preview="${esc(i.html)}">View</button>` : ''}
        ${i.pdf ? `<button data-open="${esc(i.pdf)}">PDF</button>` : ''}
        <button data-open="${esc(i.md)}">MD</button></li>`).join('')
      : '<li class="fine">None yet.</li>';
  }

  boot().then(() => { if (location.hash === '#sample') loadSample(); if (location.hash === '#settings') openSettings(); }).catch((err) => { $('statusText').textContent = 'Server error'; console.error(err); });
})();
