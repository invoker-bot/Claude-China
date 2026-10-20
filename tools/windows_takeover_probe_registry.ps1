<# Temporary, exact-path Grok Bot IFEO registration with automatic rollback.
   Run elevated only after reviewing the generated manifest and debugger command.
   The app itself must still be started from the normal, non-elevated session.
   Refuses existing IFEO keys. Never touches Claude, Codex, or vendor files.
#>
param(
    [Parameter(Mandatory=$true)][string]$Manifest,
    [switch]$RestoreOnly,
    [ValidateRange(30,900)][int]$TimeoutSeconds = 600
)
$ErrorActionPreference = 'Stop'
$probeManifestPath = (Resolve-Path -LiteralPath $Manifest).Path
$probeDirectory = Split-Path -Parent $probeManifestPath
$probeSpec = Get-Content -LiteralPath $probeManifestPath -Raw | ConvertFrom-Json
$probeTarget = [IO.Path]::GetFullPath($probeSpec.target)
if ([IO.Path]::GetFileName($probeTarget) -ine 'Grok Bot.exe') {
    throw 'Only Grok Bot.exe is permitted in this experiment.'
}
if (-not (Test-Path -LiteralPath $probeTarget -PathType Leaf)) { throw 'Missing target.' }
if ($probeSpec.run_id -notmatch '^[a-f0-9]{32}$') { throw 'Invalid experiment identifier.' }
if (-not $probeSpec.debugger -or $probeSpec.debugger.Contains("`r") -or $probeSpec.debugger.Contains("`n")) {
    throw 'Missing or invalid debugger command.'
}
$probeRegistry = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
    [Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$probeKeyPath = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\Grok Bot.exe'

function Restore-Probe {
    $probeKey = $probeRegistry.OpenSubKey($probeKeyPath, $true)
    if ($null -eq $probeKey) { return }
    try {
        if ($probeKey.GetValue('ClaudeChinaProbeOwner') -ne $probeSpec.run_id) {
            throw 'Registration ownership changed; refusing to delete another registration.'
        }
        $probeFilter = $probeKey.OpenSubKey('ClaudeChinaProbe', $true)
        if ($null -ne $probeFilter) {
            try {
                $probeRegisteredDebugger = $probeFilter.GetValue('Debugger')
                $probeRegisteredTarget = $probeFilter.GetValue('FilterFullPath')
                if (($null -ne $probeRegisteredDebugger -and $probeRegisteredDebugger -ne $probeSpec.debugger) -or
                    ($null -ne $probeRegisteredTarget -and $probeRegisteredTarget -ne $probeTarget)) {
                    throw 'Filter changed; manual review required.'
                }
                $probeFilter.DeleteValue('Debugger', $false)
                $probeFilter.DeleteValue('FilterFullPath', $false)
                $probeFilterEmpty = $probeFilter.ValueCount -eq 0 -and $probeFilter.SubKeyCount -eq 0
            } finally { $probeFilter.Dispose() }
            if ($probeFilterEmpty) { $probeKey.DeleteSubKey('ClaudeChinaProbe') }
        }
        if ($probeKey.SubKeyCount -eq 0) { $probeKey.DeleteValue('UseFilter', $false) }
        $probeKey.DeleteValue('ClaudeChinaProbeOwner', $false)
        $probeKeyEmpty = $probeKey.ValueCount -eq 0 -and $probeKey.SubKeyCount -eq 0
    } finally { $probeKey.Dispose() }
    if ($probeKeyEmpty) { $probeRegistry.DeleteSubKey($probeKeyPath) }
}

if ($RestoreOnly) {
    try {
        Restore-Probe
        Set-Content -LiteralPath (Join-Path $probeDirectory 'restored.json') -Value '{"restored":true}'
    } finally { $probeRegistry.Dispose() }
    exit 0
}

$probeInstalled = $false
try {
    $probeExisting = $probeRegistry.OpenSubKey($probeKeyPath)
    if ($null -ne $probeExisting) {
        $probeExisting.Dispose()
        throw 'An IFEO key already exists for Grok Bot. No changes made.'
    }
    if (([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) -ge $probeSpec.expires_at) {
        throw 'Experiment expired.'
    }
    $probeKey = $probeRegistry.CreateSubKey($probeKeyPath)
    try {
        $probeKey.SetValue('ClaudeChinaProbeOwner', $probeSpec.run_id)
        $probeInstalled = $true
        $probeFilter = $probeKey.CreateSubKey('ClaudeChinaProbe')
        try {
            $probeFilter.SetValue('FilterFullPath', $probeTarget)
            $probeFilter.SetValue('Debugger', $probeSpec.debugger)
        } finally { $probeFilter.Dispose() }
        $probeKey.SetValue('UseFilter', 1, [Microsoft.Win32.RegistryValueKind]::DWord)
    } finally { $probeKey.Dispose() }
    Set-Content -LiteralPath (Join-Path $probeDirectory 'ready.json') -Value '{"registered":true}'
    $probeTimer = [Diagnostics.Stopwatch]::StartNew()
    while ($probeTimer.Elapsed.TotalSeconds -lt $TimeoutSeconds -and
           -not (Test-Path -LiteralPath (Join-Path $probeDirectory 'stop'))) {
        Start-Sleep -Milliseconds 250
    }
} catch {
    @{error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $probeDirectory 'registry-error.json')
    throw
} finally {
    try {
        if ($probeInstalled) {
            Restore-Probe
            Set-Content -LiteralPath (Join-Path $probeDirectory 'restored.json') -Value '{"restored":true}'
        }
    } finally { $probeRegistry.Dispose() }
}
