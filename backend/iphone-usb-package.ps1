# Importing this reader defines functions only; it never initializes or loads a native DLL.
. "$PSScriptRoot/usb-driver-binding.ps1"
. "$PSScriptRoot/engine-package.ps1"

function Get-ReimsIphoneUsbDriverLock {
    $file=Get-Item -LiteralPath "$PSScriptRoot/iphone-usb-driver-lock.json"
    if($file.Length -gt 65536) { throw 'iPhone USB lock exceeds its size limit.' }
    $pin=Get-Content -Raw -LiteralPath $file.FullName | ConvertFrom-Json -AsHashtable
    if($pin.schema -ne 1) { throw 'Unsupported iPhone USB lock schema.' }
    $pin
}

function Get-ReimsIphoneUsbDriverFiles {
    @('libusb0.inf','libusb0.cat','amd64/libusb0.sys','amd64/libusb0.dll','x86/libusb0_x86.dll',
        'libusbK.dll','licenses/COPYING_GPL.txt','licenses/COPYING_LGPL.txt','licenses/LICENSE-libusbK-BSD.txt')
}

function Assert-ReimsIphoneUsbOrdinaryPath([string]$Path,[switch]$AllowMissing) {
    $full=[IO.Path]::GetFullPath($Path)
    for($part=$full;$part;$part=Split-Path -Parent $part) {
        if(Test-Path -LiteralPath $part) {
            if((Get-Item -LiteralPath $part -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse paths are refused for the iPhone USB package.' }
        } elseif($part -eq $full -and !$AllowMissing) { throw 'Required iPhone USB package path is missing.' }
    }
    $full
}

function Get-ReimsIphoneUsbDriverPackage([Parameter(Mandatory)][string]$Directory) {
    $root=Assert-ReimsIphoneUsbOrdinaryPath $Directory
    if(!(Test-Path -LiteralPath $root -PathType Container)) { throw 'iPhone USB package directory is missing.' }
    $manifestFile=Assert-ReimsIphoneUsbOrdinaryPath (Join-Path $root 'manifest.json')
    $info=Get-Item -LiteralPath $manifestFile
    if($info.PSIsContainer -or $info.Length -gt 65536) { throw 'Invalid bounded iPhone USB package manifest.' }
    $text=[IO.File]::ReadAllText($manifestFile)
    $document=[Text.Json.JsonDocument]::Parse($text)
    try {
        $properties=@($document.RootElement.EnumerateObject())
        if($properties.Count -ne 3 -or @($properties.Name|Sort-Object -Unique).Count -ne 3 -or
            @($properties.Name|Where-Object {$_ -cnotin @('schema','id','files')}).Count) { throw 'Invalid iPhone USB manifest fields.' }
        $m=$text | ConvertFrom-Json -AsHashtable
        $pin=Get-ReimsIphoneUsbDriverLock
        if(!($m.schema -is [int] -or $m.schema -is [long]) -or $m.schema -ne 1 -or $m.id -cne $pin.id -or $m.files -isnot [Collections.IDictionary]) { throw 'Unsupported iPhone USB manifest.' }
        $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $entries=@($document.RootElement.GetProperty('files').EnumerateObject())
        $expected=@(Get-ReimsIphoneUsbDriverFiles)
        if($entries.Count -ne $expected.Count) { throw 'iPhone USB manifest payload count mismatch.' }
        foreach($entry in $entries) {
            if(!$names.Add($entry.Name) -or $entry.Name -cnotin $expected -or $entry.Value.ValueKind -ne [Text.Json.JsonValueKind]::String -or
                $entry.Value.GetString() -cnotmatch '^[a-f0-9]{64}$') { throw 'Invalid/duplicate iPhone USB manifest payload.' }
        }
        # Recurse manually: inspect junctions before entering directories.
        $directories=[Collections.Generic.Queue[string]]::new();$directories.Enqueue($root);$files=0;$count=0
        while($directories.Count) {
            foreach($item in Get-ChildItem -LiteralPath $directories.Dequeue() -Force) {
                if(++$count -gt 32 -or $item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected/reparse iPhone USB package tree.' }
                if($item.PSIsContainer) { $directories.Enqueue($item.FullName);continue }
                $relative=[IO.Path]::GetRelativePath($root,$item.FullName).Replace('\','/')
                if($relative -ceq 'manifest.json') { continue }
                if($relative -cnotin $expected -or $item.Length -gt 4MB) { throw 'Unexpected iPhone USB payload file.' }
                if((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash -ine $m.files[$relative]) { throw 'iPhone USB payload hash mismatch.' }
                $files++
            }
        }
        if($files -ne $expected.Count) { throw 'Required iPhone USB payload is missing.' }
        Assert-ReimsUsbDriverBindingPackage (Join-Path $root 'libusb0.inf')
        $api=Get-Item -LiteralPath (Join-ReimsPackagePath $root $pin.api.file)
        if($api.Length -ne $pin.api.bytes -or (Get-FileHash -LiteralPath $api.FullName).Hash -ine $pin.api.sha256) { throw 'Pinned libusbK API hash mismatch.' }
        foreach($license in $pin.licenses) {
            $file=Get-Item -LiteralPath (Join-ReimsPackagePath $root ('licenses/'+$license.file))
            if($file.Length -ne $license.bytes -or (Get-FileHash -LiteralPath $file.FullName).Hash -ine $license.sha256) { throw 'Pinned USB license hash mismatch.' }
        }
        [pscustomobject]@{stageDirectory=$root;infPath=(Join-Path $root 'libusb0.inf');apiDll=$api.FullName;manifest=$m}
    } finally { $document.Dispose() }
}
