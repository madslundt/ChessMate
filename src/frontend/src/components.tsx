import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  type ReactElement,
  type ReactNode,
} from 'react';
import { AlertCircle, LoaderCircle, X } from 'lucide-react';
import { useT } from './i18n';
export function Spinner({ label }: { label?: string }) {
  return (
    <span className="loading" role="status">
      <LoaderCircle size={17} className="spin" />
      {label}
    </span>
  );
}
export function ErrorNotice({ error, onDismiss }: { error: unknown; onDismiss?: () => void }) {
  const t = useT();
  if (!error) return null;
  return (
    <div className="error-notice" role="alert">
      <AlertCircle size={18} />
      <span>{error instanceof Error ? error.message : String(error)}</span>
      {onDismiss && (
        <button className="icon-button" aria-label={t('close')} onClick={onDismiss}>
          <X size={16} />
        </button>
      )}
    </div>
  );
}
export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const titleId = useId();
  const ref = useRef<HTMLDialogElement>(null),
    t = useT();
  useEffect(() => {
    const d = ref.current;
    d?.showModal();
    return () => d?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={onClose}
      className="modal"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-heading">
        <h2 id={titleId}>{title}</h2>
        <button className="icon-button" aria-label={t('close')} onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {Children.map(children, (child) =>
        isValidElement(child) && typeof child.type === 'string' && ['input', 'select', 'textarea'].includes(child.type)
          ? cloneElement(child as ReactElement<{ 'aria-label'?: string }>, {
              'aria-label': label,
            })
          : child,
      )}
    </label>
  );
}
export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="toggle-row">
      <span>{label}</span>
      <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}
export function PageHeading({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <header className="page-heading">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children}
    </header>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}
