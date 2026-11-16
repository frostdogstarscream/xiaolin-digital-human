$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root 'assets\calibration-speech-v1.wav'
if(Test-Path -LiteralPath $target){throw 'Calibration audio already exists; use the existing recording or a new revision.'}
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN' } | Select-Object -First 1
    if(-not $voice){throw 'No offline Chinese SAPI voice is installed.'}
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $synth.SetOutputToWaveFile($target, $format)
    $text = [System.IO.File]::ReadAllText((Join-Path $root 'assets\calibration-speech-v1.txt'),[System.Text.Encoding]::UTF8)
    $synth.Speak($text)
    $synth.SetOutputToNull()
    @{provider='Windows offline SAPI';voice=$voice.VoiceInfo.Name;sample_rate=24000;channels=1;bits=16;cloud_calls=0;text=$text} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'assets\calibration-speech-v1.json') -Encoding UTF8
    Write-Output "Saved local calibration voice: $($voice.VoiceInfo.Name)"
} finally {$synth.Dispose()}
