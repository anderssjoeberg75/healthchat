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

// --- AUTHENTICATION ---

async function checkSession() {
  try {
    const res = await fetch('/api/auth/me');
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
    const p = currentUser.profile || {};
    if (p.sex) document.getElementById('prof-sex').value = p.sex;
    if (p.age) document.getElementById('prof-age').value = p.age;
    if (p.height_cm) document.getElementById('prof-height').value = p.height_cm;
    if (p.weight_kg) document.getElementById('prof-weight').value = p.weight_kg;
  }

  refreshDashboard();
  initRestoredFeatures();
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
    const data = await res.json();
    if (res.ok) {
      currentUser = data;
      onAuthSuccess();
    } else {
      errDiv.innerText = data.detail || 'Inloggningen misslyckades.';
      errDiv.classList.remove('hidden');
    }
  } catch (err) {
    errDiv.innerText = 'Nätverksfel vid inloggning.';
    errDiv.classList.remove('hidden');
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
    errDiv.classList.remove('hidden');
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
  await fetch('/api/auth/logout', { method: 'POST' });
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
  } else if (tabId === 'sources') {
    refreshConnectionStatus();
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

async function refreshDashboard() {
  try {
    const res = await fetch(`/api/dashboard/summary?days=${currentDaysRange}`);
    if (!res.ok) return;
    cachedSummary = await res.json();
    
    updateDashboardCards(cachedSummary);
    renderActivitiesTable(cachedSummary.history.activities || []);
    
    try {
      if (currentTab === 'training') {
        renderTrainingCharts();
      } else {
        renderHealthCharts();
      }
    } catch (chartErr) {
      // Cards and tables are already updated; a chart failure must not undo that.
      console.error('Error rendering charts:', chartErr);
    }
  } catch (err) {
    console.error('Error refreshing dashboard:', err);
  }
}

function floatVal(v, defaultVal = 0.0) {
  const parsed = parseFloat(v);
  return isNaN(parsed) ? defaultVal : parsed;
}

function formatNumber(num) {
  return Math.round(num).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function getRecoveryAiAdvice(recVal) {
  if (recVal >= 80) {
    return "🤖 AI-Analys: Återhämtning " + recVal + "% – Kroppen är i toppform och redo för högre ansträngning!\n" +
      "🎯 Rekommenderad träning: Högintensivt kvalitetspass (intervaller, tröskel/tempo eller snabbdistans).\n" +
      "❤️ Pulsnivå: Sikta på Zon 3–4 (140–170 bpm) med möjliga toppar i Zon 5.\n" +
      "🏃 Träningsfokus: Utnyttja höga energidepåer för maximal träningseffekt och utveckling.\n" +
      "💡 Tips: Värm upp grundligt i Zon 1 (10–15 min) och prioritera god återhämtning efteråt.";
  } else if (recVal >= 60) {
    return "🤖 AI-Analys: Återhämtning " + recVal + "% – God energibalans och fin form för träning idag.\n" +
      "🎯 Rekommenderad träning: Aerobt distanspass, basbygge eller medeltung styrketräning.\n" +
      "❤️ Pulsnivå: Håll pulsen i Zon 2 (125–140 bpm) eller kring din MAF-puls (140 bpm).\n" +
      "🏃 Träningsfokus: Utveckla den aeroba uthålligheten och fettförbränningen utan mjölksyra.\n" +
      "💡 Tips: Håll ett stabilt och kontrollerat tempo – undvik onödiga pulstoppar.";
  } else if (recVal >= 40) {
    return "🤖 AI-Analys: Återhämtning " + recVal + "% – Måttlig återhämtning med viss kvarvarande trötthet.\n" +
      "🎯 Rekommenderad träning: Lätt återhämtningspass, lugn aerob cykling/löpning eller rörlighet.\n" +
      "❤️ Pulsnivå: Håll pulsen i Zon 1–2 (110–135 bpm), max 140 bpm.\n" +
      "🏃 Träningsfokus: Öka blodcirkulationen för att påskynda återhämtningen utan överbelastning.\n" +
      "💡 Tips: Undvik tunga lyft och tuffa intervaller i Zon 4–5 (>155 bpm) idag.";
  } else {
    return "🤖 AI-Analys: Återhämtning " + recVal + "% – Låga energireserver, kroppen behöver återhämta sig.\n" +
      "🎯 Rekommenderad träning: Aktiv vila, lugn promenad, rörlighet eller helt träningsfri dag.\n" +
      "❤️ Pulsnivå: Undvik ansträngning, håll pulsen mycket låg i Zon 1 (<120 bpm).\n" +
      "🏃 Träningsfokus: Prioritera god sömn, hydrering och näring för att ladda om batterierna.\n" +
      "💡 Tips: Hård träning idag ökar risken för överträning och skador – prioritera vila.";
  }
}

function setText(id, text, color) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerText = text;
  if (color) el.style.color = color;
}

function updateDashboardCards(data) {
  const days = currentDaysRange;
  const daysLabel = days < 365 ? `${days} d` : (days > 365 ? 'alla d' : '1 år');
  const NO_DATA = '—';

  // 1. Recovery score, from the latest Body Battery reading.
  const bb = data.bb_latest || {};
  const recVal = Number(bb.highest) || 0;
  if (recVal > 0) {
    const recColor = recVal >= 75 ? '#10B981' : (recVal >= 45 ? '#F59E0B' : '#EF4444');
    setText('val-bb-level', `${recVal}%`, recColor);
    setText('val-recovery-status', recVal >= 80 ? 'Fullt återhämtad och redo för topprestation!'
      : (recVal >= 60 ? 'Återhämtad och redo för dagen!'
      : (recVal >= 40 ? 'Måttlig återhämtning – anpassa träningsintensiteten'
      : 'Låg återhämtning – prioritera vila och återhämtning')));
    const aiBoxEl = document.getElementById('val-recovery-ai-box');
    if (aiBoxEl) aiBoxEl.innerText = getRecoveryAiAdvice(recVal);
  } else {
    setText('val-bb-level', NO_DATA, '#9CA3AF');
    setText('val-recovery-status', 'Ingen Body Battery-data — kör en Check-in.');
    const aiBoxEl = document.getElementById('val-recovery-ai-box');
    if (aiBoxEl) aiBoxEl.innerText = '';
  }

  // 2. Weight and body composition, from the latest measurement.
  const bodyComp = data.latest_body_comp || {};
  const historyBodyComp = (data.history && data.history.body_composition) || [];
  const wKg = floatVal(bodyComp.weight_kg, 0);

  if (wKg > 0) {
    setText('val-weight-kg', `${wKg.toFixed(1)} kg`, '');

    if (historyBodyComp.length >= 2) {
      const firstW = floatVal(historyBodyComp[0].weight_kg, wKg);
      const diffKg = wKg - firstW;
      const diffPct = firstW > 0 ? (diffKg / firstW * 100.0) : 0.0;
      const icon = diffKg < 0 ? '📉' : (diffKg > 0 ? '📈' : '➡️');
      setText('val-weight-trend',
        `${icon} ${diffKg >= 0 ? '+' : ''}${diffKg.toFixed(1)} kg (${diffPct >= 0 ? '+' : ''}${diffPct.toFixed(1)}%) under ${daysLabel}`,
        diffKg <= 0 ? '#10B981' : '#EF4444');
    } else {
      // One measurement says nothing about a trend.
      setText('val-weight-trend', `Bara en mätning under ${daysLabel} — ingen trend att visa än.`, '#9CA3AF');
    }

    const heightCm = floatVal((data.profile || {}).height_cm, 0);
    setText('val-bmi-text', heightCm > 0
      ? `BMI: ${(wKg / ((heightCm / 100.0) ** 2)).toFixed(1)}`
      : 'BMI: ange din längd under Profil & Konto');

    const fatPct = floatVal(bodyComp.fat_ratio_pct, 0);
    const muscleKg = floatVal(bodyComp.muscle_mass_kg, 0);
    setText('val-fat-pct', (fatPct > 0 || muscleKg > 0)
      ? `Fett: ${fatPct.toFixed(1)}% | Muskelmassa: ${muscleKg.toFixed(1)} kg`
      : 'Ingen kroppssammansättning registrerad');
    setText('val-weight-source', `Källa: ${bodyComp.source || 'Withings'} (${bodyComp.date || data.today_date || ''})`);
  } else {
    setText('val-weight-kg', NO_DATA, '#9CA3AF');
    setText('val-weight-trend', 'Ingen vikt registrerad — anslut Withings eller Fitbit.', '#9CA3AF');
    setText('val-bmi-text', '');
    setText('val-fat-pct', '');
    setText('val-weight-source', '');
  }

  // 3. Today's calorie burn.
  const burn = data.calorie_burn_today || {};
  const totalBurn = Number(burn.total_burn) || 0;
  if (totalBurn > 0) {
    setText('val-calories-total', `${formatNumber(totalBurn)} kcal`, '');
    let breakdown = `Vila: ${formatNumber(burn.resting_burn || 0)} kcal`
      + ` | Vardagssteg: ${formatNumber(burn.steps_burn || 0)} kcal`
      + ` | Träning: ${formatNumber(burn.workout_burn || 0)} kcal`;
    if (Number(burn.workout_steps) > 0) {
      breakdown += ` (avdrag ${formatNumber(burn.workout_steps)} träningssteg)`;
    }
    setText('val-calories-breakdown', breakdown);
    const bmrSourceMap = { device: 'Garmins BMR', mifflin: 'Mifflin-St Jeor', simple: 'Viktbaserad BMR' };
    setText('val-calories-source', `Källa: ${bmrSourceMap[burn.bmr_source] || 'Uppskattad BMR'}`);
  } else {
    setText('val-calories-total', NO_DATA, '#9CA3AF');
    setText('val-calories-breakdown', 'Synka Garmin och fyll i din profil för en uppskattning.');
    setText('val-calories-source', '');
  }
}

function renderActivitiesTable(activities) {
  const tbody = document.getElementById('activities-table-body');
  if (!activities || activities.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Inga träningspass registrerade i detta intervall.</td></tr>';
    return;
  }

  tbody.innerHTML = activities.map(act => `
    <tr>
      <td>${act.date || (act.start_time ? act.start_time.slice(0, 10) : '--')}</td>
      <td><strong>${act.activity_name || act.activity_type || 'Träning'}</strong></td>
      <td>${act.distance_km ? act.distance_km.toFixed(2) + ' km' : '--'}</td>
      <td>${act.duration_min ? act.duration_min.toFixed(0) + ' min' : '--'}</td>
      <td>${act.avg_hr ? act.avg_hr + ' bpm' : '--'}</td>
      <td>${act.calories ? act.calories + ' kcal' : '--'}</td>
      <td><span class="badge-v">${act.source || 'Garmin'}</span></td>
    </tr>
  `).join('');
}


// --- DYNAMIC DEMO DATA GENERATOR FOR RANGE SWITCHING ---

// --- CHART SERIES -----------------------------------------------------------
//
// Every chart plots the rows it actually has, with its own dates on the x-axis.
// A series with no data renders empty: showing a generated curve would be
// presenting invented health data as if it were measured.

function seriesFrom(rows, valueKey, { dateKey = 'date' } = {}) {
  if (!Array.isArray(rows) || rows.length === 0) return { labels: [], values: [] };

  const sorted = [...rows]
    .filter((row) => row && (row[dateKey] || row.start_time))
    .sort((a, b) => String(a[dateKey] || a.start_time).localeCompare(String(b[dateKey] || b.start_time)));

  const years = new Set(sorted.map((row) => String(row[dateKey] || row.start_time).slice(0, 4)));
  const useYear = years.size > 1;

  const labels = [];
  const values = [];
  sorted.forEach((row) => {
    const raw = String(row[dateKey] || row.start_time || '').slice(0, 10);
    if (raw.length < 10) return;
    labels.push(useYear ? raw.slice(2) : raw.slice(5));
    const value = typeof valueKey === 'function' ? valueKey(row) : row[valueKey];
    values.push(value === null || value === undefined ? null : Number(value));
  });
  return { labels, values };
}

function hasValues(series) {
  return series.values.some((v) => v !== null && !Number.isNaN(v) && v !== 0);
}

function emptyChart(canvasId, label) {
  createChart(canvasId, 'line', { labels: [], datasets: [{ label, data: [] }] });
}


// --- 8 COROS-INSPIRED CHARTS (CHART.JS) ---

function renderHealthCharts() {
  if (!cachedSummary) return;
  const history = cachedSummary.history || {};

  // 1. Weight
  const weight = seriesFrom(history.body_composition, 'weight_kg');
  createChart('chart-weight', 'line', {
    labels: weight.labels,
    datasets: [{ label: 'Vikt (kg)', data: weight.values, borderColor: '#0078D4', backgroundColor: 'rgba(0,120,212,0.1)', tension: 0.3, fill: true }]
  });

  // 2. Calorie burn, stacked: resting + everyday steps + workouts
  const cals = history.calorie_burn || [];
  const resting = seriesFrom(cals, 'resting_burn');
  const steps = seriesFrom(cals, 'steps_burn');
  const workout = seriesFrom(cals, 'workout_burn');
  createChart('chart-calories', 'bar', {
    labels: resting.labels,
    datasets: [
      { label: 'Vilo-BMR', data: resting.values, backgroundColor: '#F59E0B' },
      { label: 'Vardagssteg', data: steps.values, backgroundColor: '#0284C7' },
      { label: 'Träning', data: workout.values, backgroundColor: '#DC2626' }
    ]
  }, { stacked: true });

  // 3. Resting heart rate
  const rhrRows = (history.daily_summary || []).filter((d) => Number(d.resting_hr) > 0);
  const rhr = seriesFrom(rhrRows, 'resting_hr');
  createChart('chart-rhr', 'line', {
    labels: rhr.labels,
    datasets: [{ label: 'Vilo-puls (bpm)', data: rhr.values, borderColor: '#0284C7', tension: 0.3 }]
  });

  // 4. HRV
  const hrv = seriesFrom(history.hrv, (row) => row.last_night_avg || row.weekly_avg || 0);
  createChart('chart-hrv', 'line', {
    labels: hrv.labels,
    datasets: [{ label: 'Nattlig HRV (ms)', data: hrv.values, borderColor: '#EC4899', tension: 0.3 }]
  });

  // 5. Sleep duration
  const sleep = seriesFrom(history.sleep, 'total_sleep_hours');
  createChart('chart-sleep', 'bar', {
    labels: sleep.labels,
    datasets: [{ label: 'Sömntid (timmar)', data: sleep.values, backgroundColor: '#8B5CF6' }]
  });

  // 6. Sleep score
  const sleepScore = seriesFrom(history.sleep, 'sleep_score');
  createChart('chart-sleep-score', 'line', {
    labels: sleepScore.labels,
    datasets: [{ label: 'Sömnkvalitet (0-100)', data: sleepScore.values, borderColor: '#10B981', tension: 0.3 }]
  });

  // 7. Body Battery
  const bb = seriesFrom(history.body_battery, 'highest');
  createChart('chart-bb', 'line', {
    labels: bb.labels,
    datasets: [{ label: 'Max Body Battery', data: bb.values, borderColor: '#8B5CF6', tension: 0.3 }]
  });

  // 8. Stress
  const stress = seriesFrom(history.stress, 'average');
  createChart('chart-stress', 'line', {
    labels: stress.labels,
    datasets: [{ label: 'Snittstress', data: stress.values, borderColor: '#F59E0B', tension: 0.3 }]
  });
}

function renderTrainingCharts() {
  const history = (cachedSummary && cachedSummary.history) || {};
  const activities = history.activities || [];

  // Training volume per day, from the logged sessions.
  const byDay = new Map();
  activities.forEach((act) => {
    const date = String(act.date || act.start_time || '').slice(0, 10);
    if (!date) return;
    byDay.set(date, (byDay.get(date) || 0) + (Number(act.duration_min) || 0) / 60);
  });
  const volumeRows = [...byDay.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([date, hours]) => ({ date, hours: Number(hours.toFixed(2)) }));
  const volume = seriesFrom(volumeRows, 'hours');

  createChart('chart-training-volume', 'bar', {
    labels: volume.labels,
    datasets: [{ label: 'Träningsvolym (timmar)', data: volume.values, backgroundColor: '#0284C7' }]
  });

  renderHrZonesChart();
}

async function renderHrZonesChart() {
  // Zone boundaries come from the user's own age, resting HR and max HR.
  let zones = null;
  try {
    const res = await fetch('/api/hr-zones');
    if (res.ok) zones = (await res.json()).zones;
  } catch (err) {
    zones = null;
  }

  const list = (zones && (zones.zones || zones)) || [];
  if (!Array.isArray(list) || list.length === 0) {
    emptyChart('chart-hr-zones', 'Pulszoner');
    return;
  }

  // Each bar spans the zone's bpm range, so the chart reads as a zone ladder.
  createChart('chart-hr-zones', 'bar', {
    labels: list.map((z) => `${z.name} — ${z.title}`),
    datasets: [{
      label: 'Pulsintervall (bpm)',
      data: list.map((z) => [Number(z.bpm_low) || 0, Number(z.bpm_high) || 0]),
      backgroundColor: list.map((z) => z.color || '#0284C7')
    }]
  }, { indexAxis: 'y' });
}

function createChart(canvasId, type, data, options = {}) {
  const canvasEl = document.getElementById(canvasId);
  if (!canvasEl) return;

  // Chart.js comes from a CDN. If it could not load, say so in place of the
  // chart instead of throwing — an uncaught error here aborted the whole
  // dashboard refresh, taking the cards and tables down with it.
  if (typeof Chart === 'undefined') {
    const wrapper = canvasEl.parentElement;
    if (wrapper && !wrapper.querySelector('.chart-unavailable')) {
      const note = document.createElement('p');
      note.className = 'chart-unavailable summary-subtext';
      note.innerText = 'Diagrammen kunde inte laddas (Chart.js nås inte).';
      wrapper.appendChild(note);
    }
    return;
  }

  if (chartInstances[canvasId]) {
    chartInstances[canvasId].destroy();
  }
  
  const ctx = canvasEl.getContext('2d');
  const empty = !data.labels || data.labels.length === 0;

  chartInstances[canvasId] = new Chart(ctx, {
    type: type,
    data: data,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: options.indexAxis || 'x',
      scales: {
        x: { stacked: options.stacked || false, grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { color: '#6B7280' } },
        y: { stacked: options.stacked || false, grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { color: '#6B7280' } }
      },
      plugins: {
        legend: { labels: { color: '#374151', font: { family: 'Segoe UI' } } },
        // Say so when there is nothing to plot, rather than drawing empty axes.
        title: empty
          ? { display: true, text: 'Ingen data ännu — kör en Check-in', color: '#9CA3AF', font: { family: 'Segoe UI', size: 13 } }
          : { display: false }
      }
    }
  });
}


