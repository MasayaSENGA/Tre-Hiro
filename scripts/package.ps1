# トレひろ - Chrome ウェブストア提出用 zip を作成する
#
# 使い方（リポジトリのルートで実行）:
#   powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1
#
# 出力: dist\tre-hiro-v<version>.zip
#   manifest.json の version を読み取ってファイル名に使う。
#   拡張機能の実行に必要なファイルだけを入れる（README.md, .claude/ などは含めない）。

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'manifest.json') | ConvertFrom-Json
$version = $manifest.version

# 配布物に含めるファイル
$files = @(
  'manifest.json',
  'shared.js',
  'content.js',
  'colorize.js',
  'autobuttons.js',
  'cardurl.js',
  'cardhistory.js',
  'listid.js',
  'shortcut.js',
  'content.css',
  'popup.html',
  'popup.css',
  'popup.js'
)
$dirs = @('icons')

# zip に入れるファイルの一覧（ディスク上のパス, zip 内の名前）
$entries = New-Object System.Collections.Generic.List[object]
foreach ($f in $files) {
  $src = Join-Path $root $f
  if (-not (Test-Path $src -PathType Leaf)) { throw "必要なファイルがありません: $f" }
  $entries.Add([pscustomobject]@{ Path = $src; Name = $f })
}
foreach ($d in $dirs) {
  Get-ChildItem (Join-Path $root $d) -Recurse -File | Sort-Object FullName | ForEach-Object {
    $entries.Add([pscustomobject]@{ Path = $_.FullName; Name = $_.FullName.Substring($root.Length + 1).Replace('\', '/') })
  }
}

# manifest.json が参照しているファイルが、すべて zip に入るかを確かめる
$names = $entries | ForEach-Object { $_.Name }
$refs = New-Object System.Collections.Generic.List[string]
if ($manifest.icons) { $manifest.icons.PSObject.Properties | ForEach-Object { $refs.Add($_.Value) } }
if ($manifest.action) {
  if ($manifest.action.default_popup) { $refs.Add($manifest.action.default_popup) }
  if ($manifest.action.default_icon) { $manifest.action.default_icon.PSObject.Properties | ForEach-Object { $refs.Add($_.Value) } }
}
foreach ($cs in @($manifest.content_scripts)) {
  foreach ($p in @($cs.js) + @($cs.css)) { if ($p) { $refs.Add($p) } }
}
$missing = $refs | Where-Object { $names -notcontains $_ } | Sort-Object -Unique
if ($missing) { throw "manifest.json が参照しているファイルが zip に入りません: $($missing -join ', ')" }

$dist = Join-Path $root 'dist'
New-Item -ItemType Directory -Force $dist | Out-Null
$zip = Join-Path $dist "tre-hiro-v$version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

# Compress-Archive や ZipFile.CreateFromDirectory は Windows PowerShell 5.1 上では
# zip 内のパス区切りに "\" を使ってしまい（icons\icon16.png）、Chrome ウェブストア側で
# アイコンが見つからない原因になる。そのためエントリ名を "/" 区切りで明示して 1 件ずつ追加する。
# また PS 5.1 ではスクリプト内で [IO.Compression.ZipFile] 型リテラルが解決できないことが
# あるため、アセンブリから型を直接取り出す。
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$fsAsm = [AppDomain]::CurrentDomain.GetAssemblies() |
  Where-Object { $_.GetName().Name -eq 'System.IO.Compression.FileSystem' } |
  Select-Object -First 1
if (-not $fsAsm) { throw 'System.IO.Compression.FileSystem を読み込めませんでした' }
$zipFile = $fsAsm.GetType('System.IO.Compression.ZipFile')
$zipExt = $fsAsm.GetType('System.IO.Compression.ZipFileExtensions')

$archive = $zipFile::Open($zip, 'Create')
try {
  foreach ($e in $entries) {
    [void]$zipExt::CreateEntryFromFile($archive, $e.Path, $e.Name)
  }
} finally {
  $archive.Dispose()
}

Write-Host "作成しました: $zip" -ForegroundColor Green
Write-Host "--- 内容 ---"
$archive = $zipFile::OpenRead($zip)
try {
  $archive.Entries | ForEach-Object { Write-Host ("  {0,8:N0} bytes  {1}" -f $_.Length, $_.FullName) }
} finally {
  $archive.Dispose()
}
