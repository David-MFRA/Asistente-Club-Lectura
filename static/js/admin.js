/* ═══════════════════════════════════════════════════
   ADMIN JS — funciones compartidas
   ═══════════════════════════════════════════════════ */

// ── DRAWER (menú móvil) ──────────────────────────────
function openDrawer() {
  const drawer = document.getElementById('drawer');
  const backdrop = document.getElementById('drawer-backdrop');
  const toggle = document.getElementById('drawer-toggle');
  if (!drawer || !backdrop) return;
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
  backdrop.classList.add('open');
  document.body.classList.add('drawer-open');
  if (toggle) toggle.setAttribute('aria-expanded', 'true');
  const firstLink = drawer.querySelector('.drawer-link');
  if (firstLink) firstLink.focus();
}
function closeDrawer() {
  const drawer = document.getElementById('drawer');
  const backdrop = document.getElementById('drawer-backdrop');
  const toggle = document.getElementById('drawer-toggle');
  if (!drawer || !backdrop) return;
  drawer.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
  backdrop.classList.remove('open');
  document.body.classList.remove('drawer-open');
  if (toggle) toggle.setAttribute('aria-expanded', 'false');
}
document.getElementById('drawer-backdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    closeDrawer();
    closeAI();
  }
});

// Marcar drawer-link activo según URL actual
(function() {
  const path = window.location.pathname;
  document.querySelectorAll('.drawer-link').forEach(link => {
    const href = link.getAttribute('href');
    if (href && href !== '#' && path === href) link.classList.add('active');
  });
})();

// ── AI MODAL ────────────────────────────────────────
function openAI() {
  document.getElementById('ai-modal').classList.add('open');
  document.getElementById('ai-backdrop').classList.add('open');
  setTimeout(() => {
    const inp = document.getElementById('ai-input');
    if (inp) inp.focus();
  }, 100);
}
function closeAI() {
  document.getElementById('ai-modal').classList.remove('open');
  document.getElementById('ai-backdrop').classList.remove('open');
}
function askAI(q) {
  const inp = document.getElementById('ai-input');
  if (inp) inp.value = q;
  sendAI();
}
async function sendAI() {
  const input = document.getElementById('ai-input');
  const msgs  = document.getElementById('ai-messages');
  const btn   = document.getElementById('ai-send');
  if (!input || !msgs) return;
  const q = input.value.trim();
  if (!q) return;
  input.value = '';
  if (btn) btn.disabled = true;

  const userEl = document.createElement('div');
  userEl.className = 'ai-message ai-message-user';
  userEl.textContent = q;
  msgs.appendChild(userEl);

  const thinkEl = document.createElement('div');
  thinkEl.className = 'ai-message ai-message-bot ai-thinking';
  thinkEl.textContent = '⏳ Pensando…';
  msgs.appendChild(thinkEl);
  msgs.scrollTop = msgs.scrollHeight;

  try {
    const resp = await fetch('/admin/ai/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q })
    });
    const data = await resp.json();
    thinkEl.className = 'ai-message ai-message-bot';
    thinkEl.textContent = data.answer || data.error || 'Sin respuesta';
  } catch(e) {
    thinkEl.className = 'ai-message ai-message-error';
    thinkEl.textContent = 'Error de conexión';
  }

  if (btn) btn.disabled = false;
  msgs.scrollTop = msgs.scrollHeight;
}

// Enter en el input de la IA
(function() {
  const inp = document.getElementById('ai-input');
  if (inp) {
    inp.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAI(); }
    });
  }
})();

// ── TABS ─────────────────────────────────────────────
function showTab(name, el) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  const target = document.getElementById('tab-' + name);
  if (target) target.classList.add('active');
  if (el) el.classList.add('active');
}

// ── INLINE EDIT ──────────────────────────────────────
function startEdit(id) {
  const name = document.getElementById('tname-' + id);
  const btns = document.getElementById('tbtns-' + id);
  const edit = document.getElementById('tedit-' + id);
  if (name) name.style.display = 'none';
  if (btns) btns.style.display = 'none';
  if (edit) {
    edit.style.display = 'flex';
    const inp = edit.querySelector('input');
    if (inp) inp.focus();
  }
}
function cancelEdit(id) {
  const name = document.getElementById('tname-' + id);
  const btns = document.getElementById('tbtns-' + id);
  const edit = document.getElementById('tedit-' + id);
  if (name) name.style.display = '';
  if (btns) btns.style.display = 'flex';
  if (edit) edit.style.display = 'none';
}

// ── TOGGLE VISIBILITY ────────────────────────────────
function toggleEl(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = (el.style.display === 'none' || !el.style.display) ? 'block' : 'none';
}
function toggleNotes(id) { toggleEl('notes-form-' + id); }

// ── AUTO-HIDE FLASH MESSAGES ─────────────────────────
setTimeout(function() {
  document.querySelectorAll('.flash').forEach(function(el) {
    el.style.transition = 'opacity .5s ease';
    el.style.opacity = '0';
    setTimeout(function() { el.remove(); }, 500);
  });
}, 4000);

