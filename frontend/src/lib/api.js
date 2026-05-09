const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:5000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `API error ${response.status}`);
  }
  return response.json();
}

export const api = {
  imageUrl(projectId, episodeId, pageId) {
    const params = new URLSearchParams({ projectId, episodeId });
    return `${API_BASE}/api/pages/${encodeURIComponent(pageId)}/image?${params}`;
  },
  manualMaskOverlayUrl(projectId, episodeId, maskId) {
    const params = new URLSearchParams({ projectId, episodeId });
    return `${API_BASE}/api/manual-masks/${encodeURIComponent(maskId)}/overlay?${params}`;
  },
  projectCoverUrl(projectId, version = "") {
    const suffix = version ? `?v=${encodeURIComponent(version)}` : "";
    return `${API_BASE}/api/projects/${encodeURIComponent(projectId)}/cover${suffix}`;
  },
  projects: () => request("/api/projects"),
  episodes: (projectId) => request(`/api/projects/${encodeURIComponent(projectId)}/episodes`),
  searchProjectMetadata: (projectId, query) =>
    request(`/api/projects/${encodeURIComponent(projectId)}/metadata/search`, {
      method: "POST",
      body: JSON.stringify({ query, provider: "all" }),
    }),
  fetchProjectMetadata: (projectId, candidate) =>
    request(`/api/projects/${encodeURIComponent(projectId)}/metadata/fetch`, {
      method: "POST",
      body: JSON.stringify(candidate),
    }),
  saveProjectMetadata: (projectId, metadata) =>
    request(`/api/projects/${encodeURIComponent(projectId)}/metadata`, {
      method: "PUT",
      body: JSON.stringify(metadata),
    }),
  openSession: (projectId, episodeId) =>
    request("/api/session/open", {
      method: "POST",
      body: JSON.stringify({ projectId, episodeId }),
    }),
  mergePageWithNext: (session, pageId) =>
    request(`/api/pages/${encodeURIComponent(pageId)}/merge-next`, {
      method: "POST",
      body: JSON.stringify(session),
    }),
  createBox: (session, pageId, bbox, style = {}) =>
    request("/api/boxes", {
      method: "POST",
      body: JSON.stringify({ ...session, pageId, bbox, style }),
    }),
  updateBox: (session, boxId, patch) =>
    request(`/api/boxes/${boxId}`, {
      method: "PATCH",
      body: JSON.stringify({ ...session, patch }),
    }),
  deleteBox: (session, boxId) =>
    request(`/api/boxes/${boxId}`, {
      method: "DELETE",
      body: JSON.stringify(session),
    }),
  restoreBox: (session, boxId) =>
    request(`/api/boxes/${boxId}/restore-original`, {
      method: "POST",
      body: JSON.stringify(session),
    }),
  restoreManualMask: (session, maskId) =>
    request(`/api/manual-masks/${maskId}/restore-original`, {
      method: "POST",
      body: JSON.stringify(session),
    }),
  applyStyle: (session, style, boxIds = null) =>
    request("/api/boxes/apply-style", {
      method: "POST",
      body: JSON.stringify({ ...session, style, boxIds }),
    }),
  jobs: () => request("/api/jobs"),
  fonts: () => request("/api/fonts"),
  fontUrl: (fontId) => `${API_BASE}/api/fonts/${encodeURIComponent(fontId)}/file`,
  uploadFont: async (file, name) => {
    const form = new FormData();
    form.append("font", file);
    form.append("name", name || file.name);
    const response = await fetch(`${API_BASE}/api/fonts/upload`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || `API error ${response.status}`);
    }
    return response.json();
  },
  settings: () => request("/api/settings"),
  saveSettings: (settings) =>
    request("/api/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  runJob: (type, session, extra = {}) =>
    request(`/api/jobs/${type}`, {
      method: "POST",
      body: JSON.stringify({ ...session, ...extra }),
    }),
  manualInpaint: (session, pageId, mask, bbox) =>
    request("/api/jobs/manual-inpaint", {
      method: "POST",
      body: JSON.stringify({ ...session, pageId, mask, bbox }),
    }),
  restoreBrush: (session, pageId, mask, bbox) =>
    request("/api/jobs/restore-brush", {
      method: "POST",
      body: JSON.stringify({ ...session, pageId, mask, bbox }),
    }),
  undo: (session) =>
    request("/api/history/undo", {
      method: "POST",
      body: JSON.stringify(session),
    }),
  redo: (session) =>
    request("/api/history/redo", {
      method: "POST",
      body: JSON.stringify(session),
    }),
};
