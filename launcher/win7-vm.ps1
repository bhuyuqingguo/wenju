# Start a Windows 7 SP1 x64 VM on the user's own Windows PC.
# This script does not download Windows. Point -Iso at a disc you already own.
# Hyper-V needs Windows Pro/Enterprise. Otherwise the VirtualBox branch is used.
param(
  [Parameter(Mandatory=$true)][string]$Iso,
  [string]$VmName = 'WenJu-Win7SP1',
  [string]$Folder = "$env:USERPROFILE\WenJu-VMs",
  [int]$MemoryMB = 2048,
  [string]$Engine = 'auto'
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Iso)) { throw "ISO not found: $Iso" }
New-Item -ItemType Directory -Force -Path $Folder | Out-Null
$vhd = Join-Path $Folder "$VmName.vhdx"
if ($Engine -eq 'auto') {
  $Engine = $(if (Get-Command hyper-v -ErrorAction SilentlyContinue) { 'hyperv' } else { 'virtualbox' })
  if (Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Enabled' }) {
    $Engine = 'hyperv'
  } elseif (Get-Command VBoxManage -ErrorAction SilentlyContinue) {
    $Engine = 'virtualbox'
  }
}
Write-Host "Engine: $Engine"
if ($Engine -eq 'hyperv') {
  if (-not (Test-Path $vhd)) { New-VHD -Path $vhd -SizeBytes 40GB -Dynamic | Out-Null }
  if (-not (Get-VM -Name $VmName -ErrorAction SilentlyContinue)) {
    New-VM -Name $VmName -MemoryStartupBytes ($MemoryMB * 1MB) -Generation 1 -VHDPath $vhd -SwitchName 'Default Switch' | Out-Null
    Set-VMDvdDrive -VMName $VmName -Path $Iso
    Set-VMProcessor -VMName $VmName -Count 2
  }
  Start-VM -Name $VmName
  Write-Host "Hyper-V VM started. Install Windows 7 SP1 from the ISO, then install KB2670838 before opening the WenJu zip."
  return
}
$vbox = Get-Command VBoxManage -ErrorAction SilentlyContinue
if (-not $vbox) { throw 'Install VirtualBox, or enable Hyper-V, then run this script again.' }
$vdi = Join-Path $Folder "$VmName.vdi"
if (-not (Test-Path $vdi)) { & VBoxManage createmedium disk --filename $vdi --size 40960 --format VDI | Out-Host }
& VBoxManage createvm --name $VmName --ostype Windows7_64 --register | Out-Host
& VBoxManage modifyvm $VmName --memory $MemoryMB --cpus 2 --nic1 nat --audio none
& VBoxManage storagectl $VmName --name SATA --add sata
& VBoxManage storageattach $VmName --storagectl SATA --port 0 --device 0 --type hdd --medium $vdi
& VBoxManage storageattach $VmName --storagectl SATA --port 1 --device 0 --type dvddrive --medium $Iso
& VBoxManage startvm $VmName
Write-Host "VirtualBox VM started. After setup, install KB2670838, then unzip WenJu_3.4.0_Windows7_x64_Portable.zip and run 打开文矩.exe."
