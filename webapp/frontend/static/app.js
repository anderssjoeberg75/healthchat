/*
 * HealthChat Web — single-page frontend.
 *
 * Every screen, button and dialog mirrors the Tkinter desktop build; the state
 * that used to live in the HealthChatApp instance now lives on the server and
 * is reached through the /api endpoints.
 */

const state = {
    days: 30,
    tab: 'dashboard',
    chatVisible: false,
    dark: false,
    authenticated: false,
    mfaRequired: false,
    version: '',
    quickQuestions: [],
    syncPoll: null,
};

// --- small helpers ---------------------------------------------------------

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
};

async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: options.body ? { 'Content-Type': 'application/json' } : {},
        credentials: 'same-origin',
        ...options,
    });
    if (response.status === 401) {
        window.location.href = '/login.html';
        throw new Error('Inte inloggad');
    }
    if (!response.ok) {
        let detail = `Fel ${response.status}`;
        try {
            detail = (await response.json()).detail || detail;
        } catch (err) { /* non-JSON error body */ }
        throw new Error(detail);
    }
    const type = response.headers.get('content-type') || '';
    return type.includes('application/json') ? response.json() : response;
}

const post = (path, body) => api(path, { method: 'POST', body: body === undefined ? '{}' : JSON.stringify(body) });

let toastTimer = null;
function toast(message, isError = false) {
    const node = $('toast');
    node.textContent = message;
    node.classList.toggle('error', isError);
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, isError ? 8000 : 4500);
}

// --- dialogs ---------------------------------------------------------------

function openDialog(title, contentNode, buttons = []) {
    $('dialog-title').textContent = title;
    const content = $('dialog-content');
    content.innerHTML = '';
    content.appendChild(contentNode);

    const footer = $('dialog-footer');
    footer.innerHTML = '';
    buttons.forEach((spec) => {
        const button = el('button', `btn${spec.accent ? ' accent' : ''}`, spec.label);
        button.addEventListener('click', () => spec.onClick(closeDialog));
        footer.appendChild(button);
    });
    $('overlay').hidden = false;
}

function closeDialog() {
    $('overlay').hidden = true;
}

function infoDialog(title, message) {
    const wrap = el('div');
    message.split('\n').forEach((line) => wrap.appendChild(el('p', null, line)));
    openDialog(title, wrap, [{ label: 'OK', accent: true, onClick: (close) => close() }]);
}

function confirmDialog(title, message, onConfirm) {
    const wrap = el('div');
    message.split('\n').forEach((line) => wrap.appendChild(el('p', null, line)));
    openDialog(title, wrap, [
        { label: 'Avbryt', onClick: (close) => close() },
        { label: 'Ja', accent: true, onClick: (close) => { close(); onConfirm(); } },
    ]);
}

// --- markdown rendering (same subset the desktop chat window supported) -----

function inlineFormat(text) {
    const escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    return escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
}

function renderMarkdown(text) {
    const lines = (text || '').split('\n');
    const out = [];
    let i = 0;

    while (i < lines.length) {
        const line = lines[i];

        if (line.includes('|') && line.trim().startsWith('|')) {
            const tableLines = [];
            while (i < lines.length && lines[i].includes('|') && lines[i].trim().startsWith('|')) {
                tableLines.push(lines[i]);
                i += 1;
            }
            const rows = tableLines
                .map((row) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim()))
                .filter((cells) => !cells.every((cell) => /^:?-{2,}:?$/.test(cell) || cell === ''));
            if (rows.length) {
                const header = rows.shift();
                out.push('<table><thead><tr>' + header.map((c) => `<th>${inlineFormat(c)}</th>`).join('') + '</tr></thead><tbody>');
                rows.forEach((cells) => {
                    out.push('<tr>' + cells.map((c) => `<td>${inlineFormat(c)}</td>`).join('') + '</tr>');
                });
                out.push('</tbody></table>');
            }
            continue;
        }

        const header = line.match(/^(#{1,4})\s+(.*)$/);
        if (header) {
            out.push(`<h4>${inlineFormat(header[2])}</h4>`);
        } else if (/^\s*[-*]\s+/.test(line)) {
            out.push(`  • ${inlineFormat(line.trim().slice(2))}`);
        } else {
            out.push(inlineFormat(line));
        }
        i += 1;
    }
    return out.join('\n');
}

// --- theme -----------------------------------------------------------------

function applyTheme(dark) {
    state.dark = dark;
    document.body.classList.toggle('dark', dark);
}

async function toggleTheme() {
    applyTheme(!state.dark);
    await post('/api/settings', { values: { dark_mode: state.dark } });
}

// --- dashboard -------------------------------------------------------------

function setRange(days) {
    state.days = days;
    document.querySelectorAll('[data-range]').forEach((button) => {
        button.classList.toggle('accent', Number(button.dataset.range) === days);
    });
    post('/api/settings', { values: { days_range: days } }).catch(() => {});
    refreshViews();
}

function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll('[data-tab]').forEach((button) => {
        button.classList.toggle('accent', button.dataset.tab === tab);
    });
    ['dashboard', 'evolab', 'activities'].forEach((name) => {
        $(`tab-${name}`).hidden = name !== tab;
    });
}

