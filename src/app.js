import {
  SAMPLE_RATE,
  MAX_DURATION,
  ROOMS,
  formatTime,
  audible,
  durationOf,
  createImpulse,
  createMixGraph,
  createDemo,
  protectPeak,
  encodeWav,
} from "./audio.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const tracks = [
  {
    kind: "backing",
    buffer: null,
    name: "",
    volume: 0.8,
    pan: 0,
    offset: 0,
    muted: false,
    solo: false,
    loading: false,
    token: 0,
  },
  {
    kind: "vocal",
    buffer: null,
    name: "",
    volume: 1,
    pan: 0,
    offset: 0,
    muted: false,
    solo: false,
    loading: false,
    token: 0,
  },
];
const settings = {
  master: 0.8,
  room: "studio",
  wet: 0.2,
  tone: 0,
  compress: false,
};
let context,
  graph,
  analysers,
  meterData,
  position = 0,
  startedAt = 0,
  playing = false,
  starting = false,
  exporting = false;
let animationFrame = 0,
  noticeTimer;
const impulses = new Map();
const trackElements = $$(".track");

function notify(message, error = false) {
  clearTimeout(noticeTimer);
  $("#notice > span").textContent = message;
  $("#notice").classList.toggle("error", error);
  $("#notice").hidden = false;
  noticeTimer = setTimeout(
    () => {
      $("#notice").hidden = true;
    },
    error ? 9000 : 5500,
  );
}
$("#notice button").addEventListener("click", () => {
  $("#notice").hidden = true;
});

function getContext() {
  if (!context) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext)
      throw new Error(
        "当前浏览器不支持 Web Audio，请使用新版 Chrome、Edge、Firefox 或 Safari。",
      );
    context = new AudioContext({ sampleRate: SAMPLE_RATE });
    const splitter = context.createChannelSplitter(2);
    analysers = [context.createAnalyser(), context.createAnalyser()];
    analysers.forEach((analyser, i) => {
      analyser.fftSize = 1024;
      splitter.connect(analyser, i);
    });
    meterData = analysers.map((a) => new Float32Array(a.fftSize));
    // The splitter is a separate analysis branch; the mix is connected to the destination once.
    context.mixAnalyserInput = splitter;
    context.addEventListener("statechange", () => {
      if (playing && context.state !== "running") {
        pause();
        notify("音频已暂停，点击播放继续。");
      }
    });
  }
  return context;
}

function impulseFor(ctx, room) {
  const key = `${ctx.sampleRate}:${room}`;
  if (!impulses.has(key)) impulses.set(key, createImpulse(ctx, room));
  return impulses.get(key);
}

function totalDuration() {
  return durationOf(tracks, settings);
}
function currentPosition() {
  return playing
    ? Math.min(totalDuration(), position + context.currentTime - startedAt)
    : position;
}

function stopGraph() {
  cancelAnimationFrame(animationFrame);
  if (graph) {
    for (const node of graph.nodes.filter(Boolean)) {
      try {
        node.source.stop();
      } catch {}
    }
    graph.disconnect();
    graph = null;
  }
}

function pause() {
  if (playing) position = currentPosition();
  playing = false;
  stopGraph();
  updateTransport();
  drawWaveforms();
  updateMeters(true);
}

async function play() {
  if (
    playing ||
    starting ||
    totalDuration() <= 0 ||
    exporting ||
    tracks.some((t) => t.loading)
  )
    return;
  starting = true;
  try {
    const ctx = getContext();
    await ctx.resume();
    if (totalDuration() <= 0 || tracks.some((t) => t.loading) || exporting)
      return;
    if (position >= totalDuration() - 0.01) position = 0;
    graph = createMixGraph(
      ctx,
      tracks,
      settings,
      ctx.destination,
      impulseFor(ctx, settings.room),
      position,
    );
    graph.master.connect(ctx.mixAnalyserInput);
    const start = ctx.currentTime + 0.02;
    graph.nodes.forEach((node) => {
      if (node?.schedule)
        node.source.start(
          start + node.schedule.delay,
          node.schedule.sourceOffset,
        );
    });
    startedAt = start;
    playing = true;
    updateTransport();
    tick();
  } catch (error) {
    playing = false;
    stopGraph();
    updateTransport();
    notify(error.message || "无法启动播放，请重试。", true);
  } finally {
    starting = false;
  }
}

function seekTo(value) {
  const wasPlaying = playing;
  pause();
  position = Math.max(0, Math.min(totalDuration(), value));
  updateTransport();
  drawWaveforms();
  if (wasPlaying) void play();
}

