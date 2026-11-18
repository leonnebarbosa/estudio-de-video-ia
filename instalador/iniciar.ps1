# Primeiro passo do instalador: baixa um Python minimo (11 MB, o "embeddable" oficial do python.org) e abre a pagina
# de boas-vindas no navegador. Todo o resto (ComfyUI, nos, dependencias, modelos) acontece pela pagina.
# Chamado por "Instalar estudio.bat". Rodar de novo so reabre a pagina.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$aqui = $PSScriptRoot
$pasta = Join-Path $aqui 'python'
$pyw = Join-Path $pasta 'pythonw.exe'
$baixados = Join-Path $aqui 'baixados'
$url = 'https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip'
$sha = '76F238F606250C87C6BEAC75DCCD35EE99070A13490555936ABB6CB64ECCE3D0'

Write-Host ''
Write-Host '  Estudio de video - instalador' -ForegroundColor Cyan
Write-Host ''

try {
    if (-not (Test-Path $pyw)) {
        Write-Host '  Baixando um Python minimo (11 MB)...'
        New-Item -ItemType Directory -Force $baixados | Out-Null
        $zip = Join-Path $baixados 'python-embed.zip'
        & curl.exe -sSL --fail --retry 3 -o $zip $url
        if ($LASTEXITCODE -ne 0) {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        }
        if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $sha) {
            Remove-Item $zip -Force
            throw 'O Python baixado veio diferente do esperado e foi descartado. Confira a internet e rode o instalador de novo.'
        }
        Expand-Archive -Path $zip -DestinationPath $pasta -Force
        Remove-Item $zip -Force
    }
    $onboarding = Join-Path $aqui 'onboarding.py'
    $endereco = Join-Path $baixados 'endereco.txt'
    New-Item -ItemType Directory -Force $baixados | Out-Null
    Remove-Item $endereco -Force -ErrorAction SilentlyContinue
    Start-Process -FilePath $pyw -ArgumentList @('-I', "`"$onboarding`"") -WorkingDirectory $aqui
    # A pagina escolhe a porta (a 8191 pode estar ocupada): espera ela dizer o endereco
    for ($i = 0; $i -lt 40 -and -not (Test-Path $endereco); $i++) { Start-Sleep -Milliseconds 250 }
    if (-not (Test-Path $endereco)) {
        throw 'A pagina do instalador nao abriu. Veja logs\instalacao.log na pasta do estudio.'
    }
    $url = (Get-Content $endereco -Raw).Trim()
    Write-Host '  Pronto: a pagina do instalador abriu no navegador.' -ForegroundColor Green
    Write-Host "  Se nao abriu, entre em $url"
    Write-Host '  Pode fechar esta janela.'
    Start-Sleep -Seconds 5
    exit 0
}
catch {
    Write-Host ''
    Write-Host ("  Erro: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host '  Sem internet? Confira a conexao e rode Instalar estudio.bat de novo.'
    exit 1
}
