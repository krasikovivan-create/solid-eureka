// Dialogs: add a friend by phone number, new chat, new group, add members to a group.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { Contact } from '../types';
import { getChat, showToast, useAppState } from '../store';
import { addMembers, lookupPhone, newGroup, openDirectChat, saveContact, type LookupResult } from '../sync';
import { formatPhone, formatPhoneInput, normalizePhone, plural } from '../utils';
import { useUi, type SheetState } from '../ui';
import { ImportContactsSheet, ProfileSheet } from './AccountSheets';
import { Avatar, ContactAvatar } from './Avatar';
import { BackIcon, CheckIcon, CloseIcon, SearchIcon, ShareIcon, UserPlusIcon, UsersIcon, WifiOffIcon } from './icons';

export function Sheets({ sheet }: { sheet: SheetState }) {
  const { openSheet } = useUi();
  const close = () => openSheet(null);
  if (!sheet) return null;
  switch (sheet.type) {
    case 'add-contact':
      return <AddContactSheet onClose={close} />;
    case 'new-chat':
      return <NewChatSheet onClose={close} />;
    case 'new-group':
      return <NewGroupSheet onClose={close} />;
    case 'add-members':
      return <AddMembersSheet chatId={sheet.chatId} onClose={close} />;
    case 'profile':
      return <ProfileSheet onClose={close} />;
    case 'import-contacts':
      return <ImportContactsSheet onClose={close} />;
  }
}

// ---- the frame ------------------------------------------------------------------------------

interface SheetProps {
  title: string;
  onClose: () => void;
  onBack?: () => void;
  children: ReactNode;
  footer?: ReactNode;
}

/** Bottom sheet on phones, centered dialog on desktop. */
export function Sheet({ title, onClose, onBack, children, footer }: SheetProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <header className="sheet__header">
          {onBack ? (
            <button className="icon-btn" onClick={onBack} aria-label="Назад">
              <BackIcon />
            </button>
          ) : (
            <span className="sheet__spacer" />
          )}
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть">
            <CloseIcon />
          </button>
        </header>
        <div className="sheet__body">{children}</div>
        {footer && <footer className="sheet__footer">{footer}</footer>}
      </div>
    </div>
  );
}

// ---- add a friend by number ----------------------------------------------------------------

