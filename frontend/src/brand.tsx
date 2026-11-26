import { Monitor, Moon, Sun } from "lucide-react";
import { useState } from "react";
import mark from "./assets/kronshield-mark.svg";

const storageKey = "kronshield.theme";
const themes = ["dark", "light", "system"] as const;
type Theme = (typeof themes)[number];

function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(storageKey);
    return themes.find((theme) => theme === saved) ?? "dark";
  } catch {
    return "dark";
  }
}

document.documentElement.dataset.theme = initialTheme();

export function ThemeControl() {
  const [theme, setTheme] = useState<Theme>(() =>
    themes.find((choice) => choice === document.documentElement.dataset.theme) ?? initialTheme());
  const Icon = theme === "light" ? Sun : theme === "system" ? Monitor : Moon;
  return <label className="theme-control">
    <Icon size={16} aria-hidden="true" />
    <select aria-label="Tema" value={theme} onChange={(event) => {
      const next = themes.find((choice) => choice === event.currentTarget.value);
      if (!next) return;
      setTheme(next);
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem(storageKey, next); } catch { /* The current document still updates. */ }
    }}>
      <option value="dark">Oscuro</option>
      <option value="light">Claro</option>
      <option value="system">Sistema</option>
    </select>
  </label>;
}

export function Brand() {
  return <div className="brand">
    <img src={mark} alt="" width="44" height="44" />
    <div><strong>KronShield</strong><span>Intelligent Cybersecurity</span></div>
  </div>;
}
