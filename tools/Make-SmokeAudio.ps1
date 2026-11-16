# Run with Windows PowerShell 5.1. Generates isolated test audio, never a Bailian cache.
param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime\native-smoke' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'zh-CN' } | Select-Object -First 1
    if (-not $voice) { throw 'An installed Windows Chinese speech voice is required.' }
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $synth.SetOutputToWaveFile((Join-Path $OutputDirectory 'speech-test.wav'), $format)
    $text = '您好，这是全息仓数字人的本地中文播放测试。现在使用的是电脑自带的测试声音，不是百炼音色。请检查我的嘴型、眨眼和讲解动作，以及人物的比例和站立位置。测试中可以按下暂停，然后继续讲解。'
    $synth.Speak($text)
    [System.IO.File]::WriteAllText((Join-Path $OutputDirectory 'speech-test.txt'), $text, [System.Text.Encoding]::UTF8)
    Write-Output "Created test audio with $($voice.VoiceInfo.Name)"
} finally { $synth.Dispose() }
