"use client";

import type { ReactNode } from "react";
import ThemeToggle from "./theme-toggle";
import { usePublicProfile } from "./profile-context";
import SiteLink from "./site-link";
import { api } from "@/lib/api";

const siteBasePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const destinations = [
  { id: "home", label: "Home", href: `${siteBasePath}/` },
  { id: "resume", label: "Résumé", href: `${siteBasePath}/resume/` },
  { id: "upload", label: "File backup", href: `${siteBasePath}/upload/` },
] as const;

type ActiveSection = typeof destinations[number]["id"];

export default function SiteChrome({ children, active }: Readonly<{ children: ReactNode; active?: ActiveSection }>) {
  const { session } = usePublicProfile();

  return <div className="personal-site">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="site-header">
      <SiteLink className="site-wordmark" href={`${siteBasePath}/`} aria-label="Profile Vault home">
        <svg width="34" height="36" viewBox="0 0 34 36" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M3 5h10l4 4h14v22H3z"/><path d="M7 14h19M7 19h13"/></svg>
        Profile Vault
      </SiteLink>
      <nav className="site-navigation" aria-label="Main navigation">
        {destinations.map((item) => <SiteLink key={item.id} href={item.href} aria-current={active === item.id ? "page" : undefined}>{item.label}</SiteLink>)}
        {session && <button className="secondary-button" type="button" onClick={() => api.clearUploadSession()}>Log out</button>}
      </nav>
      <ThemeToggle />
    </header>
    <div id="main-content" className="site-content" tabIndex={-1}>{children}</div>
    <footer className="site-footer">
      <SiteLink className="owner-corner-link" href={`${siteBasePath}/admin/`}>Owner sign-in</SiteLink>
      <span className="footer-links"><SiteLink href={`${siteBasePath}/terms/`}>Terms</SiteLink><SiteLink href={`${siteBasePath}/privacy/`}>Privacy</SiteLink><SiteLink href={`${siteBasePath}/acceptable-use/`}>Acceptable use</SiteLink></span>
    </footer>
  </div>;
}

export { destinations };
