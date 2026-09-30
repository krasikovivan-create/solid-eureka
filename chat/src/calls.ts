// Audio and video calls. My camera and microphone are always real (getUserMedia).
// Two kinds of calls share one screen and one set of controls:
//  - real: to people registered on the server — WebRTC (rtc.ts), signaling through the server;
//  - demo: to demo contacts — the mock server rings, answers or declines.
// Every call ends up as an entry in the chat history.
import type { ActiveCall, CallKind, CallLog, CallOutcome, CallParticipant, Message } from './types';
import { addMessage, ensureDirectChat, getChat, getContact, getState, isOnline, isRealChat, patchCall, setCall, showToast } from './store';
import { server, type ServerEvent } from './mock/server';
import { playConnectTone, playEndTone, playRingback, playRingtone, stopTone } from './tones';
import { callLabel, uid } from './utils';
import { callPeer, closeAll, closePeer, hasPeer, onSignal, replaceLocalTracks, setupRtc } from './rtc';
import { ensureRealContact, net, realGroupFromServer } from './real';

const RING_TIMEOUT = 30_000;
const REAL_RING_TIMEOUT = 45_000;
let ringTimer: number | undefined;
/** Resolves when my camera/microphone for the current call are ready. */
let mediaReady: Promise<MediaStream | null> = Promise.resolve(null);

const call = () => getState().call;
const phoneOf = (contactId: string) => getContact(contactId)?.phone ?? '';
const contactOfPhone = (phone: string) => getState().contacts.find((c) => c.real && c.phone === phone);

setupRtc({
  iceServers: () => net.iceServers,
  localStream: () => mediaReady,
  signal: (to, data) => {
    const c = call();
    if (c) net.send({ type: 'rtc', callId: c.id, to, data });
  },
  onStream: (phone, stream) => updateParticipant(phone, { stream }),
  onState: (phone, state) => {
    if (state === 'connected') updateParticipant(phone, { state: 'connected' });
  },
});

// ---- starting --------------------------------------------------------------------------

export function startCall(chatId: string, kind: CallKind) {
  if (call()) return showToast('Сначала завершите текущий звонок', 'warning');
  if (!isOnline()) return showToast('Звонки работают только при подключении к интернету', 'warning');
  const chat = getChat(chatId);
  if (!chat) return;
  const real = isRealChat(chat);
  if (real && !net.isOnline()) return showToast('Нет связи с сервером — звонок невозможен. Проверьте профиль.', 'warning');
  const members = real ? chat.memberIds.filter((id) => getContact(id)?.real) : chat.memberIds;
  const id = uid();
  setCall({
    id,
    mode: real ? 'real' : 'demo',
    chatId,
    kind,
    direction: 'out',
    phase: 'calling',
    startedAt: Date.now(),
    participants: members.map((contactId) => ({ contactId, state: 'ringing' })),
    muted: false,
    cameraOn: kind === 'video',
    facing: 'user',
    localStream: null,
    minimized: false,
  });
  mediaReady = acquireMedia(id, kind === 'video');
  playRingback();
  clearTimeout(ringTimer);
  if (real) {
    const phones = members.map(phoneOf);
    net.send({
      type: 'call',
      action: 'invite',
      callId: id,
      to: phones,
      kind,
      chat: chat.kind === 'group' ? { kind: 'group', id: chat.id, title: chat.title, members: phones } : { kind: 'direct' },
    });
    ringTimer = window.setTimeout(noAnswer, REAL_RING_TIMEOUT);
  } else {
    server.registerChat(chat);
    server.placeCall(id, chatId);
    ringTimer = window.setTimeout(noAnswer, RING_TIMEOUT);
  }
}

/** Accept an incoming call, with or without my camera. */
export function acceptCall(withVideo: boolean) {
  const c = call();
  if (!c || c.phase !== 'incoming') return;
  clearTimeout(ringTimer);
  stopTone();
  mediaReady = acquireMedia(c.id, withVideo);
  if (c.mode === 'real') {
    // Everyone already in the call connects to me (the caller always does).
    patchCall({ phase: 'connected', connectedAt: Date.now(), cameraOn: withVideo });
    sendCall('accept', roster(c), { cameraOn: withVideo });
  } else {
    server.answerCall(c.id, c.participants[0].contactId);
    patchCall({
      phase: 'connected',
      connectedAt: Date.now(),
      cameraOn: withVideo,
      participants: c.participants.map((p) => ({ ...p, state: 'connected' })),
    });
  }
  playConnectTone();
}

