"use client";

import SiteChrome from "./site-chrome";
import { useState } from "react";
import { api } from "@/lib/api";
import { usePublicProfile } from "./profile-context";

const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export default function SignIn() {
  const { status } = usePublicProfile();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try { await api.loginUploadUser(email, password); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not sign in."); }
    finally { setBusy(false); }
  }

  return <SiteChrome active="upload"><main className="admin-shell private-entry">
    <form className="admin-login-card" onSubmit={login}>
      <h1>File backup</h1>
      <p className="admin-intro">Sign in to store and browse your files. Access is by invitation.</p>
      {status !== "online" && <p className="notice" role="status">{status === "checking" ? "Checking server availability…" : "File backup is temporarily offline. Your files are unavailable until the server returns. You can still explore Guild Bounty from the homepage."}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <label className="admin-field">Email<input type="email" required autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label className="admin-field">Password<input type="password" required autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <button className="primary-button" disabled={busy || status !== "online"}>{busy ? "Signing in…" : "Sign in"}</button>
      <a className="site-text-link" href={`${basePath}/`}>← Back to home</a>
      <a className="site-text-link" href={`${basePath}/admin/`}>Administrator sign in</a>
    </form>
  </main></SiteChrome>;
}
