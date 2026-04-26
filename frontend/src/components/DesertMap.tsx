import React, { useEffect, useState } from "react";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer } from "@deck.gl/layers";
import { HexagonLayer } from "@deck.gl/aggregation-layers";

type ServiceStatus = "green" | "yellow" | "red";
type ServiceKey = "oncology" | "emergency" | "trauma" | "dialysis";

interface PincodeEntry {
  pin: string;
  lat: number;
  lon: number;
  provider_count: number;
  services: Record<ServiceKey, ServiceStatus>;
  need_score: number;
  state: string;
}

interface PincodeData {
  pincodes: PincodeEntry[];
  stats: Record<ServiceKey, Record<ServiceStatus, number>>;
  total_pincodes: number;
}

interface PopulationData {
  geojson: any;
  breakpoints: number[];
}

// Light yellow → orange → dark red (ColorBrewer YlOrRd)
const URGENCY_COLOR_RANGE: [number, number, number, number][] = [
  [255, 255, 178, 220],
  [254, 204,  92, 230],
  [253, 141,  60, 235],
  [240,  59,  32, 242],
  [189,   0,  38, 255],
];

const INITIAL_VIEW_STATE = {
  longitude: 82,
  latitude: 22,
  zoom: 4.2,
  pitch: 0,
  bearing: 0,
};

interface TipState { x: number; y: number; count: number; score: number }

