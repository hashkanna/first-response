import { useCallback, useEffect, useRef, useState } from 'react';
import { HUB_HTTP_URL } from './api';
import type { Cue } from './useWarRoom';

export interface GeminiTranscriptEntry {
  id: string;
  role: 'assistant' | 'user';
  text: string;
  at: string;
  source: 'gemini';
}

export interface GeminiReviewRequest {
  requestId: string;
  incidentId: string;
  candidateId: string;
}

const LIVE_URL = `${HUB_HTTP_URL.replace(/^http/, 'ws')}/live`;
type SessionAudio = {
  context: AudioContext;
  stream: MediaStream | null;
  capture: AudioWorkletNode | null;
  input: MediaStreamAudioSourceNode | null;
  mutedOutput: GainNode | null;
};

export function useGeminiLive() {
  const [isConnected, setConnected] = useState(false);
  const [isConnecting, setConnecting] = useState(false);
  const [isListening, setListening] = useState(false);
  const [isSpeaking, setSpeaking] = useState(false);
  const [audioReceivedBytes, setAudioReceivedBytes] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<GeminiTranscriptEntry[]>([]);
  const [latestCue, setLatestCue] = useState<Cue | null>(null);
  const [reviewRequest, setReviewRequest] = useState<GeminiReviewRequest | null>(null);
  const audio = useRef<SessionAudio | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const ready = useRef(false);
  const listening = useRef(false);
  const connectionGeneration = useRef(0);
  const playback = useRef(new Set<AudioBufferSourceNode>());
  const playbackAt = useRef(0);
  const connectTimeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const clearPlayback = useCallback(() => {
    for (const node of playback.current) {
      node.onended = null;
      try { node.stop(); } catch { /* A completed source may already be stopped. */ }
      node.disconnect();
    }
    playback.current.clear();
    playbackAt.current = 0;
    setSpeaking(false);
  }, []);

  const dispose = useCallback(() => {
    connectionGeneration.current += 1;
    clearTimeout(connectTimeout.current);
    ready.current = false;
    listening.current = false;
    const currentSocket = socket.current;
    socket.current = null;
    if (currentSocket) {
      currentSocket.onopen = null;
      currentSocket.onmessage = null;
      currentSocket.onclose = null;
      currentSocket.onerror = null;
      if (currentSocket.readyState === WebSocket.OPEN) currentSocket.send(JSON.stringify({ type: 'disconnect' }));
      currentSocket.close();
    }
    clearPlayback();
    const currentAudio = audio.current;
    audio.current = null;
    if (currentAudio) {
      currentAudio.stream?.getTracks().forEach((track) => track.stop());
      if (currentAudio.capture) currentAudio.capture.port.onmessage = null;
      currentAudio.capture?.disconnect();
      currentAudio.input?.disconnect();
      currentAudio.mutedOutput?.disconnect();
      void currentAudio.context.close().catch(() => undefined);
    }
  }, [clearPlayback]);

  const disconnect = useCallback(() => {
    dispose();
    setConnected(false);
    setConnecting(false);
    setListening(false);
    setSpeaking(false);
    setReviewRequest(null);
  }, [dispose]);

  useEffect(() => () => disconnect(), [disconnect]);

  const queuePlayback = useCallback((pcm: ArrayBuffer) => {
    const context = audio.current?.context;
    if (!context || pcm.byteLength < 2 || pcm.byteLength % 2 !== 0) return;
    const buffer = context.createBuffer(1, pcm.byteLength / 2, 24_000);
    const samples = buffer.getChannelData(0);
    const bytes = new DataView(pcm);
    for (let i = 0; i < samples.length; i++) samples[i] = bytes.getInt16(i * 2, true) / 32768;
    // Bound buffering if a browser suspends playback in the background.
    if (playbackAt.current - context.currentTime > 30) clearPlayback();
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    playback.current.add(source);
    setSpeaking(true);
    source.onended = () => {
      playback.current.delete(source);
      source.disconnect();
      if (playback.current.size === 0) setSpeaking(false);
    };
    const start = Math.max(context.currentTime + 0.02, playbackAt.current);
    source.start(start);
    playbackAt.current = start + buffer.duration;
  }, [clearPlayback]);

  const connect = useCallback(async (options: { microphone?: boolean } = {}) => {
    disconnect();
    setError(null);
    setModel(null);
    setTranscript([]);
    setLatestCue(null);
    setAudioReceivedBytes(0);
    setConnecting(true);
    const generation = connectionGeneration.current;
    try {
      if (typeof AudioContext === 'undefined') throw new Error('This browser does not support live audio. Use the hub text command box.');
      const context = new AudioContext();
      audio.current = { context, stream: null, capture: null, input: null, mutedOutput: null };
      await context.resume();
      if (generation !== connectionGeneration.current) { void context.close().catch(() => undefined); return; }
      if (options.microphone !== false) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
          if (generation !== connectionGeneration.current) { stream.getTracks().forEach((track) => track.stop()); return; }
          audio.current!.stream = stream;
          await context.audioWorklet.addModule('/pcm-capture.worklet.js');
          if (generation !== connectionGeneration.current) return;
          const capture = new AudioWorkletNode(context, 'war-room-pcm-capture', { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1 });
          const input = context.createMediaStreamSource(stream);
          const mutedOutput = context.createGain();
          mutedOutput.gain.value = 0;
          input.connect(capture);
          capture.connect(mutedOutput);
          mutedOutput.connect(context.destination);
          audio.current = { context, stream, capture, input, mutedOutput };
          listening.current = true;
          capture.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
            if (generation !== connectionGeneration.current) return;
            const current = socket.current;
            if (ready.current && listening.current && current?.readyState === WebSocket.OPEN && current.bufferedAmount < 256_000) current.send(event.data);
          };
        } catch (reason) {
          if (generation !== connectionGeneration.current) return;
          audio.current?.stream?.getTracks().forEach((track) => track.stop());
          if (audio.current) audio.current.stream = null;
          listening.current = false;
          const detail = reason instanceof Error && reason.name === 'NotAllowedError' ? 'Microphone permission was denied.' : 'The microphone could not start.';
          setError(`${detail} Gemini can still receive typed messages and speak its replies.`);
        }
      }
      if (generation !== connectionGeneration.current) return;
      const liveSocket = new WebSocket(LIVE_URL);
      liveSocket.binaryType = 'arraybuffer';
      socket.current = liveSocket;
      connectTimeout.current = setTimeout(() => {
        if (!ready.current && generation === connectionGeneration.current) {
          setError('Gemini Live did not connect within 25 seconds. Check the hub credentials and model access.');
          disconnect();
        }
      }, 25_000);
      liveSocket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
        if (generation !== connectionGeneration.current) return;
        if (event.data instanceof ArrayBuffer) {
          const byteLength = event.data.byteLength;
          setAudioReceivedBytes((total) => total + byteLength);
          queuePlayback(event.data);
          return;
        }
        try {
          const payload = JSON.parse(event.data) as Record<string, unknown>;
          if (payload.type === 'ready') {
            clearTimeout(connectTimeout.current);
            ready.current = true;
            setConnected(true);
            setConnecting(false);
            setListening(listening.current);
            setModel(typeof payload.model === 'string' ? payload.model : 'Gemini Live');
          } else if (payload.type === 'transcript' && (payload.role === 'user' || payload.role === 'assistant') && typeof payload.text === 'string' && typeof payload.id === 'string') {
            const id = `${generation}-${payload.id}`;
            setTranscript((entries) => {
              const existing = entries.findIndex((entry) => entry.id === id);
              const next: GeminiTranscriptEntry = { id, role: payload.role as 'user' | 'assistant', text: payload.text as string, at: typeof payload.at === 'string' ? payload.at : new Date().toISOString(), source: 'gemini' };
              if (existing < 0) return [...entries.slice(-199), next];
              const updated = [...entries];
              updated[existing] = { ...entries[existing], text: payload.delta ? entries[existing].text + next.text : next.text };
              return updated;
            });
          } else if (payload.type === 'voice_cue' && ['INTERRUPT', 'WHEN_IDLE', 'SILENT'].includes(String(payload.scheduling)) && typeof payload.facts === 'string') {
            setLatestCue({ scheduling: payload.scheduling as Cue['scheduling'], facts: payload.facts });
          } else if (payload.type === 'interrupted') {
            clearPlayback();
          } else if (payload.type === 'review_requested' && typeof payload.request_id === 'string' && payload.request_id.length > 0 && typeof payload.incident_id === 'string' && payload.incident_id.length > 0 && typeof payload.candidate_id === 'string' && payload.candidate_id.length > 0) {
            setReviewRequest({ requestId: payload.request_id, incidentId: payload.incident_id, candidateId: payload.candidate_id });
          } else if (payload.type === 'reset') {
            setReviewRequest(null);
            setLatestCue(null);
            clearPlayback();
          } else if ((payload.type === 'error' || payload.type === 'notice') && typeof payload.message === 'string') {
            setError(payload.message);
          }
        } catch {
          setError('The Live relay sent an invalid control message.');
        }
      };
      liveSocket.onerror = () => {
        if (generation === connectionGeneration.current) setError('The Live connection failed. Check that the hub is running and Gemini credentials are configured.');
      };
      liveSocket.onclose = () => {
        if (generation !== connectionGeneration.current) return;
        disconnect();
      };
    } catch (reason) {
      if (generation !== connectionGeneration.current) return;
      setError(reason instanceof Error ? reason.message : 'Gemini Live could not start.');
      disconnect();
    }
  }, [disconnect, clearPlayback, queuePlayback]);

  const sendText = useCallback((text: string, incidentId?: string | null): boolean => {
    const clean = text.trim();
    if (!clean) return false;
    if (!ready.current || socket.current?.readyState !== WebSocket.OPEN) { setError('Connect Gemini Live before sending a message into the voice session.'); return false; }
    if (clean.length > 8_000) { setError('Keep Live messages below 8000 characters.'); return false; }
    clearPlayback();
    socket.current.send(JSON.stringify({ type: 'text', text: clean, incident_id: incidentId ?? null }));
    return true;
  }, [clearPlayback]);

  const toggleListening = useCallback(() => {
    if (!ready.current || !audio.current?.capture || !audio.current.stream) { setError('Connect again with microphone access to enable voice input.'); return; }
    listening.current = !listening.current;
    audio.current.capture.port.postMessage({ enabled: listening.current });
    audio.current.stream.getAudioTracks().forEach((track) => { track.enabled = listening.current; });
    if (!listening.current && socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'audio_stream_end' }));
    setListening(listening.current);
  }, []);

  const clearReviewRequest = useCallback(() => setReviewRequest(null), []);

  return { connect, disconnect, sendText, toggleListening, isConnected, isConnecting, isListening, isSpeaking, audioReceivedBytes, error, clearError: () => setError(null), transcript, latestCue, model, reviewRequest, clearReviewRequest };
}
