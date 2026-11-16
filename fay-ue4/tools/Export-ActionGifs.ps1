param([string]$CaptureDirectory = (Join-Path $PSScriptRoot '..\ue4\Saved\ActionTests\v2-verified\frames'),
      [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\docs\action-previews-v2'))
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationCore
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
foreach($action in Get-ChildItem -LiteralPath $CaptureDirectory -Directory) {
    $encoder=New-Object System.Windows.Media.Imaging.GifBitmapEncoder
    $files=@(Get-ChildItem -LiteralPath $action.FullName -Filter '*.png' | Sort-Object Name)
    if($files.Count -lt 2){throw "Missing recorded frames: $($action.Name)"}
    foreach($file in $files) {
        $inputStream=[System.IO.File]::OpenRead($file.FullName)
        try {
            $bitmap=[System.Windows.Media.Imaging.BitmapFrame]::Create($inputStream,[System.Windows.Media.Imaging.BitmapCreateOptions]::PreservePixelFormat,[System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad)
        } finally { $inputStream.Dispose() }
        $metadata=New-Object System.Windows.Media.Imaging.BitmapMetadata 'gif'
        $metadata.SetQuery('/grctlext/Delay',[uint16]10)
        $metadata.SetQuery('/grctlext/Disposal',[byte]2)
        if($encoder.Frames.Count -eq 0){
            $metadata.SetQuery('/appext/application',[System.Text.Encoding]::ASCII.GetBytes('NETSCAPE2.0'))
            $metadata.SetQuery('/appext/data',[byte[]](3,1,0,0,0))
        }
        $encoder.Frames.Add([System.Windows.Media.Imaging.BitmapFrame]::Create($bitmap,$null,$metadata,$null))
    }
    $destination=Join-Path $OutputDirectory ($action.Name+'.gif')
    $outputStream=[System.IO.File]::Create($destination)
    try { $encoder.Save($outputStream) } finally { $outputStream.Dispose() }
    Write-Output "$($action.Name): $($files.Count) native frames -> $destination"
    $encoder=$null
    [System.GC]::Collect()
}
