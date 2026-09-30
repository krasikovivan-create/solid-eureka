import { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { Chat, Contact, Message } from '../types';
import { isOnline, useAppState } from '../store';
import { openDirectChat, resetDemo, setShowDemo, setSimulatedOffline } from '../sync';
import { demoIncomingCall, startCall } from '../calls';
import { useUi } from '../ui';
import { chatLook, formatLastSeen, formatListTime, formatPhone, messagePreview } from '../utils';
import type { AppState } from '../types';
import { ChatAvatar, ContactAvatar } from './Avatar';
import { EditIcon, MoreIcon, PhoneIcon, ShareIcon, RefreshIcon, SearchIcon, StatusIcon, UserPlusIcon, UsersIcon, VideoIcon, WifiOffIcon } from './icons';

interface Props {
  activeId: string | null;
}

type Tab = 'chats' | 'contacts';

export function Sidebar({ activeId }: Props) {
  const { openSheet } = useUi();
  const contacts = useVisibleContacts();
  const online = useAppState(isOnline);
  const account = useAppState((s) => s.account);
  const net = useAppState((s) => s.net);
  const [tab, setTab] = useState<Tab>('chats');
  const [query, setQuery] = useState('');
  const onlineCount = contacts.filter((c) => c.online).length;
  const netText = { off: 'не подключено', connecting: 'подключение…', online: 'в сети', offline: 'нет связи с сервером', error: 'ошибка' }[net.status];

  return (
    <aside className="sidebar">
      <header className="sidebar__header">
        <div className="sidebar__title">
          <h1>{tab === 'chats' ? 'Чаты' : 'Контакты'}</h1>
          <ConnectionPill />
        </div>
        <div className="sidebar__actions">
          <button className="icon-btn icon-btn--accent" onClick={() => openSheet({ type: 'new-chat' })} aria-label="Новый чат" title="Новый чат или группа">
            <EditIcon />
          </button>
          <Menu />
        </div>
      </header>
      <div className="tabs" role="tablist">
        {(['chats', 'contacts'] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`tabs__tab ${tab === t ? 'is-active' : ''}`} onClick={() => setTab(t)}>
            {t === 'chats' ? 'Чаты' : 'Контакты'}
          </button>
        ))}
        <span className="tabs__indicator" style={{ transform: `translateX(${tab === 'chats' ? 0 : 100}%)` }} />
      </div>
      <label className="search">
        <SearchIcon width={18} height={18} />
        <input type="search" placeholder={tab === 'chats' ? 'Поиск по чатам' : 'Имя или номер'} value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      {account ? (
        <button className={`account-line is-${net.status}`} onClick={() => openSheet({ type: 'profile' })}>
          <span className="conn-pill__dot" />
          {formatPhone(account.phone)} · {netText}
        </button>
      ) : (
        <button className="connect-banner" onClick={() => openSheet({ type: 'profile' })}>
          <span className="connect-banner__icon">
            <PhoneIcon width={18} height={18} />
          </span>
          <span>
            <b>Подключите свой номер</b>
            <small>чтобы писать и звонить настоящим друзьям</small>
          </span>
        </button>
      )}
      <div className="sidebar__sub">{online ? `В сети: ${onlineCount} из ${contacts.length}` : 'Статусы контактов обновятся после подключения'}</div>
      {tab === 'chats' ? <ChatList activeId={activeId} query={query} /> : <ContactList query={query} />}
    </aside>
  );
}

/** Contacts shown in lists: real ones always, demo ones unless hidden. */
function useVisibleContacts() {
  const all = useAppState((s: AppState) => s.contacts);
  const showDemo = useAppState((s: AppState) => s.showDemo);
  return useMemo(() => (showDemo ? all : all.filter((c) => c.real)), [all, showDemo]);
}

// ---- chats ---------------------------------------------------------------------------------------

