# Read-only monitor. No process termination, downloads, or file changes.
$ErrorActionPreference = 'Continue'
$acaneTotalBytes = 2753200000.0 # Approximate total shown by pip for this exact wheel.
Write-Host 'ACAne: monitor the CURRENT torch 2.11.0 Windows download.'
Write-Host 'Keep the original training window open. Close this monitor with Ctrl+C.'
Write-Host 'Total is approximate (2753.2 MB). This measures the temporary file, not installation.'
$acaneLastPath = ''
$acaneLastBytes = 0
$acaneLastTime = Get-Date
while ($true) {
    $acaneFile = Get-ChildItem -LiteralPath $env:TEMP -Directory -Filter 'pip-unpack-*' -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -File -Filter 'torch-2.11.0*cp312*win_amd64.whl' -ErrorAction SilentlyContinue } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $acaneNow = Get-Date
    if ($null -eq $acaneFile) {
        Write-Host ('{0:HH:mm:ss} No matching temporary file: download may not have started, or pip moved to another stage. See original window.' -f $acaneNow)
    } else {
        $acaneSeconds = ($acaneNow - $acaneLastTime).TotalSeconds
        $acaneSpeed = 0.0
        if ($acaneFile.FullName -eq $acaneLastPath -and $acaneSeconds -gt 0) {
            $acaneSpeed = [Math]::Max(0, ($acaneFile.Length - $acaneLastBytes) / $acaneSeconds / 1000000)
        } else {
            Write-Host ('File: ' + $acaneFile.FullName)
        }
        $acanePercent = [Math]::Min(100, 100*$acaneFile.Length/$acaneTotalBytes)
        Write-Host ('{0:HH:mm:ss} {1:N1} / ~2753.2 MB   ~{2:N1}%   {3:N2} MB/s (recent file growth)' -f $acaneNow, ($acaneFile.Length/1000000), $acanePercent, $acaneSpeed)
        $acaneLastBytes = $acaneFile.Length
        $acaneLastPath = $acaneFile.FullName
    }
    $acaneLastTime = $acaneNow
    Start-Sleep -Seconds 3
}
