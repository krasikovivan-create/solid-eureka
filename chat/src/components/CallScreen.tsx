// Full-screen call UI: incoming call, calling, the conversation (1:1 or group grid),
// and a minimized pill so you can keep chatting during a call.
import { useEffect, useRef, useState } from 'react';
import type { ActiveCall, CallParticipant, Contact } from '../types';
import { getChat, useAppState } from '../store';
import { acceptCall, declineCall, hangUp, setMinimized, switchCamera, toggleCamera, toggleMute } from '../calls';
import { chatLook, formatDuration } from '../utils';
import { useUi } from '../ui';
import { Avatar } from './Avatar';
import { CameraOffIcon, HangUpIcon, MicIcon, MicOffIcon, MinimizeIcon, PhoneIcon, SwitchCameraIcon, VideoIcon } from './icons';

export function CallScreen() {
  const call = useAppState((s) => s.call);
  if (!call) return null;
  return (
    <>
      {/* Real calls: the other people's voices keep playing even when the call is minimized. */}
      {call.mode === 'real' && call.phase === 'connected' && call.participants.map((p) => p.stream && <RemoteAudio key={p.contactId} stream={p.stream} />)}
      {call.minimized && call.phase === 'connected' ? <CallPill call={call} /> : <CallView call={call} />}
    </>
  );
}

/** Does this participant send live video right now? */
const hasVideo = (p: CallParticipant) => p.cameraOn !== false && !!p.stream?.getVideoTracks().some((t) => t.readyState === 'live' && !t.muted);

