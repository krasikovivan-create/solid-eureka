import { memo, useState } from 'react';
import type { MediaRef, Message } from '../types';
import { isOnline, useAppState } from '../store';
import { formatDuration, formatMoment, formatSize, formatTime } from '../utils';
import { useMediaUrl } from './useMediaUrl';
import { ImageIcon, PlayIcon, StatusIcon, VideoIcon } from './icons';

interface Props {
  message: Message;
  first: boolean;
  last: boolean;
  animate: boolean;
  onOpenImage: (media: MediaRef) => void;
}

export const MessageBubble = memo(function MessageBubble({ message, first, last, animate, onOpenImage }: Props) {
  const [showInfo, setShowInfo] = useState(false);
  const mine = message.author === 'me';
  const mediaOnly = !!message.media && !message.text;

  const classes = [
    'msg',
    mine ? 'msg--mine' : 'msg--theirs',
    first && 'msg--first',
    last && 'msg--last',
    animate && 'msg--new',
    message.media && 'msg--has-media',
    mediaOnly && 'msg--media-only',
    message.status === 'pending' && 'msg--pending',
  ]
    .filter(Boolean)
    .join(' ');

  const meta = (
    <span className="msg__meta">
      {formatTime(message.createdAt)}
      {mine && <StatusIcon status={message.status} />}
    </span>
  );

  return (
    <div className={classes}>
      <div
        className="msg__bubble"
        onClick={mine ? () => setShowInfo((v) => !v) : undefined}
        role={mine ? 'button' : undefined}
        tabIndex={mine ? 0 : undefined}
        onKeyDown={mine ? (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), setShowInfo((v) => !v)) : undefined}
        aria-expanded={mine ? showInfo : undefined}
        title={mine ? 'Нажмите, чтобы увидеть время доставки' : undefined}
      >
        {message.media && <MediaView media={message.media} pending={message.status === 'pending'} onOpen={onOpenImage} overlayMeta={mediaOnly ? meta : null} />}
        {message.text && (
          <div className="msg__text">
            {message.text}
            {meta}
          </div>
        )}
      </div>
      {mine && (
        <div className={`msg__info ${showInfo ? 'is-open' : ''}`} aria-hidden={!showInfo}>
          <div className="msg__info-inner">
            <InfoRow label="Создано" time={message.createdAt} />
            <InfoRow label="Отправлено" time={message.sentAt} waiting="ждёт сети" />
            <InfoRow label="Доставлено" time={message.deliveredAt} waiting={message.sentAt ? 'ещё нет' : '—'} />
            <InfoRow label="Прочитано" time={message.readAt} waiting={message.deliveredAt ? 'ещё нет' : '—'} />
          </div>
        </div>
      )}
    </div>
  );
});

function InfoRow({ label, time, waiting = '' }: { label: string; time?: number; waiting?: string }) {
  return (
    <div className="info-row">
      <span>{label}</span>
      <span className={time ? '' : 'info-row__muted'}>{time ? formatMoment(time) : waiting}</span>
    </div>
  );
}

interface MediaProps {
  media: MediaRef;
  pending: boolean;
  onOpen: (media: MediaRef) => void;
  overlayMeta: React.ReactNode;
}

function MediaView({ media, pending, onOpen, overlayMeta }: MediaProps) {
  const url = useMediaUrl(media.id);
  const online = useAppState(isOnline);
  const [loaded, setLoaded] = useState(false);
  const ratio = media.width && media.height ? media.width / media.height : media.kind === 'video' ? 16 / 9 : 4 / 3;
  // Portrait media gets narrower so it doesn't take the whole screen.
  const style = { aspectRatio: String(Math.min(Math.max(ratio, 0.6), 2.2)) };

  return (
    <div className={`media media--${media.kind} ${loaded ? 'is-loaded' : ''}`} style={style} onClick={(e) => {
        // Taps on the photo/video itself shouldn't toggle delivery details; the time badge still does.
        if (!(e.target as HTMLElement).closest('.media__meta')) e.stopPropagation();
      }}>
      {url === null && (
        <div className="media__missing">
          {media.kind === 'image' ? <ImageIcon /> : <VideoIcon />}
          <span>Файл недоступен</span>
        </div>
      )}
      {url && media.kind === 'image' && (
        <button className="media__open" onClick={() => onOpen(media)} aria-label="Открыть фото">
          <img src={url} alt={media.name} onLoad={() => setLoaded(true)} draggable={false} />
        </button>
      )}
      {url && media.kind === 'video' && (
        // "#t=0.1" makes iOS Safari show the first frame instead of a black box.
        <video src={`${url}#t=0.1`} controls playsInline preload="metadata" onLoadedData={() => setLoaded(true)} onLoadedMetadata={() => setLoaded(true)} />
      )}
      {url === undefined && <div className="media__skeleton" />}
      {media.kind === 'video' && !loaded && url && (
        <span className="media__play" aria-hidden>
          <PlayIcon />
        </span>
      )}
      {media.kind === 'video' && media.duration !== undefined && <span className="media__badge">{formatDuration(media.duration)} · {formatSize(media.size)}</span>}
      {pending && (
        <div className="media__pending">
          <span className="spinner" />
          <span>{online ? 'Загрузка…' : 'Ждёт подключения'}</span>
        </div>
      )}
      {overlayMeta && <div className="media__meta">{overlayMeta}</div>}
    </div>
  );
}
