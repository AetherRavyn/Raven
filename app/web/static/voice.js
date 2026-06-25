// v33 — Browser voice glue for the RAVEN dashboard chat page.
//
// Connects to /voice/{user_id} as a WebSocketVoiceSink so TTS
// audio plays out of the user's speakers.  Also wires the 🎙
// mic button to MediaRecorder so the user can dictate messages
// instead of typing.
//
// Wire format (server → client):
//   First frame:    JSON {"type": "voice_info", "personality": ...}
//   Audio frames:   4-byte little-endian uint32 sample rate
//                   + raw 16-bit PCM mono WAV bytes
//
// Wire format (client → server):
//   JSON {"type": "ping"}   — keepalive
//   JSON {"type": "stop"}   — interrupt current play
//
// Usage:
//   Import this script on the chat page; it auto-binds to the
//   #mic-button and #chat-log elements if they exist.

(function () {
  "use strict";

  // ── 1. Resolve the current user_id from the URL ───────────────────
  // The dashboard pattern is /chat/{user_id}; the same id is
  // used for the voice channel so the orchestrator's reply
  // routes to the right sink.
  function currentUserId() {
    var m = window.location.pathname.match(/^\/(?:chat|voice)\/([^/]+)/);
    if (m) return m[1];
    // Fallback for /chat (no user_id) — use a stable session id.
    var sid = window.sessionStorage.getItem("raven_uid");
    if (!sid) {
      sid = "anon-" + Math.random().toString(36).slice(2, 10);
      window.sessionStorage.setItem("raven_uid", sid);
    }
    return sid;
  }

  // ── 2. AudioContext that handles variable sample rates ────────────
  // The server sends a 4-byte LE uint32 prefix with each frame
  // carrying the sample rate of the WAV blob.  We construct one
  // AudioContext per unique rate and cache it.
  var audioContexts = {};
  function audioContextFor(rate) {
    if (!audioContexts[rate]) {
      audioContexts[rate] = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: rate,
      });
    }
    return audioContexts[rate];
  }

  // ── 3. Play one binary frame ──────────────────────────────────────
  function playWavFrame(ab) {
    if (!ab || ab.byteLength < 4) return;
    var dv = new DataView(ab);
    var sampleRate = dv.getUint32(0, true);
    var wavBytes = new Uint8Array(ab, 4);

    var ctx = audioContextFor(sampleRate);
    return new Promise(function (resolve) {
      ctx.decodeAudioData(wavBytes.buffer.slice(wavBytes.byteOffset, wavBytes.byteOffset + wavBytes.byteLength), function (audio) {
        var src = ctx.createBufferSource();
        src.buffer = audio;
        src.connect(ctx.destination);
        src.onended = resolve;
        src.start(0);
      }, function (err) {
        console.warn("voice.js: decodeAudioData failed", err);
        resolve();
      });
    });
  }

  // ── 4. WebSocket lifecycle ────────────────────────────────────────
  var ws = null;
  var queue = Promise.resolve();

  function connect() {
    var userId = encodeURIComponent(currentUserId());
    var proto = window.location.protocol === "https:" ? "wss" : "ws";
    var url = proto + "://" + window.location.host + "/voice/" + userId;
    ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";

    ws.onopen = function () {
      console.log("voice.js: connected as", userId);
    };

    ws.onmessage = function (ev) {
      if (typeof ev.data === "string") {
        // JSON control frame
        try {
          var msg = JSON.parse(ev.data);
          if (msg.type === "voice_info") {
            var span = document.getElementById("voice-name");
            if (span && msg.personality) span.textContent = msg.personality;
          } else if (msg.type === "stop_ack") {
            console.log("voice.js: stop acknowledged");
          } else if (msg.type === "pong") {
            // keepalive response
          }
        } catch (e) {
          // ignore malformed JSON
        }
        return;
      }
      // Binary audio frame
      queue = queue.then(function () { return playWavFrame(ev.data); });
    };

    ws.onclose = function () {
      console.log("voice.js: disconnected — retry in 2s");
      ws = null;
      setTimeout(connect, 2000);
    };

    ws.onerror = function (err) {
      console.warn("voice.js: WS error", err);
    };
  }

  // ── 5. 🎙 mic button → MediaRecorder ─────────────────────────────
  function bindMicButton() {
    var btn = document.getElementById("mic-button");
    if (!btn) return;
    var mediaRecorder = null;
    var chunks = [];
    var recording = false;

    btn.addEventListener("mousedown", startRecording);
    btn.addEventListener("touchstart", startRecording);
    btn.addEventListener("mouseup", stopRecording);
    btn.addEventListener("mouseleave", stopRecording);
    btn.addEventListener("touchend", stopRecording);

    function startRecording(e) {
      if (e && e.preventDefault) e.preventDefault();
      if (recording) return;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.warn("voice.js: MediaRecorder not supported");
        return;
      }
      navigator.mediaDevices
        .getUserMedia({ audio: true })
        .then(function (stream) {
          mediaRecorder = new MediaRecorder(stream);
          chunks = [];
          mediaRecorder.ondataavailable = function (e) {
            if (e.data && e.data.size > 0) chunks.push(e.data);
          };
          mediaRecorder.onstop = function () {
            var blob = new Blob(chunks, { type: "audio/webm" });
            uploadUtterance(blob);
            stream.getTracks().forEach(function (t) { t.stop(); });
          };
          mediaRecorder.start();
          recording = true;
          btn.classList.add("bg-red-600");
        })
        .catch(function (err) {
          console.warn("voice.js: getUserMedia failed", err);
        });
    }

    function stopRecording() {
      if (!recording) return;
      recording = false;
      btn.classList.remove("bg-red-600");
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
      }
    }
  }

  // ── 6. Upload the recorded blob to /api/voice/transcribe ──────────
  function uploadUtterance(blob) {
    var fd = new FormData();
    fd.append("audio", blob, "utterance.webm");
    var userId = encodeURIComponent(currentUserId());
    fetch("/api/voice/transcribe?user_id=" + userId, {
      method: "POST",
      body: fd,
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.text) {
          var input = document.querySelector('input[name="text"]');
          if (input) {
            input.value = data.text;
            input.form && input.form.dispatchEvent(new Event("submit", { cancelable: true }));
          }
        }
      })
      .catch(function (err) {
        console.warn("voice.js: upload failed", err);
      });
  }

  // ── 7. Boot ───────────────────────────────────────────────────────
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      connect();
      bindMicButton();
    });
  } else {
    connect();
    bindMicButton();
  }
})();
