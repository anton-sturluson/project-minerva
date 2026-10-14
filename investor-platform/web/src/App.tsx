import { useEffect, useState } from "react";
import { Portfolio } from "./Portfolio";
import { Research } from "./Research";

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
function currentPage(): Page {
  return location.hash === "#activity"
    ? "activity"
    : location.hash === "#post-mortem"
      ? "post-mortem"
      : location.hash === "#research"
        ? "research"
        : "portfolio";
}

export function App() {
  const [page, setPage] = useState<Page>(currentPage);
  useEffect(() => {
    const navigate = () => setPage(currentPage());
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
      <a className="skip-link" href={`#${page}`}>
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
        {page === "research" && <Research />}
      </main>
      <footer className="page-footer">
        <a href={`#${page}`}>Back to top ↑</a>
      </footer>
    </div>
  );
}
