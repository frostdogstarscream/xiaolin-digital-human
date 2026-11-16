function Get-KioskUEEnvironment {
    param([string]$EngineRoot, [string]$ProjectRoot)
    if (-not $EngineRoot) {
        $config = Join-Path $ProjectRoot 'runtime\ue-environment.json'
        if (Test-Path -LiteralPath $config) { $EngineRoot = (Get-Content -LiteralPath $config -Raw | ConvertFrom-Json).engine_root }
    }
    if (-not $EngineRoot) { throw 'Pass -EngineRoot with the UE4.27.2 installation directory.' }
    $engine = (Resolve-Path -LiteralPath $EngineRoot).Path
    $version = Get-Content -LiteralPath (Join-Path $engine 'Engine\Build\Build.version') -Raw | ConvertFrom-Json
    if ($version.MajorVersion -ne 4 -or $version.MinorVersion -ne 27 -or $version.PatchVersion -ne 2) { throw 'Unreal Engine 4.27.2 is required.' }
    $source = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $link = Join-Path ([System.IO.Path]::GetTempPath()) 'FayUE4DevLink'
    if (Test-Path -LiteralPath $link) {
        $item = Get-Item -LiteralPath $link
        if ($item.LinkType -ne 'Junction' -or $item.Target -ne $source) { throw "Existing path is not this project's junction: $link" }
    } else { New-Item -ItemType Junction -Path $link -Target $source -ErrorAction Stop | Out-Null }
    return @{ Engine=$engine; Root=$link; Project=(Join-Path $link 'ue4\HoloKiosk.uproject') }
}
