# Hedera 独立版构建指南

## 前置条件

1. Python 3.10+（已装: `D:\Conda\python.exe`）
2. 安装构建依赖：
   ```
   pip install pyinstaller openpyxl
   ```
   注: requests 和 pyyaml 已在项目依赖中会自动装

## 构建步骤

### 方法一：一键构建 EXE

双击 `build_exe.bat`，自动完成：
1. 检查/安装所有依赖
2. 收集静态文件和插件
3. 打包为单个 EXE 文件
4. 输出到 `dist/Hedera.exe`

产出：
```
hedera/dist/
├── Hedera.exe        ← 主程序（双击或命令行）
├── config.yaml       ← 配置文件（首次需填 API Key）
├── data/             ← 运行时数据（灵魂、记忆）
└── plugins/          ← 插件目录
```

### 方法二：构建安装包

需要额外安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)

1. 先运行 `build_exe.bat` 生成 `dist/` 目录
2. 双击 `installer.iss`（Inno Setup 会打开）
3. 菜单 Build → Compile
4. 输出到 `installer/Hedera_0.7.0_Setup.exe`

方法二产出的是标准的 Windows 安装程序：
- 选择安装路径
- 创建桌面快捷方式
- 可选开机自启
- 自动添加防火墙规则
- 含卸载程序

## 使用方法

### 构建后直接运行
```
dist\Hedera.exe serve
```

### 首次使用
```
dist\Hedera.exe init    # 初始化工作目录
# 编辑 config.yaml 填入 DeepSeek API Key
dist\Hedera.exe serve   # 启动服务
```

访问 `http://localhost:36313` 即可聊天。

## 构建信息

| 项目 | 值 |
|------|-----|
| 版本 | 0.7.0 |
| Python | 3.10+ |
| 打包工具 | PyInstaller 6.x |
| 单文件大小 | ~30-50 MB |
| 依赖 | openpyxl, requests, pyyaml |
