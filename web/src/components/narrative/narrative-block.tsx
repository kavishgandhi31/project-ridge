/**
 * Narrative block with inline citation chips.
 *
 * Parses [N] markers in narrative text and renders them as
 * interactive citation chips. Clicking a chip shows a popover
 * with the underlying observation data.
 *
 * Handles two content formats:
 * - JSON (country_narrative template): {headline, narrative, key_risks, outlook}
 * - Plain text (alert_rationale, interactive_query): rendered directly
 *
 * Density-aware:
 * - Overview: headline only
 * - Analyst: full narrative with citation chips + key risks + outlook
 * - Research: + citation metadata table, grounding score
 */

"use client";

import { Fragment, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CitationChip } from "@/components/narrative/citation-chip";
import type { CitationDetail, DensityMode, Narrative } from "@/lib/types";
import { formatRelativeTime, formatPercent } from "@/lib/format";
import { AlertTriangle } from "lucide-react";

interface NarrativeBlockProps {
  narrative: Narrative;
  density: DensityMode;
  title?: string;
}

/** Structured JSON output from the country_narrative template. */
interface StructuredNarrative {
  headline: string;
  narrative: string;
  key_risks: string[];
  outlook: string;
}

type NarrativePart =
  | { type: "text"; value: string }
  | { type: "citation"; citation: CitationDetail };

/** Try to parse content as the structured JSON format. */
function tryParseStructured(content: string): StructuredNarrative | null {
  try {
    // Content might be wrapped in markdown code fences
    let jsonStr = content.trim();
    if (jsonStr.startsWith("```")) {
      jsonStr = jsonStr.replace(/^```(?:json)?\s*/, "").replace(/\s*```$/, "");
    }
    const parsed = JSON.parse(jsonStr);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof parsed.headline === "string" &&
      typeof parsed.narrative === "string"
    ) {
      return parsed as StructuredNarrative;
    }
  } catch {
    // Not JSON -- that's fine, render as plain text
  }
  return null;
}

/** Parse text content, splitting on [N] citation markers. */
function parseCitations(
  content: string,
  citations: CitationDetail[]
): NarrativePart[] {
  const citationMap = new Map(citations.map((c) => [c.ref_number, c]));
  const parts: NarrativePart[] = [];
  const regex = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", value: content.slice(lastIndex, match.index) });
    }

    const refNum = parseInt(match[1], 10);
    const citation = citationMap.get(refNum);
    if (citation) {
      parts.push({ type: "citation", citation });
    } else {
      parts.push({ type: "text", value: match[0] });
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    parts.push({ type: "text", value: content.slice(lastIndex) });
  }

  return parts;
}

/** Render parsed parts with citation chips inline. */
function RenderParts({ parts }: { parts: NarrativePart[] }) {
  return (
    <>
      {parts.map((part, i) =>
        part.type === "text" ? (
          <Fragment key={i}>{part.value}</Fragment>
        ) : (
          <CitationChip key={i} citation={part.citation} />
        )
      )}
    </>
  );
}

export function NarrativeBlock({
  narrative,
  density,
  title = "Country Narrative",
}: NarrativeBlockProps) {
  const structured = useMemo(
    () => tryParseStructured(narrative.content),
    [narrative.content]
  );

  const citations = narrative.citations_used;

  // Parse the appropriate text for citation rendering
  const narrativeParts = useMemo(() => {
    const text = structured?.narrative ?? narrative.content;
    return parseCitations(text, citations);
  }, [structured, narrative.content, citations]);

  const headlineParts = useMemo(() => {
    if (structured?.headline) {
      return parseCitations(structured.headline, citations);
    }
    return null;
  }, [structured, citations]);

  const outlookParts = useMemo(() => {
    if (structured?.outlook) {
      return parseCitations(structured.outlook, citations);
    }
    return null;
  }, [structured, citations]);

  const isResearch = density === "research";
  const showDetail = density !== "overview";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">{title}</CardTitle>
          <div className="flex items-center gap-2">
            {narrative.grounding_score >= 0.8 && (
              <Badge variant="outline" className="text-[10px] text-green-600 border-green-200">
                Grounded
              </Badge>
            )}
            <span className="text-[11px] text-muted-foreground">
              {formatRelativeTime(narrative.generated_at)}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Headline */}
        {headlineParts && (
          <p className="text-sm font-medium leading-snug">
            <RenderParts parts={headlineParts} />
          </p>
        )}

        {/* Narrative body -- always shown */}
        <div className="text-sm leading-relaxed whitespace-pre-wrap">
          <RenderParts parts={narrativeParts} />
        </div>

        {/* Key risks -- Analyst+ */}
        {showDetail && structured?.key_risks && structured.key_risks.length > 0 && (
          <div className="space-y-1.5">
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Key Risks
            </h4>
            <ul className="space-y-1">
              {structured.key_risks.map((risk, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0 text-amber-500" />
                  <span>
                    <RenderParts parts={parseCitations(risk, citations)} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Outlook -- Analyst+ */}
        {showDetail && outlookParts && (
          <div className="space-y-1">
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Outlook
            </h4>
            <p className="text-sm leading-relaxed">
              <RenderParts parts={outlookParts} />
            </p>
          </div>
        )}

        {/* Research: citation metadata */}
        {isResearch && (
          <div className="border-t pt-3 space-y-2">
            <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
              <span>
                Grounding: {formatPercent(narrative.grounding_score)}
              </span>
              <span>
                Citations: {narrative.citations_used.length}/{narrative.citations_available_count}
              </span>
              <span>Provider: {narrative.provider_id}</span>
              <span>Model: {narrative.model_id}</span>
              <span>Tokens: {narrative.tokens_in}in / {narrative.tokens_out}out</span>
              <span>Latency: {narrative.latency_ms}ms</span>
            </div>
            {narrative.ungrounded_claims.length > 0 && (
              <div className="text-[11px]">
                <span className="text-red-500 font-medium">Ungrounded claims: </span>
                <span className="text-muted-foreground">
                  {narrative.ungrounded_claims.join(", ")}
                </span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