export function declineCall() {
  const c = call();
  if (!c || c.phase !== 'incoming') return;
  if (c.mode === 'real') sendCall('decline', roster(c));
  else server.endCall(c.id, c.participants.map((p) => p.contactId));
  finish('declined', 'Звонок отклонён');
}

export function hangUp() {
  const c = call();
  if (!c || c.phase === 'ended') return;
  if (c.phase === 'incoming') return declineCall();
  if (c.mode === 'real') sendCall(c.phase === 'calling' ? 'cancel' : 'end', roster(c));
  else server.endCall(c.id, c.participants.map((p) => p.contactId));
  finish(c.phase === 'connected' ? 'answered' : 'cancelled', 'Звонок завершён');
}

/** The internet (or the server, for a real call) dropped — a call can't go on without it. */
export function onConnectionLost(realOnly = false) {
  const c = call();
  if (!c || c.phase === 'ended' || (realOnly && c.mode !== 'real')) return;
  if (c.mode === 'demo') server.endCall(c.id, c.participants.map((p) => p.contactId));
  finish(c.phase === 'connected' ? 'answered' : c.phase === 'incoming' ? 'missed' : 'cancelled', 'Соединение потеряно');
}

function noAnswer() {
  const c = call();
  if (!c || c.phase !== 'calling') return;
  if (c.mode === 'real') sendCall('cancel', roster(c));
  else server.endCall(c.id, c.participants.map((p) => p.contactId));
  const unreachable = c.participants.every((p) => p.state === 'unavailable' || !getContact(p.contactId)?.online);
  finish('unavailable', unreachable ? (c.participants.length > 1 ? 'Никого нет в сети' : 'Абонент не в сети') : 'Нет ответа');
}

// ---- demo calls: events from the mock server --------------------------------------------

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
      ring({ id: e.callId, mode: 'demo', chatId: e.chatId, kind: e.kind, participants: [{ contactId: e.contactId, state: 'ringing' }] });
      ringTimer = undefined;
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
      checkEmpty();
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

// ---- real calls: events from the server ----------------------------------------------------

interface CallMsg {
  action: string;
  callId: string;
  from: string;
  fromName?: string;
  kind: CallKind;
  cameraOn?: boolean;
  muted?: boolean;
  chat?: { kind: 'direct' | 'group'; id?: string; title?: string; members?: string[] };
}

