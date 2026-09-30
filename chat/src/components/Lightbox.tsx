import { useEffect } from 'react';
import type { MediaRef } from '../types';
import { formatSize } from '../utils';
import { useMediaUrl } from './useMediaUrl';
import { CloseIcon, DownloadIcon } from './icons';

export function Lightbox({ media, onClose }: { media: MediaRef; onClose: () => void }) {
  const url = useMediaUrl(media.id);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-modal="true" aria-label="Просмотр фото">
      <div className="lightbox__bar" onClick={(e) => e.stopPropagation()}>
        <span className="lightbox__name">
          {media.name} · {formatSize(media.size)}
        </span>
        {url && (
          <a className="icon-btn icon-btn--light" href={url} download={media.name} aria-label="Скачать">
            <DownloadIcon />
          </a>
        )}
        <button className="icon-btn icon-btn--light" onClick={onClose} aria-label="Закрыть">
          <CloseIcon />
        </button>
      </div>
      {url && <img className="lightbox__img" src={url} alt={media.name} onClick={(e) => e.stopPropagation()} />}
    </div>
  );
}
