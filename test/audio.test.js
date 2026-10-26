import test from "node:test";
import assert from "node:assert/strict";
import {
  audible,
  durationOf,
  scheduleTrack,
  protectPeak,
  encodeWav,
  formatTime,
} from "../src/audio.js";

const track = (kind, duration, overrides = {}) => ({
  kind,
  buffer: { duration },
  volume: 1,
  offset: 0,
  muted: false,
  solo: false,
  ...overrides,
});
const effects = { wet: 0.2, room: "studio" };

test("scheduling aligns positive/negative offsets, seeking and exhausted sources", () => {
  assert.deepEqual(scheduleTrack(10, 2, 0), { delay: 2, sourceOffset: 0 });
  assert.deepEqual(scheduleTrack(10, -2, 0), { delay: 0, sourceOffset: 2 });
  assert.deepEqual(scheduleTrack(10, 2, 5), { delay: 0, sourceOffset: 3 });
  assert.equal(scheduleTrack(10, -20, 0), null);
  assert.equal(scheduleTrack(10, 0, 10), null);
});

test("solo, mute and missing tracks determine audibility", () => {
  const a = track("backing", 10),
    b = track("vocal", 5, { solo: true });
  assert.equal(audible(a, [a, b]), false);
  assert.equal(audible(b, [a, b]), true);
  b.muted = true;
  assert.equal(audible(b, [a, b]), false);
  b.buffer = null;
  assert.equal(audible(a, [a, b]), true);
});

test("export timeline includes audible reverb tails, offsets and backing duration", () => {
  const a = track("backing", 10),
    b = track("vocal", 12, { offset: 1 });
  assert.equal(durationOf([a, b], effects), 14.6);
  assert.equal(durationOf([a, b], { ...effects, wet: 0 }), 13);
  assert.equal(durationOf([a, { ...b, muted: true }], effects), 13);
  assert.equal(durationOf([a, { ...b, offset: -20 }], effects), 10);
  assert.equal(durationOf([], effects), 0);
  assert.equal(durationOf([a], { ...effects, compress: true }), 10.006);
  assert.equal(durationOf([], { ...effects, compress: true }), 0);
});

test("peak protection attenuates all channels equally and preserves quiet audio", () => {
  const channels = [new Float32Array([2, -1]), new Float32Array([0.5, -2])];
  const scale = protectPeak(channels);
  assert.ok(Math.abs(scale - 10 ** (-1 / 20) / 2) < 1e-8);
  assert.ok(Math.abs(channels[0][0] - 10 ** (-1 / 20)) < 1e-6);
  assert.equal(channels[0][1], channels[1][1] / 2);
  const quiet = [new Float32Array([0.1, -0.2])];
  const before = quiet[0].slice();
  assert.equal(protectPeak(quiet), 1);
  assert.deepEqual(quiet[0], before);
});

test("WAV contains valid stereo PCM header, interleaving, signed samples and clipping", () => {
  const data = encodeWav(
    [new Float32Array([-1, 0.5, 2]), new Float32Array([1, -0.5, -2])],
    44100,
  );
  const view = new DataView(data);
  assert.equal(new TextDecoder().decode(data.slice(0, 4)), "RIFF");
  assert.equal(new TextDecoder().decode(data.slice(8, 12)), "WAVE");
  assert.equal(view.getUint32(4, true), data.byteLength - 8);
  assert.equal(view.getUint16(22, true), 2);
  assert.equal(view.getUint32(24, true), 44100);
  assert.equal(view.getUint32(28, true), 176400);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(view.getUint32(40, true), 12);
  assert.deepEqual(
    Array.from({ length: 6 }, (_, i) => view.getInt16(44 + i * 2, true)),
    [-32768, 32767, 16384, -16384, 32767, -32768],
  );
  assert.throws(() =>
    encodeWav([new Float32Array(2), new Float32Array(1)], 44100),
  );
});

test("time formatting handles invalid and fractional values", () => {
  assert.equal(formatTime(65.25, true), "01:05.25");
  assert.equal(formatTime(-1), "00:00");
  assert.equal(formatTime(NaN), "00:00");
});
