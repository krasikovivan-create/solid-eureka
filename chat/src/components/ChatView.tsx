import { useCallback, useEffect, useState } from 'react';
import type { MediaRef, Message } from '../types';
import { isOnline, showToast, useAppState } from '../store';
import { MAX_FILE_SIZE, readChat, setActiveChat } from '../sync';
import { startCall } from '../calls';
import { chatLook, formatLastSeen, plural, uid } from '../utils';
import { ChatAvatar } from './Avatar';
import { ChatInfo } from './ChatInfo';
import { Composer, type Attachment } from './Composer';
import { MessageList } from './MessageList';
import { Lightbox } from './Lightbox';
import { BackIcon, ImageIcon, PhoneIcon, VideoIcon, WifiOffIcon } from './icons';

const EMPTY: Message[] = [];

interface Props {
  chatId: string;
  active: boolean;
  onBack: () => void;
}

export function ChatView({ chatId, active, onBack }: Props) {
  const chat = useAppState((s) => s.chats.find((c) => c.id === chatId));
  const contacts = useAppState((s) => s.contacts);
  const messages = useAppState((s) => s.messages[chatId] ?? EMPTY);
  const typer = useAppState((s) => s.typing[chatId]);
  const inCall = useAppState((s) => !!s.call && s.call.phase !== 'ended');
  const [infoOpen, setInfoOpen] = useState(false);
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
    const read = () => document.visibilityState === 'visible' && readChat(chatId);
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

  if (!chat) return null;

  const look = chatLook(chat, contacts);
  const typing = !!typer;
  let status: string;
  let statusOnline = false;
  if (chat.kind === 'group') {
    const members = chat.memberIds.map((id) => contacts.find((c) => c.id === id)).filter(Boolean);
    const onlineCount = members.filter((c) => c!.online).length;
    const typerName = typer ? contacts.find((c) => c.id === typer)?.name.split(' ')[0] : undefined;
    const count = members.length + 1; // + me
    status = typerName
      ? `${typerName} печатает…`
      : `${count} ${plural(count, 'участник', 'участника', 'участников')}${online && onlineCount ? `, ${onlineCount} в сети` : ''}`;
  } else {
    const contact = look.contact;
    statusOnline = !!contact?.online && online;
    status = typing ? 'печатает…' : !online ? 'ожидание сети…' : contact?.online ? 'в сети' : contact ? formatLastSeen(contact) : '';
  }
  const call = (kind: 'audio' | 'video') => startCall(chatId, kind);

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
        <button className="chat__who" onClick={() => setInfoOpen(true)} aria-label="Информация о чате">
          <ChatAvatar chat={chat} size={40} showStatus={online} />
          <span className="chat__title">
            <span className="chat__name">{look.name}</span>
            <span className={`chat__status ${typing ? 'is-typing' : statusOnline ? 'is-online' : ''}`} key={status}>
              {status}
            </span>
          </span>
        </button>
        <div className="chat__actions">
          <button className="icon-btn icon-btn--accent" onClick={() => call('audio')} disabled={inCall} aria-label="Аудиозвонок" title={online ? 'Аудиозвонок' : 'Звонки доступны только онлайн'}>
            <PhoneIcon width={22} height={22} />
          </button>
          <button className="icon-btn icon-btn--accent" onClick={() => call('video')} disabled={inCall} aria-label="Видеозвонок" title={online ? 'Видеозвонок' : 'Звонки доступны только онлайн'}>
            <VideoIcon width={22} height={22} />
          </button>
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

      <MessageList key={chatId} chat={chat} messages={messages} typer={typer} onOpenImage={setViewing} />

      <Composer chatId={chatId} attachments={attachments} onAddFiles={addFiles} onRemove={removeAttachment} onClear={clearAttachments} />

      {dragging && (
        <div className="drop-zone">
          <ImageIcon width={40} height={40} />
          <span>Отпустите, чтобы прикрепить</span>
        </div>
      )}
      {viewing && <Lightbox media={viewing} onClose={() => setViewing(null)} />}
      <ChatInfo chat={chat} open={infoOpen} onClose={() => setInfoOpen(false)} />
    </section>
  );
}
