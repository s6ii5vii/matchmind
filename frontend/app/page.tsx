"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Side = "home" | "away";
type Mode = "fan" | "analyst";
type Theme = "light" | "dark";
type Filter = "all" | "goal" | "shot" | "pass" | "pressure" | "turnover";
type Event = {
  id: string; minute: number; second: number; clock: string;
  team: Side; player: string; type: string; outcome: string;
  is_goal: boolean; x: number; y: number; xg?: number;
};
type Stats = {
  goals: number; passes: number; completed_passes: number; pass_accuracy: number | null;
  shots: number; xg: number; pressures: number; tackles_won: number;
  turnovers: number; event_share: number; possession: number | null; recoveries: number; final_third_entries: number;
};
type Insight = { title: string; body: string; kind: string; evidence_ids: string[]; window: string };
type MatchState = {
  minute: number; is_synthetic: boolean; teams: Record<Side, { name: string; abbr: string; color: string }>;
  score: Record<Side, number>; stats: Record<Side, Stats>;
  insights: Insight[]; recent_events: Event[]; goal_events: Event[];
  observed_event_count: number; method: string;
};
type Flash = { side: Side; player: string; clock: string; key: number };
type Verdict = "verified" | "corrected" | "unproven" | "rejected" | "pending";
type Claim = {
  id: string; team: Side; metric: string; start: number; end: number; value: number;
  text: string; evidence_ids: string[]; proposed_by: string; revision_of: string | null;
  verdict: Verdict; reason: string; finding: string; premise: boolean;
};
type TraceStep = { agent: string; action: string; detail: string; status: "info" | "ok" | "warn" | "reject" };
type Analysis = {
  engine: "foundry" | "nebius" | "offline"; window: [number, number]; narrative: string; narrative_source: string;
  claims: Claim[]; trace: TraceStep[]; minute: number;
};

const ENGINE_LABEL: Record<Analysis["engine"], string> = { foundry: "Microsoft Foundry", nebius: "Nebius Token Factory", offline: "Rule-based" };
const AGENTS = ["Orchestrator", "Stats", "Pundit", "Skeptic", "Narrator"];
const VERDICT_LABEL: Record<Verdict, string> = {
  verified: "✓ Holds up", corrected: "◐ Half-right", unproven: "? Not enough evidence", rejected: "✕ Doesn't hold up", pending: "Pending",
};

function takeSource(c: Claim): string {
  if (c.premise) return "Your question assumes";
  return c.revision_of ? "Pundit, rethinking" : "The pundit says";
}
const SUGGESTIONS = ["Who is controlling the game?", "Why did Riverside lose control after 60?", "Is Northbridge's press working?"];

const descriptions: Record<string, string> = {
  pass: "Pass", pressure: "Pressure applied", tackle: "Tackle", shot: "Shot", turnover: "Lost the ball",
  interception: "Interception", foul: "Foul",
};

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "goal", label: "Goals" },
  { id: "shot", label: "Shots" },
  { id: "pass", label: "Passes" },
  { id: "pressure", label: "Pressure" },
  { id: "turnover", label: "Turnovers" },
];

function eventLabel(event: Event): string {
  if (event.is_goal) return "Goal";
  if (event.type === "pass") return `${event.outcome === "complete" ? "Completed" : "Missed"} pass`;
  if (event.type === "shot") return `Shot ${event.outcome.replace("_", " ")}`;
  if (event.type === "tackle") return `Tackle ${event.outcome}`;
  return descriptions[event.type] ?? event.type;
}

function matchesFilter(event: Event, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "goal") return event.is_goal;
  return event.type === filter;
}

const PlayIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z" fill="currentColor" /></svg>);
const PauseIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24"><rect x="6" y="4.5" width="4.2" height="15" rx="1" fill="currentColor" /><rect x="13.8" y="4.5" width="4.2" height="15" rx="1" fill="currentColor" /></svg>);
const ResetIcon = () => (<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg>);
const MoonIcon = () => (<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>);
const SunIcon = () => (<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>);

