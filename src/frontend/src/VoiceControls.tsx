import { useEffect, useRef, useState } from 'react';
import { Mic, MicOff, Send, Square, Volume2 } from 'lucide-react';
import './styles/voice-controls.css';

type SpeechRecognitionAlternativeLike = { transcript: string };
type SpeechRecognitionResultLike = {
  isFinal: boolean;
  0: SpeechRecognitionAlternativeLike;
};
type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
};
type SpeechRecognitionErrorLike = { error: string };
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorLike) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};
type SpeechRecognitionConstructorLike = new () => SpeechRecognitionLike;
type SpeechWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructorLike;
  webkitSpeechRecognition?: SpeechRecognitionConstructorLike;
};

export type SpeechMode = 'browser' | 'server';
const SILENCE_MS = 1400;

interface VoiceControlsProps {
  /** Current coach question. Recognized text is appended for review before submit. */
  question: string;
  setQuestion: (question: string) => void;
  /** Submit the current question through the host coach session. */
  onSubmit: (question: string) => void;
  /** Disable controls while the coach/game cannot accept input. */
  disabled?: boolean;
  /** Most recent coach response. It is read automatically while auto-read is enabled. */
  latestAssistantText?: string | null;
  /** BCP 47 language tag, for example "en" or "da". */
  language?: string;
  /** Browser-native (default) or backend speech-to-text. */
  sttMode?: SpeechMode;
  /** Browser-native (default) or backend text-to-speech. */
  ttsMode?: SpeechMode;
  /** Transcribe the recorded audio using the configured backend. */
  onServerTranscribe?: (audio: Blob, mimeType: string) => Promise<string>;
  /** Synthesize speech using the configured backend and return playable audio. */
  onServerSpeak?: (text: string) => Promise<Blob>;
}

function messageForRecognitionError(error: string, language: string) {
  const danish = language.toLowerCase().startsWith('da');
  switch (error) {
    case 'not-allowed':
    case 'service-not-allowed':
      return danish ? 'Mikrofonadgang blev afvist.' : 'Microphone access was denied.';
    case 'no-speech':
      return danish ? 'Jeg hørte ingen tale. Prøv igen.' : 'No speech was detected. Try again.';
    case 'audio-capture':
      return danish ? 'Ingen mikrofon blev fundet.' : 'No microphone was found.';
    case 'network':
      return danish ? 'Talegenkendelse kunne ikke oprette forbindelse.' : 'Speech recognition could not connect.';
    default:
      return danish ? 'Talegenkendelse kunne ikke startes.' : 'Speech recognition could not start.';
  }
}

