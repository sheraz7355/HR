/* Document form UI layer — sales and purchase invoices.
 *
 * Loaded after each form's own script, configured by window.DOC (set inline
 * by the template, because it carries URLs and permissions). It replaces or
 * wraps a few of the form's globals — rebuildActionBar, saveInvoice,
 * unapproveInvoice, markDirty, addRow, recalc — and keeps every element id
 * the rest of the form and the E2E suite address.
 *
 * States: new (never saved) · draft (saved, editable) · approved (locked).
 * - A saved draft stays editable. It used to freeze every field after the
 *   first save until the page was reloaded.
 * - Save is lit only when there is something to save.
 * - Approve and unapprove reload the page, so the locked/unlocked state, the
 *   lock notice and the FBR buttons always come from the server.
 * - One primary action per state; rare actions live in a "More" menu; on a
 *   phone the bar is pinned to the bottom of the screen.
 * - Forms without their own shortcuts get Ctrl+S / Ctrl+Shift+S / Ctrl+P /
 *   Alt+N / Alt+C, an unsaved-changes guard and Esc layering.
 */
(function () {
  'use strict';
  var DOC = window.DOC || {};
  function $(s, c) { return (c || document).querySelector(s); }
  function $$(s, c) { return (c || document).querySelectorAll(s); }
  function viewUrl(id) { return DOC.viewBase + id; }

  // ── shortcuts / dirty guard for forms that have none ──────────────────
  if (typeof window.leaveTo !== 'function') {
    window.formDirty = false;
    window.leaveTo = function (dest) {
      if (window.formDirty && DOC.editable) {
        showConfirm('Discard unsaved changes?', 'This document has changes that were not saved. Leave anyway?',
          function () { window.formDirty = false; window.location.href = dest; });
        return;
      }
      window.location.href = dest;
    };
    window.doSave = function () {
      if (!DOC.editable) { toast('Approved documents are locked — unapprove to edit', 'info'); return; }
      var b = $('#saveBtn');
      if (b && !b.disabled) b.click(); else toast('Nothing to save', 'info');
    };
    window.doSaveApprove = function () {
      if (!DOC.editable) { toast('Already approved', 'info'); return; }
      var b = $('#saveApproveBtn');
      if (!b) { toast('Approval rights required', 'warning'); return; }
      if (!b.disabled) b.click();
    };
    window.doPrint = function () {
      if (window.formDirty && DOC.editable) { toast('Save your changes before printing', 'warning'); return; }
      if (!$('#invoiceId').value) { toast('Save the document before printing', 'warning'); return; }
      window.print();
    };
    window.escapeLayer = function () {
      var pop = $('#chgPopover'); if (pop && pop.classList.contains('show') && window.closeChgPopover) { closeChgPopover(); return; }
      var mods = [['chargesModal', 'closeChargesModal'], ['orderModal', 'closeOrderModal'], ['confirmModal', 'closeConfirm']];
      for (var i = 0; i < mods.length; i++) {
        var m = document.getElementById(mods[i][0]);
        if (m && m.classList.contains('show') && typeof window[mods[i][1]] === 'function') { window[mods[i][1]](); return; }
      }
      var panel = $('#sidePanel'); if (panel && panel.classList.contains('open') && window.closeSidePanel) { closeSidePanel(); return; }
      var dd = $('.ac-dd.show'); if (dd) dd.classList.remove('show');
    };
    var inForm = function (el) {
      return !!(el && el.closest && (el.closest('.hdr-strip') || el.closest('#itemsBody') || el.closest('.btm') ||
        el.closest('#sidePanel') || el.closest('.ga') || el.closest('#chargesModal')));
    };
    document.addEventListener('input', function (e) {
      var t = e.target; if (!inForm(t) || t.closest('.ac-dd')) return;
      if (/Search$/.test(t.id || '')) return;   // raw typing in a picker is not yet document state
      window.markDirty();
    }, true);
    document.addEventListener('change', function (e) { if (inForm(e.target)) window.markDirty(); }, true);
    document.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('#cancelBtn,#newBtn');
      if (!a || !(window.formDirty && DOC.editable)) return;
      e.preventDefault(); window.leaveTo(a.id === 'newBtn' ? DOC.newUrl : DOC.listUrl);
    });
    document.addEventListener('keydown', function (e) {
      var k = (e.key || '').toLowerCase(), mod = e.ctrlKey || e.metaKey;
      if (mod && !e.altKey && !e.shiftKey && (k === 's' || k === 'p')) { e.preventDefault(); if (k === 's') doSave(); else doPrint(); return; }
      if (mod && e.shiftKey && !e.altKey && k === 's') { e.preventDefault(); doSaveApprove(); return; }
      if (e.altKey && !mod && (k === 'n' || k === 'c')) { e.preventDefault(); leaveTo(k === 'n' ? DOC.newUrl : DOC.listUrl); return; }
      if (e.key === 'Escape' && !mod && !e.altKey && !e.shiftKey) escapeLayer();
    });
    window.addEventListener('beforeunload', function (e) {
      if (window.formDirty && DOC.editable) { e.preventDefault(); e.returnValue = ''; }
    });
  }

  // ── flash message carried across a reload ─────────────────────────────
  try {
    var f = sessionStorage.getItem('docFlash');
    if (f) { sessionStorage.removeItem('docFlash'); var o = JSON.parse(f); setTimeout(function () { toast(o.m, o.t || 'success'); }, 50); }
  } catch (e) { /* storage blocked: the page still works */ }
  function flashThenGo(msg, url) {
    try { sessionStorage.setItem('docFlash', JSON.stringify({ m: msg, t: 'success' })); } catch (e) { }
    window.formDirty = false; window.location.replace(url);
  }

  // ── action bar ────────────────────────────────────────────────────────
  function btn(cls, id, label, title) { return '<button type="button" class="btn ' + cls + '"' + (id ? ' id="' + id + '"' : '') + (title ? ' title="' + title + '"' : '') + '>' + label + '</button>'; }
  function link(cls, id, label, href, title) { return '<a class="btn ' + cls + '"' + (id ? ' id="' + id + '"' : '') + ' href="' + href + '"' + (title ? ' title="' + title + '"' : '') + '>' + label + '</a>'; }
  function mi(label, o) {
    o = o || {};
    var a = ' role="menuitem"' + (o.id ? ' id="' + o.id + '"' : '') + (o.act ? ' data-act="' + o.act + '"' : '') + ' class="' + (o.cls || '') + '"';
    var hint = o.hint ? '<span class="hint">' + o.hint + '</span>' : '';
    return o.href ? '<a' + a + ' href="' + o.href + '">' + label + hint + '</a>' : '<button type="button"' + a + '>' + label + hint + '</button>';
  }
  function menu(items) {
    return '<div class="ab-more"><button type="button" class="btn btn-o ab-more-btn" aria-haspopup="menu" aria-expanded="false">More <span aria-hidden="true">&#9662;</span></button>' +
      '<div class="ab-menu" role="menu">' + items.join('') + '</div></div>';
  }
  function closeMenus() {
    $$('.ab-more.open').forEach(function (m) { m.classList.remove('open'); var b = m.querySelector('.ab-more-btn'); if (b) b.setAttribute('aria-expanded', 'false'); });
  }
  window.closeDocMenus = closeMenus;
  document.addEventListener('click', function (e) { if (!e.target.closest || !e.target.closest('.ab-more')) closeMenus(); });
  if (typeof window.escapeLayer === 'function') {
    var prevEsc = window.escapeLayer;
    window.escapeLayer = function () { if ($('.ab-more.open')) { closeMenus(); return; } prevEsc(); };
  }

  window.rebuildActionBar = function (st) {
    var bar = $('.ab'); if (!bar) return;
    if (st === 'saved' || st === 'unapproved') st = 'draft';
    bar.dataset.state = st;
    var h = [], noun = DOC.noun || 'invoice';
    if (st === 'new') {
      h.push(link('btn-o', 'cancelBtn', 'Cancel', DOC.listUrl, 'Back to the list without saving (Alt+C)'));
      h.push(btn('btn-p', 'saveBtn', 'Save draft', 'Save as a draft (Ctrl+S)'));
      if (DOC.canApprove) h.push(btn('btn-s', 'saveApproveBtn', 'Save &amp; approve', 'Save, post to the ledger and lock (Ctrl+Shift+S)'));
    } else if (st === 'draft') {
      h.push(menu([mi('New ' + noun, { id: 'newBtn', href: DOC.newUrl, hint: 'Alt+N' }),
        mi('Print', { act: 'print', cls: 'only-sm', hint: 'Ctrl+P' }),
        mi('Back to list', { act: 'back', cls: 'only-sm', hint: 'Alt+C' }),
        '<hr>', mi('Delete draft', { id: 'deleteBtn', cls: 'danger' })]));
      h.push(link('btn-o hide-sm', 'cancelBtn', 'Back to list', DOC.listUrl, 'Back to the list (Alt+C)'));
      h.push(btn('btn-o hide-sm', 'printBtn', 'Print', 'Print (Ctrl+P)'));
      h.push(btn('btn-p is-clean', 'saveBtn', 'Save', 'Save changes (Ctrl+S)'));
      if (DOC.canApprove) h.push(btn('btn-s', 'saveApproveBtn', 'Approve', 'Save, post to the ledger and lock (Ctrl+Shift+S)'));
    } else {
      var mm = [mi('New ' + noun, { id: 'newBtn', href: DOC.newUrl, hint: 'Alt+N' }),
        mi('Back to list', { act: 'back', cls: 'only-sm', hint: 'Alt+C' })];
      if (DOC.fbr) mm.push(mi('Validate with FBR', { id: 'validateFbrBtn' }));
      if (DOC.canApprove) { mm.push('<hr>'); mm.push(mi('Unapprove', { id: 'unapproveBtn', cls: 'danger', hint: 'reverses the posting' })); }
      h.push(menu(mm));
      h.push(link('btn-o hide-sm', 'cancelBtn', 'Back to list', DOC.listUrl, 'Back to the list (Alt+C)'));
      if (DOC.fbr) h.push(btn('btn-o', 'submitFbrBtn', 'Send to FBR'));
      h.push(btn('btn-s', 'printBtn', 'Print', 'Print (Ctrl+P)'));
    }
    bar.innerHTML = h.join('');
    var sb = $('#saveBtn');
    if (sb) { sb.addEventListener('click', function () { saveInvoice('save'); }); if (st === 'draft') sb.disabled = !window.formDirty; }
    var sa = $('#saveApproveBtn');
    if (sa) sa.addEventListener('click', function () {
      showConfirm(st === 'new' ? 'Save & Approve' : 'Approve ' + noun, DOC.approveMsg, function () { saveInvoice('approve'); });
    });
    var pb = $('#printBtn'); if (pb) pb.addEventListener('click', function () { doPrint(); });
    var db = $('#deleteBtn');
    if (db) db.addEventListener('click', function () { closeMenus(); showConfirm('Delete draft', 'Delete this draft ' + noun + '? This cannot be undone.', deleteInvoice); });
    var ub = $('#unapproveBtn');
    if (ub) ub.addEventListener('click', function () { closeMenus(); showConfirm('Unapprove ' + noun, DOC.unapproveMsg, unapproveInvoice); });
    if (DOC.fbr && typeof window.wireFbrBtns === 'function') wireFbrBtns();
    $$('.ab [data-act]').forEach(function (el) {
      el.addEventListener('click', function () {
        closeMenus();
        if (el.dataset.act === 'print') doPrint(); else if (el.dataset.act === 'back') leaveTo(DOC.listUrl);
      });
    });
    var mb = $('.ab-more-btn');
    if (mb) mb.addEventListener('click', function (e) {
      e.stopPropagation();
      var box = mb.parentElement, open = !box.classList.contains('open');
      closeMenus(); box.classList.toggle('open', open); mb.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) { var first = box.querySelector('.ab-menu [role=menuitem]'); if (first) first.focus(); }
    });
  };

  // Save lights up only when there is something to save.
  window.markDirty = function () {
    window.formDirty = true;
    var b = $('#saveBtn'), bar = $('.ab');
    if (b && bar && bar.dataset.state === 'draft') { b.disabled = false; b.classList.remove('is-clean'); }
  };

  window.saveInvoice = async function (action) {
    var data;
    try { data = collectData(); } catch (e) { toast('Form error: ' + e.message, 'error'); return; }
    if (!data[DOC.partyKey]) { toast('Please select a ' + DOC.partyNoun, 'error'); var ps = document.getElementById(DOC.partySearch); if (ps) ps.focus(); return; }
    if (!data.items || data.items.length === 0) { toast('Add at least one item', 'error'); return; }
    data.action = action;
    var btns = $$('.ab .btn'); btns.forEach(function (b) { b.disabled = true; });
    var res;
    try {
      var r = await fetch(DOC.saveUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
      res = await r.json();
    } catch (e) { toast('Network or server error: ' + e.message, 'error'); btns.forEach(function (b) { b.disabled = false; }); return; }
    if (!res.ok) { toast(res.error || 'Save failed', 'error'); btns.forEach(function (b) { b.disabled = false; }); return; }
    var status = res.voucher_status || res.status, number = res.number || res.voucher;
    $('#invoiceId').value = res.id;
    if (res.number && $('#invNumber')) $('#invNumber').value = res.number;
    if (res.voucher && $('#invVoucher')) $('#invVoucher').value = res.voucher;
    if (status === 'approved') { flashThenGo(res.message, viewUrl(res.id)); return; }
    toast(res.message, 'success');
    var t = $('#docTitle'); if (t) t.textContent = number;
    document.title = number + ' · ' + DOC.title;
    try { history.replaceState(null, '', viewUrl(res.id)); } catch (e) { }
    var badge = $('#statusBadge'); if (badge) { badge.className = 'bdg bdg-unapproved'; badge.textContent = 'Draft'; }
    window.formDirty = false;
    rebuildActionBar('draft');
    if (typeof recalc === 'function') recalc();
  };

  window.unapproveInvoice = async function () {
    var id = $('#invoiceId').value; if (!id) return;
    var mb = $('.ab-more-btn'); if (mb) { mb.disabled = true; mb.textContent = 'Unapproving…'; }
    var res;
    try { var r = await fetch(DOC.unapproveBase + id, { method: 'POST' }); res = await r.json(); } catch (e) { res = { ok: false, error: e.message }; }
    if (!res.ok) { toast(res.error || 'Unapprove failed', 'error'); if (mb) { mb.disabled = false; mb.textContent = 'More'; } return; }
    flashThenGo(res.message || 'Unapproved', viewUrl(id));
  };

  // ── payment terms → due date (forms that have both) ───────────────────
  (function () {
    var sel = $('#payTerms'), inv = $('#invDate'), due = $('#dueDate'); if (!sel || !inv || !due) return;
    function addDays(iso, n) {
      var d = new Date(iso + 'T00:00:00'); if (isNaN(d)) return '';
      d.setDate(d.getDate() + n);
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }
    function apply() { if (sel.value === '' || !inv.value) return; due.value = addDays(inv.value, parseInt(sel.value, 10)); }
    sel.addEventListener('change', apply);
    inv.addEventListener('change', apply);
    due.addEventListener('change', function () {
      if (sel.value !== '' && due.value !== addDays(inv.value, parseInt(sel.value, 10))) sel.value = '';
    });
    if (inv.value && due.value) {
      var diff = Math.round((new Date(due.value) - new Date(inv.value)) / 864e5);
      sel.value = sel.querySelector('option[value="' + diff + '"]') ? String(diff) : '';
    }
  })();

  // ── line items: phone card labels; descriptions that never clip ──────
  function labelRows() {
    var ths = $$('#itemsTable thead th');
    $$('#itemsBody tr').forEach(function (tr) {
      Array.prototype.forEach.call(tr.children, function (td, i) {
        var th = ths[i]; if (!th) return;
        var t = (th.textContent || '').trim();
        if (t && t !== '#') td.dataset.label = t;
        if (th.classList.contains('desc-col')) td.classList.add('c-desc');
        if (t === 'Code') td.classList.add('c-code');
        if (td.querySelector('.ra')) td.classList.add('c-act');
      });
    });
  }
  function fitDesc() {
    $$('#itemsBody .ac-desc-input').forEach(function (ta) {
      ta.style.height = 'auto'; var h = ta.scrollHeight; if (h > 0) ta.style.height = h + 'px';
    });
  }
  if (typeof window.addRow === 'function') {
    var _ar = window.addRow;
    window.addRow = function () { var r = _ar.apply(this, arguments); labelRows(); fitDesc(); return r; };
  }
  if (typeof window.recalc === 'function') {
    var _rc = window.recalc;
    window.recalc = function () { var r = _rc.apply(this, arguments); fitDesc(); return r; };
  }
  var fitT;
  window.addEventListener('resize', function () { clearTimeout(fitT); fitT = setTimeout(fitDesc, 120); });
  labelRows(); setTimeout(fitDesc, 0); setTimeout(fitDesc, 700);

  // ── read-only document: empty fields read "—" ────────────────────────
  if ($('#docWrap.is-locked')) {
    $$('.hdr-strip input:disabled').forEach(function (el) {
      if ((el.type === 'date' || el.type === 'time') && !el.value) { el.type = 'text'; el.value = '—'; }
      else if (!el.value && el.type !== 'hidden') el.placeholder = '—';
    });
    var pt = $('#payTerms');
    if (pt && pt.value === '') { var o0 = pt.querySelector('option[value=""]'); if (o0) o0.textContent = '—'; }
  }

  var bar0 = $('.ab');
  rebuildActionBar(bar0 ? bar0.dataset.state : 'new');
})();
