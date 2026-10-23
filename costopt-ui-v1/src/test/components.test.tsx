import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataTable, StatusBadge } from "../components/ui";

describe("shared components", () => {
  it("renders accessible status text", () => {
    render(<StatusBadge status="needs_attention" />);
    expect(screen.getByText("Needs Attention")).toBeInTheDocument();
  });

  it("renders data and an accessible table name", () => {
    render(<DataTable rows={[{ id: "1", name: "Alpha" }]} columns={[{ key: "name", label: "Name", value: (row) => row.name, sortValue: (row) => row.name }]} ariaLabel="Example records" />);
    expect(screen.getByRole("table", { name: "Example records" })).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });
});