export function handleRealCall(m: CallMsg) {
  const c = call();
  const me = net.me?.phone;
  if (!me) return;

  if (m.action === 'invite') {
    const caller = ensureRealContact(m.from, m.fromName);
    if (c && c.id !== m.callId) {
      sendTo([m.from], 'busy', m.callId);
      logCall(caller.id, caller.id, { kind: m.kind, direction: 'in', outcome: 'missed' });
      return;
    }
    if (c) return;
    let chatId = caller.id;
    let others = [caller.id];
    if (m.chat?.kind === 'group' && m.chat.id) {
      const chat = realGroupFromServer(m.chat.id, m.chat.title ?? '', [m.from, ...(m.chat.members ?? [])]);
      chatId = chat.id;
      others = [caller.id, ...chat.memberIds.filter((id) => id !== caller.id)];
    } else {
      ensureDirectChat(caller.id);
    }
    ring({
      id: m.callId,
      mode: 'real',
      chatId,
      kind: m.kind,
      // The caller first (shown on the incoming screen); the others are being called too.
      participants: others.map((contactId, i) => ({ contactId, state: i === 0 ? 'connected' : 'ringing', cameraOn: i === 0 && m.kind === 'video' })),
    });
    ringTimer = window.setTimeout(() => {
      const now = call();
      if (now?.id === m.callId && now.phase === 'incoming') finish('missed', 'Пропущенный звонок');
    }, REAL_RING_TIMEOUT);
    return;
  }

  if (!c || c.id !== m.callId || c.mode !== 'real' || c.phase === 'ended') return;
  const from = contactOfPhone(m.from)?.id ?? ensureRealContact(m.from, m.fromName).id;
  const isCaller = c.direction === 'in' && c.participants[0]?.contactId === from;

  switch (m.action) {
    case 'accept':
    case 'here': {
      if (!c.participants.some((p) => p.contactId === from)) {
        patchCall({ participants: [...c.participants, { contactId: from, state: 'connected' }] });
      }
      updateParticipant(m.from, { state: 'connected', cameraOn: m.cameraOn, muted: m.muted });
      if (m.action === 'accept') {
        // Let the newcomer know I'm in, so the two of us connect.
        if (c.phase === 'connected' || c.direction === 'out') sendTo([m.from], 'here', c.id);
        if (c.phase === 'calling') {
          clearTimeout(ringTimer);
          patchCall({ phase: 'connected', connectedAt: Date.now() });
          playConnectTone();
        }
      }
      if (shouldOffer(c, m.from, me) && !hasPeer(m.from) && call()?.phase === 'connected') callPeer(m.from).catch(() => {});
      return;
    }
    case 'decline':
    case 'busy':
      updateParticipant(m.from, { state: 'declined' });
      if (c.phase === 'incoming') return; // someone else declined this group call — mine keeps ringing
      if (c.phase === 'calling' && m.action === 'busy' && c.participants.length === 1) return void finish('declined', 'Абонент занят');
      checkEmpty();
      return;
    case 'unavailable':
      updateParticipant(m.from, { state: 'unavailable' });
      if (c.phase === 'calling' && call()!.participants.every((p) => p.state === 'unavailable')) {
        window.setTimeout(() => {
          const now = call();
          if (now?.id === c.id && now.phase === 'calling') {
            clearTimeout(ringTimer);
            finish('unavailable', now.participants.length > 1 ? 'Никого нет в сети' : 'Абонент не в сети');
          }
        }, 2000);
      }
      return;
    case 'cancel':
    case 'end':
      closePeer(m.from);
      if (c.phase === 'incoming' && isCaller) return void finish('missed', 'Пропущенный звонок');
      updateParticipant(m.from, { state: 'left', stream: undefined });
      checkEmpty();
      return;
    case 'media':
      updateParticipant(m.from, { cameraOn: m.cameraOn, muted: m.muted });
      return;
  }
}

export function handleRtc(m: { callId: string; from: string; data: object }) {
  const c = call();
  if (!c || c.id !== m.callId || c.mode !== 'real') return;
  onSignal(m.from, m.data as never).catch(() => {});
}

/** Pair rule for group calls: the caller offers to everyone; between others, the smaller number offers. */
function shouldOffer(c: ActiveCall, other: string, me: string) {
  if (c.direction === 'out') return true;
  const callerPhone = phoneOf(c.participants[0].contactId);
  if (other === callerPhone) return false;
  return me < other;
}

// ---- in-call controls ---------------------------------------------------------------------

export function toggleMute() {
  const c = call();
  if (!c) return;
  const muted = !c.muted;
  c.localStream?.getAudioTracks().forEach((t) => (t.enabled = !muted));
  patchCall({ muted });
  announceMedia();
}