function AddContactSheet({ onClose }: { onClose: () => void }) {
  const { openChat, openSheet } = useUi();
  const account = useAppState((s) => s.account);
  const [phone, setPhone] = useState('+7 ');
  const [name, setName] = useState('');
  const [result, setResult] = useState<LookupResult | null>(null);
  const [loading, setLoading] = useState(false);
  const digits = normalizePhone(phone);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const search = async () => {
    if (!digits || loading) return;
    setLoading(true);
    setResult(null);
    const r = await lookupPhone(digits);
    setLoading(false);
    setResult(r);
    if (r.status === 'found') setName(r.profile.name);
  };

  const add = (andOpen: boolean) => {
    if (result?.status !== 'found') return;
    const contact = saveContact(result, name);
    showToast(`${contact.name} ${contact.gender === 'f' ? 'добавлена' : contact.gender === 'u' ? 'добавлен(а)' : 'добавлен'} в контакты`, 'success');
    onClose();
    if (andOpen) openChat(openDirectChat(contact.id));
  };

  const invite = async () => {
    const text = `Привет! Я пользуюсь «Связью» — мессенджером, который работает даже без интернета. Присоединяйся: ${location.origin}${location.pathname}`;
    try {
      if (navigator.share) await navigator.share({ title: 'Связь', text });
      else {
        await navigator.clipboard.writeText(text);
        showToast('Приглашение скопировано — отправьте его любым способом', 'success');
      }
    } catch {
      /* the user closed the share dialog */
    }
  };

  return (
    <Sheet title="Добавить друга" onClose={onClose}>
      <form
        className="phone-form"
        onSubmit={(e) => {
          e.preventDefault();
          search();
        }}
      >
        <label className="field">
          <span className="field__label">Номер телефона</span>
          <input
            ref={inputRef}
            className="field__input field__input--phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+7 999 123-45-67"
            value={phone}
            onChange={(e) => {
              setPhone(formatPhoneInput(e.target.value));
              setResult(null);
            }}
          />
        </label>
        <button className="btn btn--primary" type="submit" disabled={!digits || loading}>
          {loading ? <span className="spinner spinner--dark" /> : <SearchIcon width={18} height={18} />}
          Найти
        </button>
      </form>
      {account ? (
        <p className="hint">Ищем среди тех, кто зарегистрирован в «Связи».</p>
      ) : (
        <div className="notice">
          Сейчас это демо-поиск (попробуйте +7 916 123-45-67 или любой номер). Чтобы находить настоящих друзей,{' '}
          <button className="link-btn link-btn--inline" onClick={() => openSheet({ type: 'profile' })}>
            подключите свой номер
          </button>
          .
        </div>
      )}
      <button className="sheet-action" onClick={() => openSheet({ type: 'import-contacts' })}>
        <span className="sheet-action__icon">
          <UsersIcon width={20} height={20} />
        </span>
        Найти друзей из контактов телефона
      </button>

      {result?.status === 'found' && (
        <div className="found-card">
          <Avatar name={result.profile.name} colors={result.profile.colors} size={64} online={result.real ? result.user.online : undefined} />
          <div className="found-card__name">{result.profile.name}</div>
          <div className="found-card__sub">
            {formatPhone(result.profile.phone)} · {result.profile.about}
          </div>
          <label className="field field--full">
            <span className="field__label">Имя в ваших контактах</span>
            <input className="field__input" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} />
          </label>
          <div className="found-card__actions">
            <button className="btn" onClick={() => add(false)}>
              <UserPlusIcon width={18} height={18} /> Добавить
            </button>
            <button className="btn btn--primary" onClick={() => add(true)}>
              Добавить и написать
            </button>
          </div>
        </div>
      )}
      {result?.status === 'existing' && (
        <div className="found-card">
          <ContactAvatar contact={result.contact} size={64} />
          <div className="found-card__name">{result.contact.name}</div>
          <div className="found-card__sub">Уже в ваших контактах</div>
          <div className="found-card__actions">
            <button
              className="btn btn--primary"
              onClick={() => {
                onClose();
                openChat(openDirectChat(result.contact.id));
              }}
            >
              Написать
            </button>
          </div>
        </div>
      )}
      {result?.status === 'not-found' && digits && (
        <div className="found-card found-card--empty">
          <div className="found-card__name">{formatPhone(digits)}</div>
          <div className="found-card__sub">Этот номер пока не пользуется «Связью». Пригласите друга — как только он зарегистрируется, его можно будет добавить.</div>
          <div className="found-card__actions">
            <button className="btn btn--primary" onClick={invite}>
              <ShareIcon width={18} height={18} /> Пригласить
            </button>
          </div>
        </div>
      )}
      {result?.status === 'offline' && (
        <div className="found-card found-card--empty">
          <WifiOffIcon width={28} height={28} />
          <div className="found-card__sub">Нет подключения. Найти человека по номеру можно только онлайн.</div>
        </div>
      )}
      {result?.status === 'server-offline' && (
        <div className="found-card found-card--empty">
          <WifiOffIcon width={28} height={28} />
          <div className="found-card__sub">Нет связи с сервером «Связи». Попробуйте чуть позже — бесплатный сервер может просыпаться до минуты.</div>
        </div>
      )}
      {result?.status === 'error' && (
        <div className="found-card found-card--empty">
          <div className="found-card__sub">Не удалось выполнить поиск. Попробуйте ещё раз.</div>
        </div>
      )}
    </Sheet>
  );
}

// ---- pick contacts ------------------------------------------------------------------------------

interface PickerProps {
  exclude?: string[];
  selected?: string[];
  onToggle?: (id: string) => void;
  onPick?: (contact: Contact) => void;
}

/** Contact list with search; multi-select (checkboxes) or single tap. */
function ContactPicker({ exclude = [], selected, onToggle, onPick }: PickerProps) {
  const all = useAppState((s) => s.contacts);
  const showDemo = useAppState((s) => s.showDemo);
  const contacts = useMemo(() => (showDemo ? all : all.filter((c) => c.real)), [all, showDemo]);
  const [query, setQuery] = useState('');
  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    const qDigits = q.replace(/\D/g, '');
    return contacts
      .filter((c) => !exclude.includes(c.id))
      .filter((c) => !q || c.name.toLowerCase().includes(q) || (qDigits.length > 2 && c.phone.includes(qDigits)))
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'));
  }, [contacts, exclude, query]);

  return (
    <div className="picker">
      <label className="search search--sheet">
        <SearchIcon width={18} height={18} />
        <input type="search" placeholder="Имя или номер" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <ul className="picker__list">
        {list.map((c) => {
          const checked = selected?.includes(c.id);
          return (
            <li key={c.id}>
              <button className={`picker__item ${checked ? 'is-checked' : ''}`} onClick={() => (onToggle ? onToggle(c.id) : onPick?.(c))}>
                <ContactAvatar contact={c} size={44} />
                <span className="picker__text">
                  <span className="picker__name">{c.name}</span>
                  <span className="picker__sub">{formatPhone(c.phone)}</span>
                </span>
                {onToggle && (
                  <span className={`checkbox ${checked ? 'is-checked' : ''}`} aria-hidden>
                    <CheckIcon width={14} height={14} />
                  </span>
                )}
              </button>
            </li>
          );
        })}
        {list.length === 0 && <li className="picker__empty">Никого не найдено</li>}
      </ul>
    </div>
  );
}

