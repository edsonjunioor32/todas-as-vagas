param([int]$Port = 8765)

$Root = Join-Path $PSScriptRoot 'site'
if (-not (Test-Path $Root -PathType Container)) {
  Write-Host 'Pasta site nao encontrada.' -ForegroundColor Red
  Read-Host 'Pressione Enter para sair'
  exit 1
}

$listener = New-Object System.Net.HttpListener
$prefix = "http://localhost:$Port/"
$listener.Prefixes.Add($prefix)

try {
  $listener.Start()
} catch {
  Write-Host "Nao foi possivel iniciar o preview em $prefix" -ForegroundColor Red
  Write-Host $_.Exception.Message
  Read-Host 'Pressione Enter para sair'
  exit 1
}

$mime = @{
  '.html'='text/html; charset=utf-8'; '.js'='text/javascript; charset=utf-8'; '.mjs'='text/javascript; charset=utf-8';
  '.css'='text/css; charset=utf-8'; '.json'='application/json; charset=utf-8'; '.svg'='image/svg+xml';
  '.png'='image/png'; '.jpg'='image/jpeg'; '.jpeg'='image/jpeg'; '.webp'='image/webp'; '.ico'='image/x-icon';
  '.txt'='text/plain; charset=utf-8'; '.wasm'='application/wasm'
}

Write-Host ''
Write-Host 'Preview local do Todas as Vagas iniciado.' -ForegroundColor Green
Write-Host "Endereco: $prefix"
Write-Host 'Feche esta janela ou pressione Ctrl+C para encerrar.'
Write-Host ''
Start-Process $prefix

$rootFull = [IO.Path]::GetFullPath($Root)
try {
  while ($listener.IsListening) {
    $context = $listener.GetContext()
    try {
      $relative = [Uri]::UnescapeDataString($context.Request.Url.AbsolutePath.TrimStart('/'))
      if ([string]::IsNullOrWhiteSpace($relative)) { $relative = 'index.html' }
      $candidate = Join-Path $Root ($relative -replace '/', [IO.Path]::DirectorySeparatorChar)
      $full = [IO.Path]::GetFullPath($candidate)
      if (-not $full.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        $context.Response.StatusCode = 403
        $context.Response.Close()
        continue
      }
      if (Test-Path $full -PathType Container) { $full = Join-Path $full 'index.html' }
      if (-not (Test-Path $full -PathType Leaf)) {
        $context.Response.StatusCode = 404
        $context.Response.Close()
        continue
      }
      $ext = [IO.Path]::GetExtension($full).ToLowerInvariant()
      $contentType = if ($mime.ContainsKey($ext)) { $mime[$ext] } else { 'application/octet-stream' }
      $bytes = [IO.File]::ReadAllBytes($full)
      $context.Response.StatusCode = 200
      $context.Response.ContentType = $contentType
      $context.Response.ContentLength64 = $bytes.Length
      $context.Response.Headers['Cache-Control'] = 'no-store'
      $context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
      $context.Response.OutputStream.Close()
    } catch {
      try { $context.Response.StatusCode = 500; $context.Response.Close() } catch {}
    }
  }
} finally {
  $listener.Stop()
  $listener.Close()
}