function tick() {
  if (!playing) return;
  if (currentPosition() >= totalDuration()) {
    pause();
    position = totalDuration();
    updateTransport();
    drawWaveforms();
    return;
  }
  updateTransport();
  updateMeters();
  drawWaveforms();
  animationFrame = requestAnimationFrame(tick);
}

function updateMeters(reset = false) {
  ["#meter-left", "#meter-right"].forEach((selector, i) => {
    let peak = 0;
    if (!reset && analysers) {
      analysers[i].getFloatTimeDomainData(meterData[i]);
      for (const sample of meterData[i])
        peak = Math.max(peak, Math.abs(sample));
    }
    const db = peak > 0 ? 20 * Math.log10(peak) : -60;
    $(selector).style.width =
      `${Math.max(0, Math.min(100, ((db + 60) / 60) * 100))}%`;
  });
}

function updateTransport() {
  const duration = totalDuration();
  const pos = Math.max(0, Math.min(duration, currentPosition()));
  const time = formatTime(pos, true).split(".");
  $("#current-time").innerHTML = `${time[0]}<span>.${time[1]}</span>`;
  $("#total-time").textContent = formatTime(duration);
  $("#timeline-duration").textContent = `总时长 ${formatTime(duration)}`;
  $("#seek").max = duration || 1;
  $("#seek").value = pos;
  $("#seek").setAttribute(
    "aria-valuetext",
    `${formatTime(pos)} / ${formatTime(duration)}`,
  );
  $("#play-button").classList.toggle("playing", playing);
  $("#play-button").setAttribute("aria-label", playing ? "暂停" : "播放");
  $("#play-button use").setAttribute("href", playing ? "#i-pause" : "#i-play");
}

function updateUI() {
  const loaded = tracks.some((t) => t.buffer);
  const busy = tracks.some((t) => t.loading) || exporting;
  const duration = totalDuration();
  const hasAudible =
    tracks.some(
      (t) =>
        audible(t, tracks) && t.volume > 0 && t.buffer.duration + t.offset > 0,
    ) && settings.master > 0;
  trackElements.forEach((element, i) => {
    const track = tracks[i];
    element.classList.toggle("busy", track.loading);
    element.classList.toggle(
      "is-quiet",
      Boolean(track.buffer && !audible(track, tracks)),
    );
    element.querySelector(".dropzone").hidden = Boolean(track.buffer);
    element.querySelector(".loaded-track").hidden = !track.buffer;
    element.querySelector(".filename").textContent = track.name;
    element.querySelector(".file-duration").textContent = track.buffer
      ? formatTime(track.buffer.duration)
      : "";
    element.querySelector(".mute").setAttribute("aria-pressed", track.muted);
    element.querySelector(".solo").setAttribute("aria-pressed", track.solo);
    element.querySelector(".volume-value").innerHTML =
      `${Math.round(track.volume * 100)}<span>%</span>`;
    element.querySelectorAll("button,input").forEach((control) => {
      control.disabled = exporting || track.loading;
    });
    [".mute", ".solo"].forEach((selector) => {
      element.querySelector(selector).disabled =
        !track.buffer || exporting || track.loading;
    });
  });
  $("#play-button").disabled = !loaded || duration <= 0 || busy;
  $("#rewind").disabled = !loaded || busy;
  $("#seek").disabled = !loaded || duration <= 0 || busy;
  $("#clear-button").disabled = !loaded || busy;
  $("#demo-button").disabled = busy;
  $("#export-button").disabled =
    !loaded || duration <= 0 || !hasAudible || busy;
  $("#export-button > span").textContent = exporting ? "正在合成…" : "导出混音";
  $("#export-hint").textContent = exporting
    ? "正在本地渲染音频，请稍候"
    : !loaded
      ? "添加音轨，开始你的创作"
      : !hasAudible
        ? "请启用至少一条音轨，并提高音量"
        : `完整混音 · ${formatTime(duration)} · 包含效果尾音`;
  $$(
    ".effects-panel input,.effects-panel select,.effects-panel button,.output-panel input,.alignment input,.alignment button",
  ).forEach((control) => {
    control.disabled = exporting;
  });
  $("#wet-value").textContent = `${Math.round(settings.wet * 100)}%`;
  $("#tone-value").textContent =
    `${settings.tone > 0 ? "+" : ""}${settings.tone} dB`;
  $("#master-value").textContent = Math.round(settings.master * 100);
  $("#master-volume").style.background =
    `linear-gradient(90deg,var(--orange) ${settings.master * 100}%,#4a5e3b ${settings.master * 100}%)`;
  const rulerDuration = duration || 25;
  $("#ruler")
    .querySelectorAll("span")
    .forEach((span, i) => {
      span.textContent = formatTime((rulerDuration * i) / 5);
    });
  if (!playing) position = Math.min(position, duration);
  updateTransport();
  drawWaveforms();
}

