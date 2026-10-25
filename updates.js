'use strict';
// Update prompt: the collector checks GitHub for a newer release (GET /api/update); this shows it once per page
// load, saves "Not now" and the "Notify me" checkbox on the collector, and follows an update until the new version answers.
const update = {status:null, shown:null, target:null, started:0};
const UPDATE_POLL_MS = 1000, UPDATE_GIVE_UP_MS = 180000;
const updateRunning = ['starting','downloading','verifying','installing','restarting'];
async function updateRequest(path, body) {
  const options = body === undefined ? {cache:'no-store'} : {method:'POST', cache:'no-store', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
  const response = await fetch(path, options);
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  return response.json();
}
async function loadUpdate() {
  try {renderUpdate(await updateRequest('/api/update'));} catch {}
}
function showUpdate(latest) {
  $('updateTitle').textContent = `Token Observatory ${latest.version} is available`;
  $('updateText').textContent = `A new version is available (you have ${update.status.current}). Update now downloads it from GitHub, checks it against the release checksums, installs it and restarts the dashboard.`;
  $('updateNotes').textContent = latest.notes || '';
  $('updateLink').href = latest.url;
  $('updateNotify').checked = update.status.notify;
  $('updateProgress').textContent = '';
  $('updateNow').disabled = $('updateLater').disabled = false;
  update.shown = latest.version;
  $('updateDialog').showModal();
}
function renderUpdate(status) {
  update.status = status;
  const latest = status.latest, notice = $('updateNotice');
  notice.hidden = status.notify && !latest || status.checks === false;
  notice.textContent = !status.notify ? 'Update notifications off · Turn on' : latest ? `Version ${latest.version} available · Update` : '';
  if(status.prompt && latest && update.shown !== latest.version && !update.target)showUpdate(latest);
}
async function saveUpdateSettings(settings) {
  try {renderUpdate(await updateRequest('/api/update/settings', settings));}
  catch(error) {$('updateProgress').textContent = `Could not save the setting: ${error.message}`;}
}
async function notNow() {
  const version = update.status?.latest?.version;
  $('updateDialog').close();
  if(version)await saveUpdateSettings({dismiss:version, notify:$('updateNotify').checked});
}
async function noticeClicked() {
  if(!update.status)return;
  if(!update.status.notify)await saveUpdateSettings({notify:true});
  else if(update.status.latest)showUpdate(update.status.latest);
}
function updateProgress(status) {
  const progress = status.progress || {}, line = $('updateProgress');
  if(update.target && status.current === update.target) {
    line.textContent = `Updated to ${update.target}. Reloading…`;
    location.reload();
    return;
  }
  line.className = 'update-progress' + (progress.state === 'failed' ? ' failed' : '');
  if(progress.message)line.textContent = progress.message;
  if(updateRunning.includes(progress.state) || progress.state === 'idle' && update.target) {
    setTimeout(pollUpdate, UPDATE_POLL_MS);
    return;
  }
  update.target = null;
  $('updateLater').disabled = false;
  $('updateNow').disabled = progress.state === 'manual';
}
async function pollUpdate() {
  if(Date.now() - update.started > UPDATE_GIVE_UP_MS) {
    $('updateProgress').textContent = 'Token Observatory has not come back yet. Open it again, then reload this page.';
    update.target = null;$('updateLater').disabled = false;
    return;
  }
  try {updateProgress(await updateRequest('/api/update'));}
  catch {$('updateProgress').textContent = 'Restarting Token Observatory…';setTimeout(pollUpdate, UPDATE_POLL_MS);}
}
async function installUpdate() {
  const latest = update.status?.latest;
  if(!latest || update.target)return;
  update.target = latest.version;update.started = Date.now();
  $('updateNow').disabled = $('updateLater').disabled = true;
  $('updateProgress').textContent = 'Starting update…';
  try {
    await updateRequest('/api/update/settings', {notify:$('updateNotify').checked});
    updateProgress(await updateRequest('/api/update/install', {}));
  } catch(error) {
    update.target = null;
    $('updateProgress').textContent = `Update failed: ${error.message}`;
    $('updateNow').disabled = $('updateLater').disabled = false;
  }
}
$('updateLater').addEventListener('click', notNow);
$('updateNow').addEventListener('click', installUpdate);
$('updateNotice').addEventListener('click', noticeClicked);
loadUpdate();
setInterval(loadUpdate, 3600000);
