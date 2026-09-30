// Call sounds made with Web Audio, so no audio files are needed:
// ringback "гудки" (425 Hz, 1 s on / 3 s off), incoming ringtone, connect and hang-up beeps.

let ctx: AudioContext | null = null;
let active: OscillatorNode[] = [];
let loopTimer: number | undefined;

function audio(): AudioContext | null {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    return ctx;
  } catch {
    return null;
  }
}

function beep(freq: number, at: number, duration: number, volume = 0.12, type: OscillatorType = 'sine') {
  const c = audio();
  if (!c) return;
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0, at);
  gain.gain.linearRampToValueAtTime(volume, at + 0.02);
  gain.gain.setValueAtTime(volume, at + duration - 0.03);
  gain.gain.linearRampToValueAtTime(0, at + duration);
  osc.connect(gain).connect(c.destination);
  osc.start(at);
  osc.stop(at + duration + 0.05);
  active.push(osc);
  osc.onended = () => (active = active.filter((o) => o !== osc));
}

function loop(pattern: (t: number) => void, periodMs: number) {
  stopTone();
  const c = audio();
  if (!c) return;
  const run = () => pattern(c.currentTime + 0.05);
  run();
  loopTimer = window.setInterval(run, periodMs);
}

export function stopTone() {
  clearInterval(loopTimer);
  loopTimer = undefined;
  active.forEach((o) => {
    try {
      o.stop();
    } catch {
      /* already stopped */
    }
  });
  active = [];
  navigator.vibrate?.(0);
}

/** What the caller hears while the other side is ringing. */
export function playRingback() {
  loop((t) => beep(425, t, 1, 0.1), 4000);
}

/** Incoming call. */
export function playRingtone() {
  loop((t) => {
    [0, 0.18, 0.36, 0.9, 1.08, 1.26].forEach((d, i) => beep(i % 3 === 1 ? 988 : 784, t + d, 0.16, 0.14, 'triangle'));
  }, 2600);
  navigator.vibrate?.([400, 300, 400, 1500, 400, 300, 400]);
}

export function playConnectTone() {
  stopTone();
  const c = audio();
  if (!c) return;
  beep(660, c.currentTime + 0.02, 0.09, 0.1);
  beep(880, c.currentTime + 0.13, 0.12, 0.1);
}

/** Short busy beeps after hanging up. */
export function playEndTone() {
  stopTone();
  const c = audio();
  if (!c) return;
  for (let i = 0; i < 3; i++) beep(425, c.currentTime + 0.05 + i * 0.4, 0.2, 0.09);
}
