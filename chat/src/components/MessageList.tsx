import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { Chat, MediaRef, Message } from '../types';
import { useAppState } from '../store';
import { formatDay, isSameDay } from '../utils';
import { MessageBubble } from './MessageBubble';
import { ArrowDownIcon } from './icons';

interface Props {
  chat: Chat;
  messages: Message[];
  /** Contact who is typing right now. */
  typer?: string;
  onOpenImage: (media: MediaRef) => void;
}

const GROUP_GAP = 5 * 60_000;
const NEAR_BOTTOM = 120;

/** Same person, same side, close in time → one visual group of bubbles. */
const sameGroup = (a: Message, b: Message) =>
  a.author === b.author && a.author !== 'system' && !a.call && !b.call && (a.author === 'me' || a.senderId === b.senderId) && Math.abs(b.createdAt - a.createdAt) <= GROUP_GAP;

export function MessageList({ chat, messages, typer, onOpenImage }: Props) {
  const contacts = useAppState((s) => s.contacts);
  const typing = !!typer;
  const inGroup = chat.kind === 'group';
  const typerContact = typer ? contacts.find((c) => c.id === typer) : undefined;
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const [unseen, setUnseen] = useState(0);
  // "New messages" divider: remembered when the chat opens, so it stays put while reading.
  const [firstUnreadId] = useState(() => messages.find((m) => m.author === 'them' && m.status !== 'read')?.id);
  const prevCount = useRef(messages.length);
  // Only messages that appear while the chat is open get the "pop in" animation.
  const [initialIds] = useState(() => new Set(messages.map((m) => m.id)));

  const scrollToBottom = useCallback((smooth: boolean) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    setUnseen(0);
  }, []);

  // On open: jump to the first unread message, or to the bottom.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const divider = firstUnreadId && el.querySelector<HTMLElement>('.unread-divider');
    if (divider) el.scrollTop = divider.offsetTop - 12;
    else el.scrollTop = el.scrollHeight;
  }, []);

  // New messages: follow them if the user is at the bottom or wrote the message themselves.
  useLayoutEffect(() => {
    const added = messages.length - prevCount.current;
    prevCount.current = messages.length;
    if (added <= 0) return;
    const last = messages[messages.length - 1];
    if (last.author === 'me' || nearBottom.current) scrollToBottom(true);
    else setUnseen((n) => n + added);
  }, [messages, scrollToBottom]);

  useLayoutEffect(() => {
    if (typing && nearBottom.current) scrollToBottom(true);
  }, [typing, scrollToBottom]);

  // Keep the bottom pinned when the list resizes (mobile keyboard, composer growing).
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      if (nearBottom.current) el.scrollTop = el.scrollHeight;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onScroll = () => {
    const el = scrollRef.current!;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    nearBottom.current = distance < NEAR_BOTTOM;
    setShowJump(distance > 300);
    if (nearBottom.current) setUnseen(0);
  };

  return (
    <div className="messages-wrap">
      <div className="messages" ref={scrollRef} onScroll={onScroll}>
        <div className="messages__inner">
          {messages.length === 0 && <div className="messages__empty">Сообщений пока нет. Напишите первым 👋</div>}
          {messages.map((m, i) => {
            const prev = messages[i - 1];
            const next = messages[i + 1];
            const newDay = !prev || !isSameDay(prev.createdAt, m.createdAt);
            const first = newDay || !sameGroup(prev, m) || m.id === firstUnreadId;
            const last = !next || !sameGroup(m, next) || !isSameDay(next.createdAt, m.createdAt) || next.id === firstUnreadId;
            const sender = m.author === 'them' && m.senderId ? contacts.find((c) => c.id === m.senderId) : undefined;
            return (
              <Fragment key={m.id}>
                {newDay && (
                  <div className="day-divider">
                    <span>{formatDay(m.createdAt)}</span>
                  </div>
                )}
                {m.id === firstUnreadId && <div className="unread-divider">Новые сообщения</div>}
                <MessageBubble message={m} first={first} last={last} animate={!initialIds.has(m.id)} sender={sender} inGroup={inGroup} onOpenImage={onOpenImage} />
              </Fragment>
            );
          })}
          <div className={`typing-row ${typing ? 'is-visible' : ''}`} aria-live="polite">
            {typing && (
              <div className="typing-bubble" aria-label={`${typerContact?.name ?? ''} печатает`}>
                {inGroup && typerContact && <em className="typing-bubble__name">{typerContact.name.split(' ')[0]}</em>}
                <span />
                <span />
                <span />
              </div>
            )}
          </div>
        </div>
      </div>
      <button className={`jump-down ${showJump || unseen ? 'is-visible' : ''}`} onClick={() => scrollToBottom(true)} aria-label="Вниз к новым сообщениям">
        <ArrowDownIcon />
        {unseen > 0 && <span className="jump-down__badge">{unseen}</span>}
      </button>
    </div>
  );
}
