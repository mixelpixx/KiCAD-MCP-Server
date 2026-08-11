<#
.SYNOPSIS
    Build and validate KiCad MCP, then write a local MCP configuration example.

.DESCRIPTION
    Requires KiCad 9+, Python bindings that can import pcbnew, and Node.js 20+.
    Python dependencies are installed from requirements-lock.txt into the
    server's private runtime; KiCad's bundled Python installation is not modified.
#>

param(
    [switch]$SkipBuild,
    [ValidateSet('claude-desktop', 'cline', 'manual')]
    [string]$ClientType = 'claude-desktop'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Write-Success { param([string]$Message) Write-Host "[OK] $Message" -ForegroundColor Green }
function Write-Error-Custom { param([string]$Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }
function Write-Warning-Custom { param([string]$Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Info { param([string]$Message) Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Write-Step { param([string]$Message) Write-Host "`n=== $Message ===" -ForegroundColor Magenta }

function Find-KiCadPython {
    $roots = @(
        'C:\Program Files\KiCad',
        'C:\Program Files (x86)\KiCad',
        (Join-Path $env:LOCALAPPDATA 'Programs\KiCad')
    )

    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        $versions = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\d+(?:\.\d+)*$' } |
            Sort-Object { [version]$_.Name } -Descending
        foreach ($version in $versions) {
            foreach ($name in @('python.exe', 'Python.exe')) {
                $candidate = Join-Path $version.FullName "bin\$name"
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    return [ordered]@{
                        Root = $version.FullName
                        Version = $version.Name
                        Python = $candidate
                    }
                }
            }
        }
    }
    return $null
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distCli = Join-Path $projectRoot 'dist\cli.js'
$requirementsLock = Join-Path $projectRoot 'requirements-lock.txt'
$configPath = Join-Path $projectRoot 'windows-mcp-config.json'
$results = [ordered]@{
    KiCadFound = $false
    PcbnewImport = $false
    NodeFound = $false
    NpmInstall = $false
    ProjectBuilt = $false
    RuntimeReady = $false
    ConfigGenerated = $false
    Errors = @()
}

Write-Step '1/7: Detecting KiCad and pcbnew'
$kicad = Find-KiCadPython
if (-not $kicad) {
    Write-Error-Custom 'KiCad Python was not found. Install KiCad 9 or newer.'
    $results.Errors += 'KiCad Python not found'
} else {
    $results.KiCadFound = $true
    Write-Success "Found KiCad $($kicad.Version) at $($kicad.Root)"
    $pcbnewOutput = & $kicad.Python -c "import pcbnew; print(pcbnew.GetBuildVersion())" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $results.PcbnewImport = $true
        Write-Success "pcbnew imported successfully: $pcbnewOutput"
    } else {
        Write-Error-Custom "KiCad Python cannot import pcbnew: $pcbnewOutput"
        $results.Errors += 'pcbnew import failed'
    }
}

Write-Step '2/7: Checking Node.js 20+'
try {
    $nodeVersion = node --version 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'node command failed' }
    $nodeMajor = [int]($nodeVersion -replace '^v(\d+)\..*$', '$1')
    if ($nodeMajor -lt 20) {
        throw "Node.js 20+ is required; found $nodeVersion"
    }
    $nodePath = (Get-Command node -ErrorAction Stop).Source
    $results.NodeFound = $true
    Write-Success "Node.js found: $nodeVersion"
} catch {
    Write-Error-Custom $_.Exception.Message
    $results.Errors += 'Node.js 20+ not available'
}

Write-Step '3/7: Checking pinned Python dependency lock'
if (Test-Path -LiteralPath $requirementsLock -PathType Leaf) {
    Write-Success "Found requirements-lock.txt"
} else {
    Write-Error-Custom "Pinned dependency lock not found: $requirementsLock"
    $results.Errors += 'requirements-lock.txt not found'
}

Write-Step '4/7: Installing locked Node.js dependencies'
if ($results.NodeFound) {
    Push-Location $projectRoot
    try {
        & npm ci
        if ($LASTEXITCODE -eq 0) {
            $results.NpmInstall = $true
            Write-Success 'npm ci completed.'
        } else {
            Write-Error-Custom 'npm ci failed.'
            $results.Errors += 'npm ci failed'
        }
    } finally {
        Pop-Location
    }
}

Write-Step '5/7: Building the TypeScript CLI'
if ($SkipBuild) {
    Write-Info 'Build skipped by request; validating the existing artifact.'
} elseif ($results.NodeFound -and $results.NpmInstall) {
    Push-Location $projectRoot
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            Write-Error-Custom 'TypeScript build failed.'
            $results.Errors += 'TypeScript build failed'
        }
    } finally {
        Pop-Location
    }
}
if (Test-Path -LiteralPath $distCli -PathType Leaf) {
    $results.ProjectBuilt = $true
    Write-Success "Found CLI entrypoint: $distCli"
} else {
    Write-Error-Custom "CLI entrypoint is missing: $distCli"
    $results.Errors += 'dist/cli.js missing'
}

