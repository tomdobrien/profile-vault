"use client";

import { usePublicProfile } from "./profile-context";

export default function ResumeView() {
  const { profile, status } = usePublicProfile();
  if (!profile?.displayName) return <main className="resume-page resume-wait">
    <h1>Résumé</h1>
    <p role="status">{status === "checking" ? "Checking the résumé server…" : status === "offline" ? "The résumé is offline. It will appear here when the server reconnects." : "The résumé is currently unavailable."}</p>
    <a href={`${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/`}>Return home</a>
  </main>;
  const skillsByCategory = profile.skills.reduce<Record<string, string[]>>((groups, skill) => {
    const category = skill.category?.trim() || "Additional skills";
    (groups[category] ??= []).push(skill.name);
    return groups;
  }, {});

  return <main className="resume-page">
    <div className="resume-page-intro">
      <h1>{profile.displayName} <span className="redaction" role="img" aria-label="Surname withheld">••••••</span></h1>
      {profile.headline && <p className="resume-page-headline">{profile.headline}</p>}
      {profile.introduction && <p className="resume-page-summary">{profile.introduction}</p>}
      <div className="resume-contact">
        {profile.location && <span>{profile.location}</span>}
        <span>Phone <span className="redaction" role="img" aria-label="Phone number withheld">••• ••• ••••</span></span>
      </div>
    </div>

    <section className="resume-document" aria-labelledby="resume-document-title">
      <div className="resume-document-heading">
        <h2 id="resume-document-title">Career history</h2>
        <button className="secondary-button print-resume" onClick={() => window.print()}>Print / save PDF <span aria-hidden="true">↗</span></button>
      </div>
      <div className="resume-grid">
        <section className="resume-section resume-section-wide"><h3>Professional experience</h3>
          {profile.experience.length ? profile.experience.map((item, i) => <article className="entry" key={`${item.employer}-${item.role}-${i}`}>
            <div className="entry-heading"><h4>{item.employer}{item.location ? <span className="entry-location"> · {item.location}</span> : null}</h4><span>{[item.startDate, item.endDate].filter(Boolean).join(" – ")}</span></div>
            <p className="entry-meta"><strong>{item.role}</strong>{item.workMode ? ` · ${item.workMode}` : ""}</p>
            {item.responsibilities.length > 0 && <><p className="entry-subheading">Responsibilities</p><ul>{item.responsibilities.map((point, pointIndex) => <li key={`${point}-${pointIndex}`}>{point}</li>)}</ul></>}
            {item.projects.length > 0 && <><p className="entry-subheading">Projects &amp; impact</p><ul>{item.projects.map((point, pointIndex) => <li key={`${point}-${pointIndex}`}>{point}</li>)}</ul></>}
          </article>) : <p className="muted">No experience added yet.</p>}
        </section>

        {Object.keys(skillsByCategory).length > 0 && <section className="resume-section"><h3>Technical skills</h3><div className="skill-groups">{Object.entries(skillsByCategory).map(([category, skills]) => <p className="skill-group" key={category}><strong>{category}:</strong> {skills.join(", ")}</p>)}</div></section>}

        {profile.awards.length > 0 && <section className="resume-section"><h3>Awards</h3>{profile.awards.map((award, i) => <article className="entry" key={`${award.title}-${i}`}><div className="entry-heading"><h4>{award.title}</h4><span>{award.date}</span></div>{award.organization && <p className="entry-meta">{award.organization}</p>}{award.description && <p>{award.description}</p>}</article>)}</section>}

        {profile.education.length > 0 && <section className="resume-section"><h3>Education</h3>{profile.education.map((education, i) => <article className="entry" key={`${education.institution}-${education.degree}-${i}`}><div className="entry-heading"><h4>{education.institution}{education.location ? <span className="entry-location"> · {education.location}</span> : null}</h4><span>{education.graduationDate}</span></div><p className="entry-meta">{[education.degree, education.fieldOfStudy].filter(Boolean).join(" · ")}</p></article>)}</section>}

        {profile.selectedWork.length > 0 && <section className="resume-section"><h3>Selected work</h3>{profile.selectedWork.map((item, i) => <article className="entry" key={`${item.title}-${i}`}><h4>{item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a> : item.title}</h4>{item.summary && <p>{item.summary}</p>}{item.technologies.length > 0 && <p className="entry-meta">{item.technologies.join(" · ")}</p>}</article>)}</section>}

        {profile.links.length > 0 && <section className="resume-section"><h3>Links</h3><ul className="link-list">{profile.links.map((link, i) => <li key={`${link.label}-${i}`}><a href={link.url} target="_blank" rel="noreferrer">{link.label}<span aria-hidden="true"> ↗</span></a></li>)}</ul></section>}
      </div>
    </section>
  </main>;
}
