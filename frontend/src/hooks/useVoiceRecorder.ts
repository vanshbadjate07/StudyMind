import { useCallback, useEffect, useRef, useState } from "react";

export type RecorderState = "idle" | "recording" | "stopping";

/** Longest single answer we will record. A cap is needed because the
 * transcription backend rejects oversized uploads, and discovering that
 * after a four-minute answer loses the whole answer. */
export const MAX_RECORDING_SECONDS = 180;

interface UseVoiceRecorderResult {
  state: RecorderState;
  seconds: number;
  error: string | null;
  start: () => Promise<void>;
  stop: () => void;
  cancel: () => void;
}

/** Wraps MediaRecorder for one spoken answer.
 *
 * Deliberately does nothing with the audio itself beyond handing the
 * finished Blob to `onComplete`: uploading, transcribing and scoring are the
 * caller's business, so this stays a thin, testable wrapper around the
 * browser API rather than a second place where interview logic lives.
 */
export function useVoiceRecorder(
  onComplete: (audio: Blob) => void,
): UseVoiceRecorderResult {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Set when the user cancels, so the stop handler knows to discard the
  // audio rather than hand it on for transcription.
  const discardRef = useRef(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  /** Releases the microphone. Without this the browser keeps showing the
   * recording indicator after the answer is submitted, which reads as the
   * app still listening. */
  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (tickRef.current !== null) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  useEffect(() => {
    // Unmounting mid-recording (switching notebooks, ending the interview)
    // must not leave the microphone open.
    return () => {
      if (recorderRef.current?.state === "recording") {
        discardRef.current = true;
        recorderRef.current.stop();
      }
      releaseStream();
    };
  }, [releaseStream]);

  const start = useCallback(async () => {
    setError(null);
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError("This browser can't record audio. Type your answer instead.");
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      // Covers both an outright denial and a device that isn't there; the
      // user's next move is the same either way.
      setError("Microphone access was blocked. Allow it in your browser, or type your answer.");
      return;
    }

    streamRef.current = stream;
    chunksRef.current = [];
    discardRef.current = false;

    // Let the browser pick its own container when webm/opus isn't supported
    // (Safari records mp4), rather than forcing a type it will reject.
    const preferred = "audio/webm;codecs=opus";
    const recorder =
      typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported?.(preferred)
        ? new MediaRecorder(stream, { mimeType: preferred })
        : new MediaRecorder(stream);

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      const audio = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
      chunksRef.current = [];
      releaseStream();
      setState("idle");
      setSeconds(0);
      if (!discardRef.current && audio.size > 0) {
        onCompleteRef.current(audio);
      }
      discardRef.current = false;
    };

    recorderRef.current = recorder;
    recorder.start();
    setState("recording");
    setSeconds(0);

    tickRef.current = setInterval(() => {
      setSeconds((previous) => {
        const next = previous + 1;
        if (next >= MAX_RECORDING_SECONDS && recorderRef.current?.state === "recording") {
          // Stopping at the cap rather than letting the recording grow until
          // the upload is rejected, which would lose the answer entirely.
          recorderRef.current.stop();
        }
        return next;
      });
    }, 1000);
  }, [releaseStream]);

  const stop = useCallback(() => {
    if (recorderRef.current?.state !== "recording") return;
    setState("stopping");
    recorderRef.current.stop();
  }, []);

  const cancel = useCallback(() => {
    if (recorderRef.current?.state !== "recording") return;
    discardRef.current = true;
    setState("stopping");
    recorderRef.current.stop();
  }, []);

  return { state, seconds, error, start, stop, cancel };
}

export function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}
