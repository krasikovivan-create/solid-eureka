// Side panel with details: the contact's profile, or the group's members.
import { useEffect } from 'react';
import type { Chat } from '../types';
import { isOnline, useAppState } from '../store';
import { startCall } from '../calls';
import { openDirectChat } from '../sync';
import { useUi } from '../ui';
import { chatLook, formatLastSeen, formatPhone, plural } from '../utils';
import { ChatAvatar, ContactAvatar } from './Avatar';
import { CloseIcon, PhoneIcon, UserPlusIcon, VideoIcon } from './icons';

interface Props {
  chat: Chat;
  open: boolean;
  onClose: () => void;
}

export function ChatInfo({ chat, open, onClose }: Props) {
  const { openChat, openSheet } = useUi();
  const contacts = useAppState((s) => s.contacts);
  const online = useAppState(isOnline);
  const look = chatLook(chat, contacts);
  const members = chat.memberIds.map((id) => contacts.find((c) => c.id === id)).filter((c) => !!c);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const call = (kind: 'audio' | 'video') => {
    onClose();
    startCall(chat.id, kind);
  };

  const contact = look.contact;
  const sub =
    chat.kind === 'group'
      ? `${members.length + 1} ${plural(members.length + 1, 'участник', 'участника', 'участников')}`
      : contact && online && contact.online
        ? 'в сети'
        : contact
          ? formatLastSeen(contact)
          : '';

  return (
    <>
      <div className={`info-backdrop ${open ? 'is-open' : ''}`} onClick={onClose} />
      <aside className={`info-panel ${open ? 'is-open' : ''}`} aria-hidden={!open} aria-label="Информация">
        <header className="info-panel__header">
          <h2>{chat.kind === 'group' ? 'Группа' : 'Профиль'}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть">
            <CloseIcon />
          </button>
        </header>
        <div className="info-panel__body">
          <div className="profile">
            <ChatAvatar chat={chat} size={96} showStatus={false} />
            <div className="profile__name">{look.name}</div>
            <div className="profile__sub">{sub}</div>
            <div className="profile__actions">
              <button className="round-action" onClick={() => call('audio')}>
                <span>
                  <PhoneIcon width={22} height={22} />
                </span>
                Звонок
              </button>
              <button className="round-action" onClick={() => call('video')}>
                <span>
                  <VideoIcon width={22} height={22} />
                </span>
                Видео
              </button>
              {chat.kind === 'group' && (
                <button className="round-action" onClick={() => openSheet({ type: 'add-members', chatId: chat.id })}>
                  <span>
                    <UserPlusIcon width={22} height={22} />
                  </span>
                  Добавить
                </button>
              )}
            </div>
          </div>

          {chat.kind === 'direct' && contact && (
            <dl className="details">
              <div>
                <dt>Телефон</dt>
                <dd>{formatPhone(contact.phone)}</dd>
              </div>
              <div>
                <dt>О себе</dt>
                <dd>{contact.about || '—'}</dd>
              </div>
            </dl>
          )}

          {chat.kind === 'group' && (
            <>
              <div className="section-title">Участники</div>
              <ul className="members">
                <li className="members__item">
                  <div className="avatar avatar--me" style={{ width: 40, height: 40 }}>
                    <div className="avatar__img">Я</div>
                  </div>
                  <div className="members__text">
                    <span className="members__name">Вы</span>
                    <span className="members__sub">в сети</span>
                  </div>
                </li>
                {members.map((m) => (
                  <li key={m.id}>
                    <button
                      className="members__item"
                      onClick={() => {
                        onClose();
                        openChat(openDirectChat(m.id));
                      }}
                    >
                      <ContactAvatar contact={m} size={40} showStatus={online} />
                      <span className="members__text">
                        <span className="members__name">{m.name}</span>
                        <span className={`members__sub ${online && m.online ? 'is-online' : ''}`}>{online && m.online ? 'в сети' : formatLastSeen(m)}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
