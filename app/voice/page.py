"""Owner-only browser page: raw WebSocket client for xAI Grok Voice.

Talks to xAI directly from the browser using a short-lived ephemeral token
minted by /voice/session. Tool calls are relayed back to /voice/tool, which
runs with server-side access to private relationship and plan data -- the
browser itself never touches the database or the long-lived xAI key.

Push-to-talk, not voice-activity detection: the orb is the control. Click once
to start recording (blue), click again to send it and wait (grey, "thinking"),
then Rally speaks (violet, driven by output amplitude). Nothing auto-interrupts
Rally mid-sentence -- turn-taking is entirely under the user's control. A
monospace activity strip at the bottom logs every tool call and connection
event for diagnosis; it stays out of the way until expanded.
"""


def render_voice_page(admin_token: str, voice_model: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Rally Voice</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{
  --bg: #0a0a10; --panel: #101018; --hair: #1e1e29;
  --ink: #f4f4f8; --ink-dim: #6b6b7a;
  --listen: #4f7dff; --speak: #b355ff; --idle: #34343f; --danger: #ff4d6d;
  color-scheme: dark;
}}
* {{ box-sizing: border-box; }}
html, body {{ height: 100%; }}
body {{
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
  display: flex; flex-direction: column;
}}
.topbar {{
  display: flex; align-items: center; gap: 10px;
  padding: 18px 22px; flex-shrink: 0;
}}
.wordmark {{ font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }}
.dot {{
  width: 7px; height: 7px; border-radius: 50%; background: var(--idle);
  transition: background 300ms ease;
}}
.dot.live {{ background: var(--listen); box-shadow: 0 0 8px var(--listen); }}
.stage {{
  flex: 1; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 28px; padding: 24px; min-height: 0;
}}
.orb-wrap {{ width: min(56vw, 260px); aspect-ratio: 1; position: relative; cursor: pointer; }}
.orb {{
  position: absolute; inset: 0; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, var(--c2, #26263a), var(--c1, #17171f) 70%);
  transform: scale(var(--scale, 1));
  box-shadow: 0 0 calc(20px + var(--glow, 0) * 70px) calc(-2px) var(--c1, #26263a);
  transition: background 500ms ease;
}}
.orb::after {{
  content: ""; position: absolute; inset: 14%; border-radius: 50%;
  border: 1px solid color-mix(in srgb, var(--c1, #444) 55%, transparent);
  opacity: calc(0.35 + var(--glow, 0) * 0.5);
}}
.orb-wrap[data-state="idle"] {{ --c1: #34343f; --c2: #1e1e28; }}
.orb-wrap[data-state="connecting"] {{ --c1: #4a4a58; --c2: #2a2a36; }}
.orb-wrap[data-state="ready"] {{ --c1: #34343f; --c2: #1e1e28; }}
.orb-wrap[data-state="recording"] {{ --c1: #4f7dff; --c2: #7fa0ff; }}
.orb-wrap[data-state="thinking"] {{ --c1: #6b6b7a; --c2: #3a3a46; }}
.orb-wrap[data-state="thinking"] .orb {{ animation: think-pulse 1.1s ease-in-out infinite; }}
@keyframes think-pulse {{
  0%, 100% {{ box-shadow: 0 0 20px -2px var(--c1); }}
  50% {{ box-shadow: 0 0 55px -2px var(--c1); }}
}}
.orb-wrap[data-state="speaking"] {{ --c1: #b355ff; --c2: #d59bff; }}
.orb-wrap[data-state="error"] {{ --c1: #ff4d6d; --c2: #ff8a9d; }}
.caption {{ font-size: 14px; color: var(--ink-dim); min-height: 20px; text-align: center; }}
.hint {{ font-size: 12px; color: var(--ink-dim); opacity: 0.7; }}
.activity {{
  flex-shrink: 0; border-top: 1px solid var(--hair); background: var(--panel);
}}
.activity-head {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 18px; cursor: pointer; user-select: none;
}}
.activity-head span:first-child {{ font-size: 11px; color: var(--ink-dim); }}
.activity-head button {{
  background: none; border: none; color: var(--ink-dim); font-size: 11px;
  cursor: pointer; padding: 2px 6px;
}}
.activity-log {{
  font-family: ui-monospace, "SF Mono", monospace; font-size: 11px; line-height: 1.6;
  color: var(--ink-dim); padding: 0 18px; overflow-y: auto; max-height: 0;
  transition: max-height 220ms ease, padding 220ms ease;
}}
.activity-log.open {{ max-height: 32vh; padding: 0 18px 14px; }}
.activity-log .entry {{ display: flex; gap: 8px; white-space: pre-wrap; word-break: break-word; }}
.activity-log .tag {{ flex-shrink: 0; width: 46px; }}
.activity-log .tag.tool {{ color: var(--listen); }}
.activity-log .tag.sys {{ color: var(--ink-dim); }}
.activity-log .tag.err {{ color: var(--danger); }}
@media (prefers-reduced-motion: reduce) {{ .orb {{ transition: none; }} }}
</style></head>
<body>
<div class="topbar">
  <div class="dot" id="dot"></div>
  <div class="wordmark">Rally Voice</div>
</div>
<div class="stage">
  <div class="orb-wrap" id="orbWrap" data-state="idle">
    <div class="orb" id="orb"></div>
  </div>
  <div class="caption" id="caption">Tap to connect</div>
  <div class="hint" id="hint">Tap to start recording, tap again to send. Ask "who am I falling behind with?"</div>
</div>
<div class="activity">
  <div class="activity-head" id="activityHead">
    <span id="activitySummary">Activity</span>
    <button id="activityToggle">Show</button>
  </div>
  <div class="activity-log" id="log"></div>
</div>
<script>
const ADMIN_TOKEN = {admin_token!r};
const VOICE_MODEL = {voice_model!r};
const orbWrap = document.getElementById('orbWrap');
const captionEl = document.getElementById('caption');
const dotEl = document.getElementById('dot');
const logEl = document.getElementById('log');
const summaryEl = document.getElementById('activitySummary');
const toggleEl = document.getElementById('activityToggle');
const headEl = document.getElementById('activityHead');

let logOpen = false;
headEl.addEventListener('click', () => {{
  logOpen = !logOpen;
  logEl.classList.toggle('open', logOpen);
  toggleEl.textContent = logOpen ? 'Hide' : 'Show';
}});

function logLine(kind, text) {{
  const row = document.createElement('div');
  row.className = 'entry';
  const time = new Date().toLocaleTimeString([], {{hour12: false}});
  row.innerHTML = '<span class="tag ' + kind + '">' + time.slice(0, 8) + '</span><span></span>';
  row.children[1].textContent = text;
  logEl.appendChild(row);
  logEl.scrollTop = logEl.scrollHeight;
  summaryEl.textContent = 'Activity — ' + text.slice(0, 60);
}}

let state = 'idle';
function setState(next, caption) {{
  state = next;
  orbWrap.dataset.state = next;
  dotEl.classList.toggle('live', next === 'recording' || next === 'thinking' || next === 'speaking');
  if (caption !== undefined) captionEl.textContent = caption;
}}

let socket = null;
let audioCtx = null;
let micStream = null;
let playHead = 0;
let micLevel = 0, outLevel = 0;

function frame() {{
  micLevel *= 0.85;
  outLevel *= 0.85;
  const level = state === 'speaking' ? outLevel : (state === 'recording' ? micLevel : 0);
  const breathing = (state === 'recording' || state === 'speaking' || state === 'thinking')
    ? 0 : 0.02 * Math.sin(Date.now() / 900);
  document.documentElement.style.setProperty('--x', '');
  orbWrap.style.setProperty('--glow', Math.min(1, level * 3.2).toFixed(3));
  orbWrap.style.setProperty('--scale', (1 + Math.min(0.22, level * 0.9) + breathing).toFixed(3));
  requestAnimationFrame(frame);
}}
requestAnimationFrame(frame);

function rms(float32) {{
  let sum = 0;
  for (let i = 0; i < float32.length; i++) sum += float32[i] * float32[i];
  return Math.sqrt(sum / float32.length);
}}

function downsampleTo24k(float32, inputRate) {{
  if (inputRate === 24000) return float32;
  const ratio = inputRate / 24000;
  const out = new Float32Array(Math.round(float32.length / ratio));
  for (let i = 0; i < out.length; i++) out[i] = float32[Math.floor(i * ratio)];
  return out;
}}
function floatTo16BitPCM(float32) {{
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {{
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }}
  return out;
}}
function bytesToBase64(bytes) {{
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}}
function base64ToInt16(b64) {{
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}}
function playPCM16Base64(b64) {{
  const int16 = base64ToInt16(b64);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 0x8000;
  outLevel = Math.max(outLevel, rms(float32));
  const buffer = audioCtx.createBuffer(1, float32.length, 24000);
  buffer.copyToChannel(float32, 0);
  const src = audioCtx.createBufferSource();
  src.buffer = buffer;
  src.connect(audioCtx.destination);
  const startAt = Math.max(audioCtx.currentTime, playHead);
  src.start(startAt);
  playHead = startAt + buffer.duration;
}}

async function callBackendTool(name, args) {{
  try {{
    const resp = await fetch('/voice/tool', {{
      method: 'POST', headers: {{'Content-Type':'application/json', 'X-Rally-Admin-Token': ADMIN_TOKEN}},
      body: JSON.stringify({{name, args}})
    }});
    return await resp.json();
  }} catch (err) {{
    return {{ok: false, reason: 'Tool call failed: ' + err}};
  }}
}}

async function startMic() {{
  micStream = await navigator.mediaDevices.getUserMedia({{audio: true}});
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioCtx.createMediaStreamSource(micStream);
  const processor = audioCtx.createScriptProcessor(4096, 1, 1);
  const mute = audioCtx.createGain();
  mute.gain.value = 0;
  source.connect(processor);
  processor.connect(mute);
  mute.connect(audioCtx.destination);
  processor.onaudioprocess = (e) => {{
    const input = e.inputBuffer.getChannelData(0);
    if (state !== 'recording') return;
    micLevel = Math.max(micLevel, rms(input));
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const down = downsampleTo24k(input, audioCtx.sampleRate);
    const pcm16 = floatTo16BitPCM(down);
    socket.send(JSON.stringify({{type: 'input_audio_buffer.append',
                                audio: bytesToBase64(new Uint8Array(pcm16.buffer))}}));
  }};
}}

function stopAll(nextCaption) {{
  if (socket) {{ try {{ socket.close(); }} catch (e) {{}} }}
  if (micStream) micStream.getTracks().forEach(t => t.stop());
  if (audioCtx) audioCtx.close();
  socket = null; micStream = null; audioCtx = null;
  setState('idle', nextCaption || 'Tap to connect');
}}

function beginRecording() {{
  setState('recording', 'Recording — tap to send');
}}

function endRecording() {{
  setState('thinking', 'Thinking…');
  socket.send(JSON.stringify({{type: 'input_audio_buffer.commit'}}));
  socket.send(JSON.stringify({{type: 'response.create'}}));
}}

async function start() {{
  setState('connecting', 'Connecting…');
  logLine('sys', 'requesting session');
  const resp = await fetch('/voice/session', {{method: 'POST',
    headers: {{'X-Rally-Admin-Token': ADMIN_TOKEN}}}});
  if (!resp.ok) {{
    logLine('err', 'session request failed: ' + resp.status);
    stopAll('Could not start (' + resp.status + ')');
    return;
  }}
  const config = await resp.json();
  await startMic();
  socket = new WebSocket('wss://api.x.ai/v1/realtime?model=' + encodeURIComponent(VOICE_MODEL),
                        ['xai-client-secret.' + config.ephemeral_token]);
  socket.addEventListener('open', () => {{
    logLine('sys', 'connected');
    setState('ready', 'Tap to start talking');
    socket.send(JSON.stringify({{type: 'session.update', session: config.session}}));
  }});
  socket.addEventListener('close', (event) => {{
    logLine('sys', 'closed (code ' + event.code + (event.reason ? ', ' + event.reason : '') + ')');
    stopAll();
  }});
  socket.addEventListener('error', () => logLine('err', 'socket error'));
  socket.addEventListener('message', async (event) => {{
    let msg;
    try {{ msg = JSON.parse(event.data); }} catch (e) {{ return; }}
    if (msg.type === 'response.output_audio.delta' && msg.delta) {{
      setState('speaking', 'Rally is speaking…');
      playPCM16Base64(msg.delta);
      return;
    }}
    if (msg.type === 'response.done') {{
      setState('ready', 'Tap to start talking');
      return;
    }}
    if (msg.type === 'response.function_call_arguments.done') {{
      let args = {{}};
      try {{ args = JSON.parse(msg.arguments || '{{}}'); }} catch (e) {{}}
      logLine('tool', msg.name + '(' + JSON.stringify(args) + ')');
      const result = await callBackendTool(msg.name, args);
      logLine('tool', '→ ' + JSON.stringify(result));
      socket.send(JSON.stringify({{type: 'conversation.item.create', item: {{
        type: 'function_call_output', call_id: msg.call_id, output: JSON.stringify(result)}}}}));
      socket.send(JSON.stringify({{type: 'response.create'}}));
      setState('thinking', 'Thinking…');
      return;
    }}
    if (msg.type === 'error') logLine('err', JSON.stringify(msg));
  }});
}}

orbWrap.addEventListener('click', () => {{
  if (state === 'idle') {{
    start().catch(err => {{ logLine('err', String(err)); stopAll('Error — tap to retry'); }});
    return;
  }}
  if (state === 'ready') {{ beginRecording(); return; }}
  if (state === 'recording') {{ endRecording(); return; }}
  // 'connecting', 'thinking', and 'speaking' ignore taps: turns are not interrupted.
}});
</script>
</body></html>"""
