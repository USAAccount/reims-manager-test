#Requires -Version 7.2
param([Parameter(Mandatory)][string]$ArchiveDirectory,[Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][string]$SevenZip)
$ErrorActionPreference='Stop'
. "$PSScriptRoot/../backend/iphone-usb-package.ps1"
$pin=Get-ReimsIphoneUsbDriverLock
$archives=Assert-ReimsIphoneUsbOrdinaryPath $ArchiveDirectory
$output=Assert-ReimsIphoneUsbOrdinaryPath $OutputDirectory -AllowMissing
if(Test-Path -LiteralPath $output) { throw 'iPhone USB output already exists; refusing overwrite.' }
[void](Assert-ReimsIphoneUsbOrdinaryPath $SevenZip)
foreach($archive in $pin.archives.Values) {
    $file=Get-Item -LiteralPath (Assert-ReimsIphoneUsbOrdinaryPath (Join-ReimsPackagePath $archives $archive.file))
    if($file.PSIsContainer -or $file.Length -ne $archive.bytes -or (Get-FileHash -LiteralPath $file.FullName).Hash -ine $archive.sha256) { throw 'Pinned USB archive hash/size mismatch.' }
}
$bsd=$pin.licenses|Where-Object {$_.ContainsKey('url')}
$bsdPath=Join-ReimsPackagePath $archives $bsd.file
[void](Assert-ReimsIphoneUsbOrdinaryPath $bsdPath -AllowMissing)
Get-ReimsPinnedDownload $bsd.url $bsd.sha256 $bsdPath
if((Get-Item -LiteralPath $bsdPath).Length -ne $bsd.bytes) { throw 'Pinned BSD license size mismatch.' }
$parent=Split-Path $output
[void][IO.Directory]::CreateDirectory($parent)
$scratch=Join-Path $parent ('.iphone-usb-'+[guid]::NewGuid().ToString('N'))
$package=Join-Path $scratch 'package'
try {
    [void][IO.Directory]::CreateDirectory($package)
    $zip=[IO.Compression.ZipFile]::OpenRead((Join-ReimsPackagePath $archives $pin.archives.driver.file))
    try {
        $entries=@{};$names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach($entry in $zip.Entries) {
            $name=$entry.FullName.TrimEnd('/')
            [void](Join-ReimsPackagePath $scratch $name)
            if(!$names.Add($name) -or (($entry.ExternalAttributes -shr 16) -band 0xf000) -eq 0xa000) { throw 'Duplicate/symlink driver ZIP entry.' }
            $entries[$name]=$entry
        }
        $driverFiles=@(Get-ReimsIphoneUsbDriverFiles|Where-Object {$_ -notlike 'licenses/*' -and $_ -cne $pin.api.file})
        foreach($relative in $driverFiles+@('licenses/COPYING_GPL.txt','licenses/COPYING_LGPL.txt')) {
            $member=$pin.archives.driver.prefix+'/'+$(if($relative -like 'licenses/*'){[IO.Path]::GetFileName($relative)}else{'bin/'+$relative})
            if(!$entries.ContainsKey($member) -or $entries[$member].Length -gt 4MB) { throw 'Required pinned driver ZIP payload is missing/oversized.' }
            $destination=Join-ReimsPackagePath $package $relative
            [void][IO.Directory]::CreateDirectory((Split-Path $destination))
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entries[$member],$destination,$false)
        }
    } finally { $zip.Dispose() }
    $extracted=Join-Path $scratch 'api'
    & $SevenZip x '-y' '-bso0' '-bsp0' "-o$extracted" (Join-ReimsPackagePath $archives $pin.archives.api.file) $pin.api.member
    if($LASTEXITCODE -ne 0) { throw 'Pinned libusbK member extraction failed.' }
    $api=Assert-ReimsIphoneUsbOrdinaryPath (Join-ReimsPackagePath $extracted $pin.api.member)
    [IO.File]::Copy($api,(Join-ReimsPackagePath $package $pin.api.file),$false)
    [IO.File]::Copy($bsdPath,(Join-ReimsPackagePath $package ('licenses/'+$bsd.file)),$false)
    $files=[ordered]@{}
    foreach($name in Get-ReimsIphoneUsbDriverFiles) { $files[$name]=(Get-FileHash -LiteralPath (Join-ReimsPackagePath $package $name)).Hash.ToLowerInvariant() }
    [IO.File]::WriteAllText((Join-Path $package 'manifest.json'),(@{schema=1;id=$pin.id;files=$files}|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
    [void](Get-ReimsIphoneUsbDriverPackage $package)
    [void](Assert-ReimsIphoneUsbOrdinaryPath $output -AllowMissing)
    [IO.Directory]::Move($package,$output)
    [pscustomobject]@{stageDirectory=$output;infPath=(Join-Path $output 'libusb0.inf');apiDll=(Join-Path $output $pin.api.file)}
} finally {
    if(Test-Path -LiteralPath $scratch) {
        $resolved=[IO.Path]::GetFullPath($scratch)
        if([IO.Path]::GetDirectoryName($resolved) -ine [IO.Path]::GetFullPath($parent)) { throw 'Bundle cleanup escaped its owned staging directory.' }
        [void](Assert-ReimsIphoneUsbOrdinaryPath $resolved)
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