function renderCards(cards) {
    const fitness = $('card-fitness');
    fitness.innerHTML = '';
    fitness.appendChild(el('div', 'big', cards.fitness.value));
    fitness.appendChild(el('div', 'sub', cards.fitness.subtitle));

    const training = $('card-training');
    training.innerHTML = '';
    training.appendChild(el('div', 'headline', cards.training_status.value));
    training.appendChild(el('div', 'sub', cards.training_status.subtitle));

    const recovery = $('card-recovery');
    recovery.innerHTML = '';
    recovery.appendChild(el('div', `big ${cards.recovery.positive ? 'green' : 'amber'}`, cards.recovery.value));
    recovery.appendChild(el('div', 'sub', cards.recovery.subtitle));

    const weight = $('card-weight');
    weight.innerHTML = '';
    if (cards.weight.empty) {
        weight.appendChild(el('div', 'empty', cards.weight.empty));
    } else {
        weight.appendChild(el('div', 'big plain', cards.weight.value));
        weight.appendChild(el('div', 'sub', cards.weight.subtitle));
        weight.appendChild(el('div', 'note', cards.weight.source));
    }

    const calories = $('card-calories');
    calories.innerHTML = '';
    if (cards.calories.empty) {
        calories.appendChild(el('div', 'empty', cards.calories.empty));
        const help = el('div', 'sub');
        help.style.whiteSpace = 'pre-line';
        help.textContent = cards.calories.empty_help;
        calories.appendChild(help);
    } else {
        calories.appendChild(el('div', 'big orange', cards.calories.total));
        calories.appendChild(el('div', 'sub', cards.calories.subtitle));
        calories.appendChild(el('div', 'line', cards.calories.resting));
        calories.appendChild(el('div', 'line', cards.calories.steps));
        calories.appendChild(el('div', 'line', cards.calories.workout));
        if (cards.calories.note) calories.appendChild(el('div', 'note', cards.calories.note));
    }
}

function renderActivities(rows) {
    const body = $('activities-body');
    body.innerHTML = '';
    rows.forEach((row) => {
        const tr = el('tr');
        tr.appendChild(el('td', 'mid', row.date));
        tr.appendChild(el('td', 'mid', row.source));
        tr.appendChild(el('td', null, row.name));
        tr.appendChild(el('td', 'mid', row.type));
        tr.appendChild(el('td', 'num', row.distance));
        tr.appendChild(el('td', 'num', row.duration));
        tr.appendChild(el('td', 'num', String(row.calories)));
        tr.appendChild(el('td', 'num', String(row.hr)));
        body.appendChild(tr);
    });
}

async function refreshViews() {
    try {
        const data = await api(`/api/dashboard?days=${state.days}`);
        renderCards(data.cards);
        renderActivities(data.activities);
        applyStatus(data.status);

        const stamp = Date.now();
        $('chart-weekly').src = `/api/charts/weekly.png?days=${state.days}&t=${stamp}`;
        $('chart-trends').src = `/api/charts/trends.png?days=${state.days}&t=${stamp}`;
        $('chart-evolab').src = `/api/charts/evolab.png?days=${state.days}&t=${stamp}`;
    } catch (error) {
        toast(error.message, true);
    }
}

// --- connection status -----------------------------------------------------

function applyStatus(status) {
    if (!status) return;
    const label = $('status-label');
    label.textContent = status.text;
    label.classList.toggle('error', Boolean(status.is_error));
}

function setAuthenticated(authenticated) {
    state.authenticated = authenticated;
    ['btn-refresh', 'btn-reset', 'btn-save-chat', 'btn-export', 'btn-send'].forEach((id) => {
        $(id).disabled = !authenticated;
    });
    $('message-input').disabled = !authenticated;
    $('btn-connect').textContent = authenticated ? '✅ Connected (Reconnect)' : '▶ Connect to Garmin';
}

async function pollStatus() {
    try {
        const data = await api('/api/status');
        setAuthenticated(data.authenticated);
        applyStatus(data.status);
        $('mfa-card').hidden = !data.mfa_required;
        renderSyncStatus(data.sync_status);
    } catch (error) { /* the periodic poll stays quiet on errors */ }
}

