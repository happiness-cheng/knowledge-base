# Knowledge Base - Auto Test Runner
# Runs pytest periodically until 2026-06-07
# Pops up a dialog when tests fail

$ErrorActionPreference = "SilentlyContinue"
$KB_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND_DIR = Join-Path $KB_DIR "backend"
$PYTEST = Join-Path $BACKEND_DIR "venv\Scripts\python.exe"
$LOG_FILE = Join-Path $KB_DIR "auto_test.log"
$INTERVAL_SECONDS = 1800  # 30 minutes
$END_DATE = [datetime]"2026-06-08"

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts | $msg" | Out-File -Append -FilePath $LOG_FILE -Encoding utf8
}

function Run-Tests {
    Write-Log "Running pytest..."
    $output = & $PYTEST -m pytest "tests/" -q --tb=line 2>&1
    $exitCode = $LASTEXITCODE
    $outputStr = $output -join "`n"
    Write-Log "Exit code: $exitCode"

    if ($exitCode -ne 0) {
        Write-Log "FAILURES DETECTED"
        # Extract failure summary (last few lines)
        $failLines = ($output | Where-Object { $_ -match "FAILED|failed|error" }) -join "`n"
        if (-not $failLines) { $failLines = $outputStr.Substring([Math]::Max(0, $outputStr.Length - 500)) }

        # Show Windows popup
        $msg = "知识库后端测试发现失败！`n`n$failLines`n`n是否要我现在修复？`n(点击是 = 在 Claude Code 中修复)`n(点击否 = 跳过本轮)"
        $result = [System.Windows.Forms.MessageBox]::Show(
            $msg,
            "知识库自动测试 - 发现问题",
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )

        if ($result -eq [System.Windows.Forms.DialogResult]::Yes) {
            Write-Log "User chose YES - requesting fix"
            # Write a flag file that Claude Code can pick up
            "FIX_NEEDED`n$failLines" | Out-File -FilePath (Join-Path $KB_DIR "NEEDS_FIX.txt") -Encoding utf8
        } else {
            Write-Log "User chose NO - skipping"
        }
    } else {
        Write-Log "All tests passed"
        # Remove flag file if exists
        $flagFile = Join-Path $KB_DIR "NEEDS_FIX.txt"
        if (Test-Path $flagFile) { Remove-Item $flagFile }
    }
}

# Load Windows Forms for MessageBox
Add-Type -AssemblyName System.Windows.Forms

Write-Log "=== Auto Test Runner Started ==="
Write-Log "Backend: $BACKEND_DIR"
Write-Log "Interval: $($INTERVAL_SECONDS)s"
Write-Log "End date: $END_DATE"

while ((Get-Date) -lt $END_DATE) {
    if (Test-Path (Join-Path $BACKEND_DIR "venv\Scripts\python.exe")) {
        Push-Location $BACKEND_DIR
        Run-Tests
        Pop-Location
    } else {
        Write-Log "WARNING: venv not found, skipping"
    }

    $now = Get-Date
    if ($now -ge $END_DATE) {
        Write-Log "=== End date reached, stopping ==="
        break
    }

    Write-Log "Next run in $($INTERVAL_SECONDS)s..."
    Start-Sleep -Seconds $INTERVAL_SECONDS
}

Write-Log "=== Auto Test Runner Stopped ==="
