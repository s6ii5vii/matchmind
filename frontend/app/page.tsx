"use client";

import { useCallback, useEffect, useState } from "react";

type Side = "home" | "away";
type Mode = "fan" | "analyst";
type Event = {
  id: string; minute: number; second: number; clock: string;
  team: Side; player: string; type: string; outcome: string;
  is_goal: boolean; x: number; y: number; xg?: number;
};
type Stats = {
  goals: number; passes: number; completed_passes: number; pass_accuracy: number | null;
  shots: number; xg: number; pressures: number; tackles_won: number;
  turnovers: number; event_share: number;
};
type Insight = { title: string; body: string; kind: string; evidence_ids: string[]; window: string };
type MatchState = {
  minute: number; is_synthetic: boolean; teams: Record<Side, { name: string; abbr: string; color: string }>;
  score: Record<Side, number>; stats: Record<Side, Stats>;
  insights: Insight[]; recent_events: Event[]; goal_events: Event[];
  observed_event_count: number; method: string;
};

const descriptions: Record<string, string> = {
  pass: "Pass", pressure: "Pressure applied", tackle: "Tackle", shot: "Shot", turnover: "Turnover",
};

function eventLabel(event: Event): string {
  if (event.is_goal) return "GOAL";
  if (event.type === "pass") return `${event.outcome === "complete" ? "Completed" : "Missed"} pass`;
  if (event.type === "shot") return `Shot ${event.outcome}`;
  return descriptions[event.type] ?? event.type;
}

