/** Public hub address only. Provider credentials belong on the server. */
const configuredHub = import.meta.env.VITE_HUB_URL?.trim() || 'http://localhost:8000';

function hubBase(value: string): URL {
  const url = new URL(value);
  if (url.protocol === 'ws:') url.protocol = 'http:';
  if (url.protocol === 'wss:') url.protocol = 'https:';
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('VITE_HUB_URL must be an HTTP(S) or WS(S) address without credentials.');
  }
  url.search = '';
  url.hash = '';
  url.pathname = url.pathname.replace(/\/+$/, '');
  return url;
}

export const HUB_HTTP_URL = hubBase(configuredHub).toString().replace(/\/$/, '');
export const HUB_WS_URL = `${HUB_HTTP_URL.replace(/^http/, 'ws')}/ws`;

export type DemoFault = 'bad_config' | 'null_error';

export interface HubResponse {
  text?: string;
  message?: string;
  role?: string;
  artifact_url?: string;
  candidate_id?: string;
  incident_id?: string;
  fault?: string;
  mode?: string;
  ok?: boolean;
}

export interface HubStatus {
  incident_id: string | null;
  stage: string | null;
  approval: {
    approved: boolean;
    incident_id: string;
    candidate_id: string;
    artifact_url: string;
  } | null;
}

export function artifactUrl(path: string): string | null {
  try {
    const url = new URL(path, `${HUB_HTTP_URL}/`);
    // Only hub-hosted artifacts are linked; a server response cannot inject script URLs.
    return url.origin === new URL(HUB_HTTP_URL).origin ? url.toString() : null;
  } catch {
    return null;
  }
}

/** Bind reconnect/voice approvals to the incident currently visible in the UI. */
export function approvedArtifact(status: HubStatus, incidentId: string): { candidateId: string; url: string } | null {
  const approval = status.approval;
  if (status.incident_id !== incidentId || !approval?.approved || approval.incident_id !== incidentId) return null;
  const url = artifactUrl(approval.artifact_url);
  return url ? { candidateId: approval.candidate_id, url } : null;
}

async function getStatus(signal?: AbortSignal): Promise<HubStatus> {
  const response = await fetch(`${HUB_HTTP_URL}/status`, { signal, cache: 'no-store' });
  if (!response.ok) throw new Error(`Could not refresh approval status (${response.status}).`);
  const payload: unknown = await response.json();
  if (!payload || typeof payload !== 'object') throw new Error('The hub returned an invalid status.');
  const status = payload as Record<string, unknown>;
  if ((status.incident_id !== null && typeof status.incident_id !== 'string') || (status.stage !== null && typeof status.stage !== 'string')) throw new Error('The hub returned an invalid incident status.');
  const approval = status.approval;
  if (approval !== null) {
    if (!approval || typeof approval !== 'object') throw new Error('The hub returned an invalid approval status.');
    const fields = approval as Record<string, unknown>;
    if (typeof fields.approved !== 'boolean' || ['incident_id', 'candidate_id', 'artifact_url'].some((field) => typeof fields[field] !== 'string')) throw new Error('The hub returned an invalid approval status.');
  }
  return { incident_id: status.incident_id, stage: status.stage, approval } as HubStatus;
}

async function post(path: string, body: unknown, signal?: AbortSignal): Promise<HubResponse> {
  const response = await fetch(`${HUB_HTTP_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  const raw = await response.text();
  let payload: unknown = null;
  if (raw) {
    try { payload = JSON.parse(raw); } catch {
      if (response.ok) throw new Error('The hub returned invalid JSON.');
      // Preserve plain-text error responses from a reverse proxy below.
    }
  }
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' && 'detail' in payload
      ? (payload as { detail: unknown }).detail
      : raw;
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail);
    throw new Error(`Hub returned ${response.status}${message ? `: ${message.slice(0, 300)}` : ''}`);
  }
  if (payload === null) return {};
  if (typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('The hub returned an unexpected response.');
  }
  for (const field of ['text', 'message', 'role', 'artifact_url', 'candidate_id', 'incident_id', 'fault', 'mode']) {
    const value = (payload as Record<string, unknown>)[field];
    if (value !== undefined && typeof value !== 'string') throw new Error(`The hub returned an invalid ${field} field.`);
  }
  return payload as HubResponse;
}

export const hubApi = {
  status: getStatus,
  say: (text: string, signal?: AbortSignal, incidentId?: string | null) => post('/say', { text, incident_id: incidentId ?? null }, signal),
  applyFault: (fault: DemoFault, signal?: AbortSignal) => post(`/faults/${fault}/apply`, {}, signal),
  resetFault: (signal?: AbortSignal) => post('/faults/reset', {}, signal),
  approve: (candidateId: string, incidentId: string, signal?: AbortSignal) =>
    post('/approve', { candidate_id: candidateId, incident_id: incidentId }, signal),
};
