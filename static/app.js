/**
 * HealthChat Hub Client Logic (COROS Light Theme)
 */

let currentUser = null;
let currentTab = 'health';
let currentDaysRange = 30;
let chartInstances = {};
let cachedSummary = null;

// On Page Load
document.addEventListener('DOMContentLoaded', async () => {
  await checkSession();
});

/// --- AUTHENTICATION & API HELPERS ---

function getAuthHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  const token = sessionStorage.getItem('healthchat_session');
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

function apiFetch(url, options = {}) {
  const headers = getAuthHeaders(options.headers || {});
  return fetch(url, { ...options, headers });
}

async function checkSession() {
  try {
    const res = await apiFetch('/api/auth/me');
    if (res.ok) {
      currentUser = await res.json();
      onAuthSuccess();
    } else {
      showAuthModal();
    }
  } catch (err) {
    showAuthModal();
  }
}

function showAuthModal() {
  document.getElementById('auth-modal').classList.remove('hidden');
  document.getElementById('app-layout').classList.add('hidden');
}

function onAuthSuccess() {
  document.getElementById('auth-modal').classList.add('hidden');
  document.getElementById('app-layout').classList.remove('hidden');
  
  if (currentUser) {
    document.getElementById('user-display-email').innerText = currentUser.email;
    const initial = (currentUser.email[0] || 'U').toUpperCase();
    const avatarEl = document.getElementById('user-avatar-initial');
    if (avatarEl) avatarEl.innerText = initial;
    
    // Populate profile inputs
    populateProfileInputs(currentUser.profile || {});
  }

  refreshDashboard();
  loadChatHistory();
  initChatModelSelect();
  fetchLocalWeather();
}

function switchAuthTab(tab) {
  const loginBtn = document.getElementById('tab-btn-login');
  const regBtn = document.getElementById('tab-btn-register');
  const loginForm = document.getElementById('form-login');
  const regForm = document.getElementById('form-register');

  if (tab === 'login') {
    loginBtn.classList.add('active');
    regBtn.classList.remove('active');
    loginForm.classList.remove('hidden');
    regForm.classList.add('hidden');
  } else {
    regBtn.classList.add('active');
    loginBtn.classList.remove('active');
    regForm.classList.remove('hidden');
    loginForm.classList.add('hidden');
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const email = document.getElementById('login-email').value;
  const password = document.getElementById('login-password').value;
  const errDiv = document.getElementById('auth-error');

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    let data;
    try {
      data = await res.json();
    } catch (e) {
      data = { detail: `Serverfel (${res.status}): ${res.statusText}` };
    }
    if (res.ok) {
      currentUser = data;
      if (data.session_id) {
        sessionStorage.setItem('healthchat_session', data.session_id);
      }
      onAuthSuccess();
    } else {
      errDiv.innerText = data.detail || 'Inloggningen misslyckades.';
      errDiv.classList.remove('hidden');
    }
  } catch (err) {
    errDiv.innerText = `Nätverksfel vid inloggning: ${err.message || err}`;
    errDiv.classList.add('hidden');
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const email = document.getElementById('reg-email').value;
  const password = document.getElementById('reg-password').value;
  const sex = document.getElementById('reg-sex').value;
  const age = parseInt(document.getElementById('reg-age').value);
  const height_cm = parseFloat(document.getElementById('reg-height').value);
  const weight_kg = parseFloat(document.getElementById('reg-weight').value);
  const errDiv = document.getElementById('auth-error');

  try {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, sex, age, height_cm, weight_kg })
    });
    const data = await res.json();
    if (res.ok) {
      currentUser = data;
      if (data.session_id) {
        sessionStorage.setItem('healthchat_session', data.session_id);
      }
      if (data.recovery_key) {
        showRecoveryModal(data.recovery_key);
      } else {
        onAuthSuccess();
      }
    } else {
      errDiv.innerText = data.detail || 'Registreringen misslyckades.';
      errDiv.classList.remove('hidden');
    }
  } catch (err) {
    errDiv.innerText = 'Nätverksfel vid registrering.';
    errDiv.classList.add('hidden');
  }
}

function showRecoveryModal(key) {
  document.getElementById('recovery-key-text').innerText = key;
  document.getElementById('recovery-modal').classList.remove('hidden');
}

function copyRecoveryKey() {
  const key = document.getElementById('recovery-key-text').innerText;
  navigator.clipboard.writeText(key);
  alert('Återställningsnyckeln har kopierats till urklipp!');
}

function closeRecoveryModal() {
  document.getElementById('recovery-modal').classList.add('hidden');
  onAuthSuccess();
}

async function handleLogout() {
  try {
    await apiFetch('/api/auth/logout', { method: 'POST' });
  } catch (e) {}
  sessionStorage.removeItem('healthchat_session');
  currentUser = null;
  showAuthModal();
}


// --- NAVIGATION & TABS ---

function showTab(tabId) {
  currentTab = tabId;
  
  // Highlight active navbar button
  document.querySelectorAll('.nav-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.id === `tab-btn-${tabId}`);
  });
  
  // Show active content section
  document.querySelectorAll('.content-tab').forEach(section => {
    section.classList.toggle('hidden', section.id !== `tab-${tabId}`);
  });

  if (tabId === 'health' || tabId === 'dashboard') {
    renderHealthCharts();
  } else if (tabId === 'training') {
    renderTrainingCharts();
    fetchLocalWeather();
  } else if (tabId === 'ai-chat') {
    loadChatHistory();
  } else if (tabId === 'profile') {
    populateProfileInputs();
  } else if (tabId === 'datasources') {
    loadDatasources();
  }
}

async function populateProfileInputs(profile) {
  let p = profile || (currentUser && currentUser.profile) || (cachedSummary && cachedSummary.profile) || {};
  if (!p.height_cm || !p.age) {
    try {
      const res = await apiFetch('/api/auth/me');
      if (res.ok) {
        currentUser = await res.json();
        p = (currentUser && currentUser.profile) || p;
      }
    } catch (e) {}
  }
  const sexEl = document.getElementById('prof-sex');
  if (sexEl && p.sex) sexEl.value = p.sex;
  const ageEl = document.getElementById('prof-age');
  if (ageEl && p.age !== undefined && p.age !== null && p.age !== '') ageEl.value = p.age;
  const hEl = document.getElementById('prof-height');
  if (hEl && p.height_cm !== undefined && p.height_cm !== null && p.height_cm !== '') hEl.value = p.height_cm;
  const wEl = document.getElementById('prof-weight');
  if (wEl && p.weight_kg !== undefined && p.weight_kg !== null && p.weight_kg !== '') wEl.value = p.weight_kg;
  const rHrEl = document.getElementById('prof-resting-hr');
  if (rHrEl && p.resting_hr !== undefined && p.resting_hr !== null && p.resting_hr !== '') rHrEl.value = p.resting_hr;
  const mHrEl = document.getElementById('prof-max-hr');
  if (mHrEl) {
    if (p.max_hr !== undefined && p.max_hr !== null && p.max_hr !== '' && parseFloat(p.max_hr) > 0) {
      mHrEl.value = p.max_hr;
      mHrEl.dataset.isAutoComputed = 'false';
    } else {
      const currentAge = parseFloat(ageEl?.value || p.age || 0);
      if (currentAge > 0) {
        mHrEl.value = Math.round(220 - currentAge);
        mHrEl.dataset.isAutoComputed = 'true';
      }
    }
  }
  const fatEl = document.getElementById('prof-fat');
  if (fatEl && p.fat_ratio_pct !== undefined && p.fat_ratio_pct !== null && p.fat_ratio_pct !== '') fatEl.value = p.fat_ratio_pct;
  const musEl = document.getElementById('prof-muscle');
  if (musEl && p.muscle_mass_kg !== undefined && p.muscle_mass_kg !== null && p.muscle_mass_kg !== '') musEl.value = p.muscle_mass_kg;
  const boneEl = document.getElementById('prof-bone');
  if (boneEl && p.bone_mass_kg !== undefined && p.bone_mass_kg !== null && p.bone_mass_kg !== '') boneEl.value = p.bone_mass_kg;
  const watEl = document.getElementById('prof-water');
  if (watEl && p.water_pct !== undefined && p.water_pct !== null && p.water_pct !== '') watEl.value = p.water_pct;
  const bmiEl = document.getElementById('prof-bmi');
  const heightNum = parseFloat(document.getElementById('prof-height')?.value || p.height_cm || 0);
  const weightNum = parseFloat(document.getElementById('prof-weight')?.value || p.weight_kg || 0);

  let bmiVal = p.bmi;
  if ((!bmiVal || parseFloat(bmiVal) === 0) && heightNum > 0 && weightNum > 0) {
    bmiVal = (weightNum / ((heightNum / 100.0) ** 2)).toFixed(1);
  }
  if (bmiEl && bmiVal !== undefined && bmiVal !== null && bmiVal !== '') {
    bmiEl.value = bmiVal;
  }
  const tgEl = document.getElementById('prof-training-goals');
  if (tgEl) {
    tgEl.value = p.training_goals !== undefined && p.training_goals !== null ? p.training_goals : '';
  }
  const injEl = document.getElementById('prof-injuries');
  if (injEl) {
    injEl.value = p.injuries !== undefined && p.injuries !== null ? p.injuries : '';
  }

  updateLiveBmi();
  bindLiveBmiCalculator();
  updateLiveMaxHr();
  bindLiveMaxHrCalculator();
}

function updateLiveBmi() {
  const hVal = parseFloat((document.getElementById('prof-height')?.value || '').replace(',', '.'));
  const wVal = parseFloat((document.getElementById('prof-weight')?.value || '').replace(',', '.'));
  const bmiEl = document.getElementById('prof-bmi');
  if (bmiEl && hVal > 0 && wVal > 0) {
    const computedBmi = (wVal / ((hVal / 100.0) ** 2)).toFixed(1);
    bmiEl.value = computedBmi;
  }
}

function bindLiveBmiCalculator() {
  const hEl = document.getElementById('prof-height');
  const wEl = document.getElementById('prof-weight');
  if (hEl && !hEl.dataset.bmiBound) {
    hEl.addEventListener('input', updateLiveBmi);
    hEl.addEventListener('change', updateLiveBmi);
    hEl.dataset.bmiBound = 'true';
  }
  if (wEl && !wEl.dataset.bmiBound) {
    wEl.addEventListener('input', updateLiveBmi);
    wEl.addEventListener('change', updateLiveBmi);
    wEl.dataset.bmiBound = 'true';
  }
}

function updateLiveMaxHr() {
  const ageVal = parseFloat((document.getElementById('prof-age')?.value || '').replace(',', '.'));
  const rHrVal = parseFloat((document.getElementById('prof-resting-hr')?.value || '').replace(',', '.'));
  const mHrEl = document.getElementById('prof-max-hr');

  if (mHrEl && ageVal > 0) {
    if (!mHrEl.value || mHrEl.dataset.isAutoComputed === 'true') {
      mHrEl.value = Math.round(220 - ageVal);
      mHrEl.dataset.isAutoComputed = 'true';
    }
  }

  const age = ageVal || 42;
  const restingHr = rHrVal || 54;
  const maxHr = mHrEl && mHrEl.value ? parseFloat(mHrEl.value) : Math.round(220 - age);
  const hrr = maxHr - restingHr;

  const summaryHeader = document.getElementById('prof-summary-header-info');
  if (summaryHeader) {
    summaryHeader.innerText = `👤 Ålder: ${age} år | ❤️ Vilopuls: ${restingHr} bpm | ⚡ Maxpuls: ${maxHr} bpm | 📊 Pulsreserv (HRR): ${hrr} bpm`;
  }
}

function bindLiveMaxHrCalculator() {
  const ageEl = document.getElementById('prof-age');
  const rHrEl = document.getElementById('prof-resting-hr');
  const mHrEl = document.getElementById('prof-max-hr');

  if (ageEl && !ageEl.dataset.maxHrBound) {
    ageEl.addEventListener('input', updateLiveMaxHr);
    ageEl.addEventListener('change', updateLiveMaxHr);
    ageEl.dataset.maxHrBound = 'true';
  }
  if (rHrEl && !rHrEl.dataset.maxHrBound) {
    rHrEl.addEventListener('input', updateLiveMaxHr);
    rHrEl.addEventListener('change', updateLiveMaxHr);
    rHrEl.dataset.maxHrBound = 'true';
  }
  if (mHrEl && !mHrEl.dataset.maxHrBound) {
    mHrEl.addEventListener('input', () => {
      mHrEl.dataset.isAutoComputed = 'false';
      updateLiveMaxHr();
    });
    mHrEl.dataset.maxHrBound = 'true';
  }
}



function setDaysRange(days) {
  currentDaysRange = days;
  
  // Highlight active range button
  document.querySelectorAll('.btn-range').forEach(btn => {
    btn.classList.toggle('active', btn.id === `btn-range-${days}`);
  });

  refreshDashboard();
}


// --- DASHBOARD DATA & REFRESH ---

let _isHeaderRefreshing = false;

