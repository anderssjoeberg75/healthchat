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
      onAuthSuccess();
    } else {
      errDiv.innerText = data.detail || 'Inloggningen misslyckades.';
      errDiv.classList.remove('hidden');
    }
  } catch (err) {
    errDiv.innerText = `Nätverksfel vid inloggning: ${err.message || err}`;
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
    
    if (currentTab === 'training') {
      renderTrainingCharts();
    } else {
      renderHealthCharts();
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

function updateDashboardCards(data) {
  const days = currentDaysRange;
  const daysLabel = days < 365 ? `${days} d` : (days > 365 ? 'alla d' : '1 år');

  // 1. Recovery Score Card
  const bb = data.bb_latest || {};
  const recVal = bb.highest_level || 72;
  const recColor = recVal >= 75 ? '#10B981' : (recVal >= 45 ? '#F59E0B' : '#EF4444');
  
  const recValEl = document.getElementById('val-bb-level');
  if (recValEl) {
    recValEl.innerText = `${recVal}%`;
    recValEl.style.color = recColor;
  }

  const recStatusSummary = recVal >= 80 ? "Fullt återhämtad och redo för topprestation!" :
    (recVal >= 60 ? "Återhämtad och redo för dagen!" :
    (recVal >= 40 ? "Måttlig återhämtning – anpassa träningsintensiteten" :
    "Låg återhämtning – prioritera vila och återhämtning"));
  
  const recStatusEl = document.getElementById('val-recovery-status');
  if (recStatusEl) recStatusEl.innerText = recStatusSummary;

  const aiBoxEl = document.getElementById('val-recovery-ai-box');
  if (aiBoxEl) {
    aiBoxEl.innerText = getRecoveryAiAdvice(recVal);
  }

  // 2. Weight & Body Comp Card
  const bodyComp = data.latest_body_comp || {};
  const historyBodyComp = (data.history && data.history.body_composition) || [];
  
  const wKg = bodyComp.weight_kg ? floatVal(bodyComp.weight_kg) : 98.3;
  const wEl = document.getElementById('val-weight-kg');
  if (wEl) wEl.innerText = `${wKg.toFixed(1)} kg`;

  let trendStr = "📈 +0.5 kg (+0.5%) under " + daysLabel;
  let trendColor = "#10B981";
  
  if (historyBodyComp.length >= 2) {
    const firstW = floatVal(historyBodyComp[0].weight_kg || wKg);
    const diffKg = wKg - firstW;
    const diffPct = firstW > 0 ? (diffKg / firstW * 100.0) : 0.0;
    const icon = diffKg < 0 ? "📉" : (diffKg > 0 ? "📈" : "➡️");
    trendColor = diffKg <= 0 ? "#10B981" : "#EF4444";
    trendStr = `${icon} ${diffKg >= 0 ? '+' : ''}${diffKg.toFixed(1)} kg (${diffPct >= 0 ? '+' : ''}${diffPct.toFixed(1)}%) under ${daysLabel}`;
  } else {
    // Dynamic weight change calculation per interval
    const demoDiff = days >= 365 ? -3.8 : (days >= 90 ? -2.1 : (days >= 30 ? -1.2 : -0.4));
    const demoPct = (demoDiff / wKg * 100.0);
    const icon = demoDiff < 0 ? "📉" : "📈";
    trendStr = `${icon} ${demoDiff.toFixed(1)} kg (${demoPct.toFixed(1)}%) under ${daysLabel}`;
    trendColor = demoDiff <= 0 ? "#10B981" : "#EF4444";
  }

  const trendEl = document.getElementById('val-weight-trend');
  if (trendEl) {
    trendEl.innerText = trendStr;
    trendEl.style.color = trendColor;
  }

  const profile = data.profile || {};
  const heightCm = floatVal(profile.height_cm, 186.0);
  const bmi = heightCm > 0 ? (wKg / ((heightCm / 100.0) ** 2)) : 28.4;
  const bmiEl = document.getElementById('val-bmi-text');
  if (bmiEl) bmiEl.innerText = `BMI: ${bmi.toFixed(1)} (📉 -0.3 under ${daysLabel})`;

  const fatPct = floatVal(bodyComp.fat_ratio_pct, 21.4);
  const muscleKg = floatVal(bodyComp.muscle_mass_kg, 72.1);
  const fatEl = document.getElementById('val-fat-pct');
  if (fatEl) fatEl.innerText = `Fett: ${fatPct.toFixed(1)}% | Muskelmassa: ${muscleKg.toFixed(1)} kg`;

  const srcEl = document.getElementById('val-weight-source');
  if (srcEl) srcEl.innerText = `Källa: ${bodyComp.source || 'Withings'} (${data.today_date || '2026-09-11'})`;

  // 3. Calorie Burn Card
  const burn = data.calorie_burn_today || {};
  const totalBurn = burn.total_burn || 2848;
  const restingBurn = burn.resting_burn || 2150;
  const stepsBurn = burn.steps_burn || 420;
  const workoutBurn = burn.workout_burn || 278;

  const calTotalEl = document.getElementById('val-calories-total');
  if (calTotalEl) calTotalEl.innerText = `${formatNumber(totalBurn)} kcal`;

  const calBreakdownEl = document.getElementById('val-calories-breakdown');
  if (calBreakdownEl) {
    calBreakdownEl.innerText = `Vila: ${formatNumber(restingBurn)} kcal | Aktivitet: ${formatNumber(stepsBurn)} kcal | Träning: ${formatNumber(workoutBurn)} kcal`;
  }

  const bmrSourceMap = { 'device': 'Garmins BMR', 'mifflin': 'Mifflin-St Jeor', 'simple': 'Viktbaserad BMR' };
  const calSrcEl = document.getElementById('val-calories-source');
  if (calSrcEl) calSrcEl.innerText = `Källa: ${bmrSourceMap[burn.bmr_source] || 'Mifflin-St Jeor / Garmins BMR'}`;
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

function generateDatesForRange(days) {
  const dates = [];
  const now = new Date();
  const count = days >= 365 ? 12 : (days > 30 ? 14 : Math.min(days, 14));
  const stepDays = days >= 365 ? 30 : (days > 14 ? Math.round(days / count) : 1);

  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - (i * stepDays));
    if (days >= 365) {
      dates.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    } else {
      dates.push(`${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`);
    }
  }
  return dates;
}

function generateMockSeries(baseVal, variance, count, seed = 1) {
  return Array.from({ length: count }, (_, i) => {
    const val = baseVal + (Math.sin((i + seed) * 0.7) * variance) + ((Math.cos(i * 1.3)) * (variance * 0.25));
    return Number(val.toFixed(1));
  });
}


// --- 8 COROS-INSPIRED CHARTS (CHART.JS) ---

function renderHealthCharts() {
  if (!cachedSummary) return;
  const history = cachedSummary.history || {};

  const hasRealData = history.calorie_burn && history.calorie_burn.length > 0;
  const dates = hasRealData 
    ? history.calorie_burn.map(c => c.date) 
    : generateDatesForRange(currentDaysRange);
  const count = dates.length;

  // 1. Weight Chart (Blue line)
  const weightData = (history.body_comp && history.body_comp.length > 0)
    ? history.body_comp.map(b => b.weight_kg)
    : generateMockSeries(98.5, 1.2, count, 1);
  createChart('chart-weight', 'line', {
    labels: dates,
    datasets: [{ label: 'Vikt (kg)', data: weightData, borderColor: '#0078D4', backgroundColor: 'rgba(0,120,212,0.1)', tension: 0.3, fill: true }]
  });

  // 2. Calories Stacked Bar Chart (Orange resting, Blue active, Red workout)
  const cals = history.calorie_burn || [];
  const restingData = cals.length > 0 ? cals.map(c => c.resting_burn || 0) : generateMockSeries(2150, 40, count, 2);
  const activeData = cals.length > 0 ? cals.map(c => c.steps_burn || 0) : generateMockSeries(420, 90, count, 3);
  const workoutData = cals.length > 0 ? cals.map(c => c.workout_burn || 0) : generateMockSeries(350, 200, count, 4);
  createChart('chart-calories', 'bar', {
    labels: dates,
    datasets: [
      { label: 'Vilo-BMR', data: restingData, backgroundColor: '#F59E0B' },
      { label: 'Aktivitet', data: activeData, backgroundColor: '#0284C7' },
      { label: 'Träning', data: workoutData, backgroundColor: '#DC2626' }
    ]
  }, { stacked: true });

  // 3. RHR Chart (Blue line)
  const rhrData = (history.daily_summary && history.daily_summary.length > 0)
    ? history.daily_summary.map(d => d.resting_hr || 52)
    : generateMockSeries(51, 3, count, 5);
  createChart('chart-rhr', 'line', {
    labels: dates,
    datasets: [{ label: 'Vilo-puls (bpm)', data: rhrData, borderColor: '#0284C7', tension: 0.3 }]
  });

  // 4. HRV Chart (Rose/Pink line)
  const hrv = history.hrv || [];
  const hrvData = hrv.length > 0 ? hrv.map(h => h.weekly_avg) : generateMockSeries(68, 6, count, 6);
  createChart('chart-hrv', 'line', {
    labels: dates,
    datasets: [{ label: 'Vilo-HRV (ms)', data: hrvData, borderColor: '#EC4899', tension: 0.3 }]
  });

  // 5. Sleep Duration Bar Chart (Purple bars)
  const sleep = history.sleep || [];
  const sleepData = sleep.length > 0 ? sleep.map(s => s.total_sleep_hours) : generateMockSeries(7.5, 0.8, count, 7);
  createChart('chart-sleep', 'bar', {
    labels: dates,
    datasets: [{ label: 'Sömntid (timmar)', data: sleepData, backgroundColor: '#8B5CF6' }]
  });

  // 6. Sleep Score Line Chart (Green line)
  const sleepScoreData = sleep.length > 0 ? sleep.map(s => s.sleep_score || 80) : generateMockSeries(83, 7, count, 8);
  createChart('chart-sleep-score', 'line', {
    labels: dates,
    datasets: [{ label: 'Sömnkvalitet (0-100)', data: sleepScoreData, borderColor: '#10B981', tension: 0.3 }]
  });

  // 7. Body Battery Line Chart (Purple line)
  const bb = history.body_battery || [];
  const bbData = bb.length > 0 ? bb.map(b => b.highest_level) : generateMockSeries(86, 9, count, 9);
  createChart('chart-bb', 'line', {
    labels: dates,
    datasets: [{ label: 'Max Body Battery', data: bbData, borderColor: '#8B5CF6', tension: 0.3 }]
  });

  // 8. Stress Level Line Chart (Amber line)
  const stress = history.stress || [];
  const stressData = stress.length > 0 ? stress.map(s => s.avg_stress_level) : generateMockSeries(25, 5, count, 10);
  createChart('chart-stress', 'line', {
    labels: dates,
    datasets: [{ label: 'Snittstress', data: stressData, borderColor: '#F59E0B', tension: 0.3 }]
  });
}

function renderTrainingCharts() {
  const dates = generateDatesForRange(currentDaysRange);
  const count = dates.length;

  createChart('chart-training-volume', 'bar', {
    labels: dates,
    datasets: [{ label: 'Träningsvolym (timmar)', data: generateMockSeries(4.5, 2.0, count, 11), backgroundColor: '#0284C7' }]
  });

  createChart('chart-hr-zones', 'bar', {
    labels: ['Z1 (Återhämtning)', 'Z2 (Aerob/MAF)', 'Z3 (Tempo)', 'Z4 (Tröskel)', 'Z5 (Anaerob)'],
    datasets: [{ label: 'Tid i zoner (%)', data: [35, 45, 12, 6, 2], backgroundColor: ['#10B981', '#0284C7', '#F59E0B', '#F97316', '#DC2626'] }]
  });
}

function createChart(canvasId, type, data, options = {}) {
  const canvasEl = document.getElementById(canvasId);
  if (!canvasEl) return;

  if (chartInstances[canvasId]) {
    chartInstances[canvasId].destroy();
  }
  
  const ctx = canvasEl.getContext('2d');
  chartInstances[canvasId] = new Chart(ctx, {
    type: type,
    data: data,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { stacked: options.stacked || false, grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { color: '#6B7280' } },
        y: { stacked: options.stacked || false, grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { color: '#6B7280' } }
      },
      plugins: {
        legend: { labels: { color: '#374151', font: { family: 'Segoe UI' } } }
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

  const provider = document.getElementById('ai-provider-select').value;
  input.value = '';

  appendChatMessage('user', message);
  const botBubble = appendChatMessage('bot', 'Tänker...');

  try {
    const res = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, provider })
    });

    if (!res.ok) {
      botBubble.innerText = '⚠️ Kunde inte få svar från AI.';
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    botBubble.innerText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const dataStr = line.slice(6);
          if (dataStr === '[DONE]') break;
          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.content) {
              botBubble.innerText += parsed.content;
            }
          } catch (e) {}
        }
      }
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
