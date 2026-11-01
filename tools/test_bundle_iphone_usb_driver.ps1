#Requires -Version 7.2
param([Parameter(Mandatory)][string]$ArchiveDirectory,[Parameter(Mandatory)][string]$SevenZip)
$ErrorActionPreference='Stop'
$nativeBefore='ReimsUsbDriverBinding.Native' -as [type]
. "$PSScriptRoot/../backend/iphone-usb-package.ps1"
$root=Join-Path ([IO.Path]::GetTempPath()) ('reims-iphone-package-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
$script:checks=0
function Assert($Condition,[string]$Message) { if(!$Condition) { throw $Message };$script:checks++ }
function Reject([scriptblock]$Action,[string]$Pattern) {
    $message='';try { & $Action | Out-Null } catch { $message=$_.Exception.Message }
    Assert ($message -match $Pattern) "Expected refusal '$Pattern'; actual '$message'"
}
try {
    $output=Join-Path $root 'valid'
    & "$PSScriptRoot/bundle-iphone-usb-driver.ps1" -ArchiveDirectory $ArchiveDirectory -OutputDirectory $output -SevenZip $SevenZip | Out-Null
    $package=Get-ReimsIphoneUsbDriverPackage $output
    Assert ($package.stageDirectory -eq $output -and $package.infPath -eq (Join-Path $output 'libusb0.inf') -and $package.apiDll -eq (Join-Path $output 'libusbK.dll')) 'Consumer paths must point to verified expanded files'
    Assert (@(Get-ChildItem -LiteralPath $output -Recurse -File).Count -eq 10) 'Bundle must contain exactly nine payloads and its manifest'
    Assert (($null -ne ('ReimsUsbDriverBinding.Native' -as [type])) -eq ($null -ne $nativeBefore)) 'Bundling and reading must not initialize native bindings'
    Reject { & "$PSScriptRoot/bundle-iphone-usb-driver.ps1" -ArchiveDirectory $ArchiveDirectory -OutputDirectory $output -SevenZip $SevenZip } 'already exists'
    [void](Get-ReimsIphoneUsbDriverPackage $output)

    $fake=Join-Path $root 'bad-archives';New-Item -ItemType Directory -Path $fake | Out-Null
    foreach($archive in (Get-ReimsIphoneUsbDriverLock).archives.Values) {
        $stream=[IO.File]::Create((Join-Path $fake $archive.file))
        try { $stream.SetLength($archive.bytes) } finally { $stream.Dispose() }
    }
    $notPublished=Join-Path $root 'not-published'
    Reject { & "$PSScriptRoot/bundle-iphone-usb-driver.ps1" -ArchiveDirectory $fake -OutputDirectory $notPublished -SevenZip $SevenZip } 'archive hash/size mismatch'
    Assert (!(Test-Path -LiteralPath $notPublished) -and !(Get-ChildItem -LiteralPath $root -Force -Filter '.iphone-usb-*')) 'Untrusted archive cannot publish or leave a partial stage'

    $stub=Join-Path $root 'late-failure';New-Item -ItemType Directory -Path "$stub/tools","$stub/backend" | Out-Null
    Copy-Item -LiteralPath "$PSScriptRoot/bundle-iphone-usb-driver.ps1" -Destination "$stub/tools"
    foreach($name in @('iphone-usb-package.ps1','iphone-usb-driver-lock.json','usb-driver-binding.ps1','engine-package.ps1','release-asset.ps1')) {
        Copy-Item -LiteralPath "$PSScriptRoot/../backend/$name" -Destination "$stub/backend"
    }
    Add-Content -LiteralPath "$stub/backend/iphone-usb-package.ps1" -Value "`nfunction Get-ReimsIphoneUsbDriverPackage { throw 'Authored final verification failure' }"
    Reject { & "$stub/tools/bundle-iphone-usb-driver.ps1" -ArchiveDirectory $ArchiveDirectory -OutputDirectory $notPublished -SevenZip $SevenZip } 'Authored final verification failure'
    Assert (!(Test-Path -LiteralPath $notPublished) -and !(Get-ChildItem -LiteralPath $root -Force -Filter '.iphone-usb-*')) 'Late verification failure cannot publish or leave extracted staging files'

    $api=Join-Path $output 'libusbK.dll';$original=[IO.File]::ReadAllBytes($api)
    $changed=[byte[]]$original.Clone();$changed[0]=$changed[0] -bxor 1;[IO.File]::WriteAllBytes($api,$changed)
    Reject { Get-ReimsIphoneUsbDriverPackage $output } 'payload hash mismatch'
    $manifest=Join-Path $output 'manifest.json';$manifestBytes=[IO.File]::ReadAllBytes($manifest)
    $m=Get-Content -Raw -LiteralPath $manifest|ConvertFrom-Json -AsHashtable
    $m.files['libusbK.dll']=(Get-FileHash -LiteralPath $api).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText($manifest,($m|ConvertTo-Json -Depth 5))
    Reject { Get-ReimsIphoneUsbDriverPackage $output } 'Pinned libusbK API hash mismatch'
    [IO.File]::WriteAllBytes($api,$original);[IO.File]::WriteAllBytes($manifest,$manifestBytes)

    $inf=Join-Path $output 'libusb0.inf';$originalInf=[IO.File]::ReadAllBytes($inf)
    [IO.File]::WriteAllText($inf,'authored modified INF')
    $m.files['libusbK.dll']=(Get-FileHash -LiteralPath $api).Hash.ToLowerInvariant()
    $m.files['libusb0.inf']=(Get-FileHash -LiteralPath $inf).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText($manifest,($m|ConvertTo-Json -Depth 5))
    Reject { Get-ReimsIphoneUsbDriverPackage $output } 'Official driver package pin mismatch'
    [IO.File]::WriteAllBytes($inf,$originalInf);[IO.File]::WriteAllBytes($manifest,$manifestBytes)

    Remove-Item -LiteralPath $api
    Reject { Get-ReimsIphoneUsbDriverPackage $output } 'payload is missing'
    [IO.File]::WriteAllBytes($api,$original)
    [IO.File]::WriteAllText((Join-Path $output 'unexpected.dll'),'authored extra')
    Reject { Get-ReimsIphoneUsbDriverPackage $output } 'Unexpected iPhone USB payload'
    Remove-Item -LiteralPath (Join-Path $output 'unexpected.dll')
    $duplicate=[Text.Encoding]::UTF8.GetString($manifestBytes).Replace('"files": {','"files": {"libusbK.dll":"'+('0'*64)+'",')
    [IO.File]::WriteAllText($manifest,$duplicate)
    Reject { Get-ReimsIphoneUsbDriverPackage $output } 'payload count mismatch'
    [IO.File]::WriteAllBytes($manifest,$manifestBytes)
    $link=Join-Path $root 'package-link'
    New-Item -ItemType Junction -Path $link -Target $output | Out-Null
    try { Reject { Get-ReimsIphoneUsbDriverPackage $link } 'Reparse paths are refused' }
    finally { Remove-Item -LiteralPath $link -Force }
    $nested=Join-Path $output 'linked-directory'
    New-Item -ItemType Junction -Path $nested -Target $fake | Out-Null
    try { Reject { Get-ReimsIphoneUsbDriverPackage $output } 'Unexpected/reparse' }
    finally { Remove-Item -LiteralPath $nested -Force }
    [void](Get-ReimsIphoneUsbDriverPackage $output)
    "iPhone USB bundle CPU fixture: $script:checks checks passed; no payload, driver or device operation invoked."
} finally {
    if(Test-Path -LiteralPath $root) {
        $resolved=[IO.Path]::GetFullPath($root)
        $temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
        if(!$resolved.StartsWith($temp,[StringComparison]::OrdinalIgnoreCase)) { throw 'Bundle fixture cleanup escaped its workspace.' }
        [void](Assert-ReimsIphoneUsbOrdinaryPath $resolved)
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
