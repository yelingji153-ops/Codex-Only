export const SAMPLE_RATE = 44100;
export const MAX_DURATION = 1200;
export const ROOMS = {
  small: { seconds: 0.65, decay: 3.5 },
  studio: { seconds: 1.6, decay: 2.8 },
  hall: { seconds: 3.2, decay: 2.1 },
};

export function formatTime(seconds, precise = false) {
  const t = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  return `${Math.floor(t / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(t % 60)
    .toString()
    .padStart(2, "0")}${
    precise
      ? `.${Math.floor((t % 1) * 100)
          .toString()
          .padStart(2, "0")}`
      : ""
  }`;
}

export function audible(track, tracks) {
  return Boolean(
    track.buffer &&
      !track.muted &&
      (!tracks.some((t) => t.buffer && t.solo) || track.solo),
  );
}

export function durationOf(tracks, effects) {
  const duration = Math.max(
    0,
    ...tracks
      .filter((t) => t.buffer)
      .map((t) => {
        const tail =
          t.kind === "vocal" &&
          effects.wet > 0 &&
          audible(t, tracks) &&
          t.volume > 0
            ? ROOMS[effects.room].seconds
            : 0;
        return (
          Math.max(0, t.buffer.duration + t.offset) +
          (t.buffer.duration + t.offset > 0 ? tail : 0)
        );
      }),
  );
  // The Web Audio compressor has a fixed 6 ms look-ahead delay.
  return duration + (duration > 0 && effects.compress ? 0.006 : 0);
}

// Negative offsets trim material before timeline zero.
export function scheduleTrack(duration, offset, position) {
  const sourceOffset = Math.max(0, position - offset);
  return sourceOffset >= duration
    ? null
    : { delay: Math.max(0, offset - position), sourceOffset };
}

export function createImpulse(context, room) {
  const preset = ROOMS[room];
  const length = Math.ceil(context.sampleRate * preset.seconds);
  const buffer = context.createBuffer(2, length, context.sampleRate);
  let seed = 4027;
  for (let c = 0; c < 2; c++) {
    const data = buffer.getChannelData(c);
    for (let i = 0; i < length; i++) {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      const onset = Math.min(1, i / (context.sampleRate * 0.012));
      data[i] =
        (seed / 2147483648 - 1) * (1 - i / length) ** preset.decay * onset;
    }
  }
  return buffer;
}

export function createMixGraph(
  context,
  tracks,
  settings,
  destination,
  impulse,
  position = 0,
) {
  const master = context.createGain();
  master.gain.value = settings.master;
  const bus = context.createGain();
  const bypass = context.createGain();
  const compressed = context.createGain();
  bypass.gain.value = settings.compress ? 0 : 1;
  compressed.gain.value = settings.compress ? 1 : 0;
  const compressor = context.createDynamicsCompressor();
  compressor.threshold.value = -18;
  compressor.knee.value = 18;
  compressor.ratio.value = 3;
  compressor.attack.value = 0.008;
  compressor.release.value = 0.2;
  bus.connect(compressor).connect(compressed).connect(master);
  bus.connect(bypass).connect(master).connect(destination);
  const nodes = tracks.map((track) => {
    if (!track.buffer) return null;
    const source = context.createBufferSource();
    const gain = context.createGain();
    const pan = context.createStereoPanner();
    source.buffer = track.buffer;
    gain.gain.value = audible(track, tracks) ? track.volume : 0;
    pan.pan.value = track.pan;
    source.connect(gain).connect(pan);
    const result = {
      source,
      gain,
      pan,
      schedule: scheduleTrack(track.buffer.duration, track.offset, position),
    };
    if (track.kind === "vocal") {
      const tone = context.createBiquadFilter();
      tone.type = "highshelf";
      tone.frequency.value = 2500;
      tone.gain.value = settings.tone;
      const dry = context.createGain();
      dry.gain.value = 1 - settings.wet * 0.45;
      const wet = context.createGain();
      wet.gain.value = settings.wet;
      const reverb = context.createConvolver();
      reverb.buffer = impulse;
      pan.connect(tone);
      tone.connect(dry).connect(bus);
      tone.connect(reverb).connect(wet).connect(bus);
      Object.assign(result, { tone, dry, wet, reverb });
    } else pan.connect(bus);
    return result;
  });
  return {
    nodes,
    master,
    compressor,
    bypass,
    compressed,
    disconnect() {
      for (const node of nodes.filter(Boolean))
        for (const value of Object.values(node))
          if (value?.disconnect) value.disconnect();
      master.disconnect();
      compressor.disconnect();
      bus.disconnect();
      bypass.disconnect();
      compressed.disconnect();
    },
  };
}

