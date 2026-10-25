"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Side = "home" | "away";
type Mode = "simple" | "fan" | "analyst";
type Theme = "light" | "dark";
type Filter = "all" | "goal" | "shot" | "pass" | "pressure" | "turnover" | "stops";
type Event = {
  id: string; minute: number; second: number; clock: string; label: string; period: number;
  team: Side; player: string; type: string; outcome: string; receiver: string | null; pass_type: string | null;
  is_goal: boolean; x: number; y: number; xg?: number; duration_s?: number | null;
};
type Stats = {
  goals: number; passes: number; completed_passes: number; pass_accuracy: number | null;
  shots: number; xg: number; pressures: number; tackles_won: number;
  turnovers: number; event_share: number; possession: number | null; recoveries: number; final_third_entries: number;
  saves: number; corners: number; fouls: number; yellow_cards: number;
};
type Team = { name: string; abbr: string; color: string };
type MatchState = {
  minute: number; label: string; period: number; length: number; match: string;
  added: Record<string, number>; announced: Record<string, number | null>;
  is_synthetic: boolean; teams: Record<Side, Team>;
  score: Record<Side, number>; stats: Record<Side, Stats>;
  recent_events: Event[]; goal_events: Event[]; stoppages: Event[];
  observed_event_count: number; method: string;
};
type MatchInfo = { id: string; teams: Record<Side, Team>; story: string };
type Config = {
  match: string; teams: Record<Side, Team>; story: string; questions: string[]; length: number; first_half: number;
  added: Record<string, number>; labels: string[]; matches: MatchInfo[]; model_provider: Analysis["engine"];
};
type Followed = { question: string; label?: string; narrative?: string };
type HistoryItem = { question: string; match: string; label: string; narrative: string };
type Flash = { side: Side; player: string; clock: string; key: number };
type Verdict = "verified" | "corrected" | "unproven" | "rejected" | "pending";
type Claim = {
  id: string; team: Side; metric: string; start: number; end: number; value: number;
  text: string; evidence_ids: string[]; proposed_by: string; revision_of: string | null;
  verdict: Verdict; reason: string; finding: string; premise: boolean; plain: string; plain_finding: string;
};
type TraceStep = { agent: string; action: string; detail: string; status: "info" | "ok" | "warn" | "reject" };
type Category = "chances" | "build_up" | "defending" | "ball_security" | "costly";
type Player = {
  name: string; team: Side; team_name: string; number: number; position: string; impact: number;
  rating: number; tag: string | null; summary?: string;
  values: Record<Category, number>; counts: Record<string, number>;
  moments: { event_id: string; what: string; points: number }[];
};
type MomentPoint = { x: number; y: number; player: string; kind: "win" | "pass" | "shot" | "goal" };
type Moment = {
  id: string; minute: number; label: string; clock: string; team: Side; kind: "goal" | "chance"; title: string; story: string;
  xg: number; question: string; path: MomentPoint[];
};
type Duel = { a: Player; b: Player; winner: string | null; verdict: string; categories: { key: Category; label: string }[] };
const PLAIN_CATEGORY: Record<Category, string> = {
  chances: "Helping create chances", build_up: "Moving the ball towards goal",
  defending: "Winning the ball and stopping shots", ball_security: "Not losing the ball", costly: "Mistakes that led to chances",
};
const POSITION: Record<string, string> = { GK: "Goalkeeper", DF: "Defender", MF: "Midfielder", FW: "Forward" };

type Analysis = {
  engine: "foundry" | "nebius" | "offline"; window: [number, number]; window_label: string; narrative: string;
  narrative_source: string; claims: Claim[]; trace: TraceStep[]; minute: number; question: string; match: string;
};

const ENGINE_LABEL: Record<Analysis["engine"], string> = { foundry: "Microsoft Foundry", nebius: "Nebius Token Factory", offline: "Rule-based" };
const AGENTS = ["Orchestrator", "Stats", "Pundit", "Skeptic", "Narrator"];
const VERDICT_LABEL: Record<Verdict, string> = {
  verified: "✓ Holds up", corrected: "◐ Half-right", unproven: "? Not enough evidence", rejected: "✕ Doesn't hold up", pending: "Pending",
};

function takeSource(c: Claim, simple: boolean): string {
  if (c.premise) return simple ? "You asked about" : "Your question assumes";
  if (simple) return c.revision_of ? "On second thoughts" : "People are saying";
  return c.revision_of ? "Pundit, rethinking" : "The pundit says";
}
const DEFAULT_MATCH = "northbridge-riverside";
const MAX_FOLLOWED = 3;
const FOLLOW_EVERY = 10; // match minutes between refreshes of a followed question while the match plays
const HISTORY_KEY = "matchmind-history";

