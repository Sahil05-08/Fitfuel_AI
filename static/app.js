// ── FitFuel AI — Main Script ──────────────────────────────────────────────────

// ── Tab Switching ─────────────────────────────────────────────────────────────
function showTab(name, btn) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name)?.classList.add('active');
  btn?.classList.add('active');
}

// ── Chat State ────────────────────────────────────────────────────────────────
let chatHistory = [];

// ── Core API Call ─────────────────────────────────────────────────────────────
async function callAPI(msg) {
  const bubble = appendMessage('assistant', buildLoader('Finding the right recipe…'));

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, history: chatHistory }),
    });

    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();

    let html = '';

    if (data.corrections?.length) {
      const corrText = data.corrections
        .map(c => `<em>${escapeHtml(c.from)}</em> → <strong>${escapeHtml(c.to)}</strong>`)
        .join(', ');
      html += `<div class="correction-note">Auto-corrected: ${corrText}</div>`;
    }

    html += renderMarkdown(data.reply);
    bubble.innerHTML = html;

    if (data.audio) {
      const card = document.createElement('div');
      card.className = 'audio-card';
      card.innerHTML = `
        <p>Listen to Recipe</p>
        <audio controls style="width:100%">
          <source src="data:audio/mp3;base64,${data.audio}" type="audio/mp3">
        </audio>`;
      bubble.appendChild(card);
    }

    chatHistory = data.history;

  } catch (err) {
    bubble.innerHTML = statusMsg('error', 'Something went wrong. Please try again.');
    console.error('[FitFuel] callAPI error:', err);
  }

  scrollChat();
}

// ── Send Message ──────────────────────────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById('userInput');
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  setInputDisabled(true);

  appendMessage('user', escapeHtml(msg));
  chatHistory.push({ role: 'user', content: msg });

  await callAPI(msg);
  setInputDisabled(false);
  input.focus();
}

function sendQuick(text) {
  const input = document.getElementById('userInput');
  if (input) input.value = text;
  sendMessage();
}

// ── Reset Chat ────────────────────────────────────────────────────────────────
async function clearChat() {
  try {
    await fetch('/api/reset', { method: 'POST' });
  } catch (e) {
    console.warn('[FitFuel] Reset endpoint error:', e);
  }

  chatHistory = [];
  const chatbox = document.getElementById('chatbox');
  if (chatbox) chatbox.innerHTML = '';

  appendMessage('assistant', renderMarkdown(
    `**Fresh start!** Tell me what ingredients you have at home and I'll build a recipe around your fitness goal.\n\n*Try: "I have eggs and oats" or "chicken, rice, broccoli"*`
  ));
}

// ── Profile Calculator ────────────────────────────────────────────────────────
async function calcProfile(event) {
  const btn = event?.target;
  const result = document.getElementById('profile-result');

  setBtn(btn, 'Calculating…', true);
  showResult(result, buildLoader('Calculating your targets…'));

  try {
    const res = await fetch('/api/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        weight:   getVal('p-weight'),
        height:   getVal('p-height'),
        age:      getVal('p-age'),
        gender:   getVal('p-gender'),
        activity: getVal('p-activity'),
        goal:     getVal('p-goal'),
      }),
    });

    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();
    result.innerHTML = renderMarkdown(data.result);

  } catch (err) {
    result.innerHTML = statusMsg('error', 'Could not calculate profile. Please try again.');
    console.error('[FitFuel] calcProfile error:', err);
  }

  setBtn(btn, 'Calculate My Targets', false);
}

// ── Meal Planner ──────────────────────────────────────────────────────────────
async function genMealPlan(event) {
  const ingredients = document.getElementById('mp-ingredients')?.value.trim();
  if (!ingredients) { alert('Please enter your ingredients first.'); return; }

  const btn = event?.target;
  const result = document.getElementById('mealplan-result');

  setBtn(btn, 'Generating plan…', true);
  showResult(result, buildLoader('Building your meal plan…'));

  try {
    const res = await fetch('/api/mealplan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ingredients,
        goal:     getVal('mp-goal'),
        days:     getVal('mp-days'),
        calories: getVal('mp-calories'),
      }),
    });

    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();
    result.innerHTML = formatMealPlan(data.result);

  } catch (err) {
    result.innerHTML = statusMsg('error', 'Could not generate meal plan. Please try again.');
    console.error('[FitFuel] genMealPlan error:', err);
  }

  setBtn(btn, 'Generate Fitness Meal Plan', false);
}

