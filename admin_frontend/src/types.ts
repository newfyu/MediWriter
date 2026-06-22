export type User = {
  username: string;
};

export type Summary = {
  total_records: number;
  parsed_records: number;
  parse_errors: number;
  active_doctors: number;
  doc_types: number;
  avg_elapsed_seconds: number | null;
  p50_elapsed_seconds: number | null;
  p95_elapsed_seconds: number | null;
  today_records: number;
  last_7_days_records: number;
  last_30_days_records: number;
  last_indexed_at: string | null;
  first_record_date: string | null;
  last_record_date: string | null;
};

export type TrendPoint = {
  date?: string;
  hour?: number;
  source?: string;
  count: number;
};

export type Trends = {
  daily: TrendPoint[];
  hourly: TrendPoint[];
  hourly_today: TrendPoint[];
  hourly_7day_avg: TrendPoint[];
  sources: TrendPoint[];
};

export type BreakdownItem = {
  doctor_id?: string | null;
  doctor_name?: string | null;
  department?: string | null;
  doc_type?: string | null;
  source?: string | null;
  status?: string | null;
  count: number;
  avg_elapsed_seconds?: number | null;
};

export type Breakdowns = {
  doctors: BreakdownItem[];
  departments: BreakdownItem[];
  doc_types: BreakdownItem[];
  sources: BreakdownItem[];
  statuses: BreakdownItem[];
};

export type RecordItem = {
  id: number;
  source: string;
  filename: string;
  parse_status: string;
  parse_error: string | null;
  doctor_id: string | null;
  doctor_name: string | null;
  department: string | null;
  patient_department: string | null;
  doc_type: string | null;
  command_info: string | null;
  record_time: string | null;
  record_date: string | null;
  record_hour: number | null;
  elapsed_seconds: number | null;
  input_chars: number;
  output_chars: number;
  total_chars: number;
  parsed_at: string;
  path?: string;
  file_size?: number;
  file_mtime?: number;
};

export type RecordsResponse = {
  items: RecordItem[];
  total: number;
  page: number;
  page_size: number;
};

export type RawRecord = {
  id: number;
  filename: string;
  content: string;
};

export type IndexRun = {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  total_files: number;
  scanned_files: number;
  indexed_files: number;
  skipped_files: number;
  error_files: number;
  message: string | null;
};

export type IndexStatus = {
  total_records: number;
  parsed_records: number;
  parse_errors: number;
  last_indexed_at: string | null;
  is_running: boolean;
  latest_run: IndexRun | null;
  db_path: string;
  query_save_dir: string;
  archive_dir: string;
  refresh_interval_seconds: number;
};

export type CommandInfoSummary = {
  total_records: number;
  command_records: number;
  today_command_records: number;
  last_7_days_command_records: number;
  command_coverage: number;
  avg_command_length: number | null;
  latest_command_time: string | null;
};

export type CommandInfoRecent = {
  id: number;
  source: string;
  filename: string;
  doctor_id: string | null;
  doctor_name: string | null;
  department: string | null;
  doc_type: string | null;
  command_info: string;
  record_time: string | null;
  elapsed_seconds: number | null;
};

export type CommandInfoAnalysis = {
  summary: CommandInfoSummary;
  daily: TrendPoint[];
  doctors: BreakdownItem[];
  departments: BreakdownItem[];
  doc_types: BreakdownItem[];
  length_buckets: Array<{ bucket: string; count: number }>;
  recent: CommandInfoRecent[];
  recent_total: number;
  recent_page: number;
  recent_page_size: number;
};

export type RuntimeSchemaField = {
  FieldName: string;
  Description?: string;
  Position?: string;
  AnchorField?: string;
  Required?: boolean;
  Transient?: boolean;
};

export type PresetTemplate = {
  DocType: string;
  DocTypeMatch?: string;
  DicTemplate: string[];
  RuntimeSchemaFields?: RuntimeSchemaField[];
  DayLimit?: number | null;
  TemplateAdvise?: string;
  Exclude?: string[];
};

export type TemplateConfigResponse = {
  path: string;
  templates: PresetTemplate[];
  yaml_text: string;
  updated_at: number;
};

export type RecordInput = {
  id: number;
  filename: string;
  doc_type: string | null;
  doctor_name: string | null;
  department: string | null;
  input_json: string;
};

export type TemplateTestInput = {
  id: number;
  title: string;
  input_json: string;
  source_record_id: number | null;
  source_filename: string | null;
  doc_type: string | null;
  doctor_name: string | null;
  department: string | null;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
};

export type TemplateTestInputsResponse = {
  items: TemplateTestInput[];
};

export type TemplateTestRunResult = {
  ok: boolean;
  elapsed_seconds: number;
  raw_content: string;
  parsed_items: Array<{ key: string; value: string }>;
  parse_error: string | null;
  error: string | null;
  request_url: string;
};
