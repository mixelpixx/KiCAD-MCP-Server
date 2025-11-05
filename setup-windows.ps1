<#
.SYNOPSIS
    KiCAD MCP Server - Windows Setup and Configuration Script

.DESCRIPTION
    This script automates the setup of KiCAD MCP Server on Windows by:
    - Detecting KiCAD installation and version
    - Verifying Python and Node.js installations
    - Testing KiCAD Python module (pcbnew)
    - Installing required Python dependencies
    - Building the TypeScript project
    - Generating Claude Desktop configuration
    - Running diagnostic tests

.PARAMETER SkipBuild
    Skip the npm build step (useful if already built)

.PARAMETER ClientType
    Type of MCP client to configure: 'claude-desktop', 'cline', or 'manual'
    Default: 'claude-desktop'

.EXAMPLE
    .\setup-windows.ps1
    Run the full setup with default options

.EXAMPLE
    .\setup-windows.ps1 -ClientType cline
    Setup for Cline VSCode extension

.EXAMPLE
    .\setup-windows.ps1 -SkipBuild
    Run setup without rebuilding the project
#>

param(
    [switch]$SkipBuild,
    [ValidateSet('claude-desktop', 'cline', 'manual')]
    [string]$ClientType = 'claude-desktop'
)

# Color output helpers
function Write-Success { param([string]$Message) Write-Host "✓ $Message" -ForegroundColor Green }
function Write-Error-Custom { param([string]$Message) Write-Host "✗ $Message" -ForegroundColor Red }
function Write-Warning-Custom { param([string]$Message) Write-Host "⚠ $Message" -ForegroundColor Yellow }
function Write-Info { param([string]$Message) Write-Host "→ $Message" -ForegroundColor Cyan }
function Write-Step { param([string]$Message) Write-Host "`n=== $Message ===" -ForegroundColor Magenta }

Write-Host @"
╔════════════════════════════════════════════════════════════╗
║         KiCAD MCP Server - Windows Setup Script           ║
║                                                            ║
║  This script will configure KiCAD MCP for Windows         ║
╚════════════════════════════════════════════════════════════╝
"@ -ForegroundColor Cyan

# Store results for final report
$script:Results = @{
    KiCADFound = $false
    KiCADVersion = ""
    KiCADPythonPath = ""
    PythonFound = $false
    PythonVersion = ""
    NodeFound = $false
    NodeVersion = ""
    PcbnewImport = $false
    DependenciesInstalled = $false
    ProjectBuilt = $false
    ConfigGenerated = $false
    Errors = @()
}

# Get script directory (project root)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Step "Step 1: Detecting KiCAD Installation"

# Function to find KiCAD installation
function Find-KiCAD {
    $possiblePaths = @(
        "C:\Program Files\KiCad",
        "C:\Program Files (x86)\KiCad"
    )

    $versions = @("9.0", "9.1", "10.0", "8.0")

    foreach ($basePath in $possiblePaths) {
        foreach ($version in $versions) {
            $kicadPath = Join-Path $basePath $version
            $pythonExe = Join-Path $kicadPath "bin\python.exe"
            $pythonLib = Join-Path $kicadPath "lib\python3\dist-packages"

            if (Test-Path $pythonExe) {
                Write-Success "Found KiCAD $version at: $kicadPath"
                return @{
                    Path = $kicadPath
                    Version = $version
                    PythonExe = $pythonExe
                    PythonLib = $pythonLib
                }
            }
        }
    }

    return $null
}

$kicad = Find-KiCAD

if ($kicad) {
    $script:Results.KiCADFound = $true
    $script:Results.KiCADVersion = $kicad.Version
    $script:Results.KiCADPythonPath = $kicad.PythonLib
    Write-Info "KiCAD Version: $($kicad.Version)"
    Write-Info "Python Path: $($kicad.PythonLib)"
} else {
    Write-Error-Custom "KiCAD not found in standard locations"
    Write-Warning-Custom "Please install KiCAD 9.0+ from https://www.kicad.org/download/windows/"
    $script:Results.Errors += "KiCAD not found"
}