export async function toggleCamera() {
  const c = call();
  if (!c || c.phase === 'ended') return;
  if (c.cameraOn) {
    c.localStream?.getVideoTracks().forEach((t) => t.stop());
    const audioOnly = c.localStream ? new MediaStream(c.localStream.getAudioTracks()) : null;
    patchCall({ cameraOn: false, localStream: audioOnly });
    if (c.mode === 'real') replaceLocalTracks(audioOnly);
    announceMedia();
    return;
  }
  patchCall({ cameraOn: true });
  try {
    const cam = await navigator.mediaDevices.getUserMedia({ video: videoConstraints(c.facing) });
    const now = call();
    if (!now || now.id !== c.id || !now.cameraOn || now.phase === 'ended') return cam.getTracks().forEach((t) => t.stop());
    const stream = new MediaStream([...(now.localStream?.getAudioTracks() ?? []), ...cam.getVideoTracks()]);
    patchCall({ localStream: stream, mediaError: undefined });
    if (now.mode === 'real') replaceLocalTracks(stream);
    announceMedia();
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
    const stream = new MediaStream([...(now.localStream?.getAudioTracks() ?? []), ...cam.getVideoTracks()]);
    patchCall({ facing, localStream: stream });
    if (now.mode === 'real') replaceLocalTracks(stream);
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

function ring(init: Pick<ActiveCall, 'id' | 'mode' | 'chatId' | 'kind' | 'participants'>) {
  setCall({ ...init, direction: 'in', phase: 'incoming', startedAt: Date.now(), muted: false, cameraOn: false, facing: 'user', localStream: null, minimized: false });
  playRingtone();
  if (document.visibilityState === 'hidden' && 'Notification' in window && Notification.permission === 'granted') {
    const name = getContact(init.participants[0].contactId)?.name ?? 'Связь';
    try {
      new Notification(name, { body: init.kind === 'video' ? 'Входящий видеозвонок' : 'Входящий звонок', tag: init.id });
    } catch {
      /* not allowed here */
    }
  }
}

/** Everyone in the call except me (phones). */
function roster(c: ActiveCall) {
  return c.participants.map((p) => phoneOf(p.contactId)).filter(Boolean);
}

function sendCall(action: string, to: string[], extra: object = {}) {
  const c = call();
  if (!c || !to.length) return;
  net.send({ type: 'call', action, callId: c.id, to, kind: c.kind, ...extra });
}

function sendTo(to: string[], action: string, callId: string) {
  const c = call();
  net.send({ type: 'call', action, callId, to, kind: c?.kind ?? 'audio', cameraOn: c?.cameraOn, muted: c?.muted });
}

function announceMedia() {
  const c = call();
  if (c?.mode === 'real' && c.phase === 'connected') sendCall('media', roster(c), { cameraOn: c.cameraOn, muted: c.muted });
}

function updateParticipant(phoneOrId: string, patch: Partial<CallParticipant>) {
  const c = call();
  if (!c) return;
  const id = contactOfPhone(phoneOrId)?.id ?? phoneOrId;
  if (!c.participants.some((p) => p.contactId === id)) return;
  patchCall({ participants: c.participants.map((p) => (p.contactId === id ? { ...p, ...patch } : p)) });
}

/** Nobody left to talk to → the call is over. */
function checkEmpty() {
  const c = call();
  if (!c || c.phase === 'ended') return;
  // While talking, only people on the line keep the call going; while calling, anyone still ringing.
  const stillThere = c.participants.some((p) => p.state === 'connected' || (c.phase === 'calling' && p.state === 'ringing'));
  if (stillThere) return;
  if (c.phase === 'connected') finish('answered', c.participants.length > 1 ? 'Все участники вышли' : 'Собеседник завершил звонок');
  else finish('declined', 'Звонок отклонён');
}

async function acquireMedia(callId: string, video: boolean): Promise<MediaStream | null> {
  if (!navigator.mediaDevices?.getUserMedia) {
    patchCall({ cameraOn: false, mediaError: 'Браузер не даёт доступ к камере и микрофону' });
    return null;
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
    return null;
  }
  stream?.getAudioTracks().forEach((t) => (t.enabled = !c.muted));
  const hasVideo = !!stream?.getVideoTracks().length;
  patchCall({ localStream: stream, mediaError: error, cameraOn: c.cameraOn && hasVideo });
  return stream;
}

function finish(outcome: CallOutcome, endText: string) {
  const c = call();
  if (!c || c.phase === 'ended') return;
  clearTimeout(ringTimer);
  if (c.mode === 'real') closeAll();
  c.localStream?.getTracks().forEach((t) => t.stop());
  mediaReady = Promise.resolve(null);
  const now = Date.now();
  const duration = outcome === 'answered' && c.connectedAt ? Math.round((now - c.connectedAt) / 1000) : undefined;
  const log: CallLog = { kind: c.kind, direction: c.direction, outcome, duration };
  logCall(c.chatId, c.direction === 'in' ? c.participants[0].contactId : undefined, log);
  if (outcome === 'missed') stopTone();
  else playEndTone();
  setCall({ ...c, phase: 'ended', endedAt: now, endText, localStream: null, participants: c.participants.map((p) => ({ ...p, stream: undefined })) });
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
