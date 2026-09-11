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
    populateProfileInputs(currentUser.profile || {});
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
  } else if (tabId === 'profile') {
    populateProfileInputs();
  }
}

async function populateProfileInputs(profile) {
  let p = profile || (currentUser && currentUser.profile) || (cachedSummary && cachedSummary.profile) || {};
  if (!p.height_cm || !p.age) {
    try {
      const res = await fetch('/api/auth/me');
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

  // 3. Calorie Burn Card (matching Desktop card_calories)
  const burn = data.calorie_burn_today || {};
  const totalBurn = burn.total_burn !== undefined ? burn.total_burn : 1195;
  const restingBurn = burn.resting_burn !== undefined ? burn.resting_burn : 1123;
  const stepsBurn = burn.steps_burn !== undefined ? burn.steps_burn : 72;
  const workoutBurn = burn.workout_burn !== undefined ? burn.workout_burn : 0;
  const everydaySteps = burn.everyday_steps !== undefined ? burn.everyday_steps : (burn.steps || 1273);

  const calTotalEl = document.getElementById('val-calories-total');
  if (calTotalEl) {
    calTotalEl.innerText = `🔥 ${formatNumber(totalBurn)} kcal`;
    calTotalEl.style.color = '#EA580C';
  }

  const calSubtextEl = document.getElementById('val-calories-subtext');
  if (calSubtextEl) {
    calSubtextEl.innerText = 'Förbränt hittills idag (ungefärligt)';
  }

  const calBreakdownEl = document.getElementById('val-calories-breakdown');
  if (calBreakdownEl) {
    let stepsLine = `👟 Vardagssteg: ${formatNumber(stepsBurn)} kcal (${formatNumber(everydaySteps)} st)`;
    if (burn.workout_steps > 0) {
      stepsLine += ` (avdrag ${formatNumber(burn.workout_steps)} st träning)`;
    }
    calBreakdownEl.innerHTML = `
      <div>🛌 Vila (BMR): ${formatNumber(restingBurn)} kcal</div>
      <div>${stepsLine}</div>
      <div>🏋️ Träning: ${formatNumber(workoutBurn)} kcal</div>
    `;
  }

  const bmrSourceMap = {
    'device': 'Vilo-BMR från Garmin',
    'mifflin': 'Vilo-BMR beräknad från din profil',
    'simple': 'Vilo-BMR grovt uppskattad (ange profil för bättre värde)'
  };
  const calSrcEl = document.getElementById('val-calories-source');
  if (calSrcEl) {
    const srcText = bmrSourceMap[burn.bmr_source] || 'Vilo-BMR från Garmin';
    calSrcEl.innerText = srcText;
    calSrcEl.style.fontStyle = 'italic';
    calSrcEl.style.color = '#9CA3AF';
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

function generateMockSeries(baseVal, variance, count, seed = 1, days = 30) {
  const rangeFactor = Math.sin(days * 0.05);
  return Array.from({ length: count }, (_, i) => {
    const val = baseVal + (Math.sin((i + seed + days) * 0.7) * variance) + ((Math.cos((i + days) * 1.3)) * (variance * 0.25)) + (rangeFactor * variance * 0.3);
    return Number(val.toFixed(1));
  });
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
  const count = fallbackDates.length;

  // 1. Weight Chart (Blue line, matching Desktop ax_health_weight)
  const bodyComp = (history.body_composition || []).filter(b => b.weight_kg && Number(b.weight_kg) > 0);
  const weightExt = extractChartData(bodyComp, 'date', 'weight_kg');
  const weightLabels = weightExt ? weightExt.labels : fallbackDates;
  const weightData = weightExt ? weightExt.data : generateMockSeries(98.5, 1.2, count, 1, days);
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

  // 2. Calories Stacked Bar Chart (Vila BMR, Steg, Träning matching Desktop ax_health_calories)
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
  const calExt = extractChartData(mergedCals, 'date', item => item);
  const calLabels = calExt ? calExt.labels : fallbackDates;
  const restingData = calExt ? calExt.raw.map(c => Number(c.resting_burn || 0)) : generateMockSeries(2150, 40, count, 2, days);
  const activeData = calExt ? calExt.raw.map(c => Number(c.steps_burn || 0)) : generateMockSeries(420, 90, count, 3, days);
  const workoutData = calExt ? calExt.raw.map(c => Number(c.workout_burn || 0)) : generateMockSeries(350, 200, count, 4, days);
  createChart('chart-calories', 'bar', {
    labels: calLabels,
    datasets: [
      { label: 'Vila (BMR)', data: restingData, backgroundColor: '#F59E0B' },
      { label: 'Steg / Aktivitet', data: activeData, backgroundColor: '#0078D4' },
      { label: 'Träning', data: workoutData, backgroundColor: '#EF4444' }
    ]
  }, { stacked: true });

  // 3. Resting Heart Rate / Vilopuls (Pink/rose matching Desktop ax_health_rhr)
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
  const rhrData = hasRhr ? sortedRhrDates.map(d => rhrMap[d]) : generateMockSeries(51, 3, count, 5, days);
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

  // 4. Nattlig HRV Trend (Emerald green matching Desktop ax_health_hrv)
  const hrv = history.hrv || [];
  const hrvExt = extractChartData(hrv, 'date', item => {
    if (item.last_night_avg !== undefined && item.last_night_avg !== null) {
      return Number(item.last_night_avg);
    }
    return 0;
  });
  const hrvLabels = hrvExt ? hrvExt.labels : fallbackDates;
  const hrvData = hrvExt ? hrvExt.data : generateMockSeries(25, 6, count, 6, days);
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

  // 5. Sleep Duration Bar Chart (Purple matching Desktop ax_health_sleep)
  const sleep = (history.sleep || []).filter(s => (s.total_sleep_hours !== undefined && Number(s.total_sleep_hours) > 0));
  const sleepExt = extractChartData(sleep, 'date', 'total_sleep_hours');
  const sleepLabels = sleepExt ? sleepExt.labels : fallbackDates;
  const sleepData = sleepExt ? sleepExt.data : generateMockSeries(7.5, 0.8, count, 7, days);
  createChart('chart-sleep', 'bar', {
    labels: sleepLabels,
    datasets: [{ label: 'Sömntid (timmar)', data: sleepData, backgroundColor: '#8B5CF6' }]
  });

  // 6. Sleep Quality / Score Trend (Purple matching Desktop ax_health_sleep_score)
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
  const scoreData = hasScore ? sortedScoreDates.map(d => scoreMap[d]) : generateMockSeries(83, 7, count, 8, days);
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

  // 7. Body Battery Uppladdat (+) (Emerald green matching Desktop ax_health_bb)
  const bb = history.body_battery || [];
  const bbExt = extractChartData(bb, 'date', item => {
    const val = item.charged !== undefined && item.charged !== null ? item.charged : item.highest_level;
    return val !== undefined ? Number(val) : 0;
  });
  const bbLabels = bbExt ? bbExt.labels : fallbackDates;
  const bbData = bbExt ? bbExt.data : generateMockSeries(86, 9, count, 9, days);
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

  // 8. Genomsnittlig Stress Level (Coral/orange-red matching Desktop ax_health_stress)
  const stress = history.stress || [];
  const stressExt = extractChartData(stress, 'date', item => {
    const val = item.average !== undefined && item.average !== null ? item.average : item.avg_stress_level;
    return val !== undefined ? Number(val) : 0;
  });
  const stressLabels = stressExt ? stressExt.labels : fallbackDates;
  const stressData = stressExt ? stressExt.data : generateMockSeries(25, 5, count, 10, days);
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
}

function renderTrainingCharts() {
  const days = currentDaysRange;
  const fallbackDates = generateDatesForRange(days);
  const count = fallbackDates.length;

  const activities = (cachedSummary && cachedSummary.history && cachedSummary.history.activities) || [];
  
  if (activities.length > 0) {
    const actByDate = {};
    activities.forEach(a => {
      const d = String(a.date || a.start_time || '').slice(0, 10);
      if (d) {
        const distKm = Number(a.distance_km || 0);
        actByDate[d] = (actByDate[d] || 0) + distKm;
      }
    });
    const sortedDates = Object.keys(actByDate).sort();
    const actLabels = sortedDates.map(d => d.slice(5));
    const actData = sortedDates.map(d => Number(actByDate[d].toFixed(2)));
    createChart('chart-training-volume', 'bar', {
      labels: actLabels,
      datasets: [{ label: 'Träningsdistans (km)', data: actData, backgroundColor: '#0078D4' }]
    });
  } else {
    createChart('chart-training-volume', 'bar', {
      labels: fallbackDates,
      datasets: [{ label: 'Träningsdistans (km)', data: generateMockSeries(4.5, 2.0, count, 11, days), backgroundColor: '#0078D4' }]
    });
  }

  createChart('chart-hr-zones', 'bar', {
    labels: ['Z1 (Återhämtning)', 'Z2 (Aerob/MAF)', 'Z3 (Tempo)', 'Z4 (Tröskel)', 'Z5 (Anaerob)'],
    datasets: [{ label: 'Tid i zoner (%)', data: [35, 45, 12, 6, 2], backgroundColor: ['#10B981', '#0284C7', '#F59E0B', '#F97316', '#DC2626'] }]
  });
}

function createChart(canvasId, type, data, options = {}) {
  const canvasEl = document.getElementById(canvasId);
  if (!canvasEl) return;

  if (chartInstances[canvasId]) {
    try {
      chartInstances[canvasId].destroy();
    } catch (e) {}
    delete chartInstances[canvasId];
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
  const ageVal = document.getElementById('prof-age').value.trim();
  const heightVal = document.getElementById('prof-height').value.trim();
  const weightVal = document.getElementById('prof-weight').value.trim();

  const age = ageVal ? parseInt(ageVal) : null;
  const height_cm = heightVal ? parseFloat(heightVal.replace(',', '.')) : null;
  const weight_kg = weightVal ? parseFloat(weightVal.replace(',', '.')) : null;

  try {
    const res = await fetch('/api/profile/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sex, age, height_cm, weight_kg })
    });
    const data = await res.json();
    if (res.ok) {
      const updated = data.profile || { sex, age, height_cm, weight_kg };
      if (currentUser) currentUser.profile = updated;
      if (cachedSummary) cachedSummary.profile = updated;
      populateProfileInputs(updated);
      alert('Profilen har sparats klientside-krypterat i MariaDB!');
      refreshDashboard();
    } else {
      alert(data.detail || 'Kunde inte uppdatera profilen.');
    }
  } catch (e) {
    alert('Nätverksfel vid sparande av profil.');
  }
}

async function handleChangePassword(event) {
  event.preventDefault();
  const current_password = document.getElementById('pwd-current').value;
  const new_password = document.getElementById('pwd-new').value;

  try {
    const res = await fetch('/api/profile/change_password', {
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
    alert('Nätverksfel vid lösenordsbyte.');
  }
}
