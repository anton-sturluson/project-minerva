import { useEffect, useState } from "react";
import { Portfolio } from "./Portfolio";
import { Research } from "./research/Research";

type Theme = "system" | "light" | "dark";
function savedTheme(): Theme {
  try {
    const value = localStorage.getItem("minerva-theme");
    if (value === "light" || value === "dark") return value;
  } catch {
    /* Storage can be disabled; the switch still works for this visit. */
  }
  return "system";
}
function applyTheme(value: Theme) {
  document.documentElement.dataset.theme = value;
  document.documentElement.style.colorScheme =
    value === "system" ? "light dark" : value;
}
const initialTheme = savedTheme();
// Apply before React renders to avoid flashing the wrong stored theme on reload.
applyTheme(initialTheme);

export type Page = "portfolio" | "activity" | "research" | "post-mortem";
function currentPage(hash: string): Page {
  if (hash === "#financials") return "post-mortem";
  return hash === "#activity"
    ? "activity"
    : hash === "#post-mortem"
      ? "post-mortem"
      : hash === "#research" ||
          hash === "#research/activity" ||
          hash === "#research/economics"
        ? "research"
        : "portfolio";
}

export function App() {
  const [hash, setHash] = useState(() => location.hash);
  const page = currentPage(hash);
  const contentHash = page === "research" ? hash : `#${page}`;
  useEffect(() => {
    const navigate = () => {
      if (location.hash === "#financials") {
        history.replaceState(null, "", "#post-mortem");
      }
      setHash(location.hash);
    };
    navigate();
    window.addEventListener("hashchange", navigate);
    return () => window.removeEventListener("hashchange", navigate);
  }, []);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  function changeTheme(value: Theme) {
    setTheme(value);
    applyTheme(value);
    try {
      localStorage.setItem("minerva-theme", value);
    } catch {
      /* Optional persistence. */
    }
  }
  return (
    <div className="workspace" id="top">
      <a className="skip-link" href={contentHash}>
        Skip to content
      </a>
      <header className="site-header">
        <a className="wordmark" href="#portfolio" aria-label="Minerva home">
          minerva!
        </a>
        <nav className="main-nav" aria-label="Main navigation">
          <a
            href="#portfolio"
            aria-current={page === "portfolio" ? "page" : undefined}
          >
            [ Portfolio ]
          </a>
          <a href="#performance">[ Performance ]</a>
          <a
            href="#post-mortem"
            aria-current={page === "post-mortem" ? "page" : undefined}
          >
            [ Post-mortem ]
          </a>
          <a
            href="#activity"
            aria-current={page === "activity" ? "page" : undefined}
          >
            [ Activity ]
          </a>
          <a
            href="#research"
            aria-current={page === "research" ? "page" : undefined}
          >
            [ Research ]
          </a>
        </nav>
        <label className="theme-picker">
          Theme{" "}
          <select
            aria-label="Theme"
            value={theme}
            onChange={(e) => changeTheme(e.target.value as Theme)}
          >
            <option value="system">System</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </label>
      </header>
      <main id="main">
        <div hidden={page === "research"}>
          <Portfolio page={page} />
        </div>
        {page === "research" && (
          <Research
            activity={hash === "#research/activity"}
            economics={hash === "#research/economics"}
          />
        )}
      </main>
      <footer className="page-footer">
        <a href={contentHash}>Back to top ↑</a>
      </footer>
    </div>
  );
}