function renderSyncStatus(sync) {
    const node = $('sync-status');
    node.textContent = sync ? sync.text : '';
    node.classList.toggle('done', Boolean(sync && sync.done));

    if (sync && sync.running && !state.syncPoll) {
        state.syncPoll = setInterval(async () => {
            const data = await api('/api/sync/status').catch(() => null);
            if (!data) return;
            applyStatus(data.status);
            const current = data.sync_status;
            $('sync-status').textContent = current.text;
            $('sync-status').classList.toggle('done', Boolean(current.done));
            if (!current.running) {
                clearInterval(state.syncPoll);
                state.syncPoll = null;
                refreshViews();
                setTimeout(() => { $('sync-status').textContent = ''; }, 4000);
            }
        }, 2000);
    }
}

// --- chat ------------------------------------------------------------------

function renderChat(messages) {
    const display = $('chat-display');
    display.innerHTML = '';
    messages.forEach((message) => {
        const kind = message.type || 'user';
        const wrap = el('div', `msg ${kind}`);
        const head = el('div');
        head.appendChild(el('span', 'who', `${message.sender}:`));
        head.appendChild(el('span', 'time', message.timestamp || ''));
        wrap.appendChild(head);
        const text = el('div', 'text');
        text.innerHTML = kind === 'assistant' ? renderMarkdown(message.message) : inlineFormat(message.message);
        wrap.appendChild(text);
        display.appendChild(wrap);
    });
    display.scrollTop = display.scrollHeight;
}

async function sendMessage() {
    const input = $('message-input');
    const message = input.value.trim();
    if (!message) return;
    if (!state.authenticated) {
        toast('❌ Please connect to Garmin first', true);
        return;
    }

    input.value = '';
    input.disabled = true;
    $('btn-send').disabled = true;

    const display = $('chat-display');
    renderChat([...currentMessages, { sender: 'You', message, type: 'user', timestamp: '' }]);
    display.appendChild(el('div', 'msg system', 'HealthChat is thinking...'));
    display.scrollTop = display.scrollHeight;

    try {
        const data = await post('/api/chat', { message });
        currentMessages = data.messages;
        renderChat(currentMessages);
    } catch (error) {
        toast(error.message, true);
        await loadChat();
    } finally {
        input.disabled = !state.authenticated;
        $('btn-send').disabled = !state.authenticated;
        input.focus();
    }
}

let currentMessages = [];

async function loadChat() {
    const data = await api('/api/chat');
    currentMessages = data.messages;
    renderChat(currentMessages);
}

// --- quick questions -------------------------------------------------------

async function loadQuickQuestions() {
    const data = await api('/api/quick-questions');
    state.quickQuestions = data.questions;
    const grid = $('quick-questions');
    grid.innerHTML = '';
    data.questions.forEach((question) => {
        const button = el('button', 'btn quick', question);
        button.addEventListener('click', () => {
            if (!state.authenticated) {
                toast('❌ Please connect to Garmin first', true);
                return;
            }
            $('message-input').value = question;
            sendMessage();
        });
        grid.appendChild(button);
    });
}

// --- panes -----------------------------------------------------------------

function toggleChatPane(force) {
    state.chatVisible = force === undefined ? !state.chatVisible : force;
    $('right-pane').classList.toggle('visible', state.chatVisible);
    const button = $('chat-toggle');
    button.textContent = state.chatVisible ? '🤖 Dölj Coachen' : '💬 Fråga Coachen';
    button.classList.toggle('accent', !state.chatVisible);
}

// --- Settings dialog -------------------------------------------------------

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

function formRow(label, input) {
    const row = el('div', 'form-row');
    const labelNode = el('label', null, label);
    row.appendChild(labelNode);
    row.appendChild(input);
    return row;
}

function textInput(id, value, type = 'text', placeholder = '') {
    const input = document.createElement('input');
    input.type = type;
    input.id = id;
    input.value = value === undefined || value === null ? '' : value;
    if (placeholder) input.placeholder = placeholder;
    return input;
}

