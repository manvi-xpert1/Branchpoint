import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <path d="M10 6v20M10 16c0-5 12-3 12-10M10 16c0 5 12 3 12 10" stroke="#E9B85A" strokeWidth="2.6"
        fill="none" strokeLinecap="round" />
      <circle cx="22" cy="6" r="2.8" fill="#7CD1AB" />
      <circle cx="22" cy="26" r="2.8" fill="#FF5470" />
    </svg>
  );
}

/** The teal bar at the top of every app screen. The logo leads back to the landing page. */
export default function TopBar({ children, showSystemsLink = true }: { children?: ReactNode; showSystemsLink?: boolean }) {
  return (
    <header className="topbar">
      <Link to="/" className="brand"><Logo /> Branchpoint</Link>
      {children}
      <span className="spacer" />
      {showSystemsLink && <Link to="/systems" className="nav-link">All systems</Link>}
    </header>
  );
}
