#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
医疗日志分析报告生成脚本
该脚本先执行tidy.py，然后分析archive中的文件生成报告和图表
"""

import os
import json
import re
import html as html_mod
import base64
import subprocess
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
from collections import Counter, defaultdict
import seaborn as sns
from pathlib import Path
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import argparse

# 设置中文字体
import matplotlib.font_manager as fm
from matplotlib.font_manager import FontProperties

# 强制设置中文字体
zh_font = None
for font_path in ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                  '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
                  '/usr/share/fonts/truetype/droid/DroidSansFallback.ttf']:
    try:
        if os.path.exists(font_path):
            zh_font = FontProperties(fname=font_path)
            fm.fontManager.addfont(font_path)
            break
    except:
        continue

# 设置matplotlib参数
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'Droid Sans Fallback', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.size'] = 10

# 强制清除DejaVu Sans字体，避免fallback到该字体
if 'DejaVu Sans' in plt.rcParams['font.sans-serif']:
    font_list = list(plt.rcParams['font.sans-serif'])
    while 'DejaVu Sans' in font_list:
        font_list.remove('DejaVu Sans')
    plt.rcParams['font.sans-serif'] = font_list

def run_tidy():
    """执行tidy.py脚本"""
    try:
        print("正在执行tidy.py...")
        result = subprocess.run(['python3', 'tidy.py'], capture_output=True, text=True)
        if result.returncode == 0:
            print("tidy.py执行成功")
        else:
            print(f"tidy.py执行失败: {result.stderr}")
    except Exception as e:
        print(f"执行tidy.py时出错: {e}")

def parse_filename(filename):
    """解析文件名获取医生ID和时间信息"""
    try:
        # 文件名格式可能是: 
        # 1. {医生ID}_{日期}_{时间}.txt (旧格式)
        # 2. {医生姓名}_{医生ID}_{日期}_{时间}.txt (新格式)
        # 3. test_user_{日期}_{时间}.txt (测试格式)
        parts = filename.replace('.txt', '').split('_')
        
        if len(parts) >= 3:
            # 检查是否为test_user格式 (医生姓名_test_user_日期_时间)
            if len(parts) >= 4 and 'test' in parts[1].lower() and 'user' in parts[1].lower():
                doctor_id = f"{parts[0]}_{parts[1]}"
                date_str = parts[2]
                time_str = parts[3]
            elif len(parts) >= 4 and parts[1].isdigit():
                # 新格式: 医生姓名_医生ID_日期_时间
                doctor_id = parts[1]  # 使用医生ID
                date_str = parts[2]
                time_str = parts[3]
            else:
                # 旧格式: 医生ID_日期_时间
                doctor_id = parts[0]
                date_str = parts[1]
                time_str = parts[2] if len(parts) > 2 else '00-00-00'
            
            datetime_str = f"{date_str} {time_str.replace('-', ':')}"
            timestamp = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
            return doctor_id, timestamp
    except Exception as e:
        print(f"解析文件名失败 {filename}: {e}")
    return None, None

def load_archive_data():
    """加载archive目录中的所有日志文件"""
    archive_dir = Path('archive')
    if not archive_dir.exists():
        print("archive目录不存在")
        return []
    
    data = []
    for file_path in archive_dir.glob('*.txt'):
        # 跳过test_user文件
        if 'test_user' in file_path.name:
            continue
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    # 处理可能包含多个JSON对象的文件
                    json_objects = []
                    lines = content.split('\n')
                    current_json = ""
                    brace_count = 0
                    
                    for line in lines:
                        # 跳过非JSON行（如时间戳等）
                        line = line.strip()
                        if not line or (not line.startswith('{') and brace_count == 0):
                            continue
                            
                        current_json += line + "\n"
                        brace_count += line.count('{') - line.count('}')
                        
                        if brace_count == 0 and current_json.strip():
                            try:
                                json_obj = json.loads(current_json.strip())
                                json_objects.append(json_obj)
                                current_json = ""
                            except json.JSONDecodeError:
                                current_json = ""
                                continue
                    
                    # 如果只有一个JSON对象，直接解析
                    if not json_objects:
                        try:
                            json_obj = json.loads(content)
                            json_objects = [json_obj]
                        except json.JSONDecodeError as e:
                            print(f"解析JSON失败 {file_path}: {e}")
                            continue
                    
                    doctor_id, timestamp = parse_filename(file_path.name)
                    
                    # 只处理第一个JSON对象
                    if json_objects:
                        data.append({
                            'filename': file_path.name,
                            'doctor_id': doctor_id,
                            'timestamp': timestamp,
                            'data': json_objects[0]  # 只取第一个JSON对象
                        })
        except Exception as e:
            print(f"读取文件失败 {file_path}: {e}")
    
    return data

def analyze_logs(data):
    """分析日志数据"""
    print("\n=== 医疗日志分析报告 ===")
    
    # 1. 当前有多少日志
    total_logs = len(data)
    print(f"\n1. 日志总数: {total_logs}")
    
    # 2. 按日分布的日志数量
    daily_counts = defaultdict(int)
    for item in data:
        if item['timestamp']:
            date_str = item['timestamp'].strftime('%Y-%m-%d')
            daily_counts[date_str] += 1
    
    print("\n2. 按日分布的日志数量:")
    for date, count in sorted(daily_counts.items()):
        print(f"   {date}: {count}条")
    
    # 3. 医生使用次数统计
    doctor_counts = Counter()
    doctor_names = {}
    
    for item in data:
        if item['doctor_id']:
            doctor_counts[item['doctor_id']] += 1
            # 尝试从数据中获取医生姓名
            if isinstance(item['data'], dict) and 'OperInfo' in item['data'] and 'OperName' in item['data']['OperInfo']:
                doctor_names[item['doctor_id']] = item['data']['OperInfo']['OperName']
    
    print("\n3. 医生使用次数统计:")
    for doctor_id, count in doctor_counts.most_common():
        doctor_name = doctor_names.get(doctor_id, f"医生{doctor_id}")
        print(f"   {doctor_name} (ID: {doctor_id}): {count}次")
    
    # 4. 按天统计累积参与的医生数量
    daily_doctor_participation = defaultdict(set)  # 每天参与的医生集合
    for item in data:
        if item['timestamp'] and item['doctor_id']:
            date_str = item['timestamp'].strftime('%Y-%m-%d')
            daily_doctor_participation[date_str].add(item['doctor_id'])
    
    # 计算累积医生数量
    cumulative_doctors = {}
    all_doctors = set()
    for date in sorted(daily_doctor_participation.keys()):
        all_doctors.update(daily_doctor_participation[date])
        cumulative_doctors[date] = len(all_doctors)
    
    print("\n4. 按天统计累积参与的医生数量:")
    for date, cumulative_count in sorted(cumulative_doctors.items()):
        daily_new = len(daily_doctor_participation[date])
        print(f"   {date}: 当日{daily_new}人，累计{cumulative_count}人")
    
    # 5. 文档类型统计（只统计每个文件的第一个JSON对象的DocType字段）
    doc_type_counts = Counter()
    unknown_reasons = Counter()
    processed_files = set()  # 记录已处理的文件
    
    for i, item in enumerate(data):
        # 只处理每个文件的第一个JSON对象
        if item['filename'] in processed_files:
            continue
        processed_files.add(item['filename'])
        
        # 检查data是否为字典
        if isinstance(item['data'], dict):
            doc_type = item['data'].get('DocType')
            

            
            if doc_type:
                # 进一步检查DocType的有效性
                if isinstance(doc_type, str) and doc_type.strip():
                    doc_type_counts[doc_type] += 1
                elif isinstance(doc_type, list):
                    doc_type_counts['未知类型(DocType为列表)'] += 1
                    unknown_reasons['DocType为列表格式'] += 1
                else:
                    doc_type_counts['未知类型(DocType格式异常)'] += 1
                    unknown_reasons['DocType格式异常'] += 1
            else:
                doc_type_counts['未知类型'] += 1
                unknown_reasons['缺少DocType字段'] += 1
        elif isinstance(item['data'], list):
            # 如果data是列表，跳过或处理为未知类型
            doc_type_counts['未知类型(列表数据)'] += 1
            unknown_reasons['数据为列表格式'] += 1
        else:
            doc_type_counts['未知类型(其他格式)'] += 1
            unknown_reasons['数据格式异常'] += 1
    
    print("\n5. 文档类型统计:")
    for doc_type, count in doc_type_counts.most_common():
        print(f"   {doc_type}: {count}个")
    
    print("\n   未知类型原因分析:")
    for reason, count in unknown_reasons.most_common():
        print(f"     {reason}: {count}个")
    
    # 6. 最近30个commandinfo不为空的列表
    command_infos = []
    for item in data:
        if item['timestamp'] and isinstance(item['data'], dict) and 'CommandInfo' in item['data']:
            command_info = item['data']['CommandInfo']
            if command_info and command_info.strip():
                command_infos.append({
                    'timestamp': item['timestamp'],
                    'doctor_id': item['doctor_id'],
                    'doctor_name': doctor_names.get(item['doctor_id'], f"医生{item['doctor_id']}"),
                    'command_info': command_info,
                    'filename': item['filename']
                })
    
    # 按时间排序，取最近的30个
    command_infos.sort(key=lambda x: x['timestamp'], reverse=True)
    recent_commands = command_infos[:30]
    
    print("\n6. 最近30个CommandInfo不为空的记录:")
    for i, cmd in enumerate(recent_commands, 1):
        print(f"   {i}. {cmd['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} - {cmd['doctor_name']} - {cmd['command_info'][:100]}...")
    
    return {
        'total_logs': total_logs,
        'daily_counts': daily_counts,
        'doctor_counts': doctor_counts,
        'doctor_names': doctor_names,
        'doc_type_counts': doc_type_counts,
        'recent_commands': recent_commands,
        'cumulative_doctors': cumulative_doctors,
        'daily_doctor_participation': daily_doctor_participation
    }

def generate_charts(analysis_result):
    """生成图表"""
    print("\n正在生成图表...")
    
    # 创建图表目录
    charts_dir = Path('charts')
    charts_dir.mkdir(exist_ok=True)
    
    # 重新设置中文字体
    plt.rcParams['font.sans-serif'] = ['Droid Sans Fallback', 'Noto Sans CJK JP', 'SimHei']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 设置图表样式
    plt.style.use('default')
    sns.set_palette("husl")
    
    # 1. 按日分布的日志数量柱状图
    if analysis_result['daily_counts']:
        plt.figure(figsize=(12, 6))
        dates = list(analysis_result['daily_counts'].keys())
        counts = list(analysis_result['daily_counts'].values())
        
        plt.bar(dates, counts, color='skyblue', alpha=0.7)
        
        # 使用中文字体设置标题和标签
        title_props = {'fontsize': 16, 'fontweight': 'bold'}
        label_props = {'fontsize': 12}
        
        if zh_font:
            title_props['fontproperties'] = zh_font
            label_props['fontproperties'] = zh_font
        
        plt.title('按日分布的日志数量', **title_props)
        plt.xlabel('日期', **label_props)
        plt.ylabel('日志数量', **label_props)
        plt.xticks(rotation=45)
        plt.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig(charts_dir / 'daily_logs.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    # 2. 医生使用次数饼图
    if analysis_result['doctor_counts']:
        plt.figure(figsize=(10, 8))
        doctor_data = []
        for doctor_id, count in analysis_result['doctor_counts'].most_common(10):  # 只显示前10名
            doctor_name = analysis_result['doctor_names'].get(doctor_id, f"医生{doctor_id}")
            doctor_data.append((doctor_name, count))
        
        names, counts = zip(*doctor_data)
        
        # 设置中文字体
        pie_props = {'autopct': '%1.1f%%', 'startangle': 90}
        title_props = {'fontsize': 16, 'fontweight': 'bold'}
        
        if zh_font:
            title_props['fontproperties'] = zh_font
            pie_props['textprops'] = {'fontproperties': zh_font}
        
        plt.pie(counts, labels=names, **pie_props)
        plt.title('医生使用次数分布（前10名）', **title_props)
        plt.axis('equal')
        plt.tight_layout()
        plt.savefig(charts_dir / 'doctor_usage.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    # 3. 文档类型统计横向柱状图
    if analysis_result['doc_type_counts']:
        plt.figure(figsize=(12, 8))
        doc_types = []
        doc_counts = []
        
        for doc_type, count in analysis_result['doc_type_counts'].most_common(15):  # 显示前15种
            doc_types.append(doc_type)
            doc_counts.append(count)
        
        plt.barh(range(len(doc_types)), doc_counts, color='lightcoral', alpha=0.7)
        
        # 使用中文字体设置标题和标签
        title_props = {'fontsize': 16, 'fontweight': 'bold'}
        label_props = {'fontsize': 12}
        
        if zh_font:
            title_props['fontproperties'] = zh_font
            label_props['fontproperties'] = zh_font
        
        # 设置Y轴标签字体
        if zh_font:
            plt.yticks(range(len(doc_types)), doc_types, fontproperties=zh_font)
        else:
            plt.yticks(range(len(doc_types)), doc_types)
        
        plt.title('文档类型统计（前15种）', **title_props)
        plt.xlabel('数量', **label_props)
        plt.ylabel('文档类型', **label_props)
        plt.grid(axis='x', alpha=0.3)
        plt.tight_layout()
        plt.savefig(charts_dir / 'doc_types.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    # 4. 时间趋势图
    if analysis_result['daily_counts']:
        plt.figure(figsize=(14, 6))
        dates = sorted(analysis_result['daily_counts'].keys())
        counts = [analysis_result['daily_counts'][date] for date in dates]
        
        plt.plot(dates, counts, marker='o', linewidth=2, markersize=6, color='green')
        
        # 使用中文字体设置标题和标签
        title_props = {'fontsize': 16, 'fontweight': 'bold'}
        label_props = {'fontsize': 12}
        
        if zh_font:
            title_props['fontproperties'] = zh_font
            label_props['fontproperties'] = zh_font
        
        plt.title('日志数量时间趋势', **title_props)
        plt.xlabel('日期', **label_props)
        plt.ylabel('日志数量', **label_props)
        plt.xticks(rotation=45)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(charts_dir / 'time_trend.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    # 5. 累积参与医生数量图表
    if analysis_result['cumulative_doctors']:
        plt.figure(figsize=(14, 6))
        dates = sorted(analysis_result['cumulative_doctors'].keys())
        cumulative_counts = [analysis_result['cumulative_doctors'][date] for date in dates]
        
        # 绘制累积医生数量折线图
        plt.plot(dates, cumulative_counts, marker='o', linewidth=3, markersize=8, color='purple', alpha=0.8)
        plt.fill_between(dates, cumulative_counts, alpha=0.3, color='purple')
        
        # 使用中文字体设置标题和标签
        title_props = {'fontsize': 16, 'fontweight': 'bold'}
        label_props = {'fontsize': 12}
        
        if zh_font:
            title_props['fontproperties'] = zh_font
            label_props['fontproperties'] = zh_font
        
        plt.title('累积参与医生数量趋势', **title_props)
        plt.xlabel('日期', **label_props)
        plt.ylabel('累积医生数量', **label_props)
        plt.xticks(rotation=45)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(charts_dir / 'cumulative_doctors.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    print(f"图表已保存到 {charts_dir} 目录")
    
    return {
        'daily_counts': analysis_result['daily_counts'],
        'doctor_counts': analysis_result['doctor_counts'],
        'doc_type_counts': analysis_result['doc_type_counts'],
        'cumulative_doctors': analysis_result['cumulative_doctors']
    }

def generate_hourly_request_chart(data):
    """
    生成病历请求时间分布报表
    显示今天、3天平均、7天平均的每小时病历数量
    横轴：一天的各个时间（按小时）
    纵轴：每个时间区间的病历数
    """
    print("\n正在生成病历请求时间分布报表...")
    
    from datetime import datetime, timedelta
    import numpy as np
    from scipy.interpolate import make_interp_spline
    
    # 创建图表目录
    charts_dir = Path('charts')
    charts_dir.mkdir(exist_ok=True)
    
    # 获取当前日期
    today = datetime.now().date()
    
    # 初始化小时统计字典
    today_hourly = {hour: 0 for hour in range(24)}
    three_day_hourly = {hour: [] for hour in range(24)}
    seven_day_hourly = {hour: [] for hour in range(24)}
    
    # 统计各时间段的数据
    for item in data:
        if item['timestamp']:
            timestamp = item['timestamp']
            date = timestamp.date()
            hour = timestamp.hour
            
            # 今天的数据
            if date == today:
                today_hourly[hour] += 1
            
            # 最近3天的数据（包括今天）
            if (today - date).days <= 2:
                three_day_hourly[hour].append(1)
            
            # 最近7天的数据（包括今天）
            if (today - date).days <= 6:
                seven_day_hourly[hour].append(1)
    
    # 计算平均值
    three_day_avg = {hour: sum(three_day_hourly[hour]) / 3 for hour in range(24)}
    seven_day_avg = {hour: sum(seven_day_hourly[hour]) / 7 for hour in range(24)}
    
    # 准备绘图数据
    hours = list(range(24))
    today_counts = [today_hourly[hour] for hour in hours]
    three_day_counts = [three_day_avg[hour] for hour in hours]
    seven_day_counts = [seven_day_avg[hour] for hour in hours]
    
    # 创建图表
    plt.figure(figsize=(15, 8))
    
    # 绘制折线图
    plt.plot(hours, today_counts, marker='o', linewidth=2.5, markersize=6, 
             color='#FF6B6B', label='今天', alpha=0.9)
    plt.plot(hours, three_day_counts, marker='s', linewidth=2.5, markersize=5, 
             color='#4ECDC4', label='3天平均', alpha=0.8)
    plt.plot(hours, seven_day_counts, marker='^', linewidth=2.5, markersize=5, 
             color='#45B7D1', label='7天平均', alpha=0.8)
    
    # 平滑处理（可选）
    try:
        # 使用样条插值进行平滑处理
        hours_smooth = np.linspace(0, 23, 100)
        
        if max(today_counts) > 0:
            today_smooth = make_interp_spline(hours, today_counts, k=3)(hours_smooth)
            plt.plot(hours_smooth, today_smooth, '--', linewidth=1.5, color='#FF6B6B', alpha=0.6)
        
        if max(three_day_counts) > 0:
            three_day_smooth = make_interp_spline(hours, three_day_counts, k=3)(hours_smooth)
            plt.plot(hours_smooth, three_day_smooth, '--', linewidth=1.5, color='#4ECDC4', alpha=0.6)
        
        if max(seven_day_counts) > 0:
            seven_day_smooth = make_interp_spline(hours, seven_day_counts, k=3)(hours_smooth)
            plt.plot(hours_smooth, seven_day_smooth, '--', linewidth=1.5, color='#45B7D1', alpha=0.6)
    except:
        # 如果平滑处理失败，跳过
        pass
    
    # 设置图表样式
    title_props = {'fontsize': 16, 'fontweight': 'bold'}
    label_props = {'fontsize': 12}
    
    if zh_font:
        title_props['fontproperties'] = zh_font
        label_props['fontproperties'] = zh_font
    
    plt.title('病历请求时间分布（按小时统计）', **title_props)
    plt.xlabel('时间（小时）', **label_props)
    plt.ylabel('病历数量', **label_props)
    
    # 设置X轴刻度
    plt.xticks(range(0, 24, 2), [f'{h:02d}:00' for h in range(0, 24, 2)])
    
    # 添加网格
    plt.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
    
    # 添加图例
    legend_props = {}
    if zh_font:
        legend_props['prop'] = zh_font
    plt.legend(loc='upper right', **legend_props)
    
    # 设置Y轴从0开始
    plt.ylim(bottom=0)
    
    # 添加背景色区分时间段
    plt.axvspan(0, 6, alpha=0.1, color='blue', label='深夜')
    plt.axvspan(6, 12, alpha=0.1, color='yellow', label='上午')
    plt.axvspan(12, 18, alpha=0.1, color='orange', label='下午')
    plt.axvspan(18, 24, alpha=0.1, color='purple', label='晚上')
    
    plt.tight_layout()
    
    # 保存图表
    chart_path = charts_dir / 'hourly_request_distribution.png'
    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"病历请求时间分布图表已保存到 {chart_path}")
    
    # 生成统计报告
    report_data = {
        'today_total': sum(today_counts),
        'three_day_avg_total': sum(three_day_counts),
        'seven_day_avg_total': sum(seven_day_counts),
        'peak_hour_today': hours[today_counts.index(max(today_counts))] if max(today_counts) > 0 else None,
        'peak_hour_3day': hours[three_day_counts.index(max(three_day_counts))] if max(three_day_counts) > 0 else None,
        'peak_hour_7day': hours[seven_day_counts.index(max(seven_day_counts))] if max(seven_day_counts) > 0 else None,
        'hourly_data': {
            'today': today_hourly,
            'three_day_avg': three_day_avg,
            'seven_day_avg': seven_day_avg
        }
    }
    
    print(f"\n=== 病历请求时间分布统计 ===")
    print(f"今天总计: {report_data['today_total']} 条")
    print(f"3天平均总计: {report_data['three_day_avg_total']:.1f} 条/天")
    print(f"7天平均总计: {report_data['seven_day_avg_total']:.1f} 条/天")
    
    if report_data['peak_hour_today'] is not None:
        print(f"今天高峰时段: {report_data['peak_hour_today']:02d}:00")
    if report_data['peak_hour_3day'] is not None:
        print(f"3天平均高峰时段: {report_data['peak_hour_3day']:02d}:00")
    if report_data['peak_hour_7day'] is not None:
        print(f"7天平均高峰时段: {report_data['peak_hour_7day']:02d}:00")
    
    return report_data

def generate_report(analysis_result):
    """生成详细报告"""
    report_content = f"""
