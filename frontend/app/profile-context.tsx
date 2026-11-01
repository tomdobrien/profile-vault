"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import type { Profile, SiteSession } from "@/lib/types";

type PublicProfileState = {
  profile: Profile | null;
  email: string | null;
  status: "checking" | "online" | "offline";
  session: SiteSession | null;
  publicPermissions: string[];
};
const initial: PublicProfileState = {
  profile: null, email: null, status: "checking", session: null, publicPermissions: [],
};

const PublicProfileContext = createContext({ ...initial, can: (_permission: string): boolean => false });

export function PublicProfileProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [state, setState] = useState(initial);
  const [revision, setRevision] = useState(0);
  const pathname = usePathname();
  const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  const route = (basePath && pathname.startsWith(basePath + "/") ? pathname.slice(basePath.length) : pathname).replace(/\/$/, "") || "/";

  useEffect(() => {
    const changed = () => {
      setState(initial);
      setRevision((value) => value + 1);
    };
    window.addEventListener("profile-session-change", changed);
    return () => window.removeEventListener("profile-session-change", changed);
  }, []);

  useEffect(() => {
    let active = true;
    let current: AbortController | null = null;
    function clearPersonalData() {
      current?.abort();
      current = null;
      setState(previous => ({ ...previous, profile: null, email: null }));
    }
    function networkOffline() {
      clearPersonalData();
      setState({ ...initial, status: "offline" });
    }
    async function checkServer() {
      if (document.visibilityState === "hidden" || current) return;
      if (!navigator.onLine) { networkOffline(); return; }
      const request = new AbortController();
      current = request;
      const timeout = window.setTimeout(() => request.abort(), 5000);
      try {
        const [visitor, session, profile, contact] = await Promise.all([
          api.getPublicAccess(request.signal), api.getSiteSession(request.signal),
          route === "/resume" ? api.getPublishedResume(request.signal).catch(() => null) : null,
          route === "/" || route === "/terms" ? api.getPublicContact(request.signal).catch(() => null) : null,
        ]);
        if (active && current === request) {
          setState({ profile, email: profile?.contactEmail ?? contact?.contactEmail ?? null,
            session, publicPermissions: visitor.permissions, status: "online" });
        }
      } catch {
        if (active && current === request) setState({ ...initial, status: "offline" });
      } finally {
        window.clearTimeout(timeout);
        if (current === request) current = null;
      }
    }
    function visibilityChanged() {
      if (document.visibilityState === "hidden") clearPersonalData();
      else void checkServer();
    }
    void checkServer();
    const interval = window.setInterval(checkServer, 30_000);
    window.addEventListener("online", checkServer);
    window.addEventListener("offline", networkOffline);
    window.addEventListener("focus", checkServer);
    window.addEventListener("pagehide", clearPersonalData);
    window.addEventListener("pageshow", checkServer);
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      active = false;
      current?.abort();
      window.clearInterval(interval);
      window.removeEventListener("online", checkServer);
      window.removeEventListener("offline", networkOffline);
      window.removeEventListener("focus", checkServer);
      window.removeEventListener("pagehide", clearPersonalData);
      window.removeEventListener("pageshow", checkServer);
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [route, revision]);

  const can = (permission: string) => state.status === "online" && Boolean(
    state.session?.isAdmin || state.session?.permissions.includes(permission) || state.publicPermissions.includes(permission));
  return <PublicProfileContext.Provider value={{ ...state, can }}>{children}</PublicProfileContext.Provider>;
}

export function usePublicProfile() { return useContext(PublicProfileContext); }