async function openSettings() {
    const data = await api('/api/settings');
    const config = data.config;
    const secrets = config.secrets_set || {};
    const wrap = el('div');

    // --- AI provider
    wrap.appendChild(el('div', 'form-section', '🤖 AI-leverantör'));
    const providerSelect = document.createElement('select');
    providerSelect.id = 'ai_provider';
    Object.entries(data.providers).forEach(([key, meta]) => {
        const option = document.createElement('option');
        option.value = key;
        option.textContent = meta.name;
        option.selected = key === config.ai_provider;
        providerSelect.appendChild(option);
    });
    wrap.appendChild(formRow('Leverantör', providerSelect));

    const providerFields = el('div');
    wrap.appendChild(providerFields);

    function renderProviderFields() {
        const provider = providerSelect.value;
        providerFields.innerHTML = '';
        (PROVIDER_FIELDS[provider] || []).forEach(([key, label, type]) => {
            if (type === 'model') {
                const select = document.createElement('select');
                select.id = key;
                const current = config[key] || '';
                const models = (data.providers[provider] && data.providers[provider].models) || [];
                const options = models.includes(current) || !current ? models : [current, ...models];
                options.forEach((model) => {
                    const option = document.createElement('option');
                    option.value = model;
                    option.textContent = model;
                    option.selected = model === current;
                    select.appendChild(option);
                });
                providerFields.appendChild(formRow(label, select));

                // Ask the provider for its live model list; fall back silently.
                api(`/api/settings/models?provider=${provider}`).then((result) => {
                    if (!result.models || !result.models.length) return;
                    const value = select.value;
                    select.innerHTML = '';
                    result.models.forEach((model) => {
                        const option = document.createElement('option');
                        option.value = model;
                        option.textContent = model;
                        option.selected = model === value;
                        select.appendChild(option);
                    });
                }).catch(() => {});
            } else if (type === 'password') {
                const input = textInput(key, '', 'password', secrets[key] ? '•••••• (sparad — lämna tom för att behålla)' : '');
                providerFields.appendChild(formRow(label, input));
            } else {
                providerFields.appendChild(formRow(label, textInput(key, config[key], 'text')));
            }
        });
    }

    providerSelect.addEventListener('change', renderProviderFields);
    renderProviderFields();

    // --- Garmin
    wrap.appendChild(el('div', 'form-section', '⌚ Garmin Connect'));
    wrap.appendChild(formRow('E-post', textInput('garmin_email', config.garmin_email, 'email')));
    wrap.appendChild(formRow('Lösenord', textInput('garmin_password', '', 'password',
        secrets.garmin_password ? '•••••• (sparat — lämna tomt för att behålla)' : '')));

    // --- Profile (drives the calorie estimate)
    wrap.appendChild(el('div', 'form-section', '👤 Profil (för kaloriberäkning)'));
    const sexSelect = document.createElement('select');
    sexSelect.id = 'user_sex';
    [['male', 'Man'], ['female', 'Kvinna']].forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        option.selected = config.user_sex === value;
        sexSelect.appendChild(option);
    });
    wrap.appendChild(formRow('Kön', sexSelect));
    wrap.appendChild(formRow('Längd (cm)', textInput('user_height_cm', config.user_height_cm || '', 'number')));
    wrap.appendChild(formRow('Ålder (år)', textInput('user_age', config.user_age || '', 'number')));
    wrap.appendChild(formRow('Vikt (kg, valfritt)', textInput('user_weight_kg', config.user_weight_kg || '', 'number')));

    // --- Other sources
    wrap.appendChild(el('div', 'form-section', '🔗 Övriga källor'));
    [['fitbit', 'Fitbit'], ['strava', 'Strava'], ['withings', 'Withings']].forEach(([key, label]) => {
        wrap.appendChild(formRow(`${label} Client ID`, textInput(`${key}_client_id`, config[`${key}_client_id`])));
        wrap.appendChild(formRow(`${label} Client Secret`, textInput(`${key}_client_secret`, '', 'password',
            secrets[`${key}_client_secret`] ? '•••••• (sparad)' : '')));
        const row = el('div', 'form-row');
        row.appendChild(el('label', null, ''));
        const buttons = el('div');
        const connectBtn = el('button', 'btn', data.sources[key] ? `✅ ${label} ansluten — anslut igen` : `▶ Anslut till ${label}`);
        connectBtn.addEventListener('click', async () => {
            await saveSettings(false);
            connectSource(key);
        });
        buttons.appendChild(connectBtn);
        row.appendChild(buttons);
        wrap.appendChild(row);
    });

    const hint = el('div', 'hint',
        `Redirect-URL att registrera hos varje tjänst: ${window.location.origin}/oauth/<tjänst>/callback`);
    wrap.appendChild(hint);

    // --- Misc
    wrap.appendChild(el('div', 'form-section', '⚙️ Övrigt'));
    const autoLogin = textInput('auto_login', '', 'checkbox');
    autoLogin.checked = Boolean(config.auto_login);
    wrap.appendChild(formRow('Anslut automatiskt till Garmin', autoLogin));

    openDialog('⚙️ Inställningar', wrap, [
        { label: 'Avbryt', onClick: (close) => close() },
        { label: 'Spara', accent: true, onClick: async (close) => { await saveSettings(true); close(); } },
    ]);
}

