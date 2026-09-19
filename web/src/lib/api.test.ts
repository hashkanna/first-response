import { afterEach, describe, expect, it, vi } from 'vitest';
import { approvedArtifact, artifactUrl, hubApi, HUB_HTTP_URL, HUB_WS_URL, type HubStatus } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('hub HTTP boundary', () => {
  it('posts approval with the incident and candidate IDs', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ text: 'Applied verified fix.' }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const controller = new AbortController();
    await expect(hubApi.approve('candidate-3', 'incident-2', controller.signal)).resolves.toEqual({ text: 'Applied verified fix.' });
    expect(fetcher).toHaveBeenCalledWith(`${HUB_HTTP_URL}/approve`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: 'candidate-3', incident_id: 'incident-2' }), signal: controller.signal,
    });
  });

  it('surfaces a rejected operation without turning it into success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'The candidate is not verified.' }), { status: 409 })));
    await expect(hubApi.approve('candidate-1', 'incident-2')).rejects.toThrow('409: The candidate is not verified.');
  });

  it('binds typed commands to the incident visible when they were sent', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ text: 'Approved.' }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    await hubApi.say('apply the verified fix', undefined, 'incident-7');
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ text: 'apply the verified fix', incident_id: 'incident-7' });
  });

  it('surfaces text errors from a proxy', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Hub unavailable', { status: 502 })));
    await expect(hubApi.say('status')).rejects.toThrow('502: Hub unavailable');
  });

  it('rejects malformed success bodies and invalid transcript text', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response('<html>wrong service</html>', { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ text: { invalid: true } }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(hubApi.say('status')).rejects.toThrow('invalid JSON');
    await expect(hubApi.say('status')).rejects.toThrow('invalid text field');
  });

  it('allows empty successful responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(hubApi.resetFault()).resolves.toEqual({});
  });

  it('only links artifacts served by the configured hub', () => {
    expect(artifactUrl('/artifacts/verified.patch')).toBe(`${new URL(HUB_HTTP_URL).origin}/artifacts/verified.patch`);
    expect(artifactUrl('javascript:alert(1)')).toBeNull();
    expect(artifactUrl('https://untrusted.example/fix.patch')).toBeNull();
    expect(HUB_WS_URL).toBe(`${HUB_HTTP_URL.replace(/^http/, 'ws')}/ws`);
  });

  it('restores a voice approval artifact from current status after reconnect', async () => {
    const status: HubStatus = { incident_id: 'incident-7', stage: 'resolved', approval: { approved: true, incident_id: 'incident-7', candidate_id: 'fix-1', artifact_url: '/artifacts/verified.patch' } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(status), { status: 200 })));
    expect(approvedArtifact(await hubApi.status(), 'incident-7')).toEqual({ candidateId: 'fix-1', url: `${new URL(HUB_HTTP_URL).origin}/artifacts/verified.patch` });
    expect(approvedArtifact(status, 'incident-8')).toBeNull();
    expect(approvedArtifact({ ...status, approval: { ...status.approval!, incident_id: 'incident-old' } }, 'incident-7')).toBeNull();
    expect(approvedArtifact({ ...status, approval: { ...status.approval!, approved: false } }, 'incident-7')).toBeNull();
    expect(approvedArtifact({ ...status, approval: { ...status.approval!, artifact_url: 'https://untrusted.example/fix.patch' } }, 'incident-7')).toBeNull();
  });

  it('rejects invalid approval status without creating a download link', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ incident_id: 'incident-7', stage: 'resolved', approval: { approved: 'true' } }), { status: 200 })));
    await expect(hubApi.status()).rejects.toThrow('invalid approval status');
  });
});