/** Optional browser-native or backend-backed speech controls. */
export function VoiceControls({
  question,
  setQuestion,
  onSubmit,
  disabled = false,
  latestAssistantText,
  language = 'en',
  sttMode = 'browser',
  ttsMode = 'browser',
  onServerTranscribe,
  onServerSpeak,
}: VoiceControlsProps) {
  const [recognitionSupported, setRecognitionSupported] = useState(false);
  const [synthesisSupported, setSynthesisSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [autoRead, setAutoRead] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [error, setError] = useState('');
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const finalTranscriptRef = useRef('');
  const questionRef = useRef(question);
  const listeningRef = useRef(false);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const silenceFrameRef = useRef<number | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const lastAutoReadTextRef = useRef('');

  useEffect(() => {
    questionRef.current = question;
  }, [question]);

  useEffect(() => {
    const speechWindow = window as SpeechWindow;
    setRecognitionSupported(!!(speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition));
    setSynthesisSupported(!!(window.speechSynthesis && window.SpeechSynthesisUtterance));
    return () => {
      listeningRef.current = false;
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      if (silenceFrameRef.current !== null) cancelAnimationFrame(silenceFrameRef.current);
      void audioContextRef.current?.close();
      recognitionRef.current?.abort();
      if (mediaRecorderRef.current) {
        mediaRecorderRef.current.ondataavailable = null;
        mediaRecorderRef.current.onstop = null;
        mediaRecorderRef.current.onerror = null;
        if (mediaRecorderRef.current.state !== 'inactive') mediaRecorderRef.current.stop();
      }
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      audioRef.current?.pause();
      window.speechSynthesis?.cancel();
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    };
  }, []);

  const submitRecognizedSpeech = (spokenText: string) => {
    const spoken = spokenText.trim();
    if (!spoken) return;
    const value = [questionRef.current.trim(), spoken].filter(Boolean).join(' ');
    questionRef.current = '';
    setQuestion('');
    onSubmit(value);
  };

  const resetSilenceTimer = () => {
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    silenceTimerRef.current = setTimeout(stopListening, SILENCE_MS);
  };

  const stopListening = () => {
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    silenceTimerRef.current = null;
    if (silenceFrameRef.current !== null) cancelAnimationFrame(silenceFrameRef.current);
    silenceFrameRef.current = null;
    if (sttMode === 'server') {
      if (mediaRecorderRef.current?.state === 'recording') mediaRecorderRef.current.stop();
      return;
    }
    if (!listeningRef.current) return;
    try {
      recognitionRef.current?.stop();
    } catch {
      listeningRef.current = false;
      setListening(false);
    }
  };

  const startServerRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError(language.toLowerCase().startsWith('da')
        ? 'Lydoptagelse understøttes ikke i denne browser.'
        : 'Audio recording is not supported in this browser.');
      setRecognitionSupported(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!listeningRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      mediaStreamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setError(language.toLowerCase().startsWith('da') ? 'Optagelsen mislykkedes.' : 'Audio recording failed.');
        setListening(false);
        listeningRef.current = false;
        stream.getTracks().forEach((track) => track.stop());
      };
      recorder.onstop = async () => {
        setListening(false);
        listeningRef.current = false;
        if (silenceFrameRef.current !== null) cancelAnimationFrame(silenceFrameRef.current);
        silenceFrameRef.current = null;
        await audioContextRef.current?.close();
        audioContextRef.current = null;
        setTranscribing(true);
        try {
          const mimeType = recorder.mimeType || audioChunksRef.current[0]?.type || 'audio/webm';
          const audio = new Blob(audioChunksRef.current, { type: mimeType });
          if (!audio.size) return;
          if (!onServerTranscribe) throw new Error('Server speech recognition is not configured.');
          const result = (await onServerTranscribe(audio, mimeType)).trim();
          setTranscript(result);
          setInterimTranscript('');
          submitRecognizedSpeech(result);
        } catch (caught) {
          const detail = caught instanceof Error ? caught.message : '';
          setError(detail || (language.toLowerCase().startsWith('da') ? 'Talegenkendelse mislykkedes.' : 'Speech recognition failed.'));
        } finally {
          setTranscribing(false);
          mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
          mediaStreamRef.current = null;
          mediaRecorderRef.current = null;
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      listeningRef.current = true;
      setListening(true);
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      context.createMediaStreamSource(stream).connect(analyser);
      audioContextRef.current = context;
      const samples = new Uint8Array(analyser.fftSize);
      let heardSpeech = false;
      let quietSince = 0;
      const watchSilence = () => {
        if (!listeningRef.current) return;
        analyser.getByteTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, sample) => sum + (sample - 128) ** 2, 0) / samples.length) / 128;
        if (rms > 0.025) {
          heardSpeech = true;
          quietSince = 0;
        } else if (heardSpeech) {
          quietSince ||= Date.now();
          if (Date.now() - quietSince >= SILENCE_MS) {
            stopListening();
            return;
          }
        }
        silenceFrameRef.current = requestAnimationFrame(watchSilence);
      };
      silenceFrameRef.current = requestAnimationFrame(watchSilence);
    } catch (caught) {
      const detail = caught instanceof Error ? caught.message : '';
      setError(detail || messageForRecognitionError('not-allowed', language));
      listeningRef.current = false;
      setListening(false);
    }
  };

  const startBrowserRecognition = () => {
    const speechWindow = window as SpeechWindow;
    const Recognition = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
    if (!Recognition) {
      setRecognitionSupported(false);
      return;
    }
    finalTranscriptRef.current = '';
    const recognition = new Recognition();
    recognition.lang = language;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let interim = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (!result?.[0]?.transcript) continue;
        if (result.isFinal) finalTranscriptRef.current += result[0].transcript;
        else interim += result[0].transcript;
      }
      setTranscript(finalTranscriptRef.current);
      setInterimTranscript(interim);
      if (finalTranscriptRef.current || interim) resetSilenceTimer();
    };
    recognition.onerror = (event) => setError(messageForRecognitionError(event.error, language));
    recognition.onend = () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      listeningRef.current = false;
      setListening(false);
      setInterimTranscript('');
      submitRecognizedSpeech(finalTranscriptRef.current);
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
      listeningRef.current = true;
      setListening(true);
    } catch {
      listeningRef.current = false;
      setListening(false);
      setError(messageForRecognitionError('start-failed', language));
    }
  };

  const startListening = () => {
    if (listeningRef.current) {
      stopListening();
      return;
    }
    if (disabled || transcribing) return;
    setError('');
    setTranscript('');
    setInterimTranscript('');
    listeningRef.current = true;
    setListening(true);
    if (sttMode === 'server') void startServerRecording();
    else startBrowserRecognition();
  };

  const speakLatest = async () => {
    if (!latestAssistantText?.trim() || disabled || speaking) return;
    setError('');
    if (ttsMode === 'server') {
      if (!onServerSpeak) {
        setError(language.toLowerCase().startsWith('da') ? 'Serveroplæsning er ikke konfigureret.' : 'Server speech playback is not configured.');
        return;
      }
      setSpeaking(true);
      try {
        const audioBlob = await onServerSpeak(latestAssistantText);
        if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
        const audioUrl = URL.createObjectURL(audioBlob);
        audioUrlRef.current = audioUrl;
        const player = audioRef.current ?? new Audio();
        audioRef.current = player;
        player.onended = () => setSpeaking(false);
        player.onerror = () => {
          setSpeaking(false);
          setError(language.toLowerCase().startsWith('da') ? 'Afspilning af tale mislykkedes.' : 'Speech playback failed.');
        };
        player.src = audioUrl;
        await player.play();
      } catch (caught) {
        const detail = caught instanceof Error ? caught.message : '';
        setSpeaking(false);
        setError(detail || (language.toLowerCase().startsWith('da') ? 'Talesyntese mislykkedes.' : 'Speech synthesis failed.'));
      }
      return;
    }
    if (!synthesisSupported) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(latestAssistantText);
    utterance.lang = language;
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
  };

  useEffect(() => {
    const text = latestAssistantText?.trim();
    if (!text) return;
    if (!autoRead) {
      lastAutoReadTextRef.current = text;
      return;
    }
    if (disabled || speaking || text === lastAutoReadTextRef.current) return;
    lastAutoReadTextRef.current = text;
    void speakLatest();
  }, [autoRead, disabled, latestAssistantText, speaking, speakLatest]);

  const toggleAutoRead = () => {
    if (autoRead) {
      setAutoRead(false);
      if (speaking) stopSpeaking();
    } else {
      setAutoRead(true);
    }
  };

  const stopSpeaking = () => {
    if (ttsMode === 'server') {
      audioRef.current?.pause();
      if (audioRef.current) audioRef.current.currentTime = 0;
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    } else {
      window.speechSynthesis?.cancel();
    }
    setSpeaking(false);
  };

  const submitQuestion = () => {
    const value = question.trim();
    if (value && !disabled) onSubmit(value);
  };

  const danish = language.toLowerCase().startsWith('da');
  const sttAvailable = sttMode === 'server' ? !!onServerTranscribe && typeof MediaRecorder !== 'undefined' : recognitionSupported;
  const ttsAvailable = ttsMode === 'server' ? !!onServerSpeak : synthesisSupported;
  const spokenText = [transcript, interimTranscript].filter(Boolean).join(' ');

  return (
    <div className="voice-controls" aria-label={danish ? 'Stemmekontrol' : 'Voice controls'}>
      {sttAvailable ? (
        <button
          className={`voice-control-button ${listening ? 'recording' : ''}`}
          type="button"
          disabled={disabled || transcribing}
          aria-pressed={listening}
          onClick={startListening}
          title={listening ? (danish ? 'Klik for at slå mikrofonen fra' : 'Click to mute') : (danish ? 'Klik for at tale' : 'Click to speak')}
        >
          {listening ? <MicOff size={16} /> : <Mic size={16} />}
          <span>{listening ? (danish ? 'Klik for at slå fra' : 'Click to mute') : transcribing ? (danish ? 'Behandler…' : 'Transcribing…') : (danish ? 'Klik for at tale' : 'Click to speak')}</span>
        </button>
      ) : (
        <span className="voice-control-note">
          {sttMode === 'server'
            ? (danish ? 'Serverbaseret talegenkendelse er ikke konfigureret.' : 'Server speech recognition is not configured.')
            : (danish ? 'Talegenkendelse understøttes ikke i denne browser.' : 'Speech recognition is not supported in this browser.')}
        </span>
      )}
      {ttsAvailable && (
        <>
          <button
            className={`voice-control-button ${autoRead ? 'auto-read' : ''}`}
            type="button"
            onClick={toggleAutoRead}
            aria-pressed={autoRead}
            title={autoRead ? (danish ? 'Klik for at slå automatisk oplæsning fra' : 'Click to turn off automatic reading') : (danish ? 'Klik for automatisk at få svar læst op' : 'Click to read replies automatically')}
          >
            <Volume2 size={16} />
            <span>{danish ? 'Læs svar op' : 'Speak reply'}</span>
          </button>
          {speaking && (
            <button className="voice-control-button" type="button" onClick={stopSpeaking}>
              <Square size={14} />
              <span>{danish ? 'Stop' : 'Stop'}</span>
            </button>
          )}
        </>
      )}
      {!ttsAvailable && (
        <span className="voice-control-note">
          {ttsMode === 'server'
            ? (danish ? 'Serverbaseret oplæsning er ikke konfigureret.' : 'Server speech playback is not configured.')
            : (danish ? 'Oplæsning understøttes ikke i denne browser.' : 'Speech playback is not supported in this browser.')}
        </span>
      )}
      {spokenText && (
        <div className="voice-transcript" aria-live="polite">
          <span>{danish ? 'Genkendt tale' : 'Recognized speech'}</span>
          <p>{spokenText}</p>
        </div>
      )}
      {(listening || transcribing) && (
        <span className="voice-control-note" role="status">
          {sttMode === 'server'
            ? (transcribing ? (danish ? 'Talen sendes til transskription.' : 'Sending audio for transcription.') : (danish ? 'Talen optages til serverbaseret genkendelse.' : 'Recording audio for server transcription.'))
            : (danish ? 'Talen behandles af browserens talegenkendelse.' : 'Speech is handled by the browser recognition service.')}
        </span>
      )}
      {error && <span className="voice-control-error" role="status">{error}</span>}
      {question.trim() && (
        <button className="voice-submit-button" type="button" disabled={disabled} onClick={submitQuestion}>
          <Send size={15} />
          <span>{danish ? 'Spørg coachen' : 'Ask coach'}</span>
        </button>
      )}
    </div>
  );
}