# 医疗日志分析报告

生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 总体统计

- **日志总数**: {analysis_result['total_logs']} 条
- **涉及医生数**: {len(analysis_result['doctor_counts'])} 人
- **文档类型数**: {len(analysis_result['doc_type_counts'])} 种
- **统计日期范围**: {min(analysis_result['daily_counts'].keys()) if analysis_result['daily_counts'] else 'N/A'} 至 {max(analysis_result['daily_counts'].keys()) if analysis_result['daily_counts'] else 'N/A'}

## 2. 按日分布统计

"""
    
    for date, count in sorted(analysis_result['daily_counts'].items()):
        report_content += f"- {date}: {count} 条\n"
    
    report_content += "\n## 3. 累积参与医生数量统计\n\n"
    
    for date, count in sorted(analysis_result['cumulative_doctors'].items()):
        report_content += f"- {date}: {count} 位医生\n"
    
    report_content += "\n## 4. 医生使用统计\n\n"
    
    for doctor_id, count in analysis_result['doctor_counts'].most_common():
        doctor_name = analysis_result['doctor_names'].get(doctor_id, f"医生{doctor_id}")
        report_content += f"- {doctor_name} (ID: {doctor_id}): {count} 次\n"
    
    report_content += "\n## 5. 文档类型统计\n\n"
    
    for doc_type, count in analysis_result['doc_type_counts'].most_common():
        report_content += f"- {doc_type}: {count} 个\n"
    
    report_content += "\n## 6. 最近30个CommandInfo记录\n\n"
    
    for i, cmd in enumerate(analysis_result['recent_commands'], 1):
        report_content += f"{i}. **{cmd['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}** - {cmd['doctor_name']}\n"
        report_content += f"   文件: ../archive/{cmd['filename']}\n"
        report_content += f"   内容: {cmd['command_info'][:200]}...\n\n"
    
    # 保存报告到charts目录
    charts_dir = Path('charts')
    charts_dir.mkdir(exist_ok=True)
    
    report_file = charts_dir / 'medical_report.md'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    print(f"详细报告已保存为 {report_file}")

def generate_enhanced_markdown_report(analysis_result, charts_dir):
    """生成增强版Markdown报告，嵌入图表"""
    print("\n正在生成增强版Markdown报告...")
    
    # 创建Markdown文件
    md_file = charts_dir / 'enhanced_medical_report.md'
    
    # 构建Markdown内容
    md_content = f"""# 医疗日志分析报告

