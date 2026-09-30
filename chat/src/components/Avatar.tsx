import type { Chat, Contact } from '../types';
import { chatLook, initials } from '../utils';
import { useAppState } from '../store';
import { UsersIcon } from './icons';

interface Props {
  name: string;
  colors: [string, string];
  size?: number;
  /** Green dot; undefined = no dot at all. */
  online?: boolean;
  group?: boolean;
}

export function Avatar({ name, colors, size = 48, online, group }: Props) {
  const [from, to] = colors;
  return (
    <div className="avatar" style={{ width: size, height: size, fontSize: size * 0.38 }}>
      <div className="avatar__img" style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}>
        {group && size >= 40 ? <UsersIcon width={size * 0.46} height={size * 0.46} /> : initials(name)}
      </div>
      {online !== undefined && <span className={`avatar__dot ${online ? 'is-online' : ''}`} aria-label={online ? 'в сети' : 'не в сети'} />}
    </div>
  );
}

export function ContactAvatar({ contact, size, showStatus = true }: { contact: Contact; size?: number; showStatus?: boolean }) {
  return <Avatar name={contact.name} colors={contact.colors} size={size} online={showStatus ? contact.online : undefined} />;
}

/** Avatar of a chat: the contact's for a direct chat, the group's otherwise. */
export function ChatAvatar({ chat, size, showStatus = true }: { chat: Chat; size?: number; showStatus?: boolean }) {
  const contacts = useAppState((s) => s.contacts);
  const look = chatLook(chat, contacts);
  const online = chat.kind === 'direct' && showStatus ? !!look.contact?.online : undefined;
  return <Avatar name={look.name} colors={look.colors} size={size} online={online} group={chat.kind === 'group'} />;
}
