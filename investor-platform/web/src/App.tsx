import { useCallback, useEffect, useRef, useState } from "react";

import { Portfolio } from "./Portfolio";

type Connection = "checking" | "online" | "offline";

export function App() {
  const [connection, setConnection] = useState<Connection>("checking");
  const [checking, setChecking] = useState(false);
  const request = useRef<AbortController | null>(null);

  const checkConnection = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setChecking(true);
    const timeout = window.setTimeout(() => controller.abort(), 3000);
    try {
      const response = await fetch("/api/health", {
        signal: controller.signal,
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Service unavailable");
      const data: unknown = await response.json();
      if (
        typeof data !== "object" ||
        data === null ||
        !("status" in data) ||
        data.status !== "ok" ||
        !("service" in data) ||
        data.service !== "investor-platform"
      )
        throw new Error("Unexpected service response");
      if (request.current === controller) setConnection("online");
    } catch {
      if (request.current === controller) setConnection("offline");
    } finally {
      window.clearTimeout(timeout);
      if (request.current === controller) {
        request.current = null;
        setChecking(false);
      }
    }
  }, []);

  useEffect(() => {
    void checkConnection();
    const timer = window.setInterval(() => void checkConnection(), 5000);
    return () => {
      window.clearInterval(timer);
      const current = request.current;
      request.current = null;
      current?.abort();
    };
  }, [checkConnection]);

  const status =
    connection === "online"
      ? "Connected"
      : connection === "offline"
        ? "Disconnected"
        : "Connecting";

  return (
    <div className="workspace" id="top">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="edition-line">
        <span>PERSONAL WORKSPACE</span>
        <span>LOCAL EDITION</span>
      </div>
      <header className="masthead">
        <p className="welcome">WELCOME TO THE WORLD WIDE WEB OF</p>
        <a className="wordmark" href="/" aria-label="Minerva home">
          minerva!
        </a>
        <p className="subtitle">the patient investor’s home page</p>
      </header>
      <nav className="main-nav" aria-label="Main navigation">
        <a href="#main" aria-current="page">
          [ Overview ]
        </a>
        <a href="#portfolio">[ Portfolio ]</a>
        <a href="#research">[ Research ]</a>
      </nav>
      <div className="welcome-strip">
        A little capital. A lot of questions. Est. 2026.
      </div>
      <main id="main">
        <div className="home-grid">
          <section
            className="workspace-intro"
            aria-labelledby="workspace-heading"
          >
            <h1 id="workspace-heading">Your investment workspace.</h1>
            <p className="intro">
              A place to keep the record of what you own, and the thinking
              behind each decision.
            </p>
            <section
              className={"connection " + connection}
              aria-labelledby="connection-heading"
            >
              <div className="connection-heading">
                <h2 id="connection-heading">The local connection</h2>
                <span className="status">
                  <span className="status-symbol" aria-hidden="true">
                    {connection === "online"
                      ? "✓"
                      : connection === "offline"
                        ? "!"
                        : "·"}
                  </span>
                  <span role="status" aria-live="polite">
                    {status}
                  </span>
                </span>
              </div>
              <p>
                {connection === "online"
                  ? "Your local workspace is connected."
                  : connection === "offline"
                    ? "Your local workspace is offline."
                    : "Connecting to your workspace."}
              </p>
              <p className="connection-detail">
                {connection === "online"
                  ? "Your local service is ready. Open your portfolio below."
                  : connection === "offline"
                    ? "Check that the local service is running, then try again."
                    : "Checking the connection to your local service."}
              </p>
              <button
                type="button"
                onClick={() => void checkConnection()}
                disabled={checking}
              >
                {checking ? "Checking…" : "Check connection"}
              </button>
            </section>
          </section>
          <aside className="notebook-margin" aria-labelledby="margin-heading">
            <span className="margin-label">ON THE DRAWING BOARD</span>
            <h2 id="margin-heading">
              A home for <br />
              patient capital.
            </h2>
            <p>
              Start with a clear record.
              <br />
              Keep the questions open.
            </p>
            <hr />
            <h3>Places to grow</h3>
            <p>
              <a href="#portfolio">Portfolio records</a>
              <br />
              <a href="#research">The research notebook</a>
            </p>
            <p className="small-note">
              Research is planned.
              <br />
              Your workspace starts here.
            </p>
          </aside>
        </div>
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
