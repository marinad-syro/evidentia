import React from "react";
import { render, screen } from "@testing-library/react";
import { ProgressFeed } from "../components/ProgressFeed";
import { Step } from "../types";

const steps: Step[] = [
  { id: "intent", status: "done", text: "Understanding your symptoms…", detail: "Mapped to: Ophthalmology" },
  { id: "geo", status: "active", text: "Locating Koramangala…", detail: "" },
  { id: "filter", status: "pending", text: "Searching nearby…", detail: "" },
];

test("renders all steps", () => {
  render(<ProgressFeed steps={steps} error={null} />);
  expect(screen.getByText("Understanding your symptoms…")).toBeInTheDocument();
  expect(screen.getByText("Locating Koramangala…")).toBeInTheDocument();
});

test("renders detail when present", () => {
  render(<ProgressFeed steps={steps} error={null} />);
  expect(screen.getByText("Mapped to: Ophthalmology")).toBeInTheDocument();
});

test("renders error message", () => {
  render(<ProgressFeed steps={[]} error="No providers found within 25 km." />);
  expect(screen.getByText(/No providers found/)).toBeInTheDocument();
});

test("renders nothing when no steps and no error", () => {
  const { container } = render(<ProgressFeed steps={[]} error={null} />);
  expect(container.firstChild).toBeNull();
});

test("shows DONE status for completed steps", () => {
  render(<ProgressFeed steps={steps} error={null} />);
  expect(screen.getByText("[DONE]")).toBeInTheDocument();
});

test("shows ACTIVE status for in-progress steps", () => {
  render(<ProgressFeed steps={steps} error={null} />);
  expect(screen.getByText("[ACTIVE]")).toBeInTheDocument();
});
