/**
 * Density mode context for progressive disclosure.
 *
 * Three modes control how much information is shown:
 * - overview: executive summary, minimal detail
 * - analyst: full working view with charts and dimensions
 * - research: everything including raw data tables and metadata
 *
 * Persisted in localStorage so it survives page refreshes.
 */

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import type { DensityMode } from "@/lib/types";

interface DensityContextValue {
  density: DensityMode;
  setDensity: (mode: DensityMode) => void;
  /** True if current density is at least the given level. */
  showAtLeast: (level: DensityMode) => boolean;
}

const DENSITY_KEY = "hornet-density-mode";
const DENSITY_LEVELS: Record<DensityMode, number> = {
  overview: 0,
  analyst: 1,
  research: 2,
};

const DensityContext = createContext<DensityContextValue>({
  density: "analyst",
  setDensity: () => {},
  showAtLeast: () => true,
});

export function useDensity(): DensityContextValue {
  return useContext(DensityContext);
}

export function useDensityProvider(): DensityContextValue {
  const [density, setDensityState] = useState<DensityMode>("analyst");

  useEffect(() => {
    const stored = localStorage.getItem(DENSITY_KEY);
    if (stored && stored in DENSITY_LEVELS) {
      setDensityState(stored as DensityMode);
    }
  }, []);

  const setDensity = useCallback((mode: DensityMode) => {
    setDensityState(mode);
    localStorage.setItem(DENSITY_KEY, mode);
  }, []);

  const showAtLeast = useCallback(
    (level: DensityMode) => DENSITY_LEVELS[density] >= DENSITY_LEVELS[level],
    [density]
  );

  return { density, setDensity, showAtLeast };
}

export { DensityContext };