// --- STREAMING AI CHAT (SSE) ---

async function handleSendChatMessage(event) {
  event.preventDefault();
  const input = document.getElementById('chat-input-field');
  const message = input.value.trim();
  if (!message) return;

  const providerEl = document.getElementById('ai-provider-select');
  const provider = providerEl ? providerEl.value : undefined;
  input.value = '';

  appendChatMessage('user', message);
  const botBubble = appendChatMessage('bot', 'Tänker...');

  try {
    const res = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ message, provider })
    });

    if (!res.ok) {
      let detail = 'Kunde inte få svar från AI.';
      try {
        detail = (await res.json()).detail || detail;
      } catch (err) { /* non-JSON error body */ }
      botBubble.innerText = `⚠️ ${detail}`;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    botBubble.innerText = '';
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // SSE frames can split across reads, so keep the tail until it completes.
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop() || '';

      for (const frame of frames) {
        for (const line of frame.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6).trim();
          if (!payload || payload === '[DONE]') continue;
          try {
            const parsed = JSON.parse(payload);
            if (parsed.chunk) botBubble.innerText += parsed.chunk;
            if (parsed.error) botBubble.innerText = `⚠️ ${parsed.error}`;
          } catch (err) { /* partial frame */ }
        }
      }
    }

    if (!botBubble.innerText) {
      botBubble.innerText = '⚠️ Inget svar mottogs från AI-tjänsten.';
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
  const age = parseInt(document.getElementById('prof-age').value);
  const height_cm = parseFloat(document.getElementById('prof-height').value);
  const weight_kg = parseFloat(document.getElementById('prof-weight').value);

  try {
    const res = await fetch('/api/user/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sex, age, height_cm, weight_kg })
    });
    if (res.ok) {
      alert('Profilen har uppdaterats!');
      refreshDashboard();
    } else {
      alert('Kunde inte uppdatera profilen.');
    }
  } catch (e) {
    alert('Nätverksfel.');
  }
}

