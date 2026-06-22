#!/usr/bin/env python3
"""Generate a single-file HTML dashboard from charts/enhanced_medical_report.md.

The script parses key tables, inlines PNG charts as base64, and outputs a
production-ready, compact HTML board that can be opened directly.
"""
from __future__ import annotations

import argparse
import base64
import html
import re
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent

def load_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Markdown not found: {path}")
    return path.read_text(encoding="utf-8")

def extract_generation_time(md_text: str) -> str:
    match = re.search(r"生成时间[:：]\s*([0-9:\-\s]+)", md_text)
    return match.group(1).strip() if match else "未提供"

def table_from_block(block: str) -> Tuple[List[str], List[List[str]]]:
    lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
    rows: List[List[str]] = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        # Skip separator rows like |-----|----|
        if all(not cell or set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append(cells)
    if len(rows) < 2:
        return [], []
    header, data = rows[0], rows[1:]
    return header, data

def extract_table(md_text: str, heading: str) -> Dict[str, List[List[str]]]:
    pattern = rf"{re.escape(heading)}\n+((?:\|.*\n)+)"
    match = re.search(pattern, md_text)
    if not match:
        return {"header": [], "rows": []}
    header, rows = table_from_block(match.group(1))
    return {"header": header, "rows": rows}

def extract_recent_commands(md_text: str) -> List[Dict[str, str]]:
    if "最近CommandInfo记录" not in md_text:
        return []
    section = md_text.split("## 💬 最近CommandInfo记录", 1)[1]
    section = section.split("*报告生成完成", 1)[0]
    chunks = re.split(r"\n###\s*\d+\.\s*", section)
    entries: List[Dict[str, str]] = []
    for chunk in chunks[1:]:
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        timestamp = lines[0].strip()
        doctor_match = re.search(r"\*\*医生:\*\*\s*(.+)", chunk)
        file_match = re.search(r"\*\*文件:\*\*\s*\[(.+?)\]\((.+?)\)", chunk)
        content_match = re.search(r"\*\*内容:\*\*\s*```(.*?)```", chunk, re.S)
        entries.append(
            {
                "timestamp": timestamp,
                "doctor": doctor_match.group(1).strip() if doctor_match else "",
                "file": file_match.group(1).strip() if file_match else "",
                "file_href": file_match.group(2).strip() if file_match else "",
                "content": content_match.group(1).strip() if content_match else "",
            }
        )
    return entries

def encode_image(path: Path) -> str:
    if not path.exists():
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"

def render_table_card(title: str, table: Dict[str, List[List[str]]], card_id: str, note: str = "", searchable: bool = False) -> str:
    header = table.get("header", [])
    rows = table.get("rows", [])
    if not header or not rows:
        return ""
    head_html = "".join(f"<th>{html.escape(col)}</th>" for col in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    search_box = (
        f"<div class='table-actions'><input type='search' placeholder='快速筛选…' aria-label='筛选' data-table='{card_id}' class='table-search'/></div>"
        if searchable
        else ""
    )
    note_html = f"<div class='note'>{html.escape(note)}</div>" if note else ""
    return f"""
    <section class="card" id="{card_id}">
        <div class="card-title-row">
            <h3>{html.escape(title)}</h3>
            {search_box}
        </div>
        <div class="table-wrap" data-table-id="{card_id}">
            <table>
                <thead><tr>{head_html}</tr></thead>
                <tbody>{body_html}</tbody>
            </table>
        </div>
        {note_html}
    </section>
    """

def render_recent(entries: List[Dict[str, str]]) -> str:
    if not entries:
        return ""
    cards = []
    for item in entries:
        cards.append(
            f"""
            <article class="activity">
                <div class="activity-top">
                    <div class="pill">{html.escape(item.get('timestamp', ''))}</div>
                    <div class="activity-doctor">{html.escape(item.get('doctor', ''))}</div>
                </div>
                <div class="activity-file">{html.escape(item.get('file', ''))}</div>
                <p class="activity-body">{html.escape(item.get('content', ''))}</p>
            </article>
            """
        )
    return "<div class='activity-grid'>" + "".join(cards) + "</div>"

def render_charts(images: Dict[str, str]) -> str:
    cards = []
    for title, key in [
        ("按日分布的日志数量", "daily_logs"),
        ("医生使用次数分布", "doctor_usage"),
        ("文档类型统计", "doc_types"),
        ("日志数量时间趋势", "time_trend"),
        ("累积参与医生数量趋势", "cumulative_doctors"),
        ("病历请求时间分布", "hourly_request_distribution"),
    ]:
        src = images.get(key, "")
        if not src:
            continue
        cards.append(
            f"""
            <section class="card chart-card">
                <div class="card-title-row"><h3>{title}</h3></div>
                <img src="{src}" alt="{title}" loading="lazy" />
            </section>
            """
        )
    return "<div class='chart-grid'>" + "".join(cards) + "</div>"

def render_summary(table: Dict[str, List[List[str]]]) -> str:
    if not table["rows"]:
        return ""
    cards = []
    for item in table["rows"]:
        if len(item) < 2:
            continue
        label, value = item[0], item[1]
        cards.append(
            f"""
            <div class="mini-card">
                <div class="mini-label">{html.escape(label)}</div>
                <div class="mini-value">{html.escape(value)}</div>
            </div>
            """
        )
    return "<div class='mini-grid'>" + "".join(cards) + "</div>"

def build_html(md_path: Path, data: Dict[str, Dict[str, List[List[str]]]], images: Dict[str, str], recent: List[Dict[str, str]], generation_time: str) -> str:
    summary = data.get("summary", {"rows": []})
    summary_lookup = {row[0]: row[1] for row in summary.get("rows", []) if len(row) >= 2}
    total_logs = summary_lookup.get("日志总数", "-")
    doctors = summary_lookup.get("涉及医生数", "-")
    days = summary_lookup.get("统计天数", "-")
    doc_types_count = summary_lookup.get("文档类型数", "-")

    html_body = f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"UTF-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>医疗日志分析看板</title>
<style>
:root {{
  --bg: #f6f8fb;
  --panel: #ffffff;
  --panel-strong: #0f172a;
  --text: #0f172a;
  --muted: #6b7280;
  --accent: #0a84ff;
  --accent-2: #00b8a9;
  --border: #e5e7eb;
  --shadow: 0 10px 40px rgba(15, 23, 42, 0.08);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: "Inter", "Noto Sans SC", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  background: radial-gradient(circle at 20% 20%, rgba(0, 184, 169, 0.06), transparent 32%),
              radial-gradient(circle at 80% 0%, rgba(10, 132, 255, 0.08), transparent 36%),
              var(--bg);
  color: var(--text);
  -webkit-font-smoothing: antialiased;
}}
.container {{
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px 20px 32px;
}}
.hero {{
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 18px 20px;
  background: linear-gradient(135deg, #0a84ff, #00b8a9);
  color: white;
  border-radius: 14px;
  box-shadow: var(--shadow);
}}
.hero h1 {{ margin: 4px 0 8px; font-size: 26px; }}
.hero .meta {{ font-size: 13px; opacity: 0.92; }}
.hero .tagline {{
  background: rgba(255, 255, 255, 0.16);
  padding: 10px 14px;
  border-radius: 12px;
  font-weight: 600;
  letter-spacing: 0.2px;
}}

.card {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: var(--shadow);
  padding: 14px 16px;
}}
.card-title-row {{
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}}
.card h3 {{ margin: 0; font-size: 16px; }}

.mini-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}}
.mini-card {{
  background: #0f172a;
  color: #e5edff;
  border-radius: 12px;
  padding: 12px 14px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
}}
.mini-label {{ font-size: 12px; color: #c7d2fe; letter-spacing: 0.3px; }}
.mini-value {{ font-size: 20px; font-weight: 700; margin-top: 4px; }}

.chart-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
  margin-top: 14px;
}}
.chart-card img {{ width: 100%; border-radius: 10px; border: 1px solid var(--border); background: #f8fafc; }}

.table-wrap {{
  max-height: 280px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
}}
table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
thead th {{
  position: sticky;
  top: 0;
  background: #f8fafc;
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
  font-size: 12px;
  color: var(--muted);
}}
tbody td {{ padding: 7px 10px; border-bottom: 1px solid #f1f5f9; font-size: 13px; color: #111827; }}
tbody tr:last-child td {{ border-bottom: none; }}

.table-actions {{ margin-left: auto; }}
.table-search {{
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
  font-size: 13px;
  min-width: 180px;
}}

.note {{ margin-top: 8px; color: var(--muted); font-size: 12px; }}

.grid-2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-top: 14px; }}

.activity-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}}
.activity {{
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 12px;
  background: linear-gradient(145deg, #ffffff, #f8fbff);
}}
.activity-top {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; }}
.pill {{ background: #eef2ff; color: #4338ca; padding: 4px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; letter-spacing: 0.2px; }}
.activity-doctor {{ font-weight: 700; color: #0f172a; }}
.activity-file {{ color: #0a84ff; font-size: 12px; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.activity-body {{ margin: 0; font-size: 13px; color: #1f2937; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }}

@media (max-width: 800px) {{
  .hero {{ grid-template-columns: 1fr; }}
  .mini-grid {{ grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }}
}}
</style>
</head>
<body>
  <div class="container">
    <section class="hero">
      <div>
        <div class="meta">生成时间 {html.escape(generation_time)} · 数据源 {html.escape(str(md_path))}</div>
        <h1>医疗日志分析看板</h1>
        <div class="meta">覆盖 {html.escape(days)} 天 · {html.escape(doctors)} 位医生 · {html.escape(doc_types_count)} 种文档类型</div>
      </div>
      <div class="tagline">累计日志 {html.escape(total_logs)} 条</div>
    </section>

    <section class="card" aria-label="总体统计">
      <div class="card-title-row"><h3>总体统计</h3></div>
      {render_summary(summary)}
    </section>

    {render_charts(images)}

    <div class="grid-2">
      {render_table_card("按日分布统计", data.get('daily', {}), "daily-table", "可在滚动区域查看 70 天分布")}
      {render_table_card("累积参与医生数量", data.get('cumulative_doctors', {}), "cumulative-table")}
    </div>

    <div class="grid-2">
      {render_table_card("医生使用统计", data.get('doctor_usage', {}), "doctor-usage-table", "可用右上角搜索框快速过滤", searchable=True)}
      {render_table_card("文档类型统计", data.get('doc_types', {}), "doc-types-table")}
    </div>

    <section class="card" aria-label="最近 CommandInfo 记录">
      <div class="card-title-row"><h3>最近 CommandInfo 记录</h3></div>
      {render_recent(recent)}
    </section>
  </div>

<script>
const searches = document.querySelectorAll('.table-search');
searches.forEach(input => {{
  input.addEventListener('input', () => {{
    const term = input.value.toLowerCase();
    const tableId = input.dataset.table;
    const wrap = document.querySelector(`[data-table-id="${{tableId}}"]`);
    if (!wrap) return;
    wrap.querySelectorAll('tbody tr').forEach(row => {{
      const visible = Array.from(row.cells).some(cell => cell.textContent.toLowerCase().includes(term));
      row.style.display = visible ? '' : 'none';
    }});
  }});
}});
</script>
</body>
</html>"""
    return html_body

def build(md_path: Path, output: Path) -> None:
    md_text = load_text(md_path)
    generation_time = extract_generation_time(md_text)
    data = {
        "summary": extract_table(md_text, "## 📊 总体统计"),
        "daily": extract_table(md_text, "## 📅 按日分布统计"),
        "cumulative_doctors": extract_table(md_text, "## 👥 累积参与医生数量统计"),
        "doctor_usage": extract_table(md_text, "## 👨‍⚕️ 医生使用统计"),
        "doc_types": extract_table(md_text, "## 📄 文档类型统计"),
    }
    image_dir = md_path.parent
    images = {
        "daily_logs": encode_image(image_dir / "daily_logs.png"),
        "doctor_usage": encode_image(image_dir / "doctor_usage.png"),
        "doc_types": encode_image(image_dir / "doc_types.png"),
        "time_trend": encode_image(image_dir / "time_trend.png"),
        "cumulative_doctors": encode_image(image_dir / "cumulative_doctors.png"),
        "hourly_request_distribution": encode_image(image_dir / "hourly_request_distribution.png"),
    }
    recent = extract_recent_commands(md_text)
    html_text = build_html(md_path, data, images, recent, generation_time)
    output.write_text(html_text, encoding="utf-8")
    print(f"✅ Dashboard written to {output}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a single-file medical dashboard HTML")
    parser.add_argument("--md", type=Path, default=ROOT / "charts" / "enhanced_medical_report.md", help="Source markdown file")
    parser.add_argument("--out", type=Path, default=ROOT / "medical_dashboard.html", help="Output HTML path")
    args = parser.parse_args()
    build(args.md, args.out)

if __name__ == "__main__":
    main()
