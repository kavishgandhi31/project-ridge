/**
 * Top navigation bar.
 *
 * Fixed at top. Contains: logo/brand, page links, density toggle, health indicator.
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DensityToggle } from "@/components/density/density-toggle";
import { ThemeSwitcher } from "@/components/layout/theme-switcher";
import { useHealth } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { Activity } from "lucide-react";

const NAV_LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/alerts", label: "Alerts" },
  { href: "/markets", label: "Markets" },
  { href: "/pipeline", label: "Pipeline" },
];

export function TopNav() {
  const pathname = usePathname();
  const { data: health } = useHealth();

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-14 items-center px-4 gap-6">
        {/* Brand */}
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="text-lg">Ridge</span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-1">
          {NAV_LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "px-3 py-1.5 text-sm rounded-md transition-colors",
                isActive(href)
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
              )}
            >
              {label}
            </Link>
          ))}
        </nav>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Density toggle */}
        <DensityToggle />

        {/* Theme switcher */}
        <ThemeSwitcher />

        {/* Health indicator */}
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Activity className="h-3.5 w-3.5" />
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              health?.status === "ok"
                ? "bg-green-500"
                : health?.status === "degraded"
                  ? "bg-amber-500"
                  : "bg-muted"
            )}
          />
        </div>
      </div>
    </header>
  );
}
