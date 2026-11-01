"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function ContactInbox() {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.unreadMessages>> | null>(null);
  const [error, setError] = useState("");
  const [revision, refresh] = useState(0);
  useEffect(() => {
    let active = true;
    api.unreadMessages().then(result => { if (active) { setRows(result); setError(""); } })
      .catch(() => { if (active) setError("Could not load the inbox."); });
    return () => { active = false; };
  }, [revision]);
  async function markRead(id: number) {
    try { await api.markMessageRead(id); refresh(value => value + 1); }
    catch { setError("Could not mark the message as read."); }
  }
  return <section className="admin-card admin-upload-card"><h2>Contact inbox</h2>
    <p role="status">{error || (rows === null ? "Checking messages…" : rows.length ? `${rows.length}${rows.length === 50 ? "+" : ""} unread` : "No unread messages.")}</p>
    {error && <button className="secondary-button" onClick={() => refresh(value => value + 1)}>Retry</button>}
    {rows?.map(row => <article className="entry" key={row.id}><h3>{row.sender || "Visitor"}</h3>
      <p style={{whiteSpace:"pre-wrap", overflowWrap:"anywhere"}}>{row.body}</p>
      <button className="secondary-button" onClick={() => markRead(row.id)}>Mark as read</button></article>)}
  </section>;
}
