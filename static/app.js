/* ==========================================================
   AI PDF Voice Assistant — Application Logic
   Cookie-based auth: no localStorage, token is HTTP-only cookie
   ========================================================== */

// ── State ──
let currentUser = null;
let currentSessionId = null;
let ttsOn = true;
let lastAudio = null;
let busy = false;
let recorder, chunks = [], recording = false;
let audioCtx, analyser, micStream, animFrame;

const $ = id => document.getElementById(id);

// ── Simple Markdown Parser ──
function renderMarkdown(text) {
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // Code blocks
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Unordered lists
    .replace(/^\s*[-*]\s+(.+)$/gm, '<li>$1</li>')
    // Ordered lists
    .replace(/^\s*\d+\.\s+(.+)$/gm, '<li>$1</li>');
  // Wrap consecutive <li> tags in <ul>
  html = html.replace(/((?:<li>.*<\/li>\s*)+)/g, '<ul>$1</ul>');
  // Paragraphs
  html = html.split(/\n\n+/).map(p => {
    p = p.trim();
    if (!p || p.startsWith('<pre>') || p.startsWith('<ul>') || p.startsWith('<ol>')) return p;
    return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
  }).join('');
  return html;
}

// ── Toast Notifications ──
function showToast(message, type = 'success') {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = message;
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, 3000);
}

// ── Escape HTML ──
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

/* ==========================================================
   LANDING PAGE
   ========================================================== */
function initParticles(container) {
  if (!container) return;
  for (let i = 0; i < 30; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    p.style.left = Math.random() * 100 + '%';
    p.style.animationDelay = Math.random() * 8 + 's';
    p.style.animationDuration = (6 + Math.random() * 6) + 's';
    container.appendChild(p);
  }
}

function goToAuth() {
  document.querySelector('.landing').style.display = 'none';
  $('authOverlay').classList.add('show');
}

function goToLanding() {
  $('authOverlay').classList.remove('show');
  document.querySelector('.landing').style.display = '';
}

/* ==========================================================
   AUTH — Cookie-based (no localStorage)
   ========================================================== */
function switchAuthTab(tab) {
  $('tabLogin').classList.toggle('active', tab === 'login');
  $('tabRegister').classList.toggle('active', tab === 'register');
  $('loginForm').style.display = tab === 'login' ? '' : 'none';
  $('registerForm').style.display = tab === 'register' ? '' : 'none';
  $('authError').textContent = '';
}

async function handleLogin(e) {
  e.preventDefault();
  $('authError').textContent = '';
  try {
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: $('lUser').value, password: $('lPass').value })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Login failed');
    loginSuccess(d);
  } catch (e) { $('authError').textContent = e.message; }
  return false;
}

async function handleRegister(e) {
  e.preventDefault();
  $('authError').textContent = '';
  try {
    const r = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: $('rUser').value, email: $('rEmail').value, password: $('rPass').value })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Registration failed');
    loginSuccess(d);
    showToast('Account created successfully!');
  } catch (e) { $('authError').textContent = e.message; }
  return false;
}

function loginSuccess(data) {
  // No localStorage — cookie is set by the server automatically
  currentUser = data.user;
  showToast('Welcome back, ' + currentUser.username + '!');
  showApp();
}

function logout() {
  // Tell server to clear the auth cookie
  fetch('/api/auth/logout', { method: 'POST' }).catch(() => { });
  currentUser = null;
  currentSessionId = null;
  $('mainApp').classList.remove('show');
  document.querySelector('.landing').style.display = '';
  $('authOverlay').classList.remove('show');
}

// API helper — cookies are sent automatically, handles 401
function api(url, opts = {}) {
  return fetch(url, opts).then(r => {
    if (r.status === 401) {
      logout();
      showToast('Session expired — please log in again', 'error');
      throw new Error('Session expired');
    }
    return r;
  });
}

async function checkAuth() {
  try {
    const r = await fetch('/api/auth/me');
    if (!r.ok) return;
    currentUser = await r.json();
    showApp();
  } catch { }
}

function showApp() {
  document.querySelector('.landing').style.display = 'none';
  $('authOverlay').classList.remove('show');
  $('mainApp').classList.add('show');
  $('sbAvatar').textContent = currentUser.username[0].toUpperCase();
  $('sbName').textContent = currentUser.username;
  $('sbEmail').textContent = currentUser.email;
  loadSessions();
  loadPDFs();
}

/* ==========================================================
   SESSIONS
   ========================================================== */
async function loadSessions() {
  try {
    const r = await api('/api/chat/sessions');
    const list = await r.json();
    const ul = $('sessionList');
    ul.innerHTML = '';
    list.forEach(s => {
      const li = document.createElement('li');
      li.className = 'sb-item' + (s.id === currentSessionId ? ' active' : '');
      li.innerHTML = `<span style="flex:1;overflow:hidden;text-overflow:ellipsis">💬 ${esc(s.title)}</span><button class="del" onclick="event.stopPropagation();delSession(${s.id})">✕</button>`;
      li.onclick = () => loadSession(s.id);
      ul.appendChild(li);
    });
  } catch { }
}

