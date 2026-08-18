/*
 * 역할: 짧은 음성 발화를 감지해 자동 종료하고 Gemini 전사 뒤 기존 채팅 전송으로 넘긴다.
 * 입력: 전사 결과/오류/자동 전송 콜백과 외부 요청 중 여부.
 * 출력: 사용자 발화가 끝난 뒤 한 번의 클릭만으로 실행되는 음성 입력 UX.
 * 호출 시점: HomePage와 ChatComposer의 음성 버튼 클릭.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { transcribeAudio } from "../../api/trip";
import { toWavBlob } from "../../utils/audioRecording";

const MAX_RECORDING_MILLISECONDS = 60_000;
const SILENCE_DURATION_MILLISECONDS = 1_200;
const SPEECH_THRESHOLD = 0.025;

type VoiceState = "idle" | "recording" | "transcribing";

interface VoiceInputButtonProps {
  disabled?: boolean;
  /** 전사 직후 UI 오류 상태 등을 먼저 정리할 때 사용한다. */
  onTranscript: (text: string) => void;
  /** 있으면 입력창을 거치지 않고 기존 채팅 전송 흐름으로 바로 보낸다. */
  onAutoSubmit?: (text: string) => Promise<void> | void;
  onError?: (message: string) => void;
}

export function VoiceInputButton({
  disabled = false,
  onTranscript,
  onAutoSubmit,
  onError,
}: VoiceInputButtonProps) {
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const monitorContextRef = useRef<AudioContext | null>(null);
  const monitorFrameRef = useRef<number | null>(null);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heardSpeechRef = useRef(false);
  const lastSpeechAtRef = useRef(0);
  const discardRecordingRef = useRef(false);

  useEffect(
    () => () => {
      discardRecordingRef.current = true;
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

  function stopRecording() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
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
        samples.reduce((total, sample) => total + Math.abs(sample - 128), 0) /
        samples.length /
        128;
      const now = performance.now();
      if (averageAmplitude >= SPEECH_THRESHOLD) {
        heardSpeechRef.current = true;
        lastSpeechAtRef.current = now;
      }

      if (
        heardSpeechRef.current &&
        now - lastSpeechAtRef.current >= SILENCE_DURATION_MILLISECONDS
      ) {
        stopRecording();
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
      discardRecordingRef.current = false;
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
        const discardRecording = discardRecordingRef.current;
        cleanupResources();
        if (discardRecording) {
          setVoiceState("idle");
          return;
        }
        void transcribeRecording(recording);
      };
      recorder.start();
      monitorSilence(stream);
      setVoiceState("recording");
      stopTimerRef.current = setTimeout(stopRecording, MAX_RECORDING_MILLISECONDS);
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

  async function transcribeRecording(recording: Blob) {
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
      await onAutoSubmit?.(response.text);
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
      // 완료는 무음 감지가 담당한다. 두 번째 클릭은 의도적으로 취소만 한다.
      discardRecordingRef.current = true;
      stopRecording();
      return;
    }
    if (voiceState === "idle") void startRecording();
  }

  const label =
    voiceState === "recording"
      ? "듣고 있어요. 말이 끝나면 자동으로 전송합니다."
      : voiceState === "transcribing"
        ? "음성을 텍스트로 바꾸는 중"
        : "음성으로 입력";

  return (
    <button
      type="button"
      disabled={disabled || voiceState === "transcribing"}
      onClick={handleClick}
      aria-label={label}
      title={voiceState === "recording" ? "녹음을 취소하려면 누르세요" : label}
      className={`inline-flex size-10 shrink-0 items-center justify-center rounded-full transition disabled:opacity-50 ${
        voiceState === "recording"
          ? "bg-gray-950 text-white shadow-md shadow-gray-400/40 dark:bg-gray-100 dark:text-gray-950"
          : "text-gray-950 hover:bg-gray-100 dark:text-gray-100 dark:hover:bg-gray-800"
      }`}
    >
      {voiceState === "transcribing" ? (
        <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : (
        <span className={voiceState === "recording" ? "animate-pulse" : ""} aria-hidden="true">
          <VoiceWaveIcon />
        </span>
      )}
      <span className="sr-only">{label}</span>
    </button>
  );
}

function VoiceWaveIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="size-7" stroke="currentColor" strokeWidth="2.2">
      <rect x="8.25" y="3" width="7.5" height="11.5" rx="3.75" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M8.5 21h7" strokeLinecap="round" />
    </svg>
  );
}
