$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Visual Studio C++ Build Tools and a Windows SDK are required on the build machine.' }
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
$build = Join-Path $projectRoot 'build\launcher'
New-Item -ItemType Directory -Force -Path $build | Out-Null
$output = Join-Path $projectRoot '文矩.exe'
Push-Location $PSScriptRoot
try {
    $command = 'call "{0}" && rc.exe /nologo /fo"{1}\wenju.res" windows_launcher.rc && cl.exe /nologo /O2 /MT /EHsc /Fo"{1}\wenju.obj" windows_launcher.cpp "{1}\wenju.res" /link /SUBSYSTEM:WINDOWS /MANIFEST:NO /OUT:"{2}" shell32.lib ole32.lib uuid.lib user32.lib' -f $vcvars,$build,$output
    & cmd.exe /d /c $command
    if ($LASTEXITCODE -ne 0) { throw 'Native launcher compilation failed.' }
} finally { Pop-Location }
Get-Item -LiteralPath $output | Select-Object Name,Length
