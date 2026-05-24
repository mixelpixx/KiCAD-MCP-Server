<#
.SYNOPSIS
    KiCAD MCP Server - Windows OpenCode Configuration Script

.DESCRIPTION
    Verifies the local KiCAD MCP Server setup and creates or updates an
    OpenCode configuration with a local MCP server entry.

    The MCP server path and OpenCode project path are intentionally separate:
    - McpServerPath is this KiCAD MCP Server repository, where dist/index.js lives.
    - ProjectPath is the project that should receive opencode.json.

    The script writes OpenCode's config shape, not Claude Desktop's:
    - top-level key: mcp
    - server type: local
    - command: array containing executable and arguments
    - environment: object containing environment variables

.PARAMETER Apply
    Write the generated MCP entry to the selected OpenCode config file.

.PARAMETER DryRun
    Print the generated OpenCode config without writing files.

.PARAMETER Verify
    Run detection and validation only. No files are modified.

.PARAMETER Scope
    Target OpenCode config scope when applying: project or global.
    project writes opencode.json in ProjectPath.
    global writes ~/.config/opencode/opencode.json.

.PARAMETER Name
    MCP server name to use in OpenCode config. Default: kicad.

.PARAMETER KiCadRoot
    Explicit KiCAD installation root, for example C:\Program Files\KiCad\9.0.

.PARAMETER ProjectPath
    Project directory that should receive opencode.json for project-only setup.
    Defaults to the current working directory.

.PARAMETER McpServerPath
    KiCAD MCP Server repository directory. Defaults to the directory containing
    this script.

.PARAMETER ConfigPath
    Explicit OpenCode config path. Overrides Scope.

.PARAMETER SkipInstall
    Skip npm install.

.PARAMETER SkipBuild
    Skip npm run build.

.PARAMETER Force
    Allow config generation even when KiCAD Python/pcbnew validation fails.

.EXAMPLE
    .\setup-windows-opencode.ps1 -Verify

.EXAMPLE
    .\setup-windows-opencode.ps1 -DryRun

.EXAMPLE
    .\setup-windows-opencode.ps1 -Apply -Scope project -ProjectPath C:\path\to\your-project

.EXAMPLE
    .\setup-windows-opencode.ps1 -Apply -Scope global -Name kicad-dev
#>

