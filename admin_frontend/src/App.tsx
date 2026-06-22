import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import {
  Activity,
  BarChart3,
  ClipboardList,
  Copy,
  Clock,
  Database,
  Eye,
  FileJson,
  FileText,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  Lock,
  LogOut,
  MessageSquareText,
  Plus,
  RefreshCw,
  Save,
  Search,
  Shield,
  Stethoscope,
  TableProperties,
  Trash2,
  Users,
  X
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { ApiError, api } from "./api";
import type {
  BreakdownItem,
  Breakdowns,
  CommandInfoAnalysis,
  IndexStatus,
  PresetTemplate,
  RawRecord,
  RuntimeSchemaField,
  RecordItem,
  RecordsResponse,
  Summary,
  TemplateTestInput,
  TemplateTestRunResult,
  Trends,
  User
} from "./types";

type View = "dashboard" | "records" | "commands" | "templates" | "test-requests" | "index";

const SOFTWARE_TITLE = "全流程病历辅助书写系统";

type FilterState = {
  date_from: string;
  date_to: string;
  source: string;
  q: string;
};

type RecordFilterState = FilterState & {
  doctor_id: string;
  department: string;
  doc_type: string;
  status: string;
};

const chartColors = ["#227c70", "#4c6fff", "#c87919", "#8b5cf6", "#d14d72", "#64748b"];

const defaultFilters: FilterState = {
  date_from: "",
  date_to: "",
  source: "",
  q: ""
};

const defaultRecordFilters: RecordFilterState = {
  ...defaultFilters,
  doctor_id: "",
  department: "",
  doc_type: "",
  status: ""
};

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatSeconds(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (value >= 60) return `${(value / 60).toFixed(1)} 分`;
  return `${value.toFixed(1)} 秒`;
}

function shortDateTime(value: string | null | undefined) {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 19);
}

function listToLines(value: string[] | undefined) {
  return (value ?? []).join("\n");
}

function linesToList(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function blankRuntimeField(): RuntimeSchemaField {
  return {
    FieldName: "",
    Description: "",
    Position: "before",
    AnchorField: "",
    Required: true,
    Transient: true
  };
}

function blankTemplate(): PresetTemplate {
  return {
    DocType: "新文书类型",
    DicTemplate: [],
    TemplateAdvise: "",
    RuntimeSchemaFields: []
  };
}

function sampleInputJson() {
  return JSON.stringify(
    {
      DocType: "日常病程记录",
      CommandInfo: "",
      OperInfo: {},
      PatInfo: {}
    },
    null,
    2
  );
}

function hashViewName() {
  return window.location.hash.replace("#", "").split("?")[0];
}

function hashParam(name: string) {
  const query = window.location.hash.replace("#", "").split("?")[1] ?? "";
  return new URLSearchParams(query).get(name) ?? "";
}

function inputDocType(inputJson: string) {
  try {
    const value = JSON.parse(inputJson);
    return typeof value?.DocType === "string" ? value.DocType.trim() : "";
  } catch {
    return "";
  }
}

function templateMatchesDocType(template: PresetTemplate, docType: string) {
  const templateDocType = template.DocType.trim();
  const target = docType.trim();
  if (!templateDocType || !target) return false;
  if (templateDocType === target) return true;
  if (template.DocTypeMatch === "contains") return target.includes(templateDocType);
  return false;
}

function findTemplateIndexForDocType(templates: PresetTemplate[], docType: string) {
  const exact = templates.findIndex((template) => template.DocType.trim() === docType.trim());
  if (exact >= 0) return exact;

  const configured = templates.findIndex((template) => templateMatchesDocType(template, docType));
  if (configured >= 0) return configured;

  return templates.findIndex((template) => {
    const templateDocType = template.DocType.trim();
    const target = docType.trim();
    return Boolean(templateDocType && target && target.includes(templateDocType));
  });
}

function useHashView() {
  const getView = (): View => {
    const hash = hashViewName();
    if (
      hash === "records" ||
      hash === "commands" ||
      hash === "templates" ||
      hash === "test-requests" ||
      hash === "index"
    ) {
      return hash;
    }
    return "dashboard";
  };
  const [view, setViewState] = useState<View>(getView);
  useEffect(() => {
    const handler = () => setViewState(getView());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  const setView = (next: View) => {
    window.location.hash = next;
    setViewState(next);
  };
  return [view, setView] as const;
}

function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="error-banner" role="alert">
      {message}
    </div>
  );
}

function LoginPage({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const user = await api.login(username, password);
      onLogin(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <form className="login-panel" onSubmit={submit}>
        <div className="login-mark">
          <Shield size={26} aria-hidden />
        </div>
        <h1>{SOFTWARE_TITLE}</h1>
        <label>
          账号
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          密码
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
          />
        </label>
        {error ? <ErrorBanner message={error} /> : null}
        <button className="primary-button" disabled={loading}>
          <Lock size={17} aria-hidden />
          {loading ? "登录中" : "登录"}
        </button>
      </form>
    </main>
  );
}

function Layout({
  user,
  view,
  setView,
  onLogout,
  children
}: {
  user: User;
  view: View;
  setView: (view: View) => void;
  onLogout: () => void;
  children: ReactNode;
}) {
  const nav = [
    { id: "dashboard" as View, label: "总览", icon: LayoutDashboard },
    { id: "records" as View, label: "明细", icon: TableProperties },
    { id: "commands" as View, label: "指令分析", icon: MessageSquareText },
    { id: "templates" as View, label: "模板配置", icon: FileJson },
    { id: "test-requests" as View, label: "测试请求", icon: FlaskConical },
    { id: "index" as View, label: "索引", icon: Database }
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">
            <Stethoscope size={22} aria-hidden />
          </div>
          <div>
            <strong>{SOFTWARE_TITLE}</strong>
            <span>后台管理</span>
          </div>
        </div>
        <nav className="nav-list" aria-label="后台导航">
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={view === item.id ? "active" : ""}
                onClick={() => setView(item.id)}
              >
                <Icon size={18} aria-hidden />
                {item.label}
              </button>
            );
          })}
        </nav>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <span className="eyebrow">Admin</span>
            <h1>
              {view === "dashboard"
                ? `${SOFTWARE_TITLE}仪表台`
                : view === "records"
                  ? "Save 明细"
                  : view === "commands"
                    ? "CommandInfo 分析"
                    : view === "templates"
                      ? "模板配置"
                      : view === "test-requests"
                        ? "测试请求"
                        : "索引状态"}
            </h1>
          </div>
          <div className="user-actions">
            <span>{user.username}</span>
            <button className="icon-text-button" onClick={onLogout}>
              <LogOut size={17} aria-hidden />
              退出
            </button>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}

