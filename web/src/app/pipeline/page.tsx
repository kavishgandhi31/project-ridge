import { PipelineView } from "./pipeline-view";

export default function PipelinePage() {
  return (
    <div className="container mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Pipeline</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Recent pipeline runs and system health
        </p>
      </div>
      <PipelineView />
    </div>
  );
}
