import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatDuration, MAX_RECORDING_SECONDS, useVoiceRecorder } from "./useVoiceRecorder";

class FakeTrack {
  stopped = false;
  stop() {
    this.stopped = true;
  }
}

class FakeStream {
  tracks = [new FakeTrack()];
  getTracks() {
    return this.tracks;
  }
}

class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];
  static supported = true;
  static isTypeSupported = (_type: string) => FakeMediaRecorder.supported;

  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  stream: FakeStream;
  options?: { mimeType?: string };

  // Plain field assignment rather than constructor parameter properties:
  // the project builds with `erasableSyntaxOnly`, which rejects any TS
  // syntax that emits runtime code.
  constructor(stream: FakeStream, options?: { mimeType?: string }) {
    this.stream = stream;
    this.options = options;
    FakeMediaRecorder.instances.push(this);
    if (options?.mimeType) this.mimeType = options.mimeType;
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

let currentStream: FakeStream;

function mockMediaDevices(getUserMedia?: () => Promise<unknown>) {
  currentStream = new FakeStream();
  Object.defineProperty(globalThis.navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: getUserMedia ?? (() => Promise.resolve(currentStream)),
    },
  });
}

describe("useVoiceRecorder", () => {
  beforeEach(() => {
    FakeMediaRecorder.instances = [];
    FakeMediaRecorder.supported = true;
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    mockMediaDevices();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("hands the finished recording to the caller", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder(onComplete));

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.state).toBe("recording");

    act(() => {
      result.current.stop();
    });

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    expect(onComplete.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect(result.current.state).toBe("idle");
  });

  it("releases the microphone when recording stops", async () => {
    // Without this the browser keeps showing its recording indicator, which
    // reads as the app still listening after the answer is submitted.
    const { result } = renderHook(() => useVoiceRecorder(vi.fn()));

    await act(async () => {
      await result.current.start();
    });
    act(() => {
      result.current.stop();
    });

    await waitFor(() => expect(currentStream.getTracks()[0].stopped).toBe(true));
  });

  it("discards the audio when the user cancels", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder(onComplete));

    await act(async () => {
      await result.current.start();
    });
    act(() => {
      result.current.cancel();
    });

    await waitFor(() => expect(result.current.state).toBe("idle"));
    expect(onComplete).not.toHaveBeenCalled();
    expect(currentStream.getTracks()[0].stopped).toBe(true);
  });

  it("explains a blocked microphone instead of failing silently", async () => {
    mockMediaDevices(() => Promise.reject(new Error("NotAllowedError")));
    const { result } = renderHook(() => useVoiceRecorder(vi.fn()));

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.state).toBe("idle");
    expect(result.current.error).toMatch(/microphone access was blocked/i);
  });

  it("explains a browser that cannot record at all", async () => {
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      configurable: true,
      value: undefined,
    });
    const { result } = renderHook(() => useVoiceRecorder(vi.fn()));

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.error).toMatch(/can't record audio/i);
  });

  it("falls back to the browser's own container when webm/opus is unsupported", async () => {
    // Safari records mp4; forcing a mimeType it rejects would break
    // recording there entirely.
    FakeMediaRecorder.supported = false;
    const { result } = renderHook(() => useVoiceRecorder(vi.fn()));

    await act(async () => {
      await result.current.start();
    });

    expect(FakeMediaRecorder.instances[0].options).toBeUndefined();
  });

  it("counts the elapsed seconds while recording", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceRecorder(vi.fn()));

    await act(async () => {
      await result.current.start();
    });
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(result.current.seconds).toBe(3);
  });

  it("stops itself at the time limit rather than losing the answer to a rejected upload", async () => {
    vi.useFakeTimers();
    const onComplete = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder(onComplete));

    await act(async () => {
      await result.current.start();
    });
    act(() => {
      vi.advanceTimersByTime(MAX_RECORDING_SECONDS * 1000);
    });

    expect(FakeMediaRecorder.instances[0].state).toBe("inactive");
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("releases the microphone if the component unmounts mid-recording", async () => {
    const { result, unmount } = renderHook(() => useVoiceRecorder(vi.fn()));

    await act(async () => {
      await result.current.start();
    });
    unmount();

    expect(currentStream.getTracks()[0].stopped).toBe(true);
  });
});

describe("formatDuration", () => {
  it.each([
    [0, "0:00"],
    [5, "0:05"],
    [59, "0:59"],
    [60, "1:00"],
    [125, "2:05"],
  ])("formats %i seconds as %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});