function ChatList({ activeId, query }: { activeId: string | null; query: string }) {
  const { openChat } = useUi();
  const allChats = useAppState((s) => s.chats);
  const contacts = useAppState((s) => s.contacts);
  const showDemo = useAppState((s) => s.showDemo);
  const messages = useAppState((s) => s.messages);
  const chats = useMemo(
    () => (showDemo ? allChats : allChats.filter((ch) => ch.memberIds.some((id) => contacts.find((c) => c.id === id)?.real))),
    [allChats, contacts, showDemo]
  );
  const drafts = useAppState((s) => s.drafts);
  const typing = useAppState((s) => s.typing);
  const online = useAppState(isOnline);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return chats
      .map((chat) => {
        const list = messages[chat.id] ?? [];
        return {
          chat,
          name: chatLook(chat, contacts).name,
          last: list[list.length - 1] as Message | undefined,
          unread: list.filter((m) => m.author === 'them' && m.status !== 'read').length,
        };
      })
      // A direct chat with no messages stays out of the list until someone writes.
      .filter(({ chat, last }) => last || chat.kind === 'group' || chat.id === activeId)
      .filter(({ name, last }) => !q || name.toLowerCase().includes(q) || last?.text.toLowerCase().includes(q))
      .sort((a, b) => (b.last?.createdAt ?? b.chat.createdAt) - (a.last?.createdAt ?? a.chat.createdAt));
  }, [chats, contacts, messages, query, activeId]);

  return (
    <ul className="chat-list">
      {rows.map(({ chat, name, last, unread }, i) => {
        const typer = typing[chat.id];
        return (
          <ChatListItem
            key={chat.id}
            index={i}
            chat={chat}
            name={name}
            last={last}
            senderName={chat.kind === 'group' && last?.author === 'them' && last.senderId ? contacts.find((c) => c.id === last.senderId)?.name.split(' ')[0] : undefined}
            unread={unread}
            draft={chat.id !== activeId ? drafts[chat.id] : undefined}
            typing={typer ? (chat.kind === 'group' ? `${contacts.find((c) => c.id === typer)?.name.split(' ')[0] ?? 'Кто-то'} печатает…` : 'печатает…') : undefined}
            active={chat.id === activeId}
            showPresence={online}
            onOpen={openChat}
          />
        );
      })}
      {rows.length === 0 && <li className="chat-list__empty">Ничего не найдено</li>}
    </ul>
  );
}

interface ItemProps {
  index: number;
  chat: Chat;
  name: string;
  last?: Message;
  senderName?: string;
  unread: number;
  draft?: string;
  typing?: string;
  active: boolean;
  showPresence: boolean;
  onOpen: (id: string) => void;
}

const ChatListItem = memo(function ChatListItem({ index, chat, name, last, senderName, unread, draft, typing, active, showPresence, onOpen }: ItemProps) {
  let preview: React.ReactNode = last ? messagePreview(last) : chat.kind === 'group' ? 'Группа создана' : 'Нет сообщений';
  const mineLast = last?.author === 'me' && !last.call;
  if (senderName) preview = (<><span className="chat-item__you">{senderName}: </span>{preview}</>);
  if (mineLast && !typing && !draft) preview = (<><span className="chat-item__you">Вы: </span>{preview}</>);
  if (draft) preview = (<><span className="chat-item__draft">Черновик:</span> {draft}</>);
  if (typing) preview = <span className="chat-item__typing">{typing}</span>;

  return (
    <li style={{ '--i': Math.min(index, 12) } as React.CSSProperties}>
      <button className={`chat-item ${active ? 'is-active' : ''} ${unread ? 'has-unread' : ''}`} onClick={() => onOpen(chat.id)}>
        <ChatAvatar chat={chat} size={52} showStatus={showPresence} />
        <div className="chat-item__body">
          <div className="chat-item__top">
            <span className="chat-item__name">
              {chat.kind === 'group' && <UsersIcon className="chat-item__group" width={15} height={15} />}
              {name}
            </span>
            <span className="chat-item__time">
              {mineLast && !typing && !draft && <StatusIcon status={last!.status} />}
              {last && formatListTime(last.createdAt)}
            </span>
          </div>
          <div className="chat-item__bottom">
            <span className={`chat-item__preview ${last?.call?.outcome === 'missed' ? 'is-missed' : ''}`}>{preview}</span>
            {unread > 0 && <span className="badge">{unread}</span>}
          </div>
        </div>
      </button>
    </li>
  );
});

// ---- contacts -------------------------------------------------------------------------------------

function ContactList({ query }: { query: string }) {
  const { openChat, openSheet } = useUi();
  const contacts = useVisibleContacts();
  const online = useAppState(isOnline);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    const qDigits = q.replace(/\D/g, '');
    return contacts
      .filter((c) => !q || c.name.toLowerCase().includes(q) || (qDigits.length > 2 && c.phone.includes(qDigits)))
      .sort((a, b) => Number(b.online) - Number(a.online) || a.name.localeCompare(b.name, 'ru'));
  }, [contacts, query]);

  return (
    <ul className="chat-list">
      <li>
        <button className="list-action" onClick={() => openSheet({ type: 'add-contact' })}>
          <span className="list-action__icon">
            <UserPlusIcon width={22} height={22} />
          </span>
          Добавить друга по номеру
        </button>
      </li>
      <li>
        <button className="list-action" onClick={() => openSheet({ type: 'import-contacts' })}>
          <span className="list-action__icon">
            <ShareIcon width={22} height={22} style={{ transform: 'rotate(180deg)' }} />
          </span>
          Найти друзей из контактов телефона
        </button>
      </li>
      <li>
        <button className="list-action" onClick={() => openSheet({ type: 'new-group' })}>
          <span className="list-action__icon">
            <UsersIcon width={22} height={22} />
          </span>
          Создать группу
        </button>
      </li>
      {list.map((c, i) => (
        <ContactRow key={c.id} contact={c} index={i} showPresence={online} onOpen={() => openChat(openDirectChat(c.id))} />
      ))}
      {list.length === 0 && <li className="chat-list__empty">Никого не найдено</li>}
    </ul>
  );
}