export default function Home() {
  const [minute, setMinute] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [mode, setMode] = useState<Mode>("fan");
  const [focus, setFocus] = useState<Side>("home");
  const [theme, setTheme] = useState<Theme>("dark");
  const [filter, setFilter] = useState<Filter>("all");
  const [data, setData] = useState<MatchState | null>(null);
  const [loadError, setLoadError] = useState("");
  const [question, setQuestion] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analysisStatus, setAnalysisStatus] = useState<"idle" | "loading" | "error">("idle");
  const [flash, setFlash] = useState<Flash | null>(null);
  const prev = useRef<{ minute: number; home: number; away: number } | null>(null);

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/state?minute=${minute}&mode=${mode}&focus=${focus}`, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`API returned ${res.status}`);
        return (await res.json()) as MatchState;
      })
      .then((result) => { setData(result); setLoadError(""); })
      .catch((e: Error) => { if (e.name !== "AbortError") setLoadError("Backend unreachable. Start FastAPI on port 8000, then refresh."); });
    return () => controller.abort();
  }, [minute, mode, focus]);

  // goal celebration: fires when the score goes up by stepping forward a minute or less
  useEffect(() => {
    if (!data) return;
    const cur = { minute: data.minute, home: data.score.home, away: data.score.away };
    const p = prev.current;
    if (p) {
      const dm = cur.minute - p.minute;
      if (dm >= 0 && dm <= 1) {
        const side: Side | null = cur.home > p.home ? "home" : cur.away > p.away ? "away" : null;
        if (side) {
          const g = [...data.goal_events].reverse().find((e) => e.team === side);
          setFlash({ side, player: g?.player ?? "", clock: g?.clock ?? `${cur.minute}'`, key: Date.now() });
        }
      }
    }
    prev.current = cur;
  }, [data]);
  useEffect(() => {
    if (!flash) return;
    const id = window.setTimeout(() => setFlash(null), 3400);
    return () => window.clearTimeout(id);
  }, [flash]);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => setMinute((m) => (m >= 90 ? 90 : m + 1)), 950);
    return () => window.clearInterval(id);
  }, [playing]);
  useEffect(() => { if (minute === 90) setPlaying(false); }, [minute]);
  const runAgents = useCallback(async (q: string) => {
    setPlaying(false);
    setAnalysisStatus("loading");
    try {
      const response = await fetch("/api/analyze", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minute, mode, focus, question: q }),
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      setAnalysis((await response.json()) as Analysis);
      setAnalysisStatus("idle");
    } catch {
      setAnalysisStatus("error");
    }
  }, [minute, mode, focus]);

  const st = data?.stats;
  const home = data?.teams.home;
  const away = data?.teams.away;
  const goals = data?.goal_events ?? [];
  const trail = (data?.recent_events ?? []).slice(0, 5);
  const head = trail[0];
  const chrono = [...trail].reverse();
  const feed = (data?.recent_events ?? []).filter((e) => matchesFilter(e, filter)).slice(0, 6);
  const pct = (minute / 90) * 100;
  const status = playing ? "Live" : minute === 0 ? "Kick-off" : minute === 90 ? "Full time" : "Paused";
  const flashColor = flash ? (flash.side === "home" ? "var(--home)" : "var(--away)") : undefined;

  const rows: { label: string; h?: number | null; a?: number | null; unit?: string }[] = [
    { label: "Possession", h: st?.home.possession, a: st?.away.possession, unit: "%" },
    { label: "Shots", h: st?.home.shots, a: st?.away.shots },
    { label: "Synthetic xG", h: st?.home.xg, a: st?.away.xg },
    { label: "Completed passes", h: st?.home.completed_passes, a: st?.away.completed_passes },
    { label: "Pass accuracy", h: st?.home.pass_accuracy, a: st?.away.pass_accuracy, unit: "%" },
    { label: "Pressure events", h: st?.home.pressures, a: st?.away.pressures },
    { label: "Final-third entries", h: st?.home.final_third_entries, a: st?.away.final_third_entries },
    { label: "Ball recoveries", h: st?.home.recoveries, a: st?.away.recoveries },
  ];

  return (
    <main className="shell">
      <header className="header">
        <div className="brand"><span className="brand-icon">m</span><span>matchmind</span></div>
        <div className="header-right">
          <span className="header-meta">Build 0.2 — synthetic data</span>
          <button className="icon-btn" onClick={() => setTheme(theme === "light" ? "dark" : "light")} aria-label="Toggle theme">
            {theme === "light" ? <MoonIcon /> : <SunIcon />}
          </button>
        </div>
      </header>

      <section className="hero">
        <div>
          <h1>Watched the goal. Missed <em>the why?</em></h1>
          <p>A ranked read on what actually mattered in the match, with every insight tied to the exact events that caused it. Fictional clubs, real receipts.</p>
        </div>
        <div className="hero-meta"><b>Proof of concept</b><br />Premier League Hackathon<br />2026</div>
      </section>

      {loadError && <div className="error-banner" role="alert">{loadError} Instructions are in README.md.</div>}

      <section
        key={flash ? flash.key : "idle"}
        className={`surface scoreboard ${flash ? "flash" : ""}`}
        style={flashColor ? ({ ["--flash" as string]: flashColor } as React.CSSProperties) : undefined}
        aria-label="Scoreboard"
      >
        <div className="team team-home">
          <div className={`crest crest-home ${flash?.side === "home" ? "scored" : ""}`}>N</div>
          <div><span className="team-caption">HOME</span><strong>{home?.name ?? "Northbridge City"}</strong><small>Northbridge, fictional club</small></div>
        </div>
        <div className="score-center">
          <div className={`status-line ${playing ? "live" : ""}`}>{status}</div>
          <div className="big-score">
            <span className="score-num" key={`h${data?.score.home ?? 0}`}>{data?.score.home ?? 0}</span>
            <span className="sep">–</span>
            <span className="score-num" key={`a${data?.score.away ?? 0}`}>{data?.score.away ?? 0}</span>
          </div>
          <div className="minute">{String(minute).padStart(2, "0")}:00 / 90:00</div>
        </div>
        <div className="team team-away">
          <div><span className="team-caption">AWAY</span><strong>{away?.name ?? "Riverside United"}</strong><small>Riverside, fictional club</small></div>
          <div className={`crest crest-away ${flash?.side === "away" ? "scored" : ""}`}>R</div>
        </div>
        {flash && <div className="goal-banner">Goal · <b>{flash.player}</b> {flash.clock}</div>}
      </section>

      <section className="playback">
        <button className="play-btn" onClick={() => { if (minute === 90) setMinute(0); setPlaying(!playing || minute === 90); }} aria-label={playing ? "Pause" : "Play"}>
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <button className="text-btn" onClick={() => { setPlaying(false); setMinute(0); }}><ResetIcon />Reset</button>
        <div className="track">
          <input
            type="range" min="0" max="90" step="1" value={minute}
            onChange={(e) => { setPlaying(false); setMinute(Number(e.target.value)); }}
            aria-label="Match minute" className="timeline"
            style={{ background: `linear-gradient(90deg,var(--ink) ${pct}%,var(--line-strong) ${pct}%)` }}
          />
          {goals.map((g) => <i key={g.id} className="tick" style={{ left: `${(g.minute / 90) * 100}%` }} />)}
        </div>
        <div className="time-end">90&apos;</div>
      </section>
      <div className="goal-tracks">
        {goals.map((event) => (
          <span key={event.id} title={`${event.player} scored at ${event.clock}`}>{event.minute}&apos; {event.player}</span>
        ))}
      </div>

      <div className="content-grid">
        <section className="surface">
          <div className="panel-head">
            <h2><span className="section-numeral">01</span>Live event feed</h2>
            <span className="panel-meta">{data?.observed_event_count ?? 0} events observed</span>
          </div>
          <div className="tabs" role="tablist">
            {FILTERS.map((f) => (
              <button key={f.id} role="tab" aria-selected={filter === f.id} className={`tab ${filter === f.id ? "active" : ""}`} onClick={() => setFilter(f.id)}>{f.label}</button>
            ))}
          </div>
          <div className="field">
            <div className="field-half" /><div className="center-circle" />
            <div className="field-box left-box" /><div className="field-box right-box" />
            {chrono.length > 1 && (
              <svg className="trail-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                <polyline points={chrono.map((e) => `${e.x},${e.y}`).join(" ")} />
              </svg>
            )}
            {trail.slice(1).map((e, i) => (
              <span key={e.id} className={`trail-dot ${e.team}`} style={{ left: `${e.x}%`, top: `${e.y}%`, opacity: Math.max(0.15, 0.8 - i * 0.2) }} />
            ))}
            {head && (
              <div className={`event-point ${head.team}`} style={{ left: `${head.x}%`, top: `${head.y}%` }}>
                <span className="point-core" /><span className="point-label">{head.player}</span>
              </div>
            )}
            <div className="field-label">ILLUSTRATIVE EVENT COORDINATE — NOT REAL TRACKING</div>
          </div>
          <div className="event-list">
            {feed.length ? feed.map((event) => (
              <div className={`event-item ${event.is_goal ? "goal-item" : ""}`} key={event.id}>
                <span className="event-time">{event.clock}</span>
                <span className={`event-indicator ${event.team}`} />
                <span className="event-content"><b>{eventLabel(event)}</b><small>{event.player} · {data?.teams[event.team].abbr}</small></span>
                <code>{event.id}</code>
              </div>
            )) : (
              <div className="empty">{data?.recent_events.length ? "Nothing matches that filter yet." : "Hit play to start receiving synthetic match events."}</div>
            )}
          </div>
        </section>

        <section className="surface">
          <div className="panel-head">
            <h2><span className="section-numeral">02</span>Intelligence desk</h2>
            <span className="panel-meta">Ranked · evidence-based</span>
          </div>
          <div className="control-row">
            <span className="control-label">VIEWER PROFILE</span>
            <div className="seg">
              <button className={mode === "fan" ? "active" : ""} onClick={() => setMode("fan")}>Fan view</button>
              <button className={mode === "analyst" ? "active" : ""} onClick={() => setMode("analyst")}>Analyst view</button>
            </div>
          </div>
          <div className="control-row">
            <span className="control-label">FOLLOWING TEAM</span>
            <div className="seg">
              <button className={focus === "home" ? "active" : ""} onClick={() => setFocus("home")}>Northbridge City</button>
              <button className={focus === "away" ? "active" : ""} onClick={() => setFocus("away")}>Riverside United</button>
            </div>
          </div>
          <div className="insights">
            {data?.insights.length ? data.insights.map((insight, idx) => (
              <article className="insight-card" key={`${minute}-${idx}`}>
                <span className="rank">{String(idx + 1).padStart(2, "0")}</span>
                <div>
                  <div className="insight-top"><span>{insight.window}</span><span>{insight.kind}</span></div>
                  <h3>{insight.title}</h3>
                  <p>{insight.body}</p>
                  <div className="evidence">
                    {insight.evidence_ids.length ? <><b>SOURCE EVENTS</b>{insight.evidence_ids.join(" · ")}</> : <b>AWAITING EVIDENCE</b>}
                  </div>
                </div>
              </article>
            )) : <div className="empty">{data ? "No insights at this minute." : "Fetching verified match context…"}</div>}
          </div>
        </section>
      </div>

      <section className="surface agent-room">
        <div className="panel-head">
          <h2><span className="section-numeral">03</span>Agent room</h2>
          <span className="panel-meta">
            {analysis ? `${ENGINE_LABEL[analysis.engine]} agents · minute ${analysis.minute}` : "Five agents · every take checked"}
          </span>
        </div>
        <form className="ask" onSubmit={(e) => { e.preventDefault(); runAgents(question); }}>
          <input
            value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={300}
            placeholder={`Ask about the match so far (minute ${minute})…`} aria-label="Question for the agents"
          />
          <button type="submit" disabled={analysisStatus === "loading" || minute === 0}>
            {analysisStatus === "loading" ? "Agents working…" : question.trim() ? "Ask the agents" : "Analyse this moment"}
          </button>
        </form>
        <div className="suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" onClick={() => { setQuestion(s); runAgents(s); }} disabled={analysisStatus === "loading" || minute === 0}>{s}</button>
          ))}
        </div>
        {analysisStatus === "error" && <div className="recap-box error"><b>AGENTS UNAVAILABLE</b><p>Couldn&apos;t reach the analysis service. Check the backend is running.</p></div>}
        {!analysis && analysisStatus !== "error" && (
          <div className="empty">{minute === 0 ? "Play or scrub the match, then ask the agents." : "A pundit gives the popular takes, a skeptic checks every one against the data. Ask a question or analyse this moment."}</div>
        )}
        {analysis && (
          <div className="room">
            <div className="recap-box ai">
              <b>{analysis.narrative_source === "model" ? `NARRATOR · ${ENGINE_LABEL[analysis.engine].toUpperCase()} MODEL` : "NARRATOR"} · MINUTES {analysis.window[0]}–{analysis.window[1]}</b>
              <p>{analysis.narrative}</p>
            </div>
            <div className="takes-summary">
              <span><b>The take</b> vs <b>the data</b></span>
              <span>
                {(["verified", "corrected", "unproven", "rejected"] as Verdict[])
                  .map((v) => [v, analysis.claims.filter((c) => c.verdict === v && !c.revision_of).length] as const)
                  .filter(([, n]) => n > 0)
                  .map(([v, n]) => `${n} ${VERDICT_LABEL[v].slice(2).toLowerCase()}`)
                  .join(" · ")}
              </span>
            </div>
            <div className="takes">
              {analysis.claims.filter((c) => !c.revision_of || c.revision_of.includes(",")).map((c) => {
                const rethink = analysis.claims.find((r) => r.revision_of === c.id);
                return (
                  <article key={c.id} className={`take ${c.verdict} ${c.premise ? "premise" : ""}`}>
                    <div className="take-top">
                      <span>{takeSource(c)}</span>
                      <span className={`verdict ${c.verdict}`}>{VERDICT_LABEL[c.verdict]}</span>
                    </div>
                    <h3>&ldquo;{c.text}&rdquo;</h3>
                    <div className="take-data">
                      <b>THE DATA</b>
                      <p>{c.finding || c.reason}</p>
                      {c.verdict === "corrected" && <small>{c.reason}</small>}
                    </div>
                    {rethink && (
                      <div className={`rethink ${rethink.verdict}`}>
                        <b>RETHINK</b> &ldquo;{rethink.text}&rdquo; <span className={`verdict ${rethink.verdict}`}>{VERDICT_LABEL[rethink.verdict]}</span>
                      </div>
                    )}
                    {c.verdict !== "rejected" && c.evidence_ids.length > 0 && (
                      <div className="evidence"><b>SOURCE EVENTS</b>{c.evidence_ids.join(" · ")}</div>
                    )}
                  </article>
                );
              })}
            </div>
            <details className="trace-wrap">
              <summary>How the agents got here · {analysis.trace.length} steps</summary>
              <ol className="trace" aria-label="Agent trace">
                {analysis.trace.map((t, i) => (
                  <li key={i} className={`trace-step ${t.status}`}>
                    <span className={`agent-tag a${AGENTS.indexOf(t.agent)}`}>{t.agent}</span>
                    <strong>{t.action}</strong>
                    <small>{t.detail}</small>
                  </li>
                ))}
              </ol>
            </details>
          </div>
        )}
      </section>

      <section className="surface stats-panel">
        <div className="panel-head">
          <h2><span className="section-numeral">04</span>Match by the numbers</h2>
          <span className="panel-meta">Cumulative · through {minute}&apos;</span>
        </div>
        <div className="stat-heading"><span>{home?.abbr ?? "NBR"}</span><span>METRIC</span><span>{away?.abbr ?? "RSU"}</span></div>
        {rows.map((r) => {
          const h = r.h ?? 0, a = r.a ?? 0, total = h + a;
          const share = total > 0 ? (h / total) * 100 : 50;
          const show = (v?: number | null) => (v == null ? "—" : `${v}${r.unit ?? ""}`);
          return (
            <div className="stat-row" key={r.label}>
              <div className="stat-nums">
                <strong className={h > a ? "lead" : ""}>{show(r.h)}</strong>
                <span>{r.label}</span>
                <strong className={a > h ? "lead" : ""}>{show(r.a)}</strong>
              </div>
              <div className="bar"><i className="bar-h" style={{ width: `${share}%` }} /><i className="bar-a" style={{ width: `${100 - share}%` }} /></div>
            </div>
          );
        })}
      </section>

      <footer>
        <span>MATCHMIND / v0.2</span>
        <span>ALL CLUBS, PLAYERS, EVENTS AND xG ARE FICTIONAL · NO ACTUAL LEAGUE FOOTAGE</span>
        <span>EXPLAINABILITY FIRST</span>
      </footer>
    </main>
  );
}