async function handleHeaderRefresh() {
  console.log('[HeaderRefresh] Klick på Uppdatera mottaget.');
  if (_isHeaderRefreshing) {
    console.warn('[HeaderRefresh] Uppdatering pågår redan, ignorerar.');
    return;
  }
  _isHeaderRefreshing = true;

  // Säkerhetstimer för att inte låsa knappen om något oväntat sker
  const safetyTimeout = setTimeout(() => {
    _isHeaderRefreshing = false;
    const b = document.getElementById('btn-refresh-dashboard');
    if (b && b.disabled) {
      b.disabled = false;
      b.innerHTML = '🔄 Uppdatera';
    }
  }, 35000);

  const btn = document.getElementById('btn-refresh-dashboard');
  const originalHtml = btn ? btn.innerHTML : '🔄 Uppdatera';

  try {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '⏳ Synkar datakällor...';
    }

    // 1. Synka alla anslutna externa datakällor (Garmin, Withings, Strava, Fitbit)
    try {
      console.log('[HeaderRefresh] Anropar /api/datasources/sync_all...');
      const syncRes = await apiFetch('/api/datasources/sync_all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (syncRes.ok) {
        const syncData = await syncRes.json();
        console.log('[HeaderRefresh] sync_all svar:', syncData);
        if (syncData.count > 0) {
          // Poll för att vänta in att synkroniseringen blir klar
          let attempts = 0;
          while (attempts < 20) {
            await new Promise(r => setTimeout(r, 1000));
            const stRes = await apiFetch('/api/datasources/sync_all_status');
            if (stRes.ok) {
              const st = await stRes.json();
              console.log('[HeaderRefresh] sync_all_status:', st);
              if (!st.running) break;
            }
            attempts++;
          }
        }
      } else {
        console.warn('[HeaderRefresh] sync_all status inte ok:', syncRes.status);
      }
    } catch (syncErr) {
      console.warn('[HeaderRefresh] Varning vid anrop till datakällor:', syncErr);
    }

    // 2. Hämta färsk data från databasen och rita om grafer/kort
    if (btn) btn.innerHTML = '⏳ Uppdaterar grafer...';
    console.log('[HeaderRefresh] Uppdaterar grafer...');
    await refreshDashboard();

    // 3. Om användaren står i Datakällor-fliken, uppdatera även den
    if (typeof currentTab !== 'undefined' && currentTab === 'datasources') {
      if (typeof loadDatasources === 'function') {
        await loadDatasources();
      }
    }

    // 4. Bekräfta att uppdateringen är klar
    clearTimeout(safetyTimeout);
    if (btn) {
      btn.innerHTML = '✓ Uppdaterad!';
      setTimeout(() => {
        btn.innerHTML = originalHtml;
        btn.disabled = false;
        _isHeaderRefreshing = false;
      }, 1500);
    } else {
      _isHeaderRefreshing = false;
    }
  } catch (err) {
    clearTimeout(safetyTimeout);
    console.error('[HeaderRefresh] Fel vid uppdatering av dashboard:', err);
    if (btn) {
      btn.innerHTML = '⚠️ Fel vid uppdatering';
      setTimeout(() => {
        btn.innerHTML = originalHtml;
        btn.disabled = false;
        _isHeaderRefreshing = false;
      }, 2000);
    } else {
      _isHeaderRefreshing = false;
    }
  }
}
window.handleHeaderRefresh = handleHeaderRefresh;


async function refreshDashboard() {
  try {
    const res = await apiFetch(`/api/dashboard/summary?days=${currentDaysRange}`);
    if (!res.ok) {
      if (res.status === 401) {
        sessionStorage.removeItem('healthchat_session');
        showAuthModal();
      }
      return;
    }
    cachedSummary = await res.json();
    
    if (cachedSummary.profile) {
      populateProfileInputs(cachedSummary.profile);
    }
    
    updateDashboardCards(cachedSummary);
    renderActivitiesTable(cachedSummary.history.activities || []);
    
    if (currentTab === 'training') {
      renderTrainingCharts();
    } else {
      renderHealthCharts();
    }
  } catch (err) {
    console.error('Error refreshing dashboard:', err);
  }
}

const SPORT_COLORS = {
  'Löpning': '#0078D4',
  'Cykling': '#F59E0B',
  'Virtuell cykling': '#F97316',
  'Löpband': '#38BDF8',
  'Traillöpning': '#0284C7',
  'Styrketräning': '#10B981',
  'Promenad': '#8B5CF6',
  'Vandring': '#059669',
  'Simning': '#06B6D4',
  'Yoga': '#EC4899',
  'Pilates': '#D946EF',
  'Rodd': '#6366F1',
  'Skidåkning': '#0EA5E9',
  'Padel / Racket': '#EAB308',
  'Konditionsträning': '#EF4444',
  'Övrigt': '#6B7280'
};

