import { useAppStore } from "../../store/useAppStore";
export function Sidebar() {
  const { page, setPage, setDialog } = useAppStore();
  return (
    <aside className="sidebar">
      <a
        className="brand"
        href="#overview"
        aria-label="Token Observatory home"
        onClick={() => setPage("overview")}
      >
        <img
          className="brand-icon"
          src="/logo.svg"
          width="38"
          height="38"
          alt=""
        />
        <span>
          Token
          <br />
          <strong>Observatory</strong>
        </span>
      </a>
      <div className="nav-caption">WORKSPACE</div>
      {(["overview", "stats"] as const).map((p) => (
        <a
          key={p}
          className={`page-nav${page === p ? " nav-active" : ""}`}
          href={`#${p}`}
          aria-current={page === p ? "page" : undefined}
          onClick={() => setPage(p)}
        >
          <span className="nav-icon" aria-hidden="true">
            {p === "overview" ? "▦" : "▥"}
          </span>{" "}
          {p === "overview" ? "Overview" : "Stats"}
        </a>
      ))}
      <button className="nav-button" onClick={() => setDialog("settings")}>
        <span className="nav-icon" aria-hidden="true">
          ⚙
        </span>{" "}
        Settings
      </button>
      <div className="sidebar-note">
        <span className="tiny-dot" /> LOCAL TELEMETRY
        <p>
          Your logs. Your machine.
          <br />
          No uploads or API keys.
        </p>
      </div>
      <div className="sidebar-bottom">
        <span className="avatar">TO</span>
        <span>
          Personal workspace<small>Loopback connection</small>
        </span>
      </div>
    </aside>
  );
}