function syncGraph() {
  if (graph && context) {
    const now = context.currentTime;
    graph.nodes.forEach((node, i) => {
      if (!node) return;
      node.gain.gain.setTargetAtTime(
        audible(tracks[i], tracks) ? tracks[i].volume : 0,
        now,
        0.015,
      );
      node.pan.pan.setTargetAtTime(tracks[i].pan, now, 0.015);
      if (node.tone) {
        node.tone.gain.setTargetAtTime(settings.tone, now, 0.02);
        node.dry.gain.setTargetAtTime(1 - settings.wet * 0.45, now, 0.02);
        node.wet.gain.setTargetAtTime(settings.wet, now, 0.02);
      }
    });
    graph.master.gain.setTargetAtTime(settings.master, now, 0.015);
    graph.bypass.gain.setTargetAtTime(settings.compress ? 0 : 1, now, 0.015);
    graph.compressed.gain.setTargetAtTime(
      settings.compress ? 1 : 0,
      now,
      0.015,
    );
  }
  updateUI();
}

function buildPeaks(buffer) {
  const bins = 1200;
  const peaks = new Float32Array(bins);
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const data = buffer.getChannelData(c);
    for (let bin = 0; bin < bins; bin++) {
      const start = Math.floor((bin * data.length) / bins),
        end = Math.floor(((bin + 1) * data.length) / bins);
      const step = Math.max(1, Math.floor((end - start) / 100));
      for (let i = start; i < end; i += step)
        peaks[bin] = Math.max(peaks[bin], Math.abs(data[i]));
    }
  }
  return peaks;
}

function drawWaveforms() {
  const duration = totalDuration();
  if (!duration) return;
  const pos = Math.max(0, currentPosition());
  tracks.forEach((track, i) => {
    if (!track.buffer) return;
    const canvas = trackElements[i].querySelector("canvas");
    const width = canvas.clientWidth,
      height = canvas.clientHeight;
    if (!width) return;
    const ratio = window.devicePixelRatio || 1;
    if (
      canvas.width !== Math.round(width * ratio) ||
      canvas.height !== Math.round(height * ratio)
    ) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    const painter = canvas.getContext("2d");
    painter.setTransform(ratio, 0, 0, ratio, 0, 0);
    painter.clearRect(0, 0, width, height);
    painter.strokeStyle = i === 0 ? "#b6c8a41c" : "#b7acd51c";
    painter.lineWidth = 1;
    painter.beginPath();
    painter.moveTo(0, height / 2);
    painter.lineTo(width, height / 2);
    painter.stroke();
    for (let x = 0; x < width; x += 3) {
      const t = (x / width) * duration - track.offset;
      if (t < 0 || t >= track.buffer.duration) continue;
      const peak =
        track.peaks[
          Math.min(
            track.peaks.length - 1,
            Math.floor((t / track.buffer.duration) * track.peaks.length),
          )
        ];
      painter.fillStyle =
        (x / width) * duration <= pos
          ? "#efa572"
          : i === 0
            ? "#a8c28a"
            : "#b0a0d1";
      const amplitude = Math.max(1.5, peak * height * 0.85);
      painter.fillRect(x, (height - amplitude) / 2, 1.5, amplitude);
    }
    const cursor = (pos / duration) * width;
    painter.fillStyle = "#f1e7cf";
    painter.fillRect(cursor, 0, 1, height);
  });
}

async function loadFile(file, index) {
  if (!file || exporting) return;
  const track = tracks[index];
  const token = ++track.token;
  if (file.size > 100 * 1024 * 1024) {
    notify("文件超过 100 MB，请先压缩或裁剪音频。", true);
    return;
  }
  pause();
  track.loading = true;
  updateUI();
  try {
    const ctx = getContext();
    const buffer = await ctx.decodeAudioData(await file.arrayBuffer());
    if (track.token !== token) return;
    if (buffer.duration > MAX_DURATION)
      throw new Error("单条音轨最长支持 20 分钟，请先裁剪音频。");
    if (buffer.duration <= 0) throw new Error("音频没有可用内容，请更换文件。");
    Object.assign(track, {
      buffer,
      name: file.name,
      peaks: buildPeaks(buffer),
      demo: false,
    });
    position = 0;
    notify(
      `${index === 0 ? "伴奏" : "人声"}已就绪 · ${formatTime(buffer.duration)}`,
    );
  } catch (error) {
    if (track.token !== token) return;
    notify(
      error.name === "EncodingError" || error.name === "NotSupportedError"
        ? "无法解码此文件。请尝试标准 WAV 或 MP3 格式。"
        : error.message || "文件读取失败，请重试。",
      true,
    );
  } finally {
    if (track.token === token) {
      track.loading = false;
      $(`#file-${index}`).value = "";
      updateUI();
    }
  }
}

