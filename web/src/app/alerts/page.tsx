import { AlertFeed } from "./alert-feed";

export default function AlertsPage() {
  return (
    <div className="container mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Alerts</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Countries flagged by the alert engine, ordered by severity
        </p>
      </div>
      <AlertFeed />
    </div>
  );
}
