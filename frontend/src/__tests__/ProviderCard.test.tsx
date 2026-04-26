import React from "react";
import { render, screen } from "@testing-library/react";
import { ProviderCard } from "../components/ProviderCard";
import { Provider } from "../types";

const baseProvider: Provider = {
  provider_id: "abc123",
  name: "City Eye Hospital",
  facility_type: "Hospital",
  address: "12 MG Road, Bangalore",
  city: "Bangalore",
  phone: "+919876543210",
  email: "info@cityeye.in",
  website: "https://cityeye.in",
  specialties: ["ophthalmology", "optometry"],
  distance_km: 2.3,
  trust_score: 75,
  trust_signals: ["Valid phone", "Has own domain"],
  trust_penalties: [],
  live_verified: true,
  red_flags: [],
  why_this: "Specialist in cataract surgery with 15 years experience.",
  caveat: "",
  number_doctors: 5,
};

test("renders provider name", () => {
  render(<ProviderCard provider={baseProvider} rank={1} />);
  expect(screen.getByText("City Eye Hospital")).toBeInTheDocument();
});

test("renders trust score", () => {
  render(<ProviderCard provider={baseProvider} rank={1} />);
  expect(screen.getByText("75")).toBeInTheDocument();
});

test("renders live verified badge", () => {
  render(<ProviderCard provider={baseProvider} rank={1} />);
  expect(screen.getByText(/LIVE/)).toBeInTheDocument();
});

test("renders why_this text", () => {
  render(<ProviderCard provider={baseProvider} rank={1} />);
  expect(screen.getByText(/cataract surgery/i)).toBeInTheDocument();
});

test("renders caveat when present", () => {
  const p = { ...baseProvider, caveat: "1-doctor clinic — call ahead." };
  render(<ProviderCard provider={p} rank={1} />);
  expect(screen.getByText(/1-doctor clinic/)).toBeInTheDocument();
});

test("renders red flags when present", () => {
  const p = { ...baseProvider, red_flags: ["Phone mismatch detected"] };
  render(<ProviderCard provider={p} rank={1} />);
  expect(screen.getByText(/Phone mismatch/)).toBeInTheDocument();
});

test("does not show live badge when unverified", () => {
  const p = { ...baseProvider, live_verified: false };
  render(<ProviderCard provider={p} rank={1} />);
  expect(screen.queryByText(/LIVE/)).not.toBeInTheDocument();
});
