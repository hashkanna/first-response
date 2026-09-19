import { useCallback, useEffect, useRef, useState } from 'react';
import type { IncidentUpdate } from './contracts';
import { createInitialState, getVerifiedCandidates, parseIncidentUpdate, reduceIncident } from './incident';
import { approvedArtifact, artifactUrl, hubApi, HUB_WS_URL, type DemoFault, type HubResponse } from './api';

export type WarRoomMode = 'demo' | 'live';
export type ConnectionState = 'demo' | 'connecting' | 'connected' | 'disconnected';
export interface TranscriptEntry {
  id: string;
  role: 'assistant' | 'user';
  text: string;
  at: string;
  source: 'demo' | 'live' | 'operator';
}
export interface Cue {
  scheduling: 'INTERRUPT' | 'WHEN_IDLE' | 'SILENT';
  facts: string;
}

type PendingAction = 'say' | 'approve' | 'fault' | 'reset' | 'demo' | null;
interface Replay {
  events: IncidentUpdate[];
  offsets: number[];
  next: number;
  elapsed: number;
  duration: number;
  base: number;
  previousTick: number;
  playing: boolean;
}

const DEMO_DURATION_MS = 45_000;
const SPOKEN_STAGES = new Set(['alerted', 'cause_found', 'reproduced', 'fix_verified', 'no_fix_found', 'pr_opened']);
const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'The request failed.';
const aborted = (error: unknown) => error instanceof DOMException && error.name === 'AbortError';

function factualReply(text: string, state: ReturnType<typeof createInitialState>): string {
  if (!state.stage) return 'No incident has started. Run a recorded scenario to inspect its evidence and verification results.';
  const lower = text.toLowerCase();
  if (/cause|why|broke|happen/.test(lower)) {
    return state.rootCause?.explanation || 'The investigation has not reported a root cause yet. No cause is confirmed.';
  }
  if (/evidence|trace|log|diff/.test(lower)) {
    return state.evidence.length
      ? state.evidence.map((item) => item.summary).join(' ')
      : 'No evidence has been reported yet.';
  }
  if (/tried|candidate|test|fix|approv|pull request|\bpr\b/.test(lower)) {
    const verified = getVerifiedCandidates(state);
    if (verified.length) {
      const candidate = verified[0];
      const result = state.results.find((item) => item.candidate_id === candidate.candidate_id)!;
      return `Recorded result: ${candidate.title}. The patch applied, the reproduction passed, and the suite passed (${result.tests_run} tests, ${result.tests_failed} failed). You can review the verified diff. This replay does not apply a fix or open a pull request.`;
    }
    if (state.stage === 'no_fix_found') return 'No candidate passed all verification checks. No fix is available for approval.';
    return state.candidates.length
      ? `${state.candidates.length} candidates have been proposed. None has passed all verification checks yet.`
      : 'No fix candidates have been reported yet.';
  }
  return state.updates.at(-1)?.message || 'The investigation has started. No further milestone has been reported.';
}

