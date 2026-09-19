import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  BookOpen,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock3,
  Code2,
  Command,
  ExternalLink,
  FileCode2,
  FlaskConical,
  GitBranch,
  GitCompareArrows,
  Github,
  History,
  Layers3,
  LoaderCircle,
  Mic,
  Pause,
  Play,
  Radio,
  RotateCcw,
  ShieldCheck,
  SlidersHorizontal,
  Terminal,
  Volume2,
  VolumeX,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { useWarRoom } from "./lib/useWarRoom";
import { useBrowserVoice } from "./lib/useBrowserVoice";
import { useGeminiLive } from "./lib/useGeminiLive";
import { HUB_HTTP_URL } from "./lib/api";
import { elapsedMs, getVerifiedCandidates } from "./lib/incident";
import type {
  Evidence,
  FixCandidate,
  Stage,
  VerifyResult,
} from "./lib/contracts";

type ModalContent = { title: string; subtitle?: string; body: ReactNode };
const stageLabels: Record<Stage, string> = {
  alerted: "Incident detected",
  investigating: "Investigating",
  cause_found: "Root cause identified",
  reproduced: "Failure reproduced",
  fixes_proposed: "Repairs proposed",
  verifying: "Testing repairs",
  fix_verified: "Verified fix ready",
  no_fix_found: "No repair verified",
  pr_opened: "Pull request opened",
  resolved: "Incident resolved",
};
const steps: { label: string; stages: Stage[] }[] = [
  { label: "Detected", stages: ["alerted"] },
  { label: "Investigating", stages: ["investigating"] },
  { label: "Root cause", stages: ["cause_found"] },
  { label: "Reproduced", stages: ["reproduced", "fixes_proposed"] },
  { label: "Verifying", stages: ["verifying"] },
  { label: "Fix verified", stages: ["fix_verified", "pr_opened", "resolved"] },
];
const time = (at: string) =>
  new Date(at).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
const duration = (milliseconds: number) => {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
};
function CodeBlock({ code }: { code: string }) {
  return (
    <pre className="code-block">
      {code.split("\n").map((line, i) => (
        <span
          key={i}
          className={
            line.startsWith("+") && !line.startsWith("+++")
              ? "line-add"
              : line.startsWith("-") && !line.startsWith("---")
                ? "line-remove"
                : line.startsWith("@@")
                  ? "line-meta"
                  : ""
          }
        >
          {line || " "}
        </span>
      ))}
    </pre>
  );
}

function CandidateCard({
  candidate,
  result,
  index,
  active,
  onInspect,
  onApprove,
  canApprove,
  mode,
  resolved,
  applied,
}: {
  candidate?: FixCandidate;
  result?: VerifyResult;
  index: number;
  active: boolean;
  onInspect: () => void;
  onApprove: () => void;
  canApprove: boolean;
  mode: string;
  resolved: boolean;
  applied: boolean;
}) {
  const passed = Boolean(
    result?.applied &&
    result.repro_passed &&
    result.suite_passed &&
    result.tests_run > 0 &&
    result.tests_failed === 0,
  );
  const failed = Boolean(result && !passed);
  return (
    <article
      className={`candidate-card ${passed ? "candidate-passed" : ""} ${failed ? "candidate-failed" : ""}`}
    >
      <div className="candidate-top">
        <span className="candidate-number">0{index + 1}</span>
        <span
          className={`status-badge ${passed ? "success" : failed ? "failure" : active ? "testing" : "neutral"}`}
        >
          {passed ? (
            <CheckCircle2 size={13} />
          ) : failed ? (
            <XCircle size={13} />
          ) : active ? (
            <LoaderCircle size={13} className="spin" />
          ) : (
            <Circle size={11} />
          )}{" "}
          {passed
            ? "Verified"
            : failed
              ? "Failed verification"
              : active
                ? "Tests running"
                : "Awaiting candidate"}
        </span>
      </div>
      <div className="candidate-origin">
        {candidate ? (
          candidate.origin === "gemini" ? (
            <>
              <Zap size={12} /> Gemini-generated
            </>
          ) : (
            <>
              <FileCode2 size={12} />
              {mode === "demo" ? "Recorded candidate" : "Authored candidate"}
            </>
          )
        ) : (
          <>&nbsp;</>
        )}
      </div>
      <h3>
        {candidate?.title ??
          [
            "Restore the expected behavior",
            "Test an alternative repair",
            "Check a defensive fix",
          ][index]}
      </h3>
      <p className="candidate-rationale">
        {candidate?.rationale ??
          "The investigation will propose an independent repair and test it against the failure."}
      </p>
      <div className="candidate-checks">
        <div>
          <span>Reproduction test</span>
          {result ? (
            result.repro_passed ? (
              <span className="text-success">
                <Check size={13} />
                Pass
              </span>
            ) : (
              <span className="text-danger">
                <X size={13} />
                Fail
              </span>
            )
          ) : (
            <span className="muted">{active ? "Running…" : "—"}</span>
          )}
        </div>
        <div>
          <span>All test checks</span>
          {result ? (
            <span
              className={result.suite_passed ? "text-success" : "text-danger"}
            >
              {result.suite_passed ? <Check size={13} /> : <X size={13} />}{" "}
              {result.tests_run - result.tests_failed}/{result.tests_run} passed
            </span>
          ) : (
            <span className="muted">{active ? "Running…" : "—"}</span>
          )}
        </div>
      </div>
      <div className="candidate-bottom">
        <button
          className="text-button"
          disabled={!candidate}
          onClick={onInspect}
        >
          <GitCompareArrows size={14} /> Inspect diff <ArrowUpRight size={13} />
        </button>
        <span className="mono muted">
          {result
            ? `${result.duration_s.toFixed(1)}s`
            : candidate
              ? `${candidate.files_touched.length} file${candidate.files_touched.length === 1 ? "" : "s"}`
              : "—"}
        </span>
      </div>
      {passed && (
        <button
          className="approve-button"
          disabled={!canApprove || resolved}
          onClick={onApprove}
        >
          {applied ? <CheckCheck size={15} /> : <ShieldCheck size={15} />}{" "}
          {applied
            ? "Repair applied"
            : resolved
              ? "Verified alternative"
              : mode === "demo"
                ? "Review verified repair"
                : "Approve & apply repair"}
          <ArrowRight size={15} />
        </button>
      )}
    </article>
  );
}

