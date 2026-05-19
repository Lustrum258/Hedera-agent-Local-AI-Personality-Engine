"""
batch_rename.py - 批量重命名工具
用法: python batch_rename.py <目录路径> [选项]

选项:
  --prefix <文本>     在文件名前加前缀
  --suffix <文本>     在文件名后加后缀（扩展名前）
  --replace <旧> <新>  替换文件名中的文本
  --number            按序号重命名: 001.ext, 002.ext ...
  --ext <扩展名>      只处理指定扩展名（如 .txt .jpg）
  --dry-run           预览模式，不实际执行
  --recursive         递归子目录
"""

import os
import sys
import re

def get_files(target_dir, ext_filter=None, recursive=False):
    if recursive:
        for root, dirs, files in os.walk(target_dir):
            for f in files:
                if ext_filter and not f.lower().endswith(ext_filter.lower()):
                    continue
                yield root, f
    else:
        for f in os.listdir(target_dir):
            full = os.path.join(target_dir, f)
            if os.path.isfile(full):
                if ext_filter and not f.lower().endswith(ext_filter.lower()):
                    continue
                yield target_dir, f

def dry_rename(src, dst):
    print(f"  [预览] {os.path.basename(src)} -> {os.path.basename(dst)}")

def do_rename(src, dst):
    os.rename(src, dst)
    print(f"  [已重命名] {os.path.basename(src)} -> {os.path.basename(dst)}")

def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        return

    target_dir = args[0]
    if not os.path.isdir(target_dir):
        print(f"错误: 目录不存在 - {target_dir}")
        sys.exit(1)

    prefix = None
    suffix = None
    replace_old = None
    replace_new = None
    numbering = False
    ext_filter = None
    dry_run = False
    recursive = False

    i = 1
    while i < len(args):
        a = args[i]
        if a == '--prefix' and i+1 < len(args):
            prefix = args[i+1]; i += 2
        elif a == '--suffix' and i+1 < len(args):
            suffix = args[i+1]; i += 2
        elif a == '--replace' and i+2 < len(args):
            replace_old = args[i+1]; replace_new = args[i+2]; i += 3
        elif a == '--number':
            numbering = True; i += 1
        elif a == '--ext' and i+1 < len(args):
            ext_filter = args[i+1]
            if not ext_filter.startswith('.'):
                ext_filter = '.' + ext_filter
            i += 2
        elif a == '--dry-run':
            dry_run = True; i += 1
        elif a == '--recursive':
            recursive = True; i += 1
        else:
            print(f"未知选项: {a}")
            print(__doc__)
            sys.exit(1)

    rename_fn = dry_rename if dry_run else do_rename
    files = list(get_files(target_dir, ext_filter, recursive))

    if not files:
        print("没有找到匹配的文件。")
        return

    print(f"找到 {len(files)} 个文件{'（预览模式）' if dry_run else ''}")
    print("-" * 50)

    counter = 0
    for root, fname in files:
        name, ext = os.path.splitext(fname)
        new_name = name

        if replace_old is not None:
            new_name = new_name.replace(replace_old, replace_new)

        if prefix:
            new_name = prefix + new_name

        if suffix:
            new_name = new_name + suffix

        if numbering:
            counter += 1
            new_name = f"{counter:03d}"

        new_fname = new_name + ext
        src = os.path.join(root, fname)
        dst = os.path.join(root, new_fname)

        if src == dst:
            continue

        rename_fn(src, dst)

    print("-" * 50)
    if dry_run:
        print("预览结束，去掉 --dry-run 执行实际重命名。")
    else:
        print("完成。")

if __name__ == '__main__':
    main()
