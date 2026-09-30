// Navigation actions shared by the components: open a chat, open a dialog.
import { createContext, useContext } from 'react';

export type SheetState =
  | { type: 'new-chat' }
  | { type: 'add-contact' }
  | { type: 'new-group' }
  | { type: 'add-members'; chatId: string }
  | { type: 'profile' }
  | { type: 'import-contacts' }
  | null;

export interface Ui {
  openChat: (chatId: string) => void;
  openSheet: (sheet: SheetState) => void;
}

export const UiContext = createContext<Ui>({ openChat: () => {}, openSheet: () => {} });

export const useUi = () => useContext(UiContext);