Write-Step '6/7: Preparing and validating the private Python runtime'
if ($results.NodeFound -and $results.ProjectBuilt -and $results.PcbnewImport -and (Test-Path -LiteralPath $requirementsLock)) {
    $env:KICAD_PYTHON = $kicad.Python
    & $nodePath $distCli setup
    if ($LASTEXITCODE -eq 0) {
        $doctorText = (& $nodePath $distCli doctor 2>&1 | Out-String).Trim()
        try {
            $doctor = $doctorText | ConvertFrom-Json
            if ($doctor.runtimeHealthy -eq $true) {
                $results.RuntimeReady = $true
                Write-Success 'Private Python runtime is healthy.'
            } else {
                throw "doctor reported an unhealthy runtime: $doctorText"
            }
        } catch {
            Write-Error-Custom "Runtime validation failed: $($_.Exception.Message)"
            $results.Errors += 'Private Python runtime validation failed'
        }
    } else {
        Write-Error-Custom 'Private Python runtime setup failed.'
        $results.Errors += 'Private Python runtime setup failed'
    }
} else {
    Write-Error-Custom 'Runtime setup skipped because a prerequisite failed.'
    $results.Errors += 'Private Python runtime setup skipped'
}

Write-Step '7/7: Generating MCP client configuration'
if ($results.RuntimeReady) {
    $server = [ordered]@{
        command = $nodePath
        args = @($distCli, 'serve')
        env = [ordered]@{
            KICAD_PYTHON = $kicad.Python
            NODE_ENV = 'production'
            KICAD_MCP_LOG_LEVEL = 'info'
        }
    }
    $config = [ordered]@{ mcpServers = [ordered]@{ kicad = $server } }
    $config | ConvertTo-Json -Depth 10 | Out-File -LiteralPath $configPath -Encoding UTF8
    $results.ConfigGenerated = $true
    Write-Success "Configuration generated: $configPath"
    Write-Host ($config | ConvertTo-Json -Depth 10) -ForegroundColor Gray

    switch ($ClientType) {
        'claude-desktop' { Write-Info "Merge it into $env:APPDATA\Claude\claude_desktop_config.json, then restart Claude Desktop." }
        'cline' { Write-Info 'Merge it into the Cline MCP settings, then restart VS Code.' }
        default { Write-Info 'Merge it into your MCP client configuration.' }
    }
}

Write-Step 'Setup summary'
Write-Host "  KiCad:          $(if ($results.KiCadFound) { '[OK]' } else { '[ERROR]' })"
Write-Host "  pcbnew:         $(if ($results.PcbnewImport) { '[OK]' } else { '[ERROR]' })"
Write-Host "  Node.js 20+:    $(if ($results.NodeFound) { '[OK]' } else { '[ERROR]' })"
Write-Host "  npm ci:         $(if ($results.NpmInstall) { '[OK]' } else { '[ERROR]' })"
Write-Host "  dist/cli.js:    $(if ($results.ProjectBuilt) { '[OK]' } else { '[ERROR]' })"
Write-Host "  Python runtime: $(if ($results.RuntimeReady) { '[OK]' } else { '[ERROR]' })"
Write-Host "  Configuration:  $(if ($results.ConfigGenerated) { '[OK]' } else { '[ERROR]' })"

$isSuccess = $results.KiCadFound -and
    $results.PcbnewImport -and
    $results.NodeFound -and
    $results.NpmInstall -and
    $results.ProjectBuilt -and
    $results.RuntimeReady -and
    $results.ConfigGenerated -and
    $results.Errors.Count -eq 0

if (-not $isSuccess) {
    Write-Host "`nSetup failed:" -ForegroundColor Red
    foreach ($item in $results.Errors) { Write-Host "  - $item" -ForegroundColor Red }
    exit 1
}

Write-Success 'KiCad MCP setup completed successfully.'
