"""Owner-only browser page: raw WebSocket client for xAI Grok Voice.

Talks to xAI directly from the browser using a short-lived ephemeral token
minted by /voice/session. Tool calls are relayed back to /voice/tool, which
runs with server-side access to private relationship and plan data -- the
browser itself never touches the database or the long-lived xAI key.
"""


def render_voice_page(admin_token: str, voice_model: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Rally Voice</title>
<style>
body {{ font-family: -apple-system, sans-serif; background:#0b0b0f; color:#eee; margin:0; padding:24px; }}
button {{ font-size:16px; padding:10px 20px; border-radius:8px; border:none; cursor:pointer; }}
#toggle {{ background:#3a8; color:#fff; }}
#toggle.live {{ background:#c33; }}
#status {{ margin:12px 0; color:#9ad; }}
#log {{ font-family: ui-monospace, monospace; font-size:12px; white-space:pre-wrap;
        background:#151519; border-radius:8px; padding:12px; height:60vh; overflow-y:auto; }}
</style></head>
<body>
<h2>Rally Voice</h2>
<button id="toggle">Start talking</button>
<div id="status">idle</div>
<div id="log"></div>
<script>
const ADMIN_TOKEN = {admin_token!r};
const VOICE_MODEL = {voice_model!r};
const logEl = document.getElementById('log');
const statusEl = document.getElementById('status');
const toggleEl = document.getElementById('toggle');
function log(line) {{
  logEl.textContent += line + "\\n";
  logEl.scrollTop = logEl.scrollHeight;
}}
function setStatus(text) {{ statusEl.textContent = text; }}

let socket = null;
let audioCtx = null;
let micStream = null;
let playHead = 0;

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
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const input = e.inputBuffer.getChannelData(0);
    const down = downsampleTo24k(input, audioCtx.sampleRate);
    const pcm16 = floatTo16BitPCM(down);
    socket.send(JSON.stringify({{type: 'input_audio_buffer.append',
                                audio: bytesToBase64(new Uint8Array(pcm16.buffer))}}));
  }};
}}

function stopAll() {{
  if (socket) {{ try {{ socket.close(); }} catch (e) {{}} }}
  if (micStream) micStream.getTracks().forEach(t => t.stop());
  if (audioCtx) audioCtx.close();
  socket = null; micStream = null; audioCtx = null;
  toggleEl.textContent = 'Start talking';
  toggleEl.classList.remove('live');
  setStatus('idle');
}}

async function start() {{
  setStatus('starting session...');
  const resp = await fetch('/voice/session', {{method: 'POST',
    headers: {{'X-Rally-Admin-Token': ADMIN_TOKEN}}}});
  if (!resp.ok) {{ setStatus('session failed: ' + resp.status); return; }}
  const config = await resp.json();
  await startMic();
  socket = new WebSocket('wss://api.x.ai/v1/realtime?model=' + encodeURIComponent(VOICE_MODEL),
                        ['xai-client-secret.' + config.ephemeral_token]);
  socket.addEventListener('open', () => {{
    setStatus('connected -- listening');
    toggleEl.textContent = 'Stop';
    toggleEl.classList.add('live');
    socket.send(JSON.stringify({{type: 'session.update', session: config.session}}));
  }});
  socket.addEventListener('close', () => {{ log('socket closed'); stopAll(); }});
  socket.addEventListener('error', (e) => log('socket error'));
  socket.addEventListener('message', async (event) => {{
    let msg;
    try {{ msg = JSON.parse(event.data); }} catch (e) {{ return; }}
    if (msg.type === 'response.output_audio.delta' && msg.delta) {{
      playPCM16Base64(msg.delta);
      return;
    }}
    if (msg.type === 'response.function_call_arguments.done') {{
      let args = {{}};
      try {{ args = JSON.parse(msg.arguments || '{{}}'); }} catch (e) {{}}
      log('tool -> ' + msg.name + ' ' + JSON.stringify(args));
      const result = await callBackendTool(msg.name, args);
      log('tool <- ' + JSON.stringify(result));
      socket.send(JSON.stringify({{type: 'conversation.item.create', item: {{
        type: 'function_call_output', call_id: msg.call_id, output: JSON.stringify(result)}}}}));
      socket.send(JSON.stringify({{type: 'response.create'}}));
      return;
    }}
    if (msg.type === 'error') log('error: ' + JSON.stringify(msg));
  }});
}}

toggleEl.addEventListener('click', () => {{
  if (socket) stopAll(); else start().catch(err => setStatus('error: ' + err));
}});
</script>
</body></html>"""