// ── Fridge Scan ───────────────────────────────────────────────────────────────
async function scanFridge(event) {
  const file = document.getElementById('scan-image')?.files[0];
  if (!file) { alert('Please upload a photo first.'); return; }

  const btn = event?.target;
  const detBox = document.getElementById('scan-detected');
  const recipeBox = document.getElementById('scan-result');

  setBtn(btn, 'Scanning…', true);
  showResult(detBox, buildLoader('Detecting ingredients…'));
  recipeBox?.classList.add('hidden');

  const formData = new FormData();
  formData.append('image', file);
  formData.append('goal', getVal('scan-goal'));

  try {
    const res = await fetch('/api/scan', { method: 'POST', body: formData });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();

    if (data.error) {
      detBox.innerHTML = statusMsg('warning', data.error);
    } else {
      detBox.innerHTML = `<strong>Detected ingredients</strong><br><br>${escapeHtml(data.detected)}`;
      showResult(recipeBox, renderMarkdown(data.recipe));
    }

  } catch (err) {
    detBox.innerHTML = statusMsg('error', 'Could not scan image. Please try again.');
    console.error('[FitFuel] scanFridge error:', err);
  }

  setBtn(btn, 'Detect & Generate Recipe', false);
}

// ── Tools ─────────────────────────────────────────────────────────────────────
async function lookupMacro() {
  const ing = document.getElementById('macro-input')?.value.trim();
  if (!ing) return;
  const data = await toolFetch(`/api/macros?ingredient=${encodeURIComponent(ing)}`);
  showResult(document.getElementById('macro-result'), renderMarkdown(data?.result ?? ''));
}

async function lookupSub() {
  const ing = document.getElementById('sub-input')?.value.trim();
  if (!ing) return;
  const data = await toolFetch(`/api/substitute?ingredient=${encodeURIComponent(ing)}`);
  showResult(document.getElementById('sub-result'), renderMarkdown(data?.result ?? ''));
}

async function getShoppingList() {
  const goal = getVal('shop-goal');
  const days = getVal('shop-days');
  const data = await toolFetch(`/api/shopping?goal=${goal}&days=${days}`);
  showResult(document.getElementById('shop-result'), renderMarkdown(data?.result ?? ''));
}

async function lookupSupp(name) {
  document.querySelectorAll('.supp-chip').forEach(c => {
    c.classList.toggle('active', c.textContent.toLowerCase().includes(name.split(' ')[0]));
  });
  const goal = getVal('supp-goal');
  const data = await toolFetch(`/api/supplement?name=${encodeURIComponent(name)}&goal=${goal}`);
  showResult(document.getElementById('supp-result'), renderMarkdown(data?.result ?? ''));
}

async function calcWater() {
  const weight = getVal('water-weight');
  const activity = getVal('water-activity');
  if (!weight) { alert('Please enter your weight.'); return; }
  const data = await toolFetch(`/api/water?weight=${weight}&activity=${activity}`);
  showResult(document.getElementById('water-result'), renderMarkdown(data?.result ?? ''));
}

// Shared GET helper for simple tool endpoints
async function toolFetch(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('[FitFuel] toolFetch error:', err);
    return null;
  }
}

// ── Calorie Logger ────────────────────────────────────────────────────────────
let calorieTarget  = 2000;
let caloriesLogged = 0;

function logCalories() {
  const input = document.getElementById('cal-input');
  const val = parseInt(input?.value, 10);
  if (!val || val <= 0) return;

  caloriesLogged += val;
  if (input) input.value = '';

  const pct     = Math.min((caloriesLogged / calorieTarget) * 100, 100);
  const display = document.getElementById('cal-display');
  const bar     = document.getElementById('cal-bar');
  const text    = document.getElementById('cal-text');

  display?.classList.remove('hidden');
  if (bar) {
    bar.style.width = pct + '%';
    bar.style.background = pct > 90
      ? 'var(--color-danger, #e53e3e)'
      : 'var(--color-success, #38a169)';
  }
  if (text) text.textContent = `${caloriesLogged} / ${calorieTarget} kcal`;
}

// ── Dietary Restriction Toggles ───────────────────────────────────────────────
const activeDiets = new Set();

function toggleDiet(btn) {
  const diet = btn?.dataset.diet;
  if (!diet) return;

  btn.classList.toggle('active');

  if (activeDiets.has(diet)) {
    activeDiets.delete(diet);
  } else {
    activeDiets.add(diet);
    sendQuick(`I am ${diet.replace(/-/g, ' ')}`);
  }
}

