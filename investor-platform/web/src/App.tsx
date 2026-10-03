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
        <span>PERSONAL WORKSPACE</span>
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
        <p className="welcome">WELCOME TO THE WORLD WIDE WEB OF</p>
        <a className="wordmark" href="/" aria-label="Minerva home">
          minerva!
        </a>
        <p className="subtitle">the patient investor’s home page</p>
      </header>
      <nav className="main-nav" aria-label="Main navigation">
        <a href="#portfolio">[ Portfolio ]</a>
        <a href="#performance">[ Performance ]</a>
        <a href="#decisions">[ Decisions ]</a>
        <a href="#research">[ Research ]</a>
      </nav>
      <div className="welcome-strip">
        A little capital. A lot of questions. Est. 2026.
      </div>
      <main id="main">
        <Portfolio />
        <div className="directory" aria-label="Planned capabilities">
          <section id="research" aria-labelledby="research-heading">
            <div className="directory-heading">
              <h2 id="research-heading">
                <span aria-hidden="true">✳ </span>Research
              </h2>
              <span className="planned">Planned</span>
            </div>
            <p>
              Sources, notes, and investment theses.
              <br />
              Keep the thinking behind each decision.
            </p>
            <p className="directory-note">
              A notebook for the evidence and the counter-case.
            </p>
          </section>
        </div>
      </main>
      <div className="badges" aria-label="Workspace motto">
        <span className="web-badge">
          100%
          <br />
          CURIOUS
        </span>
        <span className="web-badge">
          THINK
          <br />
          LONG TERM
        </span>
        <span className="web-badge">
          PERSONAL
          <br />
          EDITION
        </span>
      </div>
      <footer className="page-footer">
        <span>MINERVA</span>
        <span>Clarity before complexity.</span>
        <a href="#top">Back to top ↑</a>
      </footer>
    </div>
  );
}
