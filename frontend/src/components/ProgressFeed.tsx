import React from "react";
import { Step } from "../types";

interface Props {
  steps: Step[];
  error: string | null;
}

const STEP_ICONS: Record<string, string> = {
  intent: "🧠",
  geo: "📍",
  filter: "🔍",
  rank: "⚖️",
  trust: "✅",
  done: "🎉",
};

const STATUS_COLOR: Record<string, string> = {
  pending: "#94a3b8",
  active: "#f59e0b",
  done: "#22c55e",
};

export function ProgressFeed({ steps, error }: Props) {
  if (steps.length === 0 && !error) return null;

  return (
    <div
      style={{
        background: "#0f172a",
        borderRadius: 12,
        padding: "20px 24px",
        fontFamily: "monospace",
        fontSize: 14,
        color: "#e2e8f0",
      }}
    >
      {steps.map((step) => (
        <div
          key={step.id}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
            marginBottom: 10,
            opacity: step.status === "pending" ? 0.4 : 1,
            transition: "opacity 0.3s",
          }}
        >
          <span style={{ fontSize: 16, lineHeight: "20px" }}>
            {STEP_ICONS[step.id] ?? "•"}
          </span>
          <div style={{ flex: 1 }}>
            <span style={{ color: STATUS_COLOR[step.status] }}>
              [{step.status.toUpperCase()}]
            </span>{" "}
            <span>{step.text}</span>
            {step.detail && (
              step.id === "filter" && step.detail.includes("Pass") ? (
                <FilterLog detail={step.detail} />
              ) : (
                <div style={{ color: "#64748b", marginTop: 2 }}>{step.detail}</div>
              )
            )}
          </div>
        </div>
      ))}
      {error && (
        <div
          style={{
            marginTop: 8,
            padding: "10px 14px",
            background: "#450a0a",
            borderRadius: 8,
            color: "#fca5a5",
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}

function FilterLog({ detail }: { detail: string }) {
  const [open, setOpen] = React.useState(false);
  const [summary, ...rest] = detail.split("\n\n");
  const log = rest.join("\n\n");

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ color: "#64748b", marginBottom: 4 }}>{summary}</div>
      {log && (
        <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
          <summary style={{
            fontSize: 11,
            color: "#94a3b8",
            cursor: "pointer",
            userSelect: "none",
            listStyle: "none",
          }}>
            {open ? "▾" : "▸"} filter breakdown
          </summary>
          <pre style={{
            marginTop: 6,
            padding: "10px 12px",
            background: "#0a0f1a",
            borderRadius: 6,
            fontSize: 11,
            lineHeight: 1.7,
            color: "#94a3b8",
            whiteSpace: "pre",
            overflowX: "auto",
            fontFamily: "ui-monospace, 'Cascadia Code', monospace",
          }}>
            {log.split("\n").map((line, i) => {
              const isBiggest = line.includes("← biggest cut");
              const isMatched = line.trim().startsWith("Matched");
              const isHeader = line.startsWith("Pass") || line.startsWith("Dataset") || line.startsWith("FAISS");
              return (
                <span key={i} style={{
                  color: isBiggest ? "#fca5a5" : isMatched ? "#86efac" : isHeader ? "#e2e8f0" : undefined,
                  display: "block",
                }}>
                  {line}
                </span>
              );
            })}
          </pre>
        </details>
      )}
    </div>
  );
}
