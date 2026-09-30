// Audio and video calls. My camera and microphone are real (getUserMedia);
// the other side is simulated by the mock server: it rings, answers or declines,
// and hangs up after a while. Every call ends up as an entry in the chat history.
import type { CallKind, CallLog, CallOutcome, Message } from './types';
import { addMessage, ensureDirectChat, getChat, getContact, getState, isOnline, patchCall, setCall, showToast } from './store';
import { server, type ServerEvent } from './mock/server';
import { playConnectTone, playEndTone, playRingback, playRingtone, stopTone } from './tones';
import { callLabel, uid } from './utils';

const RING_TIMEOUT = 30_000;
let ringTimer: number | undefined;

const call = () => getState().call;

// ---- starting --------------------------------------------------------------------------

export function startCall(chatId: string, kind: CallKind) {
  if (call()) return showToast('Сначала завершите текущий звонок', 'warning');
  if (!isOnline()) return showToast('Звонки работают только при подключении к интернету', 'warning');
  const chat = getChat(chatId);
  if (!chat) return;
  const id = uid();
  setCall({
    id,
    chatId,
    kind,
    direction: 'out',
    phase: 'calling',
    startedAt: Date.now(),
    participants: chat.memberIds.map((contactId) => ({ contactId, state: 'ringing' })),
    muted: false,
    cameraOn: kind === 'video',
    facing: 'user',
    localStream: null,
    minimized: false,
  });
  server.registerChat(chat);
  server.placeCall(id, chatId);
  playRingback();
  acquireMedia(id, kind === 'video');
  clearTimeout(ringTimer);
  ringTimer = window.setTimeout(noAnswer, RING_TIMEOUT);
}

/** Accept an incoming call, with or without my camera. */
export function acceptCall(withVideo: boolean) {
  const c = call();
  if (!c || c.phase !== 'incoming') return;
  clearTimeout(ringTimer);
  server.answerCall(c.id, c.participants[0].contactId);
  patchCall({
    phase: 'connected',
    connectedAt: Date.now(),
    cameraOn: withVideo,
    participants: c.participants.map((p) => ({ ...p, state: 'connected' })),
  });
  playConnectTone();
  acquireMedia(c.id, withVideo);
}

export function declineCall() {
  const c = call();
  if (!c || c.phase !== 'incoming') return;
  server.endCall(c.id, c.participants.map((p) => p.contactId));
  finish('declined', 'Звонок отклонён');
}

export function hangUp() {
  const c = call();
  if (!c || c.phase === 'ended') return;
  if (c.phase === 'incoming') return declineCall();
  server.endCall(c.id, c.participants.map((p) => p.contactId));
  finish(c.phase === 'connected' ? 'answered' : 'cancelled', 'Звонок завершён');
}

/** The connection dropped — a call can't go on without it. */
export function onConnectionLost() {
  const c = call();
  if (!c || c.phase === 'ended') return;
  server.endCall(c.id, c.participants.map((p) => p.contactId));
  finish(c.phase === 'connected' ? 'answered' : c.phase === 'incoming' ? 'missed' : 'cancelled', 'Соединение потеряно');
}

function noAnswer() {
  const c = call();
  if (!c || c.phase !== 'calling') return;
  server.endCall(c.id, c.participants.map((p) => p.contactId));
  const allOffline = c.participants.every((p) => !getContact(p.contactId)?.online);
  finish('unavailable', allOffline ? (c.participants.length > 1 ? 'Никого нет в сети' : 'Абонент не в сети') : 'Нет ответа');
}

// ---- events from the server ------------------------------------------------------------

export function handleCallEvent(e: Extract<ServerEvent, { type: `call-${string}` }>) {
  const c = call();
  switch (e.type) {
    case 'call-incoming': {
      if (c) {
        // Already talking: the new caller gets "busy", I get a missed call.
        server.endCall(e.callId, [e.contactId]);
        logCall(e.chatId, e.contactId, { kind: e.kind, direction: 'in', outcome: 'missed' });
        return;
      }
      ensureDirectChat(e.chatId);
      setCall({
        id: e.callId,
        chatId: e.chatId,
        kind: e.kind,
        direction: 'in',
        phase: 'incoming',
        startedAt: Date.now(),
        participants: [{ contactId: e.contactId, state: 'ringing' }],
        muted: false,
        cameraOn: false,
        facing: 'user',
        localStream: null,
        minimized: false,
      });
      playRingtone();
      return;
    }
    case 'call-cancelled':
      if (c?.id === e.callId && c.phase === 'incoming') finish('missed', 'Пропущенный звонок');
      return;
    case 'call-state': {
      if (!c || c.id !== e.callId || c.phase === 'ended') return;
      const participants = c.participants.map((p) => (p.contactId === e.contactId ? { ...p, state: e.state } : p));
      if (e.state === 'connected' && c.phase === 'calling') {
        clearTimeout(ringTimer);
        patchCall({ participants, phase: 'connected', connectedAt: Date.now() });
        playConnectTone();
        return;
      }
      patchCall({ participants });
      const stillThere = participants.some((p) => p.state === 'connected' || p.state === 'ringing');
      if (!stillThere) {
        server.endCall(c.id, []);
        if (c.phase === 'connected') finish('answered', participants.length > 1 ? 'Все участники вышли' : 'Собеседник завершил звонок');
        else finish('declined', 'Звонок отклонён');
      }
      return;
    }
  }
}