function ContactRow({ contact, index, showPresence, onOpen }: { contact: Contact; index: number; showPresence: boolean; onOpen: () => void }) {
  const { openChat } = useUi();
  const call = (kind: 'audio' | 'video') => {
    openChat(openDirectChat(contact.id));
    startCall(contact.id, kind);
  };
  return (
    <li style={{ '--i': Math.min(index + 2, 12) } as React.CSSProperties} className="contact-row">
      <button className="chat-item" onClick={onOpen}>
        <ContactAvatar contact={contact} size={48} showStatus={showPresence} />
        <div className="chat-item__body">
          <div className="chat-item__name">{contact.name}</div>
          <div className={`chat-item__preview ${contact.online && showPresence ? 'is-online' : ''}`}>
            {contact.online && showPresence ? 'в сети' : formatLastSeen(contact)} · {formatPhone(contact.phone)}
          </div>
        </div>
      </button>
      <div className="contact-row__calls">
        <button className="icon-btn icon-btn--accent" onClick={() => call('audio')} aria-label={`Позвонить: ${contact.name}`} title="Аудиозвонок">
          <PhoneIcon width={20} height={20} />
        </button>
        <button className="icon-btn icon-btn--accent" onClick={() => call('video')} aria-label={`Видеозвонок: ${contact.name}`} title="Видеозвонок">
          <VideoIcon width={20} height={20} />
        </button>
      </div>
    </li>
  );
}

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
  const { openSheet } = useUi();
  const [open, setOpen] = useState(false);
  const simulatedOffline = useAppState((s) => s.connection.simulatedOffline);
  const showDemo = useAppState((s) => s.showDemo);
  const account = useAppState((s) => s.account);
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
        <button
          className="menu__item"
          role="menuitem"
          onClick={() => {
            setOpen(false);
            openSheet({ type: 'profile' });
          }}
        >
          <PhoneIcon width={20} height={20} />
          <span className="menu__label">
            Мой номер
            <small>{account ? formatPhone(account.phone) : 'Подключиться к серверу'}</small>
          </span>
        </button>
        <button
          className="menu__item"
          role="menuitem"
          onClick={() => {
            setOpen(false);
            openSheet({ type: 'import-contacts' });
          }}
        >
          <UsersIcon width={20} height={20} />
          <span className="menu__label">
            Контакты телефона
            <small>Найти друзей, которые уже в «Связи»</small>
          </span>
        </button>
        <label className="menu__item">
          <EditIcon width={20} height={20} />
          <span className="menu__label">
            Демо-контакты
            <small>Анна, Максим, группы — для примера</small>
          </span>
          <input type="checkbox" className="switch" checked={showDemo} onChange={(e) => setShowDemo(e.target.checked)} />
        </label>
        <label className="menu__item">
          <WifiOffIcon width={20} height={20} />
          <span className="menu__label">
            Режим полёта
            <small>Проверить офлайн без отключения сети</small>
          </span>
          <input type="checkbox" className="switch" checked={simulatedOffline} onChange={(e) => setSimulatedOffline(e.target.checked)} />
        </label>
        {showDemo && <button
          className="menu__item"
          role="menuitem"
          onClick={() => {
            setOpen(false);
            demoIncomingCall();
          }}
        >
          <PhoneIcon width={20} height={20} />
          <span className="menu__label">
            Демо: входящий звонок
            <small>Кто-то из демо-контактов позвонит вам</small>
          </span>
        </button>}
        <button
          className="menu__item"
          role="menuitem"
          onClick={() => {
            setOpen(false);
            if (confirm('Вернуть демо-переписку к исходной? Настоящие чаты и контакты не пострадают.')) resetDemo();
          }}
        >
          <RefreshIcon width={20} height={20} />
          <span className="menu__label">
            Сбросить демо-данные
            <small>Настоящие чаты и контакты останутся</small>
          </span>
        </button>
      </div>
    </div>
  );
}
