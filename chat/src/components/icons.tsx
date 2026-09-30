// Inline SVG icons (no icon library needed).
import type { SVGProps } from 'react';

type P = SVGProps<SVGSVGElement>;

const base = (props: P) => ({
  width: 24,
  height: 24,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
  ...props,
});

export const PaperclipIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M21.4 11.1 12.2 20.3a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" />
  </svg>
);

export const SendIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 12 20 4l-4 16-4-7-8-1Z" fill="currentColor" stroke="none" />
    <path d="m12 13 8-9" stroke="#fff" strokeWidth={1.6} />
  </svg>
);

export const BackIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="m15 18-6-6 6-6" />
  </svg>
);

export const SearchIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);

export const MoreIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="12" cy="5" r="1.6" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
    <circle cx="12" cy="19" r="1.6" fill="currentColor" stroke="none" />
  </svg>
);

export const CloseIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);

export const ArrowDownIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 5v14M5 12l7 7 7-7" />
  </svg>
);

export const DownloadIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
  </svg>
);

export const WifiOffIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M2 2l20 20M8.5 16.5a5 5 0 0 1 7 0M5 12.9a10 10 0 0 1 5.2-2.8M19 12.9a10 10 0 0 0-2-1.6M2 8.8a15 15 0 0 1 4.2-2.6M22 8.8A15 15 0 0 0 11 4.9" />
    <circle cx="12" cy="20" r="0.8" fill="currentColor" />
  </svg>
);

export const ImageIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="3" y="3" width="18" height="18" rx="3" />
    <circle cx="9" cy="9" r="2" />
    <path d="m21 15-5-5L5 21" />
  </svg>
);

export const VideoIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="2" y="6" width="14" height="12" rx="2" />
    <path d="m16 10 6-3v10l-6-3" />
  </svg>
);

export const PlayIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M8 5.5v13l11-6.5-11-6.5Z" fill="currentColor" />
  </svg>
);

export const RefreshIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5" />
  </svg>
);

export const ChatIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" />
  </svg>
);

/** Message status: clock (pending), one tick (sent), two ticks (delivered), two blue ticks (read). */
export function StatusIcon({ status }: { status: 'pending' | 'sent' | 'delivered' | 'read' }) {
  if (status === 'pending') {
    return (
      <svg className="status-icon status-icon--pending" viewBox="0 0 16 16" width="15" height="15" aria-label="Ожидает отправки">
        <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 4.8V8l2.2 1.4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="status-icon__hand" />
      </svg>
    );
  }
  const label = status === 'sent' ? 'Отправлено' : status === 'delivered' ? 'Доставлено' : 'Прочитано';
  return (
    <svg className={`status-icon status-icon--${status}`} viewBox="0 0 20 16" width="18" height="15" aria-label={label}>
      <path className="tick tick--1" d="M1.5 8.5 5 12l7.5-8" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      {status !== 'sent' && (
        <path className="tick tick--2" d="M9 11.5l.5.5L17 4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      )}
    </svg>
  );
}

export const PhoneIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M5 4h3.5l1.7 4.3-2.2 1.4a11 11 0 0 0 6.3 6.3l1.4-2.2L20 15.5V19a1.5 1.5 0 0 1-1.6 1.5A16.5 16.5 0 0 1 3.5 5.6 1.5 1.5 0 0 1 5 4Z" />
  </svg>
);

export const HangUpIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M3.3 14.6c-.6-.6-.6-1.6.1-2.2a13 13 0 0 1 17.2 0c.7.6.7 1.6.1 2.2l-1.6 1.6a1.2 1.2 0 0 1-1.6.1l-2.3-1.8a1.2 1.2 0 0 1-.4-1.2l.4-1.7a10 10 0 0 0-6.4 0l.4 1.7c.1.4 0 .9-.4 1.2l-2.3 1.8a1.2 1.2 0 0 1-1.6-.1l-1.6-1.6Z" fill="currentColor" stroke="none" />
  </svg>
);

export const MicIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </svg>
);

export const MicOffIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M3 3l18 18M9 9v2a3 3 0 0 0 5.1 2.1M15 10V6a3 3 0 0 0-5.7-1.3M5 11a7 7 0 0 0 11.5 5.4M19 11a7 7 0 0 1-.6 2.8M12 18v3" />
  </svg>
);

export const CameraOffIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M3 3l18 18M16 16H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2M10 6h4a2 2 0 0 1 2 2v3l6-3v10" />
  </svg>
);

export const SwitchCameraIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 8a2 2 0 0 1 2-2h2l1.5-2h5L16 6h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z" />
    <path d="M9 12.5a3 3 0 0 1 5.2-2l.8.8M15 13a3 3 0 0 1-5.2 1.5l-.8-.8M15 9.5v2h-2M9 16v-2h2" />
  </svg>
);

export const MinimizeIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" />
  </svg>
);

export const EditIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
  </svg>
);

export const UserPlusIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="9" cy="8" r="4" />
    <path d="M2 21a7 7 0 0 1 14 0M19 8v6M16 11h6" />
  </svg>
);

export const UsersIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="9" cy="8" r="4" />
    <path d="M2 21a7 7 0 0 1 14 0M16 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-4-6.3" />
  </svg>
);

export const InfoIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5M12 8h.01" />
  </svg>
);

export const CheckIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="m5 12 5 5L20 7" />
  </svg>
);

export const ShareIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M12 3v12M7 8l5-5 5 5M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" />
  </svg>
);

/** Arrow for the call log: ↗ outgoing, ↙ incoming. */
export const CallArrowIcon = ({ incoming, ...p }: P & { incoming: boolean }) => (
  <svg {...base(p)}>
    {incoming ? <path d="M17 7 7 17M7 9v8h8" /> : <path d="M7 17 17 7M9 7h8v8" />}
  </svg>
);

/** Video note ("кружок") mode of the record button. */
export const RoundVideoIcon = (p: P) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M10 9.3v5.4l4.5-2.7L10 9.3Z" fill="currentColor" />
  </svg>
);

export const TrashIcon = (p: P) => (
  <svg {...base(p)}>
    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" />
  </svg>
);

export const LockIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </svg>
);

export const PauseIcon = (p: P) => (
  <svg {...base(p)}>
    <rect x="7" y="5" width="3.5" height="14" rx="1" fill="currentColor" stroke="none" />
    <rect x="13.5" y="5" width="3.5" height="14" rx="1" fill="currentColor" stroke="none" />
  </svg>
);
