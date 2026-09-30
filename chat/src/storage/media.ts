// Photos and videos are stored as Blobs in IndexedDB (localStorage only holds strings
// and is limited to a few MB). Messages keep just a MediaRef with the id.

const DB_NAME = 'svyaz-media';
const STORE = 'files';

/** Fired on window (detail = media id) when a file appears after its message was rendered. */
export const MEDIA_READY_EVENT = 'svyaz:media-ready';

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    dbPromise.catch(() => (dbPromise = null));
  }
  return dbPromise;
}

function run<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const tx = db.transaction(STORE, mode);
        const req = fn(tx.objectStore(STORE));
        tx.oncomplete = () => resolve(req.result);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
      })
  );
}

export function putMedia(id: string, blob: Blob): Promise<void> {
  return run('readwrite', (s) => s.put(blob, id)).then(() => undefined);
}

export function getMedia(id: string): Promise<Blob | undefined> {
  return run<Blob | undefined>('readonly', (s) => s.get(id));
}

/** Delete every stored file except `keep` (the real chats' photos/videos). */
export async function clearMediaExcept(keep: Set<string>): Promise<void> {
  const keys = await run<IDBValidKey[]>('readonly', (s) => s.getAllKeys());
  const drop = keys.map(String).filter((k) => !keep.has(k));
  await Promise.all(drop.map((k) => run('readwrite', (s) => s.delete(k))));
  drop.forEach((k) => {
    const url = urlCache.get(k);
    if (url) URL.revokeObjectURL(url);
    urlCache.delete(k);
  });
}

export function clearMedia(): Promise<void> {
  urlCache.forEach((url) => URL.revokeObjectURL(url));
  urlCache.clear();
  return run('readwrite', (s) => s.clear()).then(() => undefined);
}

// Object URLs are cached so a picture isn't re-read from disk on every render.
const urlCache = new Map<string, string>();
const pending = new Map<string, Promise<string | null>>();

export function peekMediaUrl(id: string): string | undefined {
  return urlCache.get(id);
}

export function rememberMediaUrl(id: string, blob: Blob): string {
  const url = URL.createObjectURL(blob);
  urlCache.set(id, url);
  return url;
}

export function loadMediaUrl(id: string): Promise<string | null> {
  const cached = urlCache.get(id);
  if (cached) return Promise.resolve(cached);
  let p = pending.get(id);
  if (!p) {
    p = getMedia(id)
      .then((blob) => (blob ? rememberMediaUrl(id, blob) : null))
      .catch(() => null)
      .finally(() => pending.delete(id));
    pending.set(id, p);
  }
  return p;
}