Write-Step "Step 2: Checking Node.js Installation"

try {
    $nodeVersion = node --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Node.js found: $nodeVersion"
        $script:Results.NodeFound = $true
        $script:Results.NodeVersion = $nodeVersion

        # Check if version is 18+
        $versionNumber = [int]($nodeVersion -replace 'v(\d+)\..*', '$1')
        if ($versionNumber -lt 18) {
            Write-Warning-Custom "Node.js version 18+ is recommended (you have $nodeVersion)"
        }
    }
} catch {
    Write-Error-Custom "Node.js not found"
    Write-Warning-Custom "Please install Node.js 18+ from https://nodejs.org/"
    $script:Results.Errors += "Node.js not found"
}

Write-Step "Step 3: Testing KiCAD Python Module"

if ($kicad) {
    Write-Info "Testing pcbnew module import..."

    $testScript = "import sys; import pcbnew; print(f'SUCCESS:{pcbnew.GetBuildVersion()}')"
    $result = & $kicad.PythonExe -c $testScript 2>&1

    if ($result -match "SUCCESS:(.+)") {
        $pcbnewVersion = $matches[1]
        Write-Success "pcbnew module imported successfully: $pcbnewVersion"
        $script:Results.PcbnewImport = $true
    } else {
        Write-Error-Custom "Failed to import pcbnew module"
        Write-Warning-Custom "Error: $result"
        Write-Info "This usually means KiCAD was not installed with Python support"
        $script:Results.Errors += "pcbnew import failed: $result"
    }
} else {
    Write-Warning-Custom "Skipping pcbnew test (KiCAD not found)"
}

Write-Step "Step 4: Checking Python Installation"

try {
    $pythonVersion = python --version 2>&1
    if ($pythonVersion -match "Python (\d+\.\d+\.\d+)") {
        Write-Success "System Python found: $pythonVersion"
        $script:Results.PythonFound = $true
        $script:Results.PythonVersion = $pythonVersion
    }
} catch {
    Write-Warning-Custom "System Python not found (using KiCAD's Python)"
}

Write-Step "Step 5: Installing Node.js Dependencies"

