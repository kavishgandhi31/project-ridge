/**
 * Theme context for switching between Light, Dark, Solarized Light/Dark.
 *
 * Persisted in localStorage. Applied via data-theme attribute on <html>.
 * To add a new theme: add CSS variables in globals.css, add to THEMES here.
 */

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

export type ThemeId = "light" | "dark" | "solarized-light" | "solarized-dark";

export interface ThemeOption {
  id: ThemeId;
  label: string;
  /** Preview colors: [background, foreground, accent] */
  preview: [string, string, string];
}

export const THEMES: ThemeOption[] = [
  { id: "light", label: "Light", preview: ["#ffffff", "#1a1a1a", "#f4f4f5"] },
  { id: "dark", label: "Dark", preview: ["#262626", "#fafafa", "#3f3f46"] },
  { id: "solarized-light", label: "Solarized Light", preview: ["#fdf6e3", "#073642", "#eee8d5"] },
  { id: "solarized-dark", label: "Solarized Dark", preview: ["#002b36", "#839496", "#073642"] },
];

const THEME_KEY = "ridge-theme";

interface ThemeContextValue {
  theme: ThemeId;
  setTheme: (id: ThemeId) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "light",
  setTheme: () => {},
});

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

export function useThemeProvider(): ThemeContextValue {
  const [theme, setThemeState] = useState<ThemeId>("light");

  useEffect(() => {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored && THEMES.some((t) => t.id === stored)) {
      setThemeState(stored as ThemeId);
      document.documentElement.setAttribute("data-theme", stored);
    }
  }, []);

  const setTheme = useCallback((id: ThemeId) => {
    setThemeState(id);
    localStorage.setItem(THEME_KEY, id);
    document.documentElement.setAttribute("data-theme", id);
  }, []);

  return { theme, setTheme };
}

export { ThemeContext };