function useNow(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

function useLook(call: ActiveCall) {
  const contacts = useAppState((s) => s.contacts);
  const chat = useAppState((s) => s.chats.find((c) => c.id === call.chatId));
  const look = chat ? chatLook(chat, contacts) : { name: 'Звонок', colors: ['#667eea', '#764ba2'] as [string, string], contact: undefined };
  const people = call.participants.map((p) => ({ ...p, contact: contacts.find((c) => c.id === p.contactId) })).filter((p): p is typeof p & { contact: Contact } => !!p.contact);
  return { look, people, isGroup: chat?.kind === 'group' };
}

// ---- the big screen ---------------------------------------------------------------------------

function CallView({ call }: { call: ActiveCall }) {
  const { openChat } = useUi();
  const { look, people, isGroup } = useLook(call);
  const now = useNow(call.phase === 'connected');
  const video = call.kind === 'video' || call.cameraOn;
  const connected = call.phase === 'connected';
  const single = !isGroup && people[0];
  const joined = people.filter((p) => p.state === 'connected');

  let status = '';
  if (call.phase === 'incoming') status = call.kind === 'video' ? 'Входящий видеозвонок' : 'Входящий звонок';
  else if (call.phase === 'calling') status = single && !single.contact.online ? 'Ожидание ответа…' : isGroup ? 'Вызов участников…' : 'Вызов…';
  else if (connected && call.mode === 'real' && single && !single.stream) status = 'Соединение…';
  else if (connected) status = formatDuration(((call.connectedAt ? now : Date.now()) - (call.connectedAt ?? Date.now())) / 1000);
  else status = call.endText ?? 'Звонок завершён';

  const [from, to] = look.colors;

  return (
    <div className={`call call--${call.phase} ${video ? 'call--video' : ''}`} role="dialog" aria-modal="true" aria-label={`Звонок: ${look.name}`}>
      <div className="call__bg" style={{ background: `radial-gradient(circle at 30% 20%, ${from}88, transparent 55%), radial-gradient(circle at 70% 80%, ${to}88, transparent 55%), #0e121b` }} />

      {/* Stage: remote side (1:1), tiles (group), or my camera while calling */}
      {connected && isGroup ? (
        <div className={`call__grid call__grid--${Math.min(people.length + 1, 4)}`}>
          {people.map((p) => (
            <Tile key={p.contactId} participant={p} contact={p.contact} real={call.mode === 'real'} video={call.kind === 'video'} />
          ))}
          <SelfTile call={call} />
        </div>
      ) : connected && single && call.mode === 'real' && hasVideo(single) ? (
        <div className="call__remote">
          <RemoteVideo stream={single.stream!} />
        </div>
      ) : connected && single && call.mode === 'demo' && call.kind === 'video' ? (
        <div className="call__remote">
          <FakeVideo contact={single.contact} />
        </div>
      ) : (
        call.cameraOn &&
        call.localStream && (
          <div className="call__remote">
            <LocalVideo stream={call.localStream} mirrored={call.facing === 'user'} />
            <div className="call__dim" />
          </div>
        )
      )}

      <header className="call__top">
        {connected ? (
          <button className="icon-btn icon-btn--light" onClick={() => setMinimized(true)} aria-label="Свернуть звонок" title="Свернуть — можно писать в чатах">
            <MinimizeIcon />
          </button>
        ) : (
          <span />
        )}
        <span className="call__secure">{call.mode === 'real' ? '🔒 Звонок зашифрован' : '🔒 Демо-звонок'}</span>
        <span />
      </header>

      {/* Name, avatar and status in the middle (hidden when there is a video/grid) */}
      {!(connected && (isGroup || (call.mode === 'demo' ? call.kind === 'video' : !!single && hasVideo(single)))) && (
        <div className="call__center">
          <div className={`call__avatar ${call.phase === 'calling' || call.phase === 'incoming' ? 'is-ringing' : ''} ${connected ? 'is-talking' : ''}`}>
            <Avatar name={look.name} colors={look.colors} size={128} group={isGroup} />
            {connected && single && <VoiceRing stream={call.mode === 'real' ? single.stream : undefined} />}
          </div>
          <div className="call__name">{look.name}</div>
          <div className="call__status" key={call.phase}>
            {status}
          </div>
          {isGroup && call.phase === 'calling' && (
            <div className="call__people">
              {people.map((p) => (
                <span key={p.contactId} className={`call__person is-${p.state}`}>
                  {p.contact.name.split(' ')[0]} · {personState(p.state, p.contact)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {connected && (isGroup || (call.mode === 'demo' ? call.kind === 'video' : !!single && hasVideo(single))) && (
        <div className="call__caption">
          <div className="call__name call__name--small">{look.name}</div>
          <div className="call__status">
            {status}
            {isGroup && ` · ${joined.length + 1} в звонке`}
          </div>
        </div>
      )}

      {/* My camera in the corner during a 1:1 call */}
      {connected && !isGroup && video && (
        <div className="call__self">
          {call.cameraOn && call.localStream?.getVideoTracks().length ? (
            <LocalVideo stream={call.localStream} mirrored={call.facing === 'user'} />
          ) : (
            <div className="call__self-off">
              <CameraOffIcon width={22} height={22} />
            </div>
          )}
        </div>
      )}

      {call.mediaError && call.phase !== 'ended' && <div className="call__warning">{call.mediaError}</div>}

      <footer className="call__controls">
        {call.phase === 'incoming' ? (
          <>
            <CallButton label="Отклонить" kind="danger" onClick={declineCall}>
              <HangUpIcon />
            </CallButton>
            <CallButton label="Ответить" kind="accept" onClick={() => acceptCall(false)}>
              <PhoneIcon />
            </CallButton>
            {call.kind === 'video' && (
              <CallButton label="С видео" kind="accept" onClick={() => acceptCall(true)}>
                <VideoIcon />
              </CallButton>
            )}
          </>
        ) : call.phase === 'ended' ? (
          <CallButton
            label="К чату"
            onClick={() => {
              openChat(call.chatId);
            }}
          >
            <PhoneIcon />
          </CallButton>
        ) : (
          <>
            <CallButton label={call.muted ? 'Вкл. микрофон' : 'Микрофон'} active={call.muted} onClick={toggleMute}>
              {call.muted ? <MicOffIcon /> : <MicIcon />}
            </CallButton>
            <CallButton label={call.cameraOn ? 'Камера' : 'Вкл. камеру'} active={!call.cameraOn} onClick={toggleCamera}>
              {call.cameraOn ? <VideoIcon /> : <CameraOffIcon />}
            </CallButton>
            {call.cameraOn && (
              <CallButton label="Сменить" onClick={switchCamera}>
                <SwitchCameraIcon />
              </CallButton>
            )}
            <CallButton label="Завершить" kind="danger" onClick={hangUp}>
              <HangUpIcon />
            </CallButton>
          </>
        )}
      </footer>
    </div>
  );
}

function personState(state: string, c: Contact) {
  const f = c.gender === 'f';
  switch (state) {
    case 'ringing':
      return c.online ? 'вызов…' : 'не в сети';
    case 'connected':
      return 'в звонке';
    case 'declined':
      return f ? 'отклонила' : 'отклонил';
    case 'left':
      return f ? 'вышла' : 'вышел';
    default:
      return 'не в сети';
  }
}

function CallButton({ label, kind, active, onClick, children }: { label: string; kind?: 'danger' | 'accept'; active?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button className={`call-btn ${kind ? `call-btn--${kind}` : ''} ${active ? 'is-active' : ''}`} onClick={onClick} aria-label={label} aria-pressed={active}>
      <span className="call-btn__circle">{children}</span>
      <span className="call-btn__label">{label}</span>
    </button>
  );
}

// ---- tiles & video --------------------------------------------------------------------------------

function Tile({ participant, contact, real, video }: { participant: CallParticipant; contact: Contact; real: boolean; video: boolean }) {
  const state = participant.state;
  const live = state === 'connected';
  return (
    <div className={`tile ${live ? 'is-live' : ''}`}>
      {live && real && hasVideo(participant) ? (
        <RemoteVideo stream={participant.stream!} />
      ) : live && !real && video ? (
        <FakeVideo contact={contact} />
      ) : (
        <div className="tile__avatar">
          <Avatar name={contact.name} colors={contact.colors} size={72} />
          {live && <VoiceRing stream={real ? participant.stream : undefined} />}
        </div>
      )}
      <div className="tile__label">
        {contact.name.split(' ')[0]}
        {participant.muted && <MicOffIcon width={14} height={14} />}
        {!live && <em> · {personState(state, contact)}</em>}
      </div>
    </div>
  );
}

function SelfTile({ call }: { call: ActiveCall }) {
  return (
    <div className="tile is-live tile--self">
      {call.cameraOn && call.localStream?.getVideoTracks().length ? (
        <LocalVideo stream={call.localStream} mirrored={call.facing === 'user'} />
      ) : (
        <div className="tile__avatar">
          <div className="avatar avatar--me" style={{ width: 72, height: 72, fontSize: 26 }}>
            <div className="avatar__img">Я</div>
          </div>
        </div>
      )}
      <div className="tile__label">
        Вы{call.muted && <MicOffIcon width={14} height={14} />}
      </div>
    </div>
  );
}

function LocalVideo({ stream, mirrored }: { stream: MediaStream; mirrored: boolean }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (ref.current && ref.current.srcObject !== stream) ref.current.srcObject = stream;
  }, [stream]);
  return <video ref={ref} className={`live-video ${mirrored ? 'is-mirrored' : ''}`} autoPlay playsInline muted />;
}

/** Ring around the avatar while the person speaks: real loudness for real calls, imitated in the demo. */
function VoiceRing({ stream }: { stream?: MediaStream }) {
  const [level, setLevel] = useState(0);
  useEffect(() => {
    if (stream?.getAudioTracks().length) return watchLevel(stream, setLevel);
    if (stream) return;
    let t: number;
    const step = () => {
      setLevel(Math.random() < 0.55 ? 0.4 + Math.random() * 0.6 : 0);
      t = window.setTimeout(step, 180 + Math.random() * 420);
    };
    step();
    return () => clearTimeout(t);
  }, [stream]);
  return <span className="voice-ring" style={{ transform: `scale(${1 + level * 0.18})`, opacity: level ? 0.9 : 0 }} />;
}

let levelCtx: AudioContext | null = null;
function watchLevel(stream: MediaStream, set: (v: number) => void) {
  try {
    levelCtx ??= new AudioContext();
    const src = levelCtx.createMediaStreamSource(new MediaStream(stream.getAudioTracks()));
    const analyser = levelCtx.createAnalyser();
    analyser.fftSize = 256;
    src.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const t = window.setInterval(() => {
      analyser.getByteTimeDomainData(data);
      let peak = 0;
      for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
      set(peak > 6 ? Math.min(1, peak / 40) : 0);
    }, 120);
    return () => {
      clearInterval(t);
      src.disconnect();
    };
  } catch {
    return undefined;
  }
}

function RemoteVideo({ stream }: { stream: MediaStream }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (ref.current && ref.current.srcObject !== stream) ref.current.srcObject = stream;
  }, [stream]);
  // Muted: the sound plays through RemoteAudio (so it continues when the call is minimized).
  return <video ref={ref} className="live-video" autoPlay playsInline muted />;
}

function RemoteAudio({ stream }: { stream: MediaStream }) {
  const ref = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (el.srcObject !== stream) el.srcObject = stream;
    el.play().catch(() => {});
  }, [stream]);
  return <audio ref={ref} autoPlay />;
}

/**
 * The other side's "camera" in the demo: an animated picture drawn on a canvas
 * (a person silhouette on a moving background in the contact's colors).
 */
function FakeVideo({ contact }: { contact: Contact }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    let raf = 0;
    let last = 0;
    const [c1, c2] = contact.colors;
    const draw = (t: number) => {
      raf = requestAnimationFrame(draw);
      if (t - last < 33) return; // ~30 fps is plenty
      last = t;
      const w = (canvas.width = canvas.clientWidth);
      const h = (canvas.height = canvas.clientHeight);
      if (!w || !h) return;
      const s = t / 1000;
      const bg = ctx.createLinearGradient(0, 0, w, h);
      bg.addColorStop(0, c1);
      bg.addColorStop(1, c2);
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);
      // soft "room" light
      const glow = ctx.createRadialGradient(w * (0.3 + 0.1 * Math.sin(s * 0.3)), h * 0.25, 10, w * 0.3, h * 0.3, Math.max(w, h) * 0.7);
      glow.addColorStop(0, 'rgba(255,255,255,0.35)');
      glow.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);
      // the person: shoulders + head, breathing and moving a little
      const unit = Math.min(w, h) * 0.62;
      const cx = w / 2 + Math.sin(s * 0.7) * unit * 0.04;
      const breathe = Math.sin(s * 1.3) * unit * 0.012;
      const headR = unit * 0.2;
      const headY = h * 0.42 + breathe;
      const shouldersY = headY + headR * 1.25 + unit * 0.42;
      ctx.fillStyle = 'rgba(25,28,45,0.5)';
      ctx.shadowColor = 'rgba(0,0,0,0.25)';
      ctx.shadowBlur = unit * 0.08;
      ctx.beginPath();
      ctx.ellipse(cx, shouldersY, unit * 0.52, unit * 0.42 + breathe, 0, Math.PI, 0);
      ctx.lineTo(cx + unit * 0.52, h);
      ctx.lineTo(cx - unit * 0.52, h);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(cx, headY, headR, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      // subtle sensor noise so it reads as video
      ctx.fillStyle = 'rgba(255,255,255,0.03)';
      for (let i = 0; i < 40; i++) ctx.fillRect(Math.random() * w, Math.random() * h, 2, 2);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [contact]);
  return <canvas ref={ref} className="fake-video" aria-label={`Видео: ${contact.name}`} />;
}

// ---- minimized ----------------------------------------------------------------------------------

function CallPill({ call }: { call: ActiveCall }) {
  const { look } = useLook(call);
  const { openChat } = useUi();
  const now = useNow(true);
  const time = formatDuration((now - (call.connectedAt ?? now)) / 1000);
  return (
    <div className="call-pill" role="status">
      <button
        className="call-pill__main"
        onClick={() => {
          setMinimized(false);
          if (getChat(call.chatId)) openChat(call.chatId);
        }}
      >
        <span className="call-pill__dot" />
        <span className="call-pill__name">{look.name}</span>
        <span className="call-pill__time">{time}</span>
        <span className="call-pill__hint">вернуться</span>
      </button>
      <button className="call-pill__btn" onClick={toggleMute} aria-label={call.muted ? 'Включить микрофон' : 'Выключить микрофон'}>
        {call.muted ? <MicOffIcon width={18} height={18} /> : <MicIcon width={18} height={18} />}
      </button>
      <button className="call-pill__btn call-pill__btn--end" onClick={hangUp} aria-label="Завершить звонок">
        <HangUpIcon width={18} height={18} />
      </button>
    </div>
  );
}
