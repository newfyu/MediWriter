#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理脚本：
1. 将 query_save 中的所有内容移动到 archive 中
2. 分析 logs 中的文件，删除内容为空的文件
"""

import os
import shutil
from pathlib import Path

def move_query_save_to_archive():
    """将 query_save 中的所有内容移动到 archive 中"""
    query_save_dir = Path("query_save")
    archive_dir = Path("archive")
    
    # 检查 query_save 目录是否存在
    if not query_save_dir.exists():
        print(f"目录 {query_save_dir} 不存在，跳过移动操作")
        return
    
    # 创建 archive 目录（如果不存在）
    archive_dir.mkdir(exist_ok=True)
    print(f"确保 {archive_dir} 目录存在")
    
    # 移动所有文件和子目录
    moved_count = 0
    for item in query_save_dir.iterdir():
        destination = archive_dir / item.name
        
        # 如果目标已存在，添加时间戳后缀
        if destination.exists():
            import time
            timestamp = int(time.time())
            if item.is_file():
                stem = destination.stem
                suffix = destination.suffix
                destination = archive_dir / f"{stem}_{timestamp}{suffix}"
            else:
                destination = archive_dir / f"{destination.name}_{timestamp}"
        
        try:
            shutil.move(str(item), str(destination))
            print(f"已移动: {item} -> {destination}")
            moved_count += 1
        except Exception as e:
            print(f"移动失败 {item}: {e}")
    
    print(f"总共移动了 {moved_count} 个项目")
    print(f"保留 {query_save_dir} 目录")

def clean_empty_log_files():
    """分析 logs 中的文件，删除内容为空的文件"""
    logs_dir = Path("logs")
    
    # 检查 logs 目录是否存在
    if not logs_dir.exists():
        print(f"目录 {logs_dir} 不存在，跳过清理操作")
        return
    
    deleted_count = 0
    total_files = 0
    
    # 遍历 logs 目录中的所有文件
    for file_path in logs_dir.rglob("*"):
        if file_path.is_file():
            total_files += 1
            try:
                # 检查文件是否为空
                if file_path.stat().st_size == 0:
                    file_path.unlink()
                    print(f"已删除空文件: {file_path}")
                    deleted_count += 1
                else:
                    # 检查文件内容是否只包含空白字符
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read().strip()
                        if not content:
                            file_path.unlink()
                            print(f"已删除空内容文件: {file_path}")
                            deleted_count += 1
            except Exception as e:
                print(f"处理文件失败 {file_path}: {e}")
    
    print(f"在 {total_files} 个文件中删除了 {deleted_count} 个空文件")

def main():
    """主函数"""
    print("开始执行清理脚本...")
    print("="*50)
    
    print("\n1. 移动 query_save 内容到 archive:")
    move_query_save_to_archive()
    
    print("\n2. 清理 logs 中的空文件:")
    clean_empty_log_files()
    
    print("\n清理脚本执行完成！")
    print("="*50)

if __name__ == "__main__":
    main()