**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 📊 总体统计

| 统计项目 | 数值 |
|---------|------|
| 日志总数 | {analysis_result['total_logs']} |
| 涉及医生数 | {len(analysis_result['doctor_counts'])} |
| 文档类型数 | {len(analysis_result['doc_type_counts'])} |
| 统计天数 | {len(analysis_result['daily_counts'])} |

---

## 📈 图表分析

### 按日分布的日志数量
![按日分布的日志数量](daily_logs.png)

### 医生使用次数分布
![医生使用次数分布](doctor_usage.png)

### 文档类型统计
![文档类型统计](doc_types.png)

### 日志数量时间趋势
![日志数量时间趋势](time_trend.png)

### 累积参与医生数量趋势
![累积参与医生数量趋势](cumulative_doctors.png)

### 病历请求时间分布
![病历请求时间分布](hourly_request_distribution.png)

---

## 📅 按日分布统计

| 日期 | 日志数量 | 占比 |
|------|----------|------|"""
    
    # 添加按日分布数据
    total_logs = analysis_result['total_logs']
    for date, count in sorted(analysis_result['daily_counts'].items()):
        percentage = (count / total_logs * 100) if total_logs > 0 else 0
        md_content += f"\n| {date} | {count} | {percentage:.1f}% |"
    
    md_content += "\n\n---\n\n## 👥 累积参与医生数量统计\n\n| 日期 | 累积医生数量 |\n|------|------------|"
    
    # 添加累积医生数据
    for date, count in sorted(analysis_result['cumulative_doctors'].items()):
        md_content += f"\n| {date} | {count} |"
    
    md_content += "\n\n---\n\n## 👨‍⚕️ 医生使用统计\n\n| 医生姓名 | 医生ID | 使用次数 | 占比 |\n|----------|--------|----------|------|"
    
    # 添加医生使用数据（显示前20名）
    for doctor_id, count in analysis_result['doctor_counts'].most_common(20):
        doctor_name = analysis_result['doctor_names'].get(doctor_id, f"医生{doctor_id}")
        percentage = (count / total_logs * 100) if total_logs > 0 else 0
        md_content += f"\n| {doctor_name} | {doctor_id} | {count} | {percentage:.1f}% |"
    
    md_content += "\n\n---\n\n## 📄 文档类型统计\n\n| 文档类型 | 数量 | 占比 |\n|----------|------|------|"
    
    # 添加文档类型数据（显示前15种）
    total_docs = sum(analysis_result['doc_type_counts'].values())
    for doc_type, count in analysis_result['doc_type_counts'].most_common(15):
        percentage = (count / total_docs * 100) if total_docs > 0 else 0
        md_content += f"\n| {doc_type} | {count} | {percentage:.1f}% |"
    
    md_content += "\n\n---\n\n## 💬 最近CommandInfo记录\n\n"
    
    # 添加最近的CommandInfo记录（显示前30条）
    for i, cmd in enumerate(analysis_result['recent_commands'][:30], 1):
        timestamp = cmd['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        doctor_name = cmd['doctor_name']
        filename = cmd['filename']
        # 为文件名添加../archive/前缀并处理为链接
        file_link = f"[../archive/{filename}](../archive/{filename})"
        command_content = cmd['command_info'][:300] + ('...' if len(cmd['command_info']) > 300 else '')
        
        md_content += f"""### {i}. {timestamp}