// ── Meal Plan Formatter ───────────────────────────────────────────────────────
// Adds breathing room between days, meals, and sections so the plan
// is easy to scan at a glance rather than one dense block of text.
function formatMealPlan(raw) {
  if (!raw) return '';

  const lines = raw.split('\n');
  const out   = [];

  lines.forEach((line, i) => {
    const trimmed  = line.trim();
    const prev     = out[out.length - 1] ?? '';
    const isDayHdr = /^#{1,3}\s*(day\s*\d+|monday|tuesday|wednesday|thursday|friday|saturday|sunday)/i.test(trimmed);
    const isMeal   = /^#{3,4}\s*(breakfast|lunch|dinner|snack|pre.?workout|post.?workout)/i.test(trimmed);
    const isBullet = /^[-*]\s/.test(trimmed);
    const isHdr    = /^#{1,6}\s/.test(trimmed);
    const isEmpty  = trimmed === '';

    // Always put a blank line before a new day heading (extra gap above it)
    if (isDayHdr && prev !== '' && prev !== '\n') {
      out.push('');
      out.push('---'); // visual divider between days
      out.push('');
    }

    // Blank line before meal headings (Breakfast / Lunch / …)
    if (isMeal && prev !== '') {
      out.push('');
    }

    // Blank line before any other non-bullet heading (e.g. "### Summary")
    if (isHdr && !isDayHdr && !isMeal && prev !== '') {
      out.push('');
    }

    // Don't stack multiple blank lines
    if (isEmpty && prev === '') return;

    out.push(line);
  });

  // Trim leading/trailing blank lines then render
  const cleaned = out.join('\n').trim();
  return renderMarkdown(cleaned);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function appendMessage(role, html) {
  const box = document.getElementById('chatbox');
  if (!box) return null;

  const wrap = document.createElement('div');
  wrap.className = `chat-msg ${role}`;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.innerHTML = html;

  wrap.appendChild(bubble);
  box.appendChild(wrap);
  scrollChat();
  return bubble;
}

function scrollChat() {
  const box = document.getElementById('chatbox');
  if (box) box.scrollTop = box.scrollHeight;
}

function setInputDisabled(state) {
  const input = document.getElementById('userInput');
  const sendBtn = document.querySelector('.send-btn');
  if (input) input.disabled = state;
  if (sendBtn) sendBtn.disabled = state;
}

function setBtn(btn, label, disabled) {
  if (!btn) return;
  btn.textContent = label;
  btn.disabled = disabled;
}

function showResult(el, html) {
  if (!el) return;
  el.classList.remove('hidden');
  el.innerHTML = html;
}

function getVal(id) {
  return document.getElementById(id)?.value ?? '';
}

function buildLoader(msg = 'Loading…') {
  return `<span class="spinner" aria-hidden="true"></span><span class="loading-text">${escapeHtml(msg)}</span>`;
}

function statusMsg(type, msg) {
  const icons = { error: '✕', warning: '!', info: 'i' };
  return `<span class="status-${type}">${icons[type] ?? ''} ${escapeHtml(msg)}</span>`;
}

function renderMarkdown(text) {
  if (typeof marked !== 'undefined') return marked.parse(text ?? '');
  return escapeHtml(text ?? '').replace(/\n/g, '<br>');
}

function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Keyboard Shortcuts ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const pairs = [
    ['macro-input',   lookupMacro],
    ['sub-input',     lookupSub],
    ['water-weight',  calcWater],
    ['cal-input',     logCalories],
  ];

  pairs.forEach(([id, fn]) => {
    document.getElementById(id)?.addEventListener('keydown', e => {
      if (e.key === 'Enter') fn();
    });
  });

  // Send on Enter, new line on Shift+Enter
  document.getElementById('userInput')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
});

// ── Welcome Message ───────────────────────────────────────────────────────────
appendMessage('assistant', renderMarkdown(
`## Welcome to FitFuel AI

I'm your personal fitness meal planner. Tell me what ingredients you have and I'll create a recipe matched to your goal.

**Try saying:**
- *"I have chicken, rice, and broccoli"*
- *"eggs, spinach, and oats"*
- *"I only have paneer"*

You can also ask me:
- *"macros of salmon"*
- *"substitute for paneer"*
- *"when should I take creatine"*

Start typing below.`
));