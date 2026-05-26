/**
 * "Ask a Question" panel for grounded queries.
 *
 * Visible in all density modes:
 * - Overview: compact single-line input
 * - Analyst/Research: full panel with conversation history
 *
 * Pre-fetches country context on mount via GET /ask/warmup/{iso3}
 * so the LLM call starts immediately when the user submits.
 */

"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CitationChip } from "@/components/narrative/citation-chip";
import { useDensity } from "@/lib/density";
import type { CitationDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { MessageCircleQuestion, Send, Loader2, CheckCircle2 } from "lucide-react";

interface AskPanelProps {
  countryIso3: string;
  countryName: string;
}

interface AskResponse {
  content: string;
  citations_used: CitationDetail[];
  grounding_score: number;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: CitationDetail[];
  grounding_score?: number;
}

/** Parse response content, splitting on [N] citation markers. */
function parseContent(
  content: string,
  citations: CitationDetail[]
): Array<{ type: "text"; value: string } | { type: "citation"; citation: CitationDetail }> {
  const citationMap = new Map(citations.map((c) => [c.ref_number, c]));
  const parts: Array<{ type: "text"; value: string } | { type: "citation"; citation: CitationDetail }> = [];
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

export function AskPanel({ countryIso3, countryName }: AskPanelProps) {
  const { density } = useDensity();
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contextReady, setContextReady] = useState(false);

  // Pre-fetch context on mount. The parent passes key={iso3} so the
  // component remounts on country change -- no separate reset effect needed.
  useEffect(() => {
    fetch(`/api/proxy/ask/warmup/${countryIso3}`)
      .then((res) => {
        if (res.ok) setContextReady(true);
      })
      .catch(() => {
        // Warmup failed -- ask endpoint will build context on demand
      });
  }, [countryIso3]);

  const handleSubmit = useCallback(async () => {
    const q = question.trim();
    if (!q || isLoading) return;

    setQuestion("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setIsLoading(true);

    try {
      const res = await fetch("/api/proxy/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          country_iso3: countryIso3,
        }),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`API returned ${res.status}: ${text}`);
      }

      const data: AskResponse = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.content,
          citations: data.citations_used,
          grounding_score: data.grounding_score,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get response");
    } finally {
      setIsLoading(false);
    }
  }, [question, isLoading, countryIso3]);

  const isCompact = density === "overview";

  return (
    <Card className="h-full">
      <CardHeader className={cn("pb-2", isCompact && "pb-1")}>
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <MessageCircleQuestion className="h-4 w-4" />
          Ask about {countryName}
          {contextReady && (
            <CheckCircle2 className="h-3 w-3 text-green-500 ml-auto" />
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className={cn("space-y-3", isCompact && "pb-3")}>
        {/* Message history */}
        {messages.length > 0 && (
          <div className="space-y-3 max-h-96 overflow-y-auto">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={cn(
                  "text-sm",
                  msg.role === "user"
                    ? "text-foreground font-medium"
                    : "text-muted-foreground"
                )}
              >
                {msg.role === "user" ? (
                  <p>{msg.content}</p>
                ) : (
                  <div className="whitespace-pre-wrap leading-relaxed">
                    {parseContent(msg.content, msg.citations ?? []).map(
                      (part, j) =>
                        part.type === "text" ? (
                          <Fragment key={j}>{part.value}</Fragment>
                        ) : (
                          <CitationChip key={j} citation={part.citation} />
                        )
                    )}
                  </div>
                )}
              </div>
            ))}
            {isLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Thinking...
              </div>
            )}
          </div>
        )}

        {error && (
          <p className="text-xs text-red-500">{error}</p>
        )}

        {/* Input */}
        <div className="flex gap-2">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            placeholder="e.g. What's driving inflation?"
            className="flex-1 h-9 rounded-md border bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            disabled={isLoading}
          />
          <Button
            size="sm"
            onClick={handleSubmit}
            disabled={isLoading || !question.trim()}
            className="h-9 px-3"
          >
            <Send className="h-3.5 w-3.5" />
          </Button>
        </div>

        {messages.length === 0 && !isCompact && (
          <p className="text-xs text-muted-foreground">
            Ask any question about {countryName}. Answers are grounded in
            the latest observation data with inline citations.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
