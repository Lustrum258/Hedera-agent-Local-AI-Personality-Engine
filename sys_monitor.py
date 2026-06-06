"""系统监控小工具 - 一键查看CPU/内存/磁盘状态"""
import psutil
import time
import os
from datetime import datetime


def get_bar(percent, width=20):
    """生成进度条"""
    filled = int(width * percent / 100)
    bar = '█' * filled + '░' * (width - filled)
    return f'[{bar}] {percent:.1f}%'


def color(percent):
    """根据使用率返回颜色"""
    if percent < 60:
        return '\033[92m'  # 绿
    elif percent < 85:
        return '\033[93m'  # 黄
    return '\033[91m'  # 红


RESET = '\033[0m'


def show_status():
    os.system('cls' if os.name == 'nt' else 'clear')
    
    cpu_percent = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    print('=' * 50)
    print(f'  系统监控面板  |  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 50)
    print()
    
    # CPU
    c = color(cpu_percent)
    print(f'  CPU 使用率:   {c}{get_bar(cpu_percent)}{RESET}')
    print(f'  核心数:       {psutil.cpu_count()} 核')
    print()
    
    # 内存
    c = color(mem.percent)
    used_gb = mem.used / (1024**3)
    total_gb = mem.total / (1024**3)
    print(f'  内存使用:     {c}{get_bar(mem.percent)}{RESET}')
    print(f'  已用/总量:    {used_gb:.1f} GB / {total_gb:.1f} GB')
    print()
    
    # 磁盘
    c = color(disk.percent)
    used_gb = disk.used / (1024**3)
    total_gb = disk.total / (1024**3)
    print(f'  磁盘使用:     {c}{get_bar(disk.percent)}{RESET}')
    print(f'  已用/总量:    {used_gb:.1f} GB / {total_gb:.1f} GB')
    print()
    
    # 网络
    net = psutil.net_io_counters()
    print(f'  网络发送:     {net.bytes_sent / (1024**2):.1f} MB')
    print(f'  网络接收:     {net.bytes_recv / (1024**2):.1f} MB')
    print()
    
    # 进程数
    print(f'  运行进程数:   {len(psutil.pids())}')
    print('=' * 50)
    print('  按 Ctrl+C 退出')


if __name__ == '__main__':
    try:
        while True:
            show_status()
            time.sleep(2)
    except KeyboardInterrupt:
        print('\n已退出监控')
