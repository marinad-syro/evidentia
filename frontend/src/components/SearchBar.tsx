import React, { useState } from "react";

interface Props {
  onSearch: (query: string) => void;
  loading: boolean;
}

export function SearchBar({ onSearch, loading }: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (value.trim().length >= 3) onSearch(value.trim());
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8 }}>
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="e.g. eye specialist near Koramangala"
        disabled={loading}
        style={{
          flex: 1,
          padding: "12px 16px",
          fontSize: 16,
          border: "2px solid #e2e8f0",
          borderRadius: 10,
          outline: "none",
          background: "#fff",
          transition: "border-color 0.15s",
        }}
        onFocus={(e) => (e.target.style.borderColor = "#3b82f6")}
        onBlur={(e) => (e.target.style.borderColor = "#e2e8f0")}
      />
      <button
        type="submit"
        disabled={loading || value.trim().length < 3}
        style={{
          padding: "12px 24px",
          fontSize: 15,
          fontWeight: 600,
          background: loading ? "#94a3b8" : "#3b82f6",
          color: "#fff",
          border: "none",
          borderRadius: 10,
          cursor: loading ? "not-allowed" : "pointer",
          transition: "background 0.15s",
          whiteSpace: "nowrap",
        }}
      >
        {loading ? "Searching…" : "Find Providers"}
      </button>
    </form>
  );
}
