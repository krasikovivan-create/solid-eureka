// Reading phone-book exports (.vcf, vCard 2.1/3.0/4.0) from iPhone, Android and Google Contacts.
import { normalizePhone } from './utils';

export interface PhoneBookEntry {
  name: string;
  phones: string[];
}

export function parseVCards(text: string): PhoneBookEntry[] {
  const lines = unfold(text);
  const entries: PhoneBookEntry[] = [];
  let current: { fn?: string; n?: string; tels: string[] } | null = null;

  for (const line of lines) {
    const colon = line.indexOf(':');
    if (colon < 0) continue;
    const head = line.slice(0, colon);
    const rawValue = line.slice(colon + 1);
    const [nameWithGroup, ...params] = head.split(';');
    const prop = nameWithGroup.replace(/^.*\./, '').toUpperCase();
    const upperParams = params.map((p) => p.toUpperCase());
    const qp = upperParams.some((p) => p === 'ENCODING=QUOTED-PRINTABLE' || p === 'QUOTED-PRINTABLE');
    const value = qp ? decodeQuotedPrintable(rawValue) : rawValue;

    if (prop === 'BEGIN' && value.toUpperCase() === 'VCARD') current = { tels: [] };
    else if (prop === 'END' && value.toUpperCase() === 'VCARD') {
      if (current) {
        const name = (current.fn || current.n || '').trim();
        const phones = [...new Set(current.tels.map((t) => normalizePhone(t)).filter((p): p is string => !!p))];
        if (phones.length) entries.push({ name: name || '+' + phones[0], phones });
      }
      current = null;
    } else if (current) {
      if (prop === 'FN') current.fn = unescape(value);
      else if (prop === 'N') {
        // N:Family;Given;Middle;Prefix;Suffix
        const [family = '', given = '', middle = ''] = value.split(';').map(unescape);
        current.n = [given, middle, family].filter(Boolean).join(' ');
      } else if (prop === 'TEL') current.tels.push(value.replace(/^tel:/i, ''));
    }
  }
  return entries;
}

/** Continuation lines (starting with a space/tab) and quoted-printable soft breaks ("=" at the end). */
function unfold(text: string): string[] {
  const raw = text.replace(/\r\n?/g, '\n').split('\n');
  const out: string[] = [];
  for (const line of raw) {
    const prev = out[out.length - 1];
    if (prev !== undefined && (line.startsWith(' ') || line.startsWith('\t'))) out[out.length - 1] = prev + line.slice(1);
    else if (prev !== undefined && /QUOTED-PRINTABLE/i.test(prev.split(':')[0]) && prev.endsWith('=')) out[out.length - 1] = prev.slice(0, -1) + line;
    else out.push(line);
  }
  return out;
}

function decodeQuotedPrintable(s: string) {
  const bytes: number[] = [];
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '=' && /^[0-9A-Fa-f]{2}$/.test(s.slice(i + 1, i + 3))) {
      bytes.push(parseInt(s.slice(i + 1, i + 3), 16));
      i += 2;
    } else {
      bytes.push(s.charCodeAt(i) & 0xff);
    }
  }
  return new TextDecoder('utf-8').decode(new Uint8Array(bytes));
}

const unescape = (s: string) => s.replace(/\\n/gi, ' ').replace(/\\([,;\\])/g, '$1').trim();

/** Android Chrome: the system contact picker (Contact Picker API). */
export function contactPickerSupported() {
  return typeof navigator !== 'undefined' && 'contacts' in navigator && 'ContactsManager' in window;
}

interface PickerContact {
  name?: string[];
  tel?: string[];
}

export async function pickFromPhone(): Promise<PhoneBookEntry[]> {
  const contacts = (navigator as unknown as { contacts: { select: (props: string[], opts: { multiple: boolean }) => Promise<PickerContact[]> } }).contacts;
  const picked = await contacts.select(['name', 'tel'], { multiple: true });
  return picked
    .map((c) => {
      const phones = [...new Set((c.tel ?? []).map((t) => normalizePhone(t)).filter((p): p is string => !!p))];
      return { name: c.name?.[0]?.trim() || (phones[0] ? '+' + phones[0] : ''), phones };
    })
    .filter((e) => e.phones.length);
}