async function loadSession(id) {
  try {
    const r = await api('/api/chat/sessions/' + id);
    const data = await r.json();
    currentSessionId = id;
    $('cpTitle').textContent = data.title;
    $('chatArea').innerHTML = '';
    if (data.messages.length === 0) {
      $('chatArea').innerHTML = '<div class="empty" id="emptyState"><div class="ei">💬</div><p>Start a conversation — type a message or tap the mic.</p></div>';
    } else {
      data.messages.forEach(m => addMsg(m.role, m.content, m.audio_url ? '/' + m.audio_url : null, m.source, false));
    }
    loadSessions();
  } catch { }
}

async function newChat() {
  currentSessionId = null;
  $('cpTitle').textContent = 'New Chat';
  $('chatArea').innerHTML = '<div class="empty" id="emptyState"><div class="ei">💬</div><p>Start a conversation — type a message or tap the mic. Upload a PDF for context-aware answers.</p></div>';
  loadSessions();
}

async function delSession(id) {
  try {
    await api('/api/chat/sessions/' + id, { method: 'DELETE' });
    showToast('Chat deleted');
    if (currentSessionId === id) newChat();
    else loadSessions();
  } catch { }
}

/* ==========================================================
   PDF LIBRARY
   ========================================================== */
async function loadPDFs() {
  try {
    const r = await api('/api/pdf/list');
    const list = await r.json();
    const ul = $('pdfList');
    ul.innerHTML = '';
    if (!list.length) { ul.innerHTML = '<li style="font-size:0.68rem;color:var(--dim);padding:0.3rem 0.6rem">No PDFs uploaded</li>'; return; }
    list.forEach(p => {
      const li = document.createElement('li');
      li.className = 'sb-item sb-pdf-item';
      li.innerHTML = `📄 <span style="flex:1;overflow:hidden;text-overflow:ellipsis">${esc(p.original_name)}</span><span class="pages">${p.page_count}pg</span><button class="del" onclick="event.stopPropagation();delPDF(${p.id})">✕</button>`;
      ul.appendChild(li);
    });
  } catch { }
}

$('pdfFileInput').addEventListener('change', function () { if (this.files[0]) uploadPDF(this.files[0]); });

async function uploadPDF(file) {
  const fd = new FormData(); fd.append('file', file);
  const s = $('uploadStatus');
  s.className = 'upload-status'; s.innerHTML = '<span class="spinner"></span> Indexing ' + esc(file.name) + '…';
  try {
    const r = await api('/api/pdf/upload', { method: 'POST', body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail);
    s.className = 'upload-status ok'; s.textContent = '✓ ' + d.message;
    showToast('PDF uploaded successfully!');
    loadPDFs();
  } catch (e) {
    s.className = 'upload-status err'; s.textContent = '✗ ' + e.message;
    showToast(e.message, 'error');
  }
}

async function delPDF(id) {
  try { await api('/api/pdf/' + id, { method: 'DELETE' }); showToast('PDF removed'); loadPDFs(); } catch { }
}

// Drop zone
const dz = $('dropZone');
const dzIn = $('dropInput');
dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
dz.addEventListener('dragleave', () => dz.classList.remove('over'));
dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('over'); if (e.dataTransfer.files[0]) uploadPDF(e.dataTransfer.files[0]); });
dzIn.addEventListener('change', () => { if (dzIn.files[0]) uploadPDF(dzIn.files[0]); });

/* ==========================================================
   CHAT
   ========================================================== */
function hideEmpty() { const e = $('emptyState'); if (e) e.style.display = 'none'; }

function addMsg(role, text, audioUrl, source, animate = true) {
  hideEmpty();
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  if (!animate) d.style.animation = 'none';

  let bubbleContent = role === 'ai' ? renderMarkdown(text) : esc(text);
  let meta = '';
  if (role === 'ai') {
    const t = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const badge = source === 'pdf'
      ? '<span class="badge pdf">PDF</span>'
      : '<span class="badge general">General</span>';
    meta = `<div class="meta"><span>${t}</span>${badge}`;
    if (audioUrl) meta += `<span class="play-btn" onclick="new Audio('${audioUrl}').play().catch(()=>{})">▶ Play</span>`;
    meta += '</div>';
  }

  d.innerHTML = `<div class="bubble">${bubbleContent}</div>${meta}`;
  $('chatArea').appendChild(d);
  $('chatArea').scrollTop = $('chatArea').scrollHeight;
}