async function saveSettings(notify) {
    const values = {};
    const provider = $('ai_provider').value;
    values.ai_provider = provider;

    (PROVIDER_FIELDS[provider] || []).forEach(([key]) => {
        const node = $(key);
        if (node) values[key] = node.value;
    });

    ['garmin_email', 'garmin_password', 'user_sex',
     'fitbit_client_id', 'fitbit_client_secret',
     'strava_client_id', 'strava_client_secret',
     'withings_client_id', 'withings_client_secret'].forEach((key) => {
        const node = $(key);
        if (node) values[key] = node.value;
    });

    ['user_height_cm', 'user_age', 'user_weight_kg'].forEach((key) => {
        const node = $(key);
        if (node) values[key] = Number(node.value || 0);
    });

    values.auto_login = $('auto_login').checked;

    await post('/api/settings', { values });
    if (notify) {
        toast('✅ Inställningarna sparades.');
        pollStatus();
    }
}

async function connectSource(provider) {
    try {
        const data = await api(`/api/connect/${provider}/url`);
        window.open(data.url, '_blank', 'noopener');
        infoDialog(`${provider.charAt(0).toUpperCase() + provider.slice(1)} inloggning`,
            'Öppnar auktoriseringssidan i en ny flik.\n\n'
            + '1. Logga in och godkänn behörigheterna.\n'
            + '2. Appen tar emot koden och genomför anslutningen automatiskt!\n\n'
            + `Redirect-URL: ${data.redirect_uri}`);
    } catch (error) {
        toast(error.message, true);
    }
}

// --- Saved prompts ---------------------------------------------------------

async function openPrompts() {
    const data = await api('/api/prompts');
    const wrap = el('div');
    const list = el('div', 'list');
    let selected = -1;

    const nameInput = textInput('prompt-name', '', 'text', 'Namn');
    const textArea = document.createElement('textarea');
    textArea.rows = 8;
    textArea.style.width = '100%';

    function renderList() {
        list.innerHTML = '';
        data.prompts.forEach((prompt, index) => {
            const item = el('div', `item${index === selected ? ' selected' : ''}`);
            item.appendChild(el('div', null, prompt.name));
            item.appendChild(el('div', 'meta', (prompt.prompt || '').slice(0, 90)));
            item.addEventListener('click', () => {
                selected = index;
                nameInput.value = prompt.name;
                textArea.value = prompt.prompt;
                renderList();
            });
            list.appendChild(item);
        });
        if (!data.prompts.length) list.appendChild(el('div', 'item', 'Inga sparade promptar än.'));
    }
    renderList();

    wrap.appendChild(list);
    wrap.appendChild(el('div', 'form-section', 'Redigera'));
    wrap.appendChild(formRow('Namn', nameInput));
    wrap.appendChild(textArea);

    openDialog('📝 Sparade Promptar', wrap, [
        {
            label: '🗑 Ta bort',
            onClick: async () => {
                if (selected < 0) return;
                const result = await api(`/api/prompts/${selected}`, { method: 'DELETE' });
                data.prompts = result.prompts;
                selected = -1;
                nameInput.value = '';
                textArea.value = '';
                renderList();
            },
        },
        {
            label: '💾 Spara',
            onClick: async () => {
                const payload = { name: nameInput.value.trim() || 'Prompt', prompt: textArea.value };
                const result = selected >= 0
                    ? await api(`/api/prompts/${selected}`, { method: 'PUT', body: JSON.stringify(payload) })
                    : await post('/api/prompts', payload);
                data.prompts = result.prompts;
                renderList();
                toast('✅ Prompten sparades.');
            },
        },
        {
            label: '▶ Använd',
            accent: true,
            onClick: (close) => {
                if (selected < 0) return;
                $('message-input').value = data.prompts[selected].prompt;
                toggleChatPane(true);
                close();
            },
        },
        { label: 'Stäng', onClick: (close) => close() },
    ]);
}

// --- Chat history ----------------------------------------------------------