const descriptions: Record<string, string> = {
  pass: "Pass", pressure: "Pressure applied", tackle: "Tackle", shot: "Shot", turnover: "Lost the ball",
  interception: "Interception", foul: "Foul", recovery: "Ball recovered", save: "Save", block: "Shot blocked",
  clearance: "Clearance", claim: "Keeper claims the cross", carry: "Carry", offside: "Offside", card: "Yellow card",
};
const RESTARTS: Record<string, string> = {
  corner: "Corner", free_kick: "Free kick", throw_in: "Throw-in", goal_kick: "Goal kick", kick_off: "Kick-off",
  cross: "Cross", keeper: "Keeper's pass",
};

function readHistory(): HistoryItem[] {
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as HistoryItem[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(items: HistoryItem[]) {
  try { window.localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 20))); } catch { /* private window */ }
}

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "goal", label: "Goals" },
  { id: "shot", label: "Shots" },
  { id: "pass", label: "Passes" },
  { id: "pressure", label: "Pressure" },
  { id: "turnover", label: "Turnovers" },
  { id: "stops", label: "Cards, subs & stoppages" },
];

function eventLabel(event: Event): string {
  if (event.is_goal) return "Goal";
  if (event.type === "pass") {
    const kind = event.pass_type ? RESTARTS[event.pass_type] ?? "Pass" : "Pass";
    return kind === "Pass" ? `${event.outcome === "complete" ? "Completed" : "Missed"} pass` : `${kind}${event.outcome === "complete" ? "" : ", missed"}`;
  }
  if (event.type === "shot") return `Shot ${event.outcome.replace("_", " ")}`;
  if (event.type === "tackle") return `Tackle ${event.outcome}`;
  if (event.type === "dribble") return event.outcome === "complete" ? "Beat a defender" : "Dribble stopped";
  if (event.type === "substitution") return `Substitution: ${event.receiver} on`;
  if (event.type === "stoppage") {
    const what = event.outcome === "injury" ? "Injury stoppage" : "VAR check, goal stands";
    return event.duration_s ? `${what} (${Math.round(event.duration_s / 6) / 10} min)` : what;
  }
  return descriptions[event.type] ?? event.type;
}

function matchesFilter(event: Event, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "goal") return event.is_goal;
  if (filter === "stops") return ["card", "substitution", "stoppage"].includes(event.type);
  return event.type === filter;
}

function matchFromUrl(): string {
  try { return new URLSearchParams(window.location.search).get("match") ?? DEFAULT_MATCH; } catch { return DEFAULT_MATCH; }
}

const PlayIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z" fill="currentColor" /></svg>);
const PauseIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24"><rect x="6" y="4.5" width="4.2" height="15" rx="1" fill="currentColor" /><rect x="13.8" y="4.5" width="4.2" height="15" rx="1" fill="currentColor" /></svg>);
const ResetIcon = () => (<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg>);
const MoonIcon = () => (<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>);
const SunIcon = () => (<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>);