param(
    [switch]$Apply,
    [switch]$DryRun,
    [switch]$Verify,
    [ValidateSet('project', 'global')]
    [string]$Scope = 'project',
    [string]$Name = 'kicad',
    [string]$KiCadRoot = '',
    [string]$ProjectPath = '',
    [string]$McpServerPath = '',
    [string]$ConfigPath = '',
    [switch]$SkipInstall,
    [switch]$SkipBuild,
    [switch]$Force
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Write-Success { param([string]$Message) Write-Host "[OK] $Message" -ForegroundColor Green }
function Write-Error-Custom { param([string]$Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }
function Write-Warning-Custom { param([string]$Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Info { param([string]$Message) Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Write-Step { param([string]$Message) Write-Host "`n=== $Message ===" -ForegroundColor Magenta }

function ConvertTo-HashtableDeep {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)

    if ($null -eq $InputObject) {
        return $null
    }

    if ($InputObject -is [System.Collections.IEnumerable] -and $InputObject -isnot [string] -and $InputObject -isnot [System.Collections.IDictionary] -and $InputObject -isnot [pscustomobject]) {
        $items = @()
        foreach ($item in $InputObject) {
            $items += ConvertTo-HashtableDeep $item
        }
        return $items
    }

    if ($InputObject -is [System.Collections.IDictionary]) {
        $hash = [ordered]@{}
        foreach ($key in $InputObject.Keys) {
            $hash[$key] = ConvertTo-HashtableDeep $InputObject[$key]
        }
        return $hash
    }

    if ($InputObject -is [pscustomobject]) {
        $hash = [ordered]@{}
        foreach ($property in $InputObject.PSObject.Properties) {
            $hash[$property.Name] = ConvertTo-HashtableDeep $property.Value
        }
        return $hash
    }

    return $InputObject
}

function Find-KiCadInstallation {
    param([string]$ExplicitRoot)

    if ($ExplicitRoot) {
        $resolved = [System.Environment]::ExpandEnvironmentVariables($ExplicitRoot)
        if (Test-Path -LiteralPath $resolved) {
            return Get-KiCadInfo -Root $resolved
        }
        return $null
    }

    $basePaths = @(
        'C:\Program Files\KiCad',
        'C:\Program Files (x86)\KiCad',
        (Join-Path $env:LOCALAPPDATA 'Programs\KiCad')
    )

    $preferredVersions = @('10.0', '9.1', '9.0', '8.0')
    foreach ($basePath in $basePaths) {
        foreach ($version in $preferredVersions) {
            $root = Join-Path $basePath $version
            $info = Get-KiCadInfo -Root $root
            if ($info) {
                return $info
            }
        }
    }

    foreach ($basePath in $basePaths) {
        if (-not (Test-Path -LiteralPath $basePath)) {
            continue
        }

        $children = Get-ChildItem -LiteralPath $basePath -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
        foreach ($child in $children) {
            $info = Get-KiCadInfo -Root $child.FullName
            if ($info) {
                return $info
            }
        }
    }

    return $null
}

function Get-KiCadInfo {
    param([string]$Root)

    if (-not $Root -or -not (Test-Path -LiteralPath $Root)) {
        return $null
    }

    $pythonExeCandidates = @(
        (Join-Path $Root 'bin\python.exe'),
        (Join-Path $Root 'bin\Python.exe')
    )
    $pythonExe = $pythonExeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $pythonExe) {
        return $null
    }

    $pythonLibCandidates = @(
        (Join-Path $Root 'lib\python3\dist-packages'),
        (Join-Path $Root 'bin\Lib\site-packages')
    )
    $pythonLib = $pythonLibCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $pythonLib) {
        $pythonLib = $pythonLibCandidates[0]
    }

    return [ordered]@{
        Root = $Root
        Version = Split-Path -Leaf $Root
        PythonExe = $pythonExe
        PythonLib = $pythonLib
    }
}

function Get-TargetConfigPath {
    param(
        [string]$ExplicitPath,
        [string]$SelectedScope,
        [string]$TargetProjectPath
    )

    if ($ExplicitPath) {
        return [System.Environment]::ExpandEnvironmentVariables($ExplicitPath)
    }

    if ($SelectedScope -eq 'global') {
        return Join-Path $env:USERPROFILE '.config\opencode\opencode.json'
    }

    return Join-Path $TargetProjectPath 'opencode.json'
}

function Resolve-DirectoryPath {
    param(
        [string]$Path,
        [string]$FallbackPath,
        [string]$Label
    )

    $candidate = if ($Path) { [System.Environment]::ExpandEnvironmentVariables($Path) } else { $FallbackPath }
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
        throw "$Label directory does not exist: $candidate"
    }

    return (Resolve-Path -LiteralPath $candidate).Path
}

function Read-OpenCodeConfig {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{
            '$schema' = 'https://opencode.ai/config.json'
        }
    }

    $raw = Get-Content -LiteralPath $Path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return [ordered]@{
            '$schema' = 'https://opencode.ai/config.json'
        }
    }

    try {
        $parsed = $raw | ConvertFrom-Json
        $config = ConvertTo-HashtableDeep $parsed
        if (-not $config.Contains('$schema')) {
            $schemaConfig = [ordered]@{ '$schema' = 'https://opencode.ai/config.json' }
            foreach ($key in $config.Keys) {
                $schemaConfig[$key] = $config[$key]
            }
            return $schemaConfig
        }
        return $config
    } catch {
        throw "Failed to parse existing OpenCode config '$Path': $($_.Exception.Message)"
    }
}

function Set-McpEntry {
    param(
        [System.Collections.IDictionary]$Config,
        [string]$ServerName,
        [string]$DistPath,
        [string]$PythonPath
    )

    if (-not $Config.Contains('mcp') -or $null -eq $Config['mcp']) {
        $Config['mcp'] = [ordered]@{}
    }

    $environment = [ordered]@{
        NODE_ENV = 'production'
        LOG_LEVEL = 'info'
        KICAD_AUTO_LAUNCH = 'false'
        KICAD_MCP_DEV = '0'
    }

    if ($PythonPath) {
        $environment['PYTHONPATH'] = $PythonPath
    }

    $Config['mcp'][$ServerName] = [ordered]@{
        type = 'local'
        command = @('node', $DistPath)
        environment = $environment
        enabled = $true
        timeout = 30000
    }
}