async function openHistory() {
    const data = await api('/api/chats');
    const wrap = el('div');
    const list = el('div', 'list');
    const preview = el('div');
    preview.style.marginTop = '14px';
    preview.style.maxHeight = '260px';
    preview.style.overflowY = 'auto';
    let selected = null;

    function renderList() {
        list.innerHTML = '';
        data.chats.forEach((chat) => {
            const item = el('div', `item${selected === chat.id ? ' selected' : ''}`);
            item.appendChild(el('div', null, chat.name));
            item.appendChild(el('div', 'meta', `${chat.message_count} meddelanden · ${chat.saved_at}`));
            item.addEventListener('click', async () => {
                selected = chat.id;
                renderList();
                const detail = await api(`/api/chats/${chat.id}`);
                preview.innerHTML = '';
                (detail.chat.messages || []).forEach((message) => {
                    const node = el('div', 'msg');
                    node.appendChild(el('div', 'who', `${message.sender}:`));
                    const text = el('div', 'text');
                    text.innerHTML = renderMarkdown(message.message);
                    node.appendChild(text);
                    preview.appendChild(node);
                });
            });
            list.appendChild(item);
        });
        if (!data.chats.length) list.appendChild(el('div', 'item', 'Inga sparade chattar än.'));
    }
    renderList();

    wrap.appendChild(list);
    wrap.appendChild(preview);

    openDialog('📂 Chat-historik', wrap, [
        {
            label: '✏️ Byt namn',
            onClick: async () => {
                if (!selected) return;
                const name = window.prompt('Nytt namn:', '');
                if (!name) return;
                const result = await api(`/api/chats/${selected}`, { method: 'PUT', body: JSON.stringify({ name }) });
                data.chats = result.chats;
                renderList();
            },
        },
        {
            label: '🗑 Ta bort',
            onClick: async () => {
                if (!selected) return;
                const result = await api(`/api/chats/${selected}`, { method: 'DELETE' });
                data.chats = result.chats;
                selected = null;
                preview.innerHTML = '';
                renderList();
            },
        },
        {
            label: '📥 Ladda in',
            accent: true,
            onClick: async (close) => {
                if (!selected) return;
                const result = await post(`/api/chats/${selected}/load`);
                currentMessages = result.messages;
                renderChat(currentMessages);
                toggleChatPane(true);
                close();
            },
        },
        { label: 'Stäng', onClick: (close) => close() },
    ]);
}

async function saveChatDialog() {
    const wrap = el('div');
    const input = textInput('chat-name', '', 'text', 'Namn på chatten');
    wrap.appendChild(formRow('Session Name:', input));
    openDialog('💾 Save Chat Session', wrap, [
        { label: 'Avbryt', onClick: (close) => close() },
        {
            label: 'Spara',
            accent: true,
            onClick: async (close) => {
                try {
                    await post('/api/chats', { name: input.value || 'Chat' });
                    toast('✅ Chatten sparades.');
                    close();
                } catch (error) {
                    toast(error.message, true);
                }
            },
        },
    ]);
}

// --- Search ----------------------------------------------------------------

function openSearch() {
    const wrap = el('div');
    const input = textInput('search-q', '', 'text', 'Sök i chatthistoriken...');
    input.style.width = '100%';
    const results = el('div', 'list');
    results.style.marginTop = '12px';
    wrap.appendChild(input);
    wrap.appendChild(results);

    async function run() {
        const query = input.value.trim();
        if (!query) return;
        const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
        results.innerHTML = '';
        data.results.forEach((hit) => {
            const item = el('div', 'item');
            item.appendChild(el('div', null, `${hit.sender}: ${(hit.message || '').slice(0, 160)}`));
            item.appendChild(el('div', 'meta', `${hit.chat} · ${hit.timestamp || ''}`));
            results.appendChild(item);
        });
        if (!data.results.length) results.appendChild(el('div', 'item', 'Inga träffar.'));
    }

    input.addEventListener('keydown', (event) => { if (event.key === 'Enter') run(); });
    openDialog('🔍 Sök i Chatthistorik', wrap, [
        { label: 'Sök', accent: true, onClick: run },
        { label: 'Stäng', onClick: (close) => close() },
    ]);
    setTimeout(() => input.focus(), 50);
}

// --- Export ----------------------------------------------------------------

function openExport() {
    const wrap = el('div');
    const format = document.createElement('select');
    [['pdf', 'PDF'], ['docx', 'Word (DOCX)'], ['txt', 'Text (TXT)']].forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        format.appendChild(option);
    });
    wrap.appendChild(formRow('Format', format));

    const timestamps = textInput('exp-ts', '', 'checkbox');
    timestamps.checked = true;
    wrap.appendChild(formRow('Inkludera tidsstämplar', timestamps));

    const system = textInput('exp-sys', '', 'checkbox');
    wrap.appendChild(formRow('Inkludera systemmeddelanden', system));

    openDialog('📄 Export Report', wrap, [
        { label: 'Avbryt', onClick: (close) => close() },
        {
            label: 'Exportera',
            accent: true,
            onClick: async (close) => {
                try {
                    const response = await fetch('/api/export', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            format: format.value,
                            include_timestamp: timestamps.checked,
                            include_system: system.checked,
                        }),
                    });
                    if (!response.ok) throw new Error((await response.json()).detail || 'Export misslyckades');
                    const blob = await response.blob();
                    const url = URL.createObjectURL(blob);
                    const link = document.createElement('a');
                    link.href = url;
                    link.download = `healthchat_report.${format.value}`;
                    link.click();
                    URL.revokeObjectURL(url);
                    close();
                } catch (error) {
                    toast(error.message, true);
                }
            },
        },
    ]);
}

