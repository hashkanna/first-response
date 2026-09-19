import { useEffect, useRef, useState } from 'react';

type RecognitionEvent = { results: { [index: number]: { [index: number]: { transcript: string }; isFinal: boolean }; length: number }; resultIndex: number };
type Recognition = { lang: string; continuous: boolean; interimResults: boolean; onresult: ((event: RecognitionEvent) => void) | null; onerror: ((event: {error: string}) => void) | null; onend: (() => void) | null; start: () => void; stop: () => void; abort: () => void };
type VoiceWindow = Window & { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };

export function useBrowserVoice(onText: (text: string) => void, fact: string | undefined) {
  const [listening, setListening] = useState(false);
  const [spoken, setSpoken] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recognition = useRef<Recognition | null>(null);
  const callback = useRef(onText);
  callback.current = onText;
  const lastFact = useRef<string | undefined>(undefined);
  const speechAvailable = typeof window !== 'undefined' && 'speechSynthesis' in window;
  const voiceWindow = window as VoiceWindow;
  const RecognitionConstructor = voiceWindow.SpeechRecognition ?? voiceWindow.webkitSpeechRecognition;
  const supported = Boolean(RecognitionConstructor);

  useEffect(() => {
    if (!fact || lastFact.current === fact) return;
    lastFact.current = fact;
    if (!spoken || !speechAvailable) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(fact);
    utterance.rate = 1.05;
    window.speechSynthesis.speak(utterance);
  }, [fact, spoken, speechAvailable]);

  useEffect(() => () => { recognition.current?.abort(); if ('speechSynthesis' in window) window.speechSynthesis.cancel(); }, []);

  const toggleListening = () => {
    if (listening) { recognition.current?.stop(); return; }
    if (!RecognitionConstructor) { setVoiceError('Speech recognition is unavailable in this browser. Use the command box below.'); return; }
    setVoiceError(null);
    try {
      const next = new RecognitionConstructor();
      recognition.current = next;
      next.lang = 'en-GB'; next.continuous = false; next.interimResults = false;
      next.onresult = event => { for (let i = event.resultIndex; i < event.results.length; i++) if (event.results[i].isFinal) callback.current(event.results[i][0].transcript); };
      next.onerror = event => { setVoiceError(event.error === 'not-allowed' ? 'Microphone permission was denied. You can still type a command.' : `Microphone stopped (${event.error}). Try again or type a command.`); setListening(false); };
      next.onend = () => setListening(false);
      next.start(); setListening(true);
    } catch { setVoiceError('The microphone could not start. Use the command box instead.'); setListening(false); }
  };
  const toggleSpoken = () => { if (spoken) window.speechSynthesis.cancel(); setSpoken(value => !value); };
  return { listening, spoken, supported, speechAvailable, voiceError, toggleListening, toggleSpoken };
}
