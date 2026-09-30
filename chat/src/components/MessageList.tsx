import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { MediaRef, Message } from '../types';
import { formatDay, isSameDay } from '../utils';
import { MessageBubble } from './MessageBubble';
import { ArrowDownIcon } from './icons';

interface Props {
  messages: Message[];
  typing: boolean;
  onOpenImage: (media: MediaRef) => void;
}

const GROUP_GAP = 5 * 60_000;
const NEAR_BOTTOM = 120;

export function MessageList({ messages, typing, onOpenImage }: Props) {
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
            const first = newDay || prev.author !== m.author || m.createdAt - prev.createdAt > GROUP_GAP || m.id === firstUnreadId;
            const last = !next || next.author !== m.author || next.createdAt - m.createdAt > GROUP_GAP || !isSameDay(next.createdAt, m.createdAt) || next.id === firstUnreadId;
            return (
              <Fragment key={m.id}>
                {newDay && (
                  <div className="day-divider">
                    <span>{formatDay(m.createdAt)}</span>
                  </div>
                )}
                {m.id === firstUnreadId && <div className="unread-divider">Новые сообщения</div>}
                <MessageBubble message={m} first={first} last={last} animate={!initialIds.has(m.id)} onOpenImage={onOpenImage} />
              </Fragment>
            );
          })}
          <div className={`typing-row ${typing ? 'is-visible' : ''}`} aria-live="polite">
            {typing && (
              <div className="typing-bubble" aria-label="печатает">
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