// --- Customize quick questions ---------------------------------------------

async function openCustomizeQuestions() {
    const data = await api('/api/quick-questions');
    const wrap = el('div');
    const inputs = [];
    for (let i = 0; i < 8; i += 1) {
        const input = textInput(`qq-${i}`, data.questions[i] || '', 'text');
        inputs.push(input);
        wrap.appendChild(formRow(`Fråga ${i + 1}`, input));
    }
    openDialog('⚙️ Anpassa snabbfrågor', wrap, [
        { label: 'Avbryt', onClick: (close) => close() },
        {
            label: 'Spara',
            accent: true,
            onClick: async (close) => {
                await post('/api/quick-questions', { questions: inputs.map((input) => input.value) });
                await loadQuickQuestions();
                close();
            },
        },
    ]);
}

// --- Account ---------------------------------------------------------------

function openAccount(user) {
    const wrap = el('div');
    wrap.appendChild(el('div', 'form-section', `Inloggad som ${user.email}`));
    const current = textInput('pw-current', '', 'password');
    const next = textInput('pw-new', '', 'password');
    wrap.appendChild(formRow('Nuvarande lösenord', current));
    wrap.appendChild(formRow('Nytt lösenord', next));
    wrap.appendChild(el('div', 'hint', 'Alla inloggade enheter loggas ut när lösenordet ändras.'));

    openDialog('👤 Konto', wrap, [
        {
            label: '🗑 Radera konto',
            onClick: () => {
                confirmDialog('Radera konto',
                    'All din hälsodata, chatthistorik och dina nycklar raderas permanent.\nVill du fortsätta?',
                    async () => {
                        const password = window.prompt('Bekräfta med ditt lösenord:');
                        if (!password) return;
                        try {
                            await post('/api/auth/delete-account', { password });
                            window.location.href = '/login.html';
                        } catch (error) {
                            toast(error.message, true);
                        }
                    });
            },
        },
        {
            label: 'Byt lösenord',
            accent: true,
            onClick: async () => {
                try {
                    await post('/api/auth/password', {
                        current_password: current.value,
                        new_password: next.value,
                    });
                    window.location.href = '/login.html';
                } catch (error) {
                    toast(error.message, true);
                }
            },
        },
        { label: 'Stäng', onClick: (close) => close() },
    ]);
}

// --- File import -----------------------------------------------------------

function importFile(source) {
    const input = $('file-input');
    input.value = '';
    input.onchange = async () => {
        if (!input.files.length) return;
        const form = new FormData();
        form.append('file', input.files[0]);
        try {
            toast(`⏳ Importerar ${source}-fil...`);
            const response = await fetch(`/api/import/${source}`, {
                method: 'POST',
                credentials: 'same-origin',
                body: form,
            });
            if (!response.ok) throw new Error((await response.json()).detail || 'Importen misslyckades');
            const data = await response.json();
            toast(`✅ Import klar: ${JSON.stringify(data.result)}`);
            refreshViews();
        } catch (error) {
            toast(error.message, true);
        }
    };
    input.click();
}

// --- actions ---------------------------------------------------------------

async function connectGarmin() {
    const button = $('btn-connect');
    button.disabled = true;
    button.textContent = 'Connecting...';
    applyStatus({ text: 'Connecting to Garmin...', is_error: false });
    try {
        const data = await post('/api/garmin/connect');
        applyStatus(data.status);
        $('mfa-card').hidden = !data.mfa_required;
        setAuthenticated(data.authenticated);
        if (data.authenticated) {
            await loadChat();
            refreshViews();
        } else if (data.mfa_required) {
            $('mfa-code').focus();
        }
    } catch (error) {
        applyStatus({ text: `❌ ${error.message}`, is_error: true });
        infoDialog('Garmin Connection Error', `Could not connect to Garmin Connect:\n\n${error.message}`);
    } finally {
        button.disabled = false;
        if (!state.authenticated) button.textContent = '▶ Connect to Garmin';
    }
}

async function submitMfa() {
    const code = $('mfa-code').value.trim();
    if (code.length !== 6) {
        applyStatus({ text: '❌ Please enter a valid 6-digit MFA code', is_error: true });
        return;
    }
    try {
        const data = await post('/api/garmin/mfa', { code });
        applyStatus(data.status);
        $('mfa-card').hidden = true;
        setAuthenticated(true);
        await loadChat();
        refreshViews();
    } catch (error) {
        applyStatus({ text: `❌ ${error.message}`, is_error: true });
    }
}

