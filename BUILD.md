# Hedera Build Guide

## Prerequisites

1. Python 3.10+
2. Install build dependencies:
   ```
   pip install pyinstaller openpyxl
   ```
   Note: `requests` and `pyyaml` are already in project dependencies.

## Build Steps

### Method 1: Build EXE

Run `build_exe.bat` to automatically:

1. Check/install all dependencies
2. Collect static files and plugins
3. Package into single EXE
4. Output to `dist/Hedera.exe`

Output:
```
hedera/dist/
├── Hedera.exe        ← Main program
├── config.yaml       ← Config file (fill API Key on first use)
├── data/             ← Runtime data
└── plugins/          ← Plugin directory
```

### Method 2: Build Installer

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php)

1. Run `build_exe.bat` first
2. Open `installer.iss` in Inno Setup
3. Menu: Build → Compile
4. Output to `installer/Hedera_0.8.1_Setup.exe`

The installer provides:
- Custom install path
- Desktop shortcut
- Optional auto-start
- Firewall rules
- Uninstaller

## Usage

### Run after build
```
dist\Hedera.exe serve
```

### First use
```
dist\Hedera.exe init    # Initialize workspace
# Edit config.yaml with your API Key
dist\Hedera.exe serve   # Start server
```

Visit `http://localhost:36313` to chat.

## Build Info

| Item | Value |
|------|-------|
| Version | 0.8.1 |
| Python | 3.10+ |
| Packager | PyInstaller 6.x |
| Single file size | ~30-50 MB |
| Dependencies | openpyxl, requests, pyyaml |
