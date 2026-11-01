"use client";
import ContactInbox from "./contact-inbox";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Award, Education, Experience, Profile, ProfileLink, SelectedWork, Skill, UploadInvitation, UploadUser, PermissionOption } from "@/lib/types";
import ThemeToggle from "../theme-toggle";
import FileBrowser from "../file-browser";
import PermissionPicker from "../permission-picker";

const siteBasePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const emptyProfile: Profile = {
  displayName: null,
  headline: null,
  introduction: null,
  location: null,
  contactEmail: null,
  contactPhone: null,
  experience: [],
  selectedWork: [],
  skills: [],
  links: [],
  awards: [],
  education: [],
};

type RepeatedSection = "experience" | "selectedWork" | "skills" | "links" | "awards" | "education";
type EntryFor<S extends RepeatedSection> = Profile[S][number];

const newExperience: Experience = {
  employer: "", location: null, role: "", workMode: null, startDate: null, endDate: null, responsibilities: [], projects: [],
};
const newWork: SelectedWork = { title: "", summary: null, technologies: [], url: null };
const newSkill: Skill = { name: "", category: null };
const newLink: ProfileLink = { label: "", url: "" };
const newAward: Award = { title: "", organization: null, date: null, description: null };
const newEducation: Education = { institution: "", location: null, degree: "", fieldOfStudy: null, graduationDate: null };

function splitLines(value: string): string[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean);
}