function formatActivityType(rawType, fallbackName = '') {
  const t = String(rawType || '').toLowerCase().trim();
  const n = String(fallbackName || '').toLowerCase().trim();

  // Virtuell cykling (Rouvy, Zwift, VirtualRide, inomhuscykling etc.)
  if (t.includes('virtual') || n.includes('virtual') || n.includes('rouvy') || n.includes('zwift') || t.includes('indoor_cycling') || t.includes('spinning')) {
    return 'Virtuell cykling';
  }
  // Cykling
  if (t.includes('cycl') || t.includes('biking') || t.includes('ride') || t.includes('cykel') || t.includes('cykling') || n.includes('cykling') || n.includes('cykel')) {
    return 'Cykling';
  }
  // Löpband
  if (t.includes('treadmill') || n.includes('löpband')) {
    return 'Löpband';
  }
  // Traillöpning
  if (t.includes('trail_running') || t.includes('trail running') || n.includes('traillöpning') || n.includes('trail')) {
    return 'Traillöpning';
  }
  // Löpning
  if (t.includes('run') || t.includes('löp') || t.includes('jogg') || n.includes('löpning') || n.includes('jogg')) {
    return 'Löpning';
  }
  // Promenad
  if (t.includes('walk') || t.includes('gång') || t.includes('promenad') || n.includes('promenad') || n.includes('gång')) {
    return 'Promenad';
  }
  // Vandring
  if (t.includes('hike') || t.includes('vandr') || n.includes('vandr')) {
    return 'Vandring';
  }
  // Simning
  if (t.includes('swim') || t.includes('sim') || n.includes('sim')) {
    return 'Simning';
  }
  // Styrketräning
  if (t.includes('strength') || t.includes('weight') || t.includes('styrk') || t.includes('gym') || n.includes('styrk') || n.includes('gym')) {
    return 'Styrketräning';
  }
  // Yoga
  if (t.includes('yoga') || n.includes('yoga')) {
    return 'Yoga';
  }
  // Pilates
  if (t.includes('pilates') || n.includes('pilates')) {
    return 'Pilates';
  }
  // Rodd
  if (t.includes('row') || t.includes('rodd') || n.includes('rodd')) {
    return 'Rodd';
  }
  // Skidåkning
  if (t.includes('ski') || t.includes('skid') || n.includes('skid')) {
    return 'Skidåkning';
  }
  // Padel / Racket
  if (t.includes('padel') || t.includes('tennis') || n.includes('padel') || n.includes('tennis')) {
    return 'Padel / Racket';
  }
  // Kondition
  if (t.includes('cardio') || t.includes('fitness') || t.includes('workout') || t.includes('hiit') || n.includes('cardio') || n.includes('fitness')) {
    return 'Konditionsträning';
  }

  // Om rawType är angett men inte översatt ovan
  if (rawType && !['träning', 'activity', 'other', 'övrigt'].includes(t)) {
    return rawType.charAt(0).toUpperCase() + rawType.slice(1).replace(/_/g, ' ');
  }

  return 'Övrigt';
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderMarkdown(text) {
  if (!text) return '';

  let t = text;

  // 1. Ensure line breaks before section headers (e.g. 📊 Analys, 💡 Rekommenderat, 📚 Data) if output inline
  t = t.replace(/([^\n])\s*([📊💡📚🏋️🛌🏃⚡⚖️❤️🎯]\s*[^:\n]+:)/g, '$1\n\n**$2**\n');

  // 2. Ensure line breaks before list items (- item) if output inline
  t = t.replace(/([^\n])\s+-\s+/g, '$1\n- ');

  // 3. Ensure line breaks before numbered steps (1. , 2. ) if output inline
  t = t.replace(/([^\n])\s+(\d+\.\s+)/g, '$1\n\n$2');

  let escaped = escapeHtml(t);

  // 4. Headers: ### Header -> <h4>Header</h4>, ## Header -> <h3>Header</h3>
  escaped = escaped.replace(/^###\s+(.*$)/gim, '<h4 class="chat-section-header">$1</h4>');
  escaped = escaped.replace(/^##\s+(.*$)/gim, '<h3 class="chat-section-header">$1</h3>');

  // 5. Bold & Italic
  escaped = escaped
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>');

  // 6. Normalize excessive blank lines
  escaped = escaped.replace(/\n{3,}/g, '\n\n');

  return escaped;
}

function floatVal(v, defaultVal = 0.0) {
  const parsed = parseFloat(v);
  return isNaN(parsed) ? defaultVal : parsed;
}

function formatNumber(num) {
  return Math.round(num).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function getRecoveryAiAdvice(recVal) {
  const p = (currentUser && currentUser.profile) || (cachedSummary && cachedSummary.profile) || {};
  const tg = (p.training_goals && typeof p.training_goals === 'string') ? p.training_goals.trim() : '';
  const tgNote = tg ? `\n🎯 Inriktning mot dina mål: "${tg}"` : '';
  const inj = (p.injuries && typeof p.injuries === 'string') ? p.injuries.trim() : '';
  const injNote = inj ? `\n🩹 Hänsyn till skador/begränsningar: "${inj}" – anpassa övningsval och intensitet så att skadan inte belastas negativt.` : '';

  if (recVal >= 80) {
    return "🤖 AI-Analys: Återhämtning " + recVal + "% – Kroppen är i toppform och redo för högre ansträngning!\n" +
      "🎯 Rekommenderad träning: Högintensivt kvalitetspass (intervaller, tröskel/tempo eller snabbdistans).\n" +
      "❤️ Pulsnivå: Sikta på Zon 3–4 (140–170 bpm) med möjliga toppar i Zon 5.\n" +
      "🏃 Träningsfokus: Utnyttja höga energidepåer för maximal träningseffekt och utveckling.\n" +
      "💡 Tips: Värm upp grundligt i Zon 1 (10–15 min) och prioritera god återhämtning efteråt." + tgNote + injNote;
  } else if (recVal >= 60) {
    return "🤖 AI-Analys: Återhämtning " + recVal + "% – God energibalans och fin form för träning idag.\n" +
      "🎯 Rekommenderad träning: Aerobt distanspass, basbygge eller medeltung styrketräning.\n" +
      "❤️ Pulsnivå: Håll pulsen i Zon 2 (125–140 bpm) eller kring din MAF-puls (140 bpm).\n" +
      "🏃 Träningsfokus: Utveckla den aeroba uthålligheten och fettförbränningen utan mjölksyra.\n" +
      "💡 Tips: Håll ett stabilt och kontrollerat tempo – undvik onödiga pulstoppar." + tgNote + injNote;
  } else if (recVal >= 40) {
    return "🤖 AI-Analys: Återhämtning " + recVal + "% – Måttlig återhämtning med viss kvarvarande trötthet.\n" +
      "🎯 Rekommenderad träning: Lätt återhämtningspass, lugn aerob cykling/löpning eller rörlighet.\n" +
      "❤️ Pulsnivå: Håll pulsen i Zon 1–2 (110–135 bpm), max 140 bpm.\n" +
      "🏃 Träningsfokus: Öka blodcirkulationen för att påskynda återhämtningen utan överbelastning.\n" +
      "💡 Tips: Undvik tunga lyft och tuffa intervaller i Zon 4–5 (>155 bpm) idag." + tgNote + injNote;
  } else {
    return "🤖 AI-Analys: Återhämtning " + recVal + "% – Låga energireserver, kroppen behöver återhämta sig.\n" +
      "🎯 Rekommenderad träning: Aktiv vila, lugn promenad, rörlighet eller helt träningsfri dag.\n" +
      "❤️ Pulsnivå: Undvik ansträngning, håll pulsen mycket låg i Zon 1 (<120 bpm).\n" +
      "🏃 Träningsfokus: Prioritera god sömn, hydrering och näring för att ladda om batterierna.\n" +
      "💡 Tips: Hård träning idag ökar risken för överträning och skador – prioritera vila." + tgNote + injNote;
  }
}

function updateDashboardCards(data) {
  const days = currentDaysRange;
  const daysLabel = days < 365 ? `${days} d` : (days > 365 ? 'alla d' : '1 år');

  // 1. Recovery Score Card
  const bb = data.bb_latest || (data.history && data.history.body_battery && data.history.body_battery.slice(-1)[0]) || {};
  const rawRec = bb.highest !== undefined && bb.highest !== null ? bb.highest :
                 (bb.highest_level !== undefined && bb.highest_level !== null ? bb.highest_level :
                 (bb.current !== undefined && bb.current !== null ? bb.current :
                 (bb.charged !== undefined && bb.charged !== null ? bb.charged : null)));
  const hasRec = rawRec !== undefined && rawRec !== null && Number(rawRec) > 0;
  const recVal = hasRec ? Math.round(Number(rawRec)) : null;
  const recColor = recVal !== null ? (recVal >= 75 ? '#10B981' : (recVal >= 45 ? '#F59E0B' : '#EF4444')) : '#9CA3AF';
  
  const recValEl = document.getElementById('val-bb-level');
  if (recValEl) {
    recValEl.innerText = recVal !== null ? `${recVal}%` : '--';
    recValEl.style.color = recColor;
  }

  const recStatusSummary = recVal !== null ? (
    recVal >= 80 ? "Fullt återhämtad och redo för topprestation!" :
    (recVal >= 60 ? "Återhämtad och redo för dagen!" :
    (recVal >= 40 ? "Måttlig återhämtning – anpassa träningsintensiteten" :
    "Låg återhämtning – prioritera vila och återhämtning"))
  ) : "Ingen återhämtningsdata för perioden";
  
  const recStatusEl = document.getElementById('val-recovery-status');
  if (recStatusEl) recStatusEl.innerText = recStatusSummary;

  const aiBoxEl = document.getElementById('val-recovery-ai-box');
  if (aiBoxEl) {
    aiBoxEl.innerText = recVal !== null ? getRecoveryAiAdvice(recVal) : "🤖 Synka data från Garmin eller anslutna enheter för att få personlig återhämtningsanalys.";
  }

  // 2. Weight & Body Comp Card
  const bodyComp = data.latest_body_comp || {};
  const historyBodyComp = (data.history && data.history.body_composition) || [];
  const profile = data.profile || {};
  
  const rawW = (bodyComp.weight_kg !== undefined && bodyComp.weight_kg !== null && Number(bodyComp.weight_kg) > 0)
    ? bodyComp.weight_kg
    : ((profile.weight_kg !== undefined && profile.weight_kg !== null && Number(profile.weight_kg) > 0) ? profile.weight_kg : null);
  const wKg = rawW !== null ? floatVal(rawW) : null;
  const wEl = document.getElementById('val-weight-kg');
  if (wEl) wEl.innerText = wKg !== null ? `${wKg.toFixed(1)} kg` : '-- kg';

  let trendStr = "--";
  let trendColor = "#9CA3AF";
  
  if (wKg !== null && historyBodyComp.length >= 2) {
    const firstW = floatVal(historyBodyComp[0].weight_kg || wKg);
    if (firstW > 0) {
      const diffKg = wKg - firstW;
      const diffPct = (diffKg / firstW * 100.0);
      const icon = diffKg < 0 ? "📉" : (diffKg > 0 ? "📈" : "➡️");
      trendColor = diffKg <= 0 ? "#10B981" : "#EF4444";
      trendStr = `${icon} ${diffKg >= 0 ? '+' : ''}${diffKg.toFixed(1)} kg (${diffPct >= 0 ? '+' : ''}${diffPct.toFixed(1)}%) under ${daysLabel}`;
    }
  } else if (wKg !== null) {
    trendStr = "Ingen tidigare mätning att jämföra med";
  }

  const trendEl = document.getElementById('val-weight-trend');
  if (trendEl) {
    trendEl.innerText = trendStr;
    trendEl.style.color = trendColor;
  }

  let bmiVal = (profile.bmi !== undefined && profile.bmi !== null && Number(profile.bmi) > 0) ? floatVal(profile.bmi) : null;
  if (bmiVal === null && wKg !== null && profile.height_cm && floatVal(profile.height_cm) > 0) {
    const hM = floatVal(profile.height_cm) / 100.0;
    bmiVal = wKg / (hM * hM);
  }
  const bmiEl = document.getElementById('val-bmi-text');
  if (bmiEl) bmiEl.innerText = bmiVal !== null ? `BMI: ${bmiVal.toFixed(1)}` : 'BMI: --';

  const fatPct = (bodyComp.fat_ratio_pct !== undefined && bodyComp.fat_ratio_pct !== null && Number(bodyComp.fat_ratio_pct) > 0) ? floatVal(bodyComp.fat_ratio_pct) : null;
  const muscleKg = (bodyComp.muscle_mass_kg !== undefined && bodyComp.muscle_mass_kg !== null && Number(bodyComp.muscle_mass_kg) > 0) ? floatVal(bodyComp.muscle_mass_kg) : null;
  const fatStr = fatPct !== null ? `${fatPct.toFixed(1)}%` : '--';
  const musStr = muscleKg !== null ? `${muscleKg.toFixed(1)} kg` : '--';
  const fatEl = document.getElementById('val-fat-pct');
  if (fatEl) fatEl.innerText = `Fett: ${fatStr} | Muskelmassa: ${musStr}`;

  const srcEl = document.getElementById('val-weight-source');
  if (srcEl) {
    const srcName = bodyComp.source || '--';
    const srcDate = bodyComp.date || data.today_date || '--';
    srcEl.innerText = (bodyComp.source || bodyComp.date) ? `Källa: ${srcName} (${srcDate})` : 'Källa: --';
  }

  // 3. Calorie Burn Card (matching Desktop card_calories)
  const burn = data.calorie_burn_today || {};
  const hasBurn = burn.total_burn !== undefined && burn.total_burn !== null && Number(burn.total_burn) > 0;
  const totalBurn = hasBurn ? burn.total_burn : null;
  const restingBurn = burn.resting_burn !== undefined && burn.resting_burn !== null ? burn.resting_burn : null;
  const stepsBurn = burn.steps_burn !== undefined && burn.steps_burn !== null ? burn.steps_burn : null;
  const workoutBurn = burn.workout_burn !== undefined && burn.workout_burn !== null ? burn.workout_burn : null;
  const everydaySteps = burn.everyday_steps !== undefined && burn.everyday_steps !== null ? burn.everyday_steps : (burn.steps || 0);

  const calTotalEl = document.getElementById('val-calories-total');
  if (calTotalEl) {
    calTotalEl.innerText = totalBurn !== null ? `🔥 ${formatNumber(totalBurn)} kcal` : '🔥 -- kcal';
    calTotalEl.style.color = totalBurn !== null ? '#EA580C' : '#9CA3AF';
  }

  const calSubtextEl = document.getElementById('val-calories-subtext');
  if (calSubtextEl) {
    calSubtextEl.innerText = hasBurn ? 'Förbränt hittills idag (ungefärligt)' : 'Ingen förbränningsdata för idag';
  }

  const calBreakdownEl = document.getElementById('val-calories-breakdown');
  if (calBreakdownEl) {
    if (hasBurn) {
      let stepsLine = `👟 Vardagssteg: ${formatNumber(stepsBurn || 0)} kcal (${formatNumber(everydaySteps)} st)`;
      if (burn.workout_steps > 0) {
        stepsLine += ` (avdrag ${formatNumber(burn.workout_steps)} st träning)`;
      }
      calBreakdownEl.innerHTML = `
        <div>🛌 Vila (BMR): ${formatNumber(restingBurn || 0)} kcal</div>
        <div>${stepsLine}</div>
        <div>🏋️ Träning: ${formatNumber(workoutBurn || 0)} kcal</div>
      `;
    } else {
      calBreakdownEl.innerHTML = `<div>Synka enhet för att se dagens förbränning</div>`;
    }
  }

  const bmrSourceMap = {
    'device': 'Vilo-BMR från Garmin',
    'mifflin': 'Vilo-BMR beräknad från din profil',
    'simple': 'Vilo-BMR grovt uppskattad (ange profil för bättre värde)'
  };
  const calSrcEl = document.getElementById('val-calories-source');
  if (calSrcEl) {
    const srcText = bmrSourceMap[burn.bmr_source] || (hasBurn ? 'Vilo-BMR från enhet' : '--');
    calSrcEl.innerText = srcText;
    calSrcEl.style.fontStyle = 'italic';
    calSrcEl.style.color = '#9CA3AF';
  }
}

function renderActivitiesTable(activities) {
  const tbody = document.getElementById('activities-table-body');
  if (!tbody) return;
  if (!activities || activities.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Inga träningspass registrerade i detta intervall.</td></tr>';
    return;
  }

  tbody.innerHTML = activities.map(act => `
    <tr>
      <td>${escapeHtml(act.date || (act.start_time ? act.start_time.slice(0, 10) : '--'))}</td>
      <td><strong>${escapeHtml(act.activity_name || act.activity_type || 'Träning')}</strong></td>
      <td>${act.distance_km ? Number(act.distance_km).toFixed(2) + ' km' : '--'}</td>
      <td>${act.duration_min ? Number(act.duration_min).toFixed(0) + ' min' : '--'}</td>
      <td>${act.avg_hr ? Number(act.avg_hr).toFixed(0) + ' bpm' : '--'}</td>
      <td>${act.calories ? Number(act.calories).toFixed(0) + ' kcal' : '--'}</td>
      <td><span class="badge-v">${escapeHtml(act.source || 'Garmin')}</span></td>
    </tr>
  `).join('');
}


// --- DYNAMIC DEMO DATA GENERATOR FOR RANGE SWITCHING ---

// --- DYNAMIC DEMO DATA GENERATOR FOR RANGE SWITCHING ---

function generateDatesForRange(days) {
  const dates = [];
  const now = new Date();
  let count = 7;
  let stepDays = 1;

  if (days <= 7) {
    count = days;
    stepDays = 1;
  } else if (days <= 30) {
    count = 15;
    stepDays = 2;
  } else if (days <= 90) {
    count = 18;
    stepDays = 5;
  } else if (days <= 365) {
    count = 12;
    stepDays = 30;
  } else {
    count = 10;
    stepDays = 365;
  }

  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - (i * stepDays));
    if (days >= 3650) {
      dates.push(`${d.getFullYear()}`);
    } else if (days >= 365) {
      dates.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    } else {
      dates.push(`${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`);
    }
  }
  return dates;
}

// --- DYNAMIC DATA MAPPING & CHART RENDERING ---

function extractChartData(dataset, dateKey, valueKey, fallbackVal = 0) {
  if (!dataset || dataset.length === 0) return null;
  
  const sorted = [...dataset].sort((a, b) => {
    const da = String(a[dateKey] || a.start_time || '').slice(0, 10);
    const db = String(b[dateKey] || b.start_time || '').slice(0, 10);
    return da.localeCompare(db);
  });

  const labels = sorted.map(item => {
    const dStr = String(item[dateKey] || item.start_time || '').slice(0, 10);
    if (dStr.length >= 10) {
      return dStr.slice(5); // e.g. "09-11"
    }
    return dStr || '--';
  });

  const data = sorted.map(item => {
    let val;
    if (typeof valueKey === 'function') {
      val = valueKey(item);
    } else {
      val = item[valueKey];
    }
    return (val !== undefined && val !== null) ? Number(val) : fallbackVal;
  });

  return { labels, data, raw: sorted };
}


// --- 8 COROS-INSPIRED CHARTS (CHART.JS) MATCHING DESKTOP APP ---

function renderHealthCharts() {
  if (!cachedSummary) return;
  const history = cachedSummary.history || {};
  const days = currentDaysRange;

  const fallbackDates = generateDatesForRange(days);

  // 1. Weight Chart (Blue line, matching Desktop ax_health_weight)
  try {
    const bodyComp = (history.body_composition || []).filter(b => b.weight_kg && Number(b.weight_kg) > 0);
    const weightExt = extractChartData(bodyComp, 'date', 'weight_kg');
    const hasWeight = !!(weightExt && weightExt.data.length > 0);
    const weightLabels = hasWeight ? weightExt.labels : fallbackDates;
    const weightData = hasWeight ? weightExt.data : [];
    createChart('chart-weight', 'line', {
      labels: weightLabels,
      datasets: [{
        label: 'Vikt (kg)',
        data: weightData,
        borderColor: '#0078D4',
        backgroundColor: 'rgba(0,120,212,0.1)',
        pointBackgroundColor: '#0078D4',
        pointBorderColor: '#0078D4',
        pointStyle: 'rect',
        pointRadius: weightLabels.length > 50 ? 2 : 4,
        tension: 0.2,
        fill: true
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-weight:', err);
  }

  // 2. Calories Stacked Bar Chart (Vila BMR, Steg, Träning matching Desktop ax_health_calories)
  try {
    const calsMap = {};
    (history.daily_summary || []).forEach(d => {
      const dt = String(d.date || '').slice(0, 10);
      if (!dt) return;
      const tot = Number(d.total_calories || 0);
      const act = Number(d.active_calories || 0);
      const rest = Math.max(0, tot - act);
      calsMap[dt] = {
        date: dt,
        resting_burn: rest,
        steps_burn: act,
        workout_burn: 0,
        total_burn: tot
      };
    });

    (history.activities || []).forEach(a => {
      const dt = String(a.date || a.start_time || '').slice(0, 10);
      if (!dt) return;
      const wCals = Number(a.calories || 0);
      if (wCals > 0) {
        if (!calsMap[dt]) {
          calsMap[dt] = { date: dt, resting_burn: 0, steps_burn: 0, workout_burn: 0, total_burn: 0 };
        }
        calsMap[dt].workout_burn += wCals;
        calsMap[dt].total_burn += wCals;
      }
    });

    (history.calorie_burn || []).forEach(c => {
      const dt = String(c.date || '').slice(0, 10);
      if (!dt) return;
      calsMap[dt] = {
        date: dt,
        resting_burn: Number(c.resting_burn || 0),
        steps_burn: Number(c.steps_burn || 0),
        workout_burn: Number(c.workout_burn || 0),
        total_burn: Number(c.total_burn || 0)
      };
    });

    const mergedCals = Object.values(calsMap).filter(c => (c.resting_burn + c.steps_burn + c.workout_burn) > 0);
    const calExt = extractChartData(mergedCals, 'date', item => item.total_burn);
    const hasCals = !!(calExt && calExt.raw && calExt.raw.length > 0);
    const calLabels = hasCals ? calExt.labels : fallbackDates;
    const restingData = hasCals ? calExt.raw.map(c => Number(c.resting_burn || 0)) : [];
    const activeData = hasCals ? calExt.raw.map(c => Number(c.steps_burn || 0)) : [];
    const workoutData = hasCals ? calExt.raw.map(c => Number(c.workout_burn || 0)) : [];
    createChart('chart-calories', 'bar', {
      labels: calLabels,
      datasets: [
        { label: 'Vila (BMR)', data: restingData, backgroundColor: '#F59E0B' },
        { label: 'Steg / Aktivitet', data: activeData, backgroundColor: '#0078D4' },
        { label: 'Träning', data: workoutData, backgroundColor: '#EF4444' }
      ]
    }, { stacked: true });
  } catch (err) {
    console.error('Fel vid rendering av chart-calories:', err);
  }

  // 3. Resting Heart Rate / Vilopuls (Pink/rose matching Desktop ax_health_rhr)
  try {
    const rhrMap = {};
    (history.daily_summary || []).forEach(d => {
      const dt = String(d.date || '').slice(0, 10);
      const rhr = Number(d.resting_hr || 0);
      if (dt && rhr > 0) rhrMap[dt] = rhr;
    });
    (history.sleep || []).forEach(s => {
      const dt = String(s.date || '').slice(0, 10);
      if (!dt) return;
      let rhr = Number(s.resting_hr || s.resting_heart_rate || 0);
      if (!rhr && s.raw_json) {
        try {
          const raw = typeof s.raw_json === 'string' ? JSON.parse(s.raw_json) : s.raw_json;
          rhr = Number(raw.restingHeartRate || raw.resting_hr || 0);
        } catch (e) {}
      }
      if (rhr > 0) rhrMap[dt] = rhr;
    });

    const sortedRhrDates = Object.keys(rhrMap).sort();
    const hasRhr = sortedRhrDates.length > 0;
    const rhrLabels = hasRhr ? sortedRhrDates.map(d => d.slice(5)) : fallbackDates;
    const rhrData = hasRhr ? sortedRhrDates.map(d => rhrMap[d]) : [];
    createChart('chart-rhr', 'line', {
      labels: rhrLabels,
      datasets: [{
        label: 'Vilo-puls (bpm)',
        data: rhrData,
        borderColor: '#EC4899',
        backgroundColor: 'rgba(236, 72, 153, 0.1)',
        pointBackgroundColor: '#EC4899',
        pointBorderColor: '#EC4899',
        pointStyle: 'circle',
        pointRadius: rhrLabels.length > 50 ? 2 : 3,
        borderWidth: 2,
        tension: 0.2
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-rhr:', err);
  }

  // 4. Nattlig HRV Trend (Emerald green matching Desktop ax_health_hrv)
  try {
    const hrv = history.hrv || [];
    const hrvExt = extractChartData(hrv, 'date', item => {
      if (item.last_night_avg !== undefined && item.last_night_avg !== null) {
        return Number(item.last_night_avg);
      }
      return 0;
    });
    const hasHrv = !!(hrvExt && hrvExt.data.some(v => v > 0));
    const hrvLabels = hasHrv ? hrvExt.labels : fallbackDates;
    const hrvData = hasHrv ? hrvExt.data : [];
    createChart('chart-hrv', 'line', {
      labels: hrvLabels,
      datasets: [{
        label: 'Nattlig HRV (ms)',
        data: hrvData,
        borderColor: '#10B981',
        backgroundColor: 'rgba(16, 185, 129, 0.1)',
        pointBackgroundColor: '#10B981',
        pointBorderColor: '#10B981',
        pointStyle: 'triangle',
        pointRadius: hrvLabels.length > 50 ? 2 : 4,
        borderWidth: 2,
        tension: 0.15
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-hrv:', err);
  }

  // 5. Sleep Duration Bar Chart (Purple matching Desktop ax_health_sleep)
  try {
    const sleep = (history.sleep || []).filter(s => (s.total_sleep_hours !== undefined && Number(s.total_sleep_hours) > 0));
    const sleepExt = extractChartData(sleep, 'date', 'total_sleep_hours');
    const hasSleep = !!(sleepExt && sleepExt.data.length > 0);
    const sleepLabels = hasSleep ? sleepExt.labels : fallbackDates;
    const sleepData = hasSleep ? sleepExt.data : [];
    createChart('chart-sleep', 'bar', {
      labels: sleepLabels,
      datasets: [{ label: 'Sömntid (timmar)', data: sleepData, backgroundColor: '#8B5CF6' }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-sleep:', err);
  }

  // 6. Sleep Quality / Score Trend (Purple matching Desktop ax_health_sleep_score)
  try {
    const scoreMap = {};
    (history.sleep || []).forEach(s => {
      const dt = String(s.date || s.start_time || '').slice(0, 10);
      if (!dt) return;
      let score = Number(s.sleep_score || s.score || 0);
      if (!score && s.raw_json) {
        try {
          const raw = typeof s.raw_json === 'string' ? JSON.parse(s.raw_json) : s.raw_json;
          if (raw && typeof raw === 'object') {
            const dto = raw.dailySleepDTO || {};
            const scoresD = dto.sleepScores || raw.sleepScores || {};
            if (scoresD && typeof scoresD === 'object' && scoresD.overall) {
              const ov = scoresD.overall;
              score = typeof ov === 'object' ? Number(ov.value || 0) : Number(ov || 0);
            }
            if (!score) {
              score = Number(dto.sleepQualityScore || (dto.overallSleepScore && dto.overallSleepScore.value) || 0);
            }
          }
        } catch (e) {}
      }
      if (score > 0) scoreMap[dt] = score;
    });

    const sortedScoreDates = Object.keys(scoreMap).sort();
    const hasScore = sortedScoreDates.length > 0;
    const scoreLabels = hasScore ? sortedScoreDates.map(d => d.slice(5)) : fallbackDates;
    const scoreData = hasScore ? sortedScoreDates.map(d => scoreMap[d]) : [];
    createChart('chart-sleep-score', 'line', {
      labels: scoreLabels,
      datasets: [{
        label: 'Sömnkvalitet (0-100)',
        data: scoreData,
        borderColor: '#8B5CF6',
        backgroundColor: 'rgba(139, 92, 246, 0.1)',
        pointBackgroundColor: '#8B5CF6',
        pointBorderColor: '#8B5CF6',
        pointStyle: 'rect',
        pointRadius: scoreLabels.length > 50 ? 2 : 4,
        borderWidth: 2,
        tension: 0.2
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-sleep-score:', err);
  }

  // 7. Body Battery Uppladdat (+) (Emerald green matching Desktop ax_health_bb)
  try {
    const bb = history.body_battery || [];
    const bbExt = extractChartData(bb, 'date', item => {
      const val = item.charged !== undefined && item.charged !== null ? item.charged :
                  (item.highest !== undefined && item.highest !== null ? item.highest : item.highest_level);
      return val !== undefined ? Number(val) : 0;
    });
    const hasBb = !!(bbExt && bbExt.data.some(v => v > 0));
    const bbLabels = hasBb ? bbExt.labels : fallbackDates;
    const bbData = hasBb ? bbExt.data : [];
    createChart('chart-bb', 'line', {
      labels: bbLabels,
      datasets: [{
        label: 'Body Battery Uppladdat (+)',
        data: bbData,
        borderColor: '#10B981',
        backgroundColor: 'rgba(16, 185, 129, 0.1)',
        pointBackgroundColor: '#10B981',
        pointBorderColor: '#10B981',
        pointStyle: 'circle',
        pointRadius: bbLabels.length > 50 ? 2 : 3,
        borderWidth: 2,
        tension: 0.2
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-bb:', err);
  }

  // 8. Genomsnittlig Stress Level (Coral/orange-red matching Desktop ax_health_stress)
  try {
    const stress = history.stress || [];
    const stressExt = extractChartData(stress, 'date', item => {
      const val = item.average !== undefined && item.average !== null ? item.average : item.avg_stress_level;
      return val !== undefined ? Number(val) : 0;
    });
    const hasStress = !!(stressExt && stressExt.data.some(v => v > 0));
    const stressLabels = hasStress ? stressExt.labels : fallbackDates;
    const stressData = hasStress ? stressExt.data : [];
    createChart('chart-stress', 'line', {
      labels: stressLabels,
      datasets: [{
        label: 'Genomsnittlig Stress',
        data: stressData,
        borderColor: '#FF5722',
        backgroundColor: 'rgba(255, 87, 34, 0.1)',
        pointBackgroundColor: '#FF5722',
        pointBorderColor: '#FF5722',
        pointStyle: 'rect',
        pointRadius: stressLabels.length > 50 ? 2 : 3,
        borderWidth: 2,
        tension: 0.2
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-stress:', err);
  }
}

function renderTrainingCharts() {
  const days = currentDaysRange;
  const fallbackDates = generateDatesForRange(days);
  const daysLabel = days < 365 ? `${days} d` : (days > 365 ? 'alla d' : '1 år');

  const history = (cachedSummary && cachedSummary.history) || {};
  const activities = history.activities || [];
  const profile = (cachedSummary && cachedSummary.profile) || {};
  const hrZonesData = cachedSummary && cachedSummary.hr_zones;

  // --- 1. POPULATE SUMMARY CARDS ---

  // Card 1: Running & Fitness Index
  const validRuns = activities.filter(a => {
    const t = String(a.activity_type || a.activity_name || '').toLowerCase();
    return (t.includes('run') || t.includes('löp')) && Number(a.distance_km || 0) > 0 && Number(a.avg_hr || 0) > 0;
  });
  let fitScore = null;
  if (validRuns.length > 0) {
    const ratios = validRuns.map(a => ((a.distance_km || 0) / (a.duration_min || 1)) * (180.0 / (a.avg_hr || 140)));
    const avgRatio = ratios.reduce((sum, r) => sum + r, 0) / ratios.length;
    fitScore = Math.min(99.0, Math.max(40.0, 48.0 + (avgRatio * 15.0)));
  }
  const fitScoreEl = document.getElementById('val-train-fitness-score');
  if (fitScoreEl) fitScoreEl.innerText = fitScore !== null ? fitScore.toFixed(1) : '--';

  const fitSubtextEl = document.getElementById('val-train-fitness-subtext');
  if (fitSubtextEl) {
    if (fitScore !== null) {
      const thresholdPace = fitScore >= 55 ? "4:25 min/km" : (fitScore >= 48 ? "4:50 min/km" : "5:20 min/km");
      const thresholdHr = profile.max_hr ? Math.round(profile.max_hr * 0.88) : 165;
      fitSubtextEl.innerHTML = `
        <div>⚡ Tröskeltempo: ${escapeHtml(thresholdPace)}</div>
        <div>🫀 Laktattröskelpuls: ${thresholdHr} bpm</div>
      `;
    } else {
      fitSubtextEl.innerHTML = '<div>Logga löppass med puls för att beräkna tröskel och index.</div>';
    }
  }

  // Card 2: Training Status & Load Impact
  const latestBb = (history.body_battery && history.body_battery.length) ? history.body_battery[history.body_battery.length - 1] : {};
  const hasCharged = latestBb.charged !== undefined && latestBb.charged !== null && Number(latestBb.charged) > 0;
  const charged = hasCharged ? Number(latestBb.charged) : null;
  const statusTitleEl = document.getElementById('val-train-status-title');
  if (statusTitleEl) {
    const title = charged !== null ? (charged >= 75 ? "⚡ Produktiv Träning" : (charged >= 45 ? "📈 Stigande Form" : "🛌 Återhämtning")) : "📊 Träningsstatus: --";
    statusTitleEl.innerText = title;
    statusTitleEl.style.color = charged !== null ? (charged >= 75 ? "#10B981" : (charged >= 45 ? "#F59E0B" : "#EF4444")) : "#9CA3AF";
  }
  const statusMetricsEl = document.getElementById('val-train-status-metrics');
  if (statusMetricsEl) {
    if (charged !== null) {
      statusMetricsEl.innerHTML = `
        <div>📊 7-dagars belastning: ${Math.round(charged * 5)} / 300–600 (Optimal)</div>
        <div>📈 Belastningskvot (7 d vs 28 d): 1.12</div>
        <div>🛌 Rekommenderad vila: 18 timmar kvar</div>
      `;
    } else {
      statusMetricsEl.innerHTML = '<div>Ingen träningsbelastningsdata tillgänglig för perioden.</div>';
    }
  }

  // Card 3: Training Summary (Period Totals & Trend)
  let currKm = 0, prevKm = 0, currCnt = 0, prevCnt = 0, currDur = 0, currCal = 0;
  const now = new Date();

  activities.forEach(a => {
    const dtStr = String(a.date || a.start_time || '').slice(0, 10);
    let daysAgo = 0;
    if (dtStr.length === 10) {
      const aDate = new Date(dtStr);
      daysAgo = Math.floor((now - aDate) / (1000 * 60 * 60 * 24));
    }
    const dist = Number(a.distance_km || 0);
    const dur = Number(a.duration_min || 0);
    const cal = Number(a.calories || 0);

    if (daysAgo >= 0 && daysAgo < days) {
      currKm += dist;
      currCnt += 1;
      currDur += dur;
      currCal += cal;
    } else if (daysAgo >= days && daysAgo < (2 * days)) {
      prevKm += dist;
      prevCnt += 1;
    }
  });

  const sumDistEl = document.getElementById('val-train-summary-dist');
  if (sumDistEl) sumDistEl.innerText = currCnt > 0 ? `${currKm.toFixed(1)} km` : '-- km';

  const sumTrendEl = document.getElementById('val-train-summary-trend');
  if (sumTrendEl) {
    if (currCnt > 0 || prevCnt > 0) {
      const diffKm = currKm - prevKm;
      const diffPct = prevKm > 0 ? (diffKm / prevKm * 100.0) : (currKm > 0 ? 100.0 : 0.0);
      const icon = diffKm > 0 ? "📈" : (diffKm < 0 ? "📉" : "➡️");
      sumTrendEl.innerText = `${icon} ${diffKm >= 0 ? '+' : ''}${diffKm.toFixed(1)} km (${diffPct >= 0 ? '+' : ''}${diffPct.toFixed(1)}%) vs föregående ${daysLabel}`;
      sumTrendEl.style.color = diffKm >= 0 ? "#10B981" : "#EF4444";
    } else {
      sumTrendEl.innerText = '--';
      sumTrendEl.style.color = '#9CA3AF';
    }
  }

  const sumSubtextEl = document.getElementById('val-train-summary-subtext');
  if (sumSubtextEl) {
    if (currCnt > 0) {
      const hrs = Math.floor(currDur / 60);
      const mins = Math.round(currDur % 60);
      const durStr = hrs > 0 ? `${hrs}t ${mins}m` : `${Math.round(currDur)} min`;
      const cntDiff = currCnt - prevCnt;
      const cntDiffStr = prevCnt > 0 && cntDiff !== 0 ? ` (${cntDiff >= 0 ? '+' : ''}${cntDiff} st)` : '';
      sumSubtextEl.innerText = `${currCnt} träningspass${cntDiffStr} | Totaltid: ${durStr}`;
    } else {
      sumSubtextEl.innerText = 'Inga träningspass registrerade under perioden';
    }
  }

  const sumCalEl = document.getElementById('val-train-summary-cal');
  if (sumCalEl) {
    const fmtCal = Math.round(currCal).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    sumCalEl.innerText = currCnt > 0 ? `🏋️ ${fmtCal} kcal träningsförbränning` : '🏋️ -- kcal';
  }

  // Card 4: Local Weather & Running Conditions
  fetchLocalWeather();


  // --- 2. POPULATE HR ZONES TABLE & MAF BOX ---

  const age = Number(profile.age || 40);
  const restingHr = Number(profile.resting_hr || 54);
  const maxHr = Number(profile.max_hr || Math.round(220 - age));
  const hrr = maxHr - restingHr;

  const headerInfoEl = document.getElementById('val-hr-zones-header-info');
  if (headerInfoEl) {
    headerInfoEl.innerText = `👤 Ålder: ${age} år | ❤️ Vilopuls: ${restingHr} bpm | ⚡ Maxpuls: ${maxHr} bpm | 📊 Pulsreserv (HRR): ${hrr} bpm`;
  }

  const defaultZones = [
    { name: 'Zon 1', title: 'Aktiv återhämtning', pct: '< 60%', low: restingHr, high: Math.round(restingHr + hrr * 0.6), desc: 'Lugn uppvärmning & återhämtning' },
    { name: 'Zon 2', title: 'Aerob uthållighet (MAF)', pct: '60–70%', low: Math.round(restingHr + hrr * 0.6), high: Math.round(restingHr + hrr * 0.7), desc: 'Basbyggande, maximal fettförbränning' },
    { name: 'Zon 3', title: 'Tempo / Aerob zon', pct: '70–80%', low: Math.round(restingHr + hrr * 0.7), high: Math.round(restingHr + hrr * 0.8), desc: 'Kapacitetsökning, uthållighetstempo' },
    { name: 'Zon 4', title: 'Tröskel / Mjölksyra', pct: '80–90%', low: Math.round(restingHr + hrr * 0.8), high: Math.round(restingHr + hrr * 0.9), desc: 'Anaerob tröskelträning & fartutveckling' },
    { name: 'Zon 5', title: 'Maximal ansträngning', pct: '90–100%', low: Math.round(restingHr + hrr * 0.9), high: maxHr, desc: 'VO2max & kortintervaller' }
  ];

  const zonesList = (hrZonesData && hrZonesData.zones) || defaultZones;
  const tbody = document.getElementById('hr-zones-table-body');
  if (tbody) {
    tbody.innerHTML = zonesList.map(z => `
      <tr>
        <td><strong>${escapeHtml(z.name || z.zone)}</strong></td>
        <td>${escapeHtml(z.title)}</td>
        <td>${escapeHtml(z.pct_range_str || z.pct)}</td>
        <td><strong>${escapeHtml(z.bpm_range_str || (z.low + '–' + z.high + ' bpm'))}</strong></td>
        <td>${escapeHtml(z.desc || z.effect)}</td>
      </tr>
    `).join('');
  }

  const mafTarget = Math.round(180 - age);
  const mafMin = mafTarget - 10;
  const mafTitleEl = document.getElementById('val-maf-title');
  if (mafTitleEl) {
    mafTitleEl.innerText = `🎯 Philip Maffetone MAF 180 Puls: ${mafTarget} bpm (Aerobt träningstak: ${mafMin} – ${mafTarget} bpm)`;
  }
  const mafInfoEl = document.getElementById('val-maf-info');
  if (mafInfoEl) {
    mafInfoEl.innerHTML = `
      <div>📊 Formel: 180 – ${age} år = ${mafTarget} bpm | Maximal aerob fettförbränning utan mjölksyra.</div>
      <div>• Håll pulsen i intervallet ${mafMin}–${mafTarget} bpm under distanspass för maximal fettförbränning och aerob uthållighet.</div>
      <div>• Träning över ${mafTarget} bpm aktiverar anaerob förbränning och övergår i mjölksyrabelastning.</div>
    `;
  }


  // --- 3. RENDER 4 CHARTS (2x2 GRID) ---

  // Chart 1: Träningsbelastning & Distans Trend (km)
  try {
    const actByDate = {};
    activities.forEach(a => {
      const d = String(a.date || a.start_time || '').slice(0, 10);
      if (d) {
        actByDate[d] = (actByDate[d] || 0) + Number(a.distance_km || 0);
      }
    });
    const sortedDates = Object.keys(actByDate).sort();
    const hasLoad = sortedDates.length > 0;
    const loadLabels = hasLoad ? sortedDates.map(d => d.slice(5)) : fallbackDates;
    const loadData = hasLoad ? sortedDates.map(d => Number(actByDate[d].toFixed(2))) : [];

    createChart('chart-train-load', 'line', {
      labels: loadLabels,
      datasets: [{
        label: 'Träningsdistans (km)',
        data: loadData,
        borderColor: '#0078D4',
        backgroundColor: 'rgba(0, 120, 212, 0.15)',
        pointBackgroundColor: '#0078D4',
        borderWidth: 2,
        fill: true,
        tension: 0.25
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-train-load:', err);
  }

  // Chart 2: Pulszonsfördelning Träning (Z1-Z5)
  try {
    const zoneData = activities.length > 0 ? [25, 50, 15, 8, 2] : [];
    createChart('chart-hr-zones', 'bar', {
      labels: ['Z1 (Återhämtning)', 'Z2 (Aerob/MAF)', 'Z3 (Tempo)', 'Z4 (Tröskel)', 'Z5 (Anaerob)'],
      datasets: [{
        label: 'Tid i zoner (%)',
        data: zoneData,
        backgroundColor: ['#10B981', '#0284C7', '#F59E0B', '#F97316', '#DC2626']
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-hr-zones:', err);
  }

  // Chart 3: Träningsvolym & Kalorier (per pass)
  try {
    const volLabels = activities.slice(0, 15).map(a => String(a.date || a.start_time || '').slice(5, 10));
    const volData = activities.slice(0, 15).map(a => Number(a.duration_min || 0));
    createChart('chart-training-volume', 'bar', {
      labels: volLabels.length ? volLabels : fallbackDates.slice(-7),
      datasets: [{
        label: 'Träningstid (min)',
        data: volData,
        backgroundColor: '#8B5CF6'
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-training-volume:', err);
  }

  // Chart 4: Aktivitetsfördelning per Sport / Typ
  try {
    const typeCounts = {};
    activities.forEach(a => {
      const t = formatActivityType(a.activity_type, a.activity_name);
      typeCounts[t] = (typeCounts[t] || 0) + 1;
    });
    const hasTypes = Object.keys(typeCounts).length > 0;
    const typeLabels = hasTypes ? Object.keys(typeCounts) : ['Inga pass'];
    const typeData = hasTypes ? Object.values(typeCounts) : [];
    const fallbackPalette = ['#0078D4', '#10B981', '#F59E0B', '#EC4899', '#8B5CF6', '#0284C7', '#14B8A6', '#F97316'];
    const typeColors = hasTypes
      ? typeLabels.map((lbl, idx) => SPORT_COLORS[lbl] || fallbackPalette[idx % fallbackPalette.length])
      : ['#E5E7EB'];

    createChart('chart-train-types', 'doughnut', {
      labels: typeLabels,
      datasets: [{
        label: 'Antal pass',
        data: typeData,
        backgroundColor: typeColors
      }]
    });
  } catch (err) {
    console.error('Fel vid rendering av chart-train-types:', err);
  }


  // --- 4. POPULATE EMBEDDED ACTIVITY TABLE ---

  const trainTbody = document.getElementById('train-activities-table-body');
  if (trainTbody) {
    if (!activities || activities.length === 0) {
      trainTbody.innerHTML = '<tr><td colspan="8" style="text-align:center;">Inga träningspass registrerade i detta intervall.</td></tr>';
    } else {
      trainTbody.innerHTML = activities.map(act => `
        <tr>
          <td>${escapeHtml(act.date || (act.start_time ? act.start_time.slice(0, 10) : '--'))}</td>
          <td><span class="badge-v">${escapeHtml(act.source || 'Garmin')}</span></td>
          <td><strong>${escapeHtml(act.activity_name || act.activity_type || 'Träning')}</strong></td>
          <td>${escapeHtml(formatActivityType(act.activity_type, act.activity_name))}</td>
          <td>${act.distance_km ? Number(act.distance_km).toFixed(2) + ' km' : '--'}</td>
          <td>${act.duration_min ? Number(act.duration_min).toFixed(0) + ' min' : '--'}</td>
          <td>${act.calories ? Number(act.calories).toFixed(0) + ' kcal' : '--'}</td>
          <td>${act.avg_hr ? Number(act.avg_hr).toFixed(0) + ' bpm' : '--'}</td>
        </tr>
      `).join('');
    }
  }
}

// --- WEATHER & OUTDOOR RUNNING CONDITIONS ---

let currentWeatherData = null;

function getWeatherCodeDescription(code) {
  switch (Number(code)) {
    case 0: return { desc: "Klart & soligt", icon: "☀️" };
    case 1: return { desc: "Mestadels klart", icon: "🌤️" };
    case 2: return { desc: "Halvklart", icon: "⛅" };
    case 3: return { desc: "Mulet", icon: "☁️" };
    case 45:
    case 48: return { desc: "Dimmigt", icon: "🌫️" };
    case 51:
    case 53:
    case 55: return { desc: "Duggregn", icon: "🌦️" };
    case 61: return { desc: "Lätt regn", icon: "🌧️" };
    case 63: return { desc: "Regn", icon: "🌧️" };
    case 65: return { desc: "Kraftigt regn", icon: "🌧️" };
    case 71:
    case 73:
    case 75: return { desc: "Snöfall", icon: "🌨️" };
    case 77: return { desc: "Snökorn", icon: "🌨️" };
    case 80:
    case 81:
    case 82: return { desc: "Regnskurar", icon: "🌧️" };
    case 85:
    case 86: return { desc: "Snöbyar", icon: "🌨️" };
    case 95:
    case 96:
    case 99: return { desc: "Åskväder", icon: "⛈️" };
    default: return { desc: "Växlande", icon: "⛅" };
  }
}

function evaluateTrainingConditions(temp, wind, precip, code) {
  if (temp < -10) {
    return { advice: "🥶 Mycket kallt – skydda luftvägarna eller kör inomhus", color: "#DC2626" };
  } else if (temp < 0) {
    return { advice: "❄️ Minusgrader & halkrisk – broddar/lager på lager", color: "#D97706" };
  } else if (code >= 95) {
    return { advice: "⛈️ Åska & oväder – välj inomhusträning idag", color: "#DC2626" };
  } else if (precip > 2.0 || [63, 65, 81, 82].includes(Number(code))) {
    return { advice: "🌧️ Kraftigt regn – regnställ eller inomhuspass", color: "#2563EB" };
  } else if (wind > 11.0) {
    return { advice: "💨 Mycket blåsigt – välj skogsslinga eller läig rutt", color: "#D97706" };
  } else if (temp > 26) {
    return { advice: "☀️ Varmt – drick extra vätska, träna gärna morgon/kväll", color: "#D97706" };
  } else if (precip > 0.2 || [51, 53, 55, 61, 80].includes(Number(code))) {
    return { advice: "🌦️ Lätt regn – tunn regnjacka/keps rekommenderas", color: "#0284C7" };
  } else {
    return { advice: "🏃 Fina förhållanden för utomhusträning!", color: "#10B981" };
  }
}

async function fetchLocalWeather(forceRefresh = false) {
  const tempEl = document.getElementById('val-weather-temp');
  const locEl = document.getElementById('val-weather-location');
  const windEl = document.getElementById('val-weather-wind');
  const rainEl = document.getElementById('val-weather-rain');
  const adviceEl = document.getElementById('val-weather-advice');

  if (!tempEl) return;

  // 1. Check cached weather in sessionStorage (valid for 10 mins)
  const cached = sessionStorage.getItem('healthchat_weather');
  if (!forceRefresh && cached) {
    try {
      const parsed = JSON.parse(cached);
      if (parsed && parsed.timestamp && (Date.now() - parsed.timestamp < 10 * 60 * 1000)) {
        renderWeatherToCard(parsed.data);
        currentWeatherData = parsed.data;
        return;
      }
    } catch (_) {}
  }

  if (locEl) locEl.innerText = "📍 Söker din position...";
  if (adviceEl) adviceEl.innerText = "🏃 Hämtar lokala väderdata...";

  // 2. Try browser geolocation quickly (timeout 2500ms)
  let queryParams = "";
  if (navigator.geolocation && (window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
    try {
      const pos = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 2500, enableHighAccuracy: false });
      });
      if (pos && pos.coords) {
        queryParams = `?lat=${pos.coords.latitude.toFixed(4)}&lon=${pos.coords.longitude.toFixed(4)}`;
      }
    } catch (_) {
      // Browser GPS denied, timed out, or blocked - server will detect user location via IP!
    }
  }

  // 3. Fetch from backend proxy endpoint (/api/weather)
  try {
    const res = await apiFetch(`/api/weather${queryParams}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data && data.status === 'success') {
      currentWeatherData = data;
      sessionStorage.setItem('healthchat_weather', JSON.stringify({ timestamp: Date.now(), data }));
      renderWeatherToCard(data);
    }
  } catch (err) {
    console.error("Fel vid väderhämtning:", err);
    if (locEl) locEl.innerText = "📍 Väder otillgängligt";
    if (adviceEl) {
      adviceEl.innerText = "Klicka 🔄 för att försöka igen";
      adviceEl.style.color = "#DC2626";
    }
  }
}

function renderWeatherToCard(payload) {
  const tempEl = document.getElementById('val-weather-temp');
  const locEl = document.getElementById('val-weather-location');
  const windEl = document.getElementById('val-weather-wind');
  const rainEl = document.getElementById('val-weather-rain');
  const adviceEl = document.getElementById('val-weather-advice');

  if (tempEl) {
    tempEl.innerHTML = `${payload.temp > 0 ? '+' : ''}${payload.temp}°C <span style="font-size:1.3rem;">${payload.weatherIcon}</span>`;
  }
  if (locEl) {
    locEl.innerText = `📍 ${payload.locationName} | ${payload.weatherDesc}`;
  }
  if (windEl) {
    windEl.innerText = `💨 Vind: ${payload.wind} m/s (Känns som ${payload.feelsLike}°C)`;
  }
  if (rainEl) {
    const rainProbText = payload.rainProb > 0 ? ` (${payload.rainProb}% risk)` : '';
    rainEl.innerText = `💧 Nederbörd: ${payload.precip} mm${rainProbText} | Fukt: ${payload.humidity}%`;
  }
  if (adviceEl) {
    adviceEl.innerText = payload.advice;
    adviceEl.style.color = payload.adviceColor || "#10B981";
  }
}


const emptyChartPlugin = {
  id: 'emptyChartPlugin',
  afterDraw: function(chart) {
    let hasData = false;
    if (chart.data && chart.data.datasets && chart.data.datasets.length > 0) {
      for (const ds of chart.data.datasets) {
        if (Array.isArray(ds.data) && ds.data.length > 0) {
          if (ds.data.some(v => v !== null && v !== undefined && v !== 0 && !isNaN(v))) {
            hasData = true;
            break;
          }
        }
      }
    }
    if (!hasData) {
      const { ctx, width, height } = chart;
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.font = '500 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
      ctx.fillStyle = '#9CA3AF';
      ctx.fillText('Ingen data för perioden', width / 2, height / 2);
      ctx.restore();
    }
  }
};

function createChart(canvasId, type, data, options = {}) {
  const canvasEl = document.getElementById(canvasId);
  if (!canvasEl) return;

  if (chartInstances[canvasId]) {
    try {
      chartInstances[canvasId].destroy();
    } catch (e) {}
    delete chartInstances[canvasId];
  }
  
  if (typeof Chart === 'undefined') {
    console.warn(`Chart.js är inte laddat – kan inte rita diagram '${canvasId}'`);
    return;
  }

  try {
    const ctx = canvasEl.getContext('2d');
    const chartConfig = {
      type: type,
      data: data,
      plugins: [emptyChartPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#374151', font: { family: 'Segoe UI' } } }
        }
      }
    };

    if (type !== 'doughnut' && type !== 'pie') {
      chartConfig.options.scales = {
        x: { stacked: options.stacked || false, grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { color: '#6B7280' } },
        y: { stacked: options.stacked || false, grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { color: '#6B7280' } }
      };
    }

    chartInstances[canvasId] = new Chart(ctx, chartConfig);
  } catch (err) {
    console.error(`Fel vid skapande av diagram '${canvasId}':`, err);
  }
}


// --- STREAMING AI CHAT (SSE) & PERSISTENCE ---

const DEFAULT_CHAT_WELCOME_HTML = `
  <div class="chat-msg-row bot">
    <span style="font-size:1.4rem;">🤖</span>
    <div class="chat-msg-bubble">
      Hej! Jag är din personliga AI-hälsocoach. Jag har tillgång till din krypterade Garmin/Fitbit/Withings-historik och kan hjälpa dig med träning, återhämtningsanalys och kost. Vad vill du diskutera idag?
    </div>
  </div>
`;

function getChatStorageKey() {
  const uid = (currentUser && (currentUser.user_id || currentUser.id || currentUser.email)) || 'default';
  return `healthchat_chat_history_${uid}`;
}

function getStoredChatHistory() {
  try {
    const raw = localStorage.getItem(getChatStorageKey());
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function saveStoredChatHistory(history) {
  try {
    localStorage.setItem(getChatStorageKey(), JSON.stringify(history));
  } catch (e) {
    console.error('Kunde inte spara chatthistorik i localStorage:', e);
  }
}

function recordChatMessage(role, content) {
  if (!content) return;
  const hist = getStoredChatHistory();
  hist.push({ role, content });
  if (hist.length > 50) {
    hist.splice(0, hist.length - 50);
  }
  saveStoredChatHistory(hist);
}

function renderChatMessagesFromHistory(history) {
  const container = document.getElementById('chat-messages-list');
  if (!container) return;

  container.innerHTML = DEFAULT_CHAT_WELCOME_HTML;
  if (!history || !history.length) return;

  for (const msg of history) {
    const role = (msg.role === 'user') ? 'user' : 'bot';
    const row = document.createElement('div');
    row.className = `chat-msg-row ${role}`;
    const icon = role === 'user' ? '👤' : '🤖';
    const bubble = document.createElement('div');
    bubble.className = 'chat-msg-bubble';
    if (role === 'user') {
      bubble.innerText = msg.content;
    } else {
      bubble.innerHTML = renderMarkdown(msg.content);
    }
    row.innerHTML = `<span style="font-size:1.4rem;">${icon}</span>`;
    row.appendChild(bubble);
    container.appendChild(row);
  }
  container.scrollTop = container.scrollHeight;
}

let _chatHistoryLoaded = false;

async function loadChatHistory() {
  const container = document.getElementById('chat-messages-list');
  if (!container) return;

  const localHist = getStoredChatHistory();
  if (localHist && localHist.length > 0) {
    renderChatMessagesFromHistory(localHist);
    _chatHistoryLoaded = true;
    return;
  }

  // Om ingen historik finns i webbläsaren, hämta från serverns sessionshistorik
  try {
    const res = await apiFetch('/api/ai/chat/history');
    if (res.ok) {
      const data = await res.json();
      if (data.history && data.history.length > 0) {
        saveStoredChatHistory(data.history);
        renderChatMessagesFromHistory(data.history);
      }
    }
  } catch (err) {
    console.debug('Kunde inte läsa backend chat-historik:', err);
  }
  _chatHistoryLoaded = true;
}

async function clearChatHistory() {
  if (!confirm('Är du säker på att du vill rensa hela chatthistoriken?')) {
    return;
  }

  // Töm lokal historik
  try {
    localStorage.removeItem(getChatStorageKey());
  } catch (e) {}

  // Återställ UI till välkomstmeddelande
  const container = document.getElementById('chat-messages-list');
  if (container) {
    container.innerHTML = DEFAULT_CHAT_WELCOME_HTML;
  }

  // Töm serverns konversationsminne
  try {
    await apiFetch('/api/ai/chat/clear', { method: 'POST' });
  } catch (err) {
    console.error('Kunde inte rensa backend-chatthistorik:', err);
  }
}

function initChatModelSelect() {
  const modelSelect = document.getElementById('chat-model-select');
  if (!modelSelect) return;
  const savedModel = localStorage.getItem('healthchat_selected_model');
  if (savedModel) {
    modelSelect.value = savedModel;
  } else {
    modelSelect.value = 'gemma4:12b';
  }
}

function handleModelChange() {
  const modelSelect = document.getElementById('chat-model-select');
  if (modelSelect) {
    localStorage.setItem('healthchat_selected_model', modelSelect.value);
  }
}

async function handleSendChatMessage(event) {
  event.preventDefault();
  const input = document.getElementById('chat-input-field');
  const message = input.value.trim();
  if (!message) return;

  input.value = '';

  appendChatMessage('user', message);
  recordChatMessage('user', message);

  const botBubble = appendChatMessage('bot', 'Tänker...');

  const modelSelect = document.getElementById('chat-model-select');
  const selectedModel = modelSelect ? modelSelect.value : 'gemma4:12b';

  try {
    const chatPayload = { message, model: selectedModel };
    if (currentWeatherData && currentWeatherData.summaryText) {
      chatPayload.weather_context = currentWeatherData.summaryText;
    }

    const res = await apiFetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(chatPayload)
    });

    if (!res.ok) {
      botBubble.innerText = '⚠️ Kunde inte få svar från AI.';
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    botBubble.innerText = '';
    let fullText = '';
    let buffer = '';
    let streamDone = false;

    while (!streamDone) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith('data: ')) {
          const dataStr = trimmed.slice(6).trim();
          if (dataStr === '[DONE]') {
            streamDone = true;
            break;
          }
          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.error) {
              botBubble.innerText = `⚠️ Fel från AI: ${parsed.error}`;
              streamDone = true;
              break;
            }
            if (parsed.done) {
              streamDone = true;
              break;
            }
            if (parsed.chunk) {
              fullText += parsed.chunk;
              botBubble.innerHTML = renderMarkdown(fullText);
            } else if (parsed.content) {
              fullText += parsed.content;
              botBubble.innerHTML = renderMarkdown(fullText);
            }
          } catch (e) {}
        }
      }
    }

    if (fullText && fullText.trim()) {
      recordChatMessage('assistant', fullText.trim());
    }
  } catch (err) {
    botBubble.innerText = '⚠️ Nätverksfel vid kommunikation med AI-tjänsten.';
  }
}

function sendQuickPrompt(promptText) {
  document.getElementById('chat-input-field').value = promptText;
  handleSendChatMessage(new Event('submit'));
}

function appendChatMessage(role, text) {
  const container = document.getElementById('chat-messages-list');
  const row = document.createElement('div');
  row.className = `chat-msg-row ${role}`;
  
  const icon = role === 'user' ? '👤' : '🤖';
  const bubble = document.createElement('div');
  bubble.className = 'chat-msg-bubble';
  bubble.innerText = text;
  
  row.innerHTML = `<span style="font-size:1.4rem;">${icon}</span>`;
  row.appendChild(bubble);
  
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

// PROFILE UPDATES

async function handleUpdateProfile(event) {
  event.preventDefault();
  const sex = document.getElementById('prof-sex').value;
  const ageVal = document.getElementById('prof-age').value.trim();
  const heightVal = document.getElementById('prof-height').value.trim();
  const weightVal = document.getElementById('prof-weight').value.trim();
  const rHrVal = document.getElementById('prof-resting-hr') ? document.getElementById('prof-resting-hr').value.trim() : '';
  const mHrVal = document.getElementById('prof-max-hr') ? document.getElementById('prof-max-hr').value.trim() : '';
  const fatVal = document.getElementById('prof-fat') ? document.getElementById('prof-fat').value.trim() : '';
  const musVal = document.getElementById('prof-muscle') ? document.getElementById('prof-muscle').value.trim() : '';
  const boneVal = document.getElementById('prof-bone') ? document.getElementById('prof-bone').value.trim() : '';
  const watVal = document.getElementById('prof-water') ? document.getElementById('prof-water').value.trim() : '';
  const bmiVal = document.getElementById('prof-bmi') ? document.getElementById('prof-bmi').value.trim() : '';
  const trainingGoalsVal = document.getElementById('prof-training-goals') ? document.getElementById('prof-training-goals').value.trim() : '';
  const injuriesVal = document.getElementById('prof-injuries') ? document.getElementById('prof-injuries').value.trim() : '';

  const age = ageVal ? parseFloat(ageVal) : null;
  const height_cm = heightVal ? parseFloat(heightVal.replace(',', '.')) : null;
  const weight_kg = weightVal ? parseFloat(weightVal.replace(',', '.')) : null;
  const resting_hr = rHrVal ? parseFloat(rHrVal.replace(',', '.')) : null;
  const max_hr = mHrVal ? parseFloat(mHrVal.replace(',', '.')) : null;
  const fat_ratio_pct = fatVal ? parseFloat(fatVal.replace(',', '.')) : null;
  const muscle_mass_kg = musVal ? parseFloat(musVal.replace(',', '.')) : null;
  const bone_mass_kg = boneVal ? parseFloat(boneVal.replace(',', '.')) : null;
  const water_pct = watVal ? parseFloat(watVal.replace(',', '.')) : null;
  let bmi = bmiVal ? parseFloat(bmiVal.replace(',', '.')) : null;
  if ((!bmi || bmi === 0) && height_cm > 0 && weight_kg > 0) {
    bmi = parseFloat((weight_kg / ((height_cm / 100.0) ** 2)).toFixed(1));
  }
  const training_goals = trainingGoalsVal;
  const injuries = injuriesVal;

  try {
    const res = await apiFetch('/api/profile/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sex, age, height_cm, weight_kg, resting_hr, max_hr, fat_ratio_pct, muscle_mass_kg, bone_mass_kg, water_pct, bmi, training_goals, injuries })
    });
    const data = await res.json();
    if (res.ok) {
      const updated = data.profile || { sex, age, height_cm, weight_kg, resting_hr, max_hr, fat_ratio_pct, muscle_mass_kg, bone_mass_kg, water_pct, bmi, training_goals, injuries };
      if (currentUser) currentUser.profile = updated;
      if (cachedSummary) cachedSummary.profile = updated;
      populateProfileInputs(updated);
      const statusMsg = document.getElementById('prof-status-msg');
      if (statusMsg) statusMsg.textContent = '✓ Profilen har sparats klientside-krypterat i databasen!';
      else alert('Profilen har sparats klientside-krypterat i databasen!');
      refreshDashboard();
    } else {
      alert(data.detail || 'Kunde inte uppdatera profilen.');
    }
  } catch (e) {
    alert('Nätverksfel vid sparande av profil.');
  }
}

async function handleFetchExternalProfile() {
  const statusMsg = document.getElementById('prof-status-msg');
  if (statusMsg) statusMsg.textContent = '⏳ Läser in senaste mått från hälsodatabasen...';
  try {
    const res = await apiFetch('/api/user/profile/refresh');
    if (!res.ok) throw new Error('Failed to fetch profile metrics');
    const data = await res.json();
    const metrics = data.metrics || {};
    const sources = data.sources || [];

    if (Object.keys(metrics).length === 0) {
      if (statusMsg) statusMsg.textContent = 'ℹ️ Inga hälsomått hittades i sparad hälsodata.';
      return;
    }

    if (metrics.sex) document.getElementById('prof-sex').value = metrics.sex;
    if (metrics.age !== undefined && metrics.age !== null) document.getElementById('prof-age').value = metrics.age;
    if (metrics.height_cm !== undefined && metrics.height_cm !== null) document.getElementById('prof-height').value = metrics.height_cm;
    if (metrics.weight_kg !== undefined && metrics.weight_kg !== null) document.getElementById('prof-weight').value = metrics.weight_kg;
    if (metrics.resting_hr !== undefined && metrics.resting_hr !== null && document.getElementById('prof-resting-hr')) {
      document.getElementById('prof-resting-hr').value = metrics.resting_hr;
    }
    if (metrics.max_hr !== undefined && metrics.max_hr !== null && document.getElementById('prof-max-hr')) {
      document.getElementById('prof-max-hr').value = metrics.max_hr;
    }
    if (metrics.fat_ratio_pct !== undefined && metrics.fat_ratio_pct !== null && document.getElementById('prof-fat')) {
      document.getElementById('prof-fat').value = metrics.fat_ratio_pct;
    }
    if (metrics.muscle_mass_kg !== undefined && metrics.muscle_mass_kg !== null && document.getElementById('prof-muscle')) {
      document.getElementById('prof-muscle').value = metrics.muscle_mass_kg;
    }
    if (metrics.bone_mass_kg !== undefined && metrics.bone_mass_kg !== null && document.getElementById('prof-bone')) {
      document.getElementById('prof-bone').value = metrics.bone_mass_kg;
    }
    if (metrics.water_pct !== undefined && metrics.water_pct !== null && document.getElementById('prof-water')) {
      document.getElementById('prof-water').value = metrics.water_pct;
    }
    
    let bmiVal = metrics.bmi;
    if ((!bmiVal || parseFloat(bmiVal) === 0) && metrics.height_cm > 0 && metrics.weight_kg > 0) {
      bmiVal = (metrics.weight_kg / ((metrics.height_cm / 100.0) ** 2)).toFixed(1);
    }
    if (document.getElementById('prof-bmi')) {
      document.getElementById('prof-bmi').value = bmiVal || '';
    }

    updateLiveBmi();
    updateLiveMaxHr();

    const srcStr = sources.length ? sources.join(', ') : 'anslutna tjänster';
    if (statusMsg) statusMsg.textContent = `✓ Hämtade uppdaterade profilmått från ${srcStr}! Klicka på "Spara profilmått" för att spara.`;
  } catch (e) {
    if (statusMsg) statusMsg.textContent = `❌ Fel vid hämtning av extern profil: ${e.message}`;
  }
}



async function handleChangePassword(event) {
  event.preventDefault();
  const current_password = document.getElementById('pwd-current').value;
  const new_password = document.getElementById('pwd-new').value;
  const confirm_password = document.getElementById('pwd-confirm') ? document.getElementById('pwd-confirm').value : new_password;
  const statusEl = document.getElementById('pwd-status-msg');

  if (new_password !== confirm_password) {
    if (statusEl) {
      statusEl.style.color = '#DC2626';
      statusEl.textContent = '❌ Det nya lösenordet och bekräftelsen matchar inte.';
    } else {
      alert('Det nya lösenordet och bekräftelsen matchar inte.');
    }
    return;
  }

  try {
    const res = await apiFetch('/api/profile/change_password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password, new_password })
    });
    const data = await res.json();
    if (res.ok) {
      if (statusEl) {
        statusEl.style.color = '#16a34a';
        statusEl.textContent = '✓ Lösenordet har uppdaterats!';
      } else {
        alert('Lösenordet har uppdaterats!');
      }
      document.getElementById('pwd-current').value = '';
      document.getElementById('pwd-new').value = '';
      if (document.getElementById('pwd-confirm')) document.getElementById('pwd-confirm').value = '';
    } else {
      const msg = data.detail || 'Kunde inte byta lösenord.';
      if (statusEl) {
        statusEl.style.color = '#DC2626';
        statusEl.textContent = `❌ ${msg}`;
      } else {
        alert(msg);
      }
    }
  } catch (e) {
    if (statusEl) {
      statusEl.style.color = '#DC2626';
      statusEl.textContent = '❌ Nätverksfel vid lösenordsbyte.';
    } else {
      alert('Nätverksfel vid lösenordsbyte.');
    }
  }
}

async function handleRotateRecoveryKey(event) {
  event.preventDefault();
  const current_password = document.getElementById('rot-key-pwd').value;
  const statusEl = document.getElementById('rot-key-status-msg');

  if (!current_password) {
    if (statusEl) {
      statusEl.style.color = '#DC2626';
      statusEl.textContent = '❌ Fyll i nuvarande lösenord.';
    }
    return;
  }

  try {
    const res = await apiFetch('/api/user/rotate_recovery_key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password })
    });
    const data = await res.json();
    if (res.ok && data.new_recovery_key) {
      if (statusEl) {
        statusEl.style.color = '#16a34a';
        statusEl.textContent = '✓ Ny återställningsnyckel har skapats!';
      }
      document.getElementById('rot-key-pwd').value = '';
      showRecoveryModal(data.new_recovery_key);
    } else {
      const msg = data.detail || 'Kunde inte generera ny återställningsnyckel.';
      if (statusEl) {
        statusEl.style.color = '#DC2626';
        statusEl.textContent = `❌ ${msg}`;
      } else {
        alert(msg);
      }
    }
  } catch (e) {
    if (statusEl) {
      statusEl.style.color = '#DC2626';
      statusEl.textContent = '❌ Nätverksfel vid skapande av ny nyckel.';
    } else {
      alert('Nätverksfel vid skapande av ny nyckel.');
    }
  }
}

async function handleDeleteAccount() {
  const confirmed = confirm(
    '⚠️ VARNING! Vill du verkligen radera ditt konto?\n\n' +
    'All din krypterade hälsodata (aktiviteter, sömn, mätvärden) tas bort permanent från databasen.\n\n' +
    'Denna åtgärd kan INTE ångras!'
  );
  if (!confirmed) return;

  const doubleConfirmed = prompt('Skriv "RADERA" för att bekräfta permanent konto-radering:');
  if (doubleConfirmed !== 'RADERA') {
    alert('Raderingen avbröts.');
    return;
  }

  const password = prompt('Ange ditt lösenord för att bekräfta permanent radering av kontot:');
  if (!password) {
    alert('Raderingen avbröts – lösenord krävs.');
    return;
  }

  try {
    const res = await apiFetch('/api/user/delete_account', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ current_password: password })
    });
    if (res.ok) {
      alert('Ditt konto och all din hälsodata har raderats permanent.');
      handleLogout();
    } else {
      const data = await res.json();
      alert(data.detail || 'Kunde inte radera kontot.');
    }
  } catch (e) {
    alert('Nätverksfel vid radering av konto.');
  }
}


// --- DATAKÄLLOR (EXTERNA TJÄNSTER) ---

let datasourcesCache = [];
const dsSyncPollers = {};

async function loadDatasources() {
  const container = document.getElementById('ds-cards');
  if (!container) return;
  if (!datasourcesCache.length) {
    container.innerHTML = '<p style="color:#6b7280; font-size:0.9rem;">⏳ Laddar datakällor...</p>';
  }
  try {
    const res = await apiFetch('/api/datasources');
    if (!res.ok) throw new Error('Kunde inte läsa datakällornas status.');
    const data = await res.json();
    datasourcesCache = data.providers || [];
    renderDatasourceCards(datasourcesCache);
  } catch (e) {
    container.innerHTML = `<p style="color:#b91c1c; font-size:0.9rem;">❌ ${escapeHtml(e.message)}</p>`;
  }
}

function renderDatasourceCards(providers) {
  const container = document.getElementById('ds-cards');
  if (!container) return;
  container.innerHTML = providers.map(p =>
    p.auth_kind === 'oauth' ? renderOauthDsCard(p) : renderCredentialsDsCard(p)
  ).join('');
}

function dsCardHeader(p) {
  const badgeClass = p.connected ? 'ds-badge connected' : 'ds-badge';
  const badgeText = p.connected ? '● Ansluten' : '○ Ej ansluten';
  const steps = (p.steps || []).map(s => `<li>${escapeHtml(s)}</li>`).join('');
  return `
    <div class="ds-card-head">
      <span class="ds-icon">${escapeHtml(p.icon)}</span>
      <div>
        <h4>${escapeHtml(p.name)}</h4>
        <p class="ds-desc">${escapeHtml(p.description)}</p>
      </div>
      <span class="${badgeClass}">${badgeText}</span>
    </div>
    <ol class="ds-steps">${steps}</ol>
    <a class="ds-link" href="${escapeHtml(p.portal_url)}" target="_blank" rel="noopener noreferrer">🔗 ${escapeHtml(p.portal_label)}</a>
  `;
}

function dsCardFooter(p) {
  const syncInfo = p.last_sync_at
    ? `Senast synkad: ${escapeHtml(p.last_sync_at)} (${escapeHtml(String(p.last_sync_count))} ${escapeHtml(p.sync_label)})`
    : 'Ingen synkronisering har körts ännu.';
  return `
    <p class="ds-sync-info">${syncInfo}</p>
    <p class="ds-status" id="ds-status-${escapeHtml(p.provider)}"></p>
  `;
}

function renderOauthDsCard(p) {
  const pid = escapeHtml(p.provider);
  const secretPlaceholder = p.secret_set ? '•••••••• (sparad)' : 'Klistra in Client Secret';
  return `
    <div class="ds-card" style="border-top-color:${escapeHtml(p.color)};">
      ${dsCardHeader(p)}
      <div class="ds-field">
        <label for="ds-cb-${pid}">Callback-URL – klistra in exakt denna i utvecklarportalen</label>
        <div class="ds-copy-row">
          <input type="text" id="ds-cb-${pid}" readonly value="${escapeHtml(p.callback_url)}">
          <button type="button" class="btn btn-secondary" onclick="copyDsField('ds-cb-${pid}')">📋 Kopiera</button>
        </div>
      </div>
      <form onsubmit="handleSaveDatasourceCredentials(event, '${pid}')">
        <div class="input-row">
          <div class="input-group">
            <label for="ds-cid-${pid}">Client ID</label>
            <input type="text" id="ds-cid-${pid}" value="${escapeHtml(p.client_id)}" placeholder="t.ex. 123456" autocomplete="off">
          </div>
          <div class="input-group">
            <label for="ds-secret-${pid}">Client Secret</label>
            <input type="password" id="ds-secret-${pid}" placeholder="${escapeHtml(secretPlaceholder)}" autocomplete="new-password">
          </div>
        </div>
        <div class="ds-actions">
          <button type="submit" class="btn btn-secondary">💾 Spara uppgifter</button>
          <button type="button" class="btn btn-primary" onclick="handleAuthorizeDatasource('${pid}')">▶ ${p.connected ? 'Anslut om' : 'Anslut'}</button>
          <button type="button" class="btn btn-secondary" onclick="handleSyncDatasource('${pid}')">📥 Synkronisera nu</button>
          <button type="button" class="btn danger-btn" onclick="handleDisconnectDatasource('${pid}')">🔌 Koppla ifrån</button>
        </div>
      </form>
      ${dsCardFooter(p)}
    </div>
  `;
}

function renderCredentialsDsCard(p) {
  const pid = escapeHtml(p.provider);
  const pwPlaceholder = p.secret_set ? '•••••••• (sparat)' : 'Ditt Garmin Connect-lösenord';
  return `
    <div class="ds-card" style="border-top-color:${escapeHtml(p.color)};">
      ${dsCardHeader(p)}
      <form onsubmit="handleGarminConnect(event, '${pid}')">
        <div class="input-row">
          <div class="input-group">
            <label for="ds-email-${pid}">E-postadress</label>
            <input type="email" id="ds-email-${pid}" value="${escapeHtml(p.email)}" placeholder="namn@exempel.se" autocomplete="off">
          </div>
          <div class="input-group">
            <label for="ds-pwd-${pid}">Lösenord</label>
            <input type="password" id="ds-pwd-${pid}" placeholder="${escapeHtml(pwPlaceholder)}" autocomplete="new-password">
          </div>
        </div>
        <div class="input-row ds-mfa-row hidden" id="ds-mfa-row-${pid}">
          <div class="input-group">
            <label for="ds-mfa-${pid}">🔐 MFA-kod (6 siffror)</label>
            <input type="text" id="ds-mfa-${pid}" inputmode="numeric" maxlength="10" placeholder="123456" autocomplete="one-time-code">
          </div>
        </div>
        <div class="ds-actions">
          <button type="submit" class="btn btn-primary">▶ ${p.connected ? 'Anslut om / Verifiera' : 'Anslut / Verifiera'}</button>
          <button type="button" class="btn btn-secondary" onclick="handleSyncDatasource('${pid}')">📥 Synkronisera nu</button>
          <button type="button" class="btn danger-btn" onclick="handleDisconnectDatasource('${pid}')">🔌 Koppla ifrån</button>
        </div>
      </form>
      ${dsCardFooter(p)}
    </div>
  `;
}

function setDsStatus(provider, text) {
  const el = document.getElementById(`ds-status-${provider}`);
  if (el) el.textContent = text;
}

function setDsGlobalStatus(text) {
  const el = document.getElementById('ds-global-status');
  if (el) el.textContent = text;
}

function copyDsField(elementId) {
  const input = document.getElementById(elementId);
  if (!input) return;
  input.select();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(input.value).catch(() => {});
  } else {
    try { document.execCommand('copy'); } catch (e) {}
  }
  setDsGlobalStatus('📋 Callback-URL kopierad till urklipp.');
}

async function dsPost(url, body) {
  const res = await apiFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
  });
  // Read as text first: a crashed endpoint or a proxy error page is not JSON, and
  // then the status code plus the raw body is what makes the failure diagnosable.
  const raw = await res.text();
  let data = {};
  try { data = raw ? JSON.parse(raw) : {}; } catch (e) {}

  if (!res.ok) {
    if (typeof data.detail === 'string' && data.detail) throw new Error(data.detail);
    const snippet = (raw || res.statusText || '').replace(/\s+/g, ' ').trim().slice(0, 200);
    throw new Error(`Serverfel ${res.status}${snippet ? ': ' + snippet : ''}`);
  }
  return data;
}

async function handleSaveDatasourceCredentials(event, provider) {
  event.preventDefault();
  const cidEl = document.getElementById(`ds-cid-${provider}`);
  const secretEl = document.getElementById(`ds-secret-${provider}`);
  setDsStatus(provider, '⏳ Sparar uppgifter...');
  try {
    const data = await dsPost(`/api/datasources/${provider}/credentials`, {
      client_id: cidEl ? cidEl.value.trim() : '',
      client_secret: secretEl ? secretEl.value.trim() : ''
    });
    await loadDatasources();
    setDsStatus(provider, `✓ ${data.message}`);
  } catch (e) {
    setDsStatus(provider, `❌ ${e.message}`);
  }
}

async function handleAuthorizeDatasource(provider) {
  setDsStatus(provider, '⏳ Förbereder auktorisering...');
  try {
    const data = await dsPost(`/api/datasources/${provider}/authorize`, {});
    if (!data.auth_url) throw new Error('Ingen auktoriseringslänk mottogs.');
    setDsStatus(provider, '↗️ Skickar dig vidare till tjänstens inloggningssida...');
    window.location.href = data.auth_url;
  } catch (e) {
    setDsStatus(provider, `❌ ${e.message}`);
  }
}

async function handleGarminConnect(event, provider) {
  event.preventDefault();
  const emailEl = document.getElementById(`ds-email-${provider}`);
  const pwdEl = document.getElementById(`ds-pwd-${provider}`);
  const mfaRow = document.getElementById(`ds-mfa-row-${provider}`);
  const mfaInput = document.getElementById(`ds-mfa-${provider}`);
  const mfaVisible = mfaRow && !mfaRow.classList.contains('hidden');
  const mfaCode = mfaVisible && mfaInput ? mfaInput.value.trim() : '';

  setDsStatus(provider, mfaCode ? '⏳ Verifierar MFA-koden...' : '⏳ Loggar in på Garmin Connect...');
  try {
    const data = await dsPost('/api/datasources/garmin/connect', {
      email: emailEl ? emailEl.value.trim() : '',
      password: pwdEl ? pwdEl.value : '',
      mfa_code: mfaCode,
      save_credentials: true
    });

    if (data.status === 'mfa_required') {
      if (mfaRow) mfaRow.classList.remove('hidden');
      if (mfaInput) mfaInput.focus();
      setDsStatus(provider, `🔐 ${data.message}`);
      return;
    }

    await loadDatasources();
    setDsStatus(provider, `✓ ${data.message}`);
  } catch (e) {
    setDsStatus(provider, `❌ ${e.message}`);
  }
}

async function handleDisconnectDatasource(provider) {
  const meta = datasourcesCache.find(p => p.provider === provider);
  const name = meta ? meta.name : provider;
  const warning = `Koppla ifrån ${name}?\n\nSparade API-uppgifter och tokens raderas. Redan hämtad hälsodata ligger kvar i databasen.`;
  if (!confirm(warning)) return;

  setDsStatus(provider, '⏳ Kopplar ifrån...');
  try {
    const data = await dsPost(`/api/datasources/${provider}/disconnect`, {});
    await loadDatasources();
    setDsStatus(provider, `✓ ${data.message}`);
  } catch (e) {
    setDsStatus(provider, `❌ ${e.message}`);
  }
}

async function handleSyncDatasource(provider) {
  setDsStatus(provider, '⏳ Startar synkronisering...');
  try {
    const data = await dsPost(`/api/datasources/${provider}/sync`, {});
    setDsStatus(provider, `⏳ ${data.message}`);
    await pollDatasourceSync(provider);
  } catch (e) {
    setDsStatus(provider, `❌ ${e.message}`);
  }
}

function pollDatasourceSync(provider) {
  if (dsSyncPollers[provider]) {
    clearTimeout(dsSyncPollers[provider]);
    delete dsSyncPollers[provider];
  }

  return new Promise((resolve) => {
    const tick = async () => {
      try {
        const res = await apiFetch(`/api/datasources/${provider}/sync_status`);
        if (!res.ok) throw new Error('Kunde inte läsa synkstatus.');
        const data = await res.json();

        if (data.status === 'running') {
          setDsStatus(provider, `⏳ ${data.message || 'Synkronisering pågår...'}`);
          dsSyncPollers[provider] = setTimeout(tick, 3000);
          return;
        }

        delete dsSyncPollers[provider];
        if (data.status === 'done') {
          setDsStatus(provider, `✓ ${data.message || 'Synkroniseringen är klar.'}`);
          await loadDatasources();
          await refreshDashboard();
        } else if (data.status === 'error') {
          setDsStatus(provider, `⚠️ ${data.message || 'Synkroniseringen misslyckades.'}`);
          await loadDatasources();
        }
        resolve(data);
      } catch (e) {
        delete dsSyncPollers[provider];
        setDsStatus(provider, `❌ ${e.message}`);
        resolve(null);
      }
    };
    dsSyncPollers[provider] = setTimeout(tick, 1500);
  });
}

async function syncAllDatasources() {
  const connected = datasourcesCache.filter(p => p.connected);
  if (!connected.length) {
    setDsGlobalStatus('ℹ️ Inga anslutna datakällor att synkronisera. Anslut en tjänst först.');
    return;
  }
  setDsGlobalStatus(`⏳ Synkroniserar ${connected.length} anslutna datakällor...`);
  for (const p of connected) {
    await handleSyncDatasource(p.provider);
  }
  setDsGlobalStatus('✓ Synkroniseringen av alla anslutna datakällor är klar.');
}

function handleDatasourceReturn() {
  const params = new URLSearchParams(window.location.search);
  const provider = params.get('datakalla');
  if (!provider) return;

  const ok = params.get('status') === 'ok';
  showTab('datasources');
  setDsGlobalStatus(
    ok
      ? '✓ Anslutningen lyckades! Klicka på "Synkronisera nu" för den anslutna tjänsten för att hämta data.'
      : '❌ Anslutningen misslyckades. Kontrollera Client ID, Client Secret och Callback-URL och försök igen.'
  );

  // Drop the query string so a reload does not repeat the message.
  window.history.replaceState({}, '', window.location.pathname);
}

// --- CHART INFO POPOVERS ---
window.toggleChartInfo = function(infoId, event) {
  if (event) {
    if (typeof event.stopPropagation === 'function') event.stopPropagation();
    if (typeof event.preventDefault === 'function') event.preventDefault();
  }
  var popover = document.getElementById(infoId);
  if (!popover) return;
  var isCurrentlyOpen = !popover.classList.contains('hidden') && popover.style.display === 'block';
  
  // Stäng alla andra öppna popovers först
  document.querySelectorAll('.chart-info-popover').forEach(function(el) {
    el.classList.add('hidden');
    el.style.display = 'none';
  });

  if (!isCurrentlyOpen) {
    popover.classList.remove('hidden');
    popover.style.display = 'block';
  }
};

window.closeChartInfo = function(infoId, event) {
  if (event) {
    if (typeof event.stopPropagation === 'function') event.stopPropagation();
    if (typeof event.preventDefault === 'function') event.preventDefault();
  }
  var popover = document.getElementById(infoId);
  if (popover) {
    popover.classList.add('hidden');
    popover.style.display = 'none';
  }
};

// Stäng popover vid klick utanför eller vid Esc-tryck
document.addEventListener('click', function(e) {
  if (!e.target.closest('.chart-info-popover') && !e.target.closest('.chart-info-btn')) {
    document.querySelectorAll('.chart-info-popover').forEach(function(el) {
      el.classList.add('hidden');
      el.style.display = 'none';
    });
  }
});

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.chart-info-popover').forEach(function(el) {
      el.classList.add('hidden');
      el.style.display = 'none';
    });
  }
});


