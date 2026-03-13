/* ═══════════════════════════════════════════════════
   ADMIN JS — funciones compartidas
   ═══════════════════════════════════════════════════ */

// ── DRAWER (menú móvil) ──────────────────────────────
function openDrawer() {
  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawer-backdrop').classList.add('open');
}
function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawer-backdrop').classList.remove('open');
}
document.getElementById('drawer-backdrop').addEventListener('click', closeDrawer);

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