**医生:** {doctor_name}  
**文件:** {file_link}  
**内容:**
```
{command_content}
```

"""
    
    md_content += "\n---\n\n*报告生成完成 | 医疗日志分析系统*\n"
    
    # 保存Markdown文件
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(md_content)
    
    print(f"增强版Markdown报告已保存为 {md_file}")


# --- 单页HTML看板生成 ---
def _read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')

def _extract_generation_time(md_text: str) -> str:
    match = re.search(r"生成时间[:：]\s*([0-9:\-\s]+)", md_text)
    return match.group(1).strip() if match else "未提供"

def _table_from_block(block: str):
    lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
    rows = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all((not c) or set(c) <= {"-", ":"} for c in cells):
            continue
        rows.append(cells)
    if len(rows) < 2:
        return [], []
    return rows[0], rows[1:]

def _extract_table(md_text: str, heading: str):
    pattern = rf"{re.escape(heading)}\n+((?:\|.*\n)+)"
    match = re.search(pattern, md_text)
    if not match:
        return {"header": [], "rows": []}
    header, rows = _table_from_block(match.group(1))
    return {"header": header, "rows": rows}

def _extract_recent_commands(md_text: str):
    if "最近CommandInfo记录" not in md_text:
        return []
    section = md_text.split("## 💬 最近CommandInfo记录", 1)[1]
    section = section.split("*报告生成完成", 1)[0]
    chunks = re.split(r"\n###\s*\d+\.\s*", section)
    entries = []
    for chunk in chunks[1:]:
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        timestamp = lines[0].strip()
        doctor_match = re.search(r"\*\*医生:\*\*\s*(.+)", chunk)
        file_match = re.search(r"\*\*文件:\*\*\s*\[(.+?)\]\((.+?)\)", chunk)
        content_match = re.search(r"\*\*内容:\*\*\s*```(.*?)```", chunk, re.S)
        entries.append({
            "timestamp": timestamp,
            "doctor": doctor_match.group(1).strip() if doctor_match else "",
            "file": file_match.group(1).strip() if file_match else "",
            "file_href": file_match.group(2).strip() if file_match else "",
            "content": content_match.group(1).strip() if content_match else "",
            "file_content": "",
        })
    return entries

def _read_relative_text(md_path: Path, href: str) -> str:
    try:
        target = (md_path.parent / href).resolve()
        if target.exists():
            try:
                return target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return target.read_text(errors="ignore")
    except Exception:
        return ""
    return ""

def _encode_image(path: Path) -> str:
    if not path.exists():
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"

def _render_table_card(title, table, card_id, note="", searchable=False):
    header = table.get("header", [])
    rows = table.get("rows", [])
    if not header or not rows:
        return ""
    head_html = "".join(f"<th>{html_mod.escape(col)}</th>" for col in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{html_mod.escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    search_box = (
        f"<div class='table-actions'><input type='search' placeholder='快速筛选…' aria-label='筛选' data-table='{card_id}' class='table-search'/></div>"
        if searchable else ""
    )
    note_html = f"<div class='note'>{html_mod.escape(note)}</div>" if note else ""
    return f"""
    <section class="card" id="{card_id}">
        <div class="card-title-row">
            <h3>{html_mod.escape(title)}</h3>
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

