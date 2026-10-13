'use strict';
const $ = id => document.getElementById(id);
let selected = null, meeting = null, meetings = [], audioDevices = null;
let activeTab = 'transcript', editing = false, refreshRunning = false, lastSignature = '', lastFetch = Date.now();
const STATUS_LABEL = { ready: 'CHƯA GHI', recording: '● ĐANG GHI', paused: 'Ⅱ TẠM DỪNG', finished: '✓ ĐÃ KẾT THÚC', interrupted: '⚠ GIÁN ĐOẠN', imported: '✓ ĐÃ NHẬP' };
const $toast = $('toast');
function esc(x) { return String(x ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function hms(s) { s = Math.max(0, Math.floor(+s || 0)); return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map(n => String(n).padStart(2, '0')).join(':'); }
function dmy(x) { if (!x) return '—'; const d = new Date(x); return isNaN(d.getTime()) ? x.substring(0, 10) : d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' }); }
function notice(text, kind = '') { const el = $('globalNotice'); el.textContent = text; el.className = 'notice' + (kind ? ' ' + kind : '') + (!text ? ' hidden' : ''); }
function toast(text, error = false) { $toast.textContent = text; $toast.className = 'toast' + (error ? ' error' : ''); clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => $toast.classList.add('hidden'), error ? 7000 : 4800); }
async function req(path, opts = {}) {
  const init = { ...opts };
  if (opts.body && typeof opts.body !== 'string' && !(opts.body instanceof FormData)) { init.body = JSON.stringify(opts.body); init.headers = { ...opts.headers, 'Content-Type': 'application/json' }; }
  let r; try { r = await fetch('/api' + path, init); } catch (e) { throw new Error('Không kết nối được bộ xử lý (cửa sổ START_WINDOWS.bat còn mở không?): ' + e.message); }
  let v; try { v = await r.json(); } catch { v = {}; }
  if (!r.ok) throw new Error(typeof v.detail === 'string' ? v.detail : ('Lỗi HTTP ' + r.status));
  return v;
}
function fail(e) { console.error(e); toast(e.message || String(e), true); }
function confirmBox(title, message, onConfirm, confirmLabel = 'Xác nhận') {
  $('dialogConfirm').textContent = confirmLabel; $('dialogTitle').textContent = title; $('dialogMessage').textContent = message; $('dialog').showModal();
  $('dialogConfirm').onclick = async () => { $('dialog').close(); try { await onConfirm(); } catch (e) { fail(e); } };
}

async function listAll() {
  meetings = await req('/meetings');
  const root = $('meetingList');
  root.innerHTML = meetings.length ? meetings.map(m => `<div class="meeting-item ${m.id === selected ? 'active' : ''}" data-meeting="${m.id}"><strong>${m.status === 'recording' || m.status === 'paused' ? '<span class="livedot">●</span> ' : ''}${esc(m.title)}</strong><small>${esc(dmy(m.started_at || m.created_at))} · ${hms(m.duration)} · ${m.pending_count ? '⏳ ' + m.pending_count + ' chờ' : (m.error_count ? '⚠ ' + m.error_count + ' lỗi' : '✓ ' + m.segment_count + ' đoạn')}</small></div>`).join('') : '<div class="sideempty">Chưa có cuộc họp</div>';
  root.querySelectorAll('[data-meeting]').forEach(el => el.addEventListener('click', () => selectMeeting(el.dataset.meeting).catch(fail)));
}
function deviceOptions(select, list, selectedDevice, selectDefault) {
  const el = $(select);
  el.innerHTML = '<option value="">— Không ghi nguồn này —</option>' + (list || []).map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('');
  if (selectDefault && (list || []).some(x => x.id === selectedDevice)) el.value = String(selectedDevice);
  else if (selectDefault && list?.length) el.value = String(list[0].id);
  else el.value = '';
}
async function loadDevices() {
  try {
    audioDevices = await req('/devices');
    deviceOptions('systemDevice', audioDevices.system || [], audioDevices.default_system, true);
    deviceOptions('micDevice', audioDevices.microphones || [], audioDevices.default_microphone, true);
    if (audioDevices.error) notice(audioDevices.error, 'info');
  } catch (e) { fail(e); }
}
async function newMeeting() {
  const now = new Date();
  const name = 'Cuộc họp ' + now.toLocaleDateString('vi-VN') + ' ' + now.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  const m = await req('/meetings', { method: 'POST', body: { title: name, model: $('modelSelect').value, device: $('deviceSelect').value, language: $('languageSelect').value } });
  await listAll(); await selectMeeting(m.id); toast('Đã tạo cuộc họp mới.');
}
async function selectMeeting(id) {
  if (selected === id && meeting) return;
  if (browserRecording) throw new Error('Đang ghi qua trình duyệt. Hãy kết thúc phiên trước khi chuyển cuộc họp.');
  releaseAllSources();
  selected = id; meeting = null; editing = false; lastSignature = '';
  $('audioPlayer').pause(); $('audioPlayer').removeAttribute('src'); $('audioPlayer').classList.add('hidden');
  await listAll(); await loadMeeting(true);
}
async function loadMeeting(initial = false) {
  if (!selected || editing) return;
  const m = await req('/meetings/' + selected); meeting = m; lastFetch = Date.now();
  $('topTitle').textContent = m.title; $('mainTitle').textContent = m.title;
  if (document.activeElement !== $('titleField')) $('titleField').value = m.title;
  if (initial) { $('modelSelect').value = m.model; $('deviceSelect').value = m.device; $('languageSelect').value = m.language; }
  const state = m.status, busy = state === 'recording' || state === 'paused';
  const otherActive = m.active_session && m.active_session !== m.id;
  $('recordBadge').className = 'status ' + (state === 'recording' ? 'recording' : state === 'paused' ? 'paused' : state === 'finished' || state === 'imported' ? 'finished' : 'idle');
  $('recordBadge').textContent = STATUS_LABEL[state] || state.toUpperCase();
  $('startBtn').classList.toggle('hidden', state !== 'ready'); $('startBtn').disabled = Boolean(otherActive);
  $('pauseBtn').classList.toggle('hidden', state !== 'recording'); $('resumeBtn').classList.toggle('hidden', state !== 'paused'); $('stopBtn').classList.toggle('hidden', !busy);
  $('systemDevice').disabled = busy; $('micDevice').disabled = busy; $('silentPlayback').disabled = busy;
  for (const id of ['browser1', 'browser2']) {
    const connected = (m.browser_connected || []).includes(id) || browserSources[id]?.connected;
    $('pick' + cap(id)).disabled = state !== 'ready' && !(busy && m.active_session === m.id && !connected);
    $('clear' + cap(id)).disabled = busy && connected;
  }
  $('liveIcon').classList.toggle('live', state === 'recording'); $('clock').textContent = hms(m.elapsed);
  $('modelSelect').disabled = busy; $('deviceSelect').disabled = busy; $('languageSelect').disabled = busy;
  for (const source of ['mic', 'system']) { const lv = (m.levels && m.levels[source]) || 0; $(source + 'Level').style.width = (lv * 100).toFixed(0) + '%'; $(source + 'Pct').textContent = (lv * 100).toFixed(0) + '%'; }
  if (!browserRecording) for (const source of ['browser1', 'browser2']) setLocalLevel(source, (m.levels && m.levels[source]) || 0);
  const pending = m.chunks.filter(x => x.state === 'pending' || x.state === 'processing').length, errors = m.chunks.filter(x => x.state === 'error').length;
  $('wordsStat').textContent = m.segments.length.toLocaleString('vi-VN'); $('pendingStat').textContent = pending; $('errorStat').textContent = errors;
  $('retryAllBtn').classList.toggle('hidden', !errors);
  if (m.audio_warnings?.length) warnBrowser('⚠ CẢNH BÁO TÍN HIỆU THU ÂM\n' + m.audio_warnings.join('\n'));
  else if (browserCaptureWarning.startsWith('⚠ CẢNH BÁO TÍN HIỆU')) warnBrowser('');
  if (m.model_error) notice('Chưa chép lời được: ' + m.model_error + ' — Âm thanh vẫn được lưu; kiểm tra Internet (lần đầu tải mô hình) hoặc đổi sang CPU rồi chờ tự thử lại.', 'warn');
  else if (otherActive) notice('Một cuộc họp khác đang ghi âm. Kết thúc phiên đó trước khi bắt đầu phiên mới.', 'info');
  else if (m.error && busy) notice('Cảnh báo nguồn âm thanh: ' + m.error, 'warn');
  else if (m.error && state === 'interrupted') notice(m.error + ' Nghe lại, kiểm tra phần cuối rồi bấm “Xác nhận kết thúc phiên đã khôi phục”.', 'warn');
  else if (errors) notice('Có ' + errors + ' đoạn nhận dạng gặp lỗi. Bấm “Thử lại đoạn lỗi” hoặc xem cuối bản chép lời.', 'warn');
  else if (m.disk_free_gb !== null && m.disk_free_gb !== undefined && m.disk_free_gb < 3) notice('Ổ đĩa chỉ còn ' + m.disk_free_gb + ' GB trống. Mỗi giờ ghi cần khoảng 0,35 GB cho mỗi nguồn.', 'warn');
  else if (m.model_loading) notice('Đang tải/khởi động mô hình nhận dạng... (lần đầu có thể mất vài phút)', 'info');
  else notice('');
  const have = [...new Set(m.chunks.map(c => c.source))];
  const sel = $('audioSource'), labels = { system: 'Nghe tiếng máy tính', mic: 'Nghe tiếng micro', imported: 'Nghe tệp nhập', browser1: 'Nghe nguồn chọn 1', browser2: 'Nghe nguồn chọn 2' };
  const want = have.length ? have : Object.keys(labels);
  if ([...sel.options].map(o => o.value).join() !== want.join()) { const prev = sel.value; sel.innerHTML = want.map(v => `<option value="${v}">${labels[v]}</option>`).join(''); sel.value = want.includes(prev) ? prev : want[0]; }
  $('exportMd').href = '/api/meetings/' + selected + '/export.md'; $('exportBundle').href = '/api/meetings/' + selected + '/export-bundle.zip'; $('exportTxt').href = '/api/meetings/' + selected + '/export.txt';
  $('finalizeBtn').classList.toggle('hidden', state !== 'interrupted');
  const missing = pending + errors;
  $('exportHint').textContent = busy ? 'Đang ghi: có thể xuất bản nháp bất kỳ lúc nào; bản đầy đủ có sau khi Kết thúc và “Đợi chép lời” về 0.'
    : missing ? `⚠ Còn ${missing} đoạn chưa hoàn tất. Bạn vẫn xuất được bản nháp, nhưng cần chờ hoặc xử lý lỗi để có văn bản đầy đủ.`
    : 'Mọi đoạn đã được chép lời. Tải Markdown rồi đưa lên ChatGPT / Claude / NotebookLM kèm bộ hướng dẫn trong thư mục huong_dan_GPT.';
  const signature = m.status + '|' + m.segments.length + '|' + m.annotations.length + '|' + pending + '|' + errors + '|' + (m.segments.length ? m.segments[m.segments.length - 1].id : '') + '|' + m.segments.reduce((a, s) => a + (s.edited ? 1 : 0), 0);
  if (initial || signature !== lastSignature) { lastSignature = signature; drawTranscript(); drawNotes(); drawSpeakers(); }
}

function drawTranscript() {
  if (!meeting || editing) return;
  const q = $('searchBox').value.toLocaleLowerCase('vi').trim(); const m = meeting;
  const items = m.segments.filter(s => !q || s.text.toLocaleLowerCase('vi').includes(q) || s.speaker.toLocaleLowerCase('vi').includes(q));
  let html = items.length ? items.map(s => `<article class="transcript-entry" data-segid="${s.id}"><button class="stamp seek-btn" data-source="${esc(s.source)}" data-time="${s.start_s}" title="Nghe lại từ thời điểm này">${hms(s.start_s)}</button><div class="entrybody"><div class="entrytop"><span class="speakername">${esc(s.speaker)}</span><span class="sourcetag">${esc(s.source)}</span>${s.edited ? '<span class="sourcetag">đã sửa</span>' : ''}<button class="editbtn" data-edit="${s.id}">Chỉnh sửa</button></div><div class="entrytext">${esc(s.text)}</div></div></article>`).join('')
    : `<div class="empty-state"><div class="empty-icon">≋</div><strong>${q ? 'Không có lời thoại khớp từ khóa' : 'Chưa có nội dung'}</strong><span>${q ? 'Thử từ khóa khác.' : 'Nội dung xuất hiện sau khi từng đoạn 20 giây được chép lời.'}</span></div>`;
  const bad = m.chunks.filter(x => x.state === 'error');
  if (bad.length) html += '<div class="sectionline"></div><h3>Đoạn gặp lỗi</h3>' + bad.map(x => `<div class="note-item"><span class="muted">${hms(x.start_s)} · ${esc(x.source)}</span><span>${esc(x.error || 'Chưa rõ lỗi')}</span><button class="btn outline" data-retry="${x.id}">Thử lại</button></div>`).join('');
  const container = $('transcriptList'), pos = container.scrollTop, atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;
  container.innerHTML = html; container.scrollTop = atBottom && meeting.status === 'recording' ? container.scrollHeight : pos;
  container.querySelectorAll('[data-edit]').forEach(b => b.addEventListener('click', () => editSegment(b.dataset.edit)));
  container.querySelectorAll('[data-retry]').forEach(b => b.addEventListener('click', async () => { try { await req('/chunks/' + b.dataset.retry + '/retry', { method: 'POST' }); toast('Đã đưa đoạn vào hàng đợi lại.'); lastSignature = ''; await loadMeeting(); } catch (e) { fail(e); } }));
  container.querySelectorAll('.seek-btn').forEach(b => b.addEventListener('click', () => seekAudio(b.dataset.source, parseFloat(b.dataset.time)).catch(fail)));
}
function editSegment(id) {
  const seg = meeting.segments.find(x => x.id === id); if (!seg) return;
  editing = true;
  const root = $('transcriptList').querySelector(`[data-segid="${id}"] .entrybody`);
  root.innerHTML = `<div class="entrytop"><strong>Chỉnh sửa nội dung</strong></div><textarea class="editarea" id="editText">${esc(seg.text)}</textarea><div class="editrow"><input class="control" id="editSpeaker" maxlength="100" placeholder="Người nói" value="${esc(seg.speaker)}"><button class="btn primary" id="saveEdit">Lưu</button><button class="btn outline" id="cancelEdit">Hủy</button><button class="btn outline" id="deleteSeg" title="Xóa câu này khỏi bản chép lời">Xóa câu</button></div>`;
  root.querySelector('#cancelEdit').onclick = () => { editing = false; drawTranscript(); };
  root.querySelector('#saveEdit').onclick = async () => { try { await req('/segments/' + id, { method: 'PATCH', body: { text: $('editText').value, speaker: $('editSpeaker').value } }); editing = false; lastSignature = ''; await loadMeeting(); toast('Đã lưu bản hiệu đính.'); } catch (e) { fail(e); } };
  root.querySelector('#deleteSeg').onclick = () => confirmBox('Xóa câu này?', 'Câu sẽ bị xóa khỏi bản chép lời. Âm thanh gốc vẫn còn.', async () => { await req('/segments/' + id, { method: 'DELETE' }); editing = false; lastSignature = ''; await loadMeeting(); }, 'Xóa');
}
function drawNotes() {
  if (!meeting) return;
  $('notesList').innerHTML = meeting.annotations.length ? meeting.annotations.map(n => `<div class="note-item"><span class="muted">${hms(n.at_s)}<br>${esc(n.kind)}</span><span>${esc(n.text)}</span><button data-delete-note="${n.id}" title="Xóa">✕</button></div>`).join('') : '<p class="formhint">Chưa có ghi chú.</p>';
  $('notesList').querySelectorAll('[data-delete-note]').forEach(b => b.addEventListener('click', async () => { try { await req('/annotations/' + b.dataset.deleteNote, { method: 'DELETE' }); lastSignature = ''; await loadMeeting(); } catch (e) { fail(e); } }));
}
function drawSpeakers() {
  if (!meeting) return;
  const count = {}; meeting.segments.forEach(s => count[s.speaker] = (count[s.speaker] || 0) + 1);
  $('speakerList').innerHTML = Object.keys(count).length ? Object.entries(count).map(([name, c]) => `<div class="speaker-item"><label>${esc(name)} · ${c} đoạn</label><input class="control" data-old="${esc(name)}" value="${esc(name)}" placeholder="Đặt tên người nói"><button class="btn outline" data-rename="${esc(name)}">Đổi tất cả</button></div>`).join('') : '<p class="formhint">Chưa có đoạn lời thoại nào.</p>';
  $('speakerList').querySelectorAll('[data-rename]').forEach(b => b.onclick = async () => { try { const input = b.parentElement.querySelector('input'); const x = await req('/meetings/' + selected + '/rename-speaker', { method: 'POST', body: { old: b.dataset.rename, new: input.value } }); toast('Đã cập nhật ' + x.changed + ' đoạn.'); lastSignature = ''; await loadMeeting(); } catch (e) { fail(e); } });
}
async function saveConfig() { if (!selected) return; await req('/meetings/' + selected, { method: 'PATCH', body: { title: $('titleField').value, model: $('modelSelect').value, device: $('deviceSelect').value, language: $('languageSelect').value } }); }

async function start() {
  if (!selected) return;
  await saveConfig();
  const mic = $('micDevice').value, system = $('systemDevice').value, chosen = selectedSources();
  if (!mic && !system && !chosen.length) { toast('Chọn micro, âm thanh máy tính hoặc 1–2 nguồn tab/cửa sổ trước khi bắt đầu.', true); return; }
  const go = async () => {
    $('startBtn').disabled = true;
    try {
      await req('/meetings/' + selected + '/start', { method: 'POST', body: { mic: mic ? +mic : null, system: system ? +system : null, browser_sources: chosen } });
      if (chosen.length) {
        try { await connectAllBrowser(selected); }
        catch (e) {
          if (!mic && !system) { await req('/meetings/' + selected + '/stop', { method: 'POST' }).catch(() => { }); throw new Error('Không nối được nguồn trình duyệt nên đã hủy phiên: ' + e.message); }
          warnBrowser('⚠ LỖI NGUỒN TRÌNH DUYỆT: ' + e.message + '\nPhiên vẫn ghi micro/âm thanh máy tính. Bấm “Chọn nguồn” để thử lại.');
        }
      }
      toast('Đang ghi. Giữ trình duyệt và cửa sổ chương trình chạy xuyên suốt cuộc họp.');
    } finally { $('startBtn').disabled = false; }
    lastSignature = ''; await loadMeeting(); await listAll();
  };
  if (system && chosen.length) {
    confirmBox('Có thể ghi trùng', 'Bạn chọn cả “Âm thanh máy tính” và nguồn tab/cửa sổ. Nếu tab đó đang phát qua loa, tiếng họp sẽ bị ghi hai lần (hai nguồn riêng, không hỏng dữ liệu nhưng dư thừa). Vẫn tiếp tục?', go, 'Vẫn ghi');
  } else await go();
}
async function pause() { pauseAllBrowser(); await req('/meetings/' + selected + '/pause', { method: 'POST' }); lastSignature = ''; await loadMeeting(); }
async function resume() { await req('/meetings/' + selected + '/resume', { method: 'POST' }); resumeAllBrowser(); lastSignature = ''; await loadMeeting(); }
async function stop() {
  $('stopBtn').disabled = true;
  try { await stopAllBrowser(); await req('/meetings/' + selected + '/stop', { method: 'POST' }); toast('Đã kết thúc ghi. Các đoạn còn lại tiếp tục được chép lời.'); }
  finally { $('stopBtn').disabled = false; }
  lastSignature = ''; await loadMeeting(); await listAll();
}
async function seekAudio(source, time) {
  if (!meeting) return;
  if (!['system', 'mic', 'imported', 'browser1', 'browser2'].includes(source)) return;
  if (meeting.status === 'recording' || meeting.status === 'paused') { toast('Nghe lại chỉ khả dụng sau khi kết thúc ghi.', true); return; }
  const player = $('audioPlayer'); const url = '/api/meetings/' + selected + '/audio/' + source;
  if (!player.src || !player.src.endsWith(url)) { player.src = url; player.classList.remove('hidden'); }
  player.addEventListener('loadedmetadata', function f() { player.removeEventListener('loadedmetadata', f); player.currentTime = time; player.play().catch(() => { }); });
  if (player.readyState >= 1) { player.currentTime = time; player.play().catch(() => { }); } else player.load();
  toast('Đang mở đoạn ' + hms(time) + ' của nguồn ' + source + ' (lần đầu có thể mất một lúc để ghép tệp).');
}
async function uploadFile() {
  const file = $('audioInput').files[0];
  if (!selected || !file) { toast('Chưa chọn tệp để tải lên.', true); return; }
  const button = $('uploadBtn'); button.disabled = true; $('uploadStatus').textContent = 'Đang tải dữ liệu vào chương trình...';
  const form = new FormData(); form.append('file', file);
  try {
    await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/meetings/' + selected + '/upload');
      xhr.upload.onprogress = e => { if (e.lengthComputable) $('uploadStatus').textContent = `Đã tải ${Math.round(e.loaded / e.total * 100)}% — sau đó giải mã và chia đoạn (tệp dài có thể mất vài phút)...`; };
      xhr.onload = () => { let response = {}; try { response = JSON.parse(xhr.responseText); } catch { } if (xhr.status >= 200 && xhr.status < 300) resolve(response); else reject(new Error(response.detail || 'Không nhập được tệp')); };
      xhr.onerror = () => reject(new Error('Không kết nối được bộ xử lý.')); xhr.send(form);
    });
    toast('Đã nhập âm thanh. Chương trình đang chép lời.'); $('uploadStatus').textContent = 'Hoàn tất nhập tệp; đang chép lời theo hàng đợi.'; $('audioInput').value = ''; $('fileLabel').textContent = 'Chưa chọn tệp';
    lastSignature = ''; await loadMeeting(); await listAll();
  } catch (e) { fail(e); $('uploadStatus').textContent = e.message; } finally { button.disabled = false; }
}
async function diarize() {
  if (!selected) return;
  const token = $('hfToken').value.trim(); if (!token) { toast('Chưa nhập mã truy cập Hugging Face.', true); return; }
  try { await req('/meetings/' + selected + '/diarize', { method: 'POST', body: { source: $('speakerSource').value, token } }); $('hfToken').value = ''; $('diarizeState').textContent = 'Đã chạy phân tách. Vui lòng chờ...'; } catch (e) { fail(e); }
}
async function pollDiarization() { if (!selected || activeTab !== 'speaker') return; try { const state = await req('/meetings/' + selected + '/diarize-status'); $('diarizeState').textContent = state.message || ''; } catch { } }
function setTab(tab) { activeTab = tab; document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab)); document.querySelectorAll('.tabview').forEach(v => v.classList.toggle('hidden', v.id !== 'tab-' + tab)); if (tab === 'speaker') pollDiarization(); }
async function setup() {
  try {
    const h = await req('/health');
    $('connPill').textContent = '● CỤC BỘ · ' + h.version;
    $('systemHint').textContent = h.whisper ? 'Whisper đã cài đặt' + (h.disk_free_gb !== null ? ' · còn ' + h.disk_free_gb + ' GB' : '') : 'Thiếu thư viện Whisper — chạy cài đặt lại';
    if (!h.whisper) notice('Chưa cài đặt Faster Whisper. Hãy chạy setup_windows.bat.', 'warn');
    await loadDevices(); await listAll();
    const active = meetings.find(m => m.id === h.active);
    if (active) await selectMeeting(active.id); else if (meetings.length) await selectMeeting(meetings[0].id); else await newMeeting();
  } catch (e) { fail(e); notice('Không khởi động được bộ xử lý. Kiểm tra cửa sổ dòng lệnh START_WINDOWS.bat.', 'warn'); }
}
$('newBtn').onclick = () => newMeeting().catch(fail); $('startBtn').onclick = () => start().catch(fail); $('pauseBtn').onclick = () => pause().catch(fail); $('resumeBtn').onclick = () => resume().catch(fail);
$('stopBtn').onclick = () => confirmBox('Kết thúc ghi âm?', 'Chương trình sẽ đóng các tệp hiện tại và tiếp tục chép lời phần còn lại. Không thể tiếp tục ghi vào phiên này sau khi kết thúc.', stop, 'Kết thúc');
$('retryAllBtn').onclick = async () => { try { const x = await req('/meetings/' + selected + '/retry-errors', { method: 'POST' }); toast('Đã đưa ' + x.changed + ' đoạn lỗi vào hàng đợi lại.'); lastSignature = ''; await loadMeeting(); } catch (e) { fail(e); } };
$('titleField').addEventListener('change', () => saveConfig().then(listAll).catch(fail)); ['modelSelect', 'deviceSelect', 'languageSelect'].forEach(id => $(id).onchange = () => saveConfig().catch(fail));
$('searchBox').oninput = drawTranscript; document.querySelectorAll('[data-tab]').forEach(btn => btn.onclick = () => setTab(btn.dataset.tab));
$('addNoteBtn').onclick = async () => { try { const text = $('noteText').value.trim(); if (!text) return; const at = meeting && (meeting.status === 'recording' || meeting.status === 'paused') ? currentElapsed() : (parseFloat($('audioPlayer').currentTime) || 0); await req('/meetings/' + selected + '/annotations', { method: 'POST', body: { text, kind: $('noteKind').value, at_s: at } }); $('noteText').value = ''; lastSignature = ''; await loadMeeting(); toast('Đã thêm ghi chú tại ' + hms(at) + '.'); } catch (e) { fail(e); } };
$('noteText').addEventListener('keydown', e => { if (e.key === 'Enter') $('addNoteBtn').click(); });
$('audioInput').onchange = () => { $('fileLabel').textContent = $('audioInput').files[0]?.name || 'Chưa chọn tệp'; }; $('uploadBtn').onclick = uploadFile;
$('loadAudioBtn').onclick = () => seekAudio($('audioSource').value, 0).catch(fail); $('diarizeBtn').onclick = diarize;
$('finalizeBtn').onclick = async () => { try { await req('/meetings/' + selected + '/finalize', { method: 'POST' }); lastSignature = ''; await loadMeeting(); toast('Đã xác nhận đóng phiên được khôi phục.'); } catch (e) { fail(e); } };
$('deleteBtn').onclick = () => confirmBox('Xóa toàn bộ cuộc họp?', 'Toàn bộ bản ghi âm, văn bản và ghi chú trên máy sẽ bị xóa vĩnh viễn. Không thể hoàn tác.', async () => { await req('/meetings/' + selected, { method: 'DELETE' }); selected = null; meeting = null; await listAll(); if (meetings.length) await selectMeeting(meetings[0].id); else await newMeeting(); toast('Đã xóa cuộc họp.'); }, 'Xóa vĩnh viễn');
$('dialogCancel').onclick = () => $('dialog').close();
$('guideBtn').onclick = () => { confirmBox('Cách sử dụng nhanh', '1) Chọn nguồn: “Âm thanh máy tính” (mọi tiếng đang phát) và/hoặc micro, hoặc bấm “Chọn nguồn 1/2” để chỉ lấy tiếng 1–2 tab Chrome/Edge. 2) Bấm Bắt đầu, nhìn thanh tín hiệu nhảy. 3) Kết thúc, chờ “Đợi chép lời” về 0. 4) Sửa câu, đặt tên người nói. 5) Xuất Markdown rồi đưa lên ChatGPT/Claude/NotebookLM với bộ hướng dẫn trong thư mục huong_dan_GPT.', () => { }, 'Đóng'); };
function currentElapsed() { return meeting ? meeting.elapsed + ((meeting.status === 'recording' || meeting.status === 'paused') ? Math.max(0, (Date.now() - lastFetch) / 1000) : 0) : 0; }
let lastSidebar = 0;
setInterval(async () => {
  if (refreshRunning || editing || !selected) return;
  refreshRunning = true;
  try { await loadMeeting(); if (Date.now() - lastSidebar > 12500) { await listAll(); lastSidebar = Date.now(); } await pollDiarization(); }
  catch (e) { console.warn(e); } finally { refreshRunning = false; }
}, 3200);
setInterval(() => { if (meeting && (meeting.status === 'recording' || meeting.status === 'paused')) $('clock').textContent = hms(currentElapsed()); }, 1000);
setup();
