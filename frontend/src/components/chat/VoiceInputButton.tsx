/*
 * 역할: 짧은 음성 발화를 감지해 자동 종료하거나 사용자가 직접 멈춰 Gemini 전사 뒤
 * 기존 채팅 입력으로 넘긴다.
 * 입력: 전사 결과/오류/자동 전송/수동 정지 콜백과 외부 요청 중 여부.
 * 출력: 무음 감지로 자동 종료되면 한 번의 클릭만으로 바로 전송되고, 녹음 중 버튼을
 * 다시 눌러 수동으로 멈추면 인식된 텍스트가 입력창에 채워져 사용자가 수정 후 보낸다.
 * 호출 시점: HomePage와 ChatComposer의 음성 버튼 클릭.
 */

import { Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { transcribeAudio } from "../../api/trip";
import { toWavBlob } from "../../utils/audioRecording";

const MAX_RECORDING_MILLISECONDS = 60_000;
const NO_SPEECH_TIMEOUT_MILLISECONDS = 10_000;
const SILENCE_DURATION_MILLISECONDS = 1_200;
const SPEECH_THRESHOLD = 0.025;

type VoiceState = "idle" | "recording" | "transcribing";

// 녹음이 끝난 이유. "manual"만 사용자가 정지 버튼을 직접 누른 경우이고,
// 나머지는 전부 자동 종료다 — onstop에서 이 값으로 자동 전송/수동 정지를 가른다.
type StopReason = "manual" | "silence" | "no-speech-timeout" | "max-duration" | "unmount";

interface VoiceInputButtonProps {
  disabled?: boolean;
  /** 전사 직후 UI 오류 상태 등을 먼저 정리할 때 사용한다. */
  onTranscript: (text: string) => void;
  /** 무음 감지 등 자동 종료 시 입력창을 거치지 않고 기존 채팅 전송 흐름으로 바로 보낸다. */
  onAutoSubmit?: (text: string) => Promise<void> | void;
  /** 녹음 중 정지 버튼을 직접 눌러 멈췄을 때. 전송하지 않고 입력창에만 채워 넣는다. */
  onManualStop?: (text: string) => void;
  onError?: (message: string) => void;
}

export function VoiceInputButton({
  disabled = false,
  onTranscript,
  onAutoSubmit,
  onManualStop,
  onError,
}: VoiceInputButtonProps) {
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const monitorContextRef = useRef<AudioContext | null>(null);
  const monitorFrameRef = useRef<number | null>(null);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const noSpeechTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heardSpeechRef = useRef(false);
  const lastSpeechAtRef = useRef(0);
  const stopReasonRef = useRef<StopReason | null>(null);

  useEffect(
    () => () => {
      stopReasonRef.current = "unmount";
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      cleanupResources();
    },
    [],
  );

  function cleanupResources() {
    if (stopTimerRef.current) {
      clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
    if (noSpeechTimerRef.current) {
      clearTimeout(noSpeechTimerRef.current);
      noSpeechTimerRef.current = null;
    }
    if (monitorFrameRef.current !== null) {
      cancelAnimationFrame(monitorFrameRef.current);
      monitorFrameRef.current = null;
    }
    if (monitorContextRef.current) {
      void monitorContextRef.current.close();
      monitorContextRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }

  // 정지 트리거는 전부 이 함수 하나를 거친다. MediaRecorder.stop()이 state를
  // 동기적으로 바꾸므로, 이미 멈춘 뒤 도착한 트리거는 가드에 걸려 무시된다 —
  // 가장 먼저 도착한 트리거의 reason만 stopReasonRef에 남는다.
  function stopRecording(reason: StopReason) {
    if (recorderRef.current?.state !== "recording") return;
    stopReasonRef.current = reason;
    recorderRef.current.stop();
  }

  function monitorSilence(stream: MediaStream) {
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    analyser.fftSize = 1_024;
    context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    monitorContextRef.current = context;

    const checkVolume = () => {
      analyser.getByteTimeDomainData(samples);
      const averageAmplitude =
        samples.reduce((total, sample) => total + Math.abs(sample - 128), 0) / samples.length / 128;
      const now = performance.now();
      if (averageAmplitude >= SPEECH_THRESHOLD) {
        if (!heardSpeechRef.current && noSpeechTimerRef.current) {
          clearTimeout(noSpeechTimerRef.current);
          noSpeechTimerRef.current = null;
        }
        heardSpeechRef.current = true;
        lastSpeechAtRef.current = now;
      }

      if (
        heardSpeechRef.current &&
        now - lastSpeechAtRef.current >= SILENCE_DURATION_MILLISECONDS
      ) {
        stopRecording("silence");
        return;
      }
      monitorFrameRef.current = requestAnimationFrame(checkVolume);
    };
    monitorFrameRef.current = requestAnimationFrame(checkVolume);
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      onError?.("이 브라우저에서는 음성 입력을 지원하지 않아요. 텍스트로 입력해 주세요.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredMimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find(
        (mimeType) => MediaRecorder.isTypeSupported(mimeType),
      );
      const recorder = preferredMimeType
        ? new MediaRecorder(stream, { mimeType: preferredMimeType })
        : new MediaRecorder(stream);
      const chunks: BlobPart[] = [];
      heardSpeechRef.current = false;
      lastSpeechAtRef.current = performance.now();
      stopReasonRef.current = null;
      streamRef.current = stream;
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      recorder.onerror = () => {
        cleanupResources();
        setVoiceState("idle");
        onError?.("녹음 중 문제가 발생했어요. 다시 시도해 주세요.");
      };
      recorder.onstop = () => {
        const recording = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        const reason = stopReasonRef.current ?? "manual";
        cleanupResources();
        if (reason === "unmount") {
          setVoiceState("idle");
          return;
        }
        void transcribeRecording(recording, reason);
      };
      recorder.start();
      monitorSilence(stream);
      setVoiceState("recording");
      stopTimerRef.current = setTimeout(
        () => stopRecording("max-duration"),
        MAX_RECORDING_MILLISECONDS,
      );
      noSpeechTimerRef.current = setTimeout(
        () => stopRecording("no-speech-timeout"),
        NO_SPEECH_TIMEOUT_MILLISECONDS,
      );
    } catch (error) {
      cleanupResources();
      setVoiceState("idle");
      const denied = error instanceof DOMException && error.name === "NotAllowedError";
      onError?.(
        denied
          ? "마이크 권한이 필요해요. 브라우저 설정에서 허용한 뒤 다시 시도해 주세요."
          : "마이크를 사용할 수 없어요. 텍스트로 입력해 주세요.",
      );
    }
  }

  async function transcribeRecording(recording: Blob, reason: StopReason) {
    if (!recording.size || !heardSpeechRef.current) {
      setVoiceState("idle");
      onError?.("음성을 인식하지 못했어요. 조금 더 또렷하게 말씀해 주세요.");
      return;
    }
    setVoiceState("transcribing");
    try {
      const wav = await toWavBlob(recording);
      const response = await transcribeAudio(wav);
      onTranscript(response.text);
      if (reason === "manual") {
        onManualStop?.(response.text);
      } else {
        await onAutoSubmit?.(response.text);
      }
    } catch (error) {
      onError?.(
        error instanceof ApiError
          ? error.message
          : "음성을 텍스트로 변환하지 못했어요. 다시 시도해 주세요.",
      );
    } finally {
      setVoiceState("idle");
    }
  }

  function handleClick() {
    if (voiceState === "recording") {
      stopRecording("manual");
      return;
    }
    if (voiceState === "idle") void startRecording();
  }

  const label =
    voiceState === "recording"
      ? "녹음 중이에요. 말이 끝나면 자동으로 전송하고, 버튼을 누르면 지금까지 인식된 내용을 입력창에 채워줘요."
      : voiceState === "transcribing"
        ? "음성을 텍스트로 바꾸는 중"
        : "음성으로 입력";

  return (
    <button
      type="button"
      disabled={disabled || voiceState === "transcribing"}
      onClick={handleClick}
      aria-label={label}
      title={voiceState === "recording" ? "눌러서 녹음 마치기" : label}
      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors disabled:opacity-50 ${
        voiceState === "recording"
          ? "animate-pulse bg-rust text-white"
          : "bg-chip text-ink hover:bg-sky-light"
      }`}
    >
      {voiceState === "transcribing" ? (
        <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : voiceState === "recording" ? (
        <Square size={14} className="fill-current" aria-hidden />
      ) : (
        <Mic size={16} aria-hidden />
      )}
      <span className="sr-only">{label}</span>
    </button>
  );
}