export default function App() {
  const room = useWarRoom();
  const gemini = useGeminiLive();
  const [capabilities, setCapabilities] = useState<{
    gemini_live?: boolean;
    verification?: string;
    investigator_backend?: string;
    repair_backend?: string;
  }>({});
  const {
    state,
    mode,
    connection,
    isPlaying,
    startDemo,
    pauseDemo,
    resumeDemo,
    resetDemo,
    setMode,
    now,
    error,
    clearError,
    transcript: roomTranscript,
    actionPending,
    actionMessage,
    approvedArtifactUrl,
  } = room;
  const [route, setRoute] = useState(
    window.location.pathname === "/operator" ? "operator" : "room",
  );
  const [activeSection, setActiveSection] = useState("overview");
  const [selectedEvidence, setSelectedEvidence] = useState("all");
  const [command, setCommand] = useState("");
  const [modal, setModal] = useState<ModalContent | null>(null);
  const [fault, setFault] = useState<"bad_config" | "null_error">("bad_config");
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const transcript = [
    ...roomTranscript,
    ...(mode === "live" ? gemini.transcript : []),
  ].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
  const current = state.stage;
  const complete = current === "resolved";
  const verified = getVerifiedCandidates(state);
  const elapsed = elapsedMs(state, now);
  const latest = state.updates.at(-1);
  const voice = useBrowserVoice(
    (text) => {
      void room.sendMessage(text);
    },
    gemini.isConnected ? undefined : room.latestCue?.facts,
  );
  const useGemini = mode === "live" && Boolean(capabilities.gemini_live);
  const activeListening = useGemini ? gemini.isListening : voice.listening;
  useEffect(() => {
    if (mode === "demo") gemini.disconnect();
  }, [mode, gemini.disconnect]);
  useEffect(() => {
    if (mode !== "live") return;
    const controller = new AbortController();
    const refresh = () => {
      void fetch(`${HUB_HTTP_URL}/health`, { signal: controller.signal })
        .then((res) => (res.ok ? res.json() : Promise.reject()))
        .then((data) => setCapabilities(data))
        .catch(() => {});
    };
    refresh();
    const timer = window.setInterval(refresh, 8000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [mode]);
  const busy = Boolean(actionPending);
  const hasIncident = Boolean(state.incidentId);
  const currentStep =
    current === "no_fix_found"
      ? 4
      : steps.findIndex((step) => current && step.stages.includes(current));
  const evidence = state.evidence.filter(
    (item) =>
      selectedEvidence === "all" ||
      (selectedEvidence === "code"
        ? ["code", "deploy_diff"].includes(item.kind)
        : ["trace", "exception", "metric"].includes(item.kind)),
  );
  useEffect(() => {
    const fn = () =>
      setRoute(window.location.pathname === "/operator" ? "operator" : "room");
    window.addEventListener("popstate", fn);
    return () => window.removeEventListener("popstate", fn);
  }, []);
  useEffect(() => {
    const scroller = transcriptEnd.current?.parentElement;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }, [transcript.length]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        input.current?.focus();
      }
      if (event.key === "Escape") setModal(null);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    if (!modal) return;
    const before = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const nodes = dialog.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]),a[href],input:not([disabled]),[tabindex="0"]',
      );
      if (!nodes?.length) return;
      const first = nodes[0],
        last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", trap);
      if (before?.isConnected) before.focus();
    };
  }, [modal]);
  const navigate = (target: string) => {
    const operator = target === "operator";
    setRoute(operator ? "operator" : "room");
    setActiveSection(target);
    window.history.pushState({}, "", operator ? "/operator" : "/");
    if (!operator)
      window.setTimeout(
        () =>
          target === "overview"
            ? window.scrollTo({ top: 0, behavior: "smooth" })
            : document
                .getElementById(target)
                ?.scrollIntoView({ behavior: "smooth", block: "start" }),
        40,
      );
  };
  const send = (event: FormEvent) => {
    event.preventDefault();
    if (!command.trim() || busy) return;
    if (gemini.isConnected) gemini.sendText(command.trim());
    else void room.sendMessage(command.trim());
    setCommand("");
  };
  const inspect = (candidate: FixCandidate, result?: VerifyResult) =>
    setModal({
      title: candidate.title,
      subtitle: `${candidate.files_touched.join(", ")} · ${mode === "demo" ? "Recorded fixture" : capabilities.verification === "modal" ? "Modal sandbox verification" : "Local verification"}`,
      body: (
        <>
          <p>{candidate.rationale}</p>
          <p className="muted">
            {candidate.origin === "gemini"
              ? "Generated by Gemini from the observed source and evidence."
              : "Authored candidate for a controlled incident."}
            {candidate.snapshot_sha && (
              <>
                {" "}
                Source snapshot:{" "}
                <code>{candidate.snapshot_sha.slice(0, 16)}</code>
              </>
            )}
          </p>
          <CodeBlock code={candidate.patch} />
          {result && (
            <>
              <h4>Verification output</h4>
              <CodeBlock code={result.log_tail || "No output captured."} />
            </>
          )}
        </>
      ),
    });
  const approve = (candidate: FixCandidate) => {
    if (mode === "demo") {
      void room.approveFix(candidate.candidate_id);
      inspect(
        candidate,
        state.results.find((r) => r.candidate_id === candidate.candidate_id),
      );
    } else
      setModal({
        title: "Apply this verified repair?",
        subtitle: "Only the local toy shop will change.",
        body: (
          <>
            <p>
              The reproduction test and the regression suite passed for{" "}
              <strong>{candidate.title}</strong>. Applying it will update the
              running demo shop and verify the repair again.
            </p>
            <CodeBlock code={candidate.patch} />
            <button
              className="primary-button"
              onClick={() => {
                setModal(null);
                void room.approveFix(candidate.candidate_id);
              }}
            >
              <ShieldCheck size={16} />
              Approve & apply repair
            </button>
          </>
        ),
      });
  };
  const download = () => {
    const file = new Blob(
      [
        JSON.stringify(
          {
            mode,
            exported_at: new Date().toISOString(),
            incident_id: state.incidentId,
            events: state.updates,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(file);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${state.incidentId ?? "incident"}-report.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const runbook = () =>
    setModal({
      title: "A small system. A real repair loop.",
      subtitle: "FIRST RESPONSE / FIELD GUIDE",
      body: (
        <div className="runbook">
          <p>
            First Response investigates two rehearsed faults in a toy checkout
            service. Every offered repair must pass a reproducing test and the
            regression suite.
          </p>
          <h4>01 · Recorded rehearsal</h4>
          <p>
            Choose a fault and run the recording. Events, test results and
            conversation are illustrative fixtures. No service is changed and no
            tests run in this mode.
          </p>
          <h4>02 · Local system</h4>
          <p>
            Start the Python hub, switch to Live system, and open Operator.
            Inject a fault to change the local toy shop. With cloud mode
            enabled, Pydantic AI analyzes the observed evidence using Gemini and
            Gemini generates three bounded candidate edits from the broken
            source. Each is tested in a network-disabled Modal sandbox. The UI
            identifies authored candidates when generation is disabled. The
            offline mode uses predefined evidence rules and separate local
            pytest processes; local processes are not a security sandbox.
          </p>
          <h4>03 · Talk to the room</h4>
          <p>
            Ask “What’s happening?”, “Explain the cause”, or “What was tried?”.
            Type a command or use browser speech recognition where available.
            Spoken updates read the same recorded or observed facts. In Live
            system mode, a configured Gemini session provides native
            conversational audio and tool calling. Browser voice remains a
            rehearsal fallback; speech recognition may use your browser
            provider’s service.
          </p>
          <h4>04 · Approve with evidence</h4>
          <p>
            Inspect the diff and test logs, then approve a verified repair.
            Local approval applies it only to the toy shop and saves a patch
            file. This build does not create remote pull requests.
          </p>
          <div className="note">
            <ShieldCheck size={18} /> Passing tests establish the rehearsed
            behavior; they do not prove a repair is safe for production.
          </div>
        </div>
      ),
    });

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="/"
          onClick={(event) => {
            event.preventDefault();
            navigate("overview");
          }}
        >
          <span className="brand-mark">
            <Activity size={24} strokeWidth={2.2} />
          </span>
          <span>
            first<span className="brand-light">response</span>
            <small>INCIDENT COMMAND</small>
          </span>
        </a>
        <div className="workspace">
          <span className="workspace-icon">
            <Layers3 size={17} />
          </span>
          <div>
            Demo workspace<small>On-call engineering</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {[
            { id: "overview", label: "War room", icon: Activity },
            { id: "evidence", label: "Evidence", icon: FileCode2 },
            { id: "repairs", label: "Repair lab", icon: FlaskConical },
            { id: "operator", label: "Operator", icon: SlidersHorizontal },
          ].map((item) => (
            <button
              key={item.id}
              className={`nav-item ${(route === "operator" ? item.id === "operator" : activeSection === item.id) ? "active" : ""}`}
              onClick={() => navigate(item.id)}
            >
              <item.icon size={18} />
              {item.label}
              {item.id === "evidence" && state.evidence.length > 0 && (
                <span className="nav-count">{state.evidence.length}</span>
              )}
              {item.id === "overview" && hasIncident && (
                <span className={`nav-dot ${complete ? "green" : ""}`} />
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <div className="orbit-mark">
            <ShieldCheck size={21} />
          </div>
          <h4>Evidence before action.</h4>
          <p>
            Find the cause. Test the repair.
            <br />
            Then make the call.
          </p>
          <button onClick={runbook}>
            How it works <ArrowUpRight size={13} />
          </button>
        </div>
        <div className="sidebar-bottom">
          <button className="nav-item" onClick={runbook}>
            <BookOpen size={17} />
            Field guide
            <ArrowUpRight size={14} />
          </button>
          <div className="operator-profile">
            <span>OC</span>
            <div>
              On-call operator<small>Human in the loop</small>
            </div>
            <span className="online-dot" />
          </div>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{route === "operator" ? "Operator" : "War room"}</strong>
          </div>
          <div className="topbar-right">
            <div className="mode-switch" aria-label="Data source">
              <button
                className={mode === "demo" ? "selected" : ""}
                onClick={() => setMode("demo")}
              >
                Rehearsal
              </button>
              <button
                className={mode === "live" ? "selected" : ""}
                onClick={() => setMode("live")}
              >
                Live system
              </button>
            </div>
            <span
              className={`connection ${connection === "connected" ? "connected" : ""}`}
            >
              <span />
              {mode === "demo"
                ? "Recorded events"
                : connection === "connected"
                  ? "Hub connected"
                  : connection === "connecting"
                    ? "Connecting…"
                    : "Hub offline"}
            </span>
            <span className="topbar-avatar">OC</span>
          </div>
        </header>
        <main>
          {error && (
            <div className="error-banner" role="alert">
              <XCircle size={17} />
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={clearError}>
                <X size={16} />
              </button>
            </div>
          )}
          {gemini.error && (
            <div className="error-banner" role="alert">
              <AudioLines size={17} />
              <span>{gemini.error}</span>
              <button
                aria-label="Dismiss voice error"
                onClick={gemini.clearError}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {actionMessage && (
            <div className="action-banner" role="status">
              <CheckCircle2 size={15} />
              {actionMessage}
            </div>
          )}
          {route === "operator" ? (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">CONTROL PLANE</div>
                  <h1>Set the scene.</h1>
                  <p>Two small faults. One complete investigation.</p>
                </div>
                <button
                  className="secondary-button"
                  onClick={() => navigate("overview")}
                >
                  Back to war room <ArrowRight size={15} />
                </button>
              </div>
              <div className="operator-mode-note">
                <Radio size={20} />
                <div>
                  <strong>
                    {mode === "demo"
                      ? "Recorded rehearsal mode"
                      : "Live system mode"}
                  </strong>
                  <p>
                    {mode === "demo"
                      ? "Fault buttons replay recorded events. Switch to Live system to run real tests."
                      : "Faults modify an isolated working copy of the toy shop. Source files remain intact."}
                  </p>
                </div>
                <span className="small-badge">
                  {mode === "demo" ? "NO SERVICE CHANGES" : "TOY SHOP ONLY"}
                </span>
              </div>
              <div className="operator-grid">
                {[
                  {
                    id: "bad_config" as const,
                    title: "The three-millisecond timeout",
                    subtitle: "BAD CONFIGURATION",
                    icon: Clock3,
                    description:
                      "A routine config change turns a 3,000 ms payment timeout into 3 ms. Checkout requests start failing.",
                    code: "PAYMENT_TIMEOUT_MS = 3",
                    before: "Expected: 3000 ms",
                  },
                  {
                    id: "null_error" as const,
                    title: "The missing coupon",
                    subtitle: "NULL REFERENCE",
                    icon: Code2,
                    description:
                      "A checkout refactor assumes every cart has a coupon. Orders without one hit an AttributeError.",
                    code: "cart.coupon.code",
                    before: "Expected: optional coupon guard",
                  },
                ].map((item) => (
                  <article className="fault-card" key={item.id}>
                    <span className="fault-icon">
                      <item.icon size={24} />
                    </span>
                    <div className="eyebrow">{item.subtitle}</div>
                    <h2>{item.title}</h2>
                    <p>{item.description}</p>
                    <div className="fault-code">
                      <code>{item.code}</code>
                      <span>{item.before}</span>
                    </div>
                    <button
                      className="primary-button"
                      disabled={
                        busy || (mode === "live" && connection !== "connected")
                      }
                      onClick={() => {
                        setFault(item.id);
                        if (mode === "demo") void startDemo(item.id);
                        else void room.applyFault(item.id);
                        navigate("overview");
                      }}
                    >
                      <Zap size={16} />
                      {mode === "demo"
                        ? "Rehearse this fault"
                        : "Inject fault & investigate"}
                      <ArrowRight size={16} />
                    </button>
                  </article>
                ))}
              </div>
              <div className="reset-panel">
                <div>
                  <h3>Back to a clean slate</h3>
                  <p>
                    Stop the current investigation and restore the toy shop.
                  </p>
                </div>
                <button
                  className="secondary-button"
                  disabled={
                    busy || (mode === "live" && connection !== "connected")
                  }
                  onClick={() =>
                    mode === "demo" ? resetDemo() : void room.resetFault()
                  }
                >
                  <RotateCcw size={15} />
                  Reset {mode === "demo" ? "rehearsal" : "system"}
                </button>
              </div>
            </>
          ) : (
            <>
              <div id="overview" className="page-heading">
                <div>
                  <div className="eyebrow">
                    <span
                      className={`live-indicator ${complete ? "is-complete" : ""}`}
                    />
                    {hasIncident
                      ? `${state.incidentId?.replaceAll("_", "-")} / CHECKOUT`
                      : "YOUR INCIDENT COMMAND CENTER"}
                  </div>
                  <h1>
                    {complete
                      ? "Back in business."
                      : current === "no_fix_found"
                        ? "Investigation needs attention."
                        : verified.length
                          ? "A repair you can verify."
                          : hasIncident
                            ? "Checkout needs attention."
                            : "Stay calm. Find the cause."}
                  </h1>
                  <p>
                    {complete
                      ? "The approved repair passed verification and is applied to the local shop."
                      : hasIncident
                        ? "From the first signal to a tested repair. Every step, in the open."
                        : "Your on-call partner for the moments that matter."}
                  </p>
                </div>
                <div className="heading-actions">
                  {hasIncident && (
                    <button
                      className="icon-button"
                      aria-label="Export incident report"
                      title="Export incident report"
                      onClick={download}
                    >
                      <ArrowDownToLine size={17} />
                    </button>
                  )}
                  {mode === "demo" ? (
                    <button
                      className="secondary-button"
                      disabled={busy}
                      onClick={() => {
                        void startDemo(fault);
                      }}
                    >
                      <RotateCcw size={15} />
                      {hasIncident ? "Replay incident" : "Run rehearsal"}
                    </button>
                  ) : (
                    <button
                      className="secondary-button"
                      onClick={() => navigate("operator")}
                    >
                      <SlidersHorizontal size={15} />
                      Inject a fault
                    </button>
                  )}
                </div>
              </div>
              <div className="incident-grid">
                <section className="incident-summary panel">
                  <div className="panel-topline">
                    <span className={`severity ${complete ? "resolved" : ""}`}>
                      <span />
                      {complete
                        ? "RESOLVED"
                        : hasIncident
                          ? "SEV 2 · CHECKOUT"
                          : "STANDING BY"}
                    </span>
                    <span className="mono muted small">
                      {mode === "demo"
                        ? "REHEARSAL"
                        : capabilities.verification === "modal"
                          ? "MODAL SANDBOXES"
                          : "LOCAL SYSTEM"}
                    </span>
                  </div>
                  <div className="incident-core">
                    <div>
                      <h2>
                        {current ? stageLabels[current] : "Ready when you are."}
                      </h2>
                      <p>
                        {latest?.message ??
                          "Inject a fault or run a rehearsal to see the investigation unfold."}
                      </p>
                    </div>
                    <div
                      className={`incident-timer ${verified.length ? "timer-complete" : ""}`}
                    >
                      <span className="timer-label">
                        <Clock3 size={12} />
                        {state.verifiedAt
                          ? "TIME TO VERIFIED FIX"
                          : "INCIDENT ELAPSED"}
                      </span>
                      <strong>
                        {duration(elapsed)}
                        <span>.{Math.floor((elapsed % 1000) / 100)}</span>
                      </strong>
                    </div>
                  </div>
                  <div className="service-strip">
                    <span>
                      <span
                        className={`service-dot ${hasIncident && !complete ? "degraded" : ""}`}
                      />
                      checkout{" "}
                      <small>
                        {hasIncident
                          ? complete
                            ? "restored"
                            : "incident open"
                          : "no active incident"}
                      </small>
                    </span>
                    <span>
                      <GitBranch size={13} />
                      {state.rootCause?.commit?.slice(0, 7) ??
                        (state.rootCause
                          ? `${state.rootCause.file.split("/").at(-1)}:${state.rootCause.line ?? "?"}`
                          : "Awaiting evidence")}
                    </span>
                    <span>
                      <ShieldCheck size={13} />
                      {complete ? "Approved & rechecked" : "Approval required"}
                    </span>
                  </div>
                </section>
                <section
                  data-audio-bytes={gemini.audioReceivedBytes}
                  className={`voice-card ${activeListening || gemini.isSpeaking ? "listening" : ""}`}
                >
                  <div className="voice-card-top">
                    <span>
                      <AudioLines size={18} />
                      Your incident copilot
                    </span>
                    <span className="small-badge">
                      {useGemini ? "GEMINI LIVE" : "BROWSER VOICE"}
                    </span>
                  </div>
                  <div className="waveform" aria-hidden="true">
                    {Array.from({ length: 43 }, (_, i) => (
                      <i
                        key={i}
                        style={{
                          height: `${8 + Math.abs(Math.sin(i * 0.73) * Math.cos(i * 0.29)) * 40}px`,
                          animationDelay: `${i * 37}ms`,
                        }}
                      />
                    ))}
                  </div>
                  <div className="voice-status">
                    <span className="online-dot" />
                    {useGemini
                      ? gemini.isConnecting
                        ? "Connecting to Gemini…"
                        : gemini.isSpeaking
                          ? "First Response is speaking."
                          : gemini.isListening
                            ? "Listening. Tell me what you need."
                            : gemini.isConnected
                              ? "Connected. Type or unmute your mic."
                              : "Gemini voice. Evidence in real time."
                      : voice.listening
                        ? "Listening. Tell me what you need."
                        : voice.spoken
                          ? "Spoken updates are enabled."
                          : "A clear head when things break."}
                  </div>
                  <div className="voice-controls">
                    <button
                      className={`mic-button ${activeListening ? "recording" : ""}`}
                      aria-pressed={activeListening}
                      onClick={() =>
                        useGemini
                          ? gemini.isConnected
                            ? void gemini.toggleListening()
                            : void gemini.connect()
                          : voice.toggleListening()
                      }
                      disabled={busy || gemini.isConnecting}
                    >
                      <Mic size={16} />
                      {useGemini
                        ? gemini.isConnecting
                          ? "Connecting…"
                          : gemini.isConnected
                            ? gemini.isListening
                              ? "Mute microphone"
                              : "Enable microphone"
                            : "Connect Gemini Live"
                        : voice.listening
                          ? "Stop listening"
                          : "Talk to the room"}
                    </button>
                    <button
                      className="voice-sound"
                      aria-label={
                        useGemini
                          ? gemini.isConnected
                            ? "Disconnect Gemini"
                            : "Connect Gemini without microphone"
                          : voice.spoken
                            ? "Mute spoken updates"
                            : "Enable spoken updates"
                      }
                      title={
                        useGemini
                          ? gemini.isConnected
                            ? "Disconnect session"
                            : "Text input, Gemini voice output"
                          : voice.spoken
                            ? "Mute spoken updates"
                            : "Enable spoken updates"
                      }
                      onClick={() =>
                        useGemini
                          ? gemini.isConnected
                            ? gemini.disconnect()
                            : void gemini.connect({ microphone: false })
                          : voice.toggleSpoken()
                      }
                      disabled={
                        gemini.isConnecting ||
                        (!useGemini && !voice.speechAvailable)
                      }
                    >
                      {useGemini ? (
                        gemini.isConnected ? (
                          <X size={18} />
                        ) : (
                          <Terminal size={18} />
                        )
                      ) : voice.spoken ? (
                        <Volume2 size={18} />
                      ) : (
                        <VolumeX size={18} />
                      )}
                    </button>
                  </div>
                  {!useGemini && voice.voiceError && (
                    <p className="voice-error" role="alert">
                      {voice.voiceError}
                    </p>
                  )}
                  {!useGemini && !voice.supported && (
                    <small className="voice-unavailable">
                      Mic unavailable here. Type a command below.
                    </small>
                  )}
                </section>
              </div>
              <section
                className="stage-track"
                aria-label="Investigation progress"
              >
                {steps.map((step, index) => {
                  const done =
                    index < currentStep || (index === 5 && verified.length > 0);
                  const active = index === currentStep;
                  return (
                    <div
                      key={step.label}
                      className={`stage-step ${done ? "done" : ""} ${active ? "current" : ""}`}
                    >
                      <span className="stage-node">
                        {done ? (
                          <Check size={13} />
                        ) : active &&
                          current !== "no_fix_found" &&
                          (isPlaying || mode === "live") ? (
                          <LoaderCircle size={13} className="spin" />
                        ) : (
                          <span>{index + 1}</span>
                        )}
                      </span>
                      <span>{step.label}</span>
                      {index < steps.length - 1 && (
                        <span className="stage-line" />
                      )}
                    </div>
                  );
                })}
              </section>
              {mode === "demo" && (
                <div className="replay-toolbar">
                  <span>
                    <span className="recorded-dot" />
                    RECORDED REHEARSAL{" "}
                    <span className="replay-description">
                      Illustrative events · no live tests
                    </span>
                  </span>
                  <div>
                    <select
                      aria-label="Rehearsal fault"
                      value={fault}
                      onChange={(e) =>
                        setFault(e.target.value as "bad_config" | "null_error")
                      }
                    >
                      <option value="bad_config">Payment timeout</option>
                      <option value="null_error">Missing coupon</option>
                    </select>
                    <button
                      className="text-button"
                      onClick={() => {
                        if (isPlaying) pauseDemo();
                        else if (hasIncident) resumeDemo();
                        else void startDemo(fault);
                      }}
                      disabled={busy}
                    >
                      {isPlaying ? <Pause size={13} /> : <Play size={13} />}{" "}
                      {isPlaying ? "Pause" : hasIncident ? "Resume" : "Play"}
                    </button>
                  </div>
                </div>
              )}
              <section id="repairs" className="repair-section">
                <div className="section-heading">
                  <div>
                    <span className="section-icon">
                      <FlaskConical size={18} />
                    </span>
                    <h2>Three approaches. One proof.</h2>
                    <span className="count-pill">
                      {state.candidates.length || 3}
                    </span>
                  </div>
                  <span className="section-caption">
                    {mode === "demo"
                      ? "Recorded verification"
                      : capabilities.repair_backend === "gemini"
                        ? "Gemini generation · Modal verification"
                        : capabilities.verification === "modal"
                          ? "Modal sandbox verification"
                          : "Independent local test runs"}
                    <span className="dot-separator">·</span>Human-approved
                    repairs
                  </span>
                </div>
                <div className="candidate-grid">
                  {[0, 1, 2].map((index) => {
                    const candidate = state.candidates[index];
                    const result = state.results.find(
                      (r) => r.candidate_id === candidate?.candidate_id,
                    );
                    return (
                      <CandidateCard
                        key={candidate?.candidate_id ?? index}
                        candidate={candidate}
                        result={result}
                        index={index}
                        active={Boolean(
                          candidate && !result && current === "verifying",
                        )}
                        onInspect={() =>
                          candidate && inspect(candidate, result)
                        }
                        onApprove={() => candidate && approve(candidate)}
                        canApprove={
                          !busy &&
                          current === "fix_verified" &&
                          (mode === "demo" || connection === "connected")
                        }
                        mode={mode}
                        resolved={complete}
                        applied={
                          complete &&
                          room.approvedCandidateId === candidate?.candidate_id
                        }
                      />
                    );
                  })}
                </div>
                {current === "no_fix_found" && (
                  <div className="error-banner">
                    <XCircle size={17} />
                    {latest?.message ??
                      "The investigation stopped. No repair is available for approval."}
                  </div>
                )}
                {approvedArtifactUrl && (
                  <a
                    className="artifact-link"
                    href={approvedArtifactUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ArrowDownToLine size={16} />
                    Download approved patch
                    <ArrowUpRight size={14} />
                  </a>
                )}
                {state.prUrl && (
                  <a
                    className="artifact-link"
                    href={state.prUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Github size={16} />
                    Open pull request
                    <ExternalLink size={14} />
                  </a>
                )}
              </section>
              <div className="details-grid">
                <section id="evidence" className="evidence-panel panel">
                  <div className="section-heading">
                    <div>
                      <span className="section-icon">
                        <FileCode2 size={18} />
                      </span>
                      <h2>The evidence trail</h2>
                      <span className="count-pill">
                        {state.evidence.length}
                      </span>
                    </div>
                    <span className="muted small">OBSERVED, NOT ASSUMED</span>
                  </div>
                  <div className="evidence-tabs">
                    {[
                      { id: "all", label: "All evidence" },
                      { id: "traces", label: "Traces & signals" },
                      { id: "code", label: "Code & deploys" },
                    ].map((tab) => (
                      <button
                        className={
                          selectedEvidence === tab.id ? "selected" : ""
                        }
                        key={tab.id}
                        onClick={() => setSelectedEvidence(tab.id)}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>
                  {state.rootCause && (
                    <div className="root-cause">
                      <span>
                        <Zap size={15} />
                        ROOT CAUSE{" "}
                        <small>
                          {Math.round(state.rootCause.confidence * 100)}%
                          confidence
                        </small>
                      </span>
                      <p>{state.rootCause.explanation}</p>
                    </div>
                  )}
                  <div className="evidence-list">
                    {evidence.length ? (
                      evidence.map((item) => (
                        <EvidenceCard
                          key={item.evidence_id}
                          evidence={item}
                          onClick={() =>
                            setModal({
                              title: item.summary,
                              subtitle: item.source_ref ?? item.kind,
                              body: <CodeBlock code={item.detail} />,
                            })
                          }
                        />
                      ))
                    ) : (
                      <div className="empty-state">
                        <div>
                          <GitCompareArrows size={26} />
                        </div>
                        <h3>Follow the facts.</h3>
                        <p>
                          Trace excerpts, deploy changes, and the failing code
                          will appear as the investigation progresses.
                        </p>
                        <span>Every conclusion starts with evidence.</span>
                      </div>
                    )}
                  </div>
                </section>
                <section className="transcript-panel panel">
                  <div className="section-heading">
                    <div>
                      <span className="section-icon">
                        <Terminal size={18} />
                      </span>
                      <h2>Room conversation</h2>
                    </div>
                    <span className="small live-label">
                      <span />{" "}
                      {mode === "demo"
                        ? "REHEARSAL"
                        : gemini.isConnected
                          ? "GEMINI LIVE"
                          : "LIVE"}
                    </span>
                  </div>
                  <div
                    className="transcript-messages"
                    aria-live="polite"
                    aria-relevant="additions"
                  >
                    {transcript.length ? (
                      transcript.map((entry) => (
                        <div
                          className={`message ${entry.role === "user" ? "user-message" : ""}`}
                          key={entry.id}
                        >
                          <div className="message-avatar">
                            {entry.role === "assistant" ? (
                              <Activity size={13} />
                            ) : (
                              <Command size={12} />
                            )}
                          </div>
                          <div>
                            <div className="message-meta">
                              <strong>
                                {entry.role === "assistant"
                                  ? entry.source === "gemini"
                                    ? "First Response · Gemini"
                                    : "First Response"
                                  : "You"}
                              </strong>
                              <time>{time(entry.at)}</time>
                            </div>
                            <p>{entry.text}</p>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="conversation-intro">
                        <span className="conversation-spark">
                          <AudioLines size={25} />
                        </span>
                        <h3>Let’s work the problem.</h3>
                        <p>
                          I’ll surface the evidence and the test results. You
                          make the call.
                        </p>
                        <button
                          onClick={() => {
                            setCommand("What is happening with checkout?");
                            input.current?.focus();
                          }}
                        >
                          “What’s happening with checkout?”{" "}
                          <ArrowUpRight size={13} />
                        </button>
                      </div>
                    )}
                    <div ref={transcriptEnd} />
                  </div>
                  <form className="command-form" onSubmit={send}>
                    <div>
                      <input
                        ref={input}
                        aria-label="Message the incident copilot"
                        placeholder={
                          gemini.isConnected
                            ? "Talk to Gemini about this incident…"
                            : "Ask about this incident…"
                        }
                        value={command}
                        onChange={(e) => setCommand(e.target.value)}
                        disabled={actionPending === "say"}
                      />
                      <button
                        type="submit"
                        aria-label="Send command"
                        disabled={
                          !command.trim() ||
                          busy ||
                          (mode === "live" && connection !== "connected")
                        }
                      >
                        {actionPending === "say" ? (
                          <LoaderCircle size={16} className="spin" />
                        ) : (
                          <ArrowRight size={17} />
                        )}
                      </button>
                    </div>
                    <span>
                      <span className="keyboard-key">⌘ K</span> to focus{" "}
                      <span>Voice optional. Evidence essential.</span>
                    </span>
                  </form>
                </section>
              </div>
              <button
                className="activity-button"
                onClick={() =>
                  setModal({
                    title: "Incident activity",
                    subtitle: `${state.updates.length} recorded state changes`,
                    body: (
                      <div className="event-history">
                        {state.updates.length ? (
                          state.updates.map((update, i) => (
                            <div key={i}>
                              <time>{time(update.at)}</time>
                              <span>
                                <strong>{stageLabels[update.stage]}</strong>
                                <p>{update.message}</p>
                              </span>
                            </div>
                          ))
                        ) : (
                          <p>No incident events yet.</p>
                        )}
                      </div>
                    ),
                  })
                }
              >
                <History size={15} />
                View full incident activity
                <ArrowRight size={14} />
              </button>
            </>
          )}
          <footer>
            <span>
              <Activity size={14} />
              FIRST RESPONSE <span className="dot-separator">/</span> Built for
              the moments that matter.
            </span>
            <span>
              {mode === "demo" ? "Rehearsal data" : "Local toy shop"}
              <span className="dot-separator">·</span>Evidence → verification →
              approval
            </span>
          </footer>
        </main>
      </div>
      {modal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setModal(null);
          }}
        >
          <section
            ref={dialog}
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
          >
            <header>
              <div>
                <span className="eyebrow">
                  {modal.subtitle ?? "FIRST RESPONSE"}
                </span>
                <h2 id="modal-title">{modal.title}</h2>
              </div>
              <button
                className="icon-button"
                aria-label="Close dialog"
                onClick={() => setModal(null)}
                autoFocus
              >
                <X size={20} />
              </button>
            </header>
            <div className="modal-body">{modal.body}</div>
          </section>
        </div>
      )}
    </div>
  );
}
function EvidenceCard({
  evidence,
  onClick,
}: {
  evidence: Evidence;
  onClick: () => void;
}) {
  const diff = evidence.kind === "deploy_diff";
  const trace = ["trace", "exception"].includes(evidence.kind);
  return (
    <button className="evidence-card" onClick={onClick}>
      <span className={`evidence-icon ${diff ? "diff" : trace ? "trace" : ""}`}>
        {diff ? (
          <GitBranch size={17} />
        ) : trace ? (
          <Activity size={17} />
        ) : (
          <FileCode2 size={17} />
        )}
      </span>
      <span className="evidence-card-body">
        <span className="evidence-kind">
          {evidence.kind.replaceAll("_", " ")}
          <span>{evidence.source_ref}</span>
        </span>
        <strong>{evidence.summary}</strong>
        <code className={diff ? "diff-preview" : ""}>
          {evidence.detail
            .split("\n")
            .find((line) =>
              diff
                ? line.startsWith("+") && !line.startsWith("+++")
                : line.trim().length > 0 && !/^\s*\d+\s*$/.test(line),
            ) ?? evidence.detail.slice(0, 130)}
        </code>
      </span>
      <ArrowUpRight size={15} />
    </button>
  );
}
