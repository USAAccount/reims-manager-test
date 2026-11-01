# Authored metadata only; no disks, PnP devices, drivers or VM are queried.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile("$PSScriptRoot/../usb.ps1",[ref]$null,[ref]$null)
$definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Get-ReimsProtectedUsbIds'},$true)
. ([scriptblock]::Create($definition.Extent.Text))
$ProjectRoot='D:\authored-engine';$VmRoot='D:\authored-vm'
function Get-PnpDevice { [CmdletBinding()]param([switch]$PresentOnly,[string[]]$Class); [pscustomobject]@{InstanceId='HID\VID_9999&PID_0001\authored-input'} }
function Get-Partition { [CmdletBinding()]param($DriveLetter); [pscustomobject]@{DiskNumber=$(if($DriveLetter -eq 'D'){1}else{0})} }
function Get-Disk { [CmdletBinding()]param($Number); [pscustomobject]@{BusType=$(if($Number -eq 1){'USB'}else{'NVMe'})} }
function Get-CimInstance { [CmdletBinding()]param($ClassName,$Filter); [pscustomobject]@{PNPDeviceID=$(if($Filter -eq 'Index=1'){'SCSI\authored-storage\1'}else{'PCI\authored-system\0'})} }
function Get-ReimsPnpProperties([string[]]$Instances,[string]$Key) {
    foreach($id in $Instances){
        if($id -ceq 'SCSI\authored-storage\1'){
            $script:reads++
            if($script:mode -ceq 'denied'){throw [UnauthorizedAccessException]::new('Authored access denied')}
            if($script:mode -ceq 'missing' -or $script:reads -eq 1){
                if($script:mode -ceq 'null'){[pscustomobject]@{InstanceId=$id;Data=$null}}else{[pscustomobject]@{InstanceId=$id}}
            }else{[pscustomobject]@{InstanceId=$id;Data='USB\VID_8888&PID_0002\authored-storage'}}
        }else{[pscustomobject]@{InstanceId=$id;Data=$null}}
    }
}
foreach($mode in @('sparse','null')){
    $script:mode=$mode;$script:reads=0
    $ids=Get-ReimsProtectedUsbIds
    if(!$ids.Contains('8888:0002') -or !$ids.Contains('9999:0001') -or $script:reads -ne 2){throw 'Individual metadata retry lost protected storage/input or exceeded one retry.'}
}
foreach($mode in @('missing','denied')){
    $script:mode=$mode;$script:reads=0;$failed=$false
    try{Get-ReimsProtectedUsbIds|Out-Null}catch{$failed=$true}
    if(!$failed){throw 'Unknown or inaccessible storage ancestry was accepted.'}
}
'PASS: sparse/null parent metadata retries once; storage/input stay protected; persistent missing/access denied refuse. No device calls.'
