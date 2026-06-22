import type {
  Breakdowns,
  CommandInfoAnalysis,
  IndexStatus,
  PresetTemplate,
  RawRecord,
  RecordInput,
  RecordItem,
  RecordsResponse,
  Summary,
  TemplateConfigResponse,
  TemplateTestInput,
  TemplateTestInputsResponse,
  TemplateTestRunResult,
  Trends,
  User
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Query = Record<string, string | number | undefined | null>;

function qs(params: Query = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value) !== "") {
      search.set(key, String(value));
    }
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "include"
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep response status text.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  me: () => request<User>("/api/auth/me"),
  login: (username: string, password: string) =>
    request<User>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  summary: (params: Query) => request<Summary>(`/api/dashboard/summary${qs(params)}`),
  trends: (params: Query) => request<Trends>(`/api/dashboard/trends${qs(params)}`),
  breakdowns: (params: Query) =>
    request<Breakdowns>(`/api/dashboard/breakdowns${qs(params)}`),
  commandInfoAnalysis: (params: Query) =>
    request<CommandInfoAnalysis>(`/api/command-info/analysis${qs(params)}`),
  records: (params: Query) => request<RecordsResponse>(`/api/records${qs(params)}`),
  record: (id: number) => request<RecordItem>(`/api/records/${id}`),
  raw: (id: number) => request<RawRecord>(`/api/records/${id}/raw`),
  recordInput: (id: number) => request<RecordInput>(`/api/records/${id}/input`),
  presetTemplates: () => request<TemplateConfigResponse>("/api/templates/preset-dic"),
  savePresetTemplates: (templates: PresetTemplate[]) =>
    request<TemplateConfigResponse>("/api/templates/preset-dic", {
      method: "PUT",
      body: JSON.stringify({ templates })
    }),
  savePresetYaml: (yamlText: string) =>
    request<TemplateConfigResponse>("/api/templates/preset-dic", {
      method: "PUT",
      body: JSON.stringify({ yaml_text: yamlText })
    }),
  testInputs: (params: Query = {}) =>
    request<TemplateTestInputsResponse>(`/api/template-test-inputs${qs(params)}`),
  createTestInput: (payload: {
    title: string;
    input_json: string;
    source_record_id?: number | null;
    source_filename?: string | null;
    doc_type?: string | null;
    doctor_name?: string | null;
    department?: string | null;
  }) =>
    request<TemplateTestInput>("/api/template-test-inputs", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateTestInput: (id: number, payload: { title?: string; input_json?: string }) =>
    request<TemplateTestInput>(`/api/template-test-inputs/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  deleteTestInput: (id: number) =>
    request<{ ok: boolean }>(`/api/template-test-inputs/${id}`, { method: "DELETE" }),
  runTestInput: (id: number) =>
    request<TemplateTestRunResult>(`/api/template-test-inputs/${id}/run`, { method: "POST" }),
  indexStatus: () => request<IndexStatus>("/api/index/status"),
  refreshIndex: () => request<{ status: string }>("/api/index/refresh", { method: "POST" })
};
