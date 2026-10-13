'use strict';
/* Chọn 1–2 tab/cửa sổ bằng hộp thoại getDisplayMedia của Chrome/Edge, lấy luồng âm thanh,
 * chuyển thành PCM 16-bit qua AudioWorklet (dự phòng ScriptProcessor) và gửi tới bộ xử lý
 * cục bộ qua WebSocket. Tự nối lại WebSocket khi rớt; cho phép chọn lại nguồn khi tab chia sẻ
 * bị dừng giữa cuộc họp. */
const browserSources = { browser1: null, browser2: null };
let browserRecording = false;
let browserPaused = false;
let browserMeeting = null;
let browserCaptureWarning = '';
let wakeLock = null;

function cap(id) { return id[0].toUpperCase() + id.slice(1); }
function sourceUi(id) {
  const src = browserSources[id];
  const label = document.getElementById(id + 'Label');
  const btn = document.getElementById('pick' + cap(id));
  if (browserRecording) btn.disabled = Boolean(src && src.connected);  // nguồn rớt giữa chừng => cho chọn lại ngay
  if (!src) { label.textContent = 'Chưa chọn'; label.className = ''; btn.textContent = '+ Chọn nguồn ' + id.at(-1); return; }
  const state = !browserRecording ? '' : src.connected ? ' · đang ghi' : ' · đang nối lại...';
  label.textContent = src.label + (src.suppress ? ' · không phát ra loa' : '') + state;
  label.className = src.connected ? 'ok' : '';
  btn.textContent = 'Đổi nguồn ' + id.at(-1);
}
function warnBrowser(text) {
  browserCaptureWarning = text;
  const el = document.getElementById('captureWarnings');
  el.textContent = text; el.classList.toggle('hidden', !text);
}
function setLocalLevel(id, level) {
  const bar = document.getElementById(id + 'Level'), pct = document.getElementById(id + 'Pct');
  if (bar) bar.style.width = (level * 100).toFixed(0) + '%';
  if (pct) pct.textContent = (level * 100).toFixed(0) + '%';
}
function releaseSource(id) {
  const src = browserSources[id]; if (!src) return;
  browserSources[id] = null;
  src.released = true;
  clearTimeout(src.reconnectTimer);
  for (const node of ['worklet', 'processor', 'input', 'sink']) { try { src[node]?.disconnect(); } catch { } }
  if (src.ctx) src.ctx.close().catch(() => { });
  if (src.ws) { try { src.ws.onclose = null; src.ws.close(); } catch { } }
  for (const track of src.stream.getTracks()) track.stop();
  setLocalLevel(id, 0);
  sourceUi(id);
}
function releaseAllSources() { releaseSource('browser1'); releaseSource('browser2'); browserRecording = false; browserPaused = false; browserMeeting = null; releaseWakeLock(); }
function selectedSources() { return Object.entries(browserSources).filter(([, x]) => !!x).map(([k]) => k); }
function connectedSources() { return selectedSources().filter(id => browserSources[id].connected); }

