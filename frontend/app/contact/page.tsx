"use client";

import { useState, type FormEvent } from "react";
import SiteChrome from "../site-chrome";
import { usePublicProfile } from "../profile-context";
import { api } from "@/lib/api";

export default function ContactPage() {
  const { status } = usePublicProfile();
  const [sender, setSender] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  async function send(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    try {
      await api.sendMessage(sender, body);
      setBody("");
      setNotice("Message delivered to the owner’s inbox.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Delivery failed. Try again.");
    } finally { setBusy(false); }
  }
  return <SiteChrome active="contact"><main className="resume-page legal-page"><h1>Contact me</h1>
    <p>Leave me a message. I’ll see it when I sign in. If you’d like a reply, include a way to reach you.</p>
    <form className="admin-form" onSubmit={send}>
      <label className="admin-field">Your name (optional)<input value={sender} maxLength={120} onChange={e => setSender(e.target.value)} /></label>
      <label className="admin-field">Message<textarea required rows={6} maxLength={4000} value={body} onChange={e => setBody(e.target.value)} /></label>
      <button className="primary-button" disabled={busy || status !== "online" || !body.trim()}>{busy ? "Sending…" : "Send message"}</button>
      <p role="status">{notice || (status === "offline" ? "The inbox is offline. You can send when the server reconnects." : status === "checking" ? "Checking inbox availability…" : "")}</p>
    </form></main></SiteChrome>;
}
