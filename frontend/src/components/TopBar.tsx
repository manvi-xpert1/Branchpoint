import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
      <path d="M10 6v20M10 16c0-5 12-3 12-10M10 16c0 5 12 3 12 10" stroke="#60a5fa" strokeWidth="2.6"
        fill="none" strokeLinecap="round" />
      <circle cx="22" cy="6" r="2.6" fill="#f87171" />
      <circle cx="22" cy="26" r="2.6" fill="#34d399" />
    </svg>
  );
}

export default function TopBar({ children }: { children?: ReactNode }) {
  return (
    <header className="topbar">
      <Link to="/" className="brand"><Logo /> Branchpoint</Link>
      {children}
    </header>
  );
}
