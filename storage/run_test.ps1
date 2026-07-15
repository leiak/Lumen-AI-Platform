$ErrorActionPreference = "Continue"
Set-Location "D:\work-ai\0401-lingclaw-to-langchain-demo\backend"
$p = Start-Process python -ArgumentList "run_mcp_server.py" `
    -RedirectStandardOutput "D:\work-ai\0401-lingclaw-to-langchain-demo\storage\mcp_server_test.log" `
    -RedirectStandardError "D:\work-ai\0401-lingclaw-to-langchain-demo\storage\mcp_server_test.err" `
    -NoNewWindow -PassThru
Start-Sleep -Seconds 12
if (-not $p.HasExited) {
    Write-Host "STILL_RUNNING pid=$($p.Id)"
    Stop-Process -Id $p.Id -Force
} else {
    Write-Host "EXITED code=$($p.ExitCode)"
}
