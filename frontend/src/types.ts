export interface Provider {
  provider_id: string;
  name: string;
  facility_type: string;
  address: string;
  city: string;
  phone: string;
  email: string;
  website: string;
  specialties: string[];
  distance_km: number;
  trust_score: number;
  trust_signals: string[];
  trust_penalties: string[];
  live_verified: boolean;
  red_flags: string[];
  why_this: string;
  caveat: string;
  number_doctors: number;
}

export interface SearchResults {
  providers: Provider[];
  specialty_interpreted: string;
  location_interpreted: string;
  radius_km: number;
  total_candidates: number;
}

export type StepStatus = "pending" | "active" | "done";

export interface Step {
  id: string;
  status: StepStatus;
  text: string;
  detail: string;
}