export function DesertMap() {
  const [data, setData]       = useState<PincodeData | null>(null);
  const [popData, setPopData] = useState<PopulationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [tip, setTip]         = useState<TipState | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch("/deserts/pincodes").then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
      fetch("/population").then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
    ])
      .then(([pins, pop]) => { setData(pins); setPopData(pop); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, []);

  if (loading) return (
    <div style={{ textAlign: "center", padding: "80px 20px", color: "#64748b", fontSize: 16 }}>
      Loading map data…
    </div>
  );
  if (error) return (
    <div style={{ textAlign: "center", padding: "80px 20px", color: "#ef4444" }}>
      Failed to load: {error}
    </div>
  );
  if (!data) return null;

  const totalPins  = data.total_pincodes;
  const highUrgency = data.pincodes.filter(p => p.need_score > 1.0).length;

  const layers = [
    // State borders — geographic context only, no fill
    popData && new GeoJsonLayer({
      id: "state-borders",
      data: popData.geojson,
      filled: false,
      stroked: true,
      getLineColor: [100, 116, 139, 140],
      lineWidthMinPixels: 0.6,
      pickable: false,
    }),

    // Need-score hexbins — the main data layer
    new HexagonLayer<PincodeEntry>({
      id: "need-hex",
      data: data.pincodes,
      getPosition: (d) => [d.lon, d.lat],
      getColorWeight: (d) => d.need_score,
      colorAggregation: "MEAN",
      colorRange: URGENCY_COLOR_RANGE,
      radius: 45000,        // 45 km hexagons
      coverage: 0.88,
      upperPercentile: 95,  // don't let Delhi alone set the top of the scale
      lowerPercentile: 5,
      extruded: false,
      pickable: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      onHover: ((info: any) => {
        if (info.object) {
          setTip({
            x: info.x,
            y: info.y,
            count: info.object.count ?? info.object.points?.length ?? 0,
            score: info.object.colorValue ?? 0,
          });
        } else {
          setTip(null);
        }
      }) as any,
    }),
  ].filter(Boolean);

  return (
    <div style={{ display: "flex", height: "calc(100vh - 160px)", minHeight: 500 }}>

      {/* ── Sidebar ── */}
      <div style={{
        width: 300, flexShrink: 0,
        background: "#fff", borderRight: "1px solid #e2e8f0",
        padding: "20px 16px", overflowY: "auto",
        display: "flex", flexDirection: "column", gap: 20,
      }}>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: "#1e293b", marginBottom: 4 }}>
            Medical Desert Map
          </h2>
          <p style={{ fontSize: 12, color: "#64748b", lineHeight: 1.6 }}>
            Each hexagon groups nearby PIN code areas. Colour shows how urgently
            those areas need better coverage — weighing both the gap in services
            <em> and </em>how many people actually live there.
          </p>
        </div>

        {/* Algorithm explanation */}
        <div style={{ background: "#f8fafc", borderRadius: 8, padding: "12px 14px", borderLeft: "3px solid #6366f1" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#4338ca", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            How the urgency score works
          </div>
          <p style={{ fontSize: 12, color: "#475569", lineHeight: 1.7, margin: 0 }}>
            For each PIN code area we compute:
          </p>
          <div style={{
            background: "#eef2ff", borderRadius: 6,
            padding: "8px 10px", margin: "8px 0",
            fontFamily: "monospace", fontSize: 11, color: "#3730a3",
            lineHeight: 1.6,
          }}>
            score = log(1 + density_ratio)<br />
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;× services_missing / 4
          </div>
          <p style={{ fontSize: 12, color: "#475569", lineHeight: 1.7, margin: 0 }}>
            <strong>density_ratio</strong> = local population density ÷ India's
            national average (382 people/km²). A Delhi PIN scores ~30×,
            Arunachal Pradesh ~0.04×.
          </p>
          <p style={{ fontSize: 12, color: "#475569", lineHeight: 1.7, margin: "6px 0 0" }}>
            <strong>Result:</strong> a village in the Himalayas missing all four
            services scores near zero. A dense district in Bihar or UP missing
            the same services scores high — because the gap affects far more people.
          </p>
        </div>

        {/* Colour legend */}
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            Hexagon colour — urgency score
          </div>
          <div style={{ display: "flex", gap: 3 }}>
            {URGENCY_COLOR_RANGE.map(([r, g, b], i) => (
              <div key={i} style={{ flex: 1, height: 12, background: `rgb(${r},${g},${b})`, borderRadius: 2 }} />
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
            <span style={{ fontSize: 10, color: "#94a3b8" }}>Low urgency</span>
            <span style={{ fontSize: 10, color: "#94a3b8" }}>High urgency</span>
          </div>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 5 }}>
            <LegendRow color="rgb(255,255,178)" label="Sparse area or good coverage — low concern" />
            <LegendRow color="rgb(253,141,60)"  label="Moderate gap in a reasonably populated area" />
            <LegendRow color="rgb(189,0,38)"    label="Critical — dense population, services missing" />
          </div>
        </div>

        {/* Services covered */}
        <div style={{ background: "#f8fafc", borderRadius: 8, padding: "10px 12px" }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
            Services checked
          </div>
          {["Oncology", "Emergency", "Trauma", "Dialysis"].map(s => (
            <div key={s} style={{ fontSize: 12, color: "#475569", padding: "2px 0" }}>
              · {s} — verified if any provider has trust ≥ 65
            </div>
          ))}
        </div>

        {/* Stats */}
        <div style={{ borderTop: "1px solid #f1f5f9", paddingTop: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 10 }}>
            Summary
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <StatRow label="PIN codes analysed"      value={totalPins.toLocaleString()} />
            <StatRow label="High-urgency PINs (score > 1)"
                     value={`${highUrgency.toLocaleString()} (${Math.round(highUrgency / totalPins * 100)}%)`}
                     highlight />
          </div>
          <p style={{ fontSize: 11, color: "#94a3b8", marginTop: 10, lineHeight: 1.5 }}>
            Each hexagon is ~45 km across. Hover to see
            the number of PIN codes inside and the average urgency score.
          </p>
        </div>
      </div>

      {/* ── Map ── */}
      <div style={{ flex: 1, position: "relative", background: "#e8edf2" }}>
        <DeckGL
          initialViewState={INITIAL_VIEW_STATE}
          controller={false}
          layers={layers as any}
          style={{ width: "100%", height: "100%" }}
        />
        {tip && (
          <div style={{
            position: "absolute",
            left: tip.x + 12,
            top: tip.y - 50,
            background: "#fff",
            border: "1px solid #e2e8f0",
            padding: "8px 12px",
            borderRadius: 6,
            boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
            fontSize: 12,
            pointerEvents: "none",
            lineHeight: 1.7,
          }}>
            <strong>{tip.count} PIN code{tip.count !== 1 ? "s" : ""}</strong> in this area<br />
            Avg urgency score: <strong>{tip.score.toFixed(2)}</strong>
          </div>
        )}
      </div>
    </div>
  );
}

function LegendRow({ color, label }: { color: string; label: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ width: 12, height: 12, borderRadius: 2, background: color, flexShrink: 0, border: "1px solid #e2e8f0" }} />
      <span style={{ fontSize: 11, color: "#64748b", lineHeight: 1.4 }}>{label}</span>
    </div>
  );
}

function StatRow({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
      <span style={{ fontSize: 12, color: "#475569" }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color: highlight ? "#ef4444" : "#1e293b", textAlign: "right" }}>{value}</span>
    </div>
  );
}
