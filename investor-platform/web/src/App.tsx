import { useState } from "react";
import { Portfolio } from "./Portfolio";

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

export function App() {
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
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="edition-line">
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
      </div>
      <header className="masthead">
        <a className="wordmark" href="/" aria-label="Minerva home">
          minerva!
        </a>
      </header>
      <nav className="main-nav" aria-label="Main navigation">
        <a href="#portfolio">[ Portfolio ]</a>
        <a href="#performance">[ Performance ]</a>
        <a href="#decisions">[ Decisions ]</a>
        <a href="#research">[ Research ]</a>
      </nav>
      <main id="main">
        <Portfolio />
        <div className="directory" aria-label="Planned capabilities">
          <section id="research" aria-labelledby="research-heading">
            <div className="directory-heading">
              <h2 id="research-heading">
                <span aria-hidden="true">✳ </span>Research
              </h2>
              <span className="planned">Coming soon</span>
            </div>
          </section>
        </div>
      </main>
      <footer className="page-footer">
        <a href="#top">Back to top ↑</a>
      </footer>
    </div>
  );
}
