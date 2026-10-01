import { useCallback, useEffect, useRef, useState } from "react";

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
    <div className="workspace">
      <aside className="sidebar" aria-label="Workspace">
        <a className="brand" href="/" aria-label="Minerva home">
          <span className="brand-mark" aria-hidden="true">
            m
          </span>
          <span>
            minerva<span className="brand-caption">INVESTOR WORKSPACE</span>
          </span>
        </a>
        <div className="sidebar-label">YOUR WORKSPACE</div>
        <nav aria-label="Main navigation">
          <a className="nav-item active" href="/" aria-current="page">
            <span aria-hidden="true">◫</span> Overview{" "}
            <span className="nav-arrow" aria-hidden="true">
              ↗
            </span>
          </a>
        </nav>
        <div className="sidebar-bottom">
          <span className="local-dot" aria-hidden="true" />
          <div>
            Local workspace<small>On your computer</small>
          </div>
          <span className="avatar" aria-hidden="true">
            M
          </span>
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <span>
            Workspace <span className="breadcrumb">/</span>{" "}
            <strong>Overview</strong>
          </span>
          <span className="local-badge">LOCAL</span>
        </header>
        <main id="main">
          <div className="eyebrow">A PLACE FOR THE BIG PICTURE</div>
          <h1>Your investment workspace.</h1>
          <p className="intro">
            A considered home for your portfolio, your research,
            <br className="desktop-break" /> and the decisions that connect
            them.
          </p>

          <section
            className={"connection-card " + connection}
            aria-labelledby="connection-heading"
          >
            <div className="connection-icon" aria-hidden="true">
              {connection === "online"
                ? "✓"
                : connection === "offline"
                  ? "!"
                  : "·"}
            </div>
            <div className="connection-copy">
              <h2 id="connection-heading">
                {connection === "online"
                  ? "Your local workspace is connected."
                  : connection === "offline"
                    ? "Your local workspace is offline."
                    : "Connecting to your workspace."}
              </h2>
              <p>
                {connection === "online"
                  ? "The foundation is ready. Portfolio management comes next."
                  : connection === "offline"
                    ? "Check that the local service is running, then try again."
                    : "Checking the connection to your local service."}
              </p>
            </div>
            <div className="connection-actions">
              <span className="status" role="status" aria-live="polite">
                <span className="status-dot" />
                {status}
              </span>
              <button
                type="button"
                onClick={() => void checkConnection()}
                disabled={checking}
              >
                {checking ? "Checking…" : "Check connection"}{" "}
                <span aria-hidden="true">↻</span>
              </button>
            </div>
          </section>

          <div className="section-heading">
            <h2>Room to build conviction.</h2>
            <span>WHAT COMES NEXT</span>
          </div>
          <div className="feature-grid">
            <section className="feature-card">
              <div className="feature-top">
                <span className="feature-symbol" aria-hidden="true">
                  ▥
                </span>
                <span className="planned">Planned</span>
              </div>
              <h3>Portfolio</h3>
              <p>
                Your holdings, activity, and performance.
                <br />
                One clear record of what you own.
              </p>
              <div className="feature-foot">
                Start with the essentials <span aria-hidden="true">01</span>
              </div>
            </section>
            <section className="feature-card">
              <div className="feature-top">
                <span className="feature-symbol" aria-hidden="true">
                  ▤
                </span>
                <span className="planned">Planned</span>
              </div>
              <h3>Research</h3>
              <p>
                Sources, notes, and investment theses.
                <br />
                Keep the thinking behind each decision.
              </p>
              <div className="feature-foot">
                Make space for deeper thinking{" "}
                <span aria-hidden="true">02</span>
              </div>
            </section>
          </div>
          <footer className="page-footer">
            <span>MINERVA</span>
            <p>Clarity before complexity.</p>
            <span>LOCAL EDITION</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