function Write-OpenCodeConfig {
    param(
        [System.Collections.IDictionary]$Config,
        [string]$Path
    )

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    if (Test-Path -LiteralPath $Path) {
        $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backupPath = "$Path.bak-$timestamp"
        Copy-Item -LiteralPath $Path -Destination $backupPath
        Write-Success "Backup written: $backupPath"
    }

    $json = $Config | ConvertTo-Json -Depth 20
    $json | Out-File -LiteralPath $Path -Encoding UTF8
}

if (-not $Apply -and -not $DryRun -and -not $Verify) {
    $Verify = $true
}

if (($Apply.IsPresent -and $DryRun.IsPresent) -or ($Apply.IsPresent -and $Verify.IsPresent) -or ($DryRun.IsPresent -and $Verify.IsPresent)) {
    throw 'Choose only one of -Apply, -DryRun, or -Verify.'
}

Write-Host @"
============================================================
  KiCAD MCP Server - OpenCode Windows Setup
============================================================
"@ -ForegroundColor Cyan

$script:Results = [ordered]@{
    KiCadFound = $false
    PcbnewImport = $false
    NodeFound = $false
    NpmInstall = $false
    ProjectBuilt = $false
    DistFound = $false
    ConfigReady = $false
    Errors = @()
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$McpServerRoot = Resolve-DirectoryPath -Path $McpServerPath -FallbackPath $ScriptRoot -Label 'MCP server'
$TargetProjectRoot = Resolve-DirectoryPath -Path $ProjectPath -FallbackPath (Get-Location).Path -Label 'Project'
$DistPath = Join-Path $McpServerRoot 'dist\index.js'
$TargetConfigPath = Get-TargetConfigPath -ExplicitPath $ConfigPath -SelectedScope $Scope -TargetProjectPath $TargetProjectRoot

Write-Info "MCP server path: $McpServerRoot"
if ($Scope -eq 'project') {
    Write-Info "OpenCode project path: $TargetProjectRoot"
}

Write-Step 'Step 1: Detecting KiCAD Installation'
$kicad = Find-KiCadInstallation -ExplicitRoot $KiCadRoot
if ($kicad) {
    $script:Results.KiCadFound = $true
    Write-Success "Found KiCAD at: $($kicad.Root)"
    Write-Info "KiCAD Python: $($kicad.PythonExe)"
    Write-Info "KiCAD PYTHONPATH: $($kicad.PythonLib)"
} else {
    Write-Error-Custom 'KiCAD was not found in standard Windows locations.'
    Write-Warning-Custom 'Use -KiCadRoot "C:\Path\To\KiCad\9.0" if KiCAD is installed elsewhere.'
    $script:Results.Errors += 'KiCAD not found'
}

Write-Step 'Step 2: Testing KiCAD pcbnew Module'
if ($kicad) {
    $testScript = "import pcbnew; print('SUCCESS:' + pcbnew.GetBuildVersion())"
    $pcbnewResult = & $kicad.PythonExe -c $testScript 2>&1
    if ($LASTEXITCODE -eq 0 -and $pcbnewResult -match 'SUCCESS:(.+)') {
        $script:Results.PcbnewImport = $true
        Write-Success "pcbnew imported successfully: $($matches[1])"
    } else {
        Write-Error-Custom 'KiCAD Python could not import pcbnew.'
        Write-Warning-Custom "Output: $pcbnewResult"
        $script:Results.Errors += 'pcbnew import failed'
    }
} else {
    Write-Warning-Custom 'Skipping pcbnew test because KiCAD was not found.'
}

Write-Step 'Step 3: Checking Node.js'
try {
    $nodeVersion = node --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        $script:Results.NodeFound = $true
        Write-Success "Node.js found: $nodeVersion"
        $major = [int]($nodeVersion -replace '^v(\d+)\..*$', '$1')
        if ($major -lt 18) {
            Write-Warning-Custom "Node.js 18+ is recommended. Found $nodeVersion."
        }
    } else {
        throw 'node command failed'
    }
} catch {
    Write-Error-Custom 'Node.js was not found. Install Node.js 18+ from https://nodejs.org/.'
    $script:Results.Errors += 'Node.js not found'
}