export function useWarRoom() {
  const [mode, setModeState] = useState<WarRoomMode>('demo');
  const [state, setState] = useState(createInitialState);
  const stateRef = useRef(state);
  stateRef.current = state;
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const [connection, setConnection] = useState<ConnectionState>('demo');
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [latestCue, setLatestCue] = useState<Cue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState<PendingAction>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [now, setNow] = useState(Date.now);
  const [demoFault, setDemoFault] = useState<DemoFault>('bad_config');
  const [approvedCandidateId, setApprovedCandidateId] = useState<string | null>(null);
  const [approvedArtifactUrl, setApprovedArtifactUrl] = useState<string | null>(null);
  const replay = useRef<Replay | null>(null);
  const requests = useRef(new Set<AbortController>());
  const generation = useRef(0);
  const transcriptCounter = useRef(0);

  const addTranscript = useCallback((role: TranscriptEntry['role'], text: string, source: TranscriptEntry['source'], at = new Date().toISOString()) => {
    setTranscript((entries) => [...entries.slice(-199), { id: `transcript-${++transcriptCounter.current}`, role, text, source, at }]);
  }, []);

  const resetView = useCallback(() => {
    const empty = createInitialState();
    stateRef.current = empty;
    setState(empty);
    setTranscript([]);
    setLatestCue(null);
    setApprovedCandidateId(null);
    setApprovedArtifactUrl(null);
    setError(null);
    setActionMessage(null);
  }, []);

  const cancelRequests = useCallback(() => {
    generation.current += 1;
    requests.current.forEach((controller) => controller.abort());
    requests.current.clear();
    setActionPending(null);
  }, []);

  const ingest = useCallback((event: IncidentUpdate, recorded: boolean) => {
    // Update the ref immediately so two messages in the same frame see the latest state.
    const next = reduceIncident(stateRef.current, event);
    const accepted = next !== stateRef.current;
    if (next.incidentId !== stateRef.current.incidentId) {
      setApprovedCandidateId(null);
      setApprovedArtifactUrl(null);
    }
    stateRef.current = next;
    setState(next);
    if (recorded && accepted && SPOKEN_STAGES.has(event.stage)) {
      addTranscript('assistant', event.message, 'demo', event.at);
      setLatestCue({ scheduling: event.stage === 'reproduced' || event.stage === 'pr_opened' ? 'WHEN_IDLE' : 'INTERRUPT', facts: event.message });
    }
  }, [addTranscript]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const current = replay.current;
      if (modeRef.current === 'demo' && current) {
        const tick = performance.now();
        if (current.playing) current.elapsed = Math.min(current.duration, current.elapsed + tick - current.previousTick);
        current.previousTick = tick;
        while (current.playing && current.next < current.events.length && current.offsets[current.next] <= current.elapsed) {
          const index = current.next++;
          ingest({ ...current.events[index], at: new Date(current.base + current.offsets[index]).toISOString() }, true);
        }
        setNow(current.base + current.elapsed);
        setProgress(current.duration ? current.elapsed / current.duration : 1);
        if (current.next === current.events.length && current.playing) {
          current.playing = false;
          setIsPlaying(false);
        }
      } else {
        setNow(Date.now());
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [ingest]);

  useEffect(() => {
    if (mode !== 'live') return;
    let closed = false;
    let socket: WebSocket | null = null;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;

    const connect = () => {
      if (closed || modeRef.current !== 'live') return;
      setConnection('connecting');
      try {
        socket = new WebSocket(HUB_WS_URL);
      } catch (reason) {
        setConnection('disconnected');
        setError(`Cannot open the hub connection: ${errorMessage(reason)}`);
        return;
      }
      const currentSocket = socket;
      currentSocket.onopen = () => {
        if (closed || modeRef.current !== 'live' || socket !== currentSocket) return;
        attempts = 0;
        setConnection('connected');
      };
      currentSocket.onmessage = (message) => {
        if (closed || modeRef.current !== 'live' || socket !== currentSocket) return;
        try {
          const payload: unknown = JSON.parse(message.data);
          if (!payload || typeof payload !== 'object') throw new Error('Invalid hub message.');
          const envelope = payload as Record<string, unknown>;
          if (envelope.type === 'reset') {
            resetView();
            return;
          }
          if (envelope.type === 'transcript') {
            if ((envelope.role !== 'assistant' && envelope.role !== 'user') || typeof envelope.text !== 'string') throw new Error('Invalid transcript message.');
            addTranscript(envelope.role, envelope.text, 'live', typeof envelope.at === 'string' ? envelope.at : undefined);
            return;
          }
          if (envelope.type === 'voice_cue') {
            if (!['INTERRUPT', 'WHEN_IDLE', 'SILENT'].includes(String(envelope.scheduling)) || typeof envelope.facts !== 'string') throw new Error('Invalid voice cue.');
            setLatestCue({ scheduling: envelope.scheduling as Cue['scheduling'], facts: envelope.facts });
            return;
          }
          const event = parseIncidentUpdate(envelope.type === 'incident_update' ? envelope.update ?? payload : payload);
          if (event) ingest(event, false);
          else if ('incident_id' in envelope || envelope.type === 'incident_update') throw new Error('The hub sent an invalid incident event.');
        } catch (reason) {
          setError(errorMessage(reason));
        }
      };
      currentSocket.onerror = () => currentSocket.close();
      currentSocket.onclose = () => {
        if (closed || modeRef.current !== 'live' || socket !== currentSocket) return;
        setConnection('disconnected');
        const delay = Math.min(15_000, 1_000 * 2 ** Math.min(attempts++, 4));
        reconnect = setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(reconnect);
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        socket.close();
      }
    };
  }, [mode, addTranscript, ingest, resetView]);

  useEffect(() => () => {
    requests.current.forEach((controller) => controller.abort());
    requests.current.clear();
  }, []);

  useEffect(() => {
    if (mode !== 'live' || connection !== 'connected' || !state.incidentId || !['resolved', 'pr_opened'].includes(state.stage || '')) return;
    const incidentId = state.incidentId;
    const activeGeneration = generation.current;
    const controller = new AbortController();
    requests.current.add(controller);
    void hubApi.status(controller.signal).then((status) => {
      if (controller.signal.aborted || activeGeneration !== generation.current || modeRef.current !== 'live' || stateRef.current.incidentId !== incidentId) return;
      const approval = approvedArtifact(status, incidentId);
      if (!approval || !getVerifiedCandidates(stateRef.current).some((candidate) => candidate.candidate_id === approval.candidateId)) return;
      setApprovedCandidateId(approval.candidateId);
      setApprovedArtifactUrl(approval.url);
    }).catch((reason: unknown) => {
      if (!aborted(reason) && !controller.signal.aborted && activeGeneration === generation.current && modeRef.current === 'live' && stateRef.current.incidentId === incidentId) setError(errorMessage(reason));
    }).finally(() => requests.current.delete(controller));
    return () => {
      controller.abort();
      requests.current.delete(controller);
    };
  }, [mode, connection, state.incidentId, state.stage]);

  const setMode = useCallback((nextMode: WarRoomMode) => {
    if (modeRef.current === nextMode) return;
    cancelRequests();
    replay.current = null;
    setIsPlaying(false);
    setProgress(0);
    resetView();
    modeRef.current = nextMode;
    setModeState(nextMode);
    setConnection(nextMode === 'demo' ? 'demo' : 'connecting');
    setNow(Date.now());
  }, [cancelRequests, resetView]);

  const startDemo = useCallback(async (fault: DemoFault = 'bad_config') => {
    if (modeRef.current !== 'demo') return;
    cancelRequests();
    replay.current = null;
    setIsPlaying(false);
    setProgress(0);
    resetView();
    setDemoFault(fault);
    setActionPending('demo');
    const controller = new AbortController();
    requests.current.add(controller);
    const activeGeneration = generation.current;
    try {
      const response = await fetch(fault === 'null_error' ? '/sample_null_events.json' : '/sample_events.json', { signal: controller.signal });
      if (!response.ok) throw new Error(`Recorded scenario could not be loaded (${response.status}).`);
      const payload: unknown = await response.json();
      if (!Array.isArray(payload) || payload.length === 0) throw new Error('Recorded scenario is empty or malformed.');
      const events = payload.map(parseIncidentUpdate);
      if (events.some((event) => !event)) throw new Error('Recorded scenario contains an invalid incident event.');
      const validEvents = events as IncidentUpdate[];
      // A recorded scenario ends at verification; it cannot manufacture a pull request.
      if (validEvents.some((event) => event.pr_url || event.stage === 'pr_opened')) throw new Error('Recorded scenarios must not contain pull request claims.');
      validEvents.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
      const firstTime = Date.parse(validEvents[0].at);
      const span = Date.parse(validEvents.at(-1)!.at) - firstTime;
      const offsets = validEvents.map((event, index) => span > 0
        ? Math.round(((Date.parse(event.at) - firstTime) / span) * DEMO_DURATION_MS)
        : (index / Math.max(1, validEvents.length - 1)) * DEMO_DURATION_MS);
      if (controller.signal.aborted || activeGeneration !== generation.current) return;
      const base = Date.now();
      replay.current = { events: validEvents, offsets, next: 0, elapsed: 0, duration: offsets.at(-1) || 0, base, previousTick: performance.now(), playing: true };
      setNow(base);
      setIsPlaying(true);
      setActionMessage('Recorded scenario running. No live investigation or sandbox is connected in demo mode.');
    } catch (reason) {
      if (!aborted(reason) && activeGeneration === generation.current) setError(errorMessage(reason));
    } finally {
      requests.current.delete(controller);
      if (activeGeneration === generation.current) setActionPending(null);
    }
  }, [cancelRequests, resetView]);

  const pauseDemo = useCallback(() => {
    if (!replay.current) return;
    replay.current.playing = false;
    setIsPlaying(false);
  }, []);

  const resumeDemo = useCallback(() => {
    const current = replay.current;
    if (!current || current.next === current.events.length) return;
    current.previousTick = performance.now();
    current.playing = true;
    setIsPlaying(true);
  }, []);

  const resetDemo = useCallback(() => {
    cancelRequests();
    replay.current = null;
    setIsPlaying(false);
    setProgress(0);
    resetView();
    setNow(Date.now());
  }, [cancelRequests, resetView]);

  const request = useCallback(async (action: Exclude<PendingAction, null | 'demo'>, operation: (signal: AbortSignal) => Promise<HubResponse>, onSuccess: (result: HubResponse) => void) => {
    const controller = new AbortController();
    requests.current.add(controller);
    const activeGeneration = generation.current;
    setError(null);
    setActionMessage(null);
    setActionPending(action);
    try {
      const result = await operation(controller.signal);
      if (!controller.signal.aborted && activeGeneration === generation.current) onSuccess(result);
    } catch (reason) {
      if (!aborted(reason) && activeGeneration === generation.current) setError(errorMessage(reason));
    } finally {
      requests.current.delete(controller);
      if (activeGeneration === generation.current) setActionPending(null);
    }
  }, []);

  const sendMessage = useCallback(async (text: string) => {
    const clean = text.trim();
    if (!clean) return;
    addTranscript('user', clean, 'operator');
    if (modeRef.current === 'demo') {
      addTranscript('assistant', factualReply(clean, stateRef.current), 'demo');
      return;
    }
    const incidentId = stateRef.current.incidentId;
    await request('say', (signal) => hubApi.say(clean, signal, incidentId), (result) => {
      if (typeof result.text === 'string') addTranscript('assistant', result.text, 'live');
      setActionMessage(result.text ? null : result.message || 'Message sent to the hub.');
    });
  }, [addTranscript, request]);

  const approveFix = useCallback(async (candidateId: string, reviewedIncidentId?: string | null) => {
    const current = stateRef.current;
    if (reviewedIncidentId !== undefined && reviewedIncidentId !== current.incidentId) {
      setError('This review belongs to an earlier incident. Review the current repair again.');
      return;
    }
    if (!current.incidentId || !getVerifiedCandidates(current).some((candidate) => candidate.candidate_id === candidateId)) {
      setError('This candidate has not passed patch application, reproduction, and suite verification.');
      return;
    }
    if (modeRef.current === 'demo') {
      setApprovedCandidateId(candidateId);
      setActionMessage('Verified recorded diff selected for review. Demo mode does not apply changes or create a pull request.');
      return;
    }
    await request('approve', (signal) => hubApi.approve(candidateId, current.incidentId!, signal), (result) => {
      if (stateRef.current.incidentId !== current.incidentId) return;
      setApprovedCandidateId(candidateId);
      if (typeof result.artifact_url === 'string') setApprovedArtifactUrl(artifactUrl(result.artifact_url));
      setActionMessage(result.text || result.message || 'Approval accepted by the hub.');
    });
  }, [request]);

  const applyFault = useCallback(async (fault: DemoFault) => {
    if (modeRef.current === 'demo') return startDemo(fault);
    await request('fault', (signal) => hubApi.applyFault(fault, signal), (result) => {
      setActionMessage(result.message || `${fault === 'bad_config' ? 'Payment timeout' : 'Missing coupon'} fault applied. The hub investigation is running.`);
    });
  }, [request, startDemo]);

  const resetFault = useCallback(async () => {
    if (modeRef.current === 'demo') return resetDemo();
    await request('reset', (signal) => hubApi.resetFault(signal), (result) => {
      resetView();
      setActionMessage(result.message || 'Shop reset to its healthy state.');
    });
  }, [request, resetDemo, resetView]);

  return {
    state, mode, setMode, connection, isPlaying, startDemo, pauseDemo, resumeDemo, resetDemo,
    sendMessage, transcript, error, clearError: () => setError(null), now, progress,
    approveFix, approvedCandidateId, approvedArtifactUrl, applyFault, resetFault,
    actionPending, actionMessage, latestCue, demoFault,
  };
}
