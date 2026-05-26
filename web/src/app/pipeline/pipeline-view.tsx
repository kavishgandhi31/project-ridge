/**
 * Pipeline runs view -- shows recent pipeline executions.
 */

"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { usePipelineRuns } from "@/lib/api/hooks";
import { formatDateTime, formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";

function statusIcon(status: string) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-4 w-4 text-green-500" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-red-500" />;
    case "running":
      return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
    default:
      return null;
  }
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    completed: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
    failed: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    running: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  };
  return colors[status] ?? "bg-muted text-muted-foreground";
}

export function PipelineView() {
  const { data: runs, isLoading } = usePipelineRuns({ limit: 20 });

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-20 rounded-xl bg-muted animate-pulse" />
        ))}
      </div>
    );
  }

  if (!runs || runs.length === 0) {
    return (
      <p className="text-center text-sm text-muted-foreground py-12">
        No pipeline runs found.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {runs.map((run) => (
        <Card key={run.run_id}>
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              {statusIcon(run.status)}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs text-muted-foreground">
                    {run.run_id.slice(0, 8)}
                  </span>
                  <Badge variant="secondary" className={cn("text-[10px]", statusBadge(run.status))}>
                    {run.status}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">
                    {run.run_type}
                  </Badge>
                </div>

                <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                  <span>Started: {formatDateTime(run.started_at)}</span>
                  {run.completed_at && (
                    <span>Completed: {formatRelativeTime(run.completed_at)}</span>
                  )}
                </div>

                <div className="flex items-center gap-4 mt-1.5 text-xs">
                  <span>{run.n_countries_scored} countries scored</span>
                  {run.n_escalate > 0 && (
                    <span className="text-red-600 dark:text-red-400">
                      {run.n_escalate} escalate
                    </span>
                  )}
                  {run.n_alert > 0 && (
                    <span className="text-amber-600 dark:text-amber-400">
                      {run.n_alert} alert
                    </span>
                  )}
                  {run.n_watch > 0 && (
                    <span className="text-blue-600 dark:text-blue-400">
                      {run.n_watch} watch
                    </span>
                  )}
                </div>

                {run.stages_completed.length > 0 && (
                  <div className="flex gap-1 mt-2">
                    {run.stages_completed.map((stage) => (
                      <Badge key={stage} variant="outline" className="text-[10px]">
                        {stage}
                      </Badge>
                    ))}
                  </div>
                )}

                {run.error_message && (
                  <p className="mt-2 text-xs text-red-500 truncate">
                    {run.error_message}
                  </p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