if ($script:Results.NodeFound) {
    Write-Info "Running npm install..."
    Push-Location $ProjectRoot
    try {
        npm install 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Node.js dependencies installed"
        } else {
            Write-Error-Custom "npm install failed"
            $script:Results.Errors += "npm install failed"
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Warning-Custom "Skipping npm install (Node.js not found)"
}

Write-Step "Step 6: Installing Python Dependencies"

if ($kicad) {
    Write-Info "Installing Python packages..."
    Push-Location $ProjectRoot
    try {
        $requirementsFile = Join-Path $ProjectRoot "requirements.txt"
        if (Test-Path $requirementsFile) {
            & $kicad.PythonExe -m pip install -r $requirementsFile 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Python dependencies installed"
                $script:Results.DependenciesInstalled = $true
            } else {
                Write-Warning-Custom "Some Python packages may have failed to install"
            }
        } else {
            Write-Warning-Custom "requirements.txt not found"
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Warning-Custom "Skipping Python dependencies (KiCAD Python not found)"
}

Write-Step "Step 7: Building TypeScript Project"

if (-not $SkipBuild -and $script:Results.NodeFound) {
    Write-Info "Running npm run build..."
    Push-Location $ProjectRoot
    try {
        npm run build 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $distPath = Join-Path $ProjectRoot "dist\index.js"
            if (Test-Path $distPath) {
                Write-Success "Project built successfully"
                $script:Results.ProjectBuilt = $true
            } else {
                Write-Error-Custom "Build completed but dist/index.js not found"
                $script:Results.Errors += "Build output missing"
            }
        } else {
            Write-Error-Custom "Build failed"
            $script:Results.Errors += "TypeScript build failed"
        }
    } finally {
        Pop-Location
    }
} else {
    if ($SkipBuild) {
        Write-Info "Skipping build (--SkipBuild specified)"
    } else {
        Write-Warning-Custom "Skipping build (Node.js not found)"
    }
}

Write-Step "Step 8: Generating Configuration"

if ($kicad -and $script:Results.ProjectBuilt) {
    $distPath = Join-Path $ProjectRoot "dist\index.js"
    $distPathEscaped = $distPath -replace '\\', '\\'
    $pythonLibEscaped = $kicad.PythonLib -replace '\\', '\\'

    $config = @"
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["$distPathEscaped"],
      "env": {
        "PYTHONPATH": "$pythonLibEscaped",
        "NODE_ENV": "production",
        "LOG_LEVEL": "info"
      }
    }
  }
}
"@

    $configPath = Join-Path $ProjectRoot "windows-mcp-config.json"
    $config | Out-File -FilePath $configPath -Encoding UTF8
    Write-Success "Configuration generated: $configPath"
    $script:Results.ConfigGenerated = $true

    Write-Info "`nConfiguration Preview:"
    Write-Host $config -ForegroundColor Gray

    # Provide instructions based on client type
    Write-Info "`nTo use this configuration:"

    if ($ClientType -eq 'claude-desktop') {
        $claudeConfigPath = "$env:APPDATA\Claude\claude_desktop_config.json"
        Write-Host "`n1. Open Claude Desktop configuration:" -ForegroundColor Yellow
        Write-Host "   $claudeConfigPath" -ForegroundColor White
        Write-Host "`n2. Copy the contents from:" -ForegroundColor Yellow
        Write-Host "   $configPath" -ForegroundColor White
        Write-Host "`n3. Restart Claude Desktop" -ForegroundColor Yellow
    } elseif ($ClientType -eq 'cline') {
        $clineConfigPath = "$env:APPDATA\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json"
        Write-Host "`n1. Open Cline configuration:" -ForegroundColor Yellow
        Write-Host "   $clineConfigPath" -ForegroundColor White
        Write-Host "`n2. Copy the contents from:" -ForegroundColor Yellow
        Write-Host "   $configPath" -ForegroundColor White
        Write-Host "`n3. Restart VSCode" -ForegroundColor Yellow
    } else {
        Write-Host "`n1. Configuration saved to:" -ForegroundColor Yellow
        Write-Host "   $configPath" -ForegroundColor White
        Write-Host "`n2. Copy to your MCP client configuration" -ForegroundColor Yellow
    }

} else {
    Write-Warning-Custom "Skipping configuration generation (prerequisites not met)"
}

Write-Step "Step 9: Running Diagnostic Test"