export function protectPeak(channels, ceiling = 10 ** (-1 / 20)) {
  let peak = 0;
  for (const channel of channels)
    for (const sample of channel) peak = Math.max(peak, Math.abs(sample));
  const scale = peak > ceiling ? ceiling / peak : 1;
  if (scale < 1)
    for (const channel of channels)
      for (let i = 0; i < channel.length; i++) channel[i] *= scale;
  return scale;
}

export function encodeWav(channels, sampleRate) {
  if (!channels.length || channels.some((c) => c.length !== channels[0].length))
    throw new Error("Invalid audio channels");
  const bytes = channels[0].length * channels.length * 2;
  const data = new ArrayBuffer(44 + bytes);
  const view = new DataView(data);
  const write = (offset, text) => {
    for (let i = 0; i < text.length; i++)
      view.setUint8(offset + i, text.charCodeAt(i));
  };
  write(0, "RIFF");
  view.setUint32(4, 36 + bytes, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels.length, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels.length * 2, true);
  view.setUint16(32, channels.length * 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, bytes, true);
  let offset = 44;
  for (let frame = 0; frame < channels[0].length; frame++)
    for (const channel of channels) {
      const sample = Math.max(-1, Math.min(1, channel[frame]));
      view.setInt16(
        offset,
        Math.round(sample * (sample < 0 ? 32768 : 32767)),
        true,
      );
      offset += 2;
    }
  return data;
}

export function createDemo(context) {
  const duration = 18;
  const backing = context.createBuffer(
    2,
    context.sampleRate * duration,
    context.sampleRate,
  );
  const vocal = context.createBuffer(
    1,
    context.sampleRate * duration,
    context.sampleRate,
  );
  const chords = [
    [130.81, 164.81, 196],
    [110, 130.81, 164.81],
    [87.31, 110, 130.81],
    [98, 123.47, 146.83],
  ];
  for (let c = 0; c < 2; c++) {
    const data = backing.getChannelData(c);
    for (let i = 0; i < data.length; i++) {
      const t = i / context.sampleRate,
        beat = t % 0.5;
      const chord = chords[Math.floor(t / 3) % 4];
      const pad =
        chord.reduce(
          (s, f) => s + Math.sin(2 * Math.PI * (f + c * 0.25) * t),
          0,
        ) * 0.065;
      const kick =
        Math.sin(2 * Math.PI * (45 * beat + 8 * (1 - Math.exp(-beat * 30)))) *
        Math.exp(-beat * 18) *
        0.35;
      const hat =
        Math.sin(t * 47000) *
        Math.sin(t * 31631) *
        Math.exp(-(t % 0.25) * 90) *
        0.065;
      data[i] = (pad + kick + hat) * Math.min(1, t * 3, (duration - t) * 2);
    }
  }
  const notes = [329.63, 392, 440, 392, 329.63, 293.66, 261.63, 293.66];
  const data = vocal.getChannelData(0);
  for (let i = 0; i < data.length; i++) {
    const t = i / context.sampleRate;
    const envelope =
      Math.max(0, Math.sin(Math.PI * ((t % 0.75) / 0.75))) ** 1.5;
    const phase =
      2 * Math.PI * notes[Math.floor(t / 0.75) % notes.length] * t +
      0.12 * Math.sin(t * 32);
    data[i] =
      (Math.sin(phase) +
        0.3 * Math.sin(phase * 2) +
        0.12 * Math.sin(phase * 3)) *
      envelope *
      0.2 *
      Math.min(1, (duration - t) * 2);
  }
  return [backing, vocal];
}