Write-Step 'Step 4: Installing Node Dependencies'
if ($SkipInstall) {
    Write-Info 'Skipping npm install because -SkipInstall was specified.'
    $script:Results.NpmInstall = $true
} elseif ($script:Results.NodeFound) {
    Push-Location $McpServerRoot
    try {
        npm install
        if ($LASTEXITCODE -eq 0) {
            $script:Results.NpmInstall = $true
            Write-Success 'npm install completed.'
        } else {
            Write-Error-Custom 'npm install failed.'
            $script:Results.Errors += 'npm install failed'
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Warning-Custom 'Skipping npm install because Node.js was not found.'
}

Write-Step 'Step 5: Building TypeScript Project'
if ($SkipBuild) {
    Write-Info 'Skipping npm run build because -SkipBuild was specified.'
} elseif ($script:Results.NodeFound) {
    Push-Location $McpServerRoot
    try {
        npm run build
        if ($LASTEXITCODE -eq 0) {
            $script:Results.ProjectBuilt = $true
            Write-Success 'npm run build completed.'
        } else {
            Write-Error-Custom 'npm run build failed.'
            $script:Results.Errors += 'TypeScript build failed'
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Warning-Custom 'Skipping build because Node.js was not found.'
}

if (Test-Path -LiteralPath $DistPath) {
    $script:Results.DistFound = $true
    Write-Success "Found MCP server entrypoint: $DistPath"
} else {
    Write-Error-Custom "MCP server entrypoint was not found: $DistPath"
    $script:Results.Errors += 'dist/index.js not found'
}

Write-Step 'Step 6: Preparing OpenCode Configuration'
$canGenerate = $script:Results.NodeFound -and $script:Results.DistFound
if (-not $Force) {
    $canGenerate = $canGenerate -and $script:Results.KiCadFound -and $script:Results.PcbnewImport
}

if ($canGenerate) {
    $config = Read-OpenCodeConfig -Path $TargetConfigPath
    $pythonPath = if ($kicad) { $kicad.PythonLib } else { '' }
    Set-McpEntry -Config $config -ServerName $Name -DistPath $DistPath -PythonPath $pythonPath
    $script:Results.ConfigReady = $true

    Write-Success "OpenCode MCP entry prepared for server name '$Name'."
    Write-Info "Target config: $TargetConfigPath"
    Write-Host ''
    Write-Host ($config | ConvertTo-Json -Depth 20) -ForegroundColor Gray

    if ($Apply) {
        Write-OpenCodeConfig -Config $config -Path $TargetConfigPath
        Write-Success "OpenCode config written: $TargetConfigPath"
    } elseif ($DryRun) {
        Write-Info 'Dry run only. No files were modified.'
    } else {
        Write-Info 'Verify mode only. No files were modified.'
    }
} else {
    Write-Warning-Custom 'OpenCode config was not generated because required checks failed.'
    Write-Warning-Custom 'Use -Force to generate config anyway, or resolve the errors above and run again.'
}

Write-Step 'Setup Summary'
Write-Host "  KiCAD Installation:  $(if ($script:Results.KiCadFound) { '[OK] Found' } else { '[ERROR] Not Found' })"
Write-Host "  pcbnew Module:       $(if ($script:Results.PcbnewImport) { '[OK] Working' } else { '[ERROR] Failed' })"
Write-Host "  Node.js:             $(if ($script:Results.NodeFound) { '[OK] Found' } else { '[ERROR] Not Found' })"
Write-Host "  npm install:         $(if ($script:Results.NpmInstall) { '[OK] Complete/Skipped' } else { '[WARN] Not Complete' })"
Write-Host "  TypeScript Build:    $(if ($script:Results.ProjectBuilt -or $SkipBuild) { '[OK] Complete/Skipped' } else { '[WARN] Not Complete' })"
Write-Host "  dist/index.js:       $(if ($script:Results.DistFound) { '[OK] Found' } else { '[ERROR] Missing' })"
Write-Host "  OpenCode Config:     $(if ($script:Results.ConfigReady) { '[OK] Ready' } else { '[ERROR] Not Ready' })"

if ($script:Results.Errors.Count -gt 0) {
    Write-Host ''
    Write-Host 'Errors:' -ForegroundColor Red
    foreach ($item in $script:Results.Errors) {
        Write-Host "  - $item" -ForegroundColor Red
    }
}

if ($Apply -and $script:Results.ConfigReady) {
    Write-Host ''
    Write-Success 'Next steps:'
    Write-Host '  1. Fully quit and restart OpenCode.' -ForegroundColor Green
    Write-Host "  2. Ask OpenCode to use the '$Name' MCP server and run check_kicad_ui." -ForegroundColor Green
} elseif (-not $Apply) {
    Write-Host ''
    Write-Info 'Run with -Apply to write the config after checks pass.'
}

if (-not $script:Results.ConfigReady -and -not $Verify) {
    exit 1
}
