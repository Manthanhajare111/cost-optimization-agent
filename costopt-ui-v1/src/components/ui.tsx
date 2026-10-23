import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button as Ui5Button, Icon, MessageStrip, ObjectStatus } from "@ui5/webcomponents-react";
import { NavLink, useLocation } from "react-router-dom";
import { useAnalysisStore } from "../store";
import { statusLabel } from "../domain";

export type ButtonVariant = "primary" | "secondary" | "danger" | "text";
export function Button({ variant = "secondary", children, onClick, disabled, type = "button", icon, className }: { variant?: ButtonVariant; children: ReactNode; onClick?: () => void; disabled?: boolean; type?: "button" | "submit"; icon?: string; className?: string }) {
  const design = variant === "primary" ? "Emphasized" : variant === "danger" ? "Negative" : variant === "text" ? "Transparent" : "Default";
  return <Ui5Button className={className} design={design} disabled={disabled} type={type === "submit" ? "Submit" : "Button"} icon={icon} onClick={onClick}>{children}</Ui5Button>;
}

export function Card({ children, className = "", title, subtitle, action }: { children: ReactNode; className?: string; title?: string; subtitle?: string; action?: ReactNode }) {
  return <section className={`card ${className}`.trim()}>{(title || action) && <header className="card-header"><div>{title && <h2>{title}</h2>}{subtitle && <p>{subtitle}</p>}</div>{action}</header>}<div className="card-body">{children}</div></section>;
}

export function MetricCard({ label, value, detail, tone = "neutral" }: { label: string; value: ReactNode; detail?: string; tone?: "positive" | "warning" | "negative" | "info" | "neutral" }) {
  return <article className={`metric metric-${tone}`}><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</article>;
}

type BadgeState = "Positive" | "Critical" | "Negative" | "Information" | "None";
const stateMap: Record<string, BadgeState> = { approved: "Positive", ready: "Positive", accepted: "Positive", resolved: "Positive", success: "Positive", awaiting_approval: "Critical", warning: "Critical", modified: "Critical", needs_attention: "Negative", error: "Negative", rejected: "Negative", info: "Information", in_progress: "Information", pending: "Information", specialist_review: "Information" };
export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const state = stateMap[status] || "None";
  const icon = state === "Positive" ? "sys-enter-2" : state === "Negative" ? "error" : state === "Critical" ? "alert" : "information";
  return <span className={`status-badge status-${state.toLowerCase()}`}><Icon name={icon} /><ObjectStatus state={state}>{label || statusLabel(status)}</ObjectStatus></span>;
}

export function Modal({ open, title, children, footer, onClose, size = "medium", className = "" }: { open: boolean; title: string; children: ReactNode; footer?: ReactNode; onClose: () => void; size?: "small" | "medium" | "large"; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const node = ref.current; if (!node) return; if (open && !node.open) node.showModal(); if (!open && node.open) node.close(); }, [open]);
  useEffect(() => { const node = ref.current; const close = () => onClose(); node?.addEventListener("close", close); return () => node?.removeEventListener("close", close); }, [onClose]);
  return <dialog ref={ref} className={`modal modal-${size} ${className}`.trim()} aria-labelledby="modal-title"><header><h2 id="modal-title">{title}</h2><Button className="modal-close" variant="text" icon="decline" onClick={onClose}>Close</Button></header><div className="modal-content">{children}</div>{footer && <footer>{footer}</footer>}</dialog>;
}

export interface Column<T> { key: string; label: string; value: (row: T) => ReactNode; sortValue?: (row: T) => string | number; className?: string }
export function DataTable<T extends { id: string }>({ rows, columns, pageSize = 6, empty = "No records found.", onRowClick, ariaLabel = "Data table" }: { rows: T[]; columns: Column<T>[]; pageSize?: number; empty?: string; onRowClick?: (row: T) => void; ariaLabel?: string }) {
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<{ key: string; direction: 1 | -1 } | null>(null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((item) => item.key === sort.key);
    if (!column?.sortValue) return rows;
    return [...rows].sort((a, b) => String(column.sortValue!(a)).localeCompare(String(column.sortValue!(b)), undefined, { numeric: true }) * sort.direction);
  }, [rows, columns, sort]);
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = Math.min(page, pages - 1);
  const visible = sorted.slice(current * pageSize, current * pageSize + pageSize);
  return <div className="table-region"><div className="table-scroll"><table aria-label={ariaLabel}><thead><tr>{columns.map((column) => <th key={column.key} className={column.className}>{column.sortValue ? <button type="button" onClick={() => setSort((value) => value?.key === column.key ? { key: column.key, direction: value.direction === 1 ? -1 : 1 } : { key: column.key, direction: 1 })}>{column.label}<Icon name={sort?.key === column.key && sort.direction === -1 ? "sort-descending" : "sort-ascending"} /></button> : column.label}</th>)}</tr></thead><tbody>{visible.length ? visible.map((row) => <tr key={row.id} tabIndex={onRowClick ? 0 : undefined} className={onRowClick ? "clickable" : ""} onClick={() => onRowClick?.(row)} onKeyDown={(event) => { if (onRowClick && (event.key === "Enter" || event.key === " ")) onRowClick(row); }}>{columns.map((column) => <td key={column.key} className={column.className}>{column.value(row)}</td>)}</tr>) : <tr><td colSpan={columns.length}><EmptyState title={empty} compact /></td></tr>}</tbody></table></div>{sorted.length > pageSize && <div className="pagination"><span>Page {current + 1} of {pages}</span><Button variant="text" disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</Button><Button variant="text" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>Next</Button></div>}</div>;
}