if ($kicad -and $script:Results.ProjectBuilt) {
    Write-Info "Testing server startup..."

    $env:PYTHONPATH = $kicad.PythonLib
    $distPath = Join-Path $ProjectRoot "dist\index.js"

    # Start the server process
    $process = Start-Process -FilePath "node" `
                            -ArgumentList $distPath `
                            -NoNewWindow `
                            -PassThru `
                            -RedirectStandardError (Join-Path $env:TEMP "kicad-mcp-test-error.txt") `
                            -RedirectStandardOutput (Join-Path $env:TEMP "kicad-mcp-test-output.txt")

    # Wait a moment for startup
    Start-Sleep -Seconds 2

    if (-not $process.HasExited) {
        Write-Success "Server started successfully (PID: $($process.Id))"
        Write-Info "Stopping test server..."
        Stop-Process -Id $process.Id -Force
    } else {
        Write-Error-Custom "Server exited immediately (exit code: $($process.ExitCode))"

        $errorLog = Join-Path $env:TEMP "kicad-mcp-test-error.txt"
        if (Test-Path $errorLog) {
            $errorContent = Get-Content $errorLog -Raw
            if ($errorContent) {
                Write-Warning-Custom "Error output:"
                Write-Host $errorContent -ForegroundColor Red
            }
        }

        $script:Results.Errors += "Server startup test failed"
    }
} else {
    Write-Warning-Custom "Skipping diagnostic test (prerequisites not met)"
}

# Final Report
Write-Step "Setup Summary"

Write-Host "`nComponent Status:" -ForegroundColor Cyan
Write-Host "  KiCAD Installation:     $(if ($script:Results.KiCADFound) { '✓ Found' } else { '✗ Not Found' })" -ForegroundColor $(if ($script:Results.KiCADFound) { 'Green' } else { 'Red' })
if ($script:Results.KiCADVersion) {
    Write-Host "    Version:              $($script:Results.KiCADVersion)" -ForegroundColor Gray
}
Write-Host "  pcbnew Module:          $(if ($script:Results.PcbnewImport) { '✓ Working' } else { '✗ Failed' })" -ForegroundColor $(if ($script:Results.PcbnewImport) { 'Green' } else { 'Red' })
Write-Host "  Node.js:                $(if ($script:Results.NodeFound) { '✓ Found' } else { '✗ Not Found' })" -ForegroundColor $(if ($script:Results.NodeFound) { 'Green' } else { 'Red' })
if ($script:Results.NodeVersion) {
    Write-Host "    Version:              $($script:Results.NodeVersion)" -ForegroundColor Gray
}
Write-Host "  Python Dependencies:    $(if ($script:Results.DependenciesInstalled) { '✓ Installed' } else { '✗ Failed' })" -ForegroundColor $(if ($script:Results.DependenciesInstalled) { 'Green' } else { 'Red' })
Write-Host "  Project Build:          $(if ($script:Results.ProjectBuilt) { '✓ Success' } else { '✗ Failed' })" -ForegroundColor $(if ($script:Results.ProjectBuilt) { 'Green' } else { 'Red' })
Write-Host "  Configuration:          $(if ($script:Results.ConfigGenerated) { '✓ Generated' } else { '✗ Not Generated' })" -ForegroundColor $(if ($script:Results.ConfigGenerated) { 'Green' } else { 'Red' })

if ($script:Results.Errors.Count -gt 0) {
    Write-Host "`nErrors Encountered:" -ForegroundColor Red
    foreach ($error in $script:Results.Errors) {
        Write-Host "  • $error" -ForegroundColor Red
    }
}

# Check for log file
$logPath = "$env:USERPROFILE\.kicad-mcp\logs\kicad_interface.log"
if (Test-Path $logPath) {
    Write-Host "`nLog file location:" -ForegroundColor Cyan
    Write-Host "  $logPath" -ForegroundColor Gray
}

# Success criteria
$isSuccess = $script:Results.KiCADFound -and
             $script:Results.PcbnewImport -and
             $script:Results.NodeFound -and
             $script:Results.ProjectBuilt

if ($isSuccess) {
    Write-Host "`n╔════════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║  ✓ Setup completed successfully!                          ║" -ForegroundColor Green
    Write-Host "║                                                            ║" -ForegroundColor Green
    Write-Host "║  Next steps:                                               ║" -ForegroundColor Green
    Write-Host "║  1. Copy the generated config to your MCP client           ║" -ForegroundColor Green
    Write-Host "║  2. Restart your MCP client (Claude Desktop/Cline)         ║" -ForegroundColor Green
    Write-Host "║  3. Try: 'Create a new KiCAD project'                      ║" -ForegroundColor Green
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Green
} else {
    Write-Host "`n╔════════════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║  ✗ Setup incomplete - issues detected                      ║" -ForegroundColor Red
    Write-Host "║                                                            ║" -ForegroundColor Red
    Write-Host "║  Please resolve the errors above and run again             ║" -ForegroundColor Red
    Write-Host "║                                                            ║" -ForegroundColor Red
    Write-Host "║  For help:                                                 ║" -ForegroundColor Red
    Write-Host "║  https://github.com/mixelpixx/KiCAD-MCP-Server/issues      ║" -ForegroundColor Red
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Red
    exit 1
}
