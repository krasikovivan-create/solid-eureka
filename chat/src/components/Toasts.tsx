import { dismissToast, getContact, useAppState } from '../store';
import { Avatar } from './Avatar';

export function Toasts({ onOpenChat }: { onOpenChat: (chatId: string) => void }) {
  const toasts = useAppState((s) => s.toasts);
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => {
        const contact = t.chatId ? getContact(t.chatId) : undefined;
        return (
          <button
            key={t.id}
            className={`toast toast--${t.kind}`}
            onClick={() => {
              dismissToast(t.id);
              if (t.chatId) onOpenChat(t.chatId);
            }}
          >
            {contact && <Avatar contact={contact} size={32} showStatus={false} />}
            <span className="toast__text">{t.text}</span>
          </button>
        );
      })}
    </div>
  );
}
