import { useCallback, useEffect, useState } from 'react';
import type { MediaRef, Message } from '../types';
import { isOnline, markChatRead, showToast, useAppState } from '../store';
import { MAX_FILE_SIZE, setActiveChat } from '../sync';
import { formatLastSeen, uid } from '../utils';
import { Avatar } from './Avatar';
import { Composer, type Attachment } from './Composer';
import { MessageList } from './MessageList';
import { Lightbox } from './Lightbox';
import { BackIcon, ImageIcon, WifiOffIcon } from './icons';

const EMPTY: Message[] = [];

interface Props {
  chatId: string;
  active: boolean;
  onBack: () => void;
}

export function ChatView({ chatId, active, onBack }: Props) {
  const contact = useAppState((s) => s.contacts.find((c) => c.id === chatId));
  const messages = useAppState((s) => s.messages[chatId] ?? EMPTY);
  const typing = useAppState((s) => !!s.typing[chatId]);
  const online = useAppState(isOnline);
  const pending = useAppState((s) => (s.messages[chatId] ?? EMPTY).filter((m) => m.status === 'pending').length);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [viewing, setViewing] = useState<MediaRef | null>(null);
  const [dragging, setDragging] = useState(false);
  const [, tick] = useState(0);

  useEffect(() => {
    if (!active) return;
    setActiveChat(chatId);
    return () => setActiveChat(null);
  }, [chatId, active]);

  // Reading: whatever arrives while the chat is open and visible counts as read.
  useEffect(() => {
    if (!active) return;
    const read = () => document.visibilityState === 'visible' && markChatRead(chatId);
    read();
    document.addEventListener('visibilitychange', read);
    return () => document.removeEventListener('visibilitychange', read);
  }, [chatId, active, messages]);

  // "был в сети 5 мин назад" has to tick.
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30_000);
    return () => clearInterval(t);
  }, []);

  const addFiles = useCallback((files: FileList | File[]) => {
    const next: Attachment[] = [];
    for (const file of Array.from(files)) {
      const kind = file.type.startsWith('image/') ? 'image' : file.type.startsWith('video/') ? 'video' : null;
      if (!kind) {
        showToast(`«${file.name}» — можно прикрепить только фото или видео`, 'warning');
        continue;
      }
      if (file.size > MAX_FILE_SIZE) {
        showToast(`«${file.name}» больше 100 МБ`, 'warning');
        continue;
      }
      next.push({ key: uid(), file, kind, url: URL.createObjectURL(file) });
    }
    setAttachments((prev) => [...prev, ...next].slice(0, 10));
  }, []);

  const removeAttachment = useCallback((key: string) => {
    setAttachments((prev) => {
      prev.filter((a) => a.key === key).forEach((a) => URL.revokeObjectURL(a.url));
      return prev.filter((a) => a.key !== key);
    });
  }, []);

  const clearAttachments = useCallback(() => {
    setAttachments((prev) => {
      prev.forEach((a) => URL.revokeObjectURL(a.url));
      return [];
    });
  }, []);

  if (!contact) return null;

  const status = typing ? 'печатает…' : !online ? 'ожидание сети…' : contact.online ? 'в сети' : formatLastSeen(contact);

  return (
    <section
      className="chat"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) {
          e.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
      }}
    >
      <header className="chat__header">
        <button className="icon-btn chat__back" onClick={onBack} aria-label="Назад к чатам">
          <BackIcon />
        </button>
        <Avatar contact={contact} size={40} showStatus={online} />
        <div className="chat__title">
          <div className="chat__name">{contact.name}</div>
          <div className={`chat__status ${typing ? 'is-typing' : contact.online && online ? 'is-online' : ''}`} key={status}>
            {status}
          </div>
        </div>
      </header>

      <div className={`offline-banner ${online ? '' : 'is-visible'}`} role="status">
        <div className="offline-banner__inner">
          <WifiOffIcon width={18} height={18} />
          <span>
            Нет подключения. {pending > 0 ? `В очереди: ${pending}. ` : ''}Сообщения сохраняются и отправятся автоматически.
          </span>
        </div>
      </div>

      <MessageList key={chatId} messages={messages} typing={typing} onOpenImage={setViewing} />

      <Composer chatId={chatId} attachments={attachments} onAddFiles={addFiles} onRemove={removeAttachment} onClear={clearAttachments} />

      {dragging && (
        <div className="drop-zone">
          <ImageIcon width={40} height={40} />
          <span>Отпустите, чтобы прикрепить</span>
        </div>
      )}
      {viewing && <Lightbox media={viewing} onClose={() => setViewing(null)} />}
    </section>
  );
}
