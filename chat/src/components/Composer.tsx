import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { getState, setDraft } from '../store';
import { sendMedia, sendText } from '../sync';
import { notifyTyping } from '../real';
import { formatSize } from '../utils';
import { CloseIcon, PaperclipIcon, PlayIcon, SendIcon } from './icons';

export interface Attachment {
  key: string;
  file: File;
  url: string;
  kind: 'image' | 'video';
}

interface Props {
  chatId: string;
  attachments: Attachment[];
  onAddFiles: (files: FileList | File[]) => void;
  onRemove: (key: string) => void;
  onClear: () => void;
}

const enterSends = () => window.matchMedia('(pointer: fine)').matches;

export function Composer({ chatId, attachments, onAddFiles, onRemove, onClear }: Props) {
  const [text, setText] = useState(() => getState().drafts[chatId] ?? '');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef(text);
  textRef.current = text;

  // Drafts are saved (debounced) so a half-written message survives reloads.
  useEffect(() => {
    const t = setTimeout(() => setDraft(chatId, text), 400);
    return () => clearTimeout(t);
  }, [chatId, text]);
  useEffect(() => () => setDraft(chatId, textRef.current), [chatId]);

  // Auto-grow the textarea up to ~6 lines.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  useEffect(() => {
    if (enterSends()) inputRef.current?.focus();
  }, [chatId]);

  const canSend = text.trim().length > 0 || attachments.length > 0;

  const submit = () => {
    if (!canSend) return;
    if (attachments.length) {
      // The caption goes with the first file; files are sent in the order they were picked.
      const files = attachments.map((a) => a.file);
      const caption = text;
      files.reduce((p, file, i) => p.then(() => sendMedia(chatId, file, i === 0 ? caption : '')), Promise.resolve());
      onClear();
    } else {
      sendText(chatId, text);
    }
    setText('');
    setDraft(chatId, '');
    inputRef.current?.focus();
  };

  return (
    <div className="composer">
      {attachments.length > 0 && (
        <div className="attachments">
          {attachments.map((a) => (
            <div className="attachment" key={a.key}>
              {a.kind === 'image' ? <img src={a.url} alt="" /> : <video src={`${a.url}#t=0.1`} muted playsInline preload="metadata" />}
              {a.kind === 'video' && (
                <span className="attachment__play">
                  <PlayIcon />
                </span>
              )}
              <span className="attachment__size">{formatSize(a.file.size)}</span>
              <button className="attachment__remove" onClick={() => onRemove(a.key)} aria-label="Убрать файл">
                <CloseIcon />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="composer__row">
        <button className="icon-btn composer__attach" onClick={() => fileRef.current?.click()} aria-label="Прикрепить фото или видео" title="Прикрепить фото или видео">
          <PaperclipIcon />
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*,video/*"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) onAddFiles(e.target.files);
            e.target.value = '';
          }}
        />
        <textarea
          ref={inputRef}
          className="composer__input"
          rows={1}
          value={text}
          placeholder={attachments.length ? 'Добавить подпись…' : 'Сообщение'}
          onChange={(e) => {
            setText(e.target.value);
            if (e.target.value) notifyTyping(chatId);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && enterSends()) {
              e.preventDefault();
              submit();
            }
          }}
          onPaste={(e) => {
            const files = Array.from(e.clipboardData.files);
            if (files.length) {
              e.preventDefault();
              onAddFiles(files);
            }
          }}
        />
        <button className={`send-btn ${canSend ? 'is-active' : ''}`} onClick={submit} disabled={!canSend} aria-label="Отправить">
          <SendIcon />
        </button>
      </div>
    </div>
  );
}
