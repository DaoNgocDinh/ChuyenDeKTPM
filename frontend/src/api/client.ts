import type {
  ApiErrorBody,
  ApprovalRequest,
  ArtifactDetail,
  ArtifactItem,
  ClarificationRequest,
  CreateProjectRequest,
  CreateRunRequest,
  DecisionReceipt,
  ErrorCode,
  EventsPage,
  FinalAcceptanceRequest,
  Project,
  RunDetail,
  RunTicket,
  TaskItem,
  TestReportItem,
} from "./types.ts";

export class PlatformApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | "network_error";

  constructor(status: number, code: ErrorCode | "network_error", message: string) {
    super(message);
    this.name = "PlatformApiError";
    this.status = status;
    this.code = code;
  }
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class PlatformApiClient {
  private readonly baseUrl: string;
  private readonly fetchFn: FetchLike;

  constructor(baseUrl = "", fetchFn?: FetchLike) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.fetchFn = fetchFn ?? ((input, init) => fetch(input, init));
  }

  private async requestJson<T>(
    path: string,
    options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    let body: string | undefined;
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }

    let response: Response;
    try {
      response = await this.fetchFn(`${this.baseUrl}${path}`, {
        method: options.method ?? "GET",
        headers,
        body,
        signal: options.signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw err;
      }
      throw new PlatformApiError(0, "network_error", "Không kết nối được tới API cục bộ.");
    }

    if (!response.ok) {
      let parsed: Partial<ApiErrorBody> | null = null;
      try {
        parsed = (await response.json()) as Partial<ApiErrorBody>;
      } catch {
        parsed = null;
      }
      const code = (parsed?.code as ErrorCode | undefined) ?? "invalid_request";
      const message = parsed?.message ?? `HTTP ${response.status}`;
      throw new PlatformApiError(response.status, code, message);
    }

    return (await response.json()) as T;
  }

  async checkHealth(signal?: AbortSignal): Promise<{ status: string }> {
    return this.requestJson<{ status: string }>("/health", { signal });
  }

  async listProjects(signal?: AbortSignal): Promise<Project[]> {
    return this.requestJson<Project[]>("/projects", { signal });
  }

  async createProject(payload: CreateProjectRequest): Promise<Project> {
    return this.requestJson<Project>("/projects", { method: "POST", body: payload });
  }

  async listRuns(projectId: string, signal?: AbortSignal): Promise<RunTicket[]> {
    return this.requestJson<RunTicket[]>(`/projects/${encodeURIComponent(projectId)}/runs`, { signal });
  }

  async createRun(projectId: string, payload: CreateRunRequest): Promise<RunTicket> {
    return this.requestJson<RunTicket>(`/projects/${encodeURIComponent(projectId)}/runs`, {
      method: "POST",
      body: payload,
    });
  }

  async getRun(runId: string, signal?: AbortSignal): Promise<RunDetail> {
    return this.requestJson<RunDetail>(`/runs/${encodeURIComponent(runId)}`, { signal });
  }

  async getEvents(runId: string, after = 0, signal?: AbortSignal): Promise<EventsPage> {
    const cursor = Math.max(0, Math.floor(after));
    return this.requestJson<EventsPage>(
      `/runs/${encodeURIComponent(runId)}/events?after=${cursor}`,
      { signal },
    );
  }

  async listArtifacts(runId: string, kind?: string, signal?: AbortSignal): Promise<ArtifactItem[]> {
    const suffix = kind ? `?kind=${encodeURIComponent(kind)}` : "";
    return this.requestJson<ArtifactItem[]>(
      `/runs/${encodeURIComponent(runId)}/artifacts${suffix}`,
      { signal },
    );
  }

  async getArtifact(runId: string, artifactId: string, signal?: AbortSignal): Promise<ArtifactDetail> {
    return this.requestJson<ArtifactDetail>(
      `/artifacts/${encodeURIComponent(artifactId)}?run_id=${encodeURIComponent(runId)}`,
      { signal },
    );
  }

  async submitApproval(runId: string, payload: ApprovalRequest): Promise<DecisionReceipt> {
    return this.requestJson<DecisionReceipt>(`/runs/${encodeURIComponent(runId)}/approvals`, {
      method: "POST",
      body: payload,
    });
  }

  async submitClarifications(runId: string, payload: ClarificationRequest): Promise<DecisionReceipt> {
    return this.requestJson<DecisionReceipt>(`/runs/${encodeURIComponent(runId)}/clarifications`, {
      method: "POST",
      body: payload,
    });
  }

  async cancelRun(runId: string): Promise<RunTicket> {
    return this.requestJson<RunTicket>(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
  }

  async resumeRun(runId: string): Promise<RunTicket> {
    return this.requestJson<RunTicket>(`/runs/${encodeURIComponent(runId)}/resume`, { method: "POST" });
  }

  async getTasks(runId: string, signal?: AbortSignal): Promise<TaskItem[]> {
    return this.requestJson<TaskItem[]>(`/runs/${encodeURIComponent(runId)}/tasks`, { signal });
  }

  async getTestReports(runId: string, signal?: AbortSignal): Promise<TestReportItem[]> {
    return this.requestJson<TestReportItem[]>(`/runs/${encodeURIComponent(runId)}/test-reports`, { signal });
  }

  async submitAcceptance(runId: string, payload: FinalAcceptanceRequest): Promise<DecisionReceipt> {
    return this.requestJson<DecisionReceipt>(`/runs/${encodeURIComponent(runId)}/acceptance`, {
      method: "POST",
      body: payload,
    });
  }

  exportRunUrl(runId: string): string {
    return `${this.baseUrl}/runs/${encodeURIComponent(runId)}/export`;
  }
}
