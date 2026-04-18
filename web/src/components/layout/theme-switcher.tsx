/**
 * Theme switcher dropdown in the top nav.
 *
 * Shows 4 theme options with color preview dots.
 */

"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useTheme, THEMES } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { Palette } from "lucide-react";

export function ThemeSwitcher() {
  const { theme, setTheme } = useTheme();

  return (
    <Popover>
      <PopoverTrigger
        aria-label="Change theme"
        className="inline-flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
      >
        <Palette className="h-4 w-4" />
      </PopoverTrigger>
      <PopoverContent className="w-44 p-1.5" side="bottom" align="end">
        <div className="space-y-0.5">
          {THEMES.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTheme(t.id)}
              className={cn(
                "flex items-center gap-2.5 w-full rounded-md px-2.5 py-2 text-xs transition-colors",
                theme === t.id
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
              )}
            >
              {/* Color preview dots */}
              <div className="flex gap-0.5">
                {t.preview.map((color, i) => (
                  <span
                    key={i}
                    className="h-3 w-3 rounded-full border border-border/50"
                    style={{ backgroundColor: color }}
                  />
                ))}
              </div>
              {t.label}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
