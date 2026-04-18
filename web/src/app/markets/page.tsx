import { MarketsView } from "./markets-view";

export default function MarketsPage() {
  return (
    <div className="container mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Markets</h1>
        <p className="text-sm text-muted-foreground mt-1">
          US Treasury yields, commodities, and market signals
        </p>
      </div>
      <MarketsView />
    </div>
  );
}