export default function Home() {
  const [minute, setMinute] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [mode, setMode] = useState<Mode>("fan");
  const [focus, setFocus] = useState<Side>("home");
  const [data, setData] = useState<MatchState | null>(null);
  const [loadError, setLoadError] = useState("");
  const [recap, setRecap] = useState("");
  const [recapStatus, setRecapStatus] = useState<"idle" | "loading" | "ai" | "error">("idle");

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

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => setMinute((m) => {
      if (m >= 90) return 90;
      return m + 1;
    }), 950);
    return () => window.clearInterval(id);
  }, [playing]);
  useEffect(() => { if (minute === 90) setPlaying(false); }, [minute]);
  useEffect(() => { setRecap(""); setRecapStatus("idle"); }, [minute, mode, focus]);

  const aiRecap = useCallback(async () => {
    setRecapStatus("loading");
    try {
      const response = await fetch("/api/narrate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minute, mode, focus }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Could not reach the configured model.");
      setRecap(result.text);
      setRecapStatus("ai");
    } catch (err) {
      setRecap(err instanceof Error ? err.message : "Unknown narration error");
      setRecapStatus("error");
    }
  }, [minute, mode, focus]);

  const st = data?.stats;
  const home = data?.teams.home;
  const away = data?.teams.away;
  const goals = data?.goal_events ?? [];
  const visibleEvent = data?.recent_events?.[0];

  return (
    <main className="shell">
      <header className="header">
        <div className="brand"><span className="brand-icon">M</span><span>match<span className="brand-accent">mind</span><small>INTELLIGENCE ENGINE</small></span></div>
        <div className="header-right"><span className="dot"/><span>SIMULATION ONLINE</span><span className="divider-v"/><span className="build-tag">BUILD 0.1 · SYNTHETIC DATA</span></div>
      </header>

      <section className="hero">
        <div><div className="eyebrow">LIVE MATCH INTELLIGENCE / 001</div><h1>The game, <em>explained.</em></h1><p>From event stream to tactical context. Every insight connected to actual simulated evidence.</p></div>
        <div className="status-label">PROOF OF CONCEPT <span>2026 HACKATHON</span></div>
      </section>

      {loadError && <div className="error" role="alert">{loadError} <span>Instructions are in README.md.</span></div>}

      <section className="scoreboard" aria-label="Scoreboard">
        <div className="team team-home"><div className="crest crest-home">N</div><div><span className="team-caption">HOME</span><strong>{home?.name ?? "Northbridge City"}</strong><small>Northbridge, fictional club</small></div></div>
        <div className="score-center"><div className="match-label"><span className={playing ? "live-pulse" : ""}/> {playing ? "SIMULATION PLAYING" : "SIMULATION PAUSED"}</div><div className="big-score">{data?.score.home ?? 0}<span>:</span>{data?.score.away ?? 0}</div><div className="minute">{String(minute).padStart(2, "0")}:00 / 90:00</div></div>
        <div className="team team-away"><div><span className="team-caption">AWAY</span><strong>{away?.name ?? "Riverside United"}</strong><small>Riverside, fictional club</small></div><div className="crest crest-away">R</div></div>
      </section>

      <section className="playback">
        <button className="play-btn" onClick={() => { if (minute === 90) setMinute(0); setPlaying(!playing || minute === 90); }} aria-label={playing ? "Pause" : "Play"}>{playing ? "❚❚" : "▶"}</button>
        <button className="skip-btn" onClick={() => { setPlaying(false); setMinute(0); }}>↺ <span>RESET</span></button>
        <input type="range" min="0" max="90" step="1" value={minute} onChange={(e) => { setPlaying(false); setMinute(Number(e.target.value)); }} aria-label="Match minute" className="timeline" style={{background: `linear-gradient(90deg,#71e4c7 ${minute / 90 * 100}%,#273442 ${minute / 90 * 100}%)`}} />
        <div className="time-end">90&apos;</div>
        <span className="timeline-help">DRAG TO INSPECT ANY MOMENT</span>
      </section>
      <div className="goal-tracks">{goals.map((event) => <span key={event.id} title={`${event.player} scored at ${event.clock}`}>● {event.minute}&apos; {event.player}</span>)}</div>

      <div className="content-grid">
        <section className="panel match-panel">
          <div className="panel-head"><div><span className="section-numeral">01 /</span><h2>Live event feed</h2></div><span className="panel-meta">{data?.observed_event_count ?? 0} EVENTS OBSERVED</span></div>
          <div className="field"><div className="field-half"/><div className="center-circle"/><div className="field-box left-box"/><div className="field-box right-box"/>
            {visibleEvent && <div className={`event-point ${visibleEvent.team}`} style={{left: `${visibleEvent.x}%`, top: `${visibleEvent.y}%`}}><span className="point-core"/><span className="point-label">{visibleEvent.player}</span></div>}
            <div className="field-label">ILLUSTRATIVE EVENT COORDINATE — NOT REAL TRACKING</div>
          </div>
          <div className="event-list">{data?.recent_events.length ? data.recent_events.slice(0,6).map((event) => (
            <div className={`event-item ${event.is_goal ? "goal-item" : ""}`} key={event.id}><span className="event-time">{event.clock}</span><span className={`event-indicator ${event.team}`}></span><span className="event-content"><b>{eventLabel(event)}</b><small>{event.player} · {data.teams[event.team].abbr}</small></span><code>{event.id}</code></div>
          )) : <div className="empty">Press play to start receiving synthetic match events.</div>}</div>
        </section>

        <section className="panel insight-panel">
          <div className="panel-head"><div><span className="section-numeral">02 /</span><h2>Intelligence desk</h2></div><span className="panel-meta">EVIDENCE-BASED</span></div>
          <div className="mode-section"><span className="control-label">VIEWER PROFILE</span><div className="segmented"><button className={mode === "fan" ? "active" : ""} onClick={() => setMode("fan")}>Fan view</button><button className={mode === "analyst" ? "active" : ""} onClick={() => setMode("analyst")}>Analyst view</button></div></div>
          <div className="mode-section"><label htmlFor="focus" className="control-label">FOLLOWING TEAM</label><select id="focus" value={focus} onChange={(e) => setFocus(e.target.value as Side)}><option value="home">Northbridge City</option><option value="away">Riverside United</option></select></div>
          <div className="insights">{data?.insights.map((insight, idx) => (
            <article className="insight-card" key={`${minute}-${idx}`}><div className="insight-top"><span className="insight-icon">✦</span><span>{insight.window.toUpperCase()}</span></div><h3>{insight.title}</h3><p>{insight.body}</p><div className="evidence">{insight.evidence_ids.length ? `SOURCE EVENTS: ${insight.evidence_ids.join(" · ")}` : "AWAITING EVIDENCE"}</div></article>
          )) ?? <div className="empty">Fetching verified match context…</div>}</div>
          <div className="ai-module"><div><strong>Microsoft Foundry commentary</strong><small>Optional LLM narration, grounded in the current stats</small></div><button disabled={recapStatus === "loading"} onClick={aiRecap}>{recapStatus === "loading" ? "Generating…" : "Generate AI recap ↗"}</button></div>
          {recap && <div className={`recap-box ${recapStatus}`}><b>{recapStatus === "ai" ? "FOUNDRY NARRATIVE" : "CONFIGURATION REQUIRED"}</b><p>{recap}</p></div>}
        </section>
      </div>

      <section className="panel stats-panel"><div className="panel-head"><div><span className="section-numeral">03 /</span><h2>Match by the numbers</h2></div><span className="panel-meta">CUMULATIVE · THROUGH {minute}&apos;</span></div>
        <div className="stat-heading"><span>{home?.abbr ?? "NBR"}</span><span>METRIC</span><span>{away?.abbr ?? "RSU"}</span></div>
        {[
          ["Shots", st?.home.shots, st?.away.shots],
          ["Synthetic xG", st?.home.xg, st?.away.xg],
          ["Completed passes", st?.home.completed_passes, st?.away.completed_passes],
          ["Pass accuracy", st?.home.pass_accuracy == null ? "—" : `${st.home.pass_accuracy}%`, st?.away.pass_accuracy == null ? "—" : `${st.away.pass_accuracy}%`],
          ["Pressure events", st?.home.pressures, st?.away.pressures],
          ["Event share (not possession)", st?.home.event_share == null ? "—" : `${st.home.event_share}%`, st?.away.event_share == null ? "—" : `${st.away.event_share}%`],
        ].map(([label, h, a]) => <div className="stat-row" key={String(label)}><strong>{h ?? "—"}</strong><span>{label}</span><strong>{a ?? "—"}</strong></div>)}
      </section>

      <footer><span>MATCHMIND / v0.1</span><span>ALL CLUBS, PLAYERS, EVENTS AND xG ARE FICTIONAL · NO ACTUAL LEAGUE FOOTAGE</span><span>EXPLAINABILITY FIRST</span></footer>
    </main>
  );
}
