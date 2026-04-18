/**
 * Client-side providers: TanStack Query + Density + Theme + Tooltip.
 *
 * Wrapped in a single component so the root layout stays a
 * Server Component (only this file has "use client").
 */

"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { DensityContext, useDensityProvider } from "@/lib/density";
import { ThemeContext, useThemeProvider } from "@/lib/theme";
import { TooltipProvider } from "@/components/ui/tooltip";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: true,
          },
        },
      })
  );

  const densityValue = useDensityProvider();
  const themeValue = useThemeProvider();

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeContext value={themeValue}>
        <DensityContext value={densityValue}>
          <TooltipProvider delay={200}>
            {children}
          </TooltipProvider>
        </DensityContext>
      </ThemeContext>
    </QueryClientProvider>
  );
}