export function EmptyState({ title, description, action, compact = false }: { title: string; description?: string; action?: ReactNode; compact?: boolean }) {
  return <div className={`empty-state ${compact ? "compact" : ""}`}><Icon name="inbox" /><h2>{title}</h2>{description && <p>{description}</p>}{action}</div>;
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return <header className="page-header"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</header>;
}

export function Breadcrumbs({ items }: { items: { label: string; to?: string }[] }) {
  return <nav className="breadcrumbs" aria-label="Breadcrumb">{items.map((item, index) => <span key={`${index}`}>{item.to ? <NavLink to={item.to}>{item.label}</NavLink> : item.label}{index < items.length - 1 && <Icon name="navigation-right-arrow" />}</span>)}</nav>;
}

const steps = ["add-data", "check-data", "setup", "review", "approve", "report"];
export function StepNavigation({ current }: { current: string }) {
  const active = steps.indexOf(current);
  return <ol className="step-navigation" aria-label="Analysis progress">{steps.map((step, index) => <li key={step} className={index === active ? "current" : index < active ? "complete" : ""}><span>{index < active ? <Icon name="accept" /> : index + 1}</span><b>{statusLabel(step)}</b></li>)}</ol>;
}

export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void }) {
  return <div className="tabs" role="tablist">{tabs.map((tab) => <button key={tab.id} role="tab" aria-selected={active === tab.id} onClick={() => onChange(tab.id)}>{tab.label}</button>)}</div>;
}

export function Accordion({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
  return <details className="accordion" open={open}><summary>{title}<Icon name="slim-arrow-down" /></summary><div>{children}</div></details>;
}

export function FormField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="form-field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

export function SearchField({ value, onChange, placeholder = "Search" }: { value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="search-field"><Icon name="search" /><span className="sr-only">{placeholder}</span><input type="search" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

const navItems = [
  { to: "/analyses", label: "Analyses", icon: "business-objects-experience" },
  { to: "/reference-data", label: "Reference Data", icon: "database" },
  { to: "/reports", label: "Reports", icon: "document-text" },
  { to: "/audit-history", label: "Audit History", icon: "activity-items" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { navOpen, setNavOpen, toast, notify, resetDemo, syncBackend } = useAnalysisStore();
  const location = useLocation();
  useEffect(() => { void syncBackend(); }, [syncBackend]);
  useEffect(() => setNavOpen(false), [location.pathname, setNavOpen]);
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => notify(null), 3500); return () => clearTimeout(timer); }, [toast, notify]);
  return <div className="app-shell">
    <header className="shell-header"><button className="menu-button" aria-label="Toggle navigation" aria-expanded={navOpen} onClick={() => setNavOpen(!navOpen)}><Icon name="menu2" /></button><NavLink to="/analyses" className="brand"><span className="brand-mark">C</span><strong>COSTOPT</strong><span>AI</span></NavLink><div className="shell-spacer" /><button className="shell-icon" aria-label="Notifications"><Icon name="bell" /><span className="notification-dot" /></button><button className="profile" aria-label="Open user profile"><span>AM</span><span><b>Alex Morgan</b><small>Cost Optimization Lead</small></span><Icon name="slim-arrow-down" /></button></header>
    <aside className={`side-nav ${navOpen ? "open" : ""}`}><p>WORKSPACE</p><nav>{navItems.map((item) => <NavLink key={item.to} to={item.to} className={({ isActive }) => isActive ? "active" : ""}><Icon name={item.icon} />{item.label}</NavLink>)}</nav><div className="nav-footer"><button onClick={resetDemo}><Icon name="refresh" />Reset demo data</button><small>Local prototype · V1</small></div></aside>
    {navOpen && <button className="nav-backdrop" aria-label="Close navigation" onClick={() => setNavOpen(false)} />}
    <main className="main-content" id="main-content">{children}</main>
    {toast && <div className="toast" role="status"><MessageStrip design={toast.kind === "success" ? "Positive" : toast.kind === "error" ? "Negative" : toast.kind === "warning" ? "Critical" : "Information"} hideCloseButton>{toast.message}</MessageStrip></div>}
  </div>;
}
