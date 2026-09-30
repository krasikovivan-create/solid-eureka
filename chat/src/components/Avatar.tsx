import type { Contact } from '../types';
import { initials } from '../utils';

interface Props {
  contact: Contact;
  size?: number;
  showStatus?: boolean;
}

export function Avatar({ contact, size = 48, showStatus = true }: Props) {
  const [from, to] = contact.colors;
  return (
    <div className="avatar" style={{ width: size, height: size, fontSize: size * 0.38 }}>
      <div className="avatar__img" style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}>
        {initials(contact.name)}
      </div>
      {showStatus && <span className={`avatar__dot ${contact.online ? 'is-online' : ''}`} aria-label={contact.online ? 'в сети' : 'не в сети'} />}
    </div>
  );
}
