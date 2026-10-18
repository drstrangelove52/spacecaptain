/*
 * Modul «Inventar» für den LabManager (Lagerorte, Möbel, Werkzeug, Etiketten).
 * Wird von labmanager.html beim ersten Öffnen nachgeladen (LabModules) und nutzt dessen
 * Helfer: GET/POST/PATCH/DELETE, apiSilent, showToast, escHtml, openModal/closeModal,
 * currentUser, _isPowerPlus(). Alle Namen liegen im Namensraum `Inv`.
 * Konzept: docs/inventar-konzept.md
 */
(function () {
  'use strict';

  const KIND = { schrank: '🗄️ Schrank', regal: '📚 Regal', wand: '🔨 Werkzeugwand', tisch: '🪵 Tisch / Werkbank', bereich: 'Im Bereich' };
  const PAGE = 100;
  const $ = (id) => document.getElementById('inv-' + id);
  const esc = (s) => escHtml(s);
  const pad2 = (n) => String(n).padStart(2, '0');          // Nummern im Code sind immer zweistellig
  const isPower = () => _isPowerPlus();

  let root = null;
  let tree = [];
  let itemsPage = 0, itemsCache = {};
  let chips = { unplaced: false, level_open: false };
  let editingItemId = null, editingAreaId = null, editingFurnId = null;
  let labelData = [], labelOutdatedOnly = false;
  let selected = new Map(), selInit = false, pendingSel = null, lastPrinted = [];   // selected: Etikett-Code → Anzahl
  let labelMode = 'furn', toolList = [], toolSel = new Map();   // Etikettenart; Werkzeug: id → Kopien
  let activeTab = 'items';
  const openAreas = new Set(), openFurn = new Set();
  let _deb = null;

  // ═══════════════════════════════════════════════════════
  // Styles (alles mit Präfix inv-, damit nichts im LabManager kollidiert)
  // ═══════════════════════════════════════════════════════
  /* gemeinsame Styles der Etiketten (Vorschau und Druckfenster) */
  const LABEL_CSS = `
  .inv-lbl{box-sizing:border-box;background:#fff;color:#000;display:flex;gap:1.5mm;align-items:center;overflow:hidden;break-inside:avoid;page-break-inside:avoid;width:var(--lw);height:var(--lh)}
  .inv-lbl.free{border:1px solid #888;border-top:5px solid var(--cc,#888);padding:1.5mm 2mm}
  .inv-lbl.free img{height:calc(var(--lh) - 6mm);width:calc(var(--lh) - 6mm)}
  .inv-lbl.sheet{position:absolute;border:0;border-top:1mm solid var(--cc,#888);padding:.8mm 1.5mm .5mm}
  .inv-lbl.sheet img{height:calc(var(--lh) - 3.2mm);width:calc(var(--lh) - 3.2mm)}
  .inv-lbl img{flex:none;image-rendering:pixelated}
  .inv-lbl .t{min-width:0;display:flex;flex-direction:column;gap:.4mm}
  .inv-lbl .c{font-family:'Share Tech Mono','Consolas','Courier New',monospace;font-weight:700;line-height:1.05;white-space:nowrap}
  .inv-lbl .n{font-size:calc(var(--lh) * .15);line-height:1.12;overflow:hidden;overflow-wrap:anywhere}
  .inv-lbl .n .ct{color:#222}
  .inv-lbl .a{font-size:calc(var(--lh) * .12);color:#444}
  .inv-lbl.tool .n{font-weight:700;line-height:1.1;overflow:hidden;overflow-wrap:anywhere;max-height:none;flex:0 1 auto}
  .inv-lbl.tool .c{font-weight:400;color:#222}
  .inv-sheet{position:relative;width:210mm;height:297mm;background:#fff;overflow:hidden;break-after:page;page-break-after:always}
  .inv-cal{position:absolute;box-sizing:border-box;border:.2mm solid #000;font:2.6mm Arial,sans-serif;color:#000;padding:.6mm 1mm}
  .inv-cal b{display:block;font-size:3.6mm}
  `;

  const CSS = `
  #page-inventory .inv-tabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--border);margin-bottom:18px}
  #page-inventory .inv-tab{padding:10px 18px;cursor:pointer;color:var(--text-mid);font-weight:600;border-bottom:2px solid transparent;margin-bottom:-1px}
  #page-inventory .inv-tab:hover{color:var(--text);background:var(--hover-subtle)}
  #page-inventory .inv-tab.active{color:var(--accent);border-bottom-color:var(--accent)}
  #page-inventory .inv-page{display:none}#page-inventory .inv-page.active{display:block}
  #page-inventory .inv-toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
  #page-inventory .inv-toolbar .search-wrap{flex:2;min-width:220px}
  #page-inventory .inv-toolbar select{flex:1;min-width:140px;width:auto}
  #page-inventory .inv-chip{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border:1px solid var(--border);border-radius:99px;cursor:pointer;font-size:15px;color:var(--text-mid);user-select:none}
  #page-inventory .inv-chip.on{border-color:var(--accent);color:var(--accent);background:color-mix(in srgb,var(--accent) 10%,transparent)}
  #page-inventory .inv-code,.inv-code{display:inline-block;font-family:var(--mono);font-size:14px;padding:2px 8px;border-radius:4px;border:1px solid var(--cc,var(--border));background:color-mix(in srgb,var(--cc,var(--accent2)) 14%,transparent);color:var(--text);white-space:nowrap}
  #page-inventory .inv-dim{color:var(--text-dim)}#page-inventory .inv-small{font-size:14px}
  #page-inventory .inv-empty{text-align:center;color:var(--text-dim);padding:40px 10px}
  #page-inventory .inv-hint{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:10px 14px;font-size:15px;color:var(--text-mid);margin-bottom:14px}
  #page-inventory .inv-hint b{color:var(--text)}
  #page-inventory .inv-card{background:var(--surface);border:1px solid var(--border);border-radius:6px;margin-bottom:12px}
  #page-inventory .inv-card-h{display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;flex-wrap:wrap}
  #page-inventory .inv-card-h .inv-name{font-weight:700;font-size:18px}
  #page-inventory .inv-card-b{padding:4px 14px 12px;border-top:1px solid var(--border)}
  #page-inventory .inv-swatch{width:12px;height:12px;border-radius:3px;background:var(--cc,var(--accent2));flex:none}
  #page-inventory .inv-furn{border-left:3px solid var(--cc,var(--border));margin:10px 0 0 4px;padding:2px 0 2px 12px}
  #page-inventory .inv-furn-h{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:4px 0;cursor:pointer}
  #page-inventory .inv-lvl{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:3px 0 3px 18px;border-top:1px dashed var(--border)}
  #page-inventory .inv-pos{display:inline-flex;align-items:center;gap:4px;margin:2px 4px 2px 0;padding:1px 6px;border:1px solid var(--border);border-radius:4px;font-size:13px;font-family:var(--mono)}
  #page-inventory .inv-sp{flex:1}
  #page-inventory .inv-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  #page-inventory .inv-pager{display:flex;gap:10px;align-items:center;margin-top:10px}
  #page-inventory .inv-lbl-grid{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
  .inv-loc-box{border:1px solid var(--border);border-radius:6px;padding:10px 12px;background:var(--surface2)}
  .inv-loc-box .form-row{margin-top:8px}
  #page-inventory .inv-labelopts{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px}
  #page-inventory .inv-labelopts .form-group{margin:0}
  #page-inventory .inv-labelopts input[type=number]{width:96px}
  #page-inventory .inv-sheetrow{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;margin-top:12px}
  #page-inventory .inv-sheetwrap{position:relative;flex:none;box-shadow:0 2px 12px rgba(0,0,0,.35);background:#fff;overflow:hidden}
  #page-inventory .inv-sheetwrap .inv-sheet{transform-origin:0 0}
  #page-inventory .inv-sheetwrap .inv-lbl{outline:.2mm dashed #c4c4c4}
  #page-inventory .inv-sheetwrap .inv-lbl.skip{outline:.2mm dashed #e0b4b4;background:repeating-linear-gradient(45deg,#fff,#fff 1mm,#f1e6e6 1mm,#f1e6e6 2mm)}
  #page-inventory .inv-freegrid{display:flex;flex-wrap:wrap;gap:2mm;margin-top:12px}
  #page-inventory .inv-sel-box{border:1px solid var(--border);border-radius:6px;background:var(--surface);margin-bottom:12px}
  #page-inventory .inv-sel-head{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:8px 12px;border-bottom:1px solid var(--border)}
  #page-inventory .inv-sel-list{max-height:300px;overflow:auto}
  #page-inventory .inv-sel-row{display:flex;align-items:center;gap:10px;padding:5px 12px;cursor:pointer;margin:0;font-size:15px}
  #page-inventory .inv-sel-row.level{padding-left:44px}
  #page-inventory .inv-sel-row.pos{padding-left:76px}
  #page-inventory .inv-sel-row input.inv-copies{width:74px}
  #page-inventory .inv-sel-ct{flex:1;min-width:0;color:var(--text-dim);font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #page-inventory .inv-sel-row:hover{background:var(--hover-subtle)}
  #page-inventory .inv-sel-row input{width:auto;margin:0}
  ${LABEL_CSS}
`;

  function ensureStyle() {
    if (document.getElementById('inv-style')) return;
    const st = document.createElement('style');
    st.id = 'inv-style';
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  // ═══════════════════════════════════════════════════════
  // Gerüst
  // ═══════════════════════════════════════════════════════
  function mount(el) {
    root = el;
    ensureStyle();
    el.innerHTML = `
    <div class="inv-tabs">
      <div class="inv-tab active" data-tab="items" onclick="Inv.showTab('items')">🔧 Werkzeug</div>
      <div class="inv-tab" data-tab="structure" onclick="Inv.showTab('structure')">🗄️ Struktur</div>
      <div class="inv-tab" data-tab="labels" onclick="Inv.showTab('labels')">🏷️ Etiketten</div>
      <div class="inv-tab" data-tab="import" onclick="Inv.showTab('import')">📥 Import</div>
    </div>

    <div class="inv-page active" id="inv-page-items">
      <div id="inv-code-banner" class="inv-hint" style="display:none"></div>
      <div class="inv-toolbar">
        <div class="search-wrap"><span class="search-icon">🔍</span>
          <input class="search-input" id="inv-f-q" placeholder="Name, Synonym oder Code (z.B. Akkuschrauber, ELE-M02)…" oninput="Inv.debouncedLoadItems()"></div>
        <select class="filter-input" id="inv-f-area" onchange="Inv.reloadItems()"></select>
        <select class="filter-input" id="inv-f-status" onchange="Inv.reloadItems()">
          <option value="">Alle Status</option><option value="aktiv">aktiv</option><option value="defekt">defekt</option><option value="ausgemustert">ausgemustert</option>
        </select>
        <span class="inv-chip" id="inv-chip-unplaced" onclick="Inv.toggleChip('unplaced')">Ohne Platz</span>
        <span class="inv-chip" id="inv-chip-level_open" onclick="Inv.toggleChip('level_open')" title="Im Möbel, aber Ebene noch nicht festgelegt (E00)">Ebene offen</span>
        <button class="btn btn-primary" onclick="Inv.openItemModal()">+ Werkzeug</button>
      </div>
      <div class="table-wrap" style="margin-bottom:0">
        <table><thead><tr><th>Name</th><th>Menge</th><th>Lagerort</th><th>Status</th><th></th></tr></thead>
        <tbody id="inv-items-body"></tbody></table>
      </div>
      <div class="inv-pager"><span class="inv-dim inv-small" id="inv-items-count"></span><span class="inv-sp"></span>
        <button class="btn btn-ghost btn-sm" id="inv-btn-prev" onclick="Inv.pageItems(-1)">‹ zurück</button>
        <button class="btn btn-ghost btn-sm" id="inv-btn-next" onclick="Inv.pageItems(1)">weiter ›</button></div>
    </div>

    <div class="inv-page" id="inv-page-structure">
      <div class="inv-hint">
        <b>Code:</b> Bereich, Möbel, Ebene, Position, z.B. <code>ELE-M02-E03-P04</code> = Elektronik, Möbel 2, Ebene 3, Platz 4.
        «Möbel» ist ein Schrank, Regal, eine Werkzeugwand oder ein Tisch. Das Kürzel des Bereichs hat <b>genau 3 Zeichen</b>, alle Nummern sind <b>zweistellig</b>.
        Ebenen zählen <b>von oben nach unten</b>, Positionen <b>von links nach rechts</b>.
        Die <b>00</b> heisst «nicht unterteilt oder noch nicht festgelegt» (<code>M00</code> = im Bereich ohne Möbel,
        <code>E00</code> = Ebene offen, <code>P00</code> = kein fester Platz). Auf Etiketten entfallen abschliessende Nullen.
      </div>
      <div class="inv-toolbar" id="inv-structure-tools"></div>
      <div id="inv-structure-list"></div>
    </div>

    <div class="inv-page" id="inv-page-labels">
      <div class="inv-toolbar">
        <span class="inv-chip on" id="inv-mode-furn" onclick="Inv.setLabelMode('furn')">🗄️ Möbel &amp; Ebenen</span>
        <span class="inv-chip" id="inv-mode-tool" onclick="Inv.setLabelMode('tool')" title="Ein Etikett pro Stück, z.B. für jedes Lineal">🔧 Werkzeug</span>
      </div>
      <div class="inv-sel-box" id="inv-furn-box">
        <div class="inv-sel-head">
          <b id="inv-sel-count">0 gewählt</b>
          <select class="filter-input" id="inv-l-area" onchange="Inv.loadLabels()" style="width:auto;min-width:150px"></select>
          <span class="inv-chip" id="inv-chip-outdated" onclick="Inv.toggleOutdated()" title="Liste auf Möbel beschränken, deren Etikett neu oder veraltet ist">Liste: nur neue/veraltete</span>
          <span class="inv-sp"></span>
          <button class="btn btn-ghost btn-sm" onclick="Inv.selectBy('all')">Alle</button>
          <button class="btn btn-ghost btn-sm" onclick="Inv.selectBy('none')">Keine</button>
          <button class="btn btn-ghost btn-sm" onclick="Inv.selectBy('outdated')" title="Neue Möbel und solche, deren Code sich geändert hat">Neue/veraltete</button>
          <button class="btn btn-ghost btn-sm" onclick="Inv.selectBy('furn')">Nur Möbel</button>
          <button class="btn btn-ghost btn-sm" onclick="Inv.selectBy('level')">Nur Ebenen</button>
          <button class="btn btn-ghost btn-sm" onclick="Inv.selectBy('pos')" title="Etiketten für einzelne Plätze (P1, P2 …) mit dem, was dort liegt">Nur Positionen</button>
        </div>
        <div class="inv-sel-list" id="inv-sel-list"></div>
      </div>
      <div class="inv-sel-box" id="inv-tool-box" style="display:none">
        <div class="inv-sel-head">
          <b id="inv-tl-count">0 gewählt</b>
          <div class="search-wrap" style="flex:1;min-width:180px"><span class="search-icon">🔍</span>
            <input class="search-input" id="inv-tl-q" placeholder="Werkzeug suchen…" oninput="Inv.debouncedToolLoad()" style="width:100%;min-width:0"></div>
          <button class="btn btn-ghost btn-sm" onclick="Inv.toolSelectAll()">Alle angezeigten</button>
          <button class="btn btn-ghost btn-sm" onclick="Inv.toolSelectNone()">Keine</button>
          <button class="btn btn-ghost btn-sm" onclick="Inv.toolCopiesQty()" title="Kopien der gewählten auf die erfasste Menge setzen">Kopien = Menge</button>
        </div>
        <div class="inv-hint" style="margin:0;border:0;border-bottom:1px solid var(--border);border-radius:0">
          Ein Etikett <b>pro Stück</b>: «Lineal 30 cm», Menge 12 → 12 Kopien. Auf dem Etikett stehen Name und Heimatort; der QR-Code zeigt, <b>wohin das Werkzeug gehört</b> (bleibt gültig, auch wenn es umgelagert wird).
        </div>
        <div class="inv-sel-list" id="inv-tl-list"></div>
      </div>
      <div class="inv-labelopts">
        <div class="form-group"><label class="form-label">Vorlage</label>
          <select class="form-input" id="inv-l-tpl" onchange="Inv.setTemplate()"></select></div>
        <div class="form-group inv-sheet-only"><label class="form-label" title="Für angebrochene Bögen: das erste freie Etikett">Beginnen bei Nr.</label>
          <input class="form-input" id="inv-l-start" type="number" min="1" value="1" onchange="Inv.renderLabels()"></div>
        <div class="form-group inv-sheet-only"><label class="form-label" title="Korrektur, falls der Druck leicht verschoben ist (+ = nach rechts)">Versatz X (mm)</label>
          <input class="form-input" id="inv-l-offx" type="number" step="0.1" value="0" onchange="Inv.offsetChanged()"></div>
        <div class="form-group inv-sheet-only"><label class="form-label" title="+ = nach unten">Versatz Y (mm)</label>
          <input class="form-input" id="inv-l-offy" type="number" step="0.1" value="0" onchange="Inv.offsetChanged()"></div>
        <button class="btn btn-ghost inv-sheet-only" onclick="Inv.printCalibration()" title="Raster auf normales Papier drucken und gegen das Licht über einen Etikettenbogen halten">📐 Testbogen</button>
        <button class="btn btn-primary" id="inv-btn-print" onclick="Inv.printLabels()">🖨️ Auswahl drucken</button>
      </div>
      <div class="inv-hint" id="inv-l-hint"></div>
      <div class="inv-sheetrow" id="inv-labels-preview"></div>
      <div style="margin-top:14px" id="inv-mark-wrap"><button class="btn btn-ghost" onclick="Inv.markPrinted()" title="Setzt bei den gewählten Möbeln das Kennzeichen «neu/veraltet» zurück">✓ Auswahl als gedruckt markieren</button></div>
    </div>

    <div class="inv-page" id="inv-page-import">
      <div class="inv-hint">
        Eine Zeile pro Werkzeug: <code>Name ; Synonyme ; Code ; Menge</code> (Trennzeichen <code>;</code> oder Tab —
        Zeilen aus Excel lassen sich direkt einfügen). Synonyme, Code und Menge sind optional.
        Der Code darf gekürzt sein: <code>ELE-M02</code> = Elektronik, Möbel 2, Ebene offen. Ohne Code wird das Werkzeug
        «ohne Platz» angelegt und kann später zugeordnet werden.
      </div>
      <textarea class="form-input" id="inv-import-text" style="min-height:220px;font-family:var(--mono);font-size:14px"
        placeholder="Akkuschrauber ; Bohrschrauber, Schrauber ; ELE-M01-E02 ; 2&#10;Seitenschneider ; Zange ; ELE-M02&#10;Hammer"></textarea>
      <div class="inv-row" style="margin-top:10px">
        <button class="btn btn-ghost" onclick="Inv.runImport(true)">Prüfen (nichts speichern)</button>
        <button class="btn btn-primary" onclick="Inv.runImport(false)">Importieren</button>
      </div>
      <div id="inv-import-result" style="margin-top:14px"></div>
    </div>`;
    initLabelControls();
  }

  async function show() {
    await loadTree();
    fillAreaSelect($('f-area'), 'Alle Bereiche');
    fillAreaSelect($('l-area'), 'Alle Bereiche');
    // Einsprung über QR-Code / Link: #inventory/ELE-M01
    const iid = window._invItem;
    if (iid) {                                   // QR-Code eines Werkzeug-Etiketts: «gehört nach …»
      window._invItem = null;
      const it = await GET('/inventory/items/' + iid);
      if (it) {
        $('f-q').value = it.position ? it.position.code : it.name;
        itemsPage = 0;
        showTab('items');
        const b = $('code-banner');
        b.style.display = 'block';
        b.innerHTML = it.position
          ? `<b>${esc(it.name)}</b> gehört nach <span class="inv-code" style="--cc:${esc(it.position.color || '#22d3ee')}">${esc(it.position.code)}</span> · ${esc(it.position.path)} · <a href="#" onclick="Inv.clearBanner();return false">Filter aufheben</a>`
          : `<b>${esc(it.name)}</b> hat noch keinen Lagerort · <a href="#" onclick="Inv.clearBanner();return false">Filter aufheben</a>`;
        return;
      }
    }
    const code = window._invCode;
    if (code) {
      window._invCode = null;
      $('f-q').value = code;
      itemsPage = 0;
      showTab('items');
      const b = $('code-banner');
      b.style.display = 'block';
      b.innerHTML = `Inhalt von <code>${esc(code)}</code> · <a href="#" onclick="Inv.clearBanner();return false">Filter aufheben</a>`;
    } else {
      showTab(activeTab);
    }
  }
  function clearBanner() { $('code-banner').style.display = 'none'; $('f-q').value = ''; reloadItems(); }

  function showTab(name) {
    activeTab = name;
    root.querySelectorAll('.inv-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    root.querySelectorAll('.inv-page').forEach(p => p.classList.toggle('active', p.id === 'inv-page-' + name));
    if (name === 'items') loadItems();
    if (name === 'structure') renderStructure();
    if (name === 'labels') loadLabels();
  }

  async function loadTree() {
    const t = await GET('/inventory/tree');
    if (t) tree = t;
    return tree;
  }
  function fillAreaSelect(sel, firstLabel) {
    const cur = sel.value;
    sel.innerHTML = `<option value="">${esc(firstLabel)}</option>` +
      tree.map(a => `<option value="${a.id}">${esc(a.name)}${a.code ? ` (${esc(a.code)})` : ''}</option>`).join('');
    sel.value = cur;
  }
  async function refreshAll() {
    await loadTree();
    fillAreaSelect($('f-area'), 'Alle Bereiche');
    fillAreaSelect($('l-area'), 'Alle Bereiche');
    renderStructure();
  }

  // ═══════════════════════════════════════════════════════
  // Werkzeug
  // ═══════════════════════════════════════════════════════
  function debouncedLoadItems() { clearTimeout(_deb); _deb = setTimeout(() => { itemsPage = 0; loadItems(); }, 250); }
  function reloadItems() { itemsPage = 0; loadItems(); }
  function toggleChip(k) { chips[k] = !chips[k]; $('chip-' + k).classList.toggle('on', chips[k]); reloadItems(); }
  function pageItems(d) { itemsPage = Math.max(0, itemsPage + d); loadItems(); }

  function codeChip(pos) {
    if (!pos) return '<span class="badge badge-red">ohne Platz</span>';
    return `<span class="inv-code" style="--cc:${esc(pos.color || '#22d3ee')}" title="${esc(pos.path)}">${esc(pos.code)}</span>
            <div class="inv-dim inv-small">${esc(pos.path)}</div>`;
  }

  async function loadItems() {
    const q = $('f-q').value.trim();
    const p = new URLSearchParams({ limit: PAGE, offset: itemsPage * PAGE });
    if (q) p.set('q', q);
    const area = $('f-area').value; if (area) p.set('area_id', area);
    const st = $('f-status').value; if (st) p.set('status', st);
    if (chips.unplaced) p.set('unplaced', 'true');
    if (chips.level_open) p.set('level_open', 'true');
    const r = await GET('/inventory/items?' + p);
    if (!r) return;
    itemsCache = Object.fromEntries(r.items.map(i => [i.id, i]));
    $('items-body').innerHTML = r.items.length ? r.items.map(i => `
      <tr>
        <td><b>${esc(i.name)}</b>${i.synonyms ? `<div class="inv-dim inv-small">${esc(i.synonyms)}</div>` : ''}</td>
        <td class="inv-mono" style="font-family:var(--mono)">${i.quantity}</td>
        <td>${codeChip(i.position)}</td>
        <td>${i.status === 'aktiv' ? '<span class="inv-dim">aktiv</span>' : `<span class="badge badge-red">${esc(i.status)}</span>`}</td>
        <td style="white-space:nowrap">
          <button class="btn btn-ghost btn-sm" onclick="Inv.openItemModal(${i.id})" title="Bearbeiten">✏️</button>
          <button class="btn btn-danger btn-sm" onclick="Inv.deleteItem(${i.id})" title="Löschen">🗑</button>
        </td>
      </tr>`).join('') : `<tr><td colspan="5" class="inv-empty">Keine Werkzeuge gefunden.</td></tr>`;
    const from = r.total ? itemsPage * PAGE + 1 : 0, to = Math.min(r.total, (itemsPage + 1) * PAGE);
    $('items-count').textContent = `${from}–${to} von ${r.total}`;
    $('btn-prev').disabled = itemsPage === 0;
    $('btn-next').disabled = to >= r.total;
  }

  async function deleteItem(id) {
    const name = itemsCache[id] ? itemsCache[id].name : 'Eintrag';
    if (!confirm(`«${name}» wirklich löschen?`)) return;
    if (await DELETE('/inventory/items/' + id)) { showToast('Gelöscht', 'success'); await loadTree(); loadItems(); }
  }

  // ── Lagerort-Auswahl (Bereich → Möbel → Ebene → Position) ──
  const areaById = (id) => tree.find(a => a.id == id);
  function furnLabel(f) {
    if (f.number === 0) return 'Im Bereich, ohne Möbel (M00)';
    return `${f.name || ((KIND[f.kind] || 'Möbel').replace(/^\S+\s/, '') + ' ' + f.number)} (M${pad2(f.number)})`;
  }
  const lvlLabel = (l) => l.number === 0 ? 'Ebene offen / nicht unterteilt (E00)' : `${l.label || 'Ebene ' + l.number} (E${pad2(l.number)})`;
  const posLabel = (p) => p.number === 0 ? 'kein fester Platz (P00)' : `${p.label || 'Platz ' + p.number} (P${pad2(p.number)})`;

  function fillLocSelects(sel) {
    const aSel = $('i-area');
    aSel.innerHTML = '<option value="">— kein Platz —</option>' +
      tree.map(a => `<option value="${a.id}" ${a.code ? '' : 'disabled'}>${esc(a.name)}${a.code ? ` (${esc(a.code)})` : ' — Kürzel fehlt'}</option>`).join('');
    aSel.value = sel.area || '';
    const a = areaById(aSel.value);
    const fSel = $('i-furn'), lSel = $('i-lvl'), pSel = $('i-pos');
    [fSel, lSel, pSel].forEach(s => { s.innerHTML = ''; s.disabled = !a; });
    if (!a) { syncCodeField(); return; }
    fSel.innerHTML = a.furniture.map(f => `<option value="${f.id}">${esc(furnLabel(f))}</option>`).join('');
    fSel.value = sel.furn || (a.furniture.find(f => f.number > 0) || a.furniture[0]).id;
    const f = a.furniture.find(x => x.id == fSel.value);
    lSel.innerHTML = f.levels.map(l => `<option value="${l.id}">${esc(lvlLabel(l))}</option>`).join('');
    lSel.value = sel.lvl || f.levels.find(l => l.number === 0).id;
    const l = f.levels.find(x => x.id == lSel.value);
    pSel.innerHTML = l.positions.map(p => `<option value="${p.id}">${esc(posLabel(p))}</option>`).join('');
    pSel.value = sel.pos || l.positions.find(p => p.number === 0).id;
    syncCodeField();
  }
  const locAreaChanged = () => fillLocSelects({ area: $('i-area').value });
  const locFurnChanged = () => fillLocSelects({ area: $('i-area').value, furn: $('i-furn').value });
  const locLvlChanged = () => fillLocSelects({ area: $('i-area').value, furn: $('i-furn').value, lvl: $('i-lvl').value });
  function currentPositionNode() {
    const a = areaById($('i-area').value); if (!a) return null;
    const f = a.furniture.find(x => x.id == $('i-furn').value); if (!f) return null;
    const l = f.levels.find(x => x.id == $('i-lvl').value); if (!l) return null;
    return l.positions.find(x => x.id == $('i-pos').value) || null;
  }
  function syncCodeField() { const p = currentPositionNode(); $('i-code').value = p ? p.code : ''; }
  function applyCodeField() {
    const raw = $('i-code').value.trim().toUpperCase();
    if (!raw) { fillLocSelects({}); return; }
    const m = raw.match(/^([A-Z0-9]{3})(?:-M(\d{1,3}))?(?:-E(\d{1,3}))?(?:-P(\d{1,3}))?$/);
    const fail = (msg) => { showToast(esc(msg), 'error'); syncCodeField(); };
    if (!m) return fail('Ungültiger Code (Beispiel: ELE-M02-E03-P04)');
    const a = tree.find(x => x.code === m[1]); if (!a) return fail(`Bereich «${m[1]}» nicht gefunden`);
    const f = a.furniture.find(x => x.number === +(m[2] || 0)); if (!f) return fail(`${m[1]}-M${pad2(+m[2])} gibt es nicht`);
    const l = f.levels.find(x => x.number === +(m[3] || 0)); if (!l) return fail(`Ebene E${pad2(+m[3])} gibt es nicht`);
    const p = l.positions.find(x => x.number === +(m[4] || 0)); if (!p) return fail(`Platz P${pad2(+m[4])} gibt es nicht`);
    fillLocSelects({ area: a.id, furn: f.id, lvl: l.id, pos: p.id });
  }

  function openItemModal(id) {
    const item = id ? itemsCache[id] : null;
    editingItemId = item ? item.id : null;
    openModal(item ? 'Werkzeug bearbeiten' : 'Neues Werkzeug', `
      <div class="form-group"><label class="form-label">Name *</label><input class="form-input" id="inv-i-name" maxlength="150"></div>
      <div class="form-group"><label class="form-label">Synonyme (kommagetrennt)</label><input class="form-input" id="inv-i-syn" placeholder="Bohrschrauber, Schrauber, Drill"></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Menge</label><input class="form-input" id="inv-i-qty" type="number" min="0" value="1"></div>
        <div class="form-group"><label class="form-label">Status</label>
          <select class="form-input" id="inv-i-status"><option value="aktiv">aktiv</option><option value="defekt">defekt</option><option value="ausgemustert">ausgemustert</option></select></div>
      </div>
      <div class="form-group"><label class="form-label">Lagerort</label>
        <div class="inv-loc-box">
          <input class="form-input" id="inv-i-code" placeholder="Code, z.B. ELE-M02-E03" onchange="Inv.applyCodeField()" style="font-family:var(--mono)">
          <div class="form-row"><select class="form-input" id="inv-i-area" onchange="Inv.locAreaChanged()"></select><select class="form-input" id="inv-i-furn" onchange="Inv.locFurnChanged()"></select></div>
          <div class="form-row"><select class="form-input" id="inv-i-lvl" onchange="Inv.locLvlChanged()"></select><select class="form-input" id="inv-i-pos" onchange="Inv.syncCodeField()"></select></div>
        </div></div>
      <div class="form-group"><label class="form-label">Beschreibung</label><textarea class="form-input" id="inv-i-desc" style="min-height:70px"></textarea></div>`,
      saveItem, 'Speichern', null, 'input', 600);
    $('i-name').value = item ? item.name : '';
    $('i-syn').value = item ? item.synonyms : '';
    $('i-qty').value = item ? item.quantity : 1;
    $('i-status').value = item ? item.status : 'aktiv';
    $('i-desc').value = item ? item.description : '';
    const pos = item && item.position;
    fillLocSelects(pos ? { area: pos.area_id, furn: pos.furniture_id, lvl: pos.level_id, pos: pos.position_id } : {});
    $('i-name').focus();
  }

  async function saveItem() {
    const name = $('i-name').value.trim();
    if (!name) { showToast('Name fehlt', 'error'); return; }
    const p = currentPositionNode();
    const body = { name, synonyms: $('i-syn').value, description: $('i-desc').value,
      quantity: parseInt($('i-qty').value || '0', 10), status: $('i-status').value };
    let r;
    if (editingItemId) {
      if (p) body.position_id = p.id; else body.unplace = true;
      r = await PATCH('/inventory/items/' + editingItemId, body);
    } else {
      if (p) body.position_id = p.id;
      r = await POST('/inventory/items', body);
    }
    if (r) { closeModal(); showToast('Gespeichert', 'success'); await loadTree(); loadItems(); }
  }

  // ═══════════════════════════════════════════════════════
  // Struktur
  // ═══════════════════════════════════════════════════════
  function renderStructure() {
    const missing = tree.filter(a => !a.code).length;
    $('structure-tools').innerHTML = isPower()
      ? `<button class="btn btn-primary" onclick="Inv.openAreaModal()">+ Bereich</button>
         <button class="btn btn-primary" onclick="Inv.openFurnModal()">+ Möbel</button>
         ${missing ? `<button class="btn btn-ghost" onclick="Inv.assignMissingCodes()" title="Schlägt für alle Bereiche ohne Kürzel eines aus dem Namen vor">✨ Kürzel für ${missing} Bereich${missing > 1 ? 'e' : ''} vergeben</button>` : ''}`
      : `<span class="inv-dim inv-small">Nur Power-Manager und Admins können die Struktur ändern.</span>`;
    const list = $('structure-list');
    if (!tree.length) { list.innerHTML = '<div class="inv-empty">Noch keine Bereiche.</div>'; return; }
    list.innerHTML = tree.map(a => {
      const open = openAreas.has(a.id);
      const real = a.furniture.filter(f => f.number > 0);
      return `<div class="inv-card" style="--cc:${esc(a.color || '#22d3ee')}">
        <div class="inv-card-h" onclick="Inv.toggleArea(${a.id})">
          <span class="inv-swatch"></span>
          <span class="inv-name">${esc(a.name)}</span>
          ${a.code ? `<span class="inv-code">${esc(a.code)}</span>` : '<span class="badge badge-red">Kürzel fehlt</span>'}
          <span class="inv-dim inv-small">${real.length} Möbel · ${a.item_count} Werkzeuge</span>
          <span class="inv-sp"></span>
          ${isPower() ? `<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Inv.openAreaModal(${a.id})">✏️ Bereich</button>
            <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Inv.openFurnModal(null,${a.id})" ${a.code ? '' : 'disabled title="Zuerst ein Kürzel vergeben"'}>+ Möbel</button>` : ''}
          <span>${open ? '▾' : '▸'}</span>
        </div>
        ${open ? `<div class="inv-card-b">${a.furniture.map(f => furnHtml(a, f)).join('') || '<div class="inv-dim inv-small" style="padding:8px 0">Keine Möbel.</div>'}</div>` : ''}
      </div>`;
    }).join('');
  }
  function toggleArea(id) { openAreas.has(id) ? openAreas.delete(id) : openAreas.add(id); renderStructure(); }
  function toggleFurn(id) { openFurn.has(id) ? openFurn.delete(id) : openFurn.add(id); renderStructure(); }

  function furnHtml(a, f) {
    const open = openFurn.has(f.id), p = isPower();
    const title = f.number === 0 ? '<i>Im Bereich, ohne Möbel</i>' : esc(f.name || ((KIND[f.kind] || '').replace(/^\S+\s/, '') + ' ' + f.number));
    return `<div class="inv-furn" style="--cc:${esc(a.color || '#888')}">
      <div class="inv-furn-h" onclick="Inv.toggleFurn(${f.id})">
        <span class="inv-code">${esc(f.code)}</span>
        <b>${title}</b>
        ${f.number > 0 ? `<span class="inv-dim inv-small">${KIND[f.kind] || ''}</span>` : ''}
        <span class="inv-dim inv-small">${f.item_count} Werkzeuge</span>
        ${f.label_outdated ? '<span class="badge badge-orange" title="Neu angelegt oder Code geändert: Etikett (neu) drucken">Etikett neu/veraltet</span>' : ''}
        <span class="inv-sp"></span>
        <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Inv.gotoItems('${esc(f.code)}')">Werkzeug anzeigen</button>
        ${f.number > 0 ? `<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Inv.labelFor('${esc(f.code)}')" title="Dieses Etikett drucken / nachdrucken">🏷️</button>` : ''}
        ${p && f.number > 0 ? `<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Inv.openFurnModal(${f.id})">✏️</button>
          <button class="btn btn-danger btn-sm" onclick="event.stopPropagation();Inv.deleteFurn(${f.id},'${esc(f.code)}')">🗑</button>` : ''}
        <span>${open ? '▾' : '▸'}</span>
      </div>
      ${open ? `${f.levels.map(l => levelHtml(a, f, l)).join('')}
        ${p && f.number > 0 ? `<div style="padding:6px 0 4px 18px"><button class="btn btn-ghost btn-sm" onclick="Inv.addLevels(${f.id})">+ Ebene</button></div>` : ''}` : ''}
    </div>`;
  }
  function levelHtml(a, f, l) {
    const p = isPower();
    const real = l.positions.filter(x => x.number > 0);
    return `<div class="inv-lvl">
      <span class="inv-code">${esc(l.code)}</span>
      <span>${l.number === 0 ? '<i class="inv-dim">Ebene offen / nicht unterteilt</i>' : esc(l.label || 'Ebene ' + l.number)}</span>
      <span class="inv-dim inv-small">${l.item_count} Werkzeuge</span>
      <span class="inv-sp"></span>
      ${l.number > 0 ? `<button class="btn btn-ghost btn-sm" onclick="Inv.labelFor('${esc(l.code)}')" title="Dieses Etikett drucken / nachdrucken">🏷️</button>` : ''}
      ${p && l.number > 0 ? `<button class="btn btn-ghost btn-sm" onclick="Inv.renameLevel(${l.id})">Name</button>
        <button class="btn btn-ghost btn-sm" onclick="Inv.addPositions(${l.id})">+ Platz</button>
        <button class="btn btn-danger btn-sm" onclick="Inv.deleteLevel(${l.id},'${esc(l.code)}')">🗑</button>` : ''}
      <div style="flex-basis:100%;padding-left:6px">${real.map(x => `
        <span class="inv-pos" title="${esc(x.code)}">P${pad2(x.number)}${x.label ? ' · ' + esc(x.label) : ''}${x.item_count ? ` <b>${x.item_count}</b>` : ''}
          ${p ? `<a href="#" onclick="Inv.renamePos(${x.id});return false" title="Name">✎</a>
          <a href="#" onclick="Inv.deletePos(${x.id},'${esc(x.code)}');return false" title="Löschen" style="color:var(--danger)">✕</a>` : ''}
        </span>`).join('')}</div>
    </div>`;
  }
  function gotoItems(code) { $('f-q').value = code; itemsPage = 0; $('code-banner').style.display = 'none'; showTab('items'); }

  // ── Bereich ──
  async function assignMissingCodes() {
    const p = await POST('/inventory/areas/assign-missing-codes?dry_run=true');
    if (!p || !p.areas.length) { showToast('Alle Bereiche haben schon ein Kürzel', 'success'); return; }
    const lines = p.areas.map(a => `${a.name}  →  ${a.code}`).join('\n');
    if (!confirm(`Diese Kürzel werden vergeben:\n\n${lines}\n\nSie lassen sich danach einzeln ändern (vor dem Etikettendruck).`)) return;
    const r = await POST('/inventory/areas/assign-missing-codes?dry_run=false');
    if (r) { showToast(`${r.areas.length} Kürzel vergeben`, 'success'); await refreshAll(); }
  }
  async function suggestAreaCode(force) {
    const codeEl = $('a-code'), name = $('a-name') ? $('a-name').value.trim() : '';
    if (!codeEl || !name || (codeEl.value.trim() && !force)) return;
    const q = new URLSearchParams({ name }); if (editingAreaId) q.set('area_id', editingAreaId);
    const r = await apiSilent('GET', '/inventory/areas/suggest-code?' + q);
    if (r) codeEl.value = r.code;
  }
  function openAreaModal(id) {
    editingAreaId = id || null;
    const a = id ? areaById(id) : null;
    openModal(a ? 'Bereich bearbeiten' : 'Neuer Bereich', `
      <div class="form-group"><label class="form-label">Name *</label><input class="form-input" id="inv-a-name" maxlength="100" onblur="Inv.suggestAreaCode(false)"></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Kürzel (genau 3 Zeichen)</label>
          <div style="display:flex;gap:6px"><input class="form-input" id="inv-a-code" maxlength="3" placeholder="auto" style="font-family:var(--mono);text-transform:uppercase">
          <button type="button" class="btn btn-ghost btn-sm" onclick="Inv.suggestAreaCode(true)" title="Vorschlag aus dem Namen">✨</button></div></div>
        <div class="form-group"><label class="form-label">Farbe</label><input class="form-input" id="inv-a-color" type="color" style="padding:2px;height:40px"></div>
      </div>
      <div class="inv-hint">Das Kürzel ist der erste Teil jedes Lagerort-Codes. Wird es geändert, ändern sich die Codes aller Möbel dieses Bereichs, die Etiketten müssen neu gedruckt werden. Bereiche sind dieselben wie die <b>Standorte</b> bei den Maschinen.</div>`,
      saveArea, 'Speichern', null, 'input', 520);
    $('a-name').value = a ? a.name : '';
    $('a-code').value = a ? (a.code || '') : '';
    $('a-color').value = a && a.color ? a.color : '#22d3ee';
    if (a && !a.code) suggestAreaCode(false);
  }
  async function saveArea() {
    const body = { name: $('a-name').value.trim(), code: $('a-code').value.trim().toUpperCase(), color: $('a-color').value };
    if (!body.name) { showToast('Name fehlt', 'error'); return; }
    if (!body.code && !editingAreaId) body.code = null;      // neu ohne Kürzel: der Server schlägt eines vor
    const r = editingAreaId ? await PATCH('/inventory/areas/' + editingAreaId, body) : await POST('/inventory/areas', body);
    if (r) { closeModal(); showToast('Gespeichert', 'success'); await refreshAll(); }
  }

  // ── Möbel ──
  function openFurnModal(id, areaId) {
    editingFurnId = id || null;
    let f = null, a = null;
    if (id) for (const x of tree) { const m = x.furniture.find(y => y.id === id); if (m) { f = m; a = x; } }
    const areaOpts = tree.map(x => `<option value="${x.id}" ${x.code ? '' : 'disabled'}>${esc(x.name)}${x.code ? ` (${esc(x.code)})` : ' — Kürzel fehlt'}</option>`).join('');
    openModal(f ? 'Möbel bearbeiten' : 'Neues Möbel', `
      <div class="form-row">
        <div class="form-group"><label class="form-label">Bereich *</label><select class="form-input" id="inv-f-area-sel">${areaOpts}</select></div>
        <div class="form-group"><label class="form-label">Art</label>
          <select class="form-input" id="inv-f-kind"><option value="schrank">Schrank</option><option value="regal">Regal</option>
            <option value="wand">Werkzeugwand</option><option value="tisch">Tisch / Werkbank</option></select></div>
      </div>
      <div class="form-group"><label class="form-label">Name (optional, z.B. «Hilti Schrank 1»)</label><input class="form-input" id="inv-f-name" maxlength="100"></div>
      ${f ? '' : `<div class="form-row">
        <div class="form-group"><label class="form-label">Ebenen (Fächer, Schubladen)</label><input class="form-input" id="inv-f-levels" type="number" min="0" max="40" value="3"></div>
        <div class="form-group"><label class="form-label">Positionen je Ebene</label><input class="form-input" id="inv-f-positions" type="number" min="0" max="40" value="0"></div>
      </div>
      <div class="inv-hint">Ebenen und Positionen lassen sich später ergänzen. Ohne Ebenen bleibt nur <code>E00</code> (z.B. Tischplatte).</div>`}
      <div class="form-group"><label class="form-label">Bemerkung</label><textarea class="form-input" id="inv-f-note" style="min-height:60px"></textarea></div>`,
      saveFurn, 'Speichern', null, 'input', 560);
    $('f-area-sel').value = a ? a.id : (areaId || (tree.find(x => x.code) || {}).id || '');
    $('f-kind').value = f ? f.kind : 'schrank';
    $('f-name').value = f ? (f.name || '') : '';
    $('f-note').value = f ? (f.note || '') : '';
  }
  async function saveFurn() {
    const body = { area_id: +$('f-area-sel').value, kind: $('f-kind').value, name: $('f-name').value, note: $('f-note').value };
    if (!body.area_id) { showToast('Bereich wählen', 'error'); return; }
    let r;
    if (editingFurnId) {
      r = await PATCH('/inventory/furniture/' + editingFurnId, body);
    } else {
      body.levels = parseInt($('f-levels').value || '0', 10);
      body.positions = parseInt($('f-positions').value || '0', 10);
      r = await POST('/inventory/furniture', body);
      if (r) openAreas.add(body.area_id);
    }
    if (r) { closeModal(); showToast(editingFurnId ? 'Gespeichert' : `Angelegt: ${esc(r.code)}`, 'success'); await refreshAll(); }
  }
  async function deleteFurn(id, code) {
    if (!confirm(`Möbel ${code} samt Ebenen und Positionen löschen? (Nur möglich, wenn kein Werkzeug darin liegt.)`)) return;
    if (await DELETE('/inventory/furniture/' + id)) { showToast('Gelöscht', 'success'); await refreshAll(); }
  }
  async function addLevels(fid) {
    const n = parseInt(prompt('Wie viele Ebenen ergänzen?', '1') || '0', 10); if (!n) return;
    const pos = parseInt(prompt('Positionen je Ebene (0 = keine)', '0') || '0', 10);
    if (await POST(`/inventory/furniture/${fid}/levels`, { count: n, positions: pos || 0 })) await refreshAll();
  }
  async function addPositions(lid) {
    const n = parseInt(prompt('Wie viele Positionen ergänzen?', '1') || '0', 10); if (!n) return;
    if (await POST(`/inventory/levels/${lid}/positions`, { count: n })) await refreshAll();
  }
  function findLevel(lid) { for (const a of tree) for (const f of a.furniture) for (const l of f.levels) if (l.id === lid) return l; return null; }
  function findPos(pid) { for (const a of tree) for (const f of a.furniture) for (const l of f.levels) for (const p of l.positions) if (p.id === pid) return p; return null; }
  async function renameLevel(lid) {
    const v = prompt('Name der Ebene (leer = «Ebene n»)', (findLevel(lid) || {}).label || ''); if (v === null) return;
    if (await PATCH('/inventory/levels/' + lid, { label: v })) await refreshAll();
  }
  async function renamePos(pid) {
    const v = prompt('Name der Position (leer = «Platz n»)', (findPos(pid) || {}).label || ''); if (v === null) return;
    if (await PATCH('/inventory/positions/' + pid, { label: v })) await refreshAll();
  }
  async function deleteLevel(lid, code) {
    if (!confirm(`Ebene ${code} löschen? Die Nummern der übrigen Ebenen bleiben bestehen.`)) return;
    if (await DELETE('/inventory/levels/' + lid)) await refreshAll();
  }
  async function deletePos(pid, code) {
    if (!confirm(`Position ${code} löschen?`)) return;
    if (await DELETE('/inventory/positions/' + pid)) await refreshAll();
  }

  // ═══════════════════════════════════════════════════════
  // Etiketten
  // ═══════════════════════════════════════════════════════
  // Vorlagen. «sheet» = vorgeschnittener A4-Bogen mit festem Raster, sonst Einzeletiketten (Fliesslayout).
  // Raster Avery L6009 / L4736 / L6040 (45,7 × 21,2 mm, 4 × 12): Drittquelle mr-label.com (MR109) —
  // am echten Bogen mit dem Testbogen prüfen und bei Bedarf über «Versatz» korrigieren.
  const TEMPLATES = {
    avery: { name: 'Avery Zweckform L6009 · 45,7 × 21,2 mm · 48 pro Bogen', sheet: true,
             w: 45.7, h: 21.2, cols: 4, rows: 12, left: 9.85, top: 21.3, pitchX: 48.2, pitchY: 21.2 },
    f60:   { name: 'Einzeletiketten 60 × 30 mm', sheet: false, w: 60, h: 30 },
    f90:   { name: 'Einzeletiketten 90 × 50 mm', sheet: false, w: 90, h: 50 },
    f100:  { name: 'Einzeletiketten 100 × 60 mm', sheet: false, w: 100, h: 60 },
  };
  const lsGet = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ohne Speicher weiter */ } };
  let tplKey = lsGet('inv_label_tpl', 'avery');
  if (!TEMPLATES[tplKey]) tplKey = 'avery';
  const tpl = () => TEMPLATES[tplKey];
  const PREVIEW_SCALE = 0.42;
  const MAX_COPIES = 200;
  const clampCopies = (v) => Math.min(MAX_COPIES, Math.max(1, parseInt(v, 10) || 1));

  function initLabelControls() {
    const sel = $('l-tpl');
    sel.innerHTML = Object.entries(TEMPLATES).map(([k, t]) => `<option value="${k}">${esc(t.name)}</option>`).join('');
    sel.value = tplKey;
    $('l-offx').value = lsGet('inv_label_offx', '0');
    $('l-offy').value = lsGet('inv_label_offy', '0');
    applyTemplateUi();
  }
  function applyTemplateUi() {
    const t = tpl();
    root.querySelectorAll('.inv-sheet-only').forEach(e => { e.style.display = t.sheet ? '' : 'none'; });
    if (t.sheet) $('l-start').max = t.cols * t.rows;
    $('l-hint').innerHTML = t.sheet
      ? `<b>Vorgeschnittene Bögen (A4, ${t.cols * t.rows} Etiketten).</b> Gedruckt wird die <b>Auswahl</b> oben, je Etikett in der gewünschten <b>Anzahl</b>. Auf Ebenen- und Positions-Etiketten steht, <b>was dort liegt</b>. Der QR-Code führt zum Inhalt.
         Druckdialog: Papier <b>A4</b>, Skalierung <b>100 % / «Tatsächliche Grösse»</b> (nicht «Anpassen»), Kopf- und Fusszeilen <b>aus</b>, Ränder <b>keine</b>.
         Typenschild-Etiketten L6009 sind für Laserdrucker gedacht. Vor dem ersten Druck den <b>Testbogen</b> auf normales Papier drucken und gegen das Licht über einen Etikettenbogen halten;
         sitzt das Raster nicht genau, den Versatz einstellen.`
      : 'Einzeletiketten zum Ausschneiden (mit Rahmen). Gedruckt wird die Auswahl oben, je Etikett in der gewünschten Anzahl.';
  }
  function setTemplate() { tplKey = $('l-tpl').value; lsSet('inv_label_tpl', tplKey); applyTemplateUi(); renderLabels(); }
  function offsetChanged() { lsSet('inv_label_offx', $('l-offx').value); lsSet('inv_label_offy', $('l-offy').value); renderLabels(); }
  const num = (id, d = 0) => { const v = parseFloat($(id).value); return isNaN(v) ? d : v; };

  function toggleOutdated() { labelOutdatedOnly = !labelOutdatedOnly; $('chip-outdated').classList.toggle('on', labelOutdatedOnly); loadLabels(); }
  async function loadLabels() {
    const p = new URLSearchParams();
    const a = $('l-area').value; if (a) p.set('area_id', a);
    if (labelOutdatedOnly) p.set('outdated', 'true');
    const r = await GET('/inventory/labels?' + p);
    if (!r) return;
    labelData = r;
    if (pendingSel) { selected = pendingSel; pendingSel = null; selInit = true; }
    else if (!selInit) {                       // Erst-Auswahl: neue/veraltete Möbel mit ihren Ebenen (je 1×)
      selected = new Map(allLabels().filter(l => l.outdated && l.kind !== 'pos').map(l => [l.code, 1]));
      selInit = true;
    }
    renderLabelList();
    renderLabels();
  }

  const qrFor = (target) => `${location.origin}/api/qr/url-png?u=${encodeURIComponent(target)}`;
  const codeUrl = (code) => `${location.origin}/inventar.html?code=${encodeURIComponent(code)}`;
  const itemUrl = (id) => `${location.origin}/inventar.html?item=${id}`;     // bleibt nach einem Umlagern gültig

  // «Lineal 30 cm ×12, Zollstock ×5, … +3»
  function contentsText(items, count, max) {
    if (!items || !items.length) return '';
    const shown = items.slice(0, max).map(i => i.name + (i.quantity > 1 ? ' ×' + i.quantity : ''));
    const more = (count || items.length) - shown.length;
    return shown.join(', ') + (more > 0 ? ` … +${more}` : '');
  }

  // Alle möglichen Etiketten (Möbel, Ebenen, Positionen) der geladenen Daten
  function allLabels() {
    const out = [];
    for (const f of labelData) {
      out.push({ code: f.code, name: f.name, area: f.area, color: f.color, kind: 'furn', fid: f.furniture_id, outdated: f.outdated, items: f.items, count: f.item_count });
      for (const l of f.levels) {
        out.push({ code: l.code, name: l.label || ('Ebene ' + l.number), area: f.area, color: f.color, kind: 'level', fid: f.furniture_id, outdated: f.outdated, items: l.items, count: l.item_count });
        for (const p of (l.positions || [])) {
          out.push({ code: p.code, name: p.label || ('Platz ' + p.number), area: f.area, color: f.color, kind: 'pos', fid: f.furniture_id, outdated: f.outdated, items: p.items, count: p.item_count });
        }
      }
    }
    return out;
  }
  // Auswahl mit Anzahl: jedes gewählte Etikett so oft wie angegeben
  function furnItems() {
    const out = [];
    for (const l of allLabels()) { const n = selected.get(l.code) || 0; for (let i = 0; i < n; i++) out.push(l); }
    return out;
  }
  // Werkzeug: je Stück ein Etikett (Kopien)
  function toolItems() {
    const out = [];
    for (const [id, copies] of toolSel) {
      const it = toolList.find(x => x.id === id);
      if (!it) continue;
      for (let i = 0; i < copies; i++) {
        out.push({ kind: 'tool', id, code: it.position ? it.position.code : '', name: it.name, color: it.position && it.position.color });
      }
    }
    return out;
  }
  const labelItems = () => (labelMode === 'tool' ? toolItems() : furnItems());

  const KIND_TXT = { furn: 'Möbel', level: 'Ebene', pos: 'Position' };
  function renderLabelList() {
    const rows = allLabels();
    $('sel-list').innerHTML = rows.length ? rows.map(l => {
      const n = selected.get(l.code) || 0, c = esc(l.code);
      const ct = l.kind === 'furn'
        ? (l.count ? `${l.count} Werkzeug${l.count > 1 ? 'e' : ''}` : '')
        : contentsText(l.items, l.count, 8);
      const full = l.items && l.items.length ? l.items.map(i => i.name + (i.quantity > 1 ? ' ×' + i.quantity : '')).join(', ') : '';
      return `<label class="inv-sel-row ${l.kind}">
        <input type="checkbox" data-code="${c}" ${n ? 'checked' : ''} onchange="Inv.toggleLabel('${c}', this.checked)">
        <span class="inv-code" style="--cc:${esc(l.color || '#22d3ee')}">${c}</span>
        <b>${esc(l.name)}</b>
        ${l.kind === 'furn' && l.outdated ? '<span class="badge badge-orange" title="Neu angelegt oder Code geändert">neu/veraltet</span>' : ''}
        <span class="inv-sel-ct" title="${esc(full)}">${ct ? esc(ct) : (l.kind === 'furn' ? '' : '<i>leer</i>')}</span>
        ${l.kind === 'furn' ? `<a href="#" class="inv-dim inv-small" onclick="Inv.toggleLevelsOf(${l.fid});return false" title="Alle Ebenen dieses Möbels an-/abwählen">Ebenen ✓/✗</a>` : ''}
        <span class="inv-dim inv-small">Anzahl</span>
        <input type="number" class="inv-copies" data-code="${c}" min="0" max="${MAX_COPIES}" value="${n || 1}" onclick="event.stopPropagation()" onchange="Inv.setLabelCopies('${c}', this.value)" title="Wie viele Etiketten gedruckt werden (0 = nicht drucken)">
      </label>`;
    }).join('') : '<div class="inv-empty">Keine Möbel vorhanden.</div>';
    updateSelCount();
  }
  function updateSelCount() {
    const items = labelItems(), n = items.length;
    if (labelMode === 'furn') {
      $('sel-count').textContent = selected.size
        ? `${selected.size} Etikett${selected.size > 1 ? 'en' : ''} gewählt · ${n} Stück`
        : 'Nichts gewählt';
    } else {
      const kinds = new Set(items.map(i => i.id)).size;
      $('tl-count').textContent = `${kinds} Werkzeug${kinds === 1 ? '' : 'e'} · ${n} Etikett${n === 1 ? '' : 'en'}`;
    }
    const t = tpl(), per = t.sheet ? t.cols * t.rows : 0;
    $('btn-print').textContent = n ? `🖨️ ${n} Etikett${n > 1 ? 'en' : ''} drucken` : '🖨️ Auswahl drucken';
    $('btn-print').disabled = !n;
    $('btn-print').title = per && n ? `${Math.ceil((n + Math.max(0, num('l-start', 1) - 1)) / per)} Bogen` : '';
  }
  // Zeile in der Liste anpassen, ohne die ganze Liste neu zu zeichnen (Fokus/Scrollposition bleiben)
  function syncRow(code) {
    const n = selected.get(code) || 0;
    const cb = root.querySelector(`#inv-sel-list input[type=checkbox][data-code="${code}"]`);
    const ni = root.querySelector(`#inv-sel-list input.inv-copies[data-code="${code}"]`);
    if (cb) cb.checked = n > 0;
    if (ni && n > 0) ni.value = n;
  }
  function toggleLabel(code, on) {
    if (on) {
      const ni = root.querySelector(`#inv-sel-list input.inv-copies[data-code="${code}"]`);
      selected.set(code, clampCopies(ni ? ni.value : 1));
    } else selected.delete(code);
    syncRow(code); renderLabels();
  }
  function setLabelCopies(code, v) {
    const n = Math.min(MAX_COPIES, parseInt(v, 10) || 0);
    if (n <= 0) selected.delete(code); else selected.set(code, n);
    syncRow(code);
    const cb = root.querySelector(`#inv-sel-list input[type=checkbox][data-code="${code}"]`);
    if (cb) cb.checked = n > 0;
    renderLabels();
  }
  function toggleLevelsOf(fid) {
    const lv = allLabels().filter(l => l.kind === 'level' && l.fid === fid);
    const allOn = lv.every(l => selected.has(l.code));
    lv.forEach(l => allOn ? selected.delete(l.code) : selected.set(l.code, 1));
    renderLabelList(); renderLabels();
  }
  function selectBy(mode) {
    const rows = allLabels();
    const pick = {
      all: () => true, none: () => false,
      outdated: l => l.outdated && l.kind !== 'pos',
      furn: l => l.kind === 'furn', level: l => l.kind === 'level', pos: l => l.kind === 'pos',
    }[mode];
    selected = new Map(rows.filter(pick).map(l => [l.code, 1]));
    renderLabelList(); renderLabels();
  }
  // Einzel-Nachdruck aus dem Strukturbaum: genau dieses Etikett vorwählen
  async function labelFor(code) {
    $('l-area').value = ''; labelOutdatedOnly = false; $('chip-outdated').classList.remove('on');
    pendingSel = new Map([[code, 1]]);
    showTab('labels');
  }
  // ── Etikettenart: Möbel, Ebenen & Positionen oder Werkzeug ──
  function setLabelMode(mode) {
    labelMode = mode;
    $('mode-furn').classList.toggle('on', mode === 'furn');
    $('mode-tool').classList.toggle('on', mode === 'tool');
    $('furn-box').style.display = mode === 'furn' ? '' : 'none';
    $('tool-box').style.display = mode === 'tool' ? '' : 'none';
    $('mark-wrap').style.display = mode === 'furn' ? '' : 'none';
    if (mode === 'tool') loadToolList(); else { renderLabelList(); renderLabels(); }
  }
  let _tdeb = null;
  function debouncedToolLoad() { clearTimeout(_tdeb); _tdeb = setTimeout(loadToolList, 250); }
  async function loadToolList() {
    const p = new URLSearchParams({ limit: 500 });
    const q = $('tl-q').value.trim(); if (q) p.set('q', q);
    const r = await GET('/inventory/items?' + p);
    if (!r) return;
    toolList = r.items;
    renderToolList(); renderLabels();
  }
  function renderToolList() {
    $('tl-list').innerHTML = toolList.length ? toolList.map(i => `
      <label class="inv-sel-row">
        <input type="checkbox" ${toolSel.has(i.id) ? 'checked' : ''} onchange="Inv.toggleTool(${i.id}, this.checked)">
        <b>${esc(i.name)}</b>
        ${i.position ? `<span class="inv-code" style="--cc:${esc(i.position.color || '#22d3ee')}">${esc(i.position.code)}</span>` : '<span class="badge badge-red">ohne Platz</span>'}
        <span class="inv-dim inv-small">Menge ${i.quantity}</span>
        <span class="inv-sp"></span>
        <span class="inv-dim inv-small">Anzahl</span>
        <input type="number" class="inv-copies" min="1" max="${MAX_COPIES}" value="${toolSel.get(i.id) || clampCopies(i.quantity)}" onclick="event.stopPropagation()" onchange="Inv.setCopies(${i.id}, this.value)" title="Wie viele Etiketten gedruckt werden">
      </label>`).join('') : '<div class="inv-empty">Keine Werkzeuge gefunden.</div>';
    updateSelCount();
  }
  function toggleTool(id, on) {
    if (on) { const it = toolList.find(x => x.id === id); toolSel.set(id, clampCopies(it ? it.quantity : 1)); } else toolSel.delete(id);
    renderToolList(); renderLabels();
  }
  function setCopies(id, v) { toolSel.set(id, clampCopies(v)); renderToolList(); renderLabels(); }
  function toolSelectAll() { toolList.forEach(i => toolSel.set(i.id, toolSel.get(i.id) || clampCopies(i.quantity))); renderToolList(); renderLabels(); }
  function toolSelectNone() { toolSel.clear(); renderToolList(); renderLabels(); }
  function toolCopiesQty() { toolList.forEach(i => { if (toolSel.has(i.id)) toolSel.set(i.id, clampCopies(i.quantity)); }); renderToolList(); renderLabels(); }

  // Schriftgrösse (mm) so wählen, dass der Code neben dem QR-Code Platz hat
  function codeFontMm(code, t) {
    const qr = t.sheet ? t.h - 3.2 : t.h - 6;
    const avail = t.w - qr - (t.sheet ? 3 : 4) - 1.5;
    return Math.max(2.4, Math.min(t.h * 0.26, avail / (code.length * 0.62)));
  }
  // Textblock: grösste Schrift (mm), bei der der ganze Text an Wortgrenzen umgebrochen neben dem QR-Code
  // und unter der Code-Zeile auf das Etikett passt. «factor» = mittlere Zeichenbreite in em.
  function fitFontMm(text, t, codeH, factor, maxFs, extraH) {
    const qr = t.sheet ? t.h - 3.2 : t.h - 6;
    const availW = t.w - qr - (t.sheet ? 3 : 4) - 1.5;
    const availH = t.h - (t.sheet ? 2.3 : 6) - codeH - 0.6 - (extraH || 0);
    const words = String(text).split(/\s+/).filter(Boolean);
    for (let fs = maxFs; fs >= 2.2; fs -= 0.1) {
      const perLine = Math.floor(availW / (fs * factor));
      if (words.some(w => w.length > perLine)) continue;
      let lines = 1, cur = 0;
      for (const w of words) {
        const need = cur ? cur + 1 + w.length : w.length;
        if (need > perLine) { lines++; cur = w.length; } else cur = need;
      }
      if (lines * fs * 1.12 <= availH) return fs;
    }
    return 2.2;
  }
  function labelHtml(it, t, extraStyle, cls) {
    const tool = it.kind === 'tool';
    const target = tool ? itemUrl(it.id) : codeUrl(it.code);
    let body;
    if (tool) {
      const codeFs = Math.min(t.h * 0.15, 3.4);
      body = `<div class="n" style="font-size:${fitFontMm(it.name, t, codeFs * 1.15, 0.56, Math.min(t.h * 0.19, 5)).toFixed(2)}mm">${esc(it.name)}</div>
              <div class="c" style="font-size:${codeFs.toFixed(2)}mm">${it.code ? '→ ' + esc(it.code) : 'ohne Platz'}</div>`;
    } else {
      // Möbel: Name; Ebene/Position: Name und was dort liegt
      const showArea = !t.sheet && it.kind === 'furn';
      const codeFs = codeFontMm(it.code, t);
      const fitFor = (txt) => fitFontMm(txt, t, codeFs * 1.1, 0.54, Math.min(t.h * 0.17, 4.2), showArea ? t.h * 0.12 * 1.3 : 0);
      // Inhalt: so viele Werkzeuge ausschreiben, wie bei lesbarer Schrift (≥ 2.8 mm) auf das Etikett passen, Rest als «+n»
      let ct = '', fs = fitFor(it.name);
      if (it.kind !== 'furn' && it.items && it.items.length) {
        for (let k = Math.min(t.sheet ? 4 : 8, it.items.length); k >= 1; k--) {
          ct = contentsText(it.items, it.count, k);
          fs = fitFor(it.name + ' ' + ct);
          if (fs >= 2.8) break;
        }
      }
      body = `<div class="c" style="font-size:${codeFs.toFixed(2)}mm">${esc(it.code)}</div>
              <div class="n" style="font-size:${fs.toFixed(2)}mm"><b>${esc(it.name)}</b>${ct ? ` <span class="ct">${esc(ct)}</span>` : ''}</div>
              ${showArea ? `<div class="a">${esc(it.area)}</div>` : ''}`;
    }
    return `<div class="inv-lbl ${cls}${tool ? ' tool' : ''}" style="--cc:${esc(it.color || '#888')};--lw:${t.w}mm;--lh:${t.h}mm;${extraStyle || ''}">
      <img src="${qrFor(target)}" alt="">
      <div class="t">${body}</div>
    </div>`;
  }
  // Bögen: Etiketten auf Seiten verteilen; auf der ersten Seite ab der gewählten Startposition
  function sheetPages(items, t, withSkips) {
    const per = t.cols * t.rows;
    const start = Math.min(Math.max(1, Math.round(num('l-start', 1))), per) - 1;
    const pages = [];
    let cur = [], slot = start;
    for (let i = 0; i < start && withSkips; i++) cur.push({ skip: true, slot: i });
    for (const it of items) {
      if (slot >= per) { pages.push(cur); cur = []; slot = 0; }
      cur.push({ it, slot });
      slot++;
    }
    if (cur.length) pages.push(cur);
    return pages;
  }
  function slotStyle(t, slot) {
    const c = slot % t.cols, r = Math.floor(slot / t.cols);
    const x = t.left + c * t.pitchX + num('l-offx'), y = t.top + r * t.pitchY + num('l-offy');
    return `left:${x.toFixed(2)}mm;top:${y.toFixed(2)}mm;`;
  }
  function sheetHtml(page, t, preview) {
    return `<div class="inv-sheet">${page.map(p => p.skip
      ? (preview ? `<div class="inv-lbl sheet skip" style="--lw:${t.w}mm;--lh:${t.h}mm;${slotStyle(t, p.slot)}"></div>` : '')
      : labelHtml(p.it, t, slotStyle(t, p.slot), 'sheet')).join('')}</div>`;
  }
  function calibrationHtml(t) {
    const cells = [];
    for (let i = 0; i < t.cols * t.rows; i++) {
      cells.push(`<div class="inv-cal" style="${slotStyle(t, i)}width:${t.w}mm;height:${t.h}mm"><b>${i + 1}</b>${t.w} × ${t.h} mm</div>`);
    }
    return `<div class="inv-sheet">${cells.join('')}</div>`;
  }

  function renderLabels() {
    const t = tpl(), box = $('labels-preview'), items = labelItems();
    updateSelCount();
    if (!items.length) { box.className = 'inv-sheetrow'; box.innerHTML = '<div class="inv-empty" style="width:100%">Nichts gewählt — oben Etiketten anhaken (oder «Alle» wählen) und die Anzahl angeben.</div>'; return; }
    if (t.sheet) {
      const pages = sheetPages(items, t, true);
      const wmm = 210 * PREVIEW_SCALE, hmm = 297 * PREVIEW_SCALE;
      box.className = 'inv-sheetrow';
      box.innerHTML = pages.map((pg, i) => `<div><div class="inv-dim inv-small" style="margin-bottom:4px">Bogen ${i + 1} von ${pages.length}</div>
        <div class="inv-sheetwrap" style="width:${wmm}mm;height:${hmm}mm"><div style="transform:scale(${PREVIEW_SCALE});transform-origin:0 0;width:210mm;height:297mm">${sheetHtml(pg, t, true)}</div></div></div>`).join('');
    } else {
      box.className = 'inv-freegrid';
      box.innerHTML = items.map(it => labelHtml(it, t, '', 'free')).join('');
    }
  }

  // Druck in einem unsichtbaren iframe: eigene Seitenregeln (@page), kein Einfluss auf den LabManager
  function printInFrame(bodyHtml, pageCss) {
    const f = document.createElement('iframe');
    f.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden';
    document.body.appendChild(f);
    const d = f.contentDocument;
    d.open();
    d.write(`<!doctype html><html><head><meta charset="utf-8"><title>Etiketten</title>
      <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap" rel="stylesheet">
      <style>html,body{margin:0;padding:0;background:#fff}${LABEL_CSS}${pageCss}</style></head><body>${bodyHtml}</body></html>`);
    d.close();
    const waitImgs = Promise.all([...d.images].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; })));
    const timeout = (ms) => new Promise(r => setTimeout(r, ms));
    Promise.race([Promise.all([waitImgs, d.fonts ? d.fonts.ready : 0]), timeout(6000)]).then(() => {
      f.contentWindow.focus();
      // Nach dem Druckdialog nachfragen, ob die Etiketten als gedruckt markiert werden sollen
      f.contentWindow.addEventListener('afterprint', () => setTimeout(() => {
        if (lastPrinted.length && confirm(`${lastPrinted.length} Etikett(en) als gedruckt markieren?\n\n«Abbrechen», falls nicht gedruckt wurde.`)) markPrinted(lastPrinted);
      }, 300), { once: true });
      f.contentWindow.print();
      setTimeout(() => f.remove(), 120000);
    });
  }
  function printLabels() {
    const t = tpl(), items = labelItems();
    if (!items.length) { showToast('Nichts gewählt', 'error'); return; }
    lastPrinted = labelMode === 'furn' ? [...new Set(items.map(i => i.code))] : [];     // Werkzeug-Etiketten haben kein «gedruckt»-Kennzeichen
    if (items.length > 480 && !confirm(`${items.length} Etiketten (${Math.ceil(items.length / 48)} Bögen) drucken?`)) return;
    if (t.sheet) {
      const pages = sheetPages(items, t, false);
      printInFrame(pages.map(pg => sheetHtml(pg, t, false)).join(''), '@page{size:A4;margin:0}');
    } else {
      printInFrame(`<div class="inv-freegrid" style="display:flex;flex-wrap:wrap;gap:2mm">${items.map(it => labelHtml(it, t, '', 'free')).join('')}</div>`, '@page{size:A4;margin:8mm}');
    }
  }
  function printCalibration() {
    const t = tpl();
    if (!t.sheet) return;
    printInFrame(calibrationHtml(t), '@page{size:A4;margin:0}');
  }
  // «Neu/veraltet» wird nur zurückgesetzt, wenn das Möbel-Etikett UND alle Ebenen-Etiketten gedruckt wurden
  // (ändert sich ein Code, müssen alle Etiketten des Möbels neu gedruckt werden). Positions-Etiketten zählen nicht mit.
  async function markPrinted(codes) {
    const set = new Set(codes || labelItems().map(i => i.code));
    if (!set.size) { showToast('Nichts gewählt', 'error'); return; }
    const done = [], partial = [];
    for (const f of labelData) {
      const mine = [f.code, ...f.levels.map(l => l.code)];
      const hit = mine.filter(c => set.has(c)).length;
      if (hit === mine.length) done.push(f.furniture_id);
      else if (hit && f.outdated) partial.push(f.code);
    }
    if (done.length && await POST('/inventory/furniture/printed', { furniture_ids: done })) {
      showToast(`${done.length} Möbel als gedruckt markiert` + (partial.length ? ` · ${esc(partial.join(', '))}: nicht komplett gedruckt, bleiben markiert` : ''), partial.length ? 'warn' : 'success');
      await refreshAll(); await loadLabels();
    } else if (!done.length) {
      showToast(partial.length ? `Nicht komplett gedruckt (${esc(partial.join(', '))}): Möbel- und alle Ebenen-Etiketten wählen` : 'Keine «neu/veraltet»-Möbel in der Auswahl', 'warn');
    }
  }

  // ═══════════════════════════════════════════════════════
  // Import
  // ═══════════════════════════════════════════════════════
  function parseImport() {
    return $('import-text').value.split(/\r?\n/).map(l => l.trim()).filter(Boolean).map(line => {
      const c = (line.includes('\t') ? line.split('\t') : line.split(';')).map(x => x.trim());
      return { name: c[0] || '', synonyms: c[1] || null, code: c[2] || null, quantity: parseInt(c[3] || '1', 10) || 1 };
    });
  }
  async function runImport(dry) {
    const rows = parseImport();
    if (!rows.length) { showToast('Nichts zum Importieren', 'error'); return; }
    const r = await POST('/inventory/items/import', { rows, dry_run: dry });
    if (!r) return;
    $('import-result').innerHTML = `<div class="inv-hint"><b>${dry ? 'Prüfung' : 'Importiert'}:</b> ${r.valid} von ${rows.length} Zeilen ${dry ? 'sind gültig' : 'angelegt'}${r.errors.length ? `, ${r.errors.length} mit Fehler` : ''}.</div>` +
      (r.errors.length ? `<div class="table-wrap"><table><thead><tr><th>Zeile</th><th>Problem</th></tr></thead><tbody>${r.errors.map(e => `<tr><td style="font-family:var(--mono)">${e.line}</td><td>${esc(e.error)}</td></tr>`).join('')}</tbody></table></div>` : '');
    if (!dry) { showToast(`${r.created} Werkzeuge importiert`, 'success'); await loadTree(); if (!r.errors.length) $('import-text').value = ''; }
  }

  // ═══════════════════════════════════════════════════════
  // Anmeldung am LabManager
  // ═══════════════════════════════════════════════════════
  window.Inv = {
    showTab, debouncedLoadItems, reloadItems, toggleChip, pageItems, openItemModal, deleteItem, clearBanner,
    locAreaChanged, locFurnChanged, locLvlChanged, syncCodeField, applyCodeField,
    toggleArea, toggleFurn, gotoItems, openAreaModal, suggestAreaCode, assignMissingCodes,
    openFurnModal, deleteFurn, addLevels, addPositions, renameLevel, renamePos, deleteLevel, deletePos,
    toggleOutdated, loadLabels, renderLabels, printLabels, printCalibration, setTemplate, offsetChanged, markPrinted, runImport,
    toggleLabel, setLabelCopies, toggleLevelsOf, selectBy, labelFor,
    setLabelMode, debouncedToolLoad, toggleTool, setCopies, toolSelectAll, toolSelectNone, toolCopiesQty,
  };

  LabModules.register('inventory', { title: 'Inventar', mount, show });
})();