def _render_recent(entries):
    if not entries:
        return ""
    cards = []
    for idx, item in enumerate(entries):
        text_id = f"text-src-{idx}"
        file_content = item.get("file_content", "")
        content_block = f"<pre class=\"activity-body\">{html_mod.escape(item.get('content', ''))}</pre>" if item.get("content") else ""
        file_block = f"""
            <div class="activity-file">{html_mod.escape(item.get('file', ''))}</div>
            <button class="txt-trigger" data-text-id="{text_id}" data-title="{html_mod.escape(item.get('file', ''))}">查看原始txt</button>
            <pre id="{text_id}" class="txt-hidden">{html_mod.escape(file_content)}</pre>
        """ if file_content else f"<div class=\"activity-file\">{html_mod.escape(item.get('file', ''))}</div>"
        cards.append(
            f"""
            <article class="activity">
                <div class="activity-top">
                    <div class="pill">{html_mod.escape(item.get('timestamp', ''))}</div>
                    <div class="activity-doctor">{html_mod.escape(item.get('doctor', ''))}</div>
                </div>
                {file_block}
                {content_block}
            </article>
            """
        )
    return "<div class='activity-grid'>" + "".join(cards) + "</div>"

def _render_charts(images):
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
                <img class="zoomable" src="{src}" alt="{title}" loading="lazy" />
            </section>
            """
        )
    return "<div class='chart-grid'>" + "".join(cards) + "</div>"

def _render_summary(table):
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
                <div class="mini-label">{html_mod.escape(label)}</div>
                <div class="mini-value">{html_mod.escape(value)}</div>
            </div>
            """
        )
    return "<div class='mini-grid'>" + "".join(cards) + "</div>"

