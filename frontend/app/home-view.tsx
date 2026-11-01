"use client";

import SiteChrome from "./site-chrome";
import { usePublicProfile } from "./profile-context";
import SiteLink from "./site-link";

const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export default function HomeView() {
  const { email, status } = usePublicProfile();
  return <SiteChrome active="home">
    <main className="home-page">
      <section className="project-feature" aria-labelledby="home-title">
        <div className="project-copy">
          <h1 id="home-title">Projects <em>&amp; tools</em></h1>
          <p>I built Guild Bounty to try out a player-run quest board. Pick a challenge, back it with demo tokens, or submit proof of your run.</p>
          <SiteLink className="primary-button" href={`${basePath}/guild-bounty/`}>Explore Guild Bounty</SiteLink>
        </div>
        <figure className="project-plate">
          <img src={`${basePath}/guild-bounty/guild-hall.png`} alt="A lamplit fortress overlooking a mountain valley at dusk" fetchPriority="high" />
          <figcaption>The guild grounds <span>Guild Bounty · Game prototype</span></figcaption>
        </figure>
      </section>
      <section className="workshop-index" aria-labelledby="directory-title">
        <h2 id="directory-title">Site directory</h2>
        <SiteLink className="index-row" href={`${basePath}/resume/`}>
          <h3>Résumé</h3><p>Experience, education, and technical skills.</p><span className="row-end">View résumé <Arrow /></span>
        </SiteLink>
        <SiteLink className="index-row" href={`${basePath}/upload/`}>
          <h3>File backup</h3><p>Private storage for invited accounts.</p><span className="row-end">{status === "offline" ? "Server offline" : "Open backup"} <Arrow /></span>
        </SiteLink>
      </section>
      {email && <div className="contact-endnote"><h2>Get in touch</h2><a href={`mailto:${email}`}>{email}</a></div>}
    </main>
  </SiteChrome>;
}

function Arrow() {
  return <svg aria-hidden="true" width="21" height="16" viewBox="0 0 21 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M1 8h17m-6-6 6 6-6 6"/></svg>;
}