export default function Home() {
  const [match, setMatch] = useState(DEFAULT_MATCH);
  const [config, setConfig] = useState<Config | null>(null);
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
  const [analysisStatus, setAnalysisStatus] = useState<"idle" | "loading" | "error" | "busy">("idle");
  const [live, setLive] = useState<{ agent: string | null; detail: string; seen: string[]; steps: TraceStep[] }>(
    { agent: null, detail: "", seen: [], steps: [] });
  const [players, setPlayers] = useState<Player[]>([]);
  const [pick, setPick] = useState<{ a: string; b: string }>({ a: "", b: "" });
  const [duel, setDuel] = useState<Duel | null>(null);
  const [moments, setMoments] = useState<Moment[]>([]);
  const [provider, setProvider] = useState<Analysis["engine"]>("offline");
  const aboutRef = useRef<HTMLDialogElement>(null);
  const [momentId, setMomentId] = useState<string | null>(null);
  const [flash, setFlash] = useState<Flash | null>(null);
  const prev = useRef<{ minute: number; home: number; away: number } | null>(null);
  const [followed, setFollowed] = useState<Followed[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const length = config?.length ?? 90;
  const labelOf = (m: number) => config?.labels[m] ?? `${m}'`;

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => { setMatch(matchFromUrl()); setHistory(readHistory()); }, []);

  // switching match starts it from kick-off, with nothing carried over from the last one
  const chooseMatch = (id: string) => {
    if (id === match) return;
    setPlaying(false); setMinute(0); setAnalysis(null); setAnalysisStatus("idle"); setQuestion("");
    setPick({ a: "", b: "" }); setDuel(null); setPlayers([]); setMoments([]); setMomentId(null); setFollowed([]); setFocus("home");
    prev.current = null;
    setMatch(id);
    try { window.history.replaceState(null, "", id === DEFAULT_MATCH ? window.location.pathname : `?match=${id}`); } catch { /* ignore */ }
  };

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/config?match=${match}`, { signal: controller.signal })
      .then((res) => res.json())
      .then((result: Config) => { setConfig(result); setProvider(result.model_provider); })
      .catch(() => {});
    return () => controller.abort();
  }, [match]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/state?minute=${minute}&mode=${mode}&focus=${focus}&match=${match}`, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`API returned ${res.status}`);
        return (await res.json()) as MatchState;
      })
      .then((result) => { setData(result); setLoadError(""); })
      .catch((e: Error) => { if (e.name !== "AbortError") setLoadError("Backend unreachable. Start FastAPI on port 8000, then refresh."); });
    return () => controller.abort();
  }, [minute, mode, focus, match]);

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
          setFlash({ side, player: g?.player ?? "", clock: g?.label ?? data.label, key: Date.now() });
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
    const id = window.setInterval(() => setMinute((m) => (m >= length ? length : m + 1)), 950);
    return () => window.clearInterval(id);
  }, [playing, length]);
  useEffect(() => { if (minute >= length) setPlaying(false); }, [minute, length]);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/players?minute=${minute}&match=${match}`, { signal: controller.signal })
      .then((res) => res.json())
      .then((result: { players: Player[] }) => setPlayers(result.players))
      .catch(() => {});
    return () => controller.abort();
  }, [minute, match]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/moments?minute=${minute}&match=${match}`, { signal: controller.signal })
      .then((res) => res.json())
      .then((result: { moments: Moment[] }) => setMoments(result.moments))
      .catch(() => {});
    return () => controller.abort();
  }, [minute, match]);

  // default duel: the best-rated forward against the best-rated defender on the other side
  useEffect(() => {
    if (pick.a || players.length === 0) return;
    const scorer = players.find((p) => p.position === "FW") ?? players[0];
    const defender = players.find((p) => p.position === "DF" && p.team !== scorer.team)
      ?? players.find((p) => p.name !== scorer.name) ?? players[1];
    setPick({ a: scorer.name, b: defender.name });
  }, [players, pick.a]);

  useEffect(() => {
    if (!pick.a || !pick.b) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ a: pick.a, b: pick.b, minute: String(minute), mode, match });
    fetch(`/api/compare?${params}`, { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then((result: Duel | null) => setDuel(result))
      .catch(() => {});
    return () => controller.abort();
  }, [pick, minute, mode, match]);

  // a followed question is asked again as the match plays on, so its answer stays current
  const refreshFollowed = useCallback((items: Followed[], at: number) => {
    items.forEach((f) => {
      fetch("/api/analyze", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minute: at, mode, focus, question: f.question, match }),
      })
        .then((res) => (res.ok ? res.json() : null))
        .then((result: Analysis | null) => {
          if (!result) return;
          setFollowed((list) => list.map((x) => (x.question === f.question
            ? { ...x, label: labelOf(result.minute), narrative: result.narrative } : x)));
        })
        .catch(() => {});
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, focus, match, config]);
  useEffect(() => {
    if (!playing || followed.length === 0 || minute === 0 || minute % FOLLOW_EVERY !== 0) return;
    refreshFollowed(followed, minute);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [minute, playing]);
  const follow = (q: string, answer: Analysis) => {
    setFollowed((list) => list.some((f) => f.question === q) ? list
      : [...list, { question: q, label: labelOf(answer.minute), narrative: answer.narrative }].slice(-MAX_FOLLOWED));
  };

  const runAgents = useCallback(async (q: string) => {
    setPlaying(false);
    setAnalysisStatus("loading");
    setLive({ agent: null, detail: "", seen: [], steps: [] });
    try {
      // the agents report each step as it happens (newline-delimited JSON), then the result
      const response = await fetch("/api/analyze/stream", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minute, mode, focus, question: q, match }),
      });
      if (response.status === 429) throw new Error("busy");
      if (!response.ok || !response.body) throw new Error(`API returned ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let result: Analysis | null = null;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (!line) continue;
          const item = JSON.parse(line);
          if (item.type === "working") {
            setLive((l) => ({ ...l, agent: item.agent, detail: item.detail,
              seen: l.agent && !l.seen.includes(l.agent) ? [...l.seen, l.agent] : l.seen }));
          } else if (item.type === "step") {
            setLive((l) => ({ ...l, steps: [...l.steps, item as TraceStep] }));
          } else if (item.type === "result") {
            result = item.result as Analysis;
          } else if (item.type === "error") {
            throw new Error(item.detail);
          }
        }
      }
      if (!result) throw new Error("No result");
      const answer: Analysis = result;
      setAnalysis(answer);
      setAnalysisStatus("idle");
      if (q.trim()) {
        setHistory((items) => {
          const next = [{ question: q.trim(), match, label: labelOf(answer.minute), narrative: answer.narrative },
            ...items.filter((h) => !(h.question === q.trim() && h.match === match))].slice(0, 20);
          saveHistory(next);
          return next;
        });
      }
    } catch (e) {
      setAnalysisStatus((e as Error).message === "busy" ? "busy" : "error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [minute, mode, focus, match, config]);

  const askAbout = (q: string) => {
    setQuestion(q);
    document.getElementById("agents")?.scrollIntoView({ behavior: "smooth" });
    runAgents(q);
  };
  const moment = moments.find((m) => m.id === momentId) ?? moments[0];

  const st = data?.stats;
  const home = data?.teams.home;
  const away = data?.teams.away;
  const goals = data?.goal_events ?? [];
  const feed = (filter === "stops" ? data?.stoppages ?? [] : (data?.recent_events ?? []).filter((e) => matchesFilter(e, filter))).slice(0, 8);
  const pct = (minute / length) * 100;
  const firstHalf = config?.first_half ?? 45;
  const status = playing ? "Live" : minute === 0 ? "Kick-off" : minute >= length ? "Full time"
    : minute === firstHalf ? "Half time" : "Paused";
  // the fourth official's board: shown from 45:00 and 90:00 until the half ends
  const board = data && data.minute >= 45 && data.minute <= firstHalf ? data.announced["1"]
    : data && data.minute >= firstHalf + 45 ? data.announced["2"] : null;
  const questions = config?.questions ?? [];
  const pastQuestions = history.filter((h) => h.match === match).slice(0, 6);
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
    { label: "Saves", h: st?.home.saves, a: st?.away.saves },
    { label: "Corners", h: st?.home.corners, a: st?.away.corners },
    { label: "Fouls", h: st?.home.fouls, a: st?.away.fouls },
    { label: "Yellow cards", h: st?.home.yellow_cards, a: st?.away.yellow_cards },
  ];

  return (
    <main className="shell">
      <header className="header">
        <div className="brand"><span className="brand-icon">m</span><span>matchmind</span></div>
        <div className="header-right">
          <span className="header-meta">v0.4 · fictional matches</span>
          <button className="icon-btn" onClick={() => setTheme(theme === "light" ? "dark" : "light")} aria-label="Toggle theme">
            {theme === "light" ? <MoonIcon /> : <SunIcon />}
          </button>
        </div>
      </header>

      <section className="hero">
        <div>
          <h1>Hear the take. <em>See the data.</em></h1>
          <p>Five AI agents watch the match with you. A Pundit says what everyone&apos;s thinking; a Skeptic checks it against every pass, tackle and shot. Ask anything, in plain English.</p>
          <a className="hero-cta" href="#agents">Ask the agents ↓</a>
        </div>
        <div className="hero-meta"><b>Proof of concept</b><br />Premier League Hackathon<br />2026</div>
      </section>

      {loadError && <div className="error-banner" role="alert">{loadError} Instructions are in README.md.</div>}

      <nav className="match-picker" aria-label="Choose a match">
        <span className="control-label">MATCH</span>
        <div className="match-options">
          {(config?.matches ?? []).map((m) => (
            <button key={m.id} className={m.id === match ? "active" : ""} onClick={() => chooseMatch(m.id)} aria-pressed={m.id === match}>
              <b>{m.teams.home.name}</b> <span>v</span> <b>{m.teams.away.name}</b>
            </button>
          ))}
        </div>
        {config?.story && <small className="match-story">{minute >= length ? config.story : "Fictional match · press play or scrub the timeline"}</small>}
      </nav>

      <section
        key={flash ? flash.key : "idle"}
        className={`surface scoreboard ${flash ? "flash" : ""}`}
        style={flashColor ? ({ ["--flash" as string]: flashColor } as React.CSSProperties) : undefined}
        aria-label="Scoreboard"
      >
        <div className="team team-home">
          <div className={`crest crest-home ${flash?.side === "home" ? "scored" : ""}`}>{home?.name[0] ?? ""}</div>
          <div><span className="team-caption">HOME</span><strong>{home?.name ?? ""}</strong><small>{home ? `${home.name.split(" ")[0]}, fictional club` : ""}</small></div>
        </div>
        <div className="score-center">
          <div className={`status-line ${playing ? "live" : ""}`}>{status}</div>
          <div className="big-score">
            <span className="score-num" key={`h${data?.score.home ?? 0}`}>{data?.score.home ?? 0}</span>
            <span className="sep">–</span>
            <span className="score-num" key={`a${data?.score.away ?? 0}`}>{data?.score.away ?? 0}</span>
          </div>
          <div className="minute">{minute === 0 ? "0'" : data?.label ?? labelOf(minute)}{data && minute > 0 ? ` · ${data.period === 1 ? "1st" : "2nd"} half` : ""}{board ? <span className="added-board" title="Added time">+{board}</span> : null}</div>
        </div>
        <div className="team team-away">
          <div><span className="team-caption">AWAY</span><strong>{away?.name ?? ""}</strong><small>{away ? `${away.name.split(" ")[0]}, fictional club` : ""}</small></div>
          <div className={`crest crest-away ${flash?.side === "away" ? "scored" : ""}`}>{away?.name[0] ?? ""}</div>
        </div>
        {flash && <div className="goal-banner">Goal · <b>{flash.player}</b> {flash.clock}</div>}
      </section>

      <section className="playback">
        <button className="play-btn" onClick={() => { if (minute >= length) setMinute(0); setPlaying(!playing || minute >= length); }} aria-label={playing ? "Pause" : "Play"}>
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <button className="text-btn" onClick={() => { setPlaying(false); setMinute(0); }}><ResetIcon />Reset</button>
        <div className="track">
          <input
            type="range" min="0" max={length} step="1" value={minute}
            onChange={(e) => { setPlaying(false); setMinute(Number(e.target.value)); }}
            aria-label="Match minute" aria-valuetext={labelOf(minute)} className="timeline"
            style={{ background: `linear-gradient(90deg,var(--ink) ${pct}%,var(--line-strong) ${pct}%)` }}
          />
          {goals.map((g) => <i key={g.id} className="tick" style={{ left: `${(g.minute / length) * 100}%` }} />)}
          <i className="tick half" style={{ left: `${(firstHalf / length) * 100}%` }} title="Half time" />
        </div>
        <div className="time-end">{labelOf(length)}</div>
      </section>
      <div className="goal-tracks">
        {goals.map((event) => (
          <span key={event.id} title={`${event.player} scored at ${event.clock}`}>{event.label} {event.player}</span>
        ))}
      </div>

      <div className="view-bar">
        <div className="control-row">
          <span className="control-label">EXPLAIN IT FOR</span>
          <div className="seg">
            <button className={mode === "simple" ? "active" : ""} onClick={() => setMode("simple")}>New to football</button>
            <button className={mode === "fan" ? "active" : ""} onClick={() => setMode("fan")}>Fan</button>
            <button className={mode === "analyst" ? "active" : ""} onClick={() => setMode("analyst")}>Analyst</button>
          </div>
        </div>
        <div className="control-row">
          <span className="control-label">FOLLOWING</span>
          <div className="seg">
            <button className={focus === "home" ? "active" : ""} onClick={() => setFocus("home")}>{config?.teams.home.name ?? "Home"}</button>
            <button className={focus === "away" ? "active" : ""} onClick={() => setFocus("away")}>{config?.teams.away.name ?? "Away"}</button>
          </div>
        </div>
      </div>

      <section className="surface agent-room" id="agents">
        <div className="panel-head">
          <h2><span className="section-numeral">01</span>Agent room</h2>
          <span className="panel-meta">
            {analysis ? `${ENGINE_LABEL[analysis.engine]} agents · at ${labelOf(analysis.minute)}` : "Five agents · every take checked"}
          </span>
        </div>
        <form className="ask" onSubmit={(e) => { e.preventDefault(); runAgents(question); }}>
          <input
            value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={300}
            placeholder={`Ask about the match so far (${labelOf(minute)})…`} aria-label="Question for the agents"
          />
          <button type="submit" disabled={analysisStatus === "loading" || minute === 0}>
            {analysisStatus === "loading" ? "Agents working…" : question.trim() ? "Ask the agents" : "Analyse this moment"}
          </button>
        </form>
        <div className="suggestions">
          {questions.map((s) => (
            <button key={s} type="button" onClick={() => { setQuestion(s); runAgents(s); }} disabled={analysisStatus === "loading" || minute === 0}>{s}</button>
          ))}
        </div>
        {analysisStatus === "error" && <div className="recap-box error"><b>AGENTS UNAVAILABLE</b><p>Couldn&apos;t reach the analysis service. Check the backend is running.</p></div>}
        {analysisStatus === "busy" && <div className="recap-box error"><b>ONE MOMENT</b><p>That&apos;s a lot of questions at once. Give the agents a few seconds and try again.</p></div>}
        {!analysis && analysisStatus === "idle" && (
          <div className="empty">{minute === 0 ? "Play or scrub the match, then ask the agents." : "A pundit gives the popular takes, a skeptic checks every one against the data. Ask a question or analyse this moment."}</div>
        )}
        {analysisStatus === "loading" && (
          <div className="live" aria-live="polite">
            <ol className="pipeline">
              {AGENTS.map((name) => {
                const state = name === live.agent ? "working" : live.seen.includes(name) ? "done" : "waiting";
                return <li key={name} className={state}><span>{name}</span><small>{state === "working" ? live.detail : state === "done" ? "done" : "waiting"}</small></li>;
              })}
            </ol>
            <ol className="trace live-trace">
              {live.steps.map((t, i) => (
                <li key={i} className={`trace-step ${t.status}`}>
                  <span className={`agent-tag a${AGENTS.indexOf(t.agent)}`}>{t.agent}</span>
                  <strong>{t.action}</strong>
                  <small>{t.detail}</small>
                </li>
              ))}
            </ol>
          </div>
        )}
        {analysis && analysisStatus !== "loading" && (
          <div className="room">
            <div className="answer">
              <b>THE ANSWER · {analysis.window_label}</b>
              <p>{analysis.narrative}</p>
              <small>Written by the Narrator{analysis.narrative_source === "model" ? ` (${ENGINE_LABEL[analysis.engine]} model)` : ""} from the takes the Skeptic checked below.</small>
              {analysis.question && (
                <button className="follow-btn" type="button" onClick={() => follow(analysis.question, analysis)}
                  disabled={followed.some((f) => f.question === analysis.question)}>
                  {followed.some((f) => f.question === analysis.question) ? "✓ Following this question" : "Follow this question as the match goes on"}
                </button>
              )}
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
                      <span>{takeSource(c, mode === "simple")}</span>
                      <span className={`verdict ${c.verdict}`}>{VERDICT_LABEL[c.verdict]}</span>
                    </div>
                    <h3>&ldquo;{mode === "simple" && c.plain ? c.plain : c.text}&rdquo;</h3>
                    <div className="take-data">
                      <b>{mode === "simple" ? "WHAT ACTUALLY HAPPENED" : "THE DATA"}</b>
                      <p>{mode === "simple" ? c.plain_finding || c.reason : c.finding || c.reason}</p>
                      {c.verdict === "corrected" && mode !== "simple" && <small>{c.reason}</small>}
                    </div>
                    {rethink && (
                      <div className={`rethink ${rethink.verdict}`}>
                        <b>{mode === "simple" ? "ACTUALLY" : "RETHINK"}</b> &ldquo;{mode === "simple" && rethink.plain ? rethink.plain : rethink.text}&rdquo; <span className={`verdict ${rethink.verdict}`}>{VERDICT_LABEL[rethink.verdict]}</span>
                      </div>
                    )}
                    {mode !== "simple" && c.verdict !== "rejected" && c.evidence_ids.length > 0 && (
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
        {followed.length > 0 && (
          <div className="followed" aria-live="polite">
            <b>FOLLOWING · UPDATES EVERY {FOLLOW_EVERY} MINUTES WHILE THE MATCH PLAYS</b>
            {followed.map((f) => (
              <div key={f.question} className="followed-item">
                <div className="followed-top">
                  <strong>{f.question}</strong>
                  <span>
                    <button type="button" onClick={() => refreshFollowed([f], minute)} disabled={minute === 0}>Update now</button>
                    <button type="button" onClick={() => setFollowed((l) => l.filter((x) => x.question !== f.question))} aria-label={`Stop following ${f.question}`}>✕</button>
                  </span>
                </div>
                {f.narrative && <p><small>{f.label}</small> {f.narrative}</p>}
              </div>
            ))}
          </div>
        )}
        {pastQuestions.length > 0 && (
          <details className="history">
            <summary>Your recent questions · saved in this browser only</summary>
            <ul>
              {pastQuestions.map((h) => (
                <li key={h.question}>
                  <button type="button" onClick={() => { setQuestion(h.question); runAgents(h.question); }} disabled={analysisStatus === "loading" || minute === 0}>
                    <b>{h.question}</b><small>Asked at {h.label} · ask again at {labelOf(minute)}</small>
                  </button>
                </li>
              ))}
            </ul>
            <button type="button" className="clear-history" onClick={() => { setHistory([]); saveHistory([]); }}>Clear history</button>
          </details>
        )}
      </section>

      <section className="surface duel">
        <div className="panel-head">
          <h2><span className="section-numeral">02</span>Player duel</h2>
          <span className="panel-meta">Rating out of 10 · who drove the good moments, who caused the bad ones</span>
        </div>
        <div className="duel-pickers">
          {(["a", "b"] as const).map((slot, i) => (
            <label key={slot} className={`picker ${slot}`}>
              <span>{i === 0 ? "PLAYER A" : "PLAYER B"}</span>
              <select value={pick[slot]} onChange={(e) => setPick({ ...pick, [slot]: e.target.value })}>
                {(["home", "away"] as Side[]).map((side) => (
                  <optgroup key={side} label={data?.teams[side].name ?? side}>
                    {players.filter((p) => p.team === side).sort((x, y) => x.number - y.number).map((p) => (
                      <option key={p.name} value={p.name}>{p.number}. {p.name} ({POSITION[p.position]})</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
          ))}
        </div>
        {duel && (
          <>
            <div className="recap-box ai duel-verdict"><b>{duel.winner ? `${duel.winner.toUpperCase()} · MORE HELPFUL` : "TOO CLOSE TO CALL"}</b><p>{duel.verdict}</p></div>
            <div className="ratings">
              {[duel.a, duel.b].map((p, i) => (
                <div key={p.name} className={`rating-card ${i === 0 ? "a" : "b"} ${duel.winner === p.name ? "best" : ""}`}>
                  <div className="rating-num">{p.rating.toFixed(1)}<small>/10</small></div>
                  <div>
                    <strong>{p.name}</strong>
                    <span>{POSITION[p.position]} · {p.team_name}{p.tag ? ` · ${p.tag}` : ""}</span>
                    {p.summary && <p>{p.summary[0].toUpperCase() + p.summary.slice(1)}.</p>}
                  </div>
                </div>
              ))}
            </div>
            <div className="duel-board">
              <div className="stat-heading"><span>{duel.a.name}</span><span>IMPACT POINTS</span><span>{duel.b.name}</span></div>
              {[...duel.categories.map((c) => ({ label: mode === "simple" ? PLAIN_CATEGORY[c.key] : c.label, h: duel.a.values[c.key], a: duel.b.values[c.key] })),
                { label: "Total impact points", h: duel.a.impact, a: duel.b.impact }].map((r) => {
                // bigger bar = better: shift so the worse value sits at zero (handles negative points)
                const low = Math.min(r.h, r.a, 0), h = r.h - low, a = r.a - low, total = h + a;
                const share = total > 0 ? (h / total) * 100 : 50;
                return (
                  <div className={`stat-row ${r.label === "Total impact points" ? "total" : ""}`} key={r.label}>
                    <div className="stat-nums">
                      <strong className={r.h > r.a ? "lead" : ""}>{r.h}</strong>
                      <span>{r.label}</span>
                      <strong className={r.a > r.h ? "lead" : ""}>{r.a}</strong>
                    </div>
                    <div className="bar"><i className="bar-h" style={{ width: `${share}%` }} /><i className="bar-a" style={{ width: `${100 - share}%` }} /></div>
                  </div>
                );
              })}
            </div>
            <div className="moments">
              {[duel.a, duel.b].map((p) => (
                <div key={p.name}>
                  <b>{p.name.toUpperCase()} · BIGGEST MOMENTS</b>
                  <ul>
                    {p.moments.length ? p.moments.map((m) => (
                      <li key={m.event_id}><span>{m.what}</span><code className={m.points < 0 ? "neg" : ""}>{m.points > 0 ? "+" : ""}{m.points}</code></li>
                    )) : <li><span>Nothing yet</span></li>}
                  </ul>
                </div>
              ))}
            </div>
          </>
        )}
        <div className="leaders">
          <b>TOP RATED SO FAR</b>
          {players.slice(0, 5).map((p, i) => (
            <button key={p.name} onClick={() => setPick({ ...pick, a: p.name === pick.b ? pick.a : p.name })}>
              {i + 1}. {p.name} <b>{p.rating.toFixed(1)}</b> <small>{p.tag ?? POSITION[p.position]}</small>
            </button>
          ))}
        </div>
      </section>

        <section className="surface moments-panel">
          <div className="panel-head">
            <h2><span className="section-numeral">03</span>Key moments</h2>
            <span className="panel-meta">Goals and big chances · click one to replay it</span>
          </div>
          {moment ? (
            <div className="moments-body">
              <div className="field replay" aria-label={`Replay: ${moment.title}`}>
                <div className="field-half" /><div className="center-circle" />
                <div className="field-box left-box" /><div className="field-box right-box" />
                <svg key={moment.id} className="replay-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                  <polyline className={`replay-line ${moment.team}`} pathLength={1} points={moment.path.map((p) => `${p.x},${p.y}`).join(" ")} />
                </svg>
                {moment.path.map((p, i) => (
                  <span
                    key={`${moment.id}-${i}`}
                    className={`replay-dot ${moment.team} ${p.kind}`}
                    style={{ left: `${p.x}%`, top: `${p.y}%`, animationDelay: `${(i / Math.max(1, moment.path.length - 1)) * 1.6}s` }}
                    title={p.player}
                  >
                    {(i === 0 || i === moment.path.length - 1) && <i>{p.player}</i>}
                  </span>
                ))}
                <div className="field-label">{moment.label} · {moment.title.toUpperCase()}</div>
              </div>
              <ol className="moment-list">
                {moments.map((m) => (
                  <li key={m.id} className={`${m.id === moment.id ? "active" : ""} ${m.kind}`}>
                    <button className="moment-pick" onClick={() => setMomentId(m.id)}>
                      <span className="moment-min">{m.label}</span>
                      <span className={`event-indicator ${m.team}`} />
                      <span className="moment-text">
                        <b>{m.kind === "goal" ? "Goal · " : ""}{m.title}</b>
                        <small>{m.story}{mode !== "simple" ? ` · ${m.xg.toFixed(2)} xG` : ""}</small>
                      </span>
                    </button>
                    <button className="ask-about" onClick={() => askAbout(m.question)} disabled={analysisStatus === "loading"} aria-label={`Ask the agents about ${m.title} at ${m.label}`}>Ask the agents →</button>
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            <div className="empty moments-empty">{minute === 0 ? "Play the match to see its key moments." : "No goals or big chances yet."}</div>
          )}
          <details className="every-event">
            <summary>Every event · {data?.observed_event_count ?? 0} so far</summary>
            <div className="tabs" role="tablist">
              {FILTERS.map((f) => (
                <button key={f.id} role="tab" aria-selected={filter === f.id} className={`tab ${filter === f.id ? "active" : ""}`} onClick={() => setFilter(f.id)}>{f.label}</button>
              ))}
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
          </details>
        </section>

      <section className="surface stats-panel">
        <div className="panel-head">
          <h2><span className="section-numeral">04</span>Match by the numbers</h2>
          <span className="panel-meta">Cumulative · through {labelOf(minute)}</span>
        </div>
        <div className="stat-heading"><span>{home?.abbr ?? ""}</span><span>METRIC</span><span>{away?.abbr ?? ""}</span></div>
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
        <span>MATCHMIND / v0.4</span>
        <span>ALL CLUBS, PLAYERS, EVENTS AND xG ARE FICTIONAL · NO ACTUAL LEAGUE FOOTAGE</span>
        <button className="about-link" onClick={() => aboutRef.current?.showModal()}>How MatchMind works →</button>
      </footer>

      <dialog ref={aboutRef} className="about" aria-labelledby="about-title" onClick={(e) => { if (e.target === e.currentTarget) aboutRef.current?.close(); }}>
        <div className="about-inner">
          <div className="about-head">
            <h2 id="about-title">How MatchMind works</h2>
            <button className="icon-btn" onClick={() => aboutRef.current?.close()} aria-label="Close">✕</button>
          </div>

          <p className="about-lead">
            Football is full of confident takes. MatchMind checks them. Five AI agents watch a match with you: a Pundit says what
            everyone&apos;s thinking, a Skeptic checks every take against every pass, tackle and shot, and a Narrator tells you
            what holds up, in plain English or in detail.
          </p>

          <h3>The five agents</h3>
          <ol className="about-agents">
            <li><b>Orchestrator</b> turns your question into a team, a stretch of minutes and the stats to check, and spots any assumption in it.</li>
            <li><b>Stats</b> counts everything that happened in that stretch, straight from the event log.</li>
            <li><b>Pundit</b> gives confident takes from what a viewer just saw, without the stats. Usually right, sometimes caught out by recency bias.</li>
            <li><b>Skeptic</b> checks every take against the whole stretch: holds up, half-right, not enough evidence, or doesn&apos;t hold up. Busted takes go back to the Pundit for a rethink. It&apos;s code, not AI, so it can&apos;t be talked round.</li>
            <li><b>Narrator</b> writes the answer from the checked takes only. A guard throws out any answer that quotes a number the Skeptic didn&apos;t produce.</li>
          </ol>
          <p>The agents only ever see events up to the current minute, so nothing comes from the future. Open <i>How the agents got here</i> under any answer to see every step.</p>

          <h3>The player rating</h3>
          <p>
            Ratings out of 10 that ask who drove the moments that mattered and who caused the bad ones. Every move ending in a shot
            shares its value between the shooter, the player who set it up and the rest of the move; every chance the opponent gets
            straight after a player loses the ball counts against that player. Saves and blocks earn the value of the chance
            they stopped, and winning the ball near your own goal is worth the danger it took away. That&apos;s how a defender or a
            goalkeeper can outrate a goalscorer.
          </p>

          <h3>The matches</h3>
          <p>
            Three fictional matches, each simulated pass by pass (about 1,900 events): a 2-1 decided by a pressing spell, a
            2-3 comeback and a goalless game won by the keepers. Like real football they have set pieces, cards, substitutions,
            injuries and VAR checks; the stoppages become added time (45+2&apos;, 90+5&apos;) and break the momentum of the team on
            top, as they do in real matches. Every rate is calibrated against recent men&apos;s football in StatsBomb Open Data
            (2023/24 Bundesliga and Euro 2024). No real Premier League data or footage is used.
          </p>

          <h3>Built with</h3>
          <ul className="about-stack">
            <li><b>Microsoft Agent Framework</b> orchestrates the five agents as a workflow, streamed live to this page.</li>
            <li><b>Azure Container Apps</b> hosts the app: one container serving the site and the API.</li>
            <li><b>GitHub Actions</b> runs the tests and builds the container on every change; GitHub&apos;s container registry stores it.</li>
            <li>
              <b>AI models:</b>{" "}
              {provider === "offline" ? "rule-based agents right now (no model key set)." : `${ENGINE_LABEL[provider]} right now.`}{" "}
              The agents can run on Microsoft Foundry or Nebius Token Factory by changing three settings.
            </li>
            <li><b>FastAPI</b> (Python) for the agents and stats, <b>Next.js</b> for this page.</li>
          </ul>

          <p className="about-foot">
            Built for Inside the Game: the Microsoft Premier League Hackathon 2026 ·{" "}
            <a href="https://github.com/s6ii5vii/matchmind" target="_blank" rel="noreferrer">Source code on GitHub ↗</a>
          </p>
        </div>
      </dialog>
    </main>
  );
}