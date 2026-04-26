import React, { useState, useCallback, useEffect } from "react";
import { API_BASE } from "./lib/api";
import "leaflet/dist/leaflet.css";
import { SearchBar } from "./components/SearchBar";
import { ProgressFeed } from "./components/ProgressFeed";
import { MapView } from "./components/MapView";
import { DesertMap } from "./components/DesertMap";
import { VoiceInterface } from "./components/VoiceInterface";
import { Step, SearchResults } from "./types";

type Mode = "text" | "voice" | "deserts";
type UserLocation = { lat: number; lon: number } | "denied" | null;

export default function App() {
  const [mode, setMode] = useState<Mode>("text");
  const [steps, setSteps] = useState<Step[]>([]);
  const [results, setResults] = useState<SearchResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [userLocation, setUserLocation] = useState<UserLocation>({ lat: 19.1511, lon: 72.8829 });
  const [locLoading, setLocLoading] = useState(false);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false));
  }, []);

  const requestLocation = useCallback(() => {
    setLocLoading(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude });
        setLocLoading(false);
      },
      () => {
        setUserLocation("denied");
        setLocLoading(false);
      },
      { timeout: 8000 },
    );
  }, []);

  const switchMode = (m: Mode) => {
    setMode(m);
    setResults(null);
    setSteps([]);
    setError(null);
    setLoading(false);
  };

  const runSearch = useCallback((query: string) => {
    setSteps([]);
    setResults(null);
    setError(null);
    setLoading(true);

    const locParam = userLocation && typeof userLocation === "object"
      ? `&lat=${userLocation.lat}&lon=${userLocation.lon}`
      : "";
    const url = `${API_BASE}/search?q=${encodeURIComponent(query)}${locParam}`;
    const es = new EventSource(url);

    es.addEventListener("step", (e) => {
      const data = JSON.parse(e.data) as { id: string; status: string; text: string; detail: string };
      setSteps((prev) => {
        const existing = prev.findIndex((s) => s.id === data.id);
        const updated: Step = {
          id: data.id,
          status: data.status as Step["status"],
          text: data.text,
          detail: data.detail,
        };
        if (existing >= 0) {
          const next = [...prev];
          next[existing] = updated;
          return next;
        }
        return [...prev, updated];
      });
    });

    es.addEventListener("results", (e) => {
      setResults(JSON.parse(e.data) as SearchResults);
    });

    es.addEventListener("error", (e) => {
      const data = (e as MessageEvent).data;
      if (data) {
        try { setError(JSON.parse(data).error ?? "Search failed."); } catch { setError(data); }
      } else {
        setError(backendOk === false
          ? "Cannot reach the backend. Check that the server is running."
          : "Search connection failed — the backend may be unavailable.");
      }
      es.close();
      setLoading(false);
    });

    const checkDone = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.id === "done" && data.status === "done") {
          setTimeout(() => { es.close(); setLoading(false); }, 200);
        }
      } catch {}
    };
    es.addEventListener("step", checkDone as EventListener);
  }, [userLocation]);

  const loc = typeof userLocation === "object" ? userLocation : null;

  return (
    <div>
      {/* ── Header + controls — 760px centered ── */}
      <div style={{ maxWidth: 760, margin: "0 auto", padding: results ? "24px 20px 16px" : "60px 20px 40px" }}>

        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <h1 style={{ fontSize: 34, fontWeight: 800, color: "#1e293b", marginBottom: 10 }}>
            Evidentia
          </h1>
          <p style={{ fontSize: 17, color: "#64748b", marginBottom: 16 }}>
            Describe your healthcare needs and we'll find the best providers for you.
          </p>
          <LocationPill location={userLocation} loading={locLoading} onRequest={requestLocation} />
        </div>

        {/* Mode toggle */}
        <div style={{ display: "flex", gap: 8, marginBottom: 20, justifyContent: "center" }}>
          {(["text", "voice", "deserts"] as Mode[]).map((m) => {
            const label = m === "text" ? "Text" : m === "voice" ? "🎙️ Voice" : "🏥 Desert Map";
            return (
              <button
                key={m}
                onClick={() => switchMode(m)}
                style={{
                  padding: "9px 24px", borderRadius: 20, border: "none", cursor: "pointer", fontSize: 15,
                  fontWeight: 500,
                  background: mode === m ? "#28030f" : "#f1f5f9",
                  color: mode === m ? "#fff" : "#64748b",
                  transition: "all 0.15s",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>

        {/* Backend status banner */}
        {backendOk === false && (
          <div style={{
            background: "#fef2f2", border: "1px solid #fecaca",
            borderRadius: 8, padding: "10px 14px", marginBottom: 16,
            fontSize: 13, color: "#b91c1c",
          }}>
            ⚠️ Cannot reach the backend at <code>{API_BASE || window.location.origin}</code>.
            {" "}Make sure the server is running and <code>VITE_API_URL</code> is set correctly.
          </div>
        )}

        {/* ── TEXT MODE ── */}
        {mode === "text" && (
          <>
            <SearchBar onSearch={runSearch} loading={loading} />

            {/* Example chips */}
            {steps.length === 0 && !loading && !results && (
              <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {["eye specialist near Koramangala", "heart doctor in Mumbai", "diabetes clinic in Pune"].map((q) => (
                  <button
                    key={q}
                    onClick={() => runSearch(q)}
                    style={{
                      padding: "5px 13px",
                      background: "#f1f5f9",
                      border: "1px solid #e2e8f0",
                      borderRadius: 20,
                      fontSize: 13,
                      color: "#475569",
                      cursor: "pointer",
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}

            {/* Progress feed — shown while loading, hidden once map appears */}
            {(steps.length > 0 || error) && !results && (
              <div style={{ marginTop: 24 }}>
                <ProgressFeed steps={steps} error={error} />
              </div>
            )}
          </>
        )}

        {/* ── VOICE MODE ── */}
        {mode === "voice" && (
          <div style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            padding: "32px 0 24px",
            background: "#fcfaf8",
            borderRadius: 16,
          }}>
            <VoiceInterface
              onResults={setResults}
              userLocation={loc}
            />
          </div>
        )}
      </div>

      {/* ── Map — full viewport width, shown once results arrive ── */}
      {mode !== "deserts" && results && (
        <MapView results={results} userLocation={loc} />
      )}

      {/* ── Desert Map — full viewport width ── */}
      {mode === "deserts" && (
        <DesertMap />
      )}
    </div>
  );
}

function LocationPill({
  location,
  loading,
  onRequest,
}: {
  location: UserLocation;
  loading: boolean;
  onRequest: () => void;
}) {
  if (loading) {
    return (
      <span style={{ fontSize: 12, color: "#94a3b8" }}>
        📍 Getting location…
      </span>
    );
  }
  if (location && typeof location === "object") {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        fontSize: 12, fontWeight: 500, color: "#16a34a",
        background: "#f0fdf4", border: "1px solid #bbf7d0",
        borderRadius: 20, padding: "3px 12px",
      }}>
        📍 Location enabled
      </span>
    );
  }
  if (location === "denied") {
    return (
      <span style={{
        fontSize: 12, color: "#94a3b8",
        background: "#f8fafc", border: "1px solid #e2e8f0",
        borderRadius: 20, padding: "3px 12px",
      }}
        title="Allow location access in your browser settings and reload"
      >
        📍 Location blocked
      </span>
    );
  }
  return (
    <button
      onClick={onRequest}
      style={{
        fontSize: 12, fontWeight: 500, color: "#28030f",
        background: "#f5e8ea", border: "1px solid #d4abb3",
        borderRadius: 20, padding: "3px 12px",
        cursor: "pointer",
      }}
    >
      📍 Enable location
    </button>
  );
}
