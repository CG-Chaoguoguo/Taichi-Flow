import { useEffect, useRef, type ReactNode } from "react";

/** Shared modal boundary: focus containment, Escape, and focus restoration. */
export function ConfirmDialog({ title, children, onClose, busy = false }: {
  title: string; children: ReactNode; onClose: () => void; busy?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const element = dialog.current;
    element?.showModal();
    return () => { element?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={dialog} className="tf-dialog tf-dialog-narrow tf-native-dialog" aria-label={title}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <h2 className="tf-title tf-mb-4">{title}</h2>
    {children}
  </dialog>;
}
