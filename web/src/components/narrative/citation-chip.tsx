/**
 * Inline citation chip that appears in narrative text.
 *
 * Renders as a small numbered badge [1]. On click, shows a popover
 * with the full observation detail: indicator, value, date, source.
 *
 * This is the core UX element for grounded AI -- every number
 * the LLM produces links back to its source observation.
 */

"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { CitationDetail } from "@/lib/types";
import { formatDate, formatObservationValue } from "@/lib/format";

interface CitationChipProps {
  citation: CitationDetail;
}

export function CitationChip({ citation }: CitationChipProps) {
  return (
    <Popover>
      <PopoverTrigger className="inline-flex items-center justify-center h-4 min-w-4 px-1 mx-0.5 rounded text-[10px] font-semibold tabular-nums bg-primary/10 text-primary hover:bg-primary/20 transition-colors cursor-pointer align-super leading-none">
        {citation.ref_number}
      </PopoverTrigger>
      <PopoverContent className="w-72 p-3" side="top">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs font-semibold">
              [{citation.ref_number}]
            </span>
            <span className="text-[10px] text-muted-foreground">
              {citation.source_id}
            </span>
          </div>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Indicator</span>
              <span className="font-mono text-xs">{citation.indicator_code}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Value</span>
              <span className="font-semibold tabular-nums">
                {formatObservationValue(citation.value, citation.indicator_code)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Date</span>
              <span>{formatDate(citation.date)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Vintage</span>
              <span className="text-xs">{formatDate(citation.vintage)}</span>
            </div>
          </div>
          {citation.display_label && (
            <p className="text-[11px] text-muted-foreground border-t pt-2">
              {citation.display_label}
            </p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
