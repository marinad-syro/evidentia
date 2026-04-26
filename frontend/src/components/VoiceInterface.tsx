import React, { useState, useRef, useCallback, useEffect } from "react";
import { SearchResults } from "../types";

type VoiceStatus = "idle" | "connecting" | "listening" | "hearing" | "thinking" | "speaking" | "error";

const STATUS_LABEL: Record<VoiceStatus, string> = {
  idle: "Tap to speak",
  connecting: "Connecting…",
  listening: "Listening…",
  hearing: "Heard you…",
  thinking: "Searching providers…",
  speaking: "Speaking…",
  error: "Error — tap to retry",
};

const STATUS_COLOR: Record<VoiceStatus, string> = {
  idle: "#28030f",
  connecting: "#94a3b8",
  listening: "#28030f",
  hearing: "#22c55e",
  thinking: "#f59e0b",
  speaking: "#8b5cf6",
  error: "#ef4444",
};

function float32ToPcm16(f32: Float32Array): Int16Array {
  const pcm = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm;
}

function bufToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let b = "";
  for (let i = 0; i < bytes.byteLength; i++) b += String.fromCharCode(bytes[i]);
  return btoa(b);
}

function base64ToBuf(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

// Live mic-level bars
function AudioBars({ analyser, active }: { analyser: AnalyserNode | null; active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !analyser || !active) return;

    const ctx = canvas.getContext("2d")!;
    const bufLen = analyser.frequencyBinCount;
    const data = new Uint8Array(bufLen);
    const BAR_COUNT = 7;
    const W = canvas.width;
    const H = canvas.height;

    const draw = () => {
      rafRef.current = requestAnimationFrame(draw);
      analyser.getByteTimeDomainData(data);

      // RMS level per bar segment
      const segSize = Math.floor(bufLen / BAR_COUNT);
      ctx.clearRect(0, 0, W, H);

      for (let i = 0; i < BAR_COUNT; i++) {
        let sum = 0;
        for (let j = 0; j < segSize; j++) {
          const v = (data[i * segSize + j] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / segSize);
        const barH = Math.max(4, rms * H * 4);

        const barW = W / BAR_COUNT - 3;
        const x = i * (barW + 3);
        const y = (H - barH) / 2;

        ctx.fillStyle = `rgba(40, 3, 15, ${0.4 + rms * 3})`;
        ctx.beginPath();
        ctx.roundRect(x, y, barW, barH, 2);
        ctx.fill();
      }
    };

    draw();
    return () => cancelAnimationFrame(rafRef.current);
  }, [analyser, active]);

  return (
    <canvas
      ref={canvasRef}
      width={56}
      height={24}
      style={{ opacity: active ? 1 : 0, transition: "opacity 0.3s" }}
    />
  );
}

interface Props {
  onResults?: (results: SearchResults) => void;
  userLocation?: { lat: number; lon: number } | null;
}

