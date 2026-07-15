Set-Location "D:\work-ai\0401-lingclaw-to-langchain-demo\backend"
$env:PYTHONUNBUFFERED = "1"
$p = Start-Process python -ArgumentList "-u run_mcp_server.py" `
    -RedirectStandardOutput "D:\work-ai\0401-lingclaw-to-langchain-demo\storage\mcp_test.log" `
    -RedirectStandardError "D:\work-ai\0401-lingclaw-to-langchain-demo\storage\mcp_test.err" `
    -NoNewWindow -PassThru
Start-Sleep -Seconds 10
if (-not $p.HasExited) {
    Write-Host "STILL_RUNNING pid=$($p.Id)"
    Stop-Process -Id $p.Id -Force
} else {
    Write-Host "EXITED code=$($p.ExitCode)"
}
