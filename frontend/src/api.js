/**
 * API client.
 *
 * The single most important rule of this demo: every request carries the
 * CURRENTLY selected workspace in the X-Workspace-Id header. There is no
 * session-bound workspace on the server. Switching the workspace in the UI
 * only changes this header for requests issued *after* the switch; tasks
 * already created keep running with the workspace captured at creation.
 */

const WORKSPACE_KEY = 'demo.currentWorkspaceId'

export function getStoredWorkspaceId() {
  return localStorage.getItem(WORKSPACE_KEY)
}

export function setStoredWorkspaceId(id) {
  localStorage.setItem(WORKSPACE_KEY, id)
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
    this.detail = detail
  }
}

async function request(path, { workspaceId, ...options } = {}) {
  if (!workspaceId) {
    throw new ApiError(400, '尚未选择工作区')
  }
  const res = await fetch(path, {
    ...options,
    headers: {
      ...(options.headers || {}),
      'X-Workspace-Id': workspaceId,
    },
  })
  const contentType = res.headers.get('content-type') || ''
  if (!res.ok) {
    let detail
    try {
      detail = contentType.includes('application/json')
        ? (await res.json()).detail
        : await res.text()
    } catch {
      detail = res.statusText
    }
    throw new ApiError(res.status, detail)
  }
  if (contentType.includes('application/json')) {
    return res.json()
  }
  return res
}

export const api = {
  workspaces: () => fetch('/api/workspaces').then((r) => r.json()),

  preview: (workspaceId, file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/imports/preview', {
      method: 'POST',
      workspaceId,
      body: form,
    })
  },

  createImport: (workspaceId, { requestId, mapping, file }) => {
    const form = new FormData()
    form.append('request_id', requestId)
    form.append('mapping', JSON.stringify(mapping))
    form.append('file', file)
    return request('/api/imports', {
      method: 'POST',
      workspaceId,
      body: form,
    })
  },

  listImports: (workspaceId) =>
    request('/api/imports', { workspaceId }),

  getImport: (workspaceId, taskId) =>
    request(`/api/imports/${taskId}`, { workspaceId }),

  cancelImport: (workspaceId, taskId) =>
    request(`/api/imports/${taskId}/cancel`, {
      method: 'POST',
      workspaceId,
    }),

  deleteImport: (workspaceId, taskId) =>
    request(`/api/imports/${taskId}`, {
      method: 'DELETE',
      workspaceId,
    }),

  listRecords: (workspaceId, businessKey) => {
    const qs = businessKey ? `?business_key=${encodeURIComponent(businessKey)}` : ''
    return request(`/api/records${qs}`, { workspaceId })
  },

  // Downloads must also carry the workspace header; use a blob fetch so the
  // browser does not silently drop it (a plain <a href> cannot set headers).
  downloadUrl: async (workspaceId, path) => {
    const res = await request(path, { workspaceId })
    return URL.createObjectURL(await res.blob())
  },
}
