# record_hr_session.ps1 --- just a placeholder
param(
    [string]$StreamBase = "hr_stream",
    [string]$LogsDir    = "..\outputs\hr_logs"
)

# 1) Activate venv (assumes this script lives in 'code/')
.\..\ .venv\Scripts\Activate.ps1

# 2) Compute stream file name using timestamp
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$streamFile = Join-Path $LogsDir "$StreamBase`_$timestamp.jsonl"

Write-Host "Recording to $streamFile ..."
python ant_hr_to_json.py > $streamFile

# Then you'd run step 2 manually by  ..\outputs\hr_logs\hr_stream_20251212_204159.jsonl | python ant_to_csv.py
