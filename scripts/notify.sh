#!/usr/bin/env bash
# =====================================================================
#  Show a Windows desktop notification from Ubuntu (WSL).
#    bash /mnt/e/PG_OCR/scripts/notify.sh "Title" "Message"
#  Uses only built-in Windows PowerShell (no installation needed).
#  If toast notifications are blocked, a small message box appears instead.
# =====================================================================
TITLE="${1:-PG OCR}"
MSG="${2:-Done}"

export PGN_TITLE="$TITLE" PGN_MSG="$MSG"
# pass the two variables (UTF-8, Chinese/Greek OK) to the Windows side
export WSLENV="${WSLENV:+$WSLENV:}PGN_TITLE/u:PGN_MSG/u"

PS=powershell.exe
command -v "$PS" >/dev/null 2>&1 || PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe

if [ -x "$PS" ] || command -v "$PS" >/dev/null 2>&1; then
    # run in the background so a fallback message box never blocks the terminal
    ( "$PS" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command '
        try {
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
            $x  = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $tx = $x.GetElementsByTagName("text")
            $tx.Item(0).AppendChild($x.CreateTextNode($env:PGN_TITLE)) | Out-Null
            $tx.Item(1).AppendChild($x.CreateTextNode($env:PGN_MSG))   | Out-Null
            $app = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show(
                [Windows.UI.Notifications.ToastNotification]::new($x))
        } catch {
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.MessageBox]::Show($env:PGN_MSG, $env:PGN_TITLE) | Out-Null
        }' >/dev/null 2>&1 & )
fi
printf '\a'          # terminal bell as well
echo "[notify] $TITLE - $MSG"
