// WebRTC for real calls: one RTCPeerConnection per other participant (a mesh, fine for
// small groups). Offers/answers and ICE candidates travel through the server ("rtc").
//
// Every connection always has one audio and one video transceiver, so turning the
// camera on/off or switching it later is just replaceTrack() — no renegotiation.

interface Peer {
  pc: RTCPeerConnection;
  remote: MediaStream;
  pending: RTCIceCandidateInit[];
  remoteSet: boolean;
}

export interface RtcHooks {
  iceServers: () => RTCIceServer[];
  /** Resolves when my camera/microphone are ready (or null if refused). */
  localStream: () => Promise<MediaStream | null>;
  signal: (to: string, data: object) => void;
  onStream: (phone: string, stream: MediaStream) => void;
  onState: (phone: string, state: RTCPeerConnectionState) => void;
}

const peers = new Map<string, Peer>();
let hooks: RtcHooks | null = null;

export function setupRtc(h: RtcHooks) {
  hooks = h;
}

export function hasPeer(phone: string) {
  return peers.has(phone);
}

function create(phone: string): Peer {
  const pc = new RTCPeerConnection({ iceServers: hooks!.iceServers() });
  const peer: Peer = { pc, remote: new MediaStream(), pending: [], remoteSet: false };
  peers.set(phone, peer);
  pc.onicecandidate = (e) => {
    if (e.candidate) hooks!.signal(phone, { candidate: e.candidate.toJSON() });
  };
  pc.ontrack = (e) => {
    if (!peer.remote.getTracks().includes(e.track)) peer.remote.addTrack(e.track);
    // A new MediaStream object so React sees the change.
    hooks!.onStream(phone, new MediaStream(peer.remote.getTracks()));
    const refresh = () => hooks!.onStream(phone, new MediaStream(peer.remote.getTracks()));
    e.track.onunmute = refresh;
    e.track.onmute = refresh;
  };
  let restarted = false;
  pc.onconnectionstatechange = () => {
    hooks!.onState(phone, pc.connectionState);
    // One ICE restart when the network changed (Wi-Fi → mobile data).
    if (pc.connectionState === 'failed' && !restarted && pc.signalingState === 'stable' && isOfferer.get(phone)) {
      restarted = true;
      pc.restartIce();
      offer(phone, peer, true).catch(() => {});
    }
  };
  return peer;
}

const isOfferer = new Map<string, boolean>();

/** Start a connection to `phone`: I make the offer. */
export async function callPeer(phone: string) {
  if (peers.has(phone)) return;
  const peer = create(phone);
  isOfferer.set(phone, true);
  const stream = await hooks!.localStream();
  if (peers.get(phone) !== peer) return; // closed meanwhile
  const audio = stream?.getAudioTracks()[0];
  const video = stream?.getVideoTracks()[0];
  const local = stream ?? new MediaStream();
  if (audio) peer.pc.addTrack(audio, local);
  else peer.pc.addTransceiver('audio', { direction: 'sendrecv' });
  if (video) peer.pc.addTrack(video, local);
  else peer.pc.addTransceiver('video', { direction: 'sendrecv' });
  await offer(phone, peer);
}

async function offer(phone: string, peer: Peer, iceRestart = false) {
  const o = await peer.pc.createOffer(iceRestart ? { iceRestart: true } : undefined);
  await peer.pc.setLocalDescription(o);
  hooks!.signal(phone, { sdp: peer.pc.localDescription!.toJSON() });
}

/** Offer/answer/candidate from `phone`. */
export async function onSignal(phone: string, data: { sdp?: RTCSessionDescriptionInit; candidate?: RTCIceCandidateInit }) {
  let peer = peers.get(phone);
  if (data.sdp) {
    if (data.sdp.type === 'offer') {
      if (!peer) {
        peer = create(phone);
        isOfferer.set(phone, false);
      }
      await peer.pc.setRemoteDescription(data.sdp);
      peer.remoteSet = true;
      await flushCandidates(peer);
      // Answer with my tracks on the transceivers the offer created.
      const stream = await hooks!.localStream();
      if (peers.get(phone) !== peer) return;
      for (const t of peer.pc.getTransceivers()) {
        const kind = t.receiver.track.kind;
        const track = (kind === 'audio' ? stream?.getAudioTracks()[0] : stream?.getVideoTracks()[0]) ?? null;
        await t.sender.replaceTrack(track);
        if (track && stream) t.sender.setStreams?.(stream);
        t.direction = 'sendrecv';
      }
      const answer = await peer.pc.createAnswer();
      await peer.pc.setLocalDescription(answer);
      hooks!.signal(phone, { sdp: peer.pc.localDescription!.toJSON() });
    } else if (peer) {
      await peer.pc.setRemoteDescription(data.sdp);
      peer.remoteSet = true;
      await flushCandidates(peer);
    }
    return;
  }
  if (data.candidate && peer) {
    if (peer.remoteSet) await peer.pc.addIceCandidate(data.candidate).catch(() => {});
    else peer.pending.push(data.candidate);
  }
}

async function flushCandidates(peer: Peer) {
  for (const c of peer.pending.splice(0)) await peer.pc.addIceCandidate(c).catch(() => {});
}

/** My camera/microphone changed: send the new tracks to everyone. */
export function replaceLocalTracks(stream: MediaStream | null) {
  const audio = stream?.getAudioTracks()[0] ?? null;
  const video = stream?.getVideoTracks()[0] ?? null;
  for (const { pc } of peers.values()) {
    for (const t of pc.getTransceivers()) {
      if (t.currentDirection === 'stopped') continue;
      const kind = t.receiver.track.kind;
      t.sender.replaceTrack(kind === 'audio' ? audio : video).catch(() => {});
    }
  }
}

export function closePeer(phone: string) {
  const peer = peers.get(phone);
  if (!peer) return;
  peers.delete(phone);
  isOfferer.delete(phone);
  peer.pc.onconnectionstatechange = null;
  peer.pc.close();
}

export function closeAll() {
  [...peers.keys()].forEach(closePeer);
}
