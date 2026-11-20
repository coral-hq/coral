import { useSyncExternalStore } from "react";

/** What a card says while the browser is offline and its actions are disabled. */
export const OFFLINE_TEXT = "You’re offline.";

function subscribeOnline(listener: () => void): () => void {
  window.addEventListener("online", listener);
  window.addEventListener("offline", listener);
  return () => {
    window.removeEventListener("online", listener);
    window.removeEventListener("offline", listener);
  };
}

const readOnline = () => navigator.onLine !== false;

/** Whether the browser is online, following its online and offline events. */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribeOnline, readOnline, () => true);
}
