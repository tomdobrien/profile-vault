import type { Profile, StoredFileList, UploadInvitation, UploadInviteDetails, UploadUser, SiteSession, PermissionOption } from "./types";
const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development" ? "http://localhost:8001" : "");
let adminSessionToken: string | null = null;
const sessionKey = `profile-session:${apiBaseUrl}`;

function sessionToken(): string | null {
  if (typeof window === "undefined") return null;
  try { return window.sessionStorage.getItem(sessionKey); }
  catch { return adminSessionToken; }
}

function saveSession(token: string | null): void {
  adminSessionToken = token;
  try {
    if (token) window.sessionStorage.setItem(sessionKey, token);
    else window.sessionStorage.removeItem(sessionKey);
  } catch { /* Memory-only sessions remain usable if browser storage is blocked. */ }
  if (typeof window !== "undefined") window.dispatchEvent(new Event("profile-session-change"));
}

function adminAuthorization(): Record<string, string> {
  const token = sessionToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json() as { detail?: string };
    return body.detail || fallback;
  } catch {
    return fallback;
  }
}

export const api = {
  async sendMessage(sender: string, body: string) {
    const response = await fetch(`${apiBaseUrl}/api/contact/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sender, body }),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Message could not be sent."));
  },
  async unreadMessages(): Promise<{ id: number; sender: string; body: string }[]> {
    const response = await fetch(`${apiBaseUrl}/api/admin/contact/messages`, { headers: adminAuthorization(), cache: "no-store" });
    if (!response.ok) throw new Error("Could not load messages.");
    return response.json();
  },
  async markMessageRead(id: number) {
    const response = await fetch(`${apiBaseUrl}/api/admin/contact/messages/${id}/read`, { method: "PUT", headers: adminAuthorization() });
    if (!response.ok) throw new Error("Could not mark message as read.");
  },
  async getPublishedResume(signal: AbortSignal): Promise<Profile> {
    const response = await fetch(`${apiBaseUrl}/api/published-resume`, { cache: "no-store", credentials: "omit", signal });
    if (!response.ok) throw new Error("Resume unavailable");
    return response.json();
  },
  async getProfile(signal?: AbortSignal): Promise<Profile> {
    const response = await fetch(`${apiBaseUrl}/api/profile`, { cache: "no-store", credentials: "omit", headers: adminAuthorization(), signal });
    if (!response.ok) throw new Error(`Profile API returned ${response.status}`);
    return response.json() as Promise<Profile>;
  },
  async updateProfile(profile: Profile): Promise<Profile> {
    const response = await fetch(`${apiBaseUrl}/api/profile`, {
      method: "PUT",
      credentials: "omit",
      headers: { "Content-Type": "application/json", ...adminAuthorization() },
      body: JSON.stringify(profile),
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response, `Profile API returned ${response.status}`));
    }
    return response.json() as Promise<Profile>;
  },
  async uploadPhoto(file: File): Promise<{ filename: string; bytes: number; duplicate: boolean }> {
    if (file.size > 500 * 1024 * 1024) throw new Error("Files must be 500 MB or smaller.");
    const response = await fetch(`${apiBaseUrl}/api/admin/photos`, {
      method: "POST",
      credentials: "omit",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-File-Name": encodeURIComponent(file.name),
        ...adminAuthorization(),
      },
      body: file,
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response, `Upload failed for ${file.name}.`));
    }
    return response.json() as Promise<{ filename: string; bytes: number; duplicate: boolean }>;
  },
  async getAdminSession(): Promise<boolean> {
    if (!sessionToken() || sessionToken()?.startsWith("upload.")) return false;
    const response = await fetch(`${apiBaseUrl}/api/admin/session`, {
      cache: "no-store",
      credentials: "omit",
      headers: adminAuthorization(),
    });
    if (response.status === 401) { saveSession(null); return false; }
    if (!response.ok) throw new Error(await errorMessage(response, "Could not verify admin access."));
    return true;
  },
  async loginAdmin(password: string): Promise<void> {
    const response = await fetch(`${apiBaseUrl}/api/admin/login`, {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Admin login failed."));
    const result = await response.json() as { token?: string };
    if (!result.token) throw new Error("Admin login did not return a session token.");
    saveSession(result.token);
  },
  async logoutAdmin(): Promise<void> {
    saveSession(null);
    const response = await fetch(`${apiBaseUrl}/api/admin/logout`, {
      method: "POST",
      credentials: "omit",
      headers: adminAuthorization(),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not log out."));
  },
  async listUploadUsers(): Promise<UploadUser[]> {
    const response = await fetch(`${apiBaseUrl}/api/admin/upload-users`, { cache: "no-store", credentials: "omit", headers: adminAuthorization() });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not load upload accounts."));
    return response.json() as Promise<UploadUser[]>;
  },
  async listStoredFiles(admin: boolean, userId?: number): Promise<StoredFileList> {
    const query = userId !== undefined ? `?user_id=${userId}` : "";
    const response = await fetch(`${apiBaseUrl}/api/${admin ? "admin" : "upload"}/files${query}`, {
      cache: "no-store", credentials: "omit", headers: adminAuthorization(),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not load files."));
    return response.json() as Promise<StoredFileList>;
  },
  async downloadStoredFile(fileId: string, filename: string, userId?: number): Promise<void> {
    const query = new URLSearchParams({ file_id: fileId });
    if (userId !== undefined) query.set("user_id", String(userId));
    const response = await fetch(`${apiBaseUrl}/api/admin/files/download?${query}`, {
      cache: "no-store", credentials: "omit", headers: adminAuthorization(),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not download this file."));
    // Download as an attachment; uploaded HTML/SVG must never execute on the site.
    const url = URL.createObjectURL(new Blob([await response.arrayBuffer()], { type: "application/octet-stream" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  },
  async getImagePreview(fileId: string, userId?: number, thumbnail = false, signal?: AbortSignal): Promise<Blob> {
    const query = new URLSearchParams({ file_id: fileId, thumbnail: String(thumbnail) });
    if (userId !== undefined) query.set("user_id", String(userId));
    const response = await fetch(`${apiBaseUrl}/api/files/image?${query}`, {
      cache: "no-store", credentials: "omit", headers: adminAuthorization(), signal,
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not load this image preview."));
    return response.blob();
  },
  async getVideoPreview(fileId: string, userId?: number, signal?: AbortSignal): Promise<{ url: string; expiresAt: number; optimized: boolean; preparing: boolean }> {
    const response = await fetch(`${apiBaseUrl}/api/files/video-ticket`, {
      method: "POST", cache: "no-store", credentials: "omit", signal,
      headers: { "Content-Type": "application/json", ...adminAuthorization() },
      body: JSON.stringify({ file_id: fileId, user_id: userId ?? null }),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not start video playback."));
    const result = await response.json() as { ticket: string; expiresAt: number; optimized: boolean; preparing: boolean };
    return { url: `${apiBaseUrl}/api/files/video?${new URLSearchParams({ ticket: result.ticket })}`, expiresAt: result.expiresAt,
      optimized: result.optimized, preparing: result.preparing };
  },
  async getTextPreview(fileId: string, userId?: number, signal?: AbortSignal): Promise<{ text: string; truncated: boolean }> {
    const query = new URLSearchParams({ file_id: fileId }); if (userId !== undefined) query.set("user_id", String(userId));
    const response = await fetch(`${apiBaseUrl}/api/files/text?${query}`, { cache: "no-store", credentials: "omit", headers: adminAuthorization(), signal });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not load this text preview."));
    return response.json();
  },
  async getPdfPreview(fileId: string, userId?: number, signal?: AbortSignal): Promise<Blob> {
    const query = new URLSearchParams({ file_id: fileId }); if (userId !== undefined) query.set("user_id", String(userId));
    const response = await fetch(`${apiBaseUrl}/api/files/pdf?${query}`, { cache: "no-store", credentials: "omit", headers: adminAuthorization(), signal });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not load this PDF preview.")); return response.blob();
  },
  async listUploadInvitations(): Promise<UploadInvitation[]> {
    const response = await fetch(`${apiBaseUrl}/api/admin/invitations`, { cache: "no-store", credentials: "omit", headers: adminAuthorization() });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not load invitations."));
    return response.json() as Promise<UploadInvitation[]>;
  },
  async createUploadInvitation(email: string, displayName: string, permissions: string[]): Promise<{ id: number; email: string; token: string; expiresAt: string }> {
    const response = await fetch(`${apiBaseUrl}/api/admin/invitations`, {
      method: "POST", credentials: "omit", headers: { "Content-Type": "application/json", ...adminAuthorization() },
      body: JSON.stringify({ email, display_name: displayName || null, permissions }),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not create invitation."));
    return response.json();
  },
  async revokeUploadInvitation(id: number): Promise<void> {
    const response = await fetch(`${apiBaseUrl}/api/admin/invitations/${id}/revoke`, { method: "POST", credentials: "omit", headers: adminAuthorization() });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not revoke invitation."));
  },
  async disableUploadUser(id: number): Promise<void> {
    const response = await fetch(`${apiBaseUrl}/api/admin/upload-users/${id}/disable`, { method: "POST", credentials: "omit", headers: adminAuthorization() });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not disable account."));
  },
  async getUploadInvite(token: string): Promise<UploadInviteDetails> {
    const response = await fetch(`${apiBaseUrl}/api/upload/invitations/validate`, {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "This invitation is invalid, expired, or already used."));
    return response.json() as Promise<UploadInviteDetails>;
  },
  async acceptUploadInvite(token: string, password: string): Promise<void> {
    const response = await fetch(`${apiBaseUrl}/api/upload/invitations/accept`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, password }),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not accept this invitation."));
  },
  async loginUploadUser(email: string, password: string): Promise<{ email: string; displayName: string | null }> {
    const response = await fetch(`${apiBaseUrl}/api/upload/login`, {
      method: "POST", credentials: "omit", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Upload sign in failed."));
    const result = await response.json() as { token?: string; email: string; displayName: string | null };
    if (!result.token) throw new Error("Upload sign in did not return a session token.");
    saveSession(result.token);
    return { email: result.email, displayName: result.displayName };
  },
  async getUploadSession(): Promise<{ email: string; displayName: string | null } | null> {
    if (!sessionToken()?.startsWith("upload.")) return null;
    const response = await fetch(`${apiBaseUrl}/api/upload/session`, { cache: "no-store", credentials: "omit", headers: adminAuthorization() });
    if (response.status === 401) { saveSession(null); return null; }
    if (!response.ok) throw new Error(await errorMessage(response, "Could not verify upload access."));
    return response.json() as Promise<{ email: string; displayName: string | null }>;
  },
  clearUploadSession(): void { saveSession(null); },
  async getSiteSession(signal?: AbortSignal): Promise<SiteSession | null> {
    if (!sessionToken()) return null;
    const response = await fetch(`${apiBaseUrl}/api/session`, { cache: "no-store", credentials: "omit", headers: adminAuthorization(), signal });
    if (response.status === 401) { saveSession(null); return null; }
    if (!response.ok) throw new Error(await errorMessage(response, "Could not verify site access."));
    return response.json();
  },
  async getPublicAccess(signal?: AbortSignal): Promise<{ permissions: string[] }> {
    const response = await fetch(`${apiBaseUrl}/api/access`, { cache: "no-store", credentials: "omit", signal });
    if (!response.ok) throw new Error("The server is unavailable.");
    return response.json();
  },
  async getPermissionOptions(): Promise<PermissionOption[]> {
    const response = await fetch(`${apiBaseUrl}/api/admin/permissions`, { cache: "no-store", credentials: "omit", headers: adminAuthorization() });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not load permissions."));
    return response.json();
  },
  async setUserPermissions(id: number, permissions: string[]): Promise<void> {
    const response = await fetch(`${apiBaseUrl}/api/admin/upload-users/${id}/permissions`, {
      method: "PUT", credentials: "omit", headers: { "Content-Type": "application/json", ...adminAuthorization() }, body: JSON.stringify({ permissions }),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not save permissions."));
  },
  async setPublicPermissions(permissions: string[]): Promise<void> {
    const response = await fetch(`${apiBaseUrl}/api/admin/public-access`, {
      method: "PUT", credentials: "omit", headers: { "Content-Type": "application/json", ...adminAuthorization() }, body: JSON.stringify({ permissions }),
    });
    if (!response.ok) throw new Error(await errorMessage(response, "Could not save visitor access."));
    window.dispatchEvent(new Event("profile-session-change"));
  },
};
