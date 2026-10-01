/**
 * The only place in the interface that talks to the Python backend.
 *
 * Every call returns documents the engine produced; nothing is derived here.
 * An error carries the engine's own message, which is the same wording the
 * command line would print for the same problem file.
 */

import type {
  AgentRunDoc,
  AgentRunSummaryDoc,
  ArenaPreviewDoc,
  CapabilitiesDoc,
  ComposeArenaRequest,
  ComposeShapeRequest,
  EvaluateRequest,
  ExampleDoc,
  ExampleSummaryDoc,
  InitRequest,
  ProblemDoc,
  ProviderModelsDoc,
  ResearchSessionDoc,
  ResearchSessionSummaryDoc,
  SearchResponseDoc,
  ProvidersDoc,
  ShapeFamilyDoc,
  ShapePreviewDoc,
  StartAgentRunRequest,
  VerdictDoc,
  WorkflowManifestDoc,
  WorkflowToolsDoc,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch (cause) {
    throw new ApiError(
      "the backend is unreachable; start it with `paper-obs serve`",
      0,
    );
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

async function errorMessage(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`;
  try {
    const body: unknown = await response.json();
    if (typeof body !== "object" || body === null || !("detail" in body)) {
      return fallback;
    }
    const detail = body.detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  } catch {
    return fallback;
  }
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

/** POST a request whose answer is a document, not JSON: the SVG of a candidate. */
async function postText(path: string, body: unknown): Promise<string> {
  const response = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  return response.text();
}

export const api = {
  /** Report whether the backend answers, and which version it runs. */
  health: () =>
    request<{
      status: string;
      version: string;
      frontend: boolean;
      frontend_directory: string;
    }>("/health"),

  /** List the example problems the backend can find. */
  examples: () => request<{ examples: ExampleSummaryDoc[] }>("/examples"),

  /** List the packable shapes a new problem can be built from. */
  shapes: () => request<{ shapes: ShapeFamilyDoc[] }>("/shapes"),

  /** Read one example problem, with its search interval. */
  example: (problemId: string) =>
    request<ExampleDoc>(`/examples/${encodeURIComponent(problemId)}`),

  /** Ask the engine for a starting arrangement and its verdict. */
  init: (body: InitRequest) => post<VerdictDoc>("/init", body),

  /**
   * Ask what can be built for a problem, before offering a control that cannot work.
   *
   * The answer is the engine's: which initialisers apply, which baselines apply,
   * and its own sentence when none does. A document the domain refuses answers
   * with both lists empty rather than an error, because "can this be built?" is
   * a question with a true answer even then.
   */
  capabilities: (problem: ProblemDoc) =>
    post<CapabilitiesDoc>("/capabilities", { problem }),

  /** Judge a candidate and get its picture back. */
  evaluate: (body: EvaluateRequest) => post<VerdictDoc>("/evaluate", body),
  validateProblem: (problem: unknown) => post<ProblemDoc>("/problems/validate", { problem }),
  rotateSelection: (body: EvaluateRequest & { shape_ids: string[]; degrees: number }) =>
    post<VerdictDoc>("/rotate-selection", body),

  /**
   * List the search strategies the engine can run.
   *
   * The list is the engine's and it comes in the order the engine wants them
   * shown; the interface adds no strategy of its own and keeps that order.
   */
  baselines: async (): Promise<string[]> =>
    (await request<{ baselines: string[] }>("/baselines")).baselines,

  /**
   * Run one strategy for a number of engine judgements, and get its curve.
   *
   * The answer carries the whole run — every step, the engine's own one-line
   * summary, and the winner's verdict, judged and drawn like any other — so a
   * caller can show the curve and put the best candidate on its canvas without
   * a second trip. A budget outside the bounds the engine accepts comes back as
   * a 400, in the engine's words.
   */
  search: (body: { problem: ProblemDoc; baseline: string; budget: number; seed?: number }) =>
    post<SearchResponseDoc>("/search", body),

  /**
   * List the model providers a client may choose from.
   *
   * The table is the backend's, so adding a provider there adds an option in the
   * interface without a line of TypeScript here. The answer also says whether a
   * key is already configured — never what it is.
   */
  providers: () => request<ProvidersDoc>("/providers"),

  /**
   * Ask a provider which model ids it serves, with the key the caller typed.
   *
   * The ids are returned and forgotten, and the key travels in a request header: a route
   * of this lab never stores one. An endpoint that has no model list answers with its own
   * refusal, redacted before it is returned.
   */
  providerModels: (body: { provider: string; api_key?: string; base_url?: string }) =>
    post<ProviderModelsDoc>("/providers/models", body),

  /** Compile a stack of arena primitives, and get its outline back. */
  composeArena: (body: ComposeArenaRequest) => post<ArenaPreviewDoc>("/arena", body),

  /**
   * Compile the same stack into a packable shape, and get its outline back.
   *
   * A shape is an outline, not a tree: the engine answers with the shape document
   * and with the path it will draw a placement by, so the composer previews the
   * engine's own geometry rather than a second one.
   */
  composeShape: (body: ComposeShapeRequest) => post<ShapePreviewDoc>("/shape", body),

  /**
   * List the workflows the backend can run, with the topology to draw them by.
   *
   * A workflow is a folder of the backend's with a manifest beside it: its steps,
   * its edges and its ceilings come from there, so the panel knows nothing about
   * any of them.
   */
  workflows: async (): Promise<WorkflowManifestDoc[]> =>
    (await request<{ workflows: WorkflowManifestDoc[] }>("/workflows")).workflows,

  /** List a workflow's tools as a model reads them, and the objectives that offer each one. */
  workflowTools: (workflowId: string): Promise<WorkflowToolsDoc> =>
    request<WorkflowToolsDoc>(`/workflows/${encodeURIComponent(workflowId)}/tools`),

  /** List the runs already written, for a picker. */
  /** The free research sessions of one problem, newest first: written by outside agents. */
  researchSessions: async (problemId: string): Promise<ResearchSessionSummaryDoc[]> =>
    (await request<{ sessions: ResearchSessionSummaryDoc[] }>(
      `/research-sessions?problem_id=${encodeURIComponent(problemId)}`)).sessions,

  researchSession: (sessionId: string) =>
    request<ResearchSessionDoc>(`/research-sessions/${encodeURIComponent(sessionId)}`),

  agentRuns: async (): Promise<AgentRunSummaryDoc[]> =>
    (await request<{ runs: AgentRunSummaryDoc[] }>("/agent-runs")).runs,

  /**
   * Read one run, in full.
   *
   * A run that is still going is read the same way as a finished one: the document
   * is written after every turn, so polling this call watches a run happen. A run
   * that has not written its first turn yet answers 404, which a watcher treats as
   * "not yet" rather than as a failure.
   */
  agentRun: (runId: string) => request<AgentRunDoc>(`/agent-runs/${encodeURIComponent(runId)}`),

  /** Ask for a run, and get the identifier to watch. The run happens after the answer. */
  startAgentRun: (body: StartAgentRunRequest) =>
    post<{ run_id: string; status: string }>("/agent-runs", body),

  stopAgentRun: (runId: string) =>
    post<{ run_id: string; status: string }>(`/agent-runs/${encodeURIComponent(runId)}/stop`, {}),

  /**
   * Delete one saved run.
   *
   * A run that is still being written is refused rather than raced: the process that owns
   * it would write the file again on its next turn.
   */
  deleteAgentRun: (runId: string) =>
    request<{ run_id: string; status: string }>(`/agent-runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    }),

  /** Bring a deleted run back among the saved runs. */
  restoreAgentRun: (runId: string) =>
    request<{ run_id: string; status: string }>(`/agent-runs/${encodeURIComponent(runId)}/restore`, {
      method: "POST",
    }),

  /** Get the SVG document of a candidate, for download. */
  render: (body: { problem: unknown; candidate: unknown; options?: unknown }) =>
    postText("/render", body),
};