// ── PAGE TOUR ENGINE ─────────────────────────────────
// Each page sets window.PAGE_TOUR = [{selector, title, desc}, ...]
let _pgTourStep = 0;
let _pgTourTimer = null;

function startPageTour() {
  const steps = window.PAGE_TOUR;
  const ov = document.getElementById('tour-overlay');
  if (!ov) return;
  if (!steps || !steps.length) {
    document.getElementById('tour-title').textContent = '🎯 Tour no disponible';
    document.getElementById('tour-desc').textContent = 'No hay tour guiado configurado para esta página.';
    document.getElementById('tour-counter').textContent = '—';
    const prevBtn = document.getElementById('tour-prev');
    if (prevBtn) prevBtn.style.display = 'none';
    const nextBtn = document.getElementById('tour-next');
    if (nextBtn) nextBtn.textContent = 'Cerrar';
    const tt = document.getElementById('tour-tooltip');
    if (tt) { tt.style.display='block'; tt.style.position='fixed'; tt.style.top='50%'; tt.style.left='50%'; tt.style.transform='translate(-50%,-50%)'; tt.style.zIndex='9999'; }
    ov.style.display = 'block';
    return;
  }
  _pgTourStep = 0;
  const prevBtn = document.getElementById('tour-prev');
  if (prevBtn) prevBtn.style.display = '';
  ov.style.display = 'block';
  _showPgTourStep();
}

function _endPageTour() {
  clearTimeout(_pgTourTimer);
  ['tour-overlay','tour-highlight','tour-tooltip'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}

function _showPgTourStep() {
  const steps = window.PAGE_TOUR || [];
  const step = steps[_pgTourStep];
  if (!step) { _endPageTour(); return; }
  const targetEl = step.selector ? document.querySelector(step.selector) : null;
  const tooltip = document.getElementById('tour-tooltip');
  const hl = document.getElementById('tour-highlight');
  const titleEl = document.getElementById('tour-title');
  const descEl  = document.getElementById('tour-desc');
  const ctrEl   = document.getElementById('tour-counter');
  const prevBtn = document.getElementById('tour-prev');
  const nextBtn = document.getElementById('tour-next');
  if (titleEl) titleEl.textContent = step.title;
  if (descEl)  descEl.textContent  = step.desc;
  if (ctrEl)   ctrEl.textContent   = `${_pgTourStep+1} / ${steps.length}`;
  if (prevBtn) prevBtn.disabled = (_pgTourStep === 0);
  if (nextBtn) nextBtn.textContent = (_pgTourStep === steps.length-1) ? 'Finalizar' : 'Siguiente →';
  if (hl) hl.style.display = 'none';
  if (tooltip) tooltip.style.display = 'none';
  if (targetEl) {
    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    clearTimeout(_pgTourTimer);
    _pgTourTimer = setTimeout(() => {
      const rect = targetEl.getBoundingClientRect();
      const sy = window.scrollY;
      if (hl) hl.style.cssText = `display:block;position:absolute;top:${rect.top+sy-6}px;left:${rect.left-6}px;width:${rect.width+12}px;height:${rect.height+12}px;border:2px solid #6366f1;border-radius:14px;box-shadow:0 0 0 4000px rgba(0,0,0,.55);pointer-events:none;z-index:9998`;
      const ttTop = rect.bottom + sy + 14;
      const ttLeft = Math.max(8, Math.min(rect.left, window.innerWidth - 336));
      if (tooltip) {
        tooltip.style.display = 'block';
        tooltip.style.position = 'absolute';
        tooltip.style.top = ttTop + 'px';
        tooltip.style.left = ttLeft + 'px';
        tooltip.style.transform = '';
        tooltip.style.zIndex = '9999';
      }
    }, 250);
  } else {
    if (hl) hl.style.display = 'none';
    if (tooltip) {
      tooltip.style.display = 'block';
      tooltip.style.position = 'fixed';
      tooltip.style.top = '50%';
      tooltip.style.left = '50%';
      tooltip.style.transform = 'translate(-50%,-50%)';
      tooltip.style.zIndex = '9999';
    }
  }
}

document.addEventListener('DOMContentLoaded', function() {
  // Show tour button only when this page has a tour defined
  const tourBtn = document.getElementById('page-tour-btn');
  if (tourBtn && window.PAGE_TOUR && window.PAGE_TOUR.length) tourBtn.style.display = '';

  const nextBtn  = document.getElementById('tour-next');
  const prevBtn  = document.getElementById('tour-prev');
  const closeBtn = document.getElementById('tour-close');
  const overlay  = document.getElementById('tour-overlay');
  if (!nextBtn) return;

  nextBtn.addEventListener('click', () => {
    if (_pgTourStep >= (window.PAGE_TOUR||[]).length - 1) { _endPageTour(); return; }
    _pgTourStep++;
    _showPgTourStep();
  });
  if (prevBtn)  prevBtn.addEventListener('click',  () => { if (_pgTourStep > 0) { _pgTourStep--; _showPgTourStep(); } });
  if (closeBtn) closeBtn.addEventListener('click', _endPageTour);
  if (overlay)  overlay.addEventListener('click',  function(e) { if (e.target === this) _endPageTour(); });
  if (new URLSearchParams(location.search).has('tour')) startPageTour();
});
