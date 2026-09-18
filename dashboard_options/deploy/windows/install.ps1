$ErrorActionPreference='Stop'
$base='C:\OptionsDashboard'
$jinke='C:\JinkeDashboard'
if (!(Test-Path "$jinke\conda\python.exe")) { throw 'Existing server Python runtime unavailable' }
New-Item -ItemType Directory -Force "$base\app\logs" | Out-Null
$env:PYTHONUTF8='1'; $env:GJ_SCRIPTS="$jinke\gjdata\scripts"
& "$jinke\conda\python.exe" "$base\app\update.py"
if ($LASTEXITCODE -ne 0) { throw 'Initial options dashboard generation failed' }
$action=New-ScheduledTaskAction -Execute "$base\app\deploy\windows\update.cmd" -WorkingDirectory "$base\app"
$trigger=New-ScheduledTaskTrigger -Daily -At '03:45'
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName 'OptionsDashboard-Update' -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
# Keep the existing root page intact and add only a stripped /options/ route.
$caddy=@'
{
    admin off
    default_sni 8.155.134.13
}
https://8.155.134.13 {
    tls {
        issuer acme {
            dir https://acme-v02.api.letsencrypt.org/directory
            profile shortlived
        }
    }
    header Cache-Control "no-store"
    handle_path /options/* {
        root * C:/OptionsDashboard/app/output
        file_server
    }
    handle {
        root * C:/JinkeDashboard/app/output
        file_server
    }
}
'@
$caddyFile="$jinke\Caddyfile"
$caddyCandidate="$jinke\Caddyfile.options-candidate"
$caddyBackup="$jinke\Caddyfile.before-options-$(Get-Date -Format 'yyyyMMddHHmmss').bak"
Copy-Item -Path $caddyFile -Destination $caddyBackup -Force
Set-Content -Path $caddyCandidate -Value $caddy -Encoding utf8
$validateOut="$base\app\logs\caddy-validate.stdout"
$validateErr="$base\app\logs\caddy-validate.stderr"
# Caddy writes informational logs to stderr even when validation succeeds.
# Redirect both streams so PSRP receives only genuine script failures.
$validation=Start-Process -FilePath "$jinke\caddy.exe" -ArgumentList @('validate','--config',$caddyCandidate,'--adapter','caddyfile') -Wait -PassThru -NoNewWindow -RedirectStandardOutput $validateOut -RedirectStandardError $validateErr
if ($validation.ExitCode -ne 0) {
    Remove-Item $caddyCandidate -Force -ErrorAction SilentlyContinue
    throw "Caddy candidate validation failed; existing configuration was retained and web task not restarted. $(Get-Content $validateErr -Raw)"
}
Move-Item -Path $caddyCandidate -Destination $caddyFile -Force
Stop-ScheduledTask -TaskName 'JinkeDashboard-Web' -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName 'JinkeDashboard-Web'
Write-Output 'Options dashboard installed at /options/ and root dashboard retained.'
