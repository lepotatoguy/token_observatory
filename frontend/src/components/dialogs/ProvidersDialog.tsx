import { useEffect, useState } from "react";
import { useProviders } from "../../hooks/useProviders";
import { useAppStore } from "../../store/useAppStore";
import { providerName, providerIcon } from "../../utils/tokens";
import type { ProviderChoice } from "../../types/providers";
import { Dialog } from "./Dialog";
export function ProvidersDialog({ firstRun = false }: { firstRun?: boolean }) {
  const { data, error, isFetching, refetch, save } = useProviders(),
    close = useAppStore((s) => s.setDialog),
    [choice, setChoice] = useState<ProviderChoice>({
      enabled: {},
      ports: {},
      setup_done: true,
    }),
    [message, setMessage] = useState(""),
    [minimaxKey, setMinimaxKey] = useState(""),
    [minimaxRegion, setMinimaxRegion] = useState("global"),
    [removeMinimaxKey, setRemoveMinimaxKey] = useState(false);
  useEffect(() => {
    if (!data) return;
    setMinimaxRegion(data.minimax?.region || "global");
    setChoice({
      enabled: Object.fromEntries(
        Object.keys(data.names).map((p) => [
          p,
          firstRun ? !!data.detected[p] : data.enabled.includes(p),
        ]),
      ),
      ports: Object.fromEntries(
        Object.entries(data.local).map(([p, v]) => [
          p,
          { listen: v.listen, target: v.target },
        ]),
      ),
      setup_done: true,
    });
  }, [data, firstRun]);
  const changePort = (p: string, key: "listen" | "target", value: number) =>
    setChoice((c) => ({
      ...c,
      ports: { ...c.ports, [p]: { ...c.ports[p], [key]: value } },
    }));
  const saveChoice = () => {
    if (!Object.values(choice.enabled).some(Boolean)) {
      setMessage("Pick at least one tool to track.");
      return;
    }
    for (const ports of Object.values(choice.ports))
      if (
        Object.values(ports).some(
          (v) => !Number.isInteger(v) || v < 1 || v > 65535,
        ) ||
        ports.listen === ports.target
      ) {
        setMessage(
          "Use distinct listen and server ports, each from 1 to 65535.",
        );
        return;
      }
    const minimax = minimaxKey || removeMinimaxKey || minimaxRegion !== (data?.minimax?.region || "global")
      ? { region: minimaxRegion, ...(removeMinimaxKey ? { api_key: null } : minimaxKey ? { api_key: minimaxKey } : {}) }
      : undefined;
    save.mutate({ ...choice, ...(minimax ? { minimax } : {}) }, {
      onSuccess: (status) => {
        const problems = Object.entries(status.local).filter(
          ([p, v]) => status.enabled.includes(p) && v.error,
        );
        if (problems.length)
          setMessage(
            `Saved, but ${problems.map(([p, v]) => `${providerName(p)}: ${v.error}`).join("; ")}`,
          );
        else close(null);
      },
    });
  };
  return (
    <Dialog
      title={firstRun ? "Welcome to Token Observatory" : "Providers"}
      onClose={() => close(null)}
    >
      <p className="providers-intro">
        {firstRun
          ? "Choose the AI tools you use. Everything is tracked on this computer only. Tools found locally are already selected."
          : "Turn tracking on or off for each tool. Recorded usage stays visible when a tool is unticked. Local counting ports pass requests through to your server. Only a short chat title and usage counts are saved."}
      </p>
      {data ? (
        <div className="provider-list">
          {[...data.cloud, ...Object.keys(data.local)].map((p, i) => {
            const local = data.local[p],
              ports = choice.ports[p];
            return (
              <div key={p}>
                <h3 hidden={i !== 0 && i !== data.cloud.length}>
                  {local ? "Local LLMs" : "Cloud coding tools"}
                </h3>
                <div
                  className={`provider-row${choice.enabled[p] ? " on" : ""}`}
                >
                  <label className="provider-toggle">
                    <input
                      type="checkbox"
                      checked={!!choice.enabled[p]}
                      onChange={(e) =>
                        setChoice((c) => ({
                          ...c,
                          enabled: { ...c.enabled, [p]: e.target.checked },
                        }))
                      }
                    />
                    <span className={`provider-icon ${p}`}>
                      {providerIcon(p)}
                    </span>
                    <strong>{providerName(p)}</strong>
                    <small>
                      {data.detected[p]
                        ? `Found: ${String(data.detected[p])}`
                        : "Not found on this computer"}
                    </small>
                  </label>
                  {local ? (
                    <>
                      <span
                        className={`provider-state${local.error ? " bad" : local.server_up ? " good" : ""}`}
                      >
                        {local.error ||
                          `${local.listening ? `Counting on port ${local.listen}` : "Starts when you save"} · ${local.server_up ? "Server answering" : "Server not running"} on port ${local.target}${p === "lmstudio" && typeof local.chat_files === "number" ? ` · ${local.chat_files} saved chat files detected` : ""}`}
                      </span>
                      <details open={firstRun && !!choice.enabled[p]}>
                        <summary>How to connect</summary>
                        {p === "lmstudio" && (
                          <p>
                            Saved LM Studio chats are imported automatically.
                            Counting ports are only needed for requests from
                            other apps.
                          </p>
                        )}
                        <ol>
                          <li>
                            Start {providerName(p)} on port {ports?.target}.
                          </li>
                          <li>
                            Point your other apps at{" "}
                            <code>
                              http://127.0.0.1:{ports?.listen}
                              {p === "ollama" ? "" : "/v1"}
                            </code>
                            .
                          </li>
                          {p === "ollama" && (
                            <li>
                              For the Ollama command, use{" "}
                              <code>
                                OLLAMA_HOST=127.0.0.1:{ports?.listen} ollama run
                                llama3.2
                              </code>
                              .
                            </li>
                          )}
                          {p === "llamacpp" && (
                            <li>
                              Start the server with{" "}
                              <code>
                                llama-server -m your-model.gguf --port{" "}
                                {ports?.target}
                              </code>
                              .
                            </li>
                          )}
                        </ol>
                        <div className="port-fields">
                          {(["listen", "target"] as const).map((key) => (
                            <label key={key}>
                              {key === "listen"
                                ? "Listen on"
                                : `${providerName(p)} port`}{" "}
                              <input
                                type="number"
                                min="1"
                                max="65535"
                                value={ports?.[key] || ""}
                                onChange={(e) =>
                                  changePort(p, key, Number(e.target.value))
                                }
                              />
                            </label>
                          ))}
                        </div>
                      </details>
                    </>
                  ) : (
                    <span className="provider-state">
                      {p === "minimax"
                        ? "Reads local MiniMax Code sessions and MiniMax model usage from Claude Code and Codex logs."
                        : p === "claude"
                          ? "Reads Claude Code logs in ~/.claude"
                          : "Reads Codex logs in ~/.codex"}
                    </span>
                  )}
                </div>
                {p === "minimax" && choice.enabled[p] && (
                  <details>
                    <summary>Account quota</summary>
                    <p>Uses your signed-in MiniMax Code account automatically. You can also use a Coding Plan API key. Quota checks contact MiniMax; local usage is counted separately.</p>
                    <p>{data.minimax?.configured ? "Quota credentials found" : "Sign in to MiniMax Code or add a Coding Plan API key"}</p>
                    <div className="quota-fields">
                    <label>
                      MiniMax Coding Plan API key
                      <input type="password" autoComplete="off" value={minimaxKey}
                        placeholder="Leave blank to keep the current key"
                        onChange={(e) => { setMinimaxKey(e.target.value); setRemoveMinimaxKey(false); }} />
                    </label>
                    <label>
                      MiniMax API region
                      <select value={minimaxRegion} onChange={(e) => setMinimaxRegion(e.target.value)}>
                        <option value="global">Global</option>
                        <option value="cn">China</option>
                      </select>
                    </label>
                    </div>
                    <button className="button" onClick={() => { setRemoveMinimaxKey(true); setMinimaxKey(""); }}>
                      {removeMinimaxKey ? "Saved key will be removed" : "Remove saved API key"}
                    </button>
                  </details>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <p>Looking for installed tools…</p>
      )}
      <p className="update-progress" role="status">
        {message || error?.message || save.error?.message}
      </p>
      <div className="update-actions">
        <button
          className="button"
          disabled={isFetching}
          onClick={() => {
            void refetch();
          }}
        >
          Check again
        </button>
        <button
          className="button primary"
          disabled={!data || save.isPending}
          onClick={saveChoice}
        >
          {save.isPending ? "Saving…" : firstRun ? "Save and start" : "Save"}
        </button>
      </div>
    </Dialog>
  );
}