function FilterBar({
  filters,
  setFilters,
  onRefresh
}: {
  filters: FilterState;
  setFilters: (filters: FilterState) => void;
  onRefresh: () => void;
}) {
  return (
    <section className="toolbar">
      <label>
        开始日期
        <input
          type="date"
          value={filters.date_from}
          onChange={(event) => setFilters({ ...filters, date_from: event.target.value })}
        />
      </label>
      <label>
        结束日期
        <input
          type="date"
          value={filters.date_to}
          onChange={(event) => setFilters({ ...filters, date_to: event.target.value })}
        />
      </label>
      <label>
        来源
        <select
          value={filters.source}
          onChange={(event) => setFilters({ ...filters, source: event.target.value })}
        >
          <option value="">全部</option>
          <option value="query_save">query_save</option>
          <option value="archive">archive</option>
        </select>
      </label>
      <label className="search-field">
        搜索
        <span>
          <Search size={16} aria-hidden />
          <input
            value={filters.q}
            placeholder="医生、科室、文档类型、指令"
            onChange={(event) => setFilters({ ...filters, q: event.target.value })}
          />
        </span>
      </label>
      <button className="secondary-button" onClick={onRefresh}>
        <RefreshCw size={17} aria-hidden />
        刷新
      </button>
    </section>
  );
}

function KpiCard({
  label,
  value,
  hint,
  icon
}: {
  label: string;
  value: string;
  hint: string;
  icon: ReactNode;
}) {
  return (
    <section className="kpi-card">
      <div className="kpi-icon">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </section>
  );
}