async function handleChangePassword(event) {
  event.preventDefault();
  const current_password = document.getElementById('pwd-current').value;
  const new_password = document.getElementById('pwd-new').value;

  try {
    const res = await fetch('/api/user/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password, new_password })
    });
    const data = await res.json();
    if (res.ok) {
      alert('Lösenordet har uppdaterats!');
      document.getElementById('pwd-current').value = '';
      document.getElementById('pwd-new').value = '';
    } else {
      alert(data.detail || 'Kunde inte byta lösenord.');
    }
  } catch (e) {
    alert('Nätverksfel.');
  }
}


// ============================================================================
// RESTORED DESKTOP FEATURES
//
// Everything below drives the endpoints that expose what the Tk build could do:
// connecting sources, check-in, settings, saved prompts, chat history, search
// and report export.
// ============================================================================

let syncPollTimer = null;
let quickQuestions = [];

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body ? { 'Content-Type': 'application/json' } : {},
    credentials: 'same-origin',
    ...options,
  });
  if (res.status === 401) {
    showAuthModal();
    throw new Error('Sessionen har gått ut.');
  }
  if (!res.ok) {
    let detail = `Fel ${res.status}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch (err) { /* non-JSON error body */ }
    throw new Error(detail);
  }
  const type = res.headers.get('content-type') || '';
  return type.includes('application/json') ? res.json() : res;
}

const apiPost = (path, body) =>
  api(path, { method: 'POST', body: body === undefined ? '{}' : JSON.stringify(body) });

// --- reusable dialog --------------------------------------------------------

function showDialog(title, bodyHtml, actions = []) {
  document.getElementById('app-modal-title').innerText = title;
  document.getElementById('app-modal-body').innerHTML = bodyHtml;

  const footer = document.getElementById('app-modal-actions');
  footer.innerHTML = '';
  actions.forEach((action, index) => {
    const btn = document.createElement('button');
    btn.className = `btn ${action.primary ? 'btn-primary' : 'btn-secondary'}`;
    btn.innerText = action.label;
    btn.onclick = () => action.onClick(closeDialog);
    btn.id = `app-modal-action-${index}`;
    footer.appendChild(btn);
  });

  document.getElementById('app-modal').classList.remove('hidden');
}

function closeDialog() {
  document.getElementById('app-modal').classList.add('hidden');
}

function notify(message, isError = false) {
  showDialog(isError ? '⚠️ Något gick fel' : 'HealthChat',
    `<p style="white-space:pre-wrap;">${escapeHtml(message)}</p>`,
    [{ label: 'OK', primary: true, onClick: (close) => close() }]);
}

function escapeHtml(text) {
  return String(text === null || text === undefined ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// --- connection status ------------------------------------------------------

async function refreshConnectionStatus() {
  let data;
  try {
    data = await api('/api/status');
  } catch (err) {
    return null;
  }

  const labels = {
    garmin: 'garmin-status',
    fitbit: 'fitbit-status',
    withings: 'withings-status',
    strava: 'strava-status',
  };
  Object.entries(labels).forEach(([source, elementId]) => {
    const el = document.getElementById(elementId);
    if (!el) return;
    const connected = data.sources && data.sources[source];
    el.innerText = connected ? '✅ Ansluten' : 'Inte ansluten';
    el.style.color = connected ? '#10B981' : '#6B7280';
  });

  const garminEl = document.getElementById('garmin-status');
  if (garminEl && data.status && data.status.text) {
    garminEl.innerText = data.status.text;
    garminEl.style.color = data.status.is_error ? '#DC2626' : (data.authenticated ? '#10B981' : '#6B7280');
  }

  const mfaRow = document.getElementById('mfa-row');
  if (mfaRow) mfaRow.classList.toggle('hidden', !data.mfa_required);

  renderSyncStatus(data.sync_status);
  return data;
}

function renderSyncStatus(sync) {
  const text = sync && sync.text ? sync.text : '';
  ['sync-status-text', 'sources-sync-text'].forEach((id) => {
    const el = document.getElementById(id);
    if (el && text) el.innerText = text;
  });

  if (sync && sync.running && !syncPollTimer) {
    syncPollTimer = setInterval(async () => {
      let data;
      try {
        data = await api('/api/sync/status');
      } catch (err) {
        return;
      }
      const current = data.sync_status || {};
      ['sync-status-text', 'sources-sync-text'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.innerText = current.text || '';
      });
      if (!current.running) {
        clearInterval(syncPollTimer);
        syncPollTimer = null;
        setCheckinBusy(false);
        await refreshDashboard();
        await refreshConnectionStatus();
      }
    }, 2000);
  }
}

function setCheckinBusy(busy) {
  const btn = document.getElementById('btn-checkin');
  if (!btn) return;
  btn.disabled = busy;
  btn.innerText = busy ? '⏳ Synkar...' : '📥 Check-in';
}

// --- check-in ---------------------------------------------------------------

async function runCheckin(full = false, source = null) {
  if (full) {
    showDialog('🔄 Synka full historik',
      '<p>Vill du hämta all tillgänglig historik från dina anslutna källor? Det kan ta flera minuter.</p>',
      [
        { label: 'Avbryt', onClick: (close) => close() },
        { label: 'Ja, synka allt', primary: true, onClick: (close) => { close(); startCheckin(true, source); } },
      ]);
    return;
  }
  startCheckin(false, source);
}

async function startCheckin(full, source) {
  setCheckinBusy(true);
  try {
    const data = await apiPost('/api/checkin', { full, source, days: currentDaysRange });
    if (data.started) {
      renderSyncStatus(data.sync_status || { text: '⏳ Synkroniserar...', running: true });
    } else {
      setCheckinBusy(false);
      if (data.reason === 'busy') notify('En synkronisering pågår redan.');
    }
  } catch (err) {
    setCheckinBusy(false);
    notify(err.message, true);
  }
}

// --- Garmin -----------------------------------------------------------------

async function connectGarmin() {
  const el = document.getElementById('garmin-status');
  if (el) { el.innerText = 'Ansluter till Garmin...'; el.style.color = '#6B7280'; }

  try {
    const data = await apiPost('/api/garmin/connect');
    await refreshConnectionStatus();
    if (data.mfa_required) {
      const input = document.getElementById('mfa-code');
      if (input) input.focus();
      notify('Garmin kräver en 6-siffrig MFA-kod. Fyll i den under Källor & Synk.');
    } else if (data.authenticated) {
      notify('✅ Ansluten till Garmin Connect!');
    }
  } catch (err) {
    await refreshConnectionStatus();
    notify(err.message, true);
  }
}

async function submitMfa() {
  const input = document.getElementById('mfa-code');
  const code = (input && input.value || '').trim();
  if (code.length !== 6) {
    notify('Ange en giltig 6-siffrig MFA-kod.', true);
    return;
  }
  try {
    await apiPost('/api/garmin/mfa', { code });
    if (input) input.value = '';
    await refreshConnectionStatus();
    notify('✅ Ansluten till Garmin Connect!');
  } catch (err) {
    notify(err.message, true);
  }
}

// --- Fitbit / Strava / Withings --------------------------------------------

async function connectSource(service) {
  try {
    const data = await api(`/api/connect/${service}/url`);
    window.open(data.url, '_blank', 'noopener');
    notify(`Öppnar inloggningen för ${service} i en ny flik.\n\n`
      + '1. Logga in och godkänn behörigheterna.\n'
      + '2. Anslutningen slutförs automatiskt när du kommer tillbaka.\n\n'
      + `Redirect-URL att registrera hos ${service}: ${data.redirect_uri}`);
  } catch (err) {
    notify(err.message, true);
  }
}

function importFile(source) {
  const input = document.getElementById('import-file-input');
  input.value = '';
  input.onchange = async () => {
    if (!input.files.length) return;
    const form = new FormData();
    form.append('file', input.files[0]);
    try {
      const res = await fetch(`/api/import/${source}`, { method: 'POST', credentials: 'same-origin', body: form });
      if (!res.ok) throw new Error((await res.json()).detail || 'Importen misslyckades');
      const data = await res.json();
      notify(`✅ Import klar: ${JSON.stringify(data.result)}`);
      await refreshDashboard();
    } catch (err) {
      notify(err.message, true);
    }
  };
  input.click();
}

// --- settings ---------------------------------------------------------------

const PROVIDER_FIELDS = {
  xai: [['xai_api_key', 'xAI API-nyckel', 'password'], ['xai_model', 'Modell', 'model']],
  openai: [['openai_api_key', 'OpenAI API-nyckel', 'password'], ['openai_model', 'Modell', 'model']],
  azure: [
    ['azure_api_key', 'Azure API-nyckel', 'password'],
    ['azure_endpoint', 'Azure endpoint', 'text'],
    ['azure_deployment', 'Deployment-namn', 'text'],
  ],
  gemini: [['gemini_api_key', 'Google API-nyckel', 'password'], ['gemini_model', 'Modell', 'model']],
  anthropic: [['anthropic_api_key', 'Anthropic API-nyckel', 'password'], ['anthropic_model', 'Modell', 'model']],
  ollama: [['ollama_base_url', 'Ollama server-URL', 'text'], ['ollama_model', 'Modell', 'model']],
};

let settingsCache = null;

async function openSettings() {
  try {
    settingsCache = await api('/api/settings');
  } catch (err) {
    notify(err.message, true);
    return;
  }

  showDialog('⚙️ Inställningar', settingsHtml(settingsCache), [
    { label: 'Stäng', onClick: (close) => close() },
    { label: '💾 Spara', primary: true, onClick: async (close) => { if (await saveSettings()) close(); } },
  ]);
  renderProviderFields();
}

function settingsHtml(data) {
  const cfg = data.config || {};
  const providers = data.providers || {};
  const providerOptions = Object.entries(providers)
    .map(([key, meta]) => `<option value="${key}" ${key === cfg.ai_provider ? 'selected' : ''}>${escapeHtml(meta.name || key)}</option>`)
    .join('');

  const sourceRows = ['fitbit', 'strava', 'withings'].map((service) => {
    const connected = (data.sources || {})[service];
    const secretSet = (cfg.secrets_set || {})[`${service}_client_secret`];
    return `
      <div class="input-row">
        <div class="input-group">
          <label for="set-${service}_client_id">${service.charAt(0).toUpperCase() + service.slice(1)} Client ID</label>
          <input type="text" id="set-${service}_client_id" value="${escapeHtml(cfg[`${service}_client_id`] || '')}">
        </div>
        <div class="input-group">
          <label for="set-${service}_client_secret">Client Secret ${connected ? '✅' : ''}</label>
          <input type="password" id="set-${service}_client_secret" placeholder="${secretSet ? '•••••• (sparad)' : ''}">
        </div>
      </div>`;
  }).join('');

  return `
    <h3 style="margin-top:0;">🤖 AI-leverantör</h3>
    <div class="input-group">
      <label for="set-ai_provider">Leverantör</label>
      <select id="set-ai_provider" class="select-input" onchange="renderProviderFields()">${providerOptions}</select>
    </div>
    <div id="provider-fields"></div>

    <h3>⌚ Garmin Connect</h3>
    <div class="input-row">
      <div class="input-group">
        <label for="set-garmin_email">E-post</label>
        <input type="email" id="set-garmin_email" value="${escapeHtml(cfg.garmin_email || '')}">
      </div>
      <div class="input-group">
        <label for="set-garmin_password">Lösenord</label>
        <input type="password" id="set-garmin_password" placeholder="${(cfg.secrets_set || {}).garmin_password ? '•••••• (sparat)' : ''}">
      </div>
    </div>

    <h3>🔗 Övriga källor</h3>
    ${sourceRows}
    <p class="summary-subtext">Redirect-URL att registrera hos varje tjänst:
      <code>${escapeHtml(data.redirect_base || '')}/oauth/&lt;tjänst&gt;/callback</code></p>

    <p class="summary-subtext">Tomma hemlighetsfält lämnar det som redan är sparat orört.</p>
  `;
}

function renderProviderFields() {
  const provider = document.getElementById('set-ai_provider').value;
  const cfg = (settingsCache && settingsCache.config) || {};
  const providers = (settingsCache && settingsCache.providers) || {};
  const container = document.getElementById('provider-fields');
  if (!container) return;

  container.innerHTML = (PROVIDER_FIELDS[provider] || []).map(([key, label, type]) => {
    if (type === 'model') {
      const models = (providers[provider] && providers[provider].models) || [];
      const current = cfg[key] || '';
      const options = (models.includes(current) || !current ? models : [current, ...models])
        .map((m) => `<option value="${escapeHtml(m)}" ${m === current ? 'selected' : ''}>${escapeHtml(m)}</option>`)
        .join('');
      return `<div class="input-group"><label for="set-${key}">${label}</label>
        <select id="set-${key}" class="select-input">${options}</select></div>`;
    }
    if (type === 'password') {
      const isSet = (cfg.secrets_set || {})[key];
      return `<div class="input-group"><label for="set-${key}">${label}</label>
        <input type="password" id="set-${key}" placeholder="${isSet ? '•••••• (sparad — lämna tom för att behålla)' : ''}"></div>`;
    }
    return `<div class="input-group"><label for="set-${key}">${label}</label>
      <input type="text" id="set-${key}" value="${escapeHtml(cfg[key] || '')}"></div>`;
  }).join('');

  // Ask the provider for its live model list; fall back quietly.
  const modelSelect = document.getElementById(`set-${provider}_model`) || document.getElementById('set-ollama_model');
  if (modelSelect) {
    fetch(`/api/settings/models?provider=${provider}`, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((result) => {
        if (!result || !result.models || !result.models.length) return;
        const value = modelSelect.value;
        modelSelect.innerHTML = result.models
          .map((m) => `<option value="${escapeHtml(m)}" ${m === value ? 'selected' : ''}>${escapeHtml(m)}</option>`)
          .join('');
      })
      .catch(() => {});
  }
}

async function saveSettings() {
  const values = {};
  const provider = document.getElementById('set-ai_provider').value;
  values.ai_provider = provider;

  const keys = (PROVIDER_FIELDS[provider] || []).map(([key]) => key).concat([
    'garmin_email', 'garmin_password',
    'fitbit_client_id', 'fitbit_client_secret',
    'strava_client_id', 'strava_client_secret',
    'withings_client_id', 'withings_client_secret',
  ]);
  keys.forEach((key) => {
    const el = document.getElementById(`set-${key}`);
    if (el) values[key] = el.value;
  });

  try {
    await apiPost('/api/settings', { values });
    await refreshConnectionStatus();
    return true;
  } catch (err) {
    notify(err.message, true);
    return false;
  }
}

// --- quick questions --------------------------------------------------------

async function loadQuickQuestions() {
  try {
    quickQuestions = (await api('/api/quick-questions')).questions || [];
  } catch (err) {
    quickQuestions = [];
  }
  const row = document.getElementById('quick-questions-row');
  if (!row) return;
  row.innerHTML = quickQuestions
    .map((q, i) => `<button class="chip-btn" onclick="useQuickQuestion(${i})">${escapeHtml(q)}</button>`)
    .join('');
}

function useQuickQuestion(index) {
  const question = quickQuestions[index];
  if (question) sendQuickPrompt(question);
}

function openCustomizeQuestions() {
  const rows = Array.from({ length: 8 }, (_, i) => `
    <div class="input-group">
      <label for="qq-${i}">Fråga ${i + 1}</label>
      <input type="text" id="qq-${i}" value="${escapeHtml(quickQuestions[i] || '')}">
    </div>`).join('');

  showDialog('⚙️ Anpassa snabbfrågor', rows, [
    { label: 'Avbryt', onClick: (close) => close() },
    {
      label: 'Spara',
      primary: true,
      onClick: async (close) => {
        const questions = Array.from({ length: 8 }, (_, i) => document.getElementById(`qq-${i}`).value);
        try {
          await apiPost('/api/quick-questions', { questions });
          await loadQuickQuestions();
          close();
        } catch (err) {
          notify(err.message, true);
        }
      },
    },
  ]);
}

// --- saved prompts ----------------------------------------------------------

let promptsCache = [];
let selectedPrompt = -1;

async function openPrompts() {
  try {
    promptsCache = (await api('/api/prompts')).prompts || [];
  } catch (err) {
    notify(err.message, true);
    return;
  }
  selectedPrompt = -1;
  showDialog('📝 Sparade promptar', promptsHtml(), [
    { label: '🗑 Ta bort', onClick: () => deletePrompt() },
    { label: '💾 Spara', onClick: () => savePrompt() },
    { label: '▶ Använd', primary: true, onClick: (close) => usePrompt(close) },
    { label: 'Stäng', onClick: (close) => close() },
  ]);
}

function promptsHtml() {
  const list = promptsCache.length
    ? promptsCache.map((p, i) => `
        <div class="data-table-row" style="padding:8px 10px; cursor:pointer; border-bottom:1px solid #E5E7EB; ${i === selectedPrompt ? 'background:#E6F2FA;' : ''}"
             onclick="selectPrompt(${i})">
          <strong>${escapeHtml(p.name)}</strong>
          <div class="summary-subtext">${escapeHtml((p.prompt || '').slice(0, 90))}</div>
        </div>`).join('')
    : '<p class="summary-subtext">Inga sparade promptar än.</p>';

  const current = selectedPrompt >= 0 ? promptsCache[selectedPrompt] : { name: '', prompt: '' };
  return `
    <div style="max-height:240px; overflow-y:auto; border:1px solid #E5E7EB; border-radius:6px;">${list}</div>
    <div class="input-group" style="margin-top:12px;">
      <label for="prompt-name">Namn</label>
      <input type="text" id="prompt-name" value="${escapeHtml(current.name || '')}">
    </div>
    <div class="input-group">
      <label for="prompt-text">Prompt</label>
      <textarea id="prompt-text" rows="6" class="select-input">${escapeHtml(current.prompt || '')}</textarea>
    </div>`;
}

function selectPrompt(index) {
  selectedPrompt = index;
  document.getElementById('app-modal-body').innerHTML = promptsHtml();
}

async function savePrompt() {
  const name = document.getElementById('prompt-name').value.trim() || 'Prompt';
  const prompt = document.getElementById('prompt-text').value;
  try {
    const result = selectedPrompt >= 0
      ? await api(`/api/prompts/${selectedPrompt}`, { method: 'PUT', body: JSON.stringify({ name, prompt }) })
      : await apiPost('/api/prompts', { name, prompt });
    promptsCache = result.prompts;
    document.getElementById('app-modal-body').innerHTML = promptsHtml();
  } catch (err) {
    notify(err.message, true);
  }
}

async function deletePrompt() {
  if (selectedPrompt < 0) return;
  try {
    promptsCache = (await api(`/api/prompts/${selectedPrompt}`, { method: 'DELETE' })).prompts;
    selectedPrompt = -1;
    document.getElementById('app-modal-body').innerHTML = promptsHtml();
  } catch (err) {
    notify(err.message, true);
  }
}

function usePrompt(close) {
  if (selectedPrompt < 0) return;
  const field = document.getElementById('chat-input-field');
  if (field) field.value = promptsCache[selectedPrompt].prompt;
  showTab('ai-chat');
  close();
}

// --- chat history, search and export ---------------------------------------

function openSaveChat() {
  showDialog('💾 Spara chatt',
    `<div class="input-group"><label for="chat-name">Namn på chatten</label>
     <input type="text" id="chat-name" placeholder="t.ex. PT-analys vecka 37"></div>`,
    [
      { label: 'Avbryt', onClick: (close) => close() },
      {
        label: 'Spara',
        primary: true,
        onClick: async (close) => {
          try {
            await apiPost('/api/chats', { name: document.getElementById('chat-name').value || 'Chat' });
            close();
            notify('✅ Chatten sparades.');
          } catch (err) {
            notify(err.message, true);
          }
        },
      },
    ]);
}

let chatsCache = [];
let selectedChat = null;

async function openHistory() {
  try {
    chatsCache = (await api('/api/chats')).chats || [];
  } catch (err) {
    notify(err.message, true);
    return;
  }
  selectedChat = null;
  showDialog('📂 Chatthistorik', historyHtml(), [
    { label: '✏️ Byt namn', onClick: () => renameChat() },
    { label: '🗑 Ta bort', onClick: () => deleteChat() },
    { label: '📥 Ladda in', primary: true, onClick: (close) => loadChat(close) },
    { label: 'Stäng', onClick: (close) => close() },
  ]);
}

function historyHtml() {
  if (!chatsCache.length) return '<p class="summary-subtext">Inga sparade chattar än.</p>';
  return `<div style="max-height:340px; overflow-y:auto; border:1px solid #E5E7EB; border-radius:6px;">
    ${chatsCache.map((c) => `
      <div style="padding:8px 10px; cursor:pointer; border-bottom:1px solid #E5E7EB; ${c.id === selectedChat ? 'background:#E6F2FA;' : ''}"
           onclick="selectChat('${c.id}')">
        <strong>${escapeHtml(c.name)}</strong>
        <div class="summary-subtext">${c.message_count || 0} meddelanden · ${escapeHtml(c.saved_at || '')}</div>
      </div>`).join('')}
  </div>`;
}

function selectChat(id) {
  selectedChat = id;
  document.getElementById('app-modal-body').innerHTML = historyHtml();
}

async function loadChat(close) {
  if (!selectedChat) return;
  try {
    const data = await apiPost(`/api/chats/${selectedChat}/load`);
    renderChatMessages(data.messages || []);
    showTab('ai-chat');
    close();
  } catch (err) {
    notify(err.message, true);
  }
}

async function renameChat() {
  if (!selectedChat) return;
  const name = window.prompt('Nytt namn:');
  if (!name) return;
  try {
    chatsCache = (await api(`/api/chats/${selectedChat}`, { method: 'PUT', body: JSON.stringify({ name }) })).chats;
    document.getElementById('app-modal-body').innerHTML = historyHtml();
  } catch (err) {
    notify(err.message, true);
  }
}

async function deleteChat() {
  if (!selectedChat) return;
  try {
    chatsCache = (await api(`/api/chats/${selectedChat}`, { method: 'DELETE' })).chats;
    selectedChat = null;
    document.getElementById('app-modal-body').innerHTML = historyHtml();
  } catch (err) {
    notify(err.message, true);
  }
}

function openSearch() {
  showDialog('🔍 Sök i chatthistoriken',
    `<div class="input-group">
       <input type="text" id="search-q" placeholder="Sökord..." onkeydown="if(event.key==='Enter'){runSearch();}">
     </div>
     <div id="search-results"></div>`,
    [
      { label: 'Sök', primary: true, onClick: () => runSearch() },
      { label: 'Stäng', onClick: (close) => close() },
    ]);
  setTimeout(() => { const el = document.getElementById('search-q'); if (el) el.focus(); }, 50);
}

async function runSearch() {
  const query = document.getElementById('search-q').value.trim();
  if (!query) return;
  const target = document.getElementById('search-results');
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
    target.innerHTML = (data.results || []).length
      ? data.results.map((hit) => `
          <div style="padding:8px 10px; border-bottom:1px solid #E5E7EB;">
            <strong>${escapeHtml(hit.sender || '')}</strong>: ${escapeHtml((hit.message || '').slice(0, 180))}
            <div class="summary-subtext">${escapeHtml(hit.chat || '')} · ${escapeHtml(hit.timestamp || '')}</div>
          </div>`).join('')
      : '<p class="summary-subtext">Inga träffar.</p>';
  } catch (err) {
    target.innerHTML = `<p class="error-msg">${escapeHtml(err.message)}</p>`;
  }
}

function openExport() {
  showDialog('📄 Exportera rapport',
    `<div class="input-group">
       <label for="export-format">Format</label>
       <select id="export-format" class="select-input">
         <option value="pdf">PDF</option>
         <option value="docx">Word (DOCX)</option>
         <option value="txt">Text (TXT)</option>
       </select>
     </div>
     <label style="display:block; margin-top:8px;"><input type="checkbox" id="export-ts" checked> Inkludera tidsstämplar</label>
     <label style="display:block; margin-top:4px;"><input type="checkbox" id="export-sys"> Inkludera systemmeddelanden</label>`,
    [
      { label: 'Avbryt', onClick: (close) => close() },
      {
        label: 'Exportera',
        primary: true,
        onClick: async (close) => {
          const format = document.getElementById('export-format').value;
          try {
            const res = await fetch('/api/export', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              credentials: 'same-origin',
              body: JSON.stringify({
                format,
                include_timestamp: document.getElementById('export-ts').checked,
                include_system: document.getElementById('export-sys').checked,
              }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Exporten misslyckades');
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `healthchat_rapport.${format}`;
            link.click();
            URL.revokeObjectURL(url);
            close();
          } catch (err) {
            notify(err.message, true);
          }
        },
      },
    ]);
}

async function resetChat() {
  try {
    await apiPost('/api/chat/reset');
    renderChatMessages([]);
  } catch (err) {
    notify(err.message, true);
  }
}

function renderChatMessages(messages) {
  const list = document.getElementById('chat-messages-list');
  if (!list) return;
  list.innerHTML = '';
  messages.forEach((msg) => {
    const role = msg.type === 'user' ? 'user' : 'bot';
    appendChatMessage(role, msg.message);
  });
}

// --- theme ------------------------------------------------------------------

function toggleTheme() {
  const dark = !document.body.classList.contains('dark-theme');
  document.body.classList.toggle('dark-theme', dark);
  try {
    localStorage.setItem('healthchat_dark', dark ? '1' : '0');
  } catch (err) { /* private mode */ }
  apiPost('/api/settings', { values: { dark_mode: dark } }).catch(() => {});
}

function applyStoredTheme() {
  let dark = false;
  try {
    dark = localStorage.getItem('healthchat_dark') === '1';
  } catch (err) { /* private mode */ }
  document.body.classList.toggle('dark-theme', dark);
}

// --- startup ----------------------------------------------------------------

async function initRestoredFeatures() {
  applyStoredTheme();
  await Promise.all([loadQuickQuestions(), refreshConnectionStatus()]);

  // Load any conversation already in progress on the server.
  try {
    const data = await api('/api/chat');
    if (data.messages && data.messages.length) renderChatMessages(data.messages);
  } catch (err) { /* not logged in yet */ }

  setInterval(refreshConnectionStatus, 30000);
}