async function runCheckin(full) {
    try {
        const data = await post('/api/checkin', { days: state.days, full });
        if (data.started) {
            renderSyncStatus(data.sync_status);
        }
    } catch (error) {
        infoDialog('Inga Källor Anslutna', error.message);
    }
}

const ACTIONS = {
    'toggle-chat': () => toggleChatPane(),
    'toggle-theme': toggleTheme,
    'refresh-views': refreshViews,
    settings: openSettings,
    prompts: openPrompts,
    history: openHistory,
    search: openSearch,
    export: openExport,
    'save-chat': saveChatDialog,
    'customize-questions': openCustomizeQuestions,
    'connect-garmin': connectGarmin,
    'submit-mfa': submitMfa,
    checkin: () => runCheckin(false),
    'full-sync': () => confirmDialog('Synkronisera Full Historik',
        'Vill du synka och skriva över databasen med full historik från start för alla anslutna källor?\n'
        + 'Detta hämtar all tillgänglig hälsodata från ditt konto.',
        () => runCheckin(true)),
    refresh: async () => {
        try {
            await post('/api/refresh');
            toast('✅ Data refreshed successfully!');
            refreshViews();
        } catch (error) {
            toast(error.message, true);
        }
    },
    'reset-chat': async () => {
        const data = await post('/api/chat/reset');
        currentMessages = data.messages;
        renderChat(currentMessages);
    },
    send: sendMessage,
    'connect-fitbit': () => connectSource('fitbit'),
    'connect-strava': () => connectSource('strava'),
    'connect-withings': () => connectSource('withings'),
    'import-fitbit': () => importFile('fitbit'),
    'import-strava': () => importFile('strava'),
    'import-withings': () => importFile('withings'),
    account: () => openAccount(state.user),
    about: () => infoDialog('Om HealthChat', `HealthChat v${state.version}\n\n`
        + 'En AI-assistent för analys av Garmin Connect-hälsodata.\n'
        + '• Serverdatabas per användare för hälsodata & historik\n'
        + '• Interaktiva grafer för sömn, stress, Body Battery & träning\n'
        + '• Data lagras hos din egen server — inte hos någon tredje part'),
    logout: async () => {
        await post('/api/auth/logout');
        window.location.href = '/login.html';
    },
};

// --- wiring ----------------------------------------------------------------

function wireMenus() {
    document.querySelectorAll('[data-menu]').forEach((menu) => {
        menu.querySelector('button').addEventListener('click', (event) => {
            event.stopPropagation();
            const wasOpen = menu.classList.contains('open');
            document.querySelectorAll('[data-menu]').forEach((other) => other.classList.remove('open'));
            menu.classList.toggle('open', !wasOpen);
        });
    });
    document.addEventListener('click', () => {
        document.querySelectorAll('[data-menu]').forEach((menu) => menu.classList.remove('open'));
    });
}

function wireActions() {
    document.addEventListener('click', (event) => {
        const target = event.target.closest('[data-action]');
        if (!target) return;
        const action = ACTIONS[target.dataset.action];
        if (action) {
            event.preventDefault();
            action();
        }
    });

    document.querySelectorAll('[data-range]').forEach((button) => {
        button.addEventListener('click', () => setRange(Number(button.dataset.range)));
    });
    document.querySelectorAll('[data-tab]').forEach((button) => {
        button.addEventListener('click', () => switchTab(button.dataset.tab));
    });

    // Ctrl+Enter sends, Enter makes a new line — same as the desktop input box.
    $('message-input').addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            sendMessage();
        }
    });
    $('mfa-code').addEventListener('keydown', (event) => {
        if (event.key === 'Enter') submitMfa();
    });
    $('overlay').addEventListener('click', (event) => {
        if (event.target === $('overlay')) closeDialog();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !$('overlay').hidden) closeDialog();
    });
}

async function init() {
    wireMenus();
    wireActions();

    const status = await api('/api/auth/status');
    if (!status.authenticated) {
        window.location.href = '/login.html';
        return;
    }
    state.user = status.user;
    state.version = status.version;
    $('version-label').textContent = `v${status.version}`;
    $('account-label').textContent = status.user.email;

    const settings = await api('/api/settings');
    applyTheme(Boolean(settings.config.dark_mode));
    setRange(Number(settings.config.days_range) || 30);

    await Promise.all([loadChat(), loadQuickQuestions(), pollStatus()]);
    setInterval(pollStatus, 15000);
}

init().catch((error) => toast(error.message, true));