def generate_dashboard_html(md_path: Path, output: Path):
    """从增强版Markdown生成单文件HTML看板"""
    md_text = _read_text(md_path)
    generation_time = _extract_generation_time(md_text)
    data = {
        "summary": _extract_table(md_text, "## 📊 总体统计"),
        "daily": _extract_table(md_text, "## 📅 按日分布统计"),
        "cumulative_doctors": _extract_table(md_text, "## 👥 累积参与医生数量统计"),
        "doctor_usage": _extract_table(md_text, "## 👨‍⚕️ 医生使用统计"),
        "doc_types": _extract_table(md_text, "## 📄 文档类型统计"),
    }
    image_dir = md_path.parent
    images = {
        "daily_logs": _encode_image(image_dir / "daily_logs.png"),
        "doctor_usage": _encode_image(image_dir / "doctor_usage.png"),
        "doc_types": _encode_image(image_dir / "doc_types.png"),
        "time_trend": _encode_image(image_dir / "time_trend.png"),
        "cumulative_doctors": _encode_image(image_dir / "cumulative_doctors.png"),
        "hourly_request_distribution": _encode_image(image_dir / "hourly_request_distribution.png"),
    }
    recent = _extract_recent_commands(md_text)
    for item in recent:
        href = item.get("file_href", "")
        if href:
            item["file_content"] = _read_relative_text(md_path, href)

    summary = data.get("summary", {"rows": []})
    lookup = {row[0]: row[1] for row in summary.get("rows", []) if len(row) >= 2}
    total_logs = lookup.get("日志总数", "-")
    doctors = lookup.get("涉及医生数", "-")
    days = lookup.get("统计天数", "-")
    doc_types_count = lookup.get("文档类型数", "-")

    html_body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
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
.chart-card img {{ width: 100%; border-radius: 10px; border: 1px solid var(--border); background: #f8fafc; cursor: zoom-in; }}

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
.activity pre {{ margin: 6px 0 0; padding: 10px; border-radius: 10px; background: #0f172a; color: #e5edff; font-size: 13px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }}
.txt-trigger {{ margin-top: 6px; border: 1px solid var(--border); background: #eef2ff; color: #4338ca; border-radius: 10px; padding: 6px 10px; cursor: pointer; font-weight: 600; font-size: 12px; }}
.txt-trigger:hover {{ background: #e0e7ff; }}
.txt-hidden {{ display: none; }}

.lightbox {{
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.55);
  display: none;
  align-items: center;
  justify-content: center;
  padding: 18px;
  z-index: 9999;
}}
.lightbox.active {{ display: flex; }}
.lightbox img {{
  max-width: 90vw;
  max-height: 90vh;
  border-radius: 16px;
  box-shadow: 0 18px 60px rgba(0,0,0,0.35);
  background: #fff;
}}
.lightbox .close {{
  position: fixed;
  top: 18px;
  right: 22px;
  color: #fff;
  font-size: 20px;
  cursor: pointer;
  padding: 6px 10px;
  background: rgba(0,0,0,0.45);
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.25);
}}
.text-modal {{
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  display: none;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 9999;
}}
.text-modal.active {{ display: flex; }}
.text-box {{
  width: min(1100px, 95vw);
  max-height: 88vh;
  background: #0f172a;
  color: #e5edff;
  border-radius: 16px;
  box-shadow: 0 18px 60px rgba(0,0,0,0.45);
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255,255,255,0.1);
}}
.text-box-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
  font-weight: 700;
}}
.text-box-close {{
  background: transparent;
  border: none;
  color: #fff;
  font-size: 20px;
  cursor: pointer;
}}
.text-box pre {{
  margin: 0;
  padding: 16px;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: auto;
  font-size: 14px;
  line-height: 1.6;
}}

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
        <div class="meta">生成时间 {html_mod.escape(generation_time)} · 数据源 {html_mod.escape(str(md_path))}</div>
        <h1>医疗日志分析看板</h1>
        <div class="meta">覆盖 {html_mod.escape(days)} 天 · {html_mod.escape(doctors)} 位医生 · {html_mod.escape(doc_types_count)} 种文档类型</div>
      </div>
      <div class="tagline">累计日志 {html_mod.escape(total_logs)} 条</div>
    </section>

    <section class="card" aria-label="总体统计">
      <div class="card-title-row"><h3>总体统计</h3></div>
      {_render_summary(summary)}
    </section>

    {_render_charts(images)}

    <div class="grid-2">
      {_render_table_card("按日分布统计", data.get('daily', {}), "daily-table", "可在滚动区域查看全部分布")}
      {_render_table_card("累积参与医生数量", data.get('cumulative_doctors', {}), "cumulative-table")}
    </div>

    <div class="grid-2">
      {_render_table_card("医生使用统计", data.get('doctor_usage', {}), "doctor-usage-table", "右上角搜索框支持过滤", searchable=True)}
      {_render_table_card("文档类型统计", data.get('doc_types', {}), "doc-types-table")}
    </div>

    <section class="card" aria-label="最近 CommandInfo 记录">
      <div class="card-title-row"><h3>最近 CommandInfo 记录</h3></div>
      {_render_recent(recent)}
    </section>
  </div>

  <div class="lightbox" id="lightbox">
    <span class="close" id="lightbox-close">×</span>
    <img src="" alt="放大图" id="lightbox-img" />
  </div>
  <div class="text-modal" id="text-modal">
    <div class="text-box">
      <div class="text-box-header">
        <div id="text-modal-title">原始txt</div>
        <button class="text-box-close" id="text-modal-close">×</button>
      </div>
      <pre id="text-modal-content"></pre>
    </div>
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

const lightbox = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightbox-img');
const closeBtn = document.getElementById('lightbox-close');

function openLightbox(src, alt) {{
  lightboxImg.src = src;
  lightboxImg.alt = alt || '放大图';
  lightbox.classList.add('active');
}}

document.querySelectorAll('.chart-card img.zoomable').forEach(img => {{
  img.addEventListener('click', () => openLightbox(img.src, img.alt));
}});

closeBtn.addEventListener('click', () => lightbox.classList.remove('active'));
lightbox.addEventListener('click', (e) => {{
  if (e.target === lightbox) lightbox.classList.remove('active');
}});
document.addEventListener('keyup', (e) => {{
  if (e.key === 'Escape') lightbox.classList.remove('active');
}});

// Text modal
const textModal = document.getElementById('text-modal');
const textContent = document.getElementById('text-modal-content');
const textTitle = document.getElementById('text-modal-title');
const textClose = document.getElementById('text-modal-close');

document.querySelectorAll('.txt-trigger').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const id = btn.dataset.textId;
    const title = btn.dataset.title || '原始txt';
    const src = document.getElementById(id);
    if (!src) return;
    textContent.textContent = src.textContent;
    textTitle.textContent = title;
    textModal.classList.add('active');
  }});
}});