trackElements.forEach((element, index) => {
  const track = tracks[index];
  const input = element.querySelector("input[type=file]");
  element
    .querySelector(".dropzone")
    .addEventListener("click", () => input.click());
  element
    .querySelector(".replace-button")
    .addEventListener("click", () => input.click());
  input.addEventListener("change", () => void loadFile(input.files[0], index));
  element.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (!exporting && !track.loading) element.classList.add("dragging");
  });
  element.addEventListener("dragleave", (event) => {
    if (!element.contains(event.relatedTarget))
      element.classList.remove("dragging");
  });
  element.addEventListener("drop", (event) => {
    event.preventDefault();
    element.classList.remove("dragging");
    if (track.loading || exporting) return;
    const files = event.dataTransfer.files;
    if (files.length > 1) {
      notify("请每次为一条音轨选择一个音频文件。", true);
      return;
    }
    void loadFile(files[0], index);
  });
  element.querySelector(".volume").addEventListener("input", (event) => {
    track.volume = Number(event.target.value) / 100;
    syncGraph();
  });
  element.querySelector(".pan").addEventListener("input", (event) => {
    track.pan = Number(event.target.value) / 100;
    syncGraph();
  });
  for (const [selector, key] of [
    [".mute", "muted"],
    [".solo", "solo"],
  ])
    element.querySelector(selector).addEventListener("click", () => {
      track[key] = !track[key];
      syncGraph();
    });
  element
    .querySelector(".waveform-button")
    .addEventListener("click", (event) => {
      if (exporting) return;
      const rect = event.currentTarget.getBoundingClientRect();
      seekTo(((event.clientX - rect.left) / rect.width) * totalDuration());
    });
});

// Prevent dropping an audio file outside an upload target from navigating away.
document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", (event) => event.preventDefault());
$("#play-button").addEventListener("click", () =>
  playing ? pause() : void play(),
);
$("#rewind").addEventListener("click", () => seekTo(0));
$("#seek").addEventListener("input", (event) =>
  seekTo(Number(event.target.value)),
);
document.addEventListener("keydown", (event) => {
  if (
    event.target.closest("input,select,textarea,button,a,[contenteditable]") ||
    event.ctrlKey ||
    event.altKey ||
    event.metaKey ||
    exporting
  )
    return;
  if (event.code === "Space") {
    event.preventDefault();
    if (!event.repeat) playing ? pause() : void play();
  }
  if (event.code === "Home") {
    event.preventDefault();
    seekTo(0);
  }
});

function setOffset(value) {
  const wasPlaying = playing;
  pause();
  const ms = Math.max(-30000, Math.min(30000, Math.round(Number(value) || 0)));
  tracks[1].offset = ms / 1000;
  $("#offset").value = ms;
  updateUI();
  if (wasPlaying) void play();
}
$("#offset").addEventListener("change", (event) =>
  setOffset(event.target.value),
);
$("#offset-minus").addEventListener("click", () =>
  setOffset(tracks[1].offset * 1000 - 50),
);
$("#offset-plus").addEventListener("click", () =>
  setOffset(tracks[1].offset * 1000 + 50),
);
$("#master-volume").addEventListener("input", (event) => {
  settings.master = Number(event.target.value) / 100;
  syncGraph();
});
$("#wet").addEventListener("input", (event) => {
  settings.wet = Number(event.target.value) / 100;
  syncGraph();
});
$("#tone").addEventListener("input", (event) => {
  settings.tone = Number(event.target.value);
  syncGraph();
});
$("#compress").addEventListener("change", (event) => {
  settings.compress = event.target.checked;
  syncGraph();
});
$("#room").addEventListener("change", (event) => {
  settings.room = event.target.value;
  if (graph)
    graph.nodes.forEach((node) => {
      if (node?.reverb) node.reverb.buffer = impulseFor(context, settings.room);
    });
  updateUI();
});
$("#effects-reset").addEventListener("click", () => {
  settings.room = "studio";
  settings.wet = 0.2;
  settings.tone = 0;
  $("#room").value = "studio";
  $("#wet").value = 20;
  $("#tone").value = 0;
  if (graph)
    graph.nodes.forEach((node) => {
      if (node?.reverb) node.reverb.buffer = impulseFor(context, settings.room);
    });
  syncGraph();
});