function DashboardPage() {
  const [filters, setFilters] = useState<FilterState>(defaultFilters);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [trends, setTrends] = useState<Trends | null>(null);
  const [breakdowns, setBreakdowns] = useState<Breakdowns | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const filterKey = JSON.stringify(filters);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [nextSummary, nextTrends, nextBreakdowns] = await Promise.all([
        api.summary(filters),
        api.trends(filters),
        api.breakdowns(filters)
      ]);
      setSummary(nextSummary);
      setTrends(nextTrends);
      setBreakdowns(nextBreakdowns);
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取看板失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  const hourlyOverlay = useMemo(() => {
    const todayRows = trends?.hourly_today ?? [];
    const weekRows = trends?.hourly_7day_avg ?? [];
    return Array.from({ length: 24 }, (_, hour) => ({
      hour: `${String(hour).padStart(2, "0")}:00`,
      today: todayRows.find((item) => item.hour === hour)?.count ?? 0,
      weekAvg: weekRows.find((item) => item.hour === hour)?.count ?? 0
    }));
  }, [trends]);

  return (
    <main className="page">
      <FilterBar filters={filters} setFilters={setFilters} onRefresh={load} />
      {error ? <ErrorBanner message={error} /> : null}
      {summary ? (
        <div className="kpi-grid">
          <KpiCard
            label="今日 Save"
            value={formatNumber(summary.today_records)}
            hint={`7日 ${formatNumber(summary.last_7_days_records)} 条`}
            icon={<Activity size={20} aria-hidden />}
          />
          <KpiCard
            label="30日 Save"
            value={formatNumber(summary.last_30_days_records)}
            hint={`累计 ${formatNumber(summary.total_records)} 条`}
            icon={<FileText size={20} aria-hidden />}
          />
          <KpiCard
            label="活跃医生"
            value={formatNumber(summary.active_doctors)}
            hint={`${formatNumber(summary.doc_types)} 种文档类型`}
            icon={<Users size={20} aria-hidden />}
          />
          <KpiCard
            label="平均耗时"
            value={formatSeconds(summary.avg_elapsed_seconds)}
            hint={`P50 ${formatSeconds(summary.p50_elapsed_seconds)}`}
            icon={<Gauge size={20} aria-hidden />}
          />
          <KpiCard
            label="P95 耗时"
            value={formatSeconds(summary.p95_elapsed_seconds)}
            hint="生成耗时分位"
            icon={<Clock size={20} aria-hidden />}
          />
          <KpiCard
            label="解析错误"
            value={formatNumber(summary.parse_errors)}
            hint={`已解析 ${formatNumber(summary.parsed_records)} 条`}
            icon={<Database size={20} aria-hidden />}
          />
        </div>
      ) : loading ? (
        <EmptyState>正在载入看板数据</EmptyState>
      ) : null}

      <div className="analytics-grid">
        <section className="panel">
          <div className="panel-title">
            <h2>按日 Save 趋势</h2>
            <span>{summary ? `${summary.first_record_date ?? "-"} 至 ${summary.last_record_date ?? "-"}` : "-"}</span>
          </div>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trends?.daily ?? []}>
                <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
                <XAxis dataKey="date" minTickGap={24} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="count" stroke="#227c70" strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">
            <h2>24 小时分布</h2>
            <span>今日 / 近7日均</span>
          </div>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={hourlyOverlay}>
                <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
                <XAxis dataKey="hour" interval={3} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="today"
                  name="今日"
                  stroke="#d14d72"
                  strokeWidth={2.5}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="weekAvg"
                  name="近7日均"
                  stroke="#4c6fff"
                  strokeWidth={2.5}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">
            <h2>来源分布</h2>
            <span>query_save / archive</span>
          </div>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={breakdowns?.sources ?? []} dataKey="count" nameKey="source" innerRadius={58} outerRadius={86}>
                  {(breakdowns?.sources ?? []).map((_, index) => (
                    <Cell key={index} fill={chartColors[index % chartColors.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </section>

        <RankingPanel title="医生排行" rows={breakdowns?.doctors ?? []} labelKey="doctor_name" />
        <RankingPanel title="科室分布" rows={breakdowns?.departments ?? []} labelKey="department" />
        <RankingPanel title="文档类型" rows={breakdowns?.doc_types ?? []} labelKey="doc_type" />
      </div>
    </main>
  );
}

function RankingPanel({
  title,
  rows,
  labelKey
}: {
  title: string;
  rows: BreakdownItem[];
  labelKey: "doctor_name" | "department" | "doc_type";
}) {
  const max = Math.max(...rows.map((row) => row.count), 1);
  return (
    <section className="panel">
      <div className="panel-title">
        <h2>{title}</h2>
        <span>Top {Math.min(rows.length, 20)}</span>
      </div>
      <div className="rank-list">
        {rows.length ? (
          rows.slice(0, 10).map((row, index) => {
            const label = String(row[labelKey] || "未知");
            return (
              <div className="rank-row" key={`${label}-${index}`}>
                <div>
                  <strong>{label}</strong>
                  <span>{formatNumber(row.count)} 条</span>
                </div>
                <div className="rank-bar">
                  <span style={{ width: `${(row.count / max) * 100}%` }} />
                </div>
              </div>
            );
          })
        ) : (
          <EmptyState>暂无数据</EmptyState>
        )}
      </div>
    </section>
  );
}

function RecordsPage() {
  const [filters, setFilters] = useState<RecordFilterState>(defaultRecordFilters);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [data, setData] = useState<RecordsResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const filterKey = JSON.stringify(filters);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await api.records({ ...filters, page, page_size: pageSize }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取明细失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, page, pageSize]);

  function updateFilters(next: Partial<RecordFilterState>) {
    setPage(1);
    setFilters({ ...filters, ...next });
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <main className="page">
      <section className="toolbar records-toolbar">
        <label>
          开始日期
          <input type="date" value={filters.date_from} onChange={(event) => updateFilters({ date_from: event.target.value })} />
        </label>
        <label>
          结束日期
          <input type="date" value={filters.date_to} onChange={(event) => updateFilters({ date_to: event.target.value })} />
        </label>
        <label>
          来源
          <select value={filters.source} onChange={(event) => updateFilters({ source: event.target.value })}>
            <option value="">全部</option>
            <option value="query_save">query_save</option>
            <option value="archive">archive</option>
          </select>
        </label>
        <label>
          状态
          <select value={filters.status} onChange={(event) => updateFilters({ status: event.target.value })}>
            <option value="">全部</option>
            <option value="ok">ok</option>
            <option value="error">error</option>
          </select>
        </label>
        <label>
          医生ID
          <input value={filters.doctor_id} onChange={(event) => updateFilters({ doctor_id: event.target.value })} />
        </label>
        <label>
          科室
          <input value={filters.department} onChange={(event) => updateFilters({ department: event.target.value })} />
        </label>
        <label>
          文档类型
          <input value={filters.doc_type} onChange={(event) => updateFilters({ doc_type: event.target.value })} />
        </label>
        <label className="search-field">
          搜索
          <span>
            <Search size={16} aria-hidden />
            <input value={filters.q} onChange={(event) => updateFilters({ q: event.target.value })} />
          </span>
        </label>
        <button className="secondary-button" onClick={load}>
          <RefreshCw size={17} aria-hidden />
          刷新
        </button>
      </section>
      {error ? <ErrorBanner message={error} /> : null}
      <section className="panel table-panel">
        <div className="panel-title">
          <h2>Save 文件明细</h2>
          <span>{data ? `${formatNumber(data.total)} 条` : loading ? "载入中" : "-"}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>医生</th>
                <th>科室</th>
                <th>文档类型</th>
                <th>来源</th>
                <th>耗时</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((item) => (
                <tr key={item.id}>
                  <td>{shortDateTime(item.record_time)}</td>
                  <td>
                    <strong>{item.doctor_name || item.doctor_id || "未知"}</strong>
                    <span className="subtext">{item.doctor_id}</span>
                  </td>
                  <td>{item.department || "-"}</td>
                  <td>{item.doc_type || "-"}</td>
                  <td><span className="source-pill">{item.source}</span></td>
                  <td>{formatSeconds(item.elapsed_seconds)}</td>
                  <td><StatusPill status={item.parse_status} /></td>
                  <td>
                    <button className="icon-button" onClick={() => setSelectedId(item.id)} aria-label="查看">
                      <Eye size={17} aria-hidden />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && !data?.items.length ? <EmptyState>暂无匹配记录</EmptyState> : null}
        </div>
        <div className="pagination">
          <button className="secondary-button" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            上一页
          </button>
          <span>
            {page} / {pages}
          </span>
          <button className="secondary-button" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            下一页
          </button>
        </div>
      </section>
      <RecordDrawer id={selectedId} onClose={() => setSelectedId(null)} />
    </main>
  );
}

function CommandInfoPage() {
  const [filters, setFilters] = useState<FilterState>(defaultFilters);
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [data, setData] = useState<CommandInfoAnalysis | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const filterKey = JSON.stringify(filters);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await api.commandInfoAnalysis({ ...filters, page, page_size: pageSize }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取 CommandInfo 分析失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, page]);

  function updateCommandFilters(next: FilterState) {
    setPage(1);
    setFilters(next);
  }

  const summary = data?.summary;
  const coverage = summary ? `${(summary.command_coverage * 100).toFixed(1)}%` : "-";
  const recentPages = data
    ? Math.max(1, Math.ceil(data.recent_total / data.recent_page_size))
    : 1;

  return (
    <main className="page">
      <FilterBar filters={filters} setFilters={updateCommandFilters} onRefresh={load} />
      {error ? <ErrorBanner message={error} /> : null}
      {summary ? (
        <div className="kpi-grid command-kpis">
          <KpiCard
            label="有指令记录"
            value={formatNumber(summary.command_records)}
            hint={`覆盖率 ${coverage}`}
            icon={<MessageSquareText size={20} aria-hidden />}
          />
          <KpiCard
            label="今日指令"
            value={formatNumber(summary.today_command_records)}
            hint={`7日 ${formatNumber(summary.last_7_days_command_records)} 条`}
            icon={<Activity size={20} aria-hidden />}
          />
          <KpiCard
            label="平均长度"
            value={summary.avg_command_length ? `${summary.avg_command_length.toFixed(0)} 字` : "-"}
            hint="CommandInfo 字符数"
            icon={<Gauge size={20} aria-hidden />}
          />
          <KpiCard
            label="最近指令"
            value={shortDateTime(summary.latest_command_time).slice(5) || "-"}
            hint="按文件时间"
            icon={<Clock size={20} aria-hidden />}
          />
        </div>
      ) : loading ? (
        <EmptyState>正在载入 CommandInfo 分析</EmptyState>
      ) : null}

      <div className="analytics-grid">
        <section className="panel command-recent-panel">
          <div className="panel-title">
            <h2>最近 CommandInfo</h2>
            <span>{data ? `${formatNumber(data.recent_total)} 条` : "-"}</span>
          </div>
          <div className="command-list">
            {data?.recent.length ? (
              data.recent.map((item) => (
                <article
                  className="command-card command-card-clickable"
                  key={item.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedId(item.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedId(item.id);
                    }
                  }}
                >
                  <p>{item.command_info}</p>
                </article>
              ))
            ) : (
              <EmptyState>暂无 CommandInfo 记录</EmptyState>
            )}
          </div>
          <div className="pagination">
            <button className="secondary-button" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              上一页
            </button>
            <span>
              {page} / {recentPages}
            </span>
            <button className="secondary-button" disabled={page >= recentPages} onClick={() => setPage(page + 1)}>
              下一页
            </button>
          </div>
        </section>
      </div>
      <RecordDrawer id={selectedId} onClose={() => setSelectedId(null)} />
    </main>
  );
}

function TemplatesPage() {
  const [templates, setTemplates] = useState<PresetTemplate[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [yamlText, setYamlText] = useState("");
  const [mode, setMode] = useState<"form" | "yaml">("form");
  const [path, setPath] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const selected = templates[selectedIndex] ?? null;

  async function load() {
    setLoading(true);
    setError("");
    try {
      const data = await api.presetTemplates();
      const targetDocType = hashParam("doc_type");
      const targetIndex = targetDocType ? findTemplateIndexForDocType(data.templates, targetDocType) : -1;
      setTemplates(data.templates);
      setYamlText(data.yaml_text);
      setPath(data.path);
      setSelectedIndex(targetIndex >= 0 ? targetIndex : 0);
      setDirty(false);
      if (targetDocType && targetIndex >= 0) {
        setMessage(`已定位到模板：${data.templates[targetIndex].DocType}`);
      } else if (targetDocType) {
        setMessage(`未找到与「${targetDocType}」匹配的模板，可手动选择或新增`);
      } else {
        setMessage("");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取模板失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function updateSelected(patch: Partial<PresetTemplate>) {
    setTemplates((current) =>
      current.map((item, index) => (index === selectedIndex ? { ...item, ...patch } : item))
    );
    setDirty(true);
    setMessage("");
  }

  function addTemplate() {
    setTemplates((current) => {
      const next = [...current, blankTemplate()];
      setSelectedIndex(next.length - 1);
      return next;
    });
    setDirty(true);
    setMessage("");
  }

  function removeTemplate() {
    if (!selected) return;
    if (!window.confirm(`删除模板「${selected.DocType}」？`)) return;
    setTemplates((current) => current.filter((_, index) => index !== selectedIndex));
    setSelectedIndex(Math.max(0, selectedIndex - 1));
    setDirty(true);
    setMessage("");
  }

  function updateRuntimeField(index: number, patch: Partial<RuntimeSchemaField>) {
    if (!selected) return;
    const fields = [...(selected.RuntimeSchemaFields ?? [])];
    fields[index] = { ...fields[index], ...patch };
    updateSelected({ RuntimeSchemaFields: fields });
  }

  function addRuntimeField() {
    if (!selected) return;
    updateSelected({ RuntimeSchemaFields: [...(selected.RuntimeSchemaFields ?? []), blankRuntimeField()] });
  }

  function removeRuntimeField(index: number) {
    if (!selected) return;
    updateSelected({
      RuntimeSchemaFields: (selected.RuntimeSchemaFields ?? []).filter((_, itemIndex) => itemIndex !== index)
    });
  }

  async function saveForm() {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const data = await api.savePresetTemplates(templates);
      setTemplates(data.templates);
      setYamlText(data.yaml_text);
      setPath(data.path);
      setDirty(false);
      setMessage("模板已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存模板失败");
    } finally {
      setSaving(false);
    }
  }

  async function saveYaml() {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const data = await api.savePresetYaml(yamlText);
      setTemplates(data.templates);
      setYamlText(data.yaml_text);
      setPath(data.path);
      setSelectedIndex(0);
      setDirty(false);
      setMessage("YAML 已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 YAML 失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="page">
      {error ? <ErrorBanner message={error} /> : null}
      {message ? <div className="success-banner">{message}</div> : null}
      <div className="template-toolbar">
        <div className="segmented-control" role="tablist" aria-label="模板编辑模式">
          <button className={mode === "form" ? "active" : ""} onClick={() => setMode("form")}>
            表单
          </button>
          <button className={mode === "yaml" ? "active" : ""} onClick={() => setMode("yaml")}>
            YAML
          </button>
        </div>
        <div className="toolbar-actions">
          <span className={dirty ? "dirty-pill" : "source-pill"}>{dirty ? "未保存" : "已同步"}</span>
          <button className="secondary-button" onClick={load} disabled={loading || saving}>
            <RefreshCw size={17} aria-hidden />
            重新读取
          </button>
          <button className="primary-button" onClick={mode === "form" ? saveForm : saveYaml} disabled={saving}>
            <Save size={17} aria-hidden />
            {saving ? "保存中" : "保存"}
          </button>
        </div>
      </div>

      {mode === "form" ? (
        <div className="split-page template-split">
          <section className="panel side-panel">
            <div className="panel-title">
              <h2>文书类型</h2>
              <button className="icon-button" onClick={addTemplate} aria-label="新增模板">
                <Plus size={17} aria-hidden />
              </button>
            </div>
            <div className="template-list">
              {templates.map((item, index) => (
                <button
                  key={`${item.DocType}-${index}`}
                  className={index === selectedIndex ? "active" : ""}
                  onClick={() => setSelectedIndex(index)}
                >
                  <strong>{item.DocType || "未命名"}</strong>
                  <span>{formatNumber(item.DicTemplate?.length ?? 0)} 个字段</span>
                </button>
              ))}
            </div>
            {!templates.length && !loading ? <EmptyState>暂无模板</EmptyState> : null}
          </section>

          <section className="panel editor-panel">
            {selected ? (
              <>
                <div className="panel-title">
                  <h2>{selected.DocType || "模板详情"}</h2>
                  <button className="secondary-button danger-action" onClick={removeTemplate}>
                    <Trash2 size={17} aria-hidden />
                    删除
                  </button>
                </div>
                <div className="form-grid">
                  <label>
                    文书类型
                    <input
                      value={selected.DocType}
                      onChange={(event) => updateSelected({ DocType: event.target.value })}
                    />
                  </label>
                  <label>
                    匹配方式
                    <select
                      value={selected.DocTypeMatch ?? ""}
                      onChange={(event) =>
                        updateSelected({ DocTypeMatch: event.target.value || undefined })
                      }
                    >
                      <option value="">精确匹配</option>
                      <option value="contains">包含匹配</option>
                      <option value="exact">精确匹配 exact</option>
                    </select>
                  </label>
                  <label>
                    日期范围
                    <input
                      type="number"
                      min={0}
                      value={selected.DayLimit ?? ""}
                      onChange={(event) =>
                        updateSelected({
                          DayLimit: event.target.value ? Number(event.target.value) : null
                        })
                      }
                    />
                  </label>
                </div>
                <label>
                  生成字段
                  <textarea
                    className="line-textarea"
                    value={listToLines(selected.DicTemplate)}
                    onChange={(event) => updateSelected({ DicTemplate: linesToList(event.target.value) })}
                  />
                </label>
                <label>
                  模板建议
                  <textarea
                    className="advise-textarea"
                    value={selected.TemplateAdvise ?? ""}
                    onChange={(event) => updateSelected({ TemplateAdvise: event.target.value })}
                  />
                </label>
                <label>
                  排除字段
                  <textarea
                    className="compact-textarea"
                    value={listToLines(selected.Exclude)}
                    onChange={(event) => updateSelected({ Exclude: linesToList(event.target.value) })}
                  />
                </label>
                <section className="runtime-section">
                  <div className="panel-title">
                    <h2>运行时思考字段</h2>
                    <button className="secondary-button" onClick={addRuntimeField}>
                      <Plus size={17} aria-hidden />
                      新增字段
                    </button>
                  </div>
                  <div className="runtime-list">
                    {(selected.RuntimeSchemaFields ?? []).map((field, index) => (
                      <article className="runtime-card" key={index}>
                        <div className="runtime-card-header">
                          <strong>{field.FieldName || "未命名字段"}</strong>
                          <button className="icon-button" onClick={() => removeRuntimeField(index)} aria-label="删除字段">
                            <Trash2 size={16} aria-hidden />
                          </button>
                        </div>
                        <div className="form-grid">
                          <label>
                            字段名
                            <input
                              value={field.FieldName ?? ""}
                              onChange={(event) => updateRuntimeField(index, { FieldName: event.target.value })}
                            />
                          </label>
                          <label>
                            位置
                            <select
                              value={field.Position ?? "before"}
                              onChange={(event) => updateRuntimeField(index, { Position: event.target.value })}
                            >
                              <option value="before">before</option>
                              <option value="after">after</option>
                            </select>
                          </label>
                          <label>
                            锚点字段
                            <input
                              value={field.AnchorField ?? ""}
                              onChange={(event) => updateRuntimeField(index, { AnchorField: event.target.value })}
                            />
                          </label>
                        </div>
                        <label>
                          字段说明
                          <textarea
                            className="compact-textarea"
                            value={field.Description ?? ""}
                            onChange={(event) => updateRuntimeField(index, { Description: event.target.value })}
                          />
                        </label>
                        <div className="checkbox-row">
                          <label>
                            <input
                              type="checkbox"
                              checked={field.Required ?? true}
                              onChange={(event) => updateRuntimeField(index, { Required: event.target.checked })}
                            />
                            必填
                          </label>
                          <label>
                            <input
                              type="checkbox"
                              checked={field.Transient ?? true}
                              onChange={(event) => updateRuntimeField(index, { Transient: event.target.checked })}
                            />
                            仅思考
                          </label>
                        </div>
                      </article>
                    ))}
                    {!selected.RuntimeSchemaFields?.length ? <EmptyState>暂无运行时字段</EmptyState> : null}
                  </div>
                </section>
              </>
            ) : loading ? (
              <EmptyState>正在读取模板</EmptyState>
            ) : (
              <EmptyState>请选择模板</EmptyState>
            )}
          </section>
        </div>
      ) : (
        <section className="panel yaml-panel">
          <div className="panel-title">
            <h2>高级 YAML</h2>
            <span>{path || "-"}</span>
          </div>
          <textarea
            className="yaml-editor"
            value={yamlText}
            spellCheck={false}
            onChange={(event) => {
              setYamlText(event.target.value);
              setDirty(true);
              setMessage("");
            }}
          />
        </section>
      )}
    </main>
  );
}

function TestRequestsPage() {
  const [items, setItems] = useState<TemplateTestInput[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftInput, setDraftInput] = useState("");
  const [searchText, setSearchText] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TemplateTestRunResult | null>(null);
  const [templateDialogDocType, setTemplateDialogDocType] = useState("");

  const selected = items.find((item) => item.id === selectedId) ?? null;
  const currentDocType = selected?.doc_type || inputDocType(draftInput);

  function selectItem(item: TemplateTestInput | null) {
    setSelectedId(item?.id ?? null);
    setDraftTitle(item?.title ?? "");
    setDraftInput(item?.input_json ?? "");
    setResult(null);
    setMessage("");
  }

  async function load(nextSelectedId: number | null = selectedId) {
    setLoading(true);
    setError("");
    try {
      const data = await api.testInputs({ q: searchText });
      setItems(data.items);
      const next = data.items.find((item) => item.id === nextSelectedId) ?? data.items[0] ?? null;
      selectItem(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取测试 input 失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchText]);

  async function createInput() {
    setSaving(true);
    setError("");
    try {
      const created = await api.createTestInput({
        title: "新测试 input",
        input_json: sampleInputJson()
      });
      setItems((current) => [created, ...current]);
      selectItem(created);
      setMessage("测试 input 已新增");
    } catch (err) {
      setError(err instanceof Error ? err.message : "新增失败");
    } finally {
      setSaving(false);
    }
  }

  async function saveDraft() {
    if (!selectedId) return null;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.updateTestInput(selectedId, {
        title: draftTitle,
        input_json: draftInput
      });
      setItems((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      selectItem(updated);
      setMessage("测试 input 已保存");
      return updated;
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function deleteInput() {
    if (!selected) return;
    if (!window.confirm(`删除测试 input「${selected.title}」？`)) return;
    setSaving(true);
    setError("");
    try {
      await api.deleteTestInput(selected.id);
      const nextItems = items.filter((item) => item.id !== selected.id);
      setItems(nextItems);
      selectItem(nextItems[0] ?? null);
      setMessage("测试 input 已删除");
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    if (!selectedId) return;
    setRunning(true);
    setError("");
    setMessage("");
    setResult(null);
    try {
      const updated = await api.updateTestInput(selectedId, {
        title: draftTitle,
        input_json: draftInput
      });
      setItems((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      const output = await api.runTestInput(updated.id);
      const data = await api.testInputs({ q: searchText });
      const refreshed = data.items.find((item) => item.id === updated.id) ?? updated;
      setItems(data.items);
      setSelectedId(refreshed.id);
      setDraftTitle(refreshed.title);
      setDraftInput(refreshed.input_json);
      setResult(output);
    } catch (err) {
      setError(err instanceof Error ? err.message : "测试失败");
    } finally {
      setRunning(false);
    }
  }

  function openPresetTemplate() {
    if (!currentDocType) {
      setError("当前 input 缺少 DocType，无法定位模板");
      return;
    }
    setTemplateDialogDocType(currentDocType);
  }

  return (
    <main className="page">
      {error ? <ErrorBanner message={error} /> : null}
      {message ? <div className="success-banner">{message}</div> : null}
      <div className="split-page test-split">
        <section className="panel side-panel">
          <div className="panel-title">
            <h2>测试 input</h2>
            <button className="icon-button" onClick={createInput} disabled={saving} aria-label="新增测试 input">
              <Plus size={17} aria-hidden />
            </button>
          </div>
          <label className="search-field side-search">
            搜索
            <span>
              <Search size={16} aria-hidden />
              <input value={searchText} onChange={(event) => setSearchText(event.target.value)} />
            </span>
          </label>
          <div className="test-input-list">
            {items.map((item) => (
              <button
                key={item.id}
                className={item.id === selectedId ? "active" : ""}
                onClick={() => selectItem(item)}
              >
                <strong>{item.title}</strong>
                <span>{item.doc_type || item.source_filename || "未标注文书"}</span>
                <small>{item.last_run_at ? `上次 ${shortDateTime(item.last_run_at)}` : shortDateTime(item.updated_at)}</small>
              </button>
            ))}
          </div>
          {!items.length && !loading ? <EmptyState>暂无测试 input</EmptyState> : null}
        </section>

        <section className="test-workspace">
          <section className="panel input-editor-panel">
            <div className="panel-title">
              <h2>Input 内容</h2>
              <div className="toolbar-actions">
                <button className="secondary-button danger-action" onClick={deleteInput} disabled={!selected || saving}>
                  <Trash2 size={17} aria-hidden />
                  删除
                </button>
                <button className="secondary-button" onClick={saveDraft} disabled={!selected || saving}>
                  <Save size={17} aria-hidden />
                  保存
                </button>
              </div>
            </div>
            {selected ? (
              <>
                <div className="form-grid">
                  <label>
                    名称
                    <input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} />
                  </label>
                  <Detail label="来源" value={selected.source_filename || "-"} />
                  <Detail label="文书类型" value={selected.doc_type || "-"} />
                </div>
                <textarea
                  className="json-editor"
                  value={draftInput}
                  spellCheck={false}
                  onChange={(event) => setDraftInput(event.target.value)}
                />
              </>
            ) : loading ? (
              <EmptyState>正在读取测试 input</EmptyState>
            ) : (
              <EmptyState>请新增或选择一个测试 input</EmptyState>
            )}
          </section>

          <section className="panel result-panel">
            <div className="panel-title">
              <h2>测试结果</h2>
              <div className="toolbar-actions">
                {result?.ok ? (
                  <button className="secondary-button" onClick={openPresetTemplate} disabled={!currentDocType}>
                    <FileJson size={17} aria-hidden />
                    编辑对应模板
                  </button>
                ) : null}
                <button className="primary-button" onClick={runTest} disabled={!selected || running}>
                  <FlaskConical size={17} aria-hidden />
                  {running ? "测试中" : "运行测试"}
                </button>
              </div>
            </div>
            {running ? (
              <div className="test-loading" role="status" aria-live="polite">
                <div className="loading-spinner" aria-hidden />
                <strong>正在运行全流程病历辅助书写系统测试</strong>
                <span>已保存当前 input，正在调用本地模型服务生成结果</span>
                <div className="indeterminate-progress" aria-hidden>
                  <span />
                </div>
              </div>
            ) : result ? (
              <div className="test-result">
                <div className="result-meta">
                  <Detail label="状态" value={result.ok ? "ok" : "error"} />
                  <Detail label="耗时" value={formatSeconds(result.elapsed_seconds)} />
                  <Detail label="请求地址" value={result.request_url} />
                </div>
                {result.error ? <ErrorBanner message={result.error} /> : null}
                {result.parse_error ? <ErrorBanner message={result.parse_error} /> : null}
                {result.parsed_items.length ? (
                  <div className="table-wrap compact-table">
                    <table>
                      <thead>
                        <tr>
                          <th>字段</th>
                          <th>结果</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.parsed_items.map((item, index) => (
                          <tr key={`${item.key}-${index}`}>
                            <td>{item.key}</td>
                            <td>{String(item.value ?? "")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                <pre className="raw-text result-raw">{result.raw_content || "无原始输出"}</pre>
              </div>
            ) : (
              <EmptyState>暂无测试结果</EmptyState>
            )}
          </section>
        </section>
      </div>
      {templateDialogDocType ? (
        <PresetTemplateDialog
          docType={templateDialogDocType}
          onClose={() => setTemplateDialogDocType("")}
          onSaved={(docType) => {
            setTemplateDialogDocType("");
            setMessage(`模板「${docType}」已保存`);
          }}
        />
      ) : null}
    </main>
  );
}

function PresetTemplateDialog({
  docType,
  onClose,
  onSaved
}: {
  docType: string;
  onClose: () => void;
  onSaved: (docType: string) => void;
}) {
  const [templates, setTemplates] = useState<PresetTemplate[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const selected = selectedIndex >= 0 ? templates[selectedIndex] : null;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .presetTemplates()
      .then((data) => {
        if (cancelled) return;
        const targetIndex = findTemplateIndexForDocType(data.templates, docType);
        setTemplates(data.templates);
        setSelectedIndex(targetIndex);
        if (targetIndex < 0) {
          setError(`未找到与「${docType}」匹配的 preset 模板`);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "读取模板失败");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docType]);

  function requestClose() {
    if (dirty && !window.confirm("模板尚未保存，确定关闭？")) return;
    onClose();
  }

  function updateSelected(patch: Partial<PresetTemplate>) {
    setTemplates((current) =>
      current.map((item, index) => (index === selectedIndex ? { ...item, ...patch } : item))
    );
    setDirty(true);
  }

  function updateRuntimeField(index: number, patch: Partial<RuntimeSchemaField>) {
    if (!selected) return;
    const fields = [...(selected.RuntimeSchemaFields ?? [])];
    fields[index] = { ...fields[index], ...patch };
    updateSelected({ RuntimeSchemaFields: fields });
  }

  function addRuntimeField() {
    if (!selected) return;
    updateSelected({ RuntimeSchemaFields: [...(selected.RuntimeSchemaFields ?? []), blankRuntimeField()] });
  }

  function removeRuntimeField(index: number) {
    if (!selected) return;
    updateSelected({
      RuntimeSchemaFields: (selected.RuntimeSchemaFields ?? []).filter((_, itemIndex) => itemIndex !== index)
    });
  }

  async function saveTemplate() {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      const data = await api.savePresetTemplates(templates);
      const savedIndex = findTemplateIndexForDocType(data.templates, selected.DocType);
      onSaved(data.templates[savedIndex]?.DocType || selected.DocType);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存模板失败");
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={requestClose}>
      <section
        className="preset-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="preset-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="eyebrow">Preset Template</span>
            <h2 id="preset-modal-title">{selected?.DocType || docType}</h2>
            <p>来自测试 input：{docType}</p>
          </div>
          <button className="icon-button" onClick={requestClose} aria-label="关闭">
            <X size={18} aria-hidden />
          </button>
        </div>

        {error ? <ErrorBanner message={error} /> : null}
        {loading ? <EmptyState>正在读取模板</EmptyState> : null}

        {selected ? (
          <div className="modal-body">
            <div className="form-grid">
              <label>
                文书类型
                <input
                  value={selected.DocType}
                  onChange={(event) => updateSelected({ DocType: event.target.value })}
                />
              </label>
              <label>
                匹配方式
                <select
                  value={selected.DocTypeMatch ?? ""}
                  onChange={(event) =>
                    updateSelected({ DocTypeMatch: event.target.value || undefined })
                  }
                >
                  <option value="">精确匹配</option>
                  <option value="contains">包含匹配</option>
                  <option value="exact">精确匹配 exact</option>
                </select>
              </label>
              <label>
                日期范围
                <input
                  type="number"
                  min={0}
                  value={selected.DayLimit ?? ""}
                  onChange={(event) =>
                    updateSelected({
                      DayLimit: event.target.value ? Number(event.target.value) : null
                    })
                  }
                />
              </label>
            </div>
            <label>
              生成字段
              <textarea
                className="line-textarea modal-line-textarea"
                value={listToLines(selected.DicTemplate)}
                onChange={(event) => updateSelected({ DicTemplate: linesToList(event.target.value) })}
              />
            </label>
            <label>
              模板建议
              <textarea
                className="advise-textarea modal-advise-textarea"
                value={selected.TemplateAdvise ?? ""}
                onChange={(event) => updateSelected({ TemplateAdvise: event.target.value })}
              />
            </label>
            <label>
              排除字段
              <textarea
                className="compact-textarea"
                value={listToLines(selected.Exclude)}
                onChange={(event) => updateSelected({ Exclude: linesToList(event.target.value) })}
              />
            </label>
            <section className="runtime-section">
              <div className="panel-title">
                <h2>运行时思考字段</h2>
                <button className="secondary-button" onClick={addRuntimeField}>
                  <Plus size={17} aria-hidden />
                  新增字段
                </button>
              </div>
              <div className="runtime-list">
                {(selected.RuntimeSchemaFields ?? []).map((field, index) => (
                  <article className="runtime-card" key={index}>
                    <div className="runtime-card-header">
                      <strong>{field.FieldName || "未命名字段"}</strong>
                      <button className="icon-button" onClick={() => removeRuntimeField(index)} aria-label="删除字段">
                        <Trash2 size={16} aria-hidden />
                      </button>
                    </div>
                    <div className="form-grid">
                      <label>
                        字段名
                        <input
                          value={field.FieldName ?? ""}
                          onChange={(event) => updateRuntimeField(index, { FieldName: event.target.value })}
                        />
                      </label>
                      <label>
                        位置
                        <select
                          value={field.Position ?? "before"}
                          onChange={(event) => updateRuntimeField(index, { Position: event.target.value })}
                        >
                          <option value="before">before</option>
                          <option value="after">after</option>
                        </select>
                      </label>
                      <label>
                        锚点字段
                        <input
                          value={field.AnchorField ?? ""}
                          onChange={(event) => updateRuntimeField(index, { AnchorField: event.target.value })}
                        />
                      </label>
                    </div>
                    <label>
                      字段说明
                      <textarea
                        className="compact-textarea"
                        value={field.Description ?? ""}
                        onChange={(event) => updateRuntimeField(index, { Description: event.target.value })}
                      />
                    </label>
                    <div className="checkbox-row">
                      <label>
                        <input
                          type="checkbox"
                          checked={field.Required ?? true}
                          onChange={(event) => updateRuntimeField(index, { Required: event.target.checked })}
                        />
                        必填
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={field.Transient ?? true}
                          onChange={(event) => updateRuntimeField(index, { Transient: event.target.checked })}
                        />
                        仅思考
                      </label>
                    </div>
                  </article>
                ))}
                {!selected.RuntimeSchemaFields?.length ? <EmptyState>暂无运行时字段</EmptyState> : null}
              </div>
            </section>
          </div>
        ) : null}

        <div className="modal-footer">
          <span className={dirty ? "dirty-pill" : "source-pill"}>{dirty ? "未保存" : "已同步"}</span>
          <button className="secondary-button" onClick={requestClose}>
            取消
          </button>
          <button className="primary-button" onClick={saveTemplate} disabled={!selected || saving}>
            <Save size={17} aria-hidden />
            {saving ? "保存中" : "保存并关闭"}
          </button>
        </div>
      </section>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return <span className={status === "ok" ? "status ok" : "status error"}>{status}</span>;
}

function RecordDrawer({
  id,
  onClose
}: {
  id: number | null;
  onClose: () => void;
}) {
  const [record, setRecord] = useState<RecordItem | null>(null);
  const [raw, setRaw] = useState<RawRecord | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loadingRaw, setLoadingRaw] = useState(false);
  const [inputBusy, setInputBusy] = useState(false);

  useEffect(() => {
    setRaw(null);
    setRecord(null);
    setError("");
    setMessage("");
    if (!id) return;
    api.record(id).then(setRecord).catch((err) => setError(err instanceof Error ? err.message : "读取记录失败"));
    setLoadingRaw(true);
    api
      .raw(id)
      .then(setRaw)
      .catch((err) => setError(err instanceof Error ? err.message : "读取原始 txt 失败"))
      .finally(() => setLoadingRaw(false));
  }, [id]);

  async function copyInputJson() {
    if (!id) return;
    setInputBusy(true);
    setError("");
    setMessage("");
    try {
      const input = await api.recordInput(id);
      await navigator.clipboard.writeText(input.input_json);
      setMessage("input JSON 已复制");
    } catch (err) {
      setError(err instanceof Error ? err.message : "复制 input JSON 失败");
    } finally {
      setInputBusy(false);
    }
  }

  async function saveAsTestInput() {
    if (!id) return;
    setInputBusy(true);
    setError("");
    setMessage("");
    try {
      const input = await api.recordInput(id);
      const created = await api.createTestInput({
        title: `${input.doc_type || record?.doc_type || "测试 input"} · ${record?.filename || input.filename}`,
        input_json: input.input_json,
        source_record_id: id,
        source_filename: input.filename,
        doc_type: input.doc_type,
        doctor_name: input.doctor_name,
        department: input.department
      });
      setMessage(`已保存为测试 input：${created.title}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存测试 input 失败");
    } finally {
      setInputBusy(false);
    }
  }

  if (!id) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <h2>{record?.filename || "记录详情"}</h2>
            <span>{record ? `${record.source} · ${shortDateTime(record.record_time)}` : "载入中"}</span>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭">
            <X size={18} aria-hidden />
          </button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {message ? <div className="success-banner">{message}</div> : null}
        {record ? (
          <div className="detail-grid">
            <Detail label="医生" value={record.doctor_name || record.doctor_id || "-"} />
            <Detail label="科室" value={record.department || "-"} />
            <Detail label="文档类型" value={record.doc_type || "-"} />
            <Detail label="耗时" value={formatSeconds(record.elapsed_seconds)} />
            <Detail label="输入字符" value={formatNumber(record.input_chars)} />
            <Detail label="输出字符" value={formatNumber(record.output_chars)} />
          </div>
        ) : null}
        <section className="command-box">
          <h3>CommandInfo</h3>
          <p>{record?.command_info || "-"}</p>
        </section>
        {loadingRaw && !raw ? <EmptyState>正在读取原始 txt</EmptyState> : null}
        {raw ? (
          <>
            <div className="raw-actions">
              <button className="secondary-button" onClick={copyInputJson} disabled={inputBusy}>
                <Copy size={17} aria-hidden />
                复制 input JSON
              </button>
              <button className="secondary-button" onClick={saveAsTestInput} disabled={inputBusy}>
                <ClipboardList size={17} aria-hidden />
                保存为测试 input
              </button>
            </div>
            <pre className="raw-text">{raw.content}</pre>
          </>
        ) : null}
      </aside>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function IndexPage() {
  const [status, setStatus] = useState<IndexStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setStatus(await api.indexStatus());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取索引状态失败");
    }
  }

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      await api.refreshIndex();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "触发刷新失败");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const run = status?.latest_run;
  const progress = run && run.total_files ? Math.round((run.scanned_files / run.total_files) * 100) : 0;

  return (
    <main className="page">
      {error ? <ErrorBanner message={error} /> : null}
      <div className="kpi-grid index-kpis">
        <KpiCard label="总索引" value={formatNumber(status?.total_records)} hint="SQLite records" icon={<Database size={20} aria-hidden />} />
        <KpiCard label="解析成功" value={formatNumber(status?.parsed_records)} hint="parse_status ok" icon={<FileText size={20} aria-hidden />} />
        <KpiCard label="解析错误" value={formatNumber(status?.parse_errors)} hint="需要排查的文件" icon={<Activity size={20} aria-hidden />} />
        <KpiCard label="刷新频率" value={`${Math.round((status?.refresh_interval_seconds ?? 3600) / 60)} 分钟`} hint="后台定时任务" icon={<Clock size={20} aria-hidden />} />
      </div>
      <section className="panel">
        <div className="panel-title">
          <h2>索引任务</h2>
          <button className="primary-button" onClick={refresh} disabled={busy || status?.is_running}>
            <RefreshCw size={17} aria-hidden />
            {status?.is_running ? "刷新中" : "手动刷新"}
          </button>
        </div>
        <div className="progress-line">
          <span style={{ width: `${status?.is_running ? progress : 100}%` }} />
        </div>
        <div className="status-grid">
          <Detail label="状态" value={status?.is_running ? "running" : run?.status || "-"} />
          <Detail label="开始时间" value={shortDateTime(run?.started_at)} />
          <Detail label="完成时间" value={shortDateTime(run?.finished_at)} />
          <Detail label="扫描文件" value={`${formatNumber(run?.scanned_files)} / ${formatNumber(run?.total_files)}`} />
          <Detail label="写入记录" value={formatNumber(run?.indexed_files)} />
          <Detail label="跳过未变更" value={formatNumber(run?.skipped_files)} />
          <Detail label="错误文件" value={formatNumber(run?.error_files)} />
          <Detail label="最近索引" value={shortDateTime(status?.last_indexed_at)} />
        </div>
      </section>
      <section className="panel">
        <div className="panel-title">
          <h2>数据路径</h2>
        </div>
        <div className="path-list">
          <code>{status?.query_save_dir}</code>
          <code>{status?.archive_dir}</code>
          <code>{status?.db_path}</code>
        </div>
      </section>
    </main>
  );
}

export default function App() {
  const [view, setView] = useHashView();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch((err) => {
        if (!(err instanceof ApiError) || err.status !== 401) {
          // Keep unauthenticated state for any startup failure.
        }
      })
      .finally(() => setChecking(false));
  }, []);

  async function logout() {
    await api.logout().catch(() => undefined);
    setUser(null);
  }

  if (checking) {
    return <EmptyState>正在检查登录状态</EmptyState>;
  }

  if (!user) {
    return <LoginPage onLogin={setUser} />;
  }

  return (
    <Layout user={user} view={view} setView={setView} onLogout={logout}>
      {view === "dashboard" ? (
        <DashboardPage />
      ) : view === "records" ? (
        <RecordsPage />
      ) : view === "commands" ? (
        <CommandInfoPage />
      ) : view === "templates" ? (
        <TemplatesPage />
      ) : view === "test-requests" ? (
        <TestRequestsPage />
      ) : (
        <IndexPage />
      )}
    </Layout>
  );
}