async function pickSource(id) {
  if (browserRecording && browserSources[id]?.connected) throw new Error('Nguồn ' + id.at(-1) + ' đang ghi. Chỉ có thể chọn lại khi nguồn đã dừng chia sẻ.');
  if (!navigator.mediaDevices?.getDisplayMedia) throw new Error('Trình duyệt này không hỗ trợ chia sẻ âm thanh tab/cửa sổ. Hãy dùng Chrome hoặc Edge.');
  const silent = document.getElementById('silentPlayback').checked;
  const opts = {
    video: { frameRate: { ideal: 1 }, width: { ideal: 320 }, height: { ideal: 180 } },
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, suppressLocalAudioPlayback: silent },
    systemAudio: 'include', windowAudio: 'window',
    selfBrowserSurface: 'exclude', surfaceSwitching: 'exclude', preferCurrentTab: false
  };
  let stream;
  try { stream = await navigator.mediaDevices.getDisplayMedia(opts); }
  catch (e) {
    if (e.name === 'NotAllowedError') throw new Error('Bạn đã hủy hộp thoại chọn nguồn hoặc trình duyệt chặn quyền chia sẻ.');
    throw new Error('Không mở được hộp thoại chọn nguồn: ' + e.message);
  }
  if (stream.getAudioTracks().length === 0) {
    stream.getTracks().forEach(x => x.stop());
    throw new Error('Nguồn vừa chọn KHÔNG cấp luồng âm thanh. Hãy chọn một TAB trình duyệt và bật “Chia sẻ âm thanh tab”, hoặc chọn “Toàn màn hình” + “Chia sẻ âm thanh hệ thống”. Cửa sổ ứng dụng (Zoom/Teams cài trên máy) thường không có âm thanh riêng.');
  }
  const audio = stream.getAudioTracks()[0], video = stream.getVideoTracks()[0];
  const vs = video?.getSettings() || {}, as = audio.getSettings() || {};
  const suppressed = Boolean(as.suppressLocalAudioPlayback);
  releaseSource(id);
  const display = vs.displaySurface === 'browser' ? 'Tab' : vs.displaySurface === 'window' ? 'Cửa sổ' : vs.displaySurface === 'monitor' ? 'Màn hình (toàn bộ âm thanh hệ thống)' : 'Nguồn';
  const src = { stream, label: display + ' · ' + (video?.label || audio.label || id), suppress: suppressed, connected: false, released: false, ctx: null, ws: null, input: null, worklet: null, processor: null, sink: null, reconnectTimer: null, lastLevelAt: 0 };
  browserSources[id] = src;
  stream.getTracks().forEach(track => { track.onended = () => {
    if (browserSources[id] !== src) return;
    if (browserRecording) warnBrowser('⚠ Nguồn ' + id.at(-1) + ' (' + src.label + ') đã DỪNG chia sẻ. Âm thanh từ nguồn đó không còn được ghi! Bấm “Chọn nguồn ' + id.at(-1) + '” để chọn lại — phiên ghi vẫn tiếp tục.');
    releaseSource(id);
  }; });
  sourceUi(id);
  if (silent && !suppressed) warnBrowser('⚠ Trình duyệt không xác nhận chế độ “không phát ra loa” cho nguồn này; tiếng vẫn phát bình thường (vẫn ghi được). Chế độ này chỉ áp dụng cho TAB Chrome/Edge.');
  else if (vs.displaySurface === 'monitor') warnBrowser('ℹ Bạn chọn toàn màn hình: nguồn này ghi TOÀN BỘ âm thanh hệ thống (không lọc riêng ứng dụng). Đừng chọn thêm “Âm thanh máy tính” để tránh ghi trùng.');
  else warnBrowser('');
  // Phiên đang ghi (kể cả phiên chỉ có micro/hệ thống): nối nguồn vừa chọn vào ngay.
  const live = typeof meeting !== 'undefined' && meeting && (meeting.status === 'recording' || meeting.status === 'paused') && meeting.active_session === meeting.id;
  if (!browserRecording && live) { browserRecording = true; browserPaused = meeting.status === 'paused'; browserMeeting = meeting.id; requestWakeLock(); }
  if (browserRecording && browserMeeting) {
    await connectSource(browserMeeting, id);
    toast('Đã nối nguồn ' + id.at(-1) + ' vào phiên đang ghi.');
  }
  return src;
}