function addThinking() {
  hideEmpty();
  const d = document.createElement('div');
  d.className = 'thinking'; d.id = 'thinking';
  d.innerHTML = '<div class="bubble"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
  $('chatArea').appendChild(d);
  $('chatArea').scrollTop = $('chatArea').scrollHeight;
}
function rmThinking() { const e = $('thinking'); if (e) e.remove(); }

function setBusy(b) {
  busy = b;
  $('sendBtn').disabled = b;
  $('textInput').disabled = b;
}

// Text chat
$('textInput').addEventListener('keydown', e => { if (e.key === 'Enter' && !busy) sendText(); });

async function sendText() {
  const q = $('textInput').value.trim();
  if (!q || busy) return;
  $('textInput').value = '';
  addMsg('user', q);
  setBusy(true); addThinking();
  try {
    const r = await api('/api/chat/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, session_id: currentSessionId })
    });
    const d = await r.json();
    rmThinking();
    addMsg('ai', d.answer, null, d.source);
    if (d.session_id && !currentSessionId) {
      currentSessionId = d.session_id;
      $('cpTitle').textContent = q.slice(0, 60);
      loadSessions();
    }
    if (ttsOn && 'speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(d.answer); u.rate = 1; speechSynthesis.speak(u);
    }
  } catch {
    rmThinking(); addMsg('ai', 'Error: could not reach the server.', null, 'general');
  }
  setBusy(false);
}

// Voice chat
function initWaveBars() {
  const wb = $('waveBar'); wb.innerHTML = '';
  for (let i = 0; i < 20; i++) { const b = document.createElement('div'); b.className = 'bar'; b.style.height = '3px'; wb.appendChild(b); }
}

function animateWave() {
  if (!analyser) return;
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(data);
  const bars = $('waveBar').querySelectorAll('.bar');
  const step = Math.floor(data.length / bars.length);
  bars.forEach((b, i) => { b.style.height = Math.max(3, data[i * step] / 6) + 'px'; });
  animFrame = requestAnimationFrame(animateWave);
}

async function toggleRec() {
  if (busy) return;
  if (!recording) {
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = new MediaRecorder(micStream);
      chunks = [];
      recorder.ondataavailable = e => chunks.push(e.data);
      recorder.onstop = sendVoice;
      recorder.start();
      recording = true;
      $('micBtn').classList.add('rec'); $('micBtn').textContent = '⏹';
      audioCtx = new AudioContext();
      const src = audioCtx.createMediaStreamSource(micStream);
      analyser = audioCtx.createAnalyser(); analyser.fftSize = 256;
      src.connect(analyser);
      initWaveBars(); $('waveBar').classList.add('show');
      animateWave();
    } catch {
      showToast('Microphone access denied', 'error');
    }
  } else {
    recorder.stop();
    micStream.getTracks().forEach(t => t.stop());
    recording = false;
    $('micBtn').classList.remove('rec'); $('micBtn').textContent = '🎤';
    cancelAnimationFrame(animFrame);
    $('waveBar').classList.remove('show');
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
  }
}

async function sendVoice() {
  const blob = new Blob(chunks);
  addMsg('user', '🎤 Voice message');
  setBusy(true); addThinking();
  const fd = new FormData(); fd.append('file', blob, 'voice.webm');
  if (currentSessionId) fd.append('session_id', currentSessionId);
  try {
    const r = await api('/api/chat/voice', { method: 'POST', body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Voice processing failed');
    rmThinking();
    const ubs = $('chatArea').querySelectorAll('.msg.user .bubble');
    const last = ubs[ubs.length - 1];
    if (last && d.question) last.textContent = d.question;
    const aUrl = d.audio_file ? '/' + d.audio_file : null;
    addMsg('ai', d.answer, aUrl, d.source);
    if (aUrl) {
      lastAudio = aUrl;
      $('replayBtn').style.display = 'flex';
      if (ttsOn) new Audio(aUrl).play().catch(() => { });
    }
    if (d.session_id && !currentSessionId) {
      currentSessionId = d.session_id;
      $('cpTitle').textContent = (d.question || 'Voice Chat').slice(0, 60);
      loadSessions();
    }
  } catch (e) {
    rmThinking();
    addMsg('ai', 'Error: ' + e.message, null, 'general');
    showToast(e.message, 'error');
  }
  setBusy(false);
}

// Controls
function toggleTTS() { ttsOn = !ttsOn; $('ttsBtn').classList.toggle('on', ttsOn); }
function replayLast() { if (lastAudio) new Audio(lastAudio).play().catch(() => { }); }
function toggleUpload() { $('uploadBar').classList.toggle('hidden'); $('uploadToggle').classList.toggle('on', !$('uploadBar').classList.contains('hidden')); }
function toggleSidebar() { $('sidebar').classList.toggle('collapsed'); }

/* ── Init ── */
document.querySelectorAll('.particles').forEach(initParticles);
checkAuth();
