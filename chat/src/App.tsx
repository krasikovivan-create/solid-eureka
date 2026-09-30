import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAppState } from './store';
import { UiContext, type SheetState } from './ui';
import { Sheets } from './components/Sheets';
import { CallScreen } from './components/CallScreen';
import { Sidebar } from './components/Sidebar';
import { ChatView } from './components/ChatView';
import { Toasts } from './components/Toasts';
import { ChatIcon } from './components/icons';

// The open chat lives in the URL hash (#/chat/anna), so the phone's back
// button/gesture returns to the list and a reload keeps the chat open.
const readHash = () => /^#\/chat\/([\w-]+)/.exec(location.hash)?.[1] ?? null;

/** True when the open chat was pushed onto history from the list, so "back" can pop it. */
let pushedFromList = false;

export function App() {
  const [chatId, setChatId] = useState<string | null>(readHash);
  // Keep the last chat mounted while the mobile pane slides away.
  const [shownId, setShownId] = useState<string | null>(chatId);
  const known = useAppState((s) => s.chats.some((c) => c.id === shownId));
  const [sheet, setSheet] = useState<SheetState>(null);

  useEffect(() => {
    const onHash = () => {
      const id = readHash();
      if (!id) pushedFromList = false;
      setChatId(id);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    if (chatId) return setShownId(chatId);
    const t = setTimeout(() => setShownId(null), 350); // after the slide-out animation
    return () => clearTimeout(t);
  }, [chatId]);

  const openChat = useCallback((id: string) => {
    const hash = `#/chat/${id}`;
    if (location.hash === hash) return;
    // From the list: a new history entry. Chat → chat (desktop): replace, so "back" goes to the list.
    if (readHash()) history.replaceState(null, '', hash);
    else {
      history.pushState(null, '', hash);
      pushedFromList = true;
    }
    setChatId(id);
  }, []);

  const closeChat = useCallback(() => {
    if (pushedFromList) history.back();
    else {
      history.replaceState(null, '', location.pathname + location.search);
      setChatId(null);
    }
  }, []);

  const ui = useMemo(() => ({ openChat, openSheet: setSheet }), [openChat]);

  return (
    <UiContext.Provider value={ui}>
    <div className={`app ${chatId ? 'app--chat-open' : ''}`}>
      <Sidebar activeId={chatId} />
      <main className="pane">
        {shownId && known ? (
          <ChatView key={shownId} chatId={shownId} active={shownId === chatId} onBack={closeChat} />
        ) : (
          <div className="empty-state">
            <div className="empty-state__icon">
              <ChatIcon width={40} height={40} />
            </div>
            <h2>Выберите чат</h2>
            <p>Сообщения хранятся на устройстве — писать можно даже без интернета. Всё отправится, как только появится связь.</p>
            <div className="empty-state__actions">
              <button className="btn btn--primary" onClick={() => setSheet({ type: 'add-contact' })}>
                Добавить друга по номеру
              </button>
              <button className="btn" onClick={() => setSheet({ type: 'new-group' })}>
                Создать группу
              </button>
            </div>
          </div>
        )}
      </main>
      <Toasts onOpenChat={openChat} />
      <Sheets sheet={sheet} />
      <CallScreen />
    </div>
    </UiContext.Provider>
  );
}
