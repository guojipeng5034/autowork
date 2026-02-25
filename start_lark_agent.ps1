# 飞书 ↔ Cursor 一体化：收消息 → Cursor 处理 → 直接回复。一个脚本搞定。
# 用法: .\start_lark_agent.ps1   （在项目根执行）
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$agent = Join-Path $root ".cursor\skills\lark-listener\scripts\lark_agent.py"

if (-not (Test-Path $agent)) { Write-Error "未找到: $agent"; exit 1 }
Write-Host "Lark <-> Cursor: receive -> process -> reply. Ctrl+C to stop."
Write-Host "Use --agent-on-new to auto-start headless Agent on new message."
& python $agent --workspace $root --ack --agent-on-new
