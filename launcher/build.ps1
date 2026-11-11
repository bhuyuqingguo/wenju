$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'The .NET Framework C# compiler is required.' }
$output = Join-Path $projectRoot '文矩.exe'
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /codepage:65001 "/out:$output" "/win32icon:$PSScriptRoot\WenJu.ico" "/win32manifest:$PSScriptRoot\app.manifest" /reference:System.Windows.Forms.dll "$PSScriptRoot\Launcher.cs"
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
Get-Item -LiteralPath $output | Select-Object Name, Length