textClose.addEventListener('click', () => textModal.classList.remove('active'));
textModal.addEventListener('click', (e) => {{
  if (e.target === textModal) textModal.classList.remove('active');
}});
document.addEventListener('keyup', (e) => {{
  if (e.key === 'Escape') textModal.classList.remove('active');
}});
</script>
</body>
</html>"""

    output.write_text(html_body, encoding="utf-8")
    print(f"HTML看板已生成: {output}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='医疗日志分析报告生成器')
    parser.add_argument('--tidy', action='store_true', help='执行tidy.py脚本')
    args = parser.parse_args()
    
    print("医疗日志分析报告生成器")
    print("=" * 50)
    
    # 1. 根据参数决定是否执行tidy.py
    if args.tidy:
        run_tidy()
    else:
        print("跳过tidy.py执行（使用--tidy参数启用）")
    
    # 2. 加载数据
    print("\n正在加载archive目录中的数据...")
    data = load_archive_data()
    
    if not data:
        print("未找到任何有效的日志数据")
        return
    
    print(f"成功加载 {len(data)} 条日志记录")
    
    # 3. 分析数据
    analysis_result = analyze_logs(data)
    
    # 4. 生成图表
    chart_data = generate_charts(analysis_result)
    
    # 5. 生成病历请求时间分布报表
    hourly_report_data = generate_hourly_request_chart(data)
    
    # 6. 生成报告
    generate_report(analysis_result)
    
    # 7. 生成增强版Markdown报告
    charts_dir = Path('charts')
    generate_enhanced_markdown_report(analysis_result, charts_dir)

    # 8. 生成单页HTML看板（内联图表，可点击放大）
    md_path = charts_dir / 'enhanced_medical_report.md'
    html_output = Path('medical_dashboard.html')
    generate_dashboard_html(md_path, html_output)
    
    print("\n=== 分析完成 ===")
    print("生成的文件:")
    print("- charts/medical_report.md (详细报告)")
    print("- charts/ 目录 (图表文件)")
    print("  - daily_logs.png (按日分布)")
    print("  - doctor_usage.png (医生使用统计)")
    print("  - doc_types.png (文档类型统计)")
    print("  - time_trend.png (时间趋势)")
    print("  - cumulative_doctors.png (累积医生数量趋势)")
    print("  - hourly_request_distribution.png (病历请求时间分布)")
    print("  - enhanced_medical_report.md (增强版Markdown报告，嵌入图表)")
    print("- medical_dashboard.html (单文件HTML看板，可直接双击打开)")

if __name__ == '__main__':
    main()
