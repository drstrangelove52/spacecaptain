/*
 * Bauplan des Inventar-Moduls (Etappe 4): zeichnet Gebäude, Stockwerke, Räume, Bereiche, Möbel und Maschinen als Rechtecke
 * (Einheit: cm) in ein SVG. Wird vom LabManager (bearbeitbar) und von der Gäste-Seite inventar.html (nur ansehen) geladen.
 *
 *   const plan = InvPlan.mount(container, data, { editable, onChange(kind, id, rect|null, {points, before}), onMode(mode, count), onBackground(floorId, pos, prevPos), onSelect, onFloor, onSelect(sel|null), onFloor(id) });
 *   plan.setData(data); plan.setHighlight({ codes: ['ELE-M02'], machineIds: [3], areaCodes: ['ELE'] });
 *   Option zoomControls (Gäste-Seite): Knöpfe + − ⤢, Pinch-Zoom und Strg+Mausrad; plan.zoomTo(z) / plan.zoomFit(), Standard = ganzer Plan sichtbar.
 *   plan.setMode('bg'|null) (Grundriss verschieben); plan.cropRect(cb) (Ausschnitt aufziehen); plan.pickPoints(n, cb); plan.drawPolygon(cb); plan.cancelMode(); plan.setBackground(floorId, patch);
 *   plan.setFloor(id); plan.floorId(); plan.select(kind, id); plan.place(kind, id, {x, y}|null);
 *   plan.update(kind, id, {x, w, rot, floor_id …}); plan.remove(kind, id); plan.toPolygon(id); plan.toRect(id);
 *
 * kind: 'room' (Raum, Treppe, Tür oder Durchgang; Räume optional als Vieleck mit `points`), 'area', 'furniture', 'machine'.
 * `data` kommt von GET /api/inventory/plan bzw. /api/inventory-public/plan. Elemente stehen auf genau einem Stockwerk
 * (`plan.floor_id`); eine Treppe liegt auf einem Stockwerk und erscheint zusätzlich auf ihrem Ziel-Stockwerk.
 * Die Seite stellt die CSS-Variablen --text, --border, --surface, --surface2, --accent, --body bereit.
 */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const SNAP = 5;                                            // cm
  const DEFAULT_SIZE = { area: [300, 300], machine: [80, 60], furniture: { schrank: [100, 50], regal: [100, 40], wand: [150, 15], tisch: [160, 80] } };
  const KIND_ORDER = ['room', 'area', 'furniture', 'machine'];   // von unten nach oben

  function svgEl(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in (attrs || {})) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  const snap = (v) => Math.round(v / SNAP) * SNAP;
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
  const furnitureCode = (code) => { const m = /^([A-Z0-9]{3}-M\d{2})/.exec(code || ''); return m ? m[1] : null; };

  function ensureStyle() {
    if (document.getElementById('invplan-style')) return;
    const st = document.createElement('style');
    st.id = 'invplan-style';
    st.textContent = `
      .invplan-wrap{border:1px solid var(--border);border-radius:10px;background:var(--surface2);overflow:auto;max-height:78vh}
      .invplan-svg{display:block;font-family:var(--body,sans-serif);user-select:none;-webkit-user-select:none}
      .invplan-stage{position:relative}
      .invplan-zoomable{height:auto;max-height:68vh;overscroll-behavior:contain;-webkit-overflow-scrolling:touch}
      .invplan-zoomable .invplan-svg{margin:0 auto}
      .invplan-zoombtns{position:absolute;right:8px;top:8px;display:flex;flex-direction:column;gap:6px;z-index:3}
      .invplan-zoombtns button{width:42px;height:42px;border-radius:10px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:22px;line-height:1;cursor:pointer;opacity:.94;touch-action:manipulation}
      .invplan-floors{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
      .invplan-floor{padding:6px 14px;border:1px solid var(--border);border-radius:16px;cursor:pointer;font-size:15px;font-weight:600;color:var(--text);background:var(--surface)}
      .invplan-floor.on{border-color:var(--accent);color:var(--accent)}
      .invplan-el{cursor:default}.invplan-edit .invplan-el{cursor:move}
      .invplan-dim{opacity:.28}
      .invplan-hit .invplan-shape{stroke:var(--accent,#f4a622)!important;stroke-width:4px!important;vector-effect:non-scaling-stroke}
      .invplan-hit .invplan-pulse{animation:invplan-pulse 1.3s ease-in-out infinite}
      @keyframes invplan-pulse{0%,100%{opacity:.15}50%{opacity:.75}}
      .invplan-sel .invplan-shape{stroke:var(--text,#fff)!important;stroke-width:3px!important;stroke-dasharray:10 6;vector-effect:non-scaling-stroke}
      .invplan-handle{fill:var(--accent,#f4a622);stroke:#000;stroke-width:2;cursor:nwse-resize}`;
    document.head.appendChild(st);
  }

  function mount(container, data, opts) {
    opts = opts || {};
    ensureStyle();
    container.innerHTML = '';
    const bar = document.createElement('div');
    bar.className = 'invplan-floors';
    container.appendChild(bar);
    const zoomable = !!opts.zoomControls;
    let stage = container;
    if (zoomable) { stage = document.createElement('div'); stage.className = 'invplan-stage'; container.appendChild(stage); }
    const wrap = document.createElement('div');
    wrap.className = 'invplan-wrap' + (zoomable ? ' invplan-zoomable' : '');
    stage.appendChild(wrap);
    const svg = svgEl('svg', { class: 'invplan-svg' + (opts.editable ? ' invplan-edit' : '') });
    svg.style.width = '100%';
    if (opts.editable) svg.style.touchAction = 'none';
    wrap.appendChild(svg);

    let sel = null;                                          // { kind, id }
    let floor = null;                                        // aktuelles Stockwerk (id)
    let hl = { codes: [], machineIds: [], areaCodes: [] };
    let drag = null;                                         // { mode: 'move'|'resize', kind, id, start, orig }
    let mods = { shift: false, ctrl: false, alt: false };      // gedrückte Umschalttasten (Winkel einrasten)
    let mode = null;                                         // null | 'bg' (Grundriss verschieben) | 'pick' (Punkte wählen) | 'draw' (Raum zeichnen)
    let span = 1500;                                         // grösste Seite der Ansicht (cm): Schriftgrössen wachsen mit
    let tmp = [], tmpMax = 0, tmpCb = null, hover = null, hoverRaw = null, defsEl = null, cropPrev = null, cropCb = null;

    const floors = () => data.floors && data.floors.length ? data.floors : [{ id: 0, name: '' }];
    const list = (kind) => kind === 'room' ? (data.rooms || []) : kind === 'area' ? data.areas : kind === 'furniture' ? data.furniture : data.machines;
    const find = (kind, id) => list(kind).find(o => o.id === id);
    const floorOf = (kind, o) => kind === 'room' ? o.floor_id : (o.plan && o.plan.floor_id != null ? o.plan.floor_id : floors()[0].id);
    const snapOf = (o) => ({ plan: o.plan ? Object.assign({}, o.plan) : null, points: o.points ? o.points.map(q => q.slice()) : null });   // für «Rückgängig»
    const curFloorOf = () => floors().find(f => f.id === floor);
    const ensureFloor = () => { if (!floors().some(f => f.id === floor)) floor = floors()[0].id; };

    function isHit(kind, o) {
      if (kind === 'furniture') return hl.codes.some(c => furnitureCode(c) === o.code);
      if (kind === 'machine') return hl.machineIds.includes(o.id);
      if (kind === 'area') return !!o.code && hl.areaCodes.includes(o.code);
      return false;
    }
    const anyHl = () => hl.codes.length + hl.machineIds.length + hl.areaCodes.length > 0;
    const visible = (kind, o) => !!o.plan && (kind === 'room'
      ? (o.floor_id === floor || (o.kind === 'treppe' && o.link_floor_id === floor))
      : floorOf(kind, o) === floor);

    function labelFor(kind, o) {
      if (kind === 'furniture') return o.code.replace(/^[A-Z0-9]{3}-/, '') + (o.title && o.title !== o.code ? ' ' + o.title : '');
      if (kind === 'area') return (o.code ? o.code + ' ' : '') + o.name;
      return o.name;
    }

    function renderBar() {
      bar.innerHTML = '';
      bar.style.display = floors().length > 1 ? '' : 'none';
      for (const f of floors()) {
        const b = document.createElement('div');
        b.className = 'invplan-floor' + (f.id === floor ? ' on' : '');
        b.textContent = f.name;
        b.onclick = () => api.setFloor(f.id);
        bar.appendChild(b);
      }
    }

    function render() {
      ensureFloor();
      renderBar();
      const r = data.room, W = r.width_cm, H = r.height_cm;
      // Ansicht: bei einem Grundriss-Bild dessen sichtbarer Ausschnitt, sonst das Gebäude; dazu alles, was darüber hinausragt
      const fl0 = floors().find(f => f.id === floor) || {}, bgv = fl0.background && fl0.bgUrl ? fl0.background : null;
      let x0 = 0, y0 = 0, x1 = W, y1 = H;
      if (bgv) {
        const c = bgv.crop || { l: 0, t: 0, r: 0, b: 0 }, a = (bgv.rot || 0) * Math.PI / 180, bx = bgv.x + bgv.w / 2, by = bgv.y + bgv.h / 2;
        const corners = [[bgv.x + c.l * bgv.w, bgv.y + c.t * bgv.h], [bgv.x + bgv.w * (1 - c.r), bgv.y + c.t * bgv.h], [bgv.x + bgv.w * (1 - c.r), bgv.y + bgv.h * (1 - c.b)], [bgv.x + c.l * bgv.w, bgv.y + bgv.h * (1 - c.b)]]
          .map(([px, py]) => [bx + (px - bx) * Math.cos(a) - (py - by) * Math.sin(a), by + (px - bx) * Math.sin(a) + (py - by) * Math.cos(a)]);
        x0 = Math.min(...corners.map(q => q[0])); x1 = Math.max(...corners.map(q => q[0])); y0 = Math.min(...corners.map(q => q[1])); y1 = Math.max(...corners.map(q => q[1]));
      }
      for (const kind of KIND_ORDER) for (const o of list(kind)) {
        if (!visible(kind, o)) continue;
        const p = o.plan, a = (p.rot || 0) * Math.PI / 180, cx = p.x + p.w / 2, cy = p.y + p.h / 2;
        const ex = (Math.abs(p.w * Math.cos(a)) + Math.abs(p.h * Math.sin(a))) / 2, ey = (Math.abs(p.w * Math.sin(a)) + Math.abs(p.h * Math.cos(a))) / 2;
        x0 = Math.min(x0, cx - ex); x1 = Math.max(x1, cx + ex); y0 = Math.min(y0, cy - ey); y1 = Math.max(y1, cy + ey);
      }
      span = Math.max(x1 - x0, y1 - y0);
      const mg = Math.max(20, span * 0.015);
      svg.setAttribute('viewBox', `${x0 - mg} ${y0 - mg} ${x1 - x0 + 2 * mg} ${y1 - y0 + 2 * mg}`);
      svg.innerHTML = '';
      const defs = svgEl('defs', {}, svg);
      defsEl = defs;
      const pat = svgEl('pattern', { id: 'invplan-grid', width: 100, height: 100, patternUnits: 'userSpaceOnUse' }, defs);
      svgEl('path', { d: 'M100 0H0V100', fill: 'none', stroke: 'currentColor', 'stroke-opacity': .12, 'stroke-width': 1 }, pat);
      const st = svgEl('pattern', { id: 'invplan-stairs', width: 24, height: 24, patternUnits: 'userSpaceOnUse' }, defs);
      svgEl('path', { d: 'M0 12H24', stroke: 'currentColor', 'stroke-opacity': .55, 'stroke-width': 3 }, st);
      svgEl('rect', { x: 0, y: 0, width: W, height: H, fill: 'var(--surface2)', stroke: 'var(--text)', 'stroke-width': 2, 'stroke-opacity': .25, 'stroke-dasharray': '12 8' }, svg);
      const curFloor = floors().find(f => f.id === floor) || {};
      if (curFloor.background && curFloor.bgUrl) {                 // Grundriss zum Abpausen
        const b = curFloor.background;
        const c = b.crop || { l: 0, t: 0, r: 0, b: 0 }, gb = svgEl('g', { 'pointer-events': 'none', transform: b.rot ? `rotate(${b.rot} ${b.x + b.w / 2} ${b.y + b.h / 2})` : null }, svg);
        let tgt = gb;
        if (c.l || c.t || c.r || c.b) {                       // nur der gewählte Ausschnitt des Bildes ist sichtbar (z.B. ohne Bemassung am Rand)
          const cp = svgEl('clipPath', { id: 'invplan-bgclip' }, defsEl);
          svgEl('rect', { x: b.x + c.l * b.w, y: b.y + c.t * b.h, width: b.w * (1 - c.l - c.r), height: b.h * (1 - c.t - c.b) }, cp);
          tgt = svgEl('g', { 'clip-path': 'url(#invplan-bgclip)' }, gb);
        }
        svgEl('image', { href: curFloor.bgUrl, x: b.x, y: b.y, width: b.w, height: b.h, opacity: b.opacity, preserveAspectRatio: 'none' }, tgt);
      }
      svgEl('rect', { x: 0, y: 0, width: W, height: H, fill: 'url(#invplan-grid)', style: 'color:var(--text)', 'pointer-events': 'none' }, svg);
      const fname = (floors().find(f => f.id === floor) || {}).name;
      const t = svgEl('text', { x: 8, y: H - 10, 'font-size': 18, fill: 'var(--text)', 'fill-opacity': .45 }, svg);
      t.textContent = `${r.name}${fname ? ' · ' + fname : ''} · ${(W / 100).toLocaleString('de-CH')} × ${(H / 100).toLocaleString('de-CH')} m`;

      // Räume anderer Stockwerke als Schatten (Orientierung), nicht anklickbar
      for (const o of list('room')) {
        if (!o.plan || o.kind === 'treppe' || o.floor_id === floor) continue;
        const p = o.plan;
        svgEl('rect', { x: p.x, y: p.y, width: p.w, height: p.h, fill: 'none', stroke: 'var(--text)', 'stroke-opacity': .22, 'stroke-width': 3,
          'stroke-dasharray': '16 10', 'pointer-events': 'none' }, svg);
      }
      const weight = (kind, o) => kind === 'room' ? (o.kind === 'raum' ? 0 : o.kind === 'treppe' ? 1 : 2) : 0;
      for (const kind of KIND_ORDER) {
        for (const o of list(kind).filter(x => visible(kind, x)).sort((a, b) => weight(kind, a) - weight(kind, b))) drawElement(kind, o);
      }
      if (opts.editable && sel) drawHandle();
      drawTemp();
      applyZoom();
    }

    function drawElement(kind, o) {
      const p = o.plan, cx = p.x + p.w / 2, cy = p.y + p.h / 2;
      const hit = isHit(kind, o);
      const cls = ['invplan-el'];
      if (anyHl() && kind !== 'room') cls.push(hit ? 'invplan-hit' : 'invplan-dim');
      if (sel && sel.kind === kind && sel.id === o.id) cls.push('invplan-sel');
      const g = svgEl('g', { class: cls.join(' '), 'data-kind': kind, 'data-id': o.id, transform: `rotate(${p.rot || 0} ${cx} ${cy})` }, svg);
      const rot = ((p.rot || 0) % 180 + 180) % 180;
      const vw = rot === 90 ? p.h : p.w, vh = rot === 90 ? p.w : p.h;

      if (kind === 'room' && (o.kind === 'tuer' || o.kind === 'durchgang')) {            // Lücke in der Wand, bei Türen mit Schwenkbogen
        const gh = Math.max(p.h, (data.room.wall_cm || 0) + 4);                      // die Lücke ist mindestens so dick wie die Wand
        const tr = !!(curFloorOf() && curFloorOf().background && curFloorOf().bgUrl);
        svgEl('rect', { class: 'invplan-shape', x: p.x, y: cy - gh / 2, width: p.w, height: gh, fill: 'var(--surface2)', 'fill-opacity': tr ? .45 : 1, stroke: 'var(--text)', 'stroke-opacity': .55, 'stroke-width': 1.5 }, g);
        if (o.kind === 'tuer') {                              // flip: Bit 1 = Anschlag rechts statt links, Bit 2 = Aufschlag nach unten statt oben
          const fh = (o.flip || 0) & 1, fv = ((o.flip || 0) >> 1) & 1, hy = p.y + p.h / 2;
          const hx = fh ? p.x + p.w : p.x, ex = fh ? p.x : p.x + p.w, ly = fv ? hy + p.w : hy - p.w;
          svgEl('path', { d: `M ${hx} ${hy} L ${hx} ${ly} A ${p.w} ${p.w} 0 0 ${fh ^ fv ? 0 : 1} ${ex} ${hy}`, fill: 'none', stroke: 'var(--text)', 'stroke-opacity': .6,
            'stroke-width': 2.5, 'pointer-events': 'none' }, g);
        }
        return;
      }
      if (kind === 'room') {
        const stairs = o.kind === 'treppe';
        if (stairs) svgEl('rect', { class: 'invplan-shape', x: p.x, y: p.y, width: p.w, height: p.h, fill: 'var(--surface)', 'fill-opacity': .9, stroke: 'var(--text)', 'stroke-opacity': .75, 'stroke-width': 3 }, g);
        else {                                                // Raum = Innenfläche; die Wand (Dicke aus den Gebäude-Einstellungen) liegt ausserhalb
          const d = o.points ? 'M ' + o.points.map(q => q.join(' ')).join(' L ') + ' Z' : `M ${p.x} ${p.y} H ${p.x + p.w} V ${p.y + p.h} H ${p.x} Z`;
          const cid = 'invplan-wall-' + o.id, cp = svgEl('clipPath', { id: cid }, defsEl);
          svgEl('path', { d: 'M -1000000 -1000000 H 1000000 V 1000000 H -1000000 Z ' + d, 'clip-rule': 'evenodd' }, cp);
          const tracing = !!(curFloorOf() && curFloorOf().background && curFloorOf().bgUrl);      // Grundriss darunter: nichts verdecken
          const wall = o.wall_cm != null ? o.wall_cm : (data.room.wall_cm || 0);                  // eigene Dicke, sonst Standard; 0 = nur Umriss
          const quiet = tracing && !opts.editable;                                              // Gäste: der Grundriss zeigt die Wände, die Räume nur dezent
          if (wall > 0 && !quiet) svgEl('path', { d, fill: 'none', stroke: tracing ? 'var(--accent)' : 'var(--text)', 'stroke-opacity': tracing ? .4 : .8, 'stroke-width': wall * 2, 'stroke-linejoin': 'miter', 'clip-path': `url(#${cid})` }, g);
          svgEl('path', { class: 'invplan-shape', d, fill: tracing ? 'var(--accent)' : 'var(--surface)', 'fill-opacity': quiet ? .03 : tracing ? .07 : .35, stroke: 'none' }, g);
          svgEl('path', { d, fill: 'none', stroke: tracing || wall > 0 ? 'var(--accent)' : 'var(--text)', 'stroke-opacity': quiet ? .45 : wall > 0 && !tracing ? .9 : .85, 'stroke-width': quiet ? 1.5 : 2, 'vector-effect': 'non-scaling-stroke', 'pointer-events': 'none' }, g);   // feine Innenkante / Umriss
        }
        if (stairs) svgEl('rect', { x: p.x, y: p.y, width: p.w, height: p.h, fill: 'url(#invplan-stairs)', style: 'color:var(--text)', 'pointer-events': 'none' }, g);
        let txt = o.name;
        if (stairs && o.link_floor_id != null) {
          const target = o.floor_id === floor ? o.link_floor_id : o.floor_id;
          const ti = floors().findIndex(f => f.id === target), ci = floors().findIndex(f => f.id === floor);
          txt += ` ${ti > ci ? '↑' : '↓'} ${(floors()[ti] || {}).name || ''}`;
        }
        const fmax = Math.max(22, span / 40), size = Math.max(fmax * 0.45, Math.min(fmax, vh * 0.5, vw * 1.7 / Math.max(txt.length, 3)));
        const tx = svgEl('text', stairs ? { x: cx, y: cy + size * 0.35, 'text-anchor': 'middle', 'font-size': size, 'font-weight': 700, fill: 'var(--text)',
          transform: `rotate(${-(p.rot || 0)} ${cx} ${cy})`, 'pointer-events': 'none', stroke: 'var(--surface)', 'stroke-width': 4, 'paint-order': 'stroke' }
          : { x: p.x + 10, y: p.y + size + 6, 'font-size': size, 'font-weight': 700, fill: 'var(--text)', 'fill-opacity': .7, 'pointer-events': 'none' }, g);
        tx.textContent = txt;
        return;
      }

      const color = o.color || '#22d3ee';
      const fill = kind === 'area' ? { 'fill-opacity': .16 } : kind === 'furniture' ? { 'fill-opacity': .5 } : { 'fill-opacity': .95 };
      svgEl('rect', Object.assign({ class: 'invplan-shape', x: p.x, y: p.y, width: p.w, height: p.h, rx: kind === 'machine' ? 8 : 2, fill: color,
        stroke: color, 'stroke-width': kind === 'area' ? 3 : 2, 'stroke-dasharray': kind === 'area' ? '10 6' : null }, fill), g);
      if (hit) svgEl('rect', { class: 'invplan-pulse', x: p.x - span / 150, y: p.y - span / 150, width: p.w + span / 75, height: p.h + span / 75, rx: 10, fill: 'none', stroke: 'var(--accent)', 'stroke-width': 4, 'vector-effect': 'non-scaling-stroke', 'pointer-events': 'none' }, g);
      // Beschriftung bleibt waagrecht (gegen die Drehung des Elements gedreht) und passt in die sichtbare Breite
      const txt = labelFor(kind, o);
      const fmax = Math.max(22, span / 40), size = Math.max(fmax * 0.42, Math.min(fmax, vh * 0.6, vw * 1.7 / Math.max(txt.length, 3)));
      if (kind === 'area') {                                 // Bereichsname oben links, ungedreht
        const a = svgEl('text', { x: p.x + 8, y: p.y + size + 4, 'font-size': size, 'font-weight': 700, fill: 'var(--text)', 'fill-opacity': .8, 'pointer-events': 'none' }, g);
        a.textContent = txt;
      } else {
        const tx = svgEl('text', { x: cx, y: cy + size * 0.35, 'font-size': size, 'font-weight': 700, 'text-anchor': 'middle', fill: kind === 'machine' ? '#000' : 'var(--text)',
          transform: `rotate(${-(p.rot || 0)} ${cx} ${cy})`, 'pointer-events': 'none' }, g);
        tx.textContent = txt;
      }
    }

    // Grösse ändern an allen vier Kanten (Streifen entlang der Linie) und vier Ecken; die gegenüberliegende Kante bleibt stehen
    const CURSOR = { n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize', nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize' };
    function drawHandle() {
      const o = find(sel.kind, sel.id);
      if (!o || !o.plan || !visible(sel.kind, o)) return;
      if (sel.kind === 'room' && o.points) {                     // Vieleck: Eckpunkte ziehen, «+» an den Kanten fügt eine Ecke ein
        const g2 = svgEl('g', {}, svg), n = o.points.length;
        o.points.forEach((q, i) => {
          const nx = o.points[(i + 1) % n];
          svgEl('circle', { cx: (q[0] + nx[0]) / 2, cy: (q[1] + nx[1]) / 2, r: 7, fill: 'var(--surface)', stroke: 'var(--accent)', 'stroke-width': 2, 'data-mid': i, style: 'cursor:copy' }, g2);
        });
        o.points.forEach((q, i) => svgEl('circle', { class: 'invplan-handle', cx: q[0], cy: q[1], r: 10, 'data-vertex': i, style: 'cursor:move' }, g2));
        return;
      }
      const p = o.plan, cx = p.x + p.w / 2, cy = p.y + p.h / 2, T = 16;
      const g = svgEl('g', { transform: `rotate(${p.rot || 0} ${cx} ${cy})` }, svg);
      const inH = Math.min(T / 2, p.h * 0.25), inW = Math.min(T / 2, p.w * 0.25);      // nach innen nur wenig, damit Verschieben möglich bleibt
      const strip = (h, x, y, w, ht) => svgEl('rect', { x, y, width: w, height: ht, fill: 'transparent', 'data-handle': h, style: `cursor:${CURSOR[h]}` }, g);
      strip('n', p.x, p.y - T / 2, p.w, T / 2 + inH);
      strip('s', p.x, p.y + p.h - inH, p.w, T / 2 + inH);
      strip('w', p.x - T / 2, p.y, T / 2 + inW, p.h);
      strip('e', p.x + p.w - inW, p.y, T / 2 + inW, p.h);
      const dot = (h, x, y) => svgEl('circle', { class: 'invplan-handle', cx: x, cy: y, r: 9, 'data-handle': h, style: `cursor:${CURSOR[h]}` }, g);
      dot('nw', p.x, p.y); dot('ne', p.x + p.w, p.y); dot('sw', p.x, p.y + p.h); dot('se', p.x + p.w, p.y + p.h);
    }

    // ── Zeigerlogik (nur bearbeitbar) ──
    function toCm(ev) {
      const pt = svg.createSVGPoint();
      pt.x = ev.clientX; pt.y = ev.clientY;
      const m = svg.getScreenCTM();
      return m ? pt.matrixTransform(m.inverse()) : { x: 0, y: 0 };
    }
    function rotateBack(pt, o) {                             // Punkt ins Eigensystem des (gedrehten) Elements
      const p = o.plan, cx = p.x + p.w / 2, cy = p.y + p.h / 2, a = -(p.rot || 0) * Math.PI / 180;
      const dx = pt.x - cx, dy = pt.y - cy;
      return { x: cx + dx * Math.cos(a) - dy * Math.sin(a), y: cy + dx * Math.sin(a) + dy * Math.cos(a) };
    }
    const selInfo = () => sel && find(sel.kind, sel.id) ? { kind: sel.kind, id: sel.id, item: find(sel.kind, sel.id) } : null;
    function setSelection(next) {
      sel = next;
      render();
      if (opts.onSelect) opts.onSelect(selInfo());
    }

    if (opts.editable) {
      svg.addEventListener('pointerdown', (ev) => {
        readMods(ev);
        const pt = toCm(ev);
        if (mode === 'pick' || mode === 'draw') { addTemp(constrainTemp(pt)); return; }
        if (mode === 'crop') { drag = { mode: 'crop', start: pt }; cropPrev = { x0: pt.x, y0: pt.y, x1: pt.x, y1: pt.y }; svg.setPointerCapture(ev.pointerId); return; }
        if (mode === 'bg') {                                 // Grundriss verschieben
          const b = (floors().find(f => f.id === floor) || {}).background;
          if (!b) return;
          drag = { mode: 'bg', start: pt, orig: { x: b.x, y: b.y } };
          svg.setPointerCapture(ev.pointerId); svg.style.cursor = 'grabbing';
          return;
        }
        if (ev.target.getAttribute && ev.target.getAttribute('data-handle') && sel) {
          const o = find(sel.kind, sel.id);
          drag = { mode: 'resize', handle: ev.target.getAttribute('data-handle'), kind: sel.kind, id: sel.id, orig: Object.assign({}, o.plan), before: snapOf(o) };
          svg.setPointerCapture(ev.pointerId);
          return;
        }
        const tgt = ev.target.getAttribute ? ev.target : null;
        if (tgt && sel && sel.kind === 'room' && (tgt.hasAttribute('data-vertex') || tgt.hasAttribute('data-mid'))) {
          const o = find('room', sel.id);
          if (tgt.hasAttribute('data-mid')) {                    // neue Ecke auf der Kantenmitte, sofort ziehbar
            const i = +tgt.getAttribute('data-mid'), a1 = o.points[i], b1 = o.points[(i + 1) % o.points.length];
            if (o.points.length >= 60) return;
            const before = snapOf(o);
            o.points.splice(i + 1, 0, [snap((a1[0] + b1[0]) / 2), snap((a1[1] + b1[1]) / 2)]);
            drag = { mode: 'vertex', kind: 'room', id: sel.id, idx: i + 1, moved: true, before };
          } else drag = { mode: 'vertex', kind: 'room', id: sel.id, idx: +tgt.getAttribute('data-vertex'), moved: false, before: snapOf(o) };
          svg.setPointerCapture(ev.pointerId);
          render();
          return;
        }
        const g = ev.target.closest && ev.target.closest('[data-kind]');
        if (!g) { setSelection(null); return; }
        const kind = g.getAttribute('data-kind'), id = +g.getAttribute('data-id');
        if (!sel || sel.kind !== kind || sel.id !== id) setSelection({ kind, id });
        const oo = find(kind, id);
        drag = { mode: 'move', kind, id, start: pt, orig: Object.assign({}, oo.plan), origPoints: oo.points ? oo.points.map(q => q.slice()) : null, moved: false, before: snapOf(oo) };
        svg.setPointerCapture(ev.pointerId);
      });
      svg.addEventListener('pointermove', (ev) => {
        readMods(ev);
        if (mode === 'pick' || mode === 'draw') { hoverRaw = toCm(ev); hover = constrainTemp(hoverRaw); render(); return; }
        if (!drag) return;
        if (drag.mode === 'crop') { const q = toCm(ev); cropPrev = { x0: drag.start.x, y0: drag.start.y, x1: q.x, y1: q.y }; render(); return; }
        if (drag.mode === 'bg') {
          const b = (floors().find(f => f.id === floor) || {}).background, q = toCm(ev);
          if (b) { b.x = Math.round(drag.orig.x + q.x - drag.start.x); b.y = Math.round(drag.orig.y + q.y - drag.start.y); render(); }
          return;
        }
        const o = find(drag.kind, drag.id), pt = toCm(ev);
        if (drag.mode === 'vertex') {
          drag.moved = true;
          o.points[drag.idx] = constrainVertex(o.points, drag.idx, pt);
          fitBox(o);
        } else if (drag.mode === 'move') {
          const dx = pt.x - drag.start.x, dy = pt.y - drag.start.y;
          if (!drag.moved && Math.hypot(dx, dy) < 3) return;
          drag.moved = true;
          const R = data.room;                               // der Mittelpunkt bleibt im Gebäude, sonst gehen Elemente «verloren»
          o.plan.x = clamp(snap(drag.orig.x + dx), -o.plan.w / 2, R.width_cm - o.plan.w / 2);
          o.plan.y = clamp(snap(drag.orig.y + dy), -o.plan.h / 2, R.height_cm - o.plan.h / 2);
          if (drag.origPoints) {                             // Vieleck: alle Ecken um denselben Betrag mitnehmen
            const ddx = o.plan.x - drag.orig.x, ddy = o.plan.y - drag.orig.y;
            o.points = drag.origPoints.map(q => [q[0] + ddx, q[1] + ddy]);
          }
        } else {                                             // Grösse: im Eigensystem des (gedrehten) Elements, Gegenkante bleibt stehen
          const og = drag.orig, h = drag.handle;
          const c0 = { x: og.x + og.w / 2, y: og.y + og.h / 2 };
          const loc = rotateBack(pt, { plan: og });
          let L = og.x, Tp = og.y, R = og.x + og.w, B = og.y + og.h;
          if (h.includes('w')) L = Math.min(snap(loc.x), R - 10);
          if (h.includes('e')) R = Math.max(snap(loc.x), L + 10);
          if (h.includes('n')) Tp = Math.min(snap(loc.y), B - 10);
          if (h.includes('s')) B = Math.max(snap(loc.y), Tp + 10);
          const w = R - L, hh = B - Tp, a = (og.rot || 0) * Math.PI / 180;
          const dx = (L + w / 2) - c0.x, dy = (Tp + hh / 2) - c0.y;      // neue Mitte, in die Welt zurückgedreht
          const cw = { x: c0.x + dx * Math.cos(a) - dy * Math.sin(a), y: c0.y + dx * Math.sin(a) + dy * Math.cos(a) };
          o.plan.w = w; o.plan.h = hh;
          o.plan.x = cw.x - w / 2; o.plan.y = cw.y - hh / 2;
        }
        render();
      });
      const end = () => {
        if (!drag) return;
        const d = drag; drag = null;
        if (d.mode === 'crop') {
          const r = cropPrev, cb = cropCb; cropPrev = null; cropCb = null; mode = null; svg.style.cursor = ''; document.removeEventListener('keydown', onKey);
          render(); if (opts.onMode) opts.onMode(null, 0);
          if (r && cb && Math.abs(r.x1 - r.x0) > 20 && Math.abs(r.y1 - r.y0) > 20) cb(r);
          return;
        }
        if (d.mode === 'bg') {
          svg.style.cursor = 'grab';
          const b = (floors().find(f => f.id === floor) || {}).background;
          if (b && opts.onBackground) opts.onBackground(floor, { x: b.x, y: b.y }, d.orig);
          return;
        }
        const o = find(d.kind, d.id);
        if ((d.mode === 'move' && d.moved) || d.mode === 'resize' || (d.mode === 'vertex' && d.moved)) { emit(d.kind, o, d.before); if (opts.onSelect) opts.onSelect(selInfo()); }
      };
      svg.addEventListener('dblclick', (ev) => {
        if (mode === 'draw') {                               // Doppelklick schliesst den Raum (der zweite Klick hat einen doppelten Punkt gesetzt)
          const n = tmp.length;
          if (n > 1 && tmp[n - 1][0] === tmp[n - 2][0] && tmp[n - 1][1] === tmp[n - 2][1]) tmp.pop();
          if (tmp.length >= 3) finishTemp();
          return;
        }
        const t = ev.target;
        if (!(sel && sel.kind === 'room' && t.getAttribute && t.hasAttribute('data-vertex'))) return;
        const o = find('room', sel.id);
        if (o.points.length <= 3) return;
        const before = snapOf(o);
        o.points.splice(+t.getAttribute('data-vertex'), 1);
        fitBox(o); render(); emit('room', o, before);
      });
      svg.addEventListener('pointerup', end);
      svg.addEventListener('pointercancel', end);
    }

    // ── Zeichenmodi: Punkte wählen (Massstab) und Raum per Klick zeichnen ──
    function startTemp(m, max, cb) {
      cancelMode();
      mode = m; tmp = []; tmpMax = max; tmpCb = cb; hover = null; sel = null;
      if (opts.onMode) opts.onMode(mode, 0);
      svg.style.cursor = 'crosshair';
      document.addEventListener('keydown', onKey);
      document.addEventListener('keyup', onKeyUp);
      render();
      if (opts.onSelect) opts.onSelect(null);
    }
    function onKey(ev) {
      if (ev.key === 'Escape') cancelMode();
      else if (ev.key === 'Backspace' && tmp.length) { tmp.pop(); render(); }
      else if (['Shift', 'Control', 'Alt'].includes(ev.key)) { readMods(ev); if (hoverRaw) { hover = constrainTemp(hoverRaw); render(); } }   // Vorschau sofort anpassen
    }
    function onKeyUp(ev) { if (['Shift', 'Control', 'Alt'].includes(ev.key)) { readMods(ev); if (hoverRaw) { hover = constrainTemp(hoverRaw); render(); } } }
    const readMods = (ev) => { mods = { shift: !!ev.shiftKey, ctrl: !!ev.ctrlKey, alt: !!ev.altKey }; };
    // Winkel einrasten: Shift oder Strg = 0/90/180/270°, Alt = 45°-Schritte, jeweils von einem Bezugspunkt aus
    function snapAngle(ref, pt) {
      const step = (mods.shift || mods.ctrl) ? 90 : mods.alt ? 45 : 0;
      if (!step || !ref) return pt;
      const r = step * Math.PI / 180, dx = pt.x - ref[0], dy = pt.y - ref[1], d = Math.hypot(dx, dy), a = Math.round(Math.atan2(dy, dx) / r) * r;
      return { x: ref[0] + d * Math.cos(a), y: ref[1] + d * Math.sin(a) };
    }
    function constrainTemp(pt) {                              // beim Zeichnen: vom letzten Punkt (beim Massstab: vom ersten) aus
      const q = snapAngle(tmp.length ? tmp[tmp.length - 1] : null, pt);
      return mode === 'draw' ? { x: snap(q.x), y: snap(q.y) } : q;
    }
    function constrainVertex(points, i, pt) {                 // Ecke ziehen: Shift/Strg = rechtwinklig zu beiden Nachbarn, Alt = 45° zur vorigen Ecke
      const n = points.length, prev = points[(i + n - 1) % n], next = points[(i + 1) % n];
      if (mods.shift || mods.ctrl) {
        const A = [prev[0], next[1]], B = [next[0], prev[1]];
        const q = Math.hypot(pt.x - A[0], pt.y - A[1]) <= Math.hypot(pt.x - B[0], pt.y - B[1]) ? A : B;
        return [snap(q[0]), snap(q[1])];
      }
      const q = snapAngle(prev, pt);
      return [snap(q.x), snap(q.y)];
    }
    function cancelMode() {
      if (mode === 'pick' || mode === 'draw' || mode === 'crop') { document.removeEventListener('keydown', onKey); document.removeEventListener('keyup', onKeyUp); mode = null; tmp = []; tmpCb = null; cropPrev = null; cropCb = null; drag = null; hover = null; svg.style.cursor = ''; render(); if (opts.onMode) opts.onMode(null, 0); }
    }
    function finishTemp() {
      const pts = tmp, cb = tmpCb;
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('keyup', onKeyUp);
      mode = null; tmp = []; tmpCb = null; hover = null; svg.style.cursor = '';
      render();
      if (opts.onMode) opts.onMode(null, 0);
      if (cb) cb(pts);
    }
    function addTemp(pt) {
      const q = mode === 'draw' ? [snap(pt.x), snap(pt.y)] : [Math.round(pt.x), Math.round(pt.y)];
      if (mode === 'draw' && tmp.length >= 3 && Math.hypot(q[0] - tmp[0][0], q[1] - tmp[0][1]) < 25) { finishTemp(); return; }   // auf den ersten Punkt klicken schliesst
      tmp.push(q);
      if (mode === 'pick' && tmp.length >= tmpMax) { finishTemp(); return; }
      render();
      if (opts.onMode) opts.onMode(mode, tmp.length);
    }
    function drawTemp() {                                    // Vorschau der gerade gesetzten Punkte
      if (mode === 'crop' && cropPrev) {
        const g0 = svgEl('g', { 'pointer-events': 'none' }, svg), r = cropPrev;
        svgEl('rect', { x: Math.min(r.x0, r.x1), y: Math.min(r.y0, r.y1), width: Math.abs(r.x1 - r.x0), height: Math.abs(r.y1 - r.y0), fill: 'rgba(244,166,34,.12)', stroke: 'var(--accent)', 'stroke-width': 3, 'stroke-dasharray': '14 8', 'vector-effect': 'non-scaling-stroke' }, g0);
        return;
      }
      if (!(mode === 'pick' || mode === 'draw') || !tmp.length) return;
      const g = svgEl('g', { 'pointer-events': 'none' }, svg);
      const pts = tmp.concat(hover && mode === 'draw' ? [[snap(hover.x), snap(hover.y)]] : (hover ? [[hover.x, hover.y]] : []));
      svgEl('polyline', { points: pts.map(q => q.join(',')).join(' '), fill: mode === 'draw' ? 'rgba(244,166,34,.15)' : 'none', stroke: 'var(--accent)', 'stroke-width': 4, 'stroke-dasharray': '12 8' }, g);
      tmp.forEach((q, i) => svgEl('circle', { cx: q[0], cy: q[1], r: i === 0 && mode === 'draw' ? 14 : 9, fill: 'var(--accent)', stroke: '#000', 'stroke-width': 2 }, g));
      if (hover) {                                           // Länge der aktuellen Strecke und Winkel direkt am Mauszeiger
        const a = tmp[tmp.length - 1], hx = mode === 'draw' ? snap(hover.x) : hover.x, hy = mode === 'draw' ? snap(hover.y) : hover.y;
        const len = Math.hypot(hx - a[0], hy - a[1]), ang = Math.round(((Math.atan2(hy - a[1], hx - a[0]) * 180 / Math.PI) + 360) % 360);
        const t = svgEl('text', { x: hx + 18, y: hy - 14, 'font-size': Math.max(14, data.room.width_cm / 70), 'font-weight': 700, fill: 'var(--accent)', stroke: 'var(--surface)', 'stroke-width': 5, 'paint-order': 'stroke' }, g);
        t.textContent = `${(len / 100).toFixed(2).replace('.', ',')} m · ${ang}°`;
      }
    }

    // ── Zoom für Touch-Geräte (Gäste-Seite): ganzer Plan sichtbar, Knöpfe, Pinch, Strg+Mausrad ──
    let zoom = 1;
    function fitWidth() {
      const vb = (svg.getAttribute('viewBox') || '0 0 1 1').split(' ').map(Number), ratio = (vb[2] / vb[3]) || 1;
      return Math.max(120, Math.min(wrap.clientWidth - 4, window.innerHeight * 0.66 * ratio));          // ganzer Plan: Breite des Feldes, höchstens ~2/3 der Fensterhöhe
    }
    function applyZoom() { if (zoomable) svg.style.width = Math.round(fitWidth() * zoom) + 'px'; }
    function setZoom(z, cx, cy) {                            // cx/cy: Bildschirmpunkt, der unter dem Finger/Zeiger stehen bleibt
      z = Math.min(Math.max(z, 1), 8);
      if (Math.abs(z - zoom) < 0.001) return;
      const wr = wrap.getBoundingClientRect(), ax = cx == null ? wr.left + wr.width / 2 : cx, ay = cy == null ? wr.top + wr.height / 2 : cy;
      const s0 = svg.getBoundingClientRect(), fx = (ax - s0.left) / (s0.width || 1), fy = (ay - s0.top) / (s0.height || 1);
      zoom = z; applyZoom();
      const s1 = svg.getBoundingClientRect();
      wrap.scrollLeft += (s1.left + fx * s1.width) - ax;
      wrap.scrollTop += (s1.top + fy * s1.height) - ay;
    }
    if (zoomable) {
      const btns = document.createElement('div');
      btns.className = 'invplan-zoombtns';
      btns.innerHTML = '<button type="button" data-z="in" aria-label="Vergrössern">＋</button><button type="button" data-z="out" aria-label="Verkleinern">−</button><button type="button" data-z="fit" aria-label="Ganzen Plan zeigen" title="Ganzer Plan">⤢</button>';
      btns.addEventListener('click', (e) => {
        const z = e.target.getAttribute && e.target.getAttribute('data-z');
        if (z === 'in') setZoom(zoom * 1.5); else if (z === 'out') setZoom(zoom / 1.5);
        else if (z === 'fit') { zoom = 1; applyZoom(); wrap.scrollLeft = 0; wrap.scrollTop = 0; }
      });
      stage.appendChild(btns);
      let pinch = null;
      const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
      wrap.addEventListener('touchstart', (e) => { if (e.touches.length === 2) pinch = { d: dist(e.touches) || 1, z: zoom }; }, { passive: true });
      wrap.addEventListener('touchmove', (e) => {
        if (!pinch || e.touches.length !== 2) return;
        e.preventDefault();                                  // sonst zoomt iOS die ganze Seite statt des Plans
        setZoom(pinch.z * dist(e.touches) / pinch.d, (e.touches[0].clientX + e.touches[1].clientX) / 2, (e.touches[0].clientY + e.touches[1].clientY) / 2);
      }, { passive: false });
      wrap.addEventListener('touchend', (e) => { if (e.touches.length < 2) pinch = null; }, { passive: true });
      wrap.addEventListener('wheel', (e) => {                // Trackpad/Maus: Strg+Rad oder Pinch-Geste
        if (!(e.ctrlKey || e.metaKey)) return;
        e.preventDefault();
        setZoom(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), e.clientX, e.clientY);
      }, { passive: false });
      window.addEventListener('resize', applyZoom);
    }

    function fitBox(o) {                                     // Umgebung der Eckpunkte → plan.x/y/w/h
      const xs = o.points.map(q => q[0]), ys = o.points.map(q => q[1]);
      o.plan.x = Math.min(...xs); o.plan.y = Math.min(...ys);
      o.plan.w = Math.max(5, Math.max(...xs) - o.plan.x); o.plan.h = Math.max(5, Math.max(...ys) - o.plan.y);
    }
    function emit(kind, o, before) { if (opts.onChange) opts.onChange(kind, o.id, o.plan, { points: kind === 'room' ? (o.points || null) : undefined, before }); }

    const api = {
      el: svg,
      setData(d) {
        data = d;
        if (sel) { const o = find(sel.kind, sel.id); if (!o || !o.plan) sel = null; }
        render();
      },
      setFloor(id) {
        floor = id;
        if (sel) { const o = find(sel.kind, sel.id); if (!o || !visible(sel.kind, o)) sel = null; }
        render();
        if (opts.onFloor) opts.onFloor(floor);
        if (opts.onSelect) opts.onSelect(selInfo());
      },
      floorId() { ensureFloor(); return floor; },
      setHighlight(h) {
        hl = Object.assign({ codes: [], machineIds: [], areaCodes: [] }, h || {});
        if (anyHl()) {                                       // Treffer auf einem anderen Stockwerk: dorthin wechseln
          const hits = [];
          for (const k of ['furniture', 'machine', 'area']) for (const o of list(k)) if (o.plan && isHit(k, o)) hits.push(floorOf(k, o));
          if (hits.length && !hits.includes(floor)) { floor = hits[0]; if (opts.onFloor) opts.onFloor(floor); }
        }
        render();
      },
      zoomTo(z) { zoom = Math.min(Math.max(z, 1), 8); applyZoom(); },
      zoomFit() { zoom = 1; applyZoom(); wrap.scrollLeft = 0; wrap.scrollTop = 0; },
      cropRect(cb) {                                         // Rechteck aufziehen → cb({x0,y0,x1,y1}) in Plan-cm
        cancelMode(); mode = 'crop'; cropCb = cb; cropPrev = null; svg.style.cursor = 'crosshair';
        document.addEventListener('keydown', onKey);
        if (opts.onMode) opts.onMode('crop', 0);
      },
      setMode(m) {                                           // 'bg' = Grundriss verschieben, sonst aus
        if (m === 'bg') { cancelMode(); mode = 'bg'; svg.style.cursor = 'grab'; }
        else if (mode === 'bg') { mode = null; svg.style.cursor = ''; }
        if (opts.onMode) opts.onMode(mode, 0);
      },
      mode() { return mode; },
      pickPoints(n, cb) { startTemp('pick', n, cb); },
      drawPolygon(cb) { startTemp('draw', 0, cb); },
      cancelMode,
      setBackground(floorId, patch) { const f = floors().find(x => x.id === floorId); if (f && f.background) Object.assign(f.background, patch); render(); },
      select(kind, id) { setSelection(kind ? { kind, id } : null); },
      selected: selInfo,
      clientToCm: toCm,
      scrollToHighlight() {                                  // markiertes Element in die Mitte des Ausschnitts holen (Handy)
        const hit = svg.querySelector('.invplan-hit');
        if (!hit) return;
        const a = hit.getBoundingClientRect(), b = wrap.getBoundingClientRect();
        wrap.scrollLeft += (a.left + a.width / 2) - (b.left + b.width / 2);
        wrap.scrollTop += (a.top + a.height / 2) - (b.top + b.height / 2);
      },
      place(kind, id, at) {                                  // unplatziertes Element auf das aktuelle Stockwerk setzen
        const o = find(kind, id); if (!o) return;
        const sz = kind === 'furniture' ? (DEFAULT_SIZE.furniture[o.kind] || [100, 50]) : DEFAULT_SIZE[kind];
        const c = at || { x: data.room.width_cm / 2, y: data.room.height_cm / 2 };
        ensureFloor();
        o.plan = { x: clamp(snap(c.x - sz[0] / 2), -sz[0] / 2, data.room.width_cm - sz[0] / 2), y: clamp(snap(c.y - sz[1] / 2), -sz[1] / 2, data.room.height_cm - sz[1] / 2),
          w: sz[0], h: sz[1], rot: 0, floor_id: floor };
        emit(kind, o, { plan: null, points: null }); setSelection({ kind, id });
      },
      update(kind, id, patch) {
        const o = find(kind, id); if (!o || !o.plan) return;
        const snapBefore = snapOf(o), before = Object.assign({}, o.plan);
        Object.assign(o.plan, patch);
        if (o.points && before.w && before.h && ['x', 'y', 'w', 'h'].some(k => k in patch)) {
          o.points = o.points.map(q => [o.plan.x + (q[0] - before.x) / before.w * o.plan.w, o.plan.y + (q[1] - before.y) / before.h * o.plan.h]);
        }
        const R = data.room;
        o.plan.x = clamp(o.plan.x, -o.plan.w / 2, R.width_cm - o.plan.w / 2);
        o.plan.y = clamp(o.plan.y, -o.plan.h / 2, R.height_cm - o.plan.h / 2);
        if (kind !== 'room' && patch.floor_id != null && patch.floor_id !== floor) sel = null;      // auf anderes Stockwerk verschoben
        render(); emit(kind, o, snapBefore);
        if (opts.onSelect) opts.onSelect(selInfo());
      },
      toPolygon(id) {                                        // Rechteck-Raum → Vieleck mit vier Ecken
        const o = find('room', id); if (!o || !o.plan || o.kind !== 'raum' || o.points) return;
        const p = o.plan;
        const before = snapOf(o);
        o.points = [[p.x, p.y], [p.x + p.w, p.y], [p.x + p.w, p.y + p.h], [p.x, p.y + p.h]];
        emit('room', o, before); setSelection({ kind: 'room', id });
      },
      toRect(id) {                                           // Vieleck → Rechteck der Umgebung
        const o = find('room', id); if (!o || !o.points) return;
        const before = snapOf(o);
        o.points = null;
        emit('room', o, before); setSelection({ kind: 'room', id });
      },
      remove(kind, id) {
        const o = find(kind, id); if (!o) return;
        const before = snapOf(o);
        o.plan = null;
        if (sel && sel.kind === kind && sel.id === id) sel = null;
        render(); if (opts.onChange) opts.onChange(kind, id, null, { before });
        if (opts.onSelect) opts.onSelect(selInfo());
      },
    };
    render();
    return api;
  }

  window.InvPlan = { mount, furnitureCode };
})();
