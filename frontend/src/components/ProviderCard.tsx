import React from "react";
import { Provider } from "../types";

interface Props {
  provider: Provider;
  rank: number;
}

function TrustBadge({ score, verified }: { score: number; verified: boolean }) {
  const color = score >= 70 ? "#22c55e" : score >= 40 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div
        style={{
          width: 48,
          height: 48,
          borderRadius: "50%",
          border: `3px solid ${color}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontWeight: 700,
          fontSize: 13,
          color,
        }}
      >
        {score}
      </div>
      {verified && (
        <span style={{ fontSize: 11, color: "#22c55e", fontWeight: 600 }}>
          LIVE ✓
        </span>
      )}
    </div>
  );
}

export function ProviderCard({ provider: p, rank }: Props) {
  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid #e2e8f0",
        borderRadius: 14,
        padding: "20px 24px",
        position: "relative",
      }}
    >
      {/* Rank badge */}
      <div
        style={{
          position: "absolute",
          top: 16,
          left: -12,
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: rank === 1 ? "#f59e0b" : "#94a3b8",
          color: "#fff",
          fontWeight: 700,
          fontSize: 12,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        #{rank}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h3 style={{ fontSize: 17, fontWeight: 700, marginBottom: 2 }}>{p.name}</h3>
          <div style={{ fontSize: 13, color: "#64748b", marginBottom: 8 }}>
            {p.facility_type} · {p.distance_km} km away · {p.city}
          </div>

          {/* Why this */}
          <p style={{ fontSize: 14, color: "#334155", marginBottom: 10, fontStyle: "italic" }}>
            "{p.why_this}"
          </p>

          {/* Specialties */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
            {p.specialties.slice(0, 4).map((s) => (
              <span
                key={s}
                style={{
                  padding: "2px 10px",
                  background: "#eff6ff",
                  color: "#3b82f6",
                  borderRadius: 20,
                  fontSize: 12,
                  fontWeight: 500,
                }}
              >
                {s}
              </span>
            ))}
          </div>

          {/* Contact */}
          <div style={{ fontSize: 13, color: "#475569", display: "flex", gap: 16, flexWrap: "wrap" }}>
            {p.phone && <span>📞 {p.phone}</span>}
            {p.website && (
              <a href={p.website} target="_blank" rel="noopener noreferrer" style={{ color: "#3b82f6" }}>
                🌐 Website
              </a>
            )}
            {p.address && <span>📍 {p.address}</span>}
          </div>

          {/* Caveat */}
          {p.caveat && (
            <div
              style={{
                marginTop: 10,
                padding: "6px 12px",
                background: "#fffbeb",
                borderLeft: "3px solid #f59e0b",
                fontSize: 12,
                color: "#92400e",
                borderRadius: "0 6px 6px 0",
              }}
            >
              ⚠️ {p.caveat}
            </div>
          )}

          {/* Red flags */}
          {p.red_flags.length > 0 && (
            <div style={{ marginTop: 6 }}>
              {p.red_flags.map((flag, i) => (
                <div key={i} style={{ fontSize: 12, color: "#ef4444" }}>
                  🚩 {flag}
                </div>
              ))}
            </div>
          )}
        </div>

        <TrustBadge score={p.trust_score} verified={p.live_verified} />
      </div>

      {/* Trust signals */}
      {p.trust_signals.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary style={{ fontSize: 12, color: "#64748b", cursor: "pointer" }}>
            Trust signals ({p.trust_signals.length})
          </summary>
          <ul style={{ marginTop: 6, paddingLeft: 18, fontSize: 12, color: "#475569" }}>
            {p.trust_signals.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