/** Menu → "Demo: incoming call". */
export function demoIncomingCall() {
  if (call()) return showToast('Сначала завершите текущий звонок', 'warning');
  if (!isOnline()) return showToast('Звонки работают только при подключении к интернету', 'warning');
  if (!server.ringMe()) showToast('Сейчас никого нет в сети — попробуйте чуть позже', 'info');
}

// ---- in-call controls ---------------------------------------------------------------------

export function toggleMute() {
  const c = call();
  if (!c) return;
  const muted = !c.muted;
  c.localStream?.getAudioTracks().forEach((t) => (t.enabled = !muted));
  patchCall({ muted });
}

export async function toggleCamera() {
  const c = call();
  if (!c || c.phase === 'ended') return;
  if (c.cameraOn) {
    c.localStream?.getVideoTracks().forEach((t) => t.stop());
    const audioOnly = c.localStream ? new MediaStream(c.localStream.getAudioTracks()) : null;
    patchCall({ cameraOn: false, localStream: audioOnly });
    return;
  }
  patchCall({ cameraOn: true });
  try {
    const cam = await navigator.mediaDevices.getUserMedia({ video: videoConstraints(c.facing) });
    const now = call();
    if (!now || now.id !== c.id || !now.cameraOn || now.phase === 'ended') return cam.getTracks().forEach((t) => t.stop());
    patchCall({ localStream: new MediaStream([...(now.localStream?.getAudioTracks() ?? []), ...cam.getVideoTracks()]), mediaError: undefined });
  } catch {
    patchCall({ cameraOn: false, mediaError: 'Нет доступа к камере' });
  }
}

export async function switchCamera() {
  const c = call();
  if (!c || !c.cameraOn) return;
  const facing = c.facing === 'user' ? 'environment' : 'user';
  try {
    const cam = await navigator.mediaDevices.getUserMedia({ video: videoConstraints(facing) });
    const now = call();
    if (!now || now.id !== c.id || now.phase === 'ended') return cam.getTracks().forEach((t) => t.stop());
    now.localStream?.getVideoTracks().forEach((t) => t.stop());
    patchCall({ facing, localStream: new MediaStream([...(now.localStream?.getAudioTracks() ?? []), ...cam.getVideoTracks()]) });
  } catch {
    showToast('Не удалось переключить камеру', 'warning');
  }
}

export function setMinimized(minimized: boolean) {
  patchCall({ minimized });
}

// ---- internals -------------------------------------------------------------------------------

const videoConstraints = (facing: 'user' | 'environment'): MediaTrackConstraints => ({
  facingMode: facing,
  width: { ideal: 1280 },
  height: { ideal: 720 },
});

async function acquireMedia(callId: string, video: boolean) {
  if (!navigator.mediaDevices?.getUserMedia) {
    patchCall({ cameraOn: false, mediaError: 'Браузер не даёт доступ к камере и микрофону' });
    return;
  }
  let stream: MediaStream | null = null;
  let error: string | undefined;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: video ? videoConstraints('user') : false });
  } catch {
    if (video) {
      // No camera (or no permission) — try at least the microphone.
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        error = 'Нет доступа к камере — звонок идёт без видео';
      } catch {
        error = 'Нет доступа к камере и микрофону';
      }
    } else {
      error = 'Нет доступа к микрофону — собеседник вас не услышит';
    }
  }
  const c = call();
  if (!c || c.id !== callId || c.phase === 'ended') {
    stream?.getTracks().forEach((t) => t.stop());
    return;
  }
  stream?.getAudioTracks().forEach((t) => (t.enabled = !c.muted));
  const hasVideo = !!stream?.getVideoTracks().length;
  patchCall({ localStream: stream, mediaError: error, cameraOn: c.cameraOn && hasVideo });
}

function finish(outcome: CallOutcome, endText: string) {
  const c = call();
  if (!c || c.phase === 'ended') return;
  clearTimeout(ringTimer);
  c.localStream?.getTracks().forEach((t) => t.stop());
  const now = Date.now();
  const duration = outcome === 'answered' && c.connectedAt ? Math.round((now - c.connectedAt) / 1000) : undefined;
  const log: CallLog = { kind: c.kind, direction: c.direction, outcome, duration };
  logCall(c.chatId, c.direction === 'in' ? c.participants[0].contactId : undefined, log);
  if (outcome === 'missed') stopTone();
  else playEndTone();
  setCall({ ...c, phase: 'ended', endedAt: now, endText, localStream: null });
  const id = c.id;
  setTimeout(() => {
    if (call()?.id === id) setCall(null);
  }, 1800);
}

function logCall(chatId: string, callerId: string | undefined, log: CallLog) {
  const now = Date.now();
  const incoming = log.direction === 'in';
  const message: Message = {
    id: uid(),
    chatId,
    author: incoming ? 'them' : 'me',
    senderId: callerId,
    text: '',
    call: log,
    createdAt: now,
    // A missed call counts as unread; everything else is already "seen".
    status: incoming && log.outcome === 'missed' ? 'delivered' : 'read',
  };
  addMessage(message);
  if (log.outcome === 'missed' && callerId) {
    const name = getContact(callerId)?.name ?? 'Контакт';
    showToast(`${callLabel(log)} от ${name}`, 'message', chatId, callerId);
  }
}

