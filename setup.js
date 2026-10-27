'use strict';
// Provider settings and first-run setup: choose which tools to track and connect local LLM servers.
const providerSetup = {status:null, firstRun:false, shown:false, saving:false};
const LOCAL_HELP = {
  ollama: (listen, target) => `<ol><li>Start Ollama as usual (it listens on port ${target}).</li><li>Point your apps at <code>http://127.0.0.1:${listen}</code> instead of port ${target}: in Open WebUI, Continue, Cline and similar, set the Ollama URL to it.</li><li>For the <code>ollama</code> command, run it as <code>OLLAMA_HOST=127.0.0.1:${listen} ollama run llama3.2</code>.</li></ol>`,
  lmstudio: (listen, target) => `<ol><li>In LM Studio, open the Developer tab and start the server (port ${target}).</li><li>In your apps, use the OpenAI-compatible base URL <code>http://127.0.0.1:${listen}/v1</code> instead of port ${target}.</li></ol>`,
  llamacpp: (listen, target) => `<ol><li>Start <code>llama-server -m your-model.gguf --port ${target}</code>.</li><li>In your apps, use the base URL <code>http://127.0.0.1:${listen}/v1</code> instead of port ${target}.</li></ol>`,
};

async function loadProviders() {
  const response = await fetch('/api/providers', {cache:'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  providerSetup.status = await response.json();
  return providerSetup.status;
}

function localStatus(tool, info) {
  if (info.error) return `<span class="provider-state bad">${escapeHTML(info.error)}</span>`;
  const proxy = info.listening ? `Counting on port ${info.listen}` : 'Starts when you save';
  const server = info.server_up ? `${escapeHTML(providerName(tool))} is answering on port ${info.target}` : `${escapeHTML(providerName(tool))} isn't running on port ${info.target} right now`;
  return `<span class="provider-state ${info.server_up ? 'good' : ''}">${proxy} · ${server}</span>`;
}

function providerRow(name, status) {
  const local = status.local[name];
  const checked = status.enabled.includes(name);
  const found = status.detected[name];
  const detail = local
    ? `${localStatus(name, local)}<details${checked && providerSetup.firstRun ? ' open' : ''}><summary>How to connect</summary>${LOCAL_HELP[name](local.listen, local.target)}<div class="port-fields"><label>Listen on <input type="number" min="1" max="65535" data-port="${name}:listen" value="${local.listen}"></label><label>${escapeHTML(providerName(name))} port <input type="number" min="1" max="65535" data-port="${name}:target" value="${local.target}"></label></div></details>`
    : `<span class="provider-state">${name === 'claude' ? 'Reads Claude Code logs in ~/.claude' : 'Reads Codex logs in ~/.codex'}</span>`;
  return `<div class="provider-row${checked ? ' on' : ''}"><label class="provider-toggle"><input type="checkbox" data-enable="${name}"${checked ? ' checked' : ''}><span class="provider-icon ${name}">${providerIcon(name)}</span><strong>${escapeHTML(providerName(name))}</strong><small>${found ? `Found: ${escapeHTML(found)}` : 'Not found on this computer'}</small></label>${detail}</div>`;
}

function renderProviders() {
  const status = providerSetup.status;
  if (!status) return;
  // First run preselects what was found, so one click on Save is enough for most people.
  if (providerSetup.firstRun) status.enabled = Object.keys(status.names).filter(p => status.detected[p]);
  $('providersTitle').textContent = providerSetup.firstRun ? 'Welcome to Token Observatory' : 'Providers';
  $('providersIntro').innerHTML = providerSetup.firstRun
    ? 'Choose the AI tools you use. Everything is tracked on this computer only, and you can change it later under <strong>Providers</strong>. Tools we found are already ticked.'
    : 'Turn tracking on or off for each tool. Local LLM servers keep no token counts of their own, so Token Observatory counts them on a second port that passes every request through unchanged. Each chat is named by the start of its first message; nothing else from prompts or replies is saved.';
  $('providerList').innerHTML = `<h3>Cloud coding tools</h3>${status.cloud.map(p => providerRow(p, status)).join('')}<h3>Local LLMs</h3>${Object.keys(status.local).map(p => providerRow(p, status)).join('')}`;
  $('providersSave').textContent = providerSetup.firstRun ? 'Save and start' : 'Save';
  $('closeProviders').setAttribute('aria-label', providerSetup.firstRun ? 'Set up later' : 'Close providers');
}

async function openProviders(firstRun = false) {
  providerSetup.firstRun = firstRun;
  $('providersStatus').textContent = 'Looking for installed tools…';
  if (!$('providersDialog').open) $('providersDialog').showModal();
  try {
    await loadProviders();
    $('providersStatus').textContent = '';
    renderProviders();
  } catch (error) {
    $('providersStatus').textContent = `Could not read provider settings: ${error.message}`;
  }
}

function providerChoices() {
  const enabled = {}, ports = {};
  document.querySelectorAll('[data-enable]').forEach(box => { enabled[box.dataset.enable] = box.checked; });
  document.querySelectorAll('[data-port]').forEach(input => {
    const [tool, key] = input.dataset.port.split(':');
    (ports[tool] = ports[tool] || {})[key] = Number(input.value);
  });
  return {enabled, ports, setup_done:true};
}

async function saveProviders() {
  if (providerSetup.saving) return;
  const choice = providerChoices();
  if (!Object.values(choice.enabled).some(Boolean)) { $('providersStatus').textContent = 'Pick at least one tool to track.'; return; }
  providerSetup.saving = true; $('providersSave').disabled = true; $('providersStatus').textContent = 'Saving…';
  try {
    const response = await fetch('/api/providers', {method:'POST', cache:'no-store', headers:{'Content-Type':'application/json'}, body:JSON.stringify(choice)});
    if (!response.ok) throw new Error((await response.text()).match(/<p>Message: ([^<]*)/)?.[1] || `HTTP ${response.status}`);
    providerSetup.status = await response.json();
    providerSetup.firstRun = false;
    renderProviders();
    const problems = Object.entries(providerSetup.status.local).filter(([tool, info]) => providerSetup.status.enabled.includes(tool) && info.error);
    const message = problems.length ? `Saved, but ${problems.map(([tool, info]) => `${providerName(tool)}: ${info.error}`).join('; ')}` : 'Provider settings saved.';
    $('providersStatus').textContent = '';
    $('providersDialog').close();
    showToast(message, problems.length > 0);
    if (state.data) state.data.providers = {enabled:providerSetup.status.enabled, setup_done:true};
    refresh();
  } catch (error) {
    $('providersStatus').textContent = `Could not save: ${error.message}`;
  } finally { providerSetup.saving = false; $('providersSave').disabled = false; }
}

// A short notice at the bottom of the page after the dialog closes.
function showToast(message, warn = false) {
  const toast = $('toast');
  toast.textContent = message;
  toast.className = `toast show${warn ? ' warn' : ''}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.className = 'toast'; }, warn ? 8000 : 3000);
}

// The first live snapshot says whether setup ever ran; ask once per visit until it has.
function maybeStartSetup() {
  if (providerSetup.shown || state.history || !state.data?.providers || state.data.providers.setup_done) return;
  providerSetup.shown = true;
  openProviders(true);
}

$('providersButton').addEventListener('click', () => openProviders(false));
$('closeProviders').addEventListener('click', () => $('providersDialog').close());
$('providersCheck').addEventListener('click', () => openProviders(providerSetup.firstRun));
$('providersSave').addEventListener('click', saveProviders);
$('providerList').addEventListener('change', event => {
  const box = event.target.closest?.('[data-enable]');
  if (box) box.closest('.provider-row').classList.toggle('on', box.checked);
});
setInterval(maybeStartSetup, 1000);
