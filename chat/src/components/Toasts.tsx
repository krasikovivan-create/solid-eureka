import { dismissToast, getChat, getContact, useAppState } from '../store';
import { ChatAvatar, ContactAvatar } from './Avatar';

export function Toasts({ onOpenChat }: { onOpenChat: (chatId: string) => void }) {
  const toasts = useAppState((s) => s.toasts);
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => {
        const contact = t.contactId ? getContact(t.contactId) : undefined;
        const chat = !contact && t.chatId ? getChat(t.chatId) : undefined;
        return (
          <button
            key={t.id}
            className={`toast toast--${t.kind}`}
            onClick={() => {
              dismissToast(t.id);
              if (t.chatId) onOpenChat(t.chatId);
            }}
          >
            {contact && <ContactAvatar contact={contact} size={32} showStatus={false} />}
            {chat && <ChatAvatar chat={chat} size={32} showStatus={false} />}
            <span className="toast__text">{t.text}</span>
          </button>
        );
      })}
    </div>
  );
}
