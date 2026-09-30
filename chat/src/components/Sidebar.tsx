import { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { Contact, Message } from '../types';
import { isOnline, useAppState } from '../store';
import { resetDemo, setSimulatedOffline } from '../sync';
import { formatListTime, messagePreview } from '../utils';
import { Avatar } from './Avatar';
import { MoreIcon, RefreshIcon, SearchIcon, StatusIcon, WifiOffIcon } from './icons';

interface Props {
  activeId: string | null;
  onOpen: (chatId: string) => void;
}

export function Sidebar({ activeId, onOpen }: Props) {
  const contacts = useAppState((s) => s.contacts);
  const messages = useAppState((s) => s.messages);
  const drafts = useAppState((s) => s.drafts);
  const typing = useAppState((s) => s.typing);
  const online = useAppState(isOnline);
  const [query, setQuery] = useState('');

  const chats = useMemo(() => {
    const q = query.trim().toLowerCase();
    return contacts
      .map((contact) => {
        const list = messages[contact.id] ?? [];
        return {
          contact,
          last: list[list.length - 1] as Message | undefined,
          unread: list.filter((m) => m.author === 'them' && m.status !== 'read').length,
        };
      })
      .filter(({ contact, last }) => !q || contact.name.toLowerCase().includes(q) || last?.text.toLowerCase().includes(q))
      .sort((a, b) => (b.last?.createdAt ?? 0) - (a.last?.createdAt ?? 0));
  }, [contacts, messages, query]);

  const onlineCount = contacts.filter((c) => c.online).length;

  return (
    <aside className="sidebar">
      <header className="sidebar__header">
        <div className="sidebar__title">
          <h1>Чаты</h1>
          <ConnectionPill />
        </div>
        <Menu />
      </header>
      <label className="search">
        <SearchIcon width={18} height={18} />
        <input type="search" placeholder="Поиск" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <div className="sidebar__sub">{online ? `В сети: ${onlineCount} из ${contacts.length}` : 'Статусы контактов обновятся после подключения'}</div>
      <ul className="chat-list">
        {chats.map(({ contact, last, unread }, i) => (
          <ChatListItem
            key={contact.id}
            index={i}
            contact={contact}
            last={last}
            unread={unread}
            draft={contact.id !== activeId ? drafts[contact.id] : undefined}
            typing={!!typing[contact.id]}
            active={contact.id === activeId}
            showPresence={online}
            onOpen={onOpen}
          />
        ))}
        {chats.length === 0 && <li className="chat-list__empty">Ничего не найдено</li>}
      </ul>
    </aside>
  );
}

interface ItemProps {
  index: number;
  contact: Contact;
  last?: Message;
  unread: number;
  draft?: string;
  typing: boolean;
  active: boolean;
  showPresence: boolean;
  onOpen: (id: string) => void;
}

const ChatListItem = memo(function ChatListItem({ index, contact, last, unread, draft, typing, active, showPresence, onOpen }: ItemProps) {
  let preview: React.ReactNode = last ? messagePreview(last) : 'Нет сообщений';
  if (draft) preview = (<><span className="chat-item__draft">Черновик:</span> {draft}</>);
  if (typing) preview = <span className="chat-item__typing">печатает…</span>;

  return (
    <li style={{ '--i': index } as React.CSSProperties}>
      <button className={`chat-item ${active ? 'is-active' : ''} ${unread ? 'has-unread' : ''}`} onClick={() => onOpen(contact.id)}>
        <Avatar contact={contact} size={52} showStatus={showPresence} />
        <div className="chat-item__body">
          <div className="chat-item__top">
            <span className="chat-item__name">{contact.name}</span>
            <span className="chat-item__time">
              {last?.author === 'me' && !typing && !draft && <StatusIcon status={last.status} />}
              {last && formatListTime(last.createdAt)}
            </span>
          </div>
          <div className="chat-item__bottom">
            <span className="chat-item__preview">
              {last?.author === 'me' && !typing && !draft && <span className="chat-item__you">Вы: </span>}
              {preview}
            </span>
            {unread > 0 && <span className="badge">{unread}</span>}
          </div>
        </div>
      </button>
    </li>
  );
});

function ConnectionPill() {
  const { browserOnline, simulatedOffline, syncing } = useAppState((s) => s.connection);
  const online = browserOnline && !simulatedOffline;
  const pendingTotal = useAppState((s) => {
    let n = 0;
    for (const list of Object.values(s.messages)) for (const m of list) if (m.status === 'pending') n++;
    return n;
  });

  let label = 'Онлайн';
  let cls = 'is-online';
  if (!online) {
    label = simulatedOffline ? 'Офлайн (режим полёта)' : 'Офлайн';
    cls = 'is-offline';
  } else if (syncing > 0 || pendingTotal > 0) {
    label = `Синхронизация… ${syncing || pendingTotal}`;
    cls = 'is-syncing';
  }

  return (
    <span className={`conn-pill ${cls}`} role="status" aria-live="polite">
      <span className="conn-pill__dot" />
      {label}
      {!online && pendingTotal > 0 && <span className="conn-pill__count">{pendingTotal} в очереди</span>}
    </span>
  );
}

function Menu() {
  const [open, setOpen] = useState(false);
  const simulatedOffline = useAppState((s) => s.connection.simulatedOffline);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  return (
    <div className="menu" ref={ref}>
      <button className="icon-btn" onClick={() => setOpen((v) => !v)} aria-label="Меню" aria-expanded={open}>
        <MoreIcon />
      </button>
      <div className={`menu__panel ${open ? 'is-open' : ''}`} role="menu">
        <label className="menu__item">
          <WifiOffIcon width={20} height={20} />
          <span className="menu__label">
            Режим полёта
            <small>Проверить офлайн без отключения сети</small>
          </span>
          <input type="checkbox" className="switch" checked={simulatedOffline} onChange={(e) => setSimulatedOffline(e.target.checked)} />
        </label>
        <button
          className="menu__item"
          role="menuitem"
          onClick={() => {
            setOpen(false);
            if (confirm('Удалить все сообщения и файлы и вернуть демо-переписку?')) resetDemo();
          }}
        >
          <RefreshIcon width={20} height={20} />
          <span className="menu__label">
            Сбросить демо-данные
            <small>Очистить localStorage и IndexedDB</small>
          </span>
        </button>
      </div>
    </div>
  );
}
