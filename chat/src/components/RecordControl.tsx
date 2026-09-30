// The microphone / video-note button of the composer, Telegram-style:
//  - tap switches between voice message and video note ("кружок");
//  - hold to record, release to send;
//  - while holding, slide left to cancel or slide up to lock (hands-free),
//    then send with the button or throw away with the trash can.
import { useEffect, useRef, useState } from 'react';
import { showToast } from '../store';
import { sendRecording } from '../sync';
import { MAX_ROUND, MAX_VOICE, Recorder, recordingSupported, type RecordKind } from '../recorder';
import { LockIcon, MicIcon, RoundVideoIcon, SendIcon, TrashIcon } from './icons';

const MODE_KEY = 'svyaz.recordMode';
const HOLD_MS = 220;
const CANCEL_DX = -110;
const LOCK_DY = -70;

function loadMode(): RecordKind {
  try {
    return localStorage.getItem(MODE_KEY) === 'round' ? 'round' : 'voice';
  } catch {
    return 'voice';
  }
}

type Phase = 'idle' | 'starting' | 'recording';

export function RecordControl({ chatId }: { chatId: string }) {
  const [mode, setMode] = useState<RecordKind>(loadMode);
  const [phase, setPhase] = useState<Phase>('idle');
  const [locked, setLocked] = useState(false);
  const [drag, setDrag] = useState({ dx: 0, dy: 0 });
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [hint, setHint] = useState(false);
  const rec = useRef<Recorder | null>(null);
  const down = useRef(false);
  const start = useRef({ x: 0, y: 0 });
  const holdTimer = useRef<number | undefined>(undefined);
  const tick = useRef<number | undefined>(undefined);
  const lockedRef = useRef(false);
  lockedRef.current = locked;

  const max = mode === 'round' ? MAX_ROUND : MAX_VOICE;

  // Stop everything if the chat is closed mid-recording.
  useEffect(() => () => reset(true), []);

  function reset(discard: boolean) {
    clearTimeout(holdTimer.current);
    clearInterval(tick.current);
    if (discard) rec.current?.cancel();
    rec.current = null;
    down.current = false;
    setPhase('idle');
    setLocked(false);
    setDrag({ dx: 0, dy: 0 });
    setElapsed(0);
    setLevel(0);
  }

  async function begin(lockedFromStart: boolean) {
    if (!recordingSupported()) {
      showToast('Этот браузер не умеет записывать голосовые и кружки', 'warning');
      return;
    }
    setPhase('starting');
    setLocked(lockedFromStart);
    let r: Recorder;
    try {
      r = await Recorder.start(mode);
    } catch {
      setPhase('idle');
      showToast(mode === 'round' ? 'Нет доступа к камере или микрофону' : 'Нет доступа к микрофону', 'warning');
      return;
    }
    // Released while the browser was asking for permission — nothing to record yet.
    if (!down.current && !lockedFromStart) {
      r.cancel();
      setPhase('idle');
      showToast('Удерживайте кнопку, чтобы записать', 'info');
      return;
    }
    rec.current = r;
    setPhase('recording');
    navigator.vibrate?.(20);
    tick.current = window.setInterval(() => {
      const cur = rec.current;
      if (!cur) return;
      setElapsed(cur.elapsed);
      setLevel(cur.level);
      if (cur.elapsed >= (cur.kind === 'round' ? MAX_ROUND : MAX_VOICE)) finish();
    }, 100);
  }

  async function finish() {
    const r = rec.current;
    if (!r) return reset(false);
    rec.current = null;
    clearInterval(tick.current);
    const result = await r.stop();
    reset(false);
    if (result.duration < 0.8) {
      showToast('Слишком коротко — удерживайте кнопку дольше', 'info');
      return;
    }
    sendRecording(chatId, result.blob, {
      kind: r.kind === 'voice' ? 'audio' : 'video',
      duration: result.duration,
      round: r.kind === 'round' || undefined,
      waveform: result.waveform,
      width: result.width,
      height: result.height,
    });
  }

  function cancel() {
    reset(true);
    navigator.vibrate?.([15, 40, 15]);
  }

  const onPointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    if (phase === 'recording' && locked) return void finish();
    if (phase !== 'idle') return;
    e.currentTarget.setPointerCapture(e.pointerId);
    down.current = true;
    start.current = { x: e.clientX, y: e.clientY };
    holdTimer.current = window.setTimeout(() => {
      holdTimer.current = undefined;
      begin(false);
    }, HOLD_MS);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!down.current || phase !== 'recording' || lockedRef.current) return;
    const dx = Math.min(0, e.clientX - start.current.x);
    const dy = Math.min(0, e.clientY - start.current.y);
    setDrag({ dx, dy });
    if (dx < CANCEL_DX) cancel();
    else if (dy < LOCK_DY) {
      setLocked(true);
      setDrag({ dx: 0, dy: 0 });
      navigator.vibrate?.(15);
    }
  };

  const onPointerUp = () => {
    if (!down.current) return;
    down.current = false;
    if (holdTimer.current !== undefined) {
      // A tap, not a hold: switch voice ↔ video note.
      clearTimeout(holdTimer.current);
      holdTimer.current = undefined;
      const next = mode === 'voice' ? 'round' : 'voice';
      setMode(next);
      try {
        localStorage.setItem(MODE_KEY, next);
      } catch {
        /* ignore */
      }
      setHint(true);
      window.setTimeout(() => setHint(false), 1600);
      return;
    }
    if (phase === 'recording' && !lockedRef.current) finish();
  };

  const recording = phase === 'recording';
  const timer = `${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, '0')},${Math.floor((elapsed % 1) * 10)}`;
  const cancelProgress = Math.min(1, -drag.dx / -CANCEL_DX);

  return (
    <>
      {recording && (
        <div className={`rec-bar ${locked ? 'is-locked' : ''}`}>
          {locked ? (
            <button className="icon-btn rec-bar__trash" onClick={cancel} aria-label="Удалить запись">
              <TrashIcon />
            </button>
          ) : (
            <span className="rec-bar__dot" />
          )}
          <span className="rec-bar__time">{timer}</span>
          {locked ? (
            <span className="rec-bar__wave" aria-hidden>
              {Array.from({ length: 24 }, (_, i) => (
                <span key={i} style={{ height: `${20 + ((Math.sin(elapsed * 6 + i) + 1) / 2) * level * 80}%` }} />
              ))}
            </span>
          ) : (
            <span className="rec-bar__cancel" style={{ transform: `translateX(${drag.dx * 0.6}px)`, opacity: 1 - cancelProgress * 0.8 }}>
              ‹ Влево — отмена
            </span>
          )}
        </div>
      )}

      {recording && !locked && (
        <div className="rec-lock" style={{ transform: `translateY(${Math.max(drag.dy, LOCK_DY)}px)` }} aria-hidden>
          <LockIcon width={16} height={16} />
          <span>↑</span>
        </div>
      )}

      {recording && mode === 'round' && rec.current && <RoundPreview stream={rec.current.stream} progress={elapsed / max} />}

      {hint && phase === 'idle' && (
        <div className="rec-hint" role="status">
          {mode === 'round' ? 'Кружок: удерживайте, чтобы записать' : 'Голосовое: удерживайте, чтобы записать'}
        </div>
      )}

      <button
        className={`send-btn rec-btn is-active ${recording ? 'is-recording' : ''} ${phase === 'starting' ? 'is-starting' : ''}`}
        style={recording && !locked ? { transform: `scale(${1.5 + level * 0.35})` } : undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => phase === 'recording' && !lockedRef.current && cancel()}
        onContextMenu={(e) => e.preventDefault()}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) {
            e.preventDefault();
            if (phase === 'idle') begin(true);
            else if (recording) finish();
          }
        }}
        aria-label={
          recording && locked ? 'Отправить запись' : mode === 'round' ? 'Видеосообщение: удерживайте для записи, нажмите — голосовое' : 'Голосовое: удерживайте для записи, нажмите — видеосообщение'
        }
        title={mode === 'round' ? 'Удерживайте — записать кружок. Нажмите — перейти к голосовым' : 'Удерживайте — записать голосовое. Нажмите — перейти к кружкам'}
      >
        {recording && locked ? <SendIcon /> : mode === 'round' ? <RoundVideoIcon /> : <MicIcon />}
      </button>
    </>
  );
}

/** Big circle with my camera while recording a video note. */
function RoundPreview({ stream, progress }: { stream: MediaStream; progress: number }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.srcObject = stream;
  }, [stream]);
  const r = 47;
  const c = 2 * Math.PI * r;
  return (
    <div className="round-rec" aria-hidden>
      <div className="round-rec__circle">
        <video ref={ref} autoPlay playsInline muted />
        <svg viewBox="0 0 100 100" className="round-rec__ring">
          <circle cx="50" cy="50" r={r} className="round-rec__track" />
          <circle cx="50" cy="50" r={r} className="round-rec__progress" strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(1, progress))} />
        </svg>
      </div>
    </div>
  );
}
