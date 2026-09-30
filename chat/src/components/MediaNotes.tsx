// Voice messages (waveform player with speed) and video notes ("кружки").
import { useEffect, useRef, useState } from 'react';
import type { MediaRef } from '../types';
import { formatDuration } from '../utils';
import { useMediaUrl } from './useMediaUrl';
import { PauseIcon, PlayIcon } from './icons';

/** Only one voice message / video note plays at a time. */
let current: HTMLMediaElement | null = null;
function claim(el: HTMLMediaElement) {
  if (current && current !== el) current.pause();
  current = el;
}

const SPEEDS = [1, 1.5, 2];

export function VoiceNote({ media, mine, pending }: { media: MediaRef; mine: boolean; pending: boolean }) {
  const url = useMediaUrl(media.id);
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const [speed, setSpeed] = useState(1);
  const duration = media.duration ?? 0;
  const bars = media.waveform?.length ? media.waveform : Array(40).fill(0.3);
  const progress = duration ? Math.min(1, pos / duration) : 0;

  useEffect(() => {
    const el = audio.current;
    if (!el) return;
    const onTime = () => setPos(el.currentTime);
    const onEnd = () => {
      setPlaying(false);
      setPos(0);
    };
    const onPause = () => setPlaying(false);
    const onPlay = () => setPlaying(true);
    el.addEventListener('timeupdate', onTime);
    el.addEventListener('ended', onEnd);
    el.addEventListener('pause', onPause);
    el.addEventListener('play', onPlay);
    return () => {
      el.removeEventListener('timeupdate', onTime);
      el.removeEventListener('ended', onEnd);
      el.removeEventListener('pause', onPause);
      el.removeEventListener('play', onPlay);
    };
  }, [url]);

  const toggle = () => {
    const el = audio.current;
    if (!el || !url) return;
    if (el.paused) {
      claim(el);
      el.playbackRate = speed;
      el.play().catch(() => {});
    } else el.pause();
  };

  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const el = audio.current;
    if (!el || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const t = ((e.clientX - rect.left) / rect.width) * duration;
    el.currentTime = Math.max(0, Math.min(duration - 0.05, t));
    setPos(el.currentTime);
    if (el.paused) toggle();
  };

  const nextSpeed = () => {
    const s = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
    setSpeed(s);
    if (audio.current) audio.current.playbackRate = s;
  };

  return (
    <div className={`voice ${mine ? 'voice--mine' : ''}`} onClick={(e) => e.stopPropagation()}>
      <button className="voice__play" onClick={toggle} disabled={!url} aria-label={playing ? 'Пауза' : 'Слушать'}>
        {pending && !url ? <span className="spinner" /> : playing ? <PauseIcon width={20} height={20} /> : <PlayIcon width={20} height={20} />}
      </button>
      <div className="voice__body">
        <div className="voice__wave" onClick={seek} role="slider" aria-label="Перемотка" aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(pos)}>
          {bars.map((v, i) => (
            <span key={i} className={i / bars.length < progress ? 'is-played' : ''} style={{ height: `${Math.max(12, v * 100)}%` }} />
          ))}
        </div>
        <div className="voice__meta">
          <span>{formatDuration(playing || pos > 0 ? pos : duration)}</span>
          {(playing || pos > 0) && (
            <button className="voice__speed" onClick={nextSpeed} aria-label="Скорость воспроизведения">
              {speed}×
            </button>
          )}
        </div>
      </div>
      {url && <audio ref={audio} src={url} preload="metadata" />}
    </div>
  );
}

/** Video note: a muted looping circle; tap to watch with sound from the start. */
export function RoundNote({ media, pending }: { media: MediaRef; pending: boolean }) {
  const url = useMediaUrl(media.id);
  const video = useRef<HTMLVideoElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(false);
  const [progress, setProgress] = useState(0);
  const duration = media.duration ?? 0;

  // The silent preview only plays while the circle is on screen.
  useEffect(() => {
    const el = video.current;
    const wrap = box.current;
    if (!el || !wrap || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver(([entry]) => {
      if (active) return;
      if (entry.isIntersecting) el.play().catch(() => {});
      else el.pause();
    });
    io.observe(wrap);
    return () => io.disconnect();
  }, [url, active]);

  useEffect(() => {
    const el = video.current;
    if (!el) return;
    const onTime = () => active && duration && setProgress(Math.min(1, el.currentTime / duration));
    const onEnd = () => stopActive();
    const onPause = () => {
      if (active && current !== el) stopActive();
    };
    el.addEventListener('timeupdate', onTime);
    el.addEventListener('ended', onEnd);
    el.addEventListener('pause', onPause);
    return () => {
      el.removeEventListener('timeupdate', onTime);
      el.removeEventListener('ended', onEnd);
      el.removeEventListener('pause', onPause);
    };
  });

  function stopActive() {
    const el = video.current;
    setActive(false);
    setProgress(0);
    if (!el) return;
    el.muted = true;
    el.loop = true;
    el.play().catch(() => {});
  }

  const toggle = () => {
    const el = video.current;
    if (!el || !url) return;
    if (!active) {
      claim(el);
      setActive(true);
      el.loop = false;
      el.muted = false;
      el.currentTime = 0;
      el.play().catch(() => {});
    } else if (el.paused) el.play().catch(() => {});
    else el.pause();
  };

  const r = 48.5;
  const c = 2 * Math.PI * r;
  return (
    <div ref={box} className={`round-note ${active ? 'is-active' : ''}`} onClick={(e) => (e.stopPropagation(), toggle())} role="button" aria-label="Видеосообщение">
      {url ? <video ref={video} src={url} muted loop playsInline preload="metadata" autoPlay /> : <div className="media__skeleton" />}
      {active && (
        <svg viewBox="0 0 100 100" className="round-note__ring">
          <circle cx="50" cy="50" r={r} strokeDasharray={c} strokeDashoffset={c * (1 - progress)} />
        </svg>
      )}
      {!active && <span className="round-note__badge">{formatDuration(duration)} 🔇</span>}
      {pending && (
        <span className="round-note__pending">
          <span className="spinner" />
        </span>
      )}
    </div>
  );
}
