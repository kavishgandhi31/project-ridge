import { CountryGrid } from "@/components/country/country-grid";

export default function HomePage() {
  return (
    <div className="container mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Macro risk scores across all monitored countries
        </p>
      </div>
      <CountryGrid />
    </div>
  );
}