async function buildPipeline(src, id) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'playback' });
  src.ctx = ctx;
  const input = ctx.createMediaStreamSource(new MediaStream(src.stream.getAudioTracks()));
  const sink = ctx.createGain(); sink.gain.value = 0;
  src.input = input; src.sink = sink;
  const onPcm = buffer => {
    if (!browserRecording || browserPaused || src.released) return;
    const now = performance.now();
    if (now - src.lastLevelAt > 120) {
      const v = new Int16Array(buffer); let acc = 0;
      for (let i = 0; i < v.length; i += 4) acc += v[i] * v[i];
      setLocalLevel(id, Math.min(1, Math.sqrt(acc / (v.length / 4)) / 32768 * 8));
      src.lastLevelAt = now;
    }
    const ws = src.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (ws.bufferedAmount > 4 * 1024 * 1024) { warnBrowser('⚠ Bộ xử lý ghi âm không theo kịp âm thanh nguồn ' + id.at(-1) + '. Có thể mất dữ liệu! Kiểm tra cửa sổ chương trình.'); return; }
    ws.send(buffer);
  };
  let usedWorklet = false;
  if (ctx.audioWorklet) {
    try {
      await ctx.audioWorklet.addModule('/pcm-worklet.js');
      const worklet = new AudioWorkletNode(ctx, 'pcm-capture', { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
      worklet.port.onmessage = ev => onPcm(ev.data);
      src.worklet = worklet;
      input.connect(worklet); worklet.connect(sink);
      usedWorklet = true;
    } catch (e) { console.warn('AudioWorklet không khả dụng, dùng ScriptProcessor', e); }
  }
  if (!usedWorklet) {
    const processor = ctx.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = e => {
      const ch = e.inputBuffer.getChannelData(0);
      const pcm = new Int16Array(ch.length);
      for (let i = 0; i < ch.length; i++) { const s = Math.max(-1, Math.min(1, ch[i])); pcm[i] = s < 0 ? s * 32768 : s * 32767; }
      onPcm(pcm.buffer);
    };
    src.processor = processor;
    input.connect(processor); processor.connect(sink);
  }
  sink.connect(ctx.destination);
  await ctx.resume();
}

function openSocket(mid, id, src) {
  return new Promise((ok, bad) => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/api/meetings/${encodeURIComponent(mid)}/browser/${id}`);
    ws.binaryType = 'arraybuffer';
    let ready = false;
    ws.onopen = () => ws.send(JSON.stringify({ rate: Math.round(src.ctx.sampleRate), label: src.label.slice(0, 120) }));
    ws.onmessage = ev => { try { const msg = JSON.parse(ev.data); if (msg.ready && !ready) { ready = true; ok(ws); } } catch { } };
    ws.onerror = () => { if (!ready) bad(new Error('Không mở được đường truyền ghi nguồn ' + id.at(-1) + '. Cửa sổ chương trình còn chạy không?')); };
    ws.onclose = ev => {
      if (!ready) { bad(new Error(ev.code === 4001 ? 'Nguồn ' + id.at(-1) + ' đang có kết nối khác (trang mở hai lần?).' : 'Bộ xử lý từ chối nguồn ' + id.at(-1) + ' (mã ' + ev.code + ').')); return; }
      if (src.released || browserSources[id] !== src) return;
      src.connected = false; sourceUi(id); setLocalLevel(id, 0);
      if (browserRecording) {
        warnBrowser('⚠ Mất kết nối ghi nguồn ' + id.at(-1) + '. Đang tự nối lại...');
        scheduleReconnect(mid, id, src);
      }
    };
  });
}
function scheduleReconnect(mid, id, src) {
  clearTimeout(src.reconnectTimer);
  src.reconnectTimer = setTimeout(async () => {
    if (src.released || !browserRecording || browserSources[id] !== src) return;
    try { src.ws = await openSocket(mid, id, src); src.connected = true; sourceUi(id); if (browserCaptureWarning.includes('Mất kết nối')) warnBrowser(''); }
    catch (e) { console.warn(e); scheduleReconnect(mid, id, src); }
  }, 2000);
}
async function connectSource(mid, id) {
  const src = browserSources[id]; if (!src) return;
  if (!src.ctx) await buildPipeline(src, id);
  src.ws = await openSocket(mid, id, src);
  src.connected = true;
  sourceUi(id);
}
async function connectAllBrowser(mid) {
  browserRecording = true; browserPaused = false; browserMeeting = mid;
  const failures = [];
  for (const id of selectedSources()) { try { await connectSource(mid, id); } catch (e) { failures.push(e.message); } }
  requestWakeLock();
  if (failures.length && connectedSources().length === 0) { await stopAllBrowser(); throw new Error(failures.join(' / ')); }
  if (failures.length) warnBrowser('⚠ ' + failures.join('\n'));
  for (const id of selectedSources()) sourceUi(id);
}
function pauseAllBrowser() {
  browserPaused = true;
  for (const id of selectedSources()) { const ws = browserSources[id]?.ws; if (ws?.readyState === WebSocket.OPEN) ws.send('pause'); setLocalLevel(id, 0); }
}
function resumeAllBrowser() { browserPaused = false; }
async function stopAllBrowser() {
  browserRecording = false;
  // WebSocket có bộ đệm: đợi gửi hết PCM để không mất vài giây cuối.
  const deadline = Date.now() + 4000;
  while (Date.now() < deadline) {
    const waiting = selectedSources().some(id => { const ws = browserSources[id]?.ws; return ws?.readyState === WebSocket.OPEN && ws.bufferedAmount > 0; });
    if (!waiting) break;
    await new Promise(r => setTimeout(r, 60));
  }
  releaseAllSources();
}
async function requestWakeLock() {
  try { if ('wakeLock' in navigator && !wakeLock) { wakeLock = await navigator.wakeLock.request('screen'); wakeLock.addEventListener('release', () => { wakeLock = null; }); } } catch { }
}
function releaseWakeLock() { try { wakeLock?.release(); } catch { } wakeLock = null; }
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && browserRecording) requestWakeLock(); });

for (const id of ['browser1', 'browser2']) {
  document.getElementById('pick' + cap(id)).onclick = async () => { try { await pickSource(id); if (!browserRecording) toast('Đã chọn nguồn ' + id.at(-1) + '. Phát thử và theo dõi thanh tín hiệu sau khi bấm Bắt đầu.'); } catch (e) { fail(e); } };
  document.getElementById('clear' + cap(id)).onclick = () => { if (browserRecording && browserSources[id]?.connected) { toast('Không thể gỡ nguồn đang ghi. Hãy kết thúc phiên trước.', true); return; } releaseSource(id); };
}
window.addEventListener('beforeunload', e => { if (browserRecording) { e.preventDefault(); e.returnValue = 'Đang thu âm tab/cửa sổ! Rời khỏi trang sẽ ngắt luồng.'; } });