function SelectedChips({ ids, onRemove }: { ids: string[]; onRemove: (id: string) => void }) {
  const contacts = useAppState((s) => s.contacts);
  if (!ids.length) return null;
  return (
    <div className="chips">
      {ids.map((id) => {
        const c = contacts.find((x) => x.id === id);
        if (!c) return null;
        return (
          <button key={id} className="chip" onClick={() => onRemove(id)} aria-label={`Убрать ${c.name}`}>
            <ContactAvatar contact={c} size={22} showStatus={false} />
            {c.name.split(' ')[0]}
            <CloseIcon width={14} height={14} />
          </button>
        );
      })}
    </div>
  );
}

// ---- new chat -----------------------------------------------------------------------------------

function NewChatSheet({ onClose }: { onClose: () => void }) {
  const { openChat, openSheet } = useUi();
  return (
    <Sheet title="Новый чат" onClose={onClose}>
      <div className="sheet-actions">
        <button className="sheet-action" onClick={() => openSheet({ type: 'new-group' })}>
          <span className="sheet-action__icon">
            <UsersIcon width={20} height={20} />
          </span>
          Новая группа
        </button>
        <button className="sheet-action" onClick={() => openSheet({ type: 'add-contact' })}>
          <span className="sheet-action__icon">
            <UserPlusIcon width={20} height={20} />
          </span>
          Добавить друга по номеру
        </button>
      </div>
      <ContactPicker
        onPick={(c) => {
          onClose();
          openChat(openDirectChat(c.id));
        }}
      />
    </Sheet>
  );
}

// ---- new group ----------------------------------------------------------------------------------

function NewGroupSheet({ onClose }: { onClose: () => void }) {
  const { openChat } = useUi();
  const [step, setStep] = useState<'members' | 'name'>('members');
  const [selected, setSelected] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const create = () => {
    if (!title.trim() || selected.length < 2) return;
    const id = newGroup(title, selected);
    onClose();
    openChat(id);
  };

  if (step === 'name') {
    return (
      <Sheet
        title="Новая группа"
        onClose={onClose}
        onBack={() => setStep('members')}
        footer={
          <button className="btn btn--primary btn--wide" disabled={!title.trim()} onClick={create}>
            Создать группу
          </button>
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            create();
          }}
        >
          <div className="group-preview">
            <Avatar name={title || 'Группа'} colors={['#667eea', '#764ba2']} size={64} group />
            <label className="field field--full">
              <span className="field__label">Название группы</span>
              <input className="field__input" autoFocus value={title} maxLength={50} placeholder="Например, «Семья» или «Поход в горы»" onChange={(e) => setTitle(e.target.value)} />
            </label>
          </div>
        </form>
        <div className="section-title">
          {selected.length} {plural(selected.length, 'участник', 'участника', 'участников')}
        </div>
        <SelectedChips ids={selected} onRemove={(id) => setSelected((s) => s.filter((x) => x !== id))} />
      </Sheet>
    );
  }

  return (
    <Sheet
      title="Участники группы"
      onClose={onClose}
      footer={
        <button className="btn btn--primary btn--wide" disabled={selected.length < 2} onClick={() => setStep('name')}>
          {selected.length < 2 ? 'Выберите минимум двоих' : `Далее · ${selected.length}`}
        </button>
      }
    >
      <SelectedChips ids={selected} onRemove={toggle} />
      <ContactPicker selected={selected} onToggle={toggle} />
    </Sheet>
  );
}

// ---- add members ---------------------------------------------------------------------------------

function AddMembersSheet({ chatId, onClose }: { chatId: string; onClose: () => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const existing = useMemo(() => getChat(chatId)?.memberIds ?? [], [chatId]);
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  return (
    <Sheet
      title="Добавить участников"
      onClose={onClose}
      footer={
        <button
          className="btn btn--primary btn--wide"
          disabled={!selected.length}
          onClick={() => {
            addMembers(chatId, selected);
            onClose();
          }}
        >
          Добавить{selected.length ? ` · ${selected.length}` : ''}
        </button>
      }
    >
      <SelectedChips ids={selected} onRemove={toggle} />
      <ContactPicker exclude={existing} selected={selected} onToggle={toggle} />
    </Sheet>
  );
}
