# Abre o ComfyUI em modo de pouca VRAM (para modelos maiores que a 3080, como o MiniMax H3)
# e grava tudo que aparece na janela em logs\comfyui_<data>.log
#   --disable-pinned-memory : nao trava 13 GB de RAM (com 32 GB e modelo de 36 GB isso estrangula o Windows)
#   --cache-none            : solta o codificador de texto antes de carregar o modelo de video
#   --fast-disk             : le o modelo direto do NVMe em vez de segurar tudo na RAM
# O ComfyUI portatil dentro desta pasta (onde o instalador o poe) ou ao lado dela
$raiz = Join-Path $PSScriptRoot 'ComfyUI_windows_portable'
if (-not (Test-Path $raiz)) { $raiz = Join-Path (Split-Path $PSScriptRoot) 'ComfyUI_windows_portable' }
$logs = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs ("comfyui_{0:yyyyMMdd_HHmm}.log" -f (Get-Date))
Write-Output "log: $log"
Set-Location $raiz
# Sem isto a saida em pipe fica em cp1252: um print com emoji (ex.: o upscaler H3 com force_unload) mata a thread da fila
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
cmd /c ".\python_embeded\python.exe -u -s ComfyUI\main.py --windows-standalone-build --lowvram --reserve-vram 1.5 --disable-pinned-memory --cache-none --fast-disk 2>&1" | Tee-Object -FilePath $log
