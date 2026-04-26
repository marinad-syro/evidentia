import React, { useState, useCallback } from "react";
import { SearchBar } from "./components/SearchBar";
import { ProgressFeed } from "./components/ProgressFeed";
import { ProviderCard } from "./components/ProviderCard";
import { Step, SearchResults } from "./types";

const STEP_ORDER = ["intent", "geo", "filter", "rank", "trust", "done"];

export default function App() {
  const [steps, setSteps] = useState<Step[]>([]);
  const [results, setResults] = useState<SearchResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const runSearch = useCallback((query: string) => {
    setSteps([]);
    setResults(null);
    setError(null);
    setLoading(true);

    const es = new EventSource(`/search?q=${encodeURIComponent(query)}`);

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
      if (e.type === "error" && (e as MessageEvent).data) {
        const data = JSON.parse((e as MessageEvent).data);
        setError(data.error ?? "An error occurred.");
      }
      es.close();
      setLoading(false);
    });

    es.onopen = () => {};

    // Close when "done" step arrives
    const checkDone = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.id === "done" && data.status === "done") {
          setTimeout(() => {
            es.close();
            setLoading(false);
          }, 200);
        }
      } catch {}
    };
    es.addEventListener("step", checkDone as EventListener);
  }, []);

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: "40px 20px" }}>
      {/* Header */}
      <div style={{ textAlign: "center", marginBottom: 36 }}>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: "#1e293b", marginBottom: 8 }}>
          Healthcare Provider Finder
        </h1>
        <p style={{ fontSize: 15, color: "#64748b" }}>
          Describe what you need in plain English — we'll find the right provider near you.
        </p>
      </div>

      <SearchBar onSearch={runSearch} loading={loading} />

      {/* Example queries */}
      {steps.length === 0 && !loading && (
        <div style={{ marginTop: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {[
            "eye specialist near Koramangala",
            "heart doctor in Mumbai",
            "government hospital for diabetes in Pune",
          ].map((q) => (
            <button
              key={q}
              onClick={() => runSearch(q)}
              style={{
                padding: "6px 14px",
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

      {/* Progress feed */}
      {(steps.length > 0 || error) && (
        <div style={{ marginTop: 28 }}>
          <ProgressFeed steps={steps} error={error} />
        </div>
      )}

      {/* Results */}
      {results && (
        <div style={{ marginTop: 32 }}>
          <div style={{ marginBottom: 16, fontSize: 13, color: "#64748b" }}>
            Showing {results.providers.length} providers for{" "}
            <strong>{results.specialty_interpreted}</strong> near{" "}
            <strong>{results.location_interpreted}</strong> · {results.total_candidates} candidates scanned
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {results.providers.map((p, i) => (
              <ProviderCard key={p.provider_id} provider={p} rank={i + 1} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
