import { useEffect, useState } from 'react';
import { loadMediaUrl, MEDIA_READY_EVENT, peekMediaUrl } from '../storage/media';

/** Object URL for a photo/video stored in IndexedDB; undefined while loading, null if missing. */
export function useMediaUrl(id: string): string | null | undefined {
  const [url, setUrl] = useState<string | null | undefined>(() => peekMediaUrl(id));

  useEffect(() => {
    let alive = true;
    const load = () => loadMediaUrl(id).then((u) => alive && setUrl(u));
    load();
    const onReady = (e: Event) => {
      if ((e as CustomEvent<string>).detail === id) load();
    };
    window.addEventListener(MEDIA_READY_EVENT, onReady);
    return () => {
      alive = false;
      window.removeEventListener(MEDIA_READY_EVENT, onReady);
    };
  }, [id]);

  return url;
}
