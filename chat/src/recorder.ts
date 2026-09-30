// Recording voice messages and video notes ("кружки") with MediaRecorder.
// While recording, the microphone level is sampled for the live indicator and
// for the waveform that is stored with a voice message.

export type RecordKind = 'voice' | 'round';

export interface Recording {
  blob: Blob;
  duration: number;
  waveform?: number[];
  width?: number;
  height?: number;
}

export const MAX_VOICE = 5 * 60;
export const MAX_ROUND = 60;
const BARS = 48;

function pickMime(kind: RecordKind) {
  const list =
    kind === 'voice'
      ? ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/webm']
      : ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/mp4', 'video/webm'];
  return list.find((m) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m));
}

export function recordingSupported() {
  return typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

export class Recorder {
  readonly stream: MediaStream;
  private rec: MediaRecorder;
  private chunks: Blob[] = [];
  private levels: number[] = [];
  private ctx: AudioContext | null = null;
  private timer: number | undefined;
  private startedAt = 0;
  private stopped: Promise<Blob>;
  /** Latest loudness 0..1, for the UI. */
  level = 0;

  private constructor(readonly kind: RecordKind, stream: MediaStream) {
    this.stream = stream;
    const mimeType = pickMime(kind);
    this.rec = new MediaRecorder(stream, { ...(mimeType ? { mimeType } : {}), ...(kind === 'voice' ? { audioBitsPerSecond: 48_000 } : { videoBitsPerSecond: 900_000 }) });
    this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.stopped = new Promise((resolve) => {
      this.rec.onstop = () => resolve(new Blob(this.chunks, { type: this.rec.mimeType || mimeType || (kind === 'voice' ? 'audio/webm' : 'video/webm') }));
    });
    this.watchLevel();
    this.rec.start(250);
    this.startedAt = performance.now();
  }

  /** Asks for the microphone (and the front camera for a video note) and starts. */
  static async start(kind: RecordKind): Promise<Recorder> {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: kind === 'round' ? { facingMode: 'user', width: { ideal: 480 }, height: { ideal: 480 }, aspectRatio: { ideal: 1 } } : false,
    });
    try {
      return new Recorder(kind, stream);
    } catch (e) {
      stream.getTracks().forEach((t) => t.stop());
      throw e;
    }
  }

  get elapsed() {
    return (performance.now() - this.startedAt) / 1000;
  }

  async stop(): Promise<Recording> {
    const duration = this.elapsed;
    const settings = this.stream.getVideoTracks()[0]?.getSettings();
    if (this.rec.state !== 'inactive') this.rec.stop();
    const blob = await this.stopped;
    this.release();
    return {
      blob,
      duration,
      waveform: this.kind === 'voice' ? this.waveform() : undefined,
      width: settings?.width,
      height: settings?.height,
    };
  }

  cancel() {
    if (this.rec.state !== 'inactive') this.rec.stop();
    this.release();
  }

  private release() {
    clearInterval(this.timer);
    this.stream.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.ctx = null;
  }

  private watchLevel() {
    try {
      this.ctx = new AudioContext();
      const src = this.ctx.createMediaStreamSource(this.stream);
      const analyser = this.ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      this.timer = window.setInterval(() => {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) sum += (v - 128) ** 2;
        const rms = Math.sqrt(sum / data.length) / 128;
        this.level = Math.min(1, rms * 4);
        this.levels.push(this.level);
      }, 60);
    } catch {
      /* no Web Audio — no level, no waveform */
    }
  }

  /** Squeeze all samples into BARS bars, normalized so the loudest bar is 1. */
  private waveform(): number[] {
    const src = this.levels;
    if (!src.length) return Array(BARS).fill(0.15);
    const out: number[] = [];
    for (let i = 0; i < BARS; i++) {
      const from = Math.floor((i * src.length) / BARS);
      const to = Math.max(from + 1, Math.floor(((i + 1) * src.length) / BARS));
      let peak = 0;
      for (let j = from; j < to && j < src.length; j++) peak = Math.max(peak, src[j]);
      out.push(peak);
    }
    const max = Math.max(...out, 0.05);
    return out.map((v) => Math.round(Math.max(0.08, v / max) * 100) / 100);
  }
}
