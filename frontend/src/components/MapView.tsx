import React, { useState, useRef, useEffect } from "react";
import { MapContainer, TileLayer, Marker, useMap } from "react-leaflet";
import L from "leaflet";
import { SearchResults, Provider } from "../types";
import { ProviderCard } from "./ProviderCard";

function pinColor(score: number): string {
  if (score >= 70) return "#22c55e";
  if (score >= 40) return "#f59e0b";
  return "#ef4444";
}

function makePinIcon(score: number, rank: number, selected: boolean): L.DivIcon {
  const color = pinColor(score);
  const size = selected ? 30 : 24;
  return L.divIcon({
    html: `<div style="
      width:${size}px;height:${size}px;border-radius:50%;
      background:${color};border:2.5px solid #fff;
      box-shadow:${selected ? "0 2px 8px rgba(0,0,0,0.35)" : "0 1px 4px rgba(0,0,0,0.22)"};
      display:flex;align-items:center;justify-content:center;
      font-size:${selected ? 12 : 10}px;font-weight:700;color:#fff;cursor:pointer;
    ">${rank}</div>`,
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function MapController({
  providers,
  selectedIdx,
  userLocation,
}: {
  providers: Provider[];
  selectedIdx: number;
  userLocation: { lat: number; lon: number } | null;
}) {
  const map = useMap();
  const initialized = useRef(false);

  useEffect(() => {
    const valid = providers.filter((p) => p.latitude && p.longitude);

    if (!initialized.current) {
      initialized.current = true;
      if (valid.length > 0) {
        const bounds = L.latLngBounds(
          valid.map((p) => [p.latitude, p.longitude] as [number, number]),
        );
        if (userLocation) bounds.extend([userLocation.lat, userLocation.lon]);
        map.fitBounds(bounds, { padding: [60, 50] });
      }
      return;
    }

    const p = providers[selectedIdx];
    if (p?.latitude && p?.longitude) {
      map.flyTo([p.latitude, p.longitude], 15, { duration: 0.7 });
    }
  }, [selectedIdx, map]);

  return null;
}

interface Props {
  results: SearchResults;
  userLocation: { lat: number; lon: number } | null;
}

export function MapView({ results, userLocation }: Props) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  const { providers } = results;

  useEffect(() => {
    cardRefs.current[selectedIdx]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedIdx]);

  const defaultCenter: [number, number] = userLocation
    ? [userLocation.lat, userLocation.lon]
    : [19.076, 72.877];

  return (
    <div style={{ display: "flex", height: "70vh", minHeight: 520, borderTop: "1px solid #e2e8f0" }}>

      {/* ── Left sidebar ── */}
      <div style={{
        width: 390,
        overflowY: "auto",
        background: "#f8fafc",
        borderRight: "1px solid #e2e8f0",
        flexShrink: 0,
      }}>
        {/* Summary header */}
        <div style={{
          padding: "12px 20px 10px",
          borderBottom: "1px solid #e2e8f0",
          position: "sticky",
          top: 0,
          background: "#f8fafc",
          zIndex: 10,
        }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#1e293b" }}>
            {providers.length} provider{providers.length !== 1 ? "s" : ""} found
          </span>
          {results.specialty_interpreted && (
            <span style={{ fontSize: 12, color: "#64748b" }}>
              {" "}· {results.specialty_interpreted}
              {results.location_interpreted && ` near ${results.location_interpreted}`}
            </span>
          )}
          <div style={{ marginTop: 6, display: "flex", gap: 10, fontSize: 11, color: "#94a3b8" }}>
            {[["#22c55e", "High trust"], ["#f59e0b", "Medium"], ["#ef4444", "Low"]].map(([c, label]) => (
              <span key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: c, display: "inline-block" }} />
                {label}
              </span>
            ))}
          </div>
        </div>

        {/* Provider cards */}
        {providers.map((p, i) => (
          <div
            key={p.provider_id}
            ref={(el) => { cardRefs.current[i] = el; }}
            onClick={() => setSelectedIdx(i)}
            style={{
              padding: "10px 12px 10px 24px",
              borderLeft: i === selectedIdx ? "3px solid #3b82f6" : "3px solid transparent",
              background: i === selectedIdx ? "#fff" : "transparent",
              cursor: "pointer",
              transition: "background 0.12s",
            }}
          >
            <ProviderCard provider={p} rank={i + 1} compact />
          </div>
        ))}
      </div>

      {/* ── Map ── */}
      <div style={{ flex: 1, position: "relative" }}>
        <MapContainer
          center={defaultCenter}
          zoom={12}
          style={{ width: "100%", height: "100%" }}
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          />
          <MapController
            providers={providers}
            selectedIdx={selectedIdx}
            userLocation={userLocation}
          />

          {/* User location dot */}
          {userLocation && (
            <Marker
              position={[userLocation.lat, userLocation.lon]}
              icon={L.divIcon({
                html: `<div style="width:14px;height:14px;border-radius:50%;background:#3b82f6;border:3px solid #fff;box-shadow:0 0 0 4px rgba(59,130,246,0.25)"></div>`,
                className: "",
                iconSize: [14, 14],
                iconAnchor: [7, 7],
              })}
            />
          )}

          {/* Provider pins */}
          {providers.map((p, i) =>
            p.latitude && p.longitude ? (
              <Marker
                key={p.provider_id}
                position={[p.latitude, p.longitude]}
                icon={makePinIcon(p.trust_score, i + 1, i === selectedIdx)}
                eventHandlers={{ click: () => setSelectedIdx(i) }}
              />
            ) : null,
          )}
        </MapContainer>
      </div>
    </div>
  );
}