export default function AdminPage() {
  const [profile, setProfile] = useState<Profile>(emptyProfile);
  const [loading, setLoading] = useState(true);
  const [authChecking, setAuthChecking] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [loginPassword, setLoginPassword] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [authError, setAuthError] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [photoFiles, setPhotoFiles] = useState<File[]>([]);
  const [uploadingPhotos, setUploadingPhotos] = useState(false);
  const [photoProgress, setPhotoProgress] = useState("");
  const [photoNotice, setPhotoNotice] = useState("");
  const [photoError, setPhotoError] = useState("");
  const [uploadUsers, setUploadUsers] = useState<UploadUser[]>([]);
  const [uploadInvitations, setUploadInvitations] = useState<UploadInvitation[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [invitePermissions, setInvitePermissions] = useState<string[]>([]);
  const [permissionOptions, setPermissionOptions] = useState<PermissionOption[]>([]);
  const [permissionBusy, setPermissionBusy] = useState(false);
  const [inviteUrl, setInviteUrl] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [accountNotice, setAccountNotice] = useState("");
  const [accountError, setAccountError] = useState("");
  const [fileAccount, setFileAccount] = useState<number | undefined>(undefined);
  const [fileRevision, setFileRevision] = useState(0);
  const photoInputRef = useRef<HTMLInputElement>(null);

  async function refreshUploadAccounts() {
    const [users, invitations, options] = await Promise.all([
      api.listUploadUsers(), api.listUploadInvitations(), api.getPermissionOptions(),
    ]);
    setUploadUsers(users);
    setUploadInvitations(invitations);
    setPermissionOptions(options.filter((option) => option.key !== "resume:view"));
  }

  useEffect(() => {
    api.getAdminSession()
      .then(async (isAuthenticated) => {
        if (!isAuthenticated) return;
        setAuthenticated(true);
        try {
          setProfile(await api.getProfile());
        } catch {
          setAuthenticated(false);
          setAuthError("Could not load the profile. Check that the backend is running.");
        }
        try {
          await refreshUploadAccounts();
        } catch (cause) {
          setAccountError(cause instanceof Error ? cause.message : "Could not load upload accounts.");
        }
      })
      .catch(() => setAuthError("Could not verify admin access. Check that the backend is running and authentication is configured."))
      .finally(() => { setAuthChecking(false); setLoading(false); });
  }, []);

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoggingIn(true);
    setAuthError("");
    try {
      await api.loginAdmin(loginPassword);
      setAuthenticated(true);
      setLoginPassword("");
      setLoading(true);
      setProfile(await api.getProfile());
      await refreshUploadAccounts();
    } catch (cause) {
      setAuthenticated(false);
      setAuthError(cause instanceof Error ? cause.message : "Admin login failed.");
    } finally {
      setLoggingIn(false);
      setLoading(false);
    }
  }

  async function logout() {
    try {
      await api.logoutAdmin();
    } catch {
      setAuthError("Signed out on this device. The server could not be reached.");
    } finally {
      setAuthenticated(false);
      setProfile(emptyProfile);
    }
  }

  function updateEntry<S extends RepeatedSection>(section: S, index: number, patch: Partial<EntryFor<S>>) {
    setProfile((current) => {
      const entries = current[section] as EntryFor<S>[];
      return {
        ...current,
        [section]: entries.map((entry, entryIndex) =>
          entryIndex === index ? { ...entry, ...patch } : entry,
        ),
      };
    });
  }

  function addEntry<S extends RepeatedSection>(section: S, entry: EntryFor<S>) {
    setProfile((current) => ({
      ...current,
      [section]: [...(current[section] as EntryFor<S>[]), entry],
    }));
  }

  function removeEntry<S extends RepeatedSection>(section: S, index: number) {
    setProfile((current) => ({
      ...current,
      [section]: (current[section] as EntryFor<S>[]).filter((_, entryIndex) => entryIndex !== index),
    }));
  }

  async function saveProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      setProfile(await api.updateProfile(profile));
      setNotice("Saved to your private profile. The public résumé uses the separate published copy on your server.");
    } catch {
      setError("Could not save your changes. Check that the backend is running and try again.");
    } finally {
      setSaving(false);
    }
  }

  async function uploadPhotos(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (photoFiles.length === 0) return;
    setUploadingPhotos(true);
    setPhotoNotice("");
    setPhotoError("");
    let uploaded = 0;
    let skipped = 0;
    for (const [index, file] of photoFiles.entries()) {
      setPhotoProgress(`Uploading and checking ${index + 1} of ${photoFiles.length}: ${file.name}`);
      try {
        const result = await api.uploadPhoto(file);
        if (result.duplicate) skipped += 1;
        else uploaded += 1;
      } catch (cause) {
        setPhotoError(`${uploaded} uploaded, ${skipped} duplicates skipped. ${cause instanceof Error ? cause.message : "Upload failed."}`);
        setPhotoFiles(photoFiles.slice(index));
        if (photoInputRef.current) photoInputRef.current.value = "";
        setPhotoProgress("");
        setUploadingPhotos(false);
        setFileRevision((value) => value + 1);
        return;
      }
    }
    setPhotoProgress("");
    setPhotoNotice(uploaded > 0
      ? `${uploaded} new ${uploaded === 1 ? "file was" : "files were"} saved; ${skipped} duplicates skipped.`
      : `No new files were saved; ${skipped} ${skipped === 1 ? "duplicate was" : "duplicates were"} skipped.`);
    setPhotoFiles([]);
    if (photoInputRef.current) photoInputRef.current.value = "";
    setUploadingPhotos(false);
    setFileRevision((value) => value + 1);
  }

  async function inviteUploader(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setInviteBusy(true);
    setAccountError("");
    setAccountNotice("");
    setInviteUrl("");
    try {
      const invitation = await api.createUploadInvitation(inviteEmail, inviteName, invitePermissions);
      setInviteUrl(`${window.location.origin}${siteBasePath}/invite/#token=${encodeURIComponent(invitation.token)}`);
      setAccountNotice(`Invitation created for ${invitation.email}. Share the link below; it expires in 7 days and can be used once.`);
      setInviteEmail("");
      setInviteName("");
      setInvitePermissions([]);
      await refreshUploadAccounts();
    } catch (cause) {
      setAccountError(cause instanceof Error ? cause.message : "Could not create invitation.");
    } finally {
      setInviteBusy(false);
    }
  }

  async function revokeInvitation(id: number) {
    setAccountError("");
    try {
      await api.revokeUploadInvitation(id);
      setAccountNotice("Invitation revoked.");
      await refreshUploadAccounts();
    } catch (cause) {
      setAccountError(cause instanceof Error ? cause.message : "Could not revoke invitation.");
    }
  }

  async function disableUploader(user: UploadUser) {
    if (!window.confirm(`Disable site access for ${user.email}? Their existing backup files will stay in place.`)) return;
    setAccountError("");
    try {
      await api.disableUploadUser(user.id);
      setAccountNotice(`Site access for ${user.email} has been disabled.`);
      await refreshUploadAccounts();
    } catch (cause) {
      setAccountError(cause instanceof Error ? cause.message : "Could not disable this account.");
    }
  }

  async function savePermissions(user: UploadUser) {
    setPermissionBusy(true);
    setAccountError("");
    setAccountNotice("");
    try {
      await api.setUserPermissions(user.id, user.permissions);
      await refreshUploadAccounts();
      setAccountNotice(`Permissions saved for ${user.email}.`);
    } catch (cause) {
      setAccountError(cause instanceof Error ? cause.message : "Could not save permissions.");
    } finally { setPermissionBusy(false); }
  }

  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <h1>Manage your profile</h1>
          <p className="admin-intro">Edit your profile, manage invitations and permissions, or send files to private Pi storage.</p>
        </div>
        <div className="admin-header-actions">{authenticated && <button className="secondary-button" type="button" onClick={logout}>Log out</button>}<ThemeToggle /><a className="admin-home-link" href={`${siteBasePath}/`}>← View homepage</a></div>
      </header>

      {authChecking ? <p className="notice" role="status">Checking admin access…</p> : !authenticated ? (
        <form className="admin-login-card" onSubmit={login}>
          <h2>Admin sign in</h2>
          <p className="admin-intro">Enter your password to edit your profile or upload to private storage.</p>
          {authError && <p className="notice notice-error" role="alert">{authError}</p>}
          <label className="admin-field">Password
            <input type="password" autoComplete="current-password" required value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} />
          </label>
          <button className="primary-button" type="submit" disabled={loggingIn}>{loggingIn ? "Signing in…" : "Sign in"}</button>
        </form>
      ) : loading ? <p className="notice" role="status">Loading your profile…</p> : (
        <>
        <ContactInbox />
        <section className="admin-card admin-upload-card" aria-labelledby="photo-upload-heading">
          <div className="admin-section-heading"><div><p className="eyebrow">Private storage</p><h2 id="photo-upload-heading">Phone photo backup</h2></div></div>
          <p className="admin-intro">Choose photos or videos from this device. They’ll be copied to the photo folder on your Pi and won’t appear on the public homepage.</p>
          <form className="admin-upload-form" onSubmit={uploadPhotos}>
            <label className="admin-field">Photos and videos
              <input ref={photoInputRef} type="file" multiple disabled={uploadingPhotos} onChange={(event) => { setPhotoFiles(Array.from(event.target.files ?? [])); setPhotoNotice(""); setPhotoError(""); }} />
            </label>
            <p className="field-hint">Any file type, up to 500 MB per file. Files are copied; originals stay on this device.</p>
            {photoFiles.length > 0 && <p className="admin-empty">{photoFiles.length} {photoFiles.length === 1 ? "file" : "files"} selected</p>}
            {photoProgress && <p className="notice" role="status">{photoProgress}</p>}
            {photoNotice && <p className="notice notice-success" role="status">{photoNotice}</p>}
            {photoError && <p className="notice notice-error" role="alert">{photoError}</p>}
            <button className="primary-button" type="submit" disabled={uploadingPhotos || photoFiles.length === 0}>{uploadingPhotos ? "Uploading…" : "Upload to Pi"}<span aria-hidden="true">↑</span></button>
          </form>
        </section>
        <section className="admin-card admin-upload-card" aria-labelledby="upload-accounts-heading">
          <div className="admin-section-heading"><div><p className="eyebrow">Access control</p><h2 id="upload-accounts-heading">Site access and permissions</h2></div></div>
          <p className="admin-intro">Select which file features invited accounts can access. Only you can change permissions. New features are never granted automatically.</p>
          {accountError && <p className="notice notice-error" role="alert">{accountError}</p>}
          {accountNotice && <p className="notice notice-success" role="status">{accountNotice}</p>}
          <div className="admin-entry">
            <h3>Public introduction and resume</h3>
            <p className="field-hint">The Pi serves a separate public résumé while connected. Your saved editor details stay private. Update the published résumé on the Pi to change what visitors see.</p>
          </div>
          <form className="admin-upload-form" onSubmit={inviteUploader}>
            <div className="admin-field-grid">
              <label className="admin-field">Invite email<input type="email" required maxLength={254} autoComplete="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} /></label>
              <label className="admin-field">Name (optional)<input maxLength={160} autoComplete="name" value={inviteName} onChange={(event) => setInviteName(event.target.value)} /></label>
            </div>
            <PermissionPicker options={permissionOptions} value={invitePermissions} onChange={setInvitePermissions} disabled={inviteBusy} />
            <p className="field-hint">Unchecked features are not granted to this account. Public features are available to everyone.</p>
            <button className="primary-button" type="submit" disabled={inviteBusy}>{inviteBusy ? "Creating invite…" : "Create invite"}</button>
          </form>
          {inviteUrl && <div className="admin-entry"><p className="field-hint">This one-time link is shown only now. Copy it and send it to the invited person.</p><label className="admin-field">Invitation link<input readOnly value={inviteUrl} onFocus={(event) => event.currentTarget.select()} /></label><button className="secondary-button" type="button" onClick={() => void navigator.clipboard.writeText(inviteUrl)}>Copy link</button></div>}
          <h3>Accounts</h3>
          {uploadUsers.length === 0 ? <p className="admin-empty">No invited accounts yet.</p> : <div className="account-list">{uploadUsers.map((user) => <div className="admin-entry" key={user.id}>
            <div className="account-row"><div><strong>{user.displayName || user.email}</strong><p className="field-hint">{user.email} · {user.active ? "Active" : "Disabled"}</p></div>{user.active && <button className="remove-button" type="button" disabled={permissionBusy} onClick={() => void disableUploader(user)}>Disable</button>}</div>
            <PermissionPicker options={permissionOptions} value={user.permissions} disabled={permissionBusy || !user.active} onChange={(permissions) => setUploadUsers((users) => users.map((item) => item.id === user.id ? { ...item, permissions } : item))} />
            {user.active && <button className="secondary-button" type="button" disabled={permissionBusy} onClick={() => void savePermissions(user)}>Save permissions</button>}
          </div>)}</div>}
          <h3>Invitations</h3>
          {uploadInvitations.length === 0 ? <p className="admin-empty">No invitations yet.</p> : <div className="account-list">{uploadInvitations.map((invitation) => {
            const state = invitation.accepted ? "Accepted" : invitation.revoked ? "Revoked" : invitation.expired ? "Expired" : "Pending";
            return <div className="account-row" key={invitation.id}><div><strong>{invitation.displayName || invitation.email}</strong><p className="field-hint">{invitation.email} · {state}</p><p className="field-hint">{invitation.permissions.map((key) => permissionOptions.find((option) => option.key === key)?.label ?? key).join(", ") || "No account permissions"}</p></div>{state === "Pending" && <button className="remove-button" type="button" onClick={() => void revokeInvitation(invitation.id)}>Revoke</button>}</div>;
          })}</div>}
        </section>
        <section className="admin-card admin-upload-card" aria-labelledby="backup-files-heading">
          <div className="admin-section-heading"><div><p className="eyebrow">Private storage</p><h2 id="backup-files-heading">Browse backup files</h2></div></div>
          <label className="admin-field">Account
            <select value={fileAccount ?? "owner"} onChange={(event) => setFileAccount(event.target.value === "owner" ? undefined : Number(event.target.value))}>
              <option value="owner">My files (site owner)</option>
              {uploadUsers.map((user) => <option key={user.id} value={user.id}>{user.displayName ? `${user.displayName} (${user.email})` : user.email}{user.active ? "" : " - disabled"}</option>)}
            </select>
          </label>
          <FileBrowser key={fileAccount ?? "owner"} admin userId={fileAccount} title="Uploaded files" revision={fileRevision} />
        </section>
        <form className="admin-form" onSubmit={saveProfile}>
          {error && <p className="notice notice-error" role="alert">{error}</p>}
          {notice && <p className="notice notice-success" role="status">{notice}</p>}

          <section className="admin-card" aria-labelledby="intro-heading">
            <div className="admin-section-heading"><div><p className="eyebrow">Resume header</p><h2 id="intro-heading">Introduction &amp; contact</h2></div></div>
            <div className="admin-field-grid">
              <label className="admin-field">Display name
                <input maxLength={160} value={profile.displayName ?? ""} onChange={(e) => setProfile({ ...profile, displayName: e.target.value || null })} />
              </label>
              <label className="admin-field">Headline
                <input maxLength={240} value={profile.headline ?? ""} onChange={(e) => setProfile({ ...profile, headline: e.target.value || null })} />
              </label>
              <label className="admin-field">City / region
                <input maxLength={160} placeholder="City, State" value={profile.location ?? ""} onChange={(e) => setProfile({ ...profile, location: e.target.value || null })} />
              </label>
              <label className="admin-field">Email
                <input type="email" maxLength={254} value={profile.contactEmail ?? ""} onChange={(e) => setProfile({ ...profile, contactEmail: e.target.value || null })} />
              </label>
              <label className="admin-field">Phone
                <input type="tel" maxLength={80} value={profile.contactPhone ?? ""} onChange={(e) => setProfile({ ...profile, contactPhone: e.target.value || null })} />
              </label>
              <label className="admin-field admin-field-wide">Introduction
                <textarea rows={4} value={profile.introduction ?? ""} onChange={(e) => setProfile({ ...profile, introduction: e.target.value || null })} />
              </label>
            </div>
          </section>

          <section className="admin-card" aria-labelledby="experience-heading">
            <div className="admin-section-heading"><div><p className="eyebrow">Resume</p><h2 id="experience-heading">Experience</h2></div><button className="secondary-button" type="button" onClick={() => addEntry("experience", { ...newExperience })}>Add experience</button></div>
            {profile.experience.length === 0 && <p className="admin-empty">No experience entries yet.</p>}
            {profile.experience.map((item, index) => <fieldset className="admin-entry" key={`experience-${index}`}>
              <legend>Position {index + 1}</legend><button className="remove-button" type="button" onClick={() => removeEntry("experience", index)}>Remove</button>
              <div className="admin-field-grid">
                <label className="admin-field">Role<input required value={item.role} onChange={(e) => updateEntry("experience", index, { role: e.target.value })} /></label>
                <label className="admin-field">Employer<input required value={item.employer} onChange={(e) => updateEntry("experience", index, { employer: e.target.value })} /></label>
                <label className="admin-field">City / region<input value={item.location ?? ""} onChange={(e) => updateEntry("experience", index, { location: e.target.value || null })} /></label>
                <label className="admin-field">Work arrangement<input placeholder="On-site, hybrid, remote" value={item.workMode ?? ""} onChange={(e) => updateEntry("experience", index, { workMode: e.target.value || null })} /></label>
                <label className="admin-field">Start date<input placeholder="2022" value={item.startDate ?? ""} onChange={(e) => updateEntry("experience", index, { startDate: e.target.value || null })} /></label>
                <label className="admin-field">End date<input placeholder="Present" value={item.endDate ?? ""} onChange={(e) => updateEntry("experience", index, { endDate: e.target.value || null })} /></label>
                <label className="admin-field admin-field-wide">Responsibilities <span className="field-hint">One per line</span><textarea rows={3} value={item.responsibilities.join("\n")} onChange={(e) => updateEntry("experience", index, { responsibilities: splitLines(e.target.value) })} /></label>
                <label className="admin-field admin-field-wide">Projects &amp; impact <span className="field-hint">One outcome or project per line</span><textarea rows={4} value={item.projects.join("\n")} onChange={(e) => updateEntry("experience", index, { projects: splitLines(e.target.value) })} /></label>
              </div>
            </fieldset>)}
          </section>

          <section className="admin-card" aria-labelledby="work-heading">
            <div className="admin-section-heading"><div><p className="eyebrow">Portfolio</p><h2 id="work-heading">Selected work</h2></div><button className="secondary-button" type="button" onClick={() => addEntry("selectedWork", { ...newWork })}>Add work</button></div>
            {profile.selectedWork.length === 0 && <p className="admin-empty">No work entries yet.</p>}
            {profile.selectedWork.map((item, index) => <fieldset className="admin-entry" key={`work-${index}`}>
              <legend>Project {index + 1}</legend><button className="remove-button" type="button" onClick={() => removeEntry("selectedWork", index)}>Remove</button>
              <div className="admin-field-grid">
                <label className="admin-field">Title<input required value={item.title} onChange={(e) => updateEntry("selectedWork", index, { title: e.target.value })} /></label>
                <label className="admin-field">Project URL<input type="url" placeholder="https://" value={item.url ?? ""} onChange={(e) => updateEntry("selectedWork", index, { url: e.target.value || null })} /></label>
                <label className="admin-field admin-field-wide">Summary<textarea rows={3} value={item.summary ?? ""} onChange={(e) => updateEntry("selectedWork", index, { summary: e.target.value || null })} /></label>
                <label className="admin-field admin-field-wide">Technologies <span className="field-hint">One per line</span><textarea rows={2} value={item.technologies.join("\n")} onChange={(e) => updateEntry("selectedWork", index, { technologies: splitLines(e.target.value) })} /></label>
              </div>
            </fieldset>)}
          </section>

          <section className="admin-card" aria-labelledby="skills-heading">
            <div className="admin-section-heading"><div><p className="eyebrow">Expertise</p><h2 id="skills-heading">Skills</h2></div><button className="secondary-button" type="button" onClick={() => addEntry("skills", { ...newSkill })}>Add skill</button></div>
            {profile.skills.length === 0 && <p className="admin-empty">No skills yet.</p>}
            <p className="admin-empty">Skills are grouped by category on your resume. Reuse a category name such as “Languages &amp; Technologies” or “Tools” for each skill in that group.</p>
            {profile.skills.map((item, index) => <fieldset className="admin-entry admin-entry-compact" key={`skill-${index}`}>
              <legend>Skill {index + 1}</legend><button className="remove-button" type="button" onClick={() => removeEntry("skills", index)}>Remove</button>
              <div className="admin-field-grid"><label className="admin-field">Name<input required value={item.name} onChange={(e) => updateEntry("skills", index, { name: e.target.value })} /></label><label className="admin-field">Category<input value={item.category ?? ""} onChange={(e) => updateEntry("skills", index, { category: e.target.value || null })} /></label></div>
            </fieldset>)}
          </section>

          <section className="admin-card" aria-labelledby="awards-heading">
            <div className="admin-section-heading"><div><p className="eyebrow">Recognition</p><h2 id="awards-heading">Awards</h2></div><button className="secondary-button" type="button" onClick={() => addEntry("awards", { ...newAward })}>Add award</button></div>
            {profile.awards.length === 0 && <p className="admin-empty">No awards yet.</p>}
            {profile.awards.map((item, index) => <fieldset className="admin-entry" key={`award-${index}`}>
              <legend>Award {index + 1}</legend><button className="remove-button" type="button" onClick={() => removeEntry("awards", index)}>Remove</button>
              <div className="admin-field-grid">
                <label className="admin-field">Award / achievement<input required value={item.title} onChange={(e) => updateEntry("awards", index, { title: e.target.value })} /></label>
                <label className="admin-field">Organization<input value={item.organization ?? ""} onChange={(e) => updateEntry("awards", index, { organization: e.target.value || null })} /></label>
                <label className="admin-field">Date<input placeholder="2015" value={item.date ?? ""} onChange={(e) => updateEntry("awards", index, { date: e.target.value || null })} /></label>
                <label className="admin-field admin-field-wide">Details<textarea rows={2} value={item.description ?? ""} onChange={(e) => updateEntry("awards", index, { description: e.target.value || null })} /></label>
              </div>
            </fieldset>)}
          </section>

          <section className="admin-card" aria-labelledby="education-heading">
            <div className="admin-section-heading"><div><p className="eyebrow">Academic background</p><h2 id="education-heading">Education</h2></div><button className="secondary-button" type="button" onClick={() => addEntry("education", { ...newEducation })}>Add education</button></div>
            {profile.education.length === 0 && <p className="admin-empty">No education entries yet.</p>}
            {profile.education.map((item, index) => <fieldset className="admin-entry" key={`education-${index}`}>
              <legend>Education {index + 1}</legend><button className="remove-button" type="button" onClick={() => removeEntry("education", index)}>Remove</button>
              <div className="admin-field-grid">
                <label className="admin-field">Institution<input required value={item.institution} onChange={(e) => updateEntry("education", index, { institution: e.target.value })} /></label>
                <label className="admin-field">City / region<input value={item.location ?? ""} onChange={(e) => updateEntry("education", index, { location: e.target.value || null })} /></label>
                <label className="admin-field">Degree<input required placeholder="B.S." value={item.degree} onChange={(e) => updateEntry("education", index, { degree: e.target.value })} /></label>
                <label className="admin-field">Field of study<input value={item.fieldOfStudy ?? ""} onChange={(e) => updateEntry("education", index, { fieldOfStudy: e.target.value || null })} /></label>
                <label className="admin-field">Graduation date<input placeholder="May 2013" value={item.graduationDate ?? ""} onChange={(e) => updateEntry("education", index, { graduationDate: e.target.value || null })} /></label>
              </div>
            </fieldset>)}
          </section>

          <section className="admin-card" aria-labelledby="links-heading">
            <div className="admin-section-heading"><div><p className="eyebrow">Elsewhere</p><h2 id="links-heading">Contact &amp; links</h2></div><button className="secondary-button" type="button" onClick={() => addEntry("links", { ...newLink })}>Add link</button></div>
            {profile.links.length === 0 && <p className="admin-empty">No links yet.</p>}
            {profile.links.map((item, index) => <fieldset className="admin-entry admin-entry-compact" key={`link-${index}`}>
              <legend>Link {index + 1}</legend><button className="remove-button" type="button" onClick={() => removeEntry("links", index)}>Remove</button>
              <div className="admin-field-grid"><label className="admin-field">Label<input required value={item.label} onChange={(e) => updateEntry("links", index, { label: e.target.value })} /></label><label className="admin-field">URL<input required type="url" placeholder="https://" value={item.url} onChange={(e) => updateEntry("links", index, { url: e.target.value })} /></label></div>
            </fieldset>)}
          </section>

          <div className="admin-savebar"><p>Save server changes, then publish the updated public snapshot.</p><button className="primary-button" type="submit" disabled={saving}>{saving ? "Saving…" : "Save profile"}<span aria-hidden="true">✓</span></button></div>
        </form>
        </>
      )}
    </main>
  );
}
