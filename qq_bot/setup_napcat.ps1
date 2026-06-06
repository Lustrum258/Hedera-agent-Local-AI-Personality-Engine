# NapCat 自动下载和配置脚本
# 需要以管理员权限运行 PowerShell

Write-Host "=== NapCat 安装配置脚本 ===" -ForegroundColor Cyan
Write-Host ""

# 检查是否安装了QQ
$qqPath = Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue | 
    Where-Object { $_.DisplayName -like "*QQ*" } | 
    Select-Object -First 1 -ExpandProperty InstallLocation

if (-not $qqPath) {
    $qqPath = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue | 
        Where-Object { $_.DisplayName -like "*QQ*" } | 
        Select-Object -First 1 -ExpandProperty InstallLocation
}

if (-not $qqPath) {
    Write-Host "[警告] 未检测到QQ安装路径，请确保已安装QQ" -ForegroundColor Yellow
    Write-Host "NapCat需要配合QQ使用，推荐QQ 9.9.12-27556版本" -ForegroundColor Yellow
    Write-Host ""
}

# 创建NapCat目录
$napcatDir = "$PSScriptRoot\NapCat"
if (-not (Test-Path $napcatDir)) {
    New-Item -ItemType Directory -Path $napcatDir -Force | Out-Null
}

Write-Host "[1/3] 下载NapCat Shell版本..." -ForegroundColor Green
Write-Host ""

# 获取最新release信息
try {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest" -Method Get
    $version = $release.tag_name
    Write-Host "最新版本: $version" -ForegroundColor Cyan
    
    # 找到Windows Shell版本的下载链接
    $asset = $release.assets | Where-Object { $_.name -like "*Shell*win*" -or $_.name -like "*win*Shell*" } | Select-Object -First 1
    
    if (-not $asset) {
        $asset = $release.assets | Where-Object { $_.name -like "*Shell*" } | Select-Object -First 1
    }
    
    if ($asset) {
        $downloadUrl = $asset.browser_download_url
        $fileName = $asset.name
        Write-Host "下载文件: $fileName" -ForegroundColor Cyan
        Write-Host "下载地址: $downloadUrl" -ForegroundColor Gray
        Write-Host ""
        Write-Host "请手动下载以下文件到 $napcatDir 目录:" -ForegroundColor Yellow
        Write-Host $downloadUrl -ForegroundColor White
        Write-Host ""
        
        # 尝试使用浏览器打开下载页面
        Start-Process "https://github.com/NapNeko/NapCatQQ/releases/latest"
    }
} catch {
    Write-Host "获取版本信息失败，请手动下载" -ForegroundColor Yellow
    Write-Host "下载地址: https://github.com/NapNeko/NapCatQQ/releases" -ForegroundColor White
    Start-Process "https://github.com/NapNeko/NapCatQQ/releases"
}

Write-Host "[2/3] 创建配置文件..." -ForegroundColor Green

# 创建onebot11配置文件
$config = @{
    network = @{
        websocketServers = @(
            @{
                name = "ws-server"
                enable = $true
                host = "0.0.0.0"
                port = 6700
                messagePostFormat = "array"
                reportSelfMessage = $false
                token = ""
                debug = $false
            }
        )
        httpServers = @()
        httpClients = @()
        websocketClients = @()
    }
}

$configJson = $config | ConvertTo-Json -Depth 10
$configPath = "$napcatDir\config\onebot11.json"
$configDir = "$napcatDir\config"

if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

# 备注信息
$configComment = @"
# NapCat OneBot11 配置文件
# websocketServers: WebSocket服务器配置
# - port 6700: 供NoneBot2连接
# - host 0.0.0.0: 监听所有网卡
#
# 下载NapCat后，解压到此目录，然后运行 launcher.bat
# 登录后访问 http://localhost:6099 进行WebUI配置
"@

Write-Host "配置文件将保存到: $configPath" -ForegroundColor Cyan
Write-Host ""

Write-Host "[3/3] 创建启动脚本..." -ForegroundColor Green

# 创建启动脚本
$startScript = @'
@echo off
chcp 65001 >nul
echo ====================================
echo   NapCat QQ协议端 启动脚本
echo ====================================
echo.

:: 检查NapCat目录
if not exist "NapCat\launcher.bat" (
    echo [错误] 未找到NapCat，请先下载并解压到 NapCat 目录
    echo 下载地址: https://github.com/NapNeko/NapCatQQ/releases
    echo.
    echo 请选择 NapCat.Shell.zip 版本下载
    pause
    exit /b 1
)

echo [信息] 正在启动NapCat...
echo [信息] 首次启动需要扫码登录QQ
echo [信息] 登录后请访问 http://localhost:6099 配置网络
echo.
echo [重要] 在WebUI中配置WebSocket服务器:
echo   1. 点击左侧"网络配置"
echo   2. 添加 WebSocket 服务器
echo   3. 端口设置为: 6700
echo   4. 保存并重启
echo.

cd NapCat
call launcher.bat
pause
'@

$startScript | Out-File -FilePath "$PSScriptRoot\start_napcat.bat" -Encoding ASCII

Write-Host "启动脚本已创建: start_napcat.bat" -ForegroundColor Green
Write-Host ""

Write-Host "=== 安装说明 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. 下载NapCat:" -ForegroundColor White
Write-Host "   - 访问 https://github.com/NapNeko/NapCatQQ/releases" -ForegroundColor Gray
Write-Host "   - 下载 NapCat.Shell.zip" -ForegroundColor Gray
Write-Host "   - 解压到 qq_bot\NapCat 目录" -ForegroundColor Gray
Write-Host ""
Write-Host "2. 启动NapCat:" -ForegroundColor White
Write-Host "   - 运行 start_napcat.bat" -ForegroundColor Gray
Write-Host "   - 扫码登录QQ" -ForegroundColor Gray
Write-Host ""
Write-Host "3. 配置WebSocket:" -ForegroundColor White
Write-Host "   - 访问 http://localhost:6099" -ForegroundColor Gray
Write-Host "   - 网络配置 -> 添加WebSocket服务器" -ForegroundColor Gray
Write-Host "   - 端口: 6700" -ForegroundColor Gray
Write-Host ""
Write-Host "4. 启动NoneBot2:" -ForegroundColor White
Write-Host "   - 运行 start_bot.bat" -ForegroundColor Gray
Write-Host ""

Write-Host "按任意键退出..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")