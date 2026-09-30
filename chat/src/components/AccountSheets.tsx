// "My number" (sign in to the real server) and "Import contacts" (phone book → friends on the server).
import { useMemo, useRef, useState } from 'react';
import { showToast, useAppState } from '../store';
import { addRealContact, signIn, signOut, updateMyName } from '../real';
import { findRegistered, openDirectChat } from '../sync';
import type { RemoteUser } from '../net/client';
import { contactPickerSupported, parseVCards, pickFromPhone, type PhoneBookEntry } from '../vcard';
import { formatPhone, formatPhoneInput, normalizePhone, plural } from '../utils';
import { useUi } from '../ui';
import { Avatar } from './Avatar';
import { Sheet } from './Sheets';
import { CheckIcon, ShareIcon, UsersIcon } from './icons';

const STATUS_TEXT: Record<string, string> = {
  off: 'Не подключено',
  connecting: 'Подключение…',
  online: 'Подключено',
  offline: 'Нет связи с сервером',
  error: 'Ошибка',
};

// ---- my number ---------------------------------------------------------------------------------

export function ProfileSheet({ onClose }: { onClose: () => void }) {
  const { openSheet } = useUi();
  const account = useAppState((s) => s.account);
  const net = useAppState((s) => s.net);
  const [phone, setPhone] = useState(account ? formatPhone(account.phone) : '+7 ');
  const [name, setName] = useState(account?.name ?? '');
  const [url, setUrl] = useState(net.url);
  const [showServer, setShowServer] = useState(!net.url);
  const digits = normalizePhone(phone);
  const changedNumber = !account || digits !== account.phone || url.trim() !== net.url;
  const canSubmit = !!digits && !!name.trim() && !!url.trim();

  const submit = () => {
    if (!canSubmit) return;
    if (changedNumber) signIn(digits!, name, url);
    else updateMyName(name);
    if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission().catch(() => {});
    showToast(changedNumber ? 'Подключаемся к серверу…' : 'Профиль сохранён', 'info');
  };

  return (
    <Sheet
      title="Мой номер"
      onClose={onClose}
      footer={
        <button className="btn btn--primary btn--wide" disabled={!canSubmit} onClick={submit}>
          {account ? (changedNumber ? 'Подключиться' : 'Сохранить') : 'Подключить номер'}
        </button>
      }
    >
      {account && (
        <div className={`account-card is-${net.status}`}>
          <div className="avatar avatar--me" style={{ width: 52, height: 52, fontSize: 20 }}>
            <div className="avatar__img">Я</div>
          </div>
          <div className="account-card__text">
            <span className="account-card__name">{account.name}</span>
            <span className="account-card__phone">{formatPhone(account.phone)}</span>
          </div>
          <span className="account-card__status">
            <span className="conn-pill__dot" />
            {STATUS_TEXT[net.status]}
          </span>
        </div>
      )}
      {net.error && <div className="notice notice--error">{net.error}</div>}
      {account && net.status === 'connecting' && <div className="notice">Бесплатный сервер «засыпает» без дела — первое подключение может занять до минуты.</div>}
      {!account && (
        <p className="sheet-lead">
          Подключите свой номер, чтобы переписываться и созваниваться с настоящими людьми. Друзья найдут вас по номеру, а вы их — по номеру или из контактов телефона.
        </p>
      )}

      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className="field">
          <span className="field__label">Ваш номер телефона</span>
          <input className="field__input field__input--phone" type="tel" inputMode="tel" autoComplete="tel" value={phone} onChange={(e) => setPhone(formatPhoneInput(e.target.value))} />
        </label>
        <label className="field">
          <span className="field__label">Имя — его увидят друзья</span>
          <input className="field__input" value={name} maxLength={60} autoComplete="name" placeholder="Например, Иван" onChange={(e) => setName(e.target.value)} />
        </label>
        {showServer ? (
          <label className="field">
            <span className="field__label">Адрес сервера</span>
            <input className="field__input" value={url} inputMode="url" placeholder="https://svyaz-server.onrender.com" onChange={(e) => setUrl(e.target.value)} />
            <span className="hint">Сервер из папки chat/server — как его запустить, написано в README.</span>
          </label>
        ) : (
          <button type="button" className="link-btn" onClick={() => setShowServer(true)}>
            Сервер: {net.url.replace(/^https?:\/\//, '')} · изменить
          </button>
        )}
        <button type="submit" hidden />
      </form>

      <p className="hint">Номер не проверяется по SMS: он закрепляется за этим устройством, и с другого устройства его занять нельзя.</p>

      {account && (
        <div className="profile-actions">
          <button className="btn" onClick={() => openSheet({ type: 'import-contacts' })}>
            <UsersIcon width={18} height={18} /> Найти друзей из контактов
          </button>
          <button
            className="btn btn--ghost-danger"
            onClick={() => {
              signOut();
              onClose();
              showToast('Вы вышли. Переписка осталась на устройстве.', 'info');
            }}
          >
            Выйти
          </button>
        </div>
      )}
    </Sheet>
  );
}

// ---- import contacts ------------------------------------------------------------------------------

interface Match {
  user: RemoteUser;
  bookName: string;
}

export function ImportContactsSheet({ onClose }: { onClose: () => void }) {
  const { openSheet, openChat } = useUi();
  const account = useAppState((s) => s.account);
  const netStatus = useAppState((s) => s.net.status);
  const contacts = useAppState((s) => s.contacts);
  const fileRef = useRef<HTMLInputElement>(null);
  const [entries, setEntries] = useState<PhoneBookEntry[] | null>(null);
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const known = useMemo(() => new Set(contacts.filter((c) => c.real).map((c) => c.phone)), [contacts]);

  const check = async (list: PhoneBookEntry[]) => {
    setEntries(list);
    setError('');
    if (!list.length) return setError('В файле не нашлось ни одного номера телефона.');
    setBusy(true);
    try {
      const byPhone = new Map<string, string>();
      list.forEach((e) => e.phones.forEach((p) => byPhone.set(p, e.name)));
      const users = await findRegistered([...byPhone.keys()]);
      const found = users.map((user) => ({ user, bookName: byPhone.get(user.phone) ?? user.name }));
      setMatches(found);
      setSelected(found.filter((m) => !known.has(m.user.phone)).map((m) => m.user.phone));
    } catch {
      setError('Сервер не ответил. Проверьте подключение и попробуйте ещё раз.');
    } finally {
      setBusy(false);
    }
  };

  const fromPhone = async () => {
    try {
      check(await pickFromPhone());
    } catch {
      /* the user closed the picker */
    }
  };

  const fromFile = async (file: File) => {
    try {
      check(parseVCards(await file.text()));
    } catch {
      setError('Не удалось прочитать файл. Нужен файл контактов в формате .vcf.');
    }
  };

  const add = () => {
    const chosen = matches?.filter((m) => selected.includes(m.user.phone)) ?? [];
    chosen.forEach((m) => addRealContact(m.user, m.bookName));
    showToast(`Добавлено ${chosen.length} ${plural(chosen.length, 'контакт', 'контакта', 'контактов')}`, 'success');
    onClose();
    if (chosen.length === 1) openChat(openDirectChat(addRealContact(chosen[0].user, chosen[0].bookName).id));
  };

  const invite = async () => {
    const text = `Привет! Я пользуюсь «Связью» — мессенджером, который работает даже без интернета. Присоединяйся: ${location.origin}${location.pathname}`;
    try {
      if (navigator.share) await navigator.share({ title: 'Связь', text });
      else {
        await navigator.clipboard.writeText(text);
        showToast('Приглашение скопировано', 'success');
      }
    } catch {
      /* closed */
    }
  };

  if (!account) {
    return (
      <Sheet title="Контакты телефона" onClose={onClose}>
        <p className="sheet-lead">Чтобы найти друзей из контактов, сначала подключите свой номер — поиск идёт по серверу.</p>
        <button className="btn btn--primary btn--wide" onClick={() => openSheet({ type: 'profile' })}>
          Подключить номер
        </button>
      </Sheet>
    );
  }

  const registered = new Set(matches?.map((m) => m.user.phone));
  const notOnApp = entries ? entries.filter((e) => !e.phones.some((p) => registered.has(p))).length : 0;

  return (
    <Sheet
      title="Контакты телефона"
      onClose={onClose}
      footer={
        matches?.length ? (
          <button className="btn btn--primary btn--wide" disabled={!selected.length} onClick={add}>
            Добавить {selected.length ? `· ${selected.length}` : ''}
          </button>
        ) : undefined
      }
    >
      {!matches && (
        <>
          <p className="sheet-lead">Узнайте, кто из ваших контактов уже пользуется «Связью». Номера сверяются с сервером и нигде не сохраняются.</p>
          <div className="stack">
            {contactPickerSupported() && (
              <button className="btn btn--primary btn--wide" disabled={busy || netStatus !== 'online'} onClick={fromPhone}>
                <UsersIcon width={18} height={18} /> Выбрать из контактов телефона
              </button>
            )}
            <button className={`btn btn--wide ${contactPickerSupported() ? '' : 'btn--primary'}`} disabled={busy || netStatus !== 'online'} onClick={() => fileRef.current?.click()}>
              Загрузить файл контактов (.vcf)
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".vcf,text/vcard,text/x-vcard"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) fromFile(f);
                e.target.value = '';
              }}
            />
          </div>
          {netStatus !== 'online' && <div className="notice">Нет связи с сервером — поиск заработает, как только подключение восстановится.</div>}
          {busy && (
            <div className="notice">
              <span className="spinner spinner--accent" /> Проверяем {entries?.length ?? ''} контактов…
            </div>
          )}
          {error && <div className="notice notice--error">{error}</div>}
          <details className="howto">
            <summary>Как получить файл контактов</summary>
            <p>
              <b>iPhone:</b> приложение «Контакты» → «Списки» → удерживайте «Все контакты» → «Экспортировать» → сохраните файл .vcf и выберите его здесь.
            </p>
            <p>
              <b>Android:</b> «Контакты» → меню → «Управление контактами» / «Экспорт» → «Экспорт в файл .vcf». Или откройте contacts.google.com → «Экспортировать» → vCard.
            </p>
          </details>
        </>
      )}

      {matches && (
        <>
          <div className="section-title">
            {matches.length ? `Уже в «Связи»: ${matches.length}` : 'Никого из контактов пока нет в «Связи»'}
          </div>
          <ul className="picker__list">
            {matches.map((m) => {
              const already = known.has(m.user.phone);
              const checked = selected.includes(m.user.phone);
              return (
                <li key={m.user.phone}>
                  <button
                    className={`picker__item ${checked ? 'is-checked' : ''}`}
                    disabled={already}
                    onClick={() => setSelected((s) => (s.includes(m.user.phone) ? s.filter((x) => x !== m.user.phone) : [...s, m.user.phone]))}
                  >
                    <Avatar name={m.bookName} colors={m.user.colors ?? ['#a1c4fd', '#c2e9fb']} size={44} online={m.user.online} />
                    <span className="picker__text">
                      <span className="picker__name">{m.bookName}</span>
                      <span className="picker__sub">
                        {formatPhone(m.user.phone)}
                        {m.user.name && m.user.name !== m.bookName ? ` · в «Связи»: ${m.user.name}` : ''}
                        {already ? ' · уже в контактах' : ''}
                      </span>
                    </span>
                    {!already && (
                      <span className={`checkbox ${checked ? 'is-checked' : ''}`} aria-hidden>
                        <CheckIcon width={14} height={14} />
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
          {notOnApp > 0 && (
            <div className="invite-row">
              <span>
                Ещё {notOnApp} {plural(notOnApp, 'контакт', 'контакта', 'контактов')} не в «Связи»
              </span>
              <button className="btn" onClick={invite}>
                <ShareIcon width={16} height={16} /> Пригласить
              </button>
            </div>
          )}
          <button
            className="link-btn"
            onClick={() => {
              setMatches(null);
              setEntries(null);
            }}
          >
            Проверить другой файл
          </button>
        </>
      )}
    </Sheet>
  );
}
