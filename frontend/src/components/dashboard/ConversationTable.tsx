import type { ScopedSession } from "../../types/session";
import { useAppStore } from "../../store/useAppStore";
import { compact, exact, providerIcon } from "../../utils/tokens";
import { relative, date } from "../../utils/time";
import { contextPercent } from "../../utils/conversations";
export function visibleSessions(
  sessions: ScopedSession[],
  search: string,
  sort: string,
  direction: string,
) {
  const query = search.toLowerCase();
  return sessions
    .filter((s) =>
      `${s.title} ${s.model} ${s.project} ${s.session_id}`
        .toLowerCase()
        .includes(query),
    )
    .sort(
      (a, b) =>
        (direction === "desc" ? 1 : -1) *
        (sort === "tokens"
          ? b.scope.total - a.scope.total
          : (b.last || 0) - (a.last || 0)),
    );
}
export function ConversationTable({
  sessions,
  now,
}: {
  sessions: ScopedSession[];
  now: number;
}) {
  const s = useAppStore(),
    visible = visibleSessions(sessions, s.search, s.sort, s.sortDirection);
  return (
    <section className="panel sessions-panel">
      <div className="panel-heading">
        <div>
          <h2>
            Conversations <span className="count">{visible.length}</span>
          </h2>
          <p>Select a chat to inspect its usage.</p>
        </div>
        <label className="search">
          ⌕
          <input
            type="search"
            placeholder="Search chats or models"
            aria-label="Search chats or models"
            value={s.search}
            onChange={(e) => s.setSearch(e.target.value)}
          />
        </label>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Conversation</th>
              {(["tokens", "recent"] as const).map((key) => (
                <th
                  key={key}
                  aria-sort={
                    s.sort === key
                      ? s.sortDirection === "desc"
                        ? "descending"
                        : "ascending"
                      : "none"
                  }
                >
                  <button type="button" onClick={() => s.setSort(key)}>
                    {key === "tokens" ? "Tokens" : "Last activity"}
                    {s.sort === key
                      ? s.sortDirection === "desc"
                        ? " ↓"
                        : " ↑"
                      : ""}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length ? (
              visible.map((chat) => (
                <tr
                  key={chat.id}
                  tabIndex={0}
                  className={s.selected === chat.id ? "active" : ""}
                  aria-selected={s.selected === chat.id}
                  onClick={() =>
                    s.setSelected(s.selected === chat.id ? null : chat.id)
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      s.setSelected(s.selected === chat.id ? null : chat.id);
                    }
                  }}
                >
                  <td>
                    <div className="conversation">
                      <span className={`provider-icon ${chat.provider}`}>
                        {providerIcon(chat.provider)}
                      </span>
                      <div>
                        <div className="conversation-title" title={chat.title}>
                          {chat.title}
                        </div>
                        <div className="conversation-sub">
                          {chat.model}
                          {chat.agent_count
                            ? ` · ${chat.agent_count} subagents`
                            : chat.subagent
                              ? " · subagent"
                              : ""}
                          {chat.last && now - chat.last < 300
                            ? " · recent"
                            : ""}
                          {(contextPercent(chat) || 0) >= 80 && (
                            <span className="pressure-badge">
                              {" "}
                              · context {contextPercent(chat)?.toFixed(0)}%
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="token-number" title={exact(chat.scope.total)}>
                    {chat.usage_source === "unavailable"
                      ? "Unreported"
                      : compact(chat.scope.total)}
                  </td>
                  <td className="relative" title={date(chat.last)}>
                    {relative(chat.last, now)}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={3}>
                  <div className="empty-state">
                    No chats match these filters.
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="table-footer">
        {visible.length} chats ·{" "}
        {exact(visible.reduce((n, chat) => n + chat.events.length, 0))} usage
        updates · select a row for details
      </div>
    </section>
  );
}