export function VoiceInterface({ onResults, userLocation }: Props) {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [transcript, setTranscript] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const nextPlayRef = useRef<number>(0);
  const [analyserNode, setAnalyserNode] = useState<AnalyserNode | null>(null);

  const teardown = useCallback(() => {
    processorRef.current?.disconnect();
    analyserRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    try { ctxRef.current?.close(); } catch {}
    wsRef.current?.close();
    processorRef.current = null;
    analyserRef.current = null;
    streamRef.current = null;
    ctxRef.current = null;
    wsRef.current = null;
    setAnalyserNode(null);
  }, []);

  const playDelta = useCallback((b64: string, ctx: AudioContext) => {
    const pcm = new Int16Array(base64ToBuf(b64));
    const f32 = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) f32[i] = pcm[i] / 32768.0;
    const buf = ctx.createBuffer(1, f32.length, 24000);
    buf.copyToChannel(f32, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const t = Math.max(ctx.currentTime, nextPlayRef.current);
    src.start(t);
    nextPlayRef.current = t + buf.duration;
  }, []);

  const start = useCallback(async () => {
    setStatus("connecting");
    setTranscript("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const ctx = new AudioContext({ sampleRate: 24000 });
      ctxRef.current = ctx;
      nextPlayRef.current = ctx.currentTime;

      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${proto}//${window.location.host}/ws/voice`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (userLocation) {
          ws.send(JSON.stringify({ type: "client.location", lat: userLocation.lat, lon: userLocation.lon }));
        }
        setStatus("listening");

        const source = ctx.createMediaStreamSource(stream);

        // Analyser for visualisation (doesn't affect audio sent to xAI)
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        analyserRef.current = analyser;
        source.connect(analyser);
        setAnalyserNode(analyser);

        const processor = ctx.createScriptProcessor(4096, 1, 1);
        processorRef.current = processor;
        source.connect(processor);
        processor.connect(ctx.destination);
        processor.onaudioprocess = (e) => {
          if (ws.readyState !== WebSocket.OPEN) return;
          const pcm = float32ToPcm16(e.inputBuffer.getChannelData(0));
          ws.send(JSON.stringify({ type: "input_audio_buffer.append", audio: bufToBase64(pcm.buffer as ArrayBuffer) }));
        };
      };

      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data as string);
        switch (ev.type) {
          case "input_audio_buffer.speech_started":
            setStatus("hearing");
            if (ctxRef.current) nextPlayRef.current = ctxRef.current.currentTime;
            break;
          case "input_audio_buffer.speech_stopped":
            setStatus("listening");
            break;
          case "response.output_audio.delta":
            if (ctxRef.current) playDelta(ev.delta, ctxRef.current);
            setStatus("speaking");
            break;
          case "response.text.delta":
          case "response.audio_transcript.delta":
            setTranscript((p) => p + (ev.delta ?? ""));
            break;
          case "response.done":
            setStatus("listening");
            setTimeout(() => setTranscript(""), 4000);
            break;
          case "voice.results":
            if (onResults) {
              onResults({
                providers: ev.providers ?? [],
                specialty_interpreted: ev.specialty_interpreted ?? "",
                location_interpreted: ev.location_interpreted ?? "",
                radius_km: ev.radius_km ?? 0,
                total_candidates: ev.total_candidates ?? ev.providers?.length ?? 0,
              });
            }
            break;
          case "voice.searching":
            setStatus("thinking");
            break;
          case "voice.error":
            setStatus("error");
            break;
        }
      };

      ws.onerror = () => setStatus("error");
      ws.onclose = () => { setStatus("idle"); teardown(); };
    } catch {
      setStatus("error");
      teardown();
    }
  }, [playDelta, teardown, onResults, userLocation]);

  const stop = useCallback(() => {
    teardown();
    setStatus("idle");
    setTranscript("");
  }, [teardown]);

  useEffect(() => () => teardown(), [teardown]);

  const active = status !== "idle" && status !== "error";
  const color = STATUS_COLOR[status];
  const micActive = status === "listening" || status === "hearing";
  const bgColor = (status === "idle" || status === "listening") ? "#fbf582" : color;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>

      {/* Mic button */}
      <button
        onClick={active ? stop : start}
        style={{
          width: 60,
          height: 60,
          borderRadius: "50%",
          border: "none",
          cursor: "pointer",
          background: bgColor,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transition: "background 0.25s, box-shadow 0.25s",
          boxShadow: active ? `0 0 0 6px ${bgColor}33` : "0 2px 8px rgba(0,0,0,0.15)",
          animation: status === "hearing" ? "hearing-ring 0.6s ease-in-out 2" : "none",
        }}
        title={STATUS_LABEL[status]}
      >
        {active ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#28030f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="4" y="4" width="16" height="16" rx="3" />
          </svg>
        ) : (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#28030f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="2" width="6" height="12" rx="3" />
            <path d="M5 10a7 7 0 0 0 14 0" />
            <line x1="12" y1="17" x2="12" y2="22" />
            <line x1="8" y1="22" x2="16" y2="22" />
          </svg>
        )}
      </button>

      {/* Live audio bars — only visible when mic is open */}
      <AudioBars analyser={analyserNode} active={micActive} />

      {/* Status label */}
      <div style={{
        fontSize: 12,
        fontWeight: 500,
        color,
        transition: "color 0.2s",
        letterSpacing: "0.03em",
      }}>
        {STATUS_LABEL[status]}
      </div>

      {/* Transcript */}
      {transcript && (
        <div style={{
          maxWidth: 300,
          padding: "8px 14px",
          background: "#f1f5f9",
          borderRadius: 8,
          fontSize: 13,
          color: "#334155",
          textAlign: "center",
          fontStyle: "italic",
          borderLeft: `3px solid ${color}`,
          transition: "border-color 0.2s",
        }}>
          {transcript}
        </div>
      )}

      <style>{`
        @keyframes hearing-ring {
          0%   { box-shadow: 0 0 0 0   rgba(34,197,94,0.6); }
          50%  { box-shadow: 0 0 0 14px rgba(34,197,94,0); }
          100% { box-shadow: 0 0 0 0   rgba(34,197,94,0); }
        }
      `}</style>
    </div>
  );
}
