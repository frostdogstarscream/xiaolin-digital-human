param([Parameter(Mandatory=$true)][string]$JobFile)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$job=[System.IO.File]::ReadAllText($JobFile,[System.Text.Encoding]::UTF8) | ConvertFrom-Json
if(Test-Path -LiteralPath $job.output){throw 'Output already exists.'}
$synth=New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice=$synth.GetInstalledVoices() | Where-Object {$_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN'} | Select-Object -First 1
    if(-not $voice){throw 'No offline Chinese voice is installed.'}
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $format=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)
    $synth.SetOutputToWaveFile($job.output,$format)
    $synth.Speak([string]$job.text)
    $synth.SetOutputToNull()
} finally {$synth.Dispose()}
