#Requires -Version 7.2
param([Parameter(Mandatory)][string]$ArchiveDirectory)
$ErrorActionPreference='Stop'
. "$PSScriptRoot/../backend/iphone-usb-package.ps1"
$directory=Assert-ReimsIphoneUsbOrdinaryPath $ArchiveDirectory -AllowMissing
[void][IO.Directory]::CreateDirectory($directory)
$pin=Get-ReimsIphoneUsbDriverLock
$inputs=@($pin.archives.Values)+@($pin.licenses|Where-Object {$_.ContainsKey('url')})
foreach($item in $inputs) {
    if($item.file -cne [IO.Path]::GetFileName($item.file) -or $item.bytes -le 0) { throw 'Invalid pinned USB download.' }
    $path=Join-ReimsPackagePath $directory $item.file
    [void](Assert-ReimsIphoneUsbOrdinaryPath $path -AllowMissing)
    Get-ReimsPinnedDownload $item.url $item.sha256 $path
    if((Get-Item -LiteralPath $path).Length -ne $item.bytes) { throw 'Pinned USB download size mismatch.' }
}