$("#clear-button").addEventListener("click", () => {
  pause();
  position = 0;
  tracks.forEach((track, i) => {
    Object.assign(track, {
      buffer: null,
      name: "",
      peaks: null,
      volume: i === 0 ? 0.8 : 1,
      pan: 0,
      offset: 0,
      muted: false,
      solo: false,
      loading: false,
      token: track.token + 1,
    });
    trackElements[i].querySelector(".volume").value = track.volume * 100;
    trackElements[i].querySelector(".pan").value = 0;
    $(`#file-${i}`).value = "";
  });
  $("#offset").value = 0;
  updateUI();
  notify("工程已清空，可以开始新的创作。");
});

$("#demo-button").addEventListener("click", async () => {
  if (tracks.some((t) => t.buffer && !t.demo)) {
    notify("请先清空当前工程，再加载示例，以保留你导入的音频。");
    return;
  }
  pause();
  try {
    const ctx = getContext();
    const buffers = createDemo(ctx);
    buffers.forEach((buffer, i) => {
      Object.assign(tracks[i], {
        buffer,
        name:
          i === 0 ? "Midnight Garden · 伴奏.wav" : "Soft Light · 合成旋律.wav",
        peaks: buildPeaks(buffer),
        demo: true,
        muted: false,
        solo: false,
        offset: 0,
      });
    });
    $("#offset").value = 0;
    position = 0;
    updateUI();
    notify("示例已加载，点击播放体验混音。旋律为合成音色，非真实人声。");
  } catch (error) {
    notify(error.message, true);
  }
});

$("#export-button").addEventListener("click", async () => {
  if (exporting || tracks.some((t) => t.loading) || !totalDuration()) return;
  pause();
  exporting = true;
  updateUI();
  // Freeze a snapshot so exported sound always reflects the settings at click time.
  const snapshot = tracks.map((t) => ({ ...t }));
  const mixSettings = { ...settings };
  const protection = $("#protect-peak").checked;
  let offlineGraph;
  try {
    const OfflineContext =
      window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!OfflineContext)
      throw new Error(
        "此浏览器不支持离线混音导出，请使用新版 Chrome、Edge 或 Firefox。",
      );
    await new Promise((resolve) =>
      requestAnimationFrame(() => setTimeout(resolve, 0)),
    );
    const offline = new OfflineContext(
      2,
      Math.ceil(durationOf(snapshot, mixSettings) * SAMPLE_RATE),
      SAMPLE_RATE,
    );
    offlineGraph = createMixGraph(
      offline,
      snapshot,
      mixSettings,
      offline.destination,
      impulseFor(offline, mixSettings.room),
    );
    offlineGraph.nodes.forEach((node) => {
      if (node?.schedule)
        node.source.start(node.schedule.delay, node.schedule.sourceOffset);
    });
    const rendered = await offline.startRendering();
    const channels = [rendered.getChannelData(0), rendered.getChannelData(1)];
    if (protection) protectPeak(channels);
    const wav = encodeWav(channels, SAMPLE_RATE);
    const filename = `MIXROOM-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}.wav`;
    if (window.mixroomDesktop) {
      const result = await window.mixroomDesktop.saveWav(wav, filename);
      notify(result.canceled ? '已取消保存，音轨仍保留在工程中。' : `混音已保存 · ${(wav.byteLength / 1024 / 1024).toFixed(1)} MB · WAV 立体声`);
      return;
    }
    const blob = new Blob([wav], {
      type: "audio/wav",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    notify(
      `混音已导出 · ${(blob.size / 1024 / 1024).toFixed(1)} MB · WAV 立体声`,
    );
  } catch (error) {
    notify(
      error.name === "RangeError"
        ? "内存不足，请尝试更短的音频，或关闭其他标签页后重试。"
        : `导出失败：${error.message || "请重试"}`,
      true,
    );
  } finally {
    offlineGraph?.disconnect();
    exporting = false;
    updateUI();
  }
});

new ResizeObserver(() => drawWaveforms()).observe($(".studio"));
window.addEventListener("pagehide", () => {
  pause();
  void context?.suspend();
});
updateUI();
