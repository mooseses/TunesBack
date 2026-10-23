# Smoke test for the packaged Windows app.
# Starts it, drives the custom title bar with real mouse input and reports what
# happened. Fails only if the app crashes or never shows a window.
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$Fixtures,
    [string]$Screenshots = "false"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[Win]::SetProcessDPIAware() | Out-Null

# Fresh profile, so the app opens on its first-run set-up.
$config = Join-Path $env:APPDATA "TunesBack"
New-Item -ItemType Directory -Force -Path $config | Out-Null
@{ debug_logging = $true; theme = "dark" } |
    ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $config "settings.json")

function Rect($h) { $r = New-Object Win+RECT; [Win]::GetWindowRect($h, [ref]$r) | Out-Null; $r }
function Show($label, $r) { "{0,-10} x={1} y={2} w={3} h={4}" -f $label, $r.Left, $r.Top, ($r.Right - $r.Left), ($r.Bottom - $r.Top) }
function Down { [Win]::mouse_event(0x2, 0, 0, 0, [UIntPtr]::Zero) }
function Up { [Win]::mouse_event(0x4, 0, 0, 0, [UIntPtr]::Zero) }
function Drag($x, $y, $dx, $dy) {
    [Win]::SetCursorPos($x, $y) | Out-Null; Start-Sleep -Milliseconds 200; Down; Start-Sleep -Milliseconds 200
    for ($i = 1; $i -le 10; $i++) { [Win]::SetCursorPos($x + $dx * $i / 10, $y + $dy * $i / 10) | Out-Null; Start-Sleep -Milliseconds 40 }
    Start-Sleep -Milliseconds 200; Up; Start-Sleep -Milliseconds 800
}
function Click($x, $y) { [Win]::SetCursorPos($x, $y) | Out-Null; Start-Sleep -Milliseconds 150; Down; Up; Start-Sleep -Milliseconds 120 }
function Shot($name) {
    if ($Screenshots -ne "true") { return }
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $small = New-Object System.Drawing.Bitmap $bmp, ([int]($b.Width / 2)), ([int]($b.Height / 2))
    $ms = New-Object System.IO.MemoryStream
    $codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq "image/jpeg" }
    $params = New-Object System.Drawing.Imaging.EncoderParameters 1
    $params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter ([System.Drawing.Imaging.Encoder]::Quality), 60L
    $small.Save($ms, $codec, $params)
    $data = [Convert]::ToBase64String($ms.ToArray())
    for ($i = 0; $i -lt $data.Length; $i += 4000) { "SHOT $name " + $data.Substring($i, [Math]::Min(4000, $data.Length - $i)) }
    "SHOT $name END"
}
Add-Type -AssemblyName System.Windows.Forms

$proc = Start-Process -FilePath $Exe -PassThru
$hwnd = [IntPtr]::Zero
for ($i = 0; $i -lt 120 -and $hwnd -eq [IntPtr]::Zero; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { break }
    $proc.Refresh(); $hwnd = $proc.MainWindowHandle
}
$log = Join-Path $env:LOCALAPPDATA "TunesBack\Logs\tunesback.log"
if ($hwnd -eq [IntPtr]::Zero) {
    "FAIL: no window (exited: $($proc.HasExited))"
    if (Test-Path $log) { Get-Content $log -Tail 60 }
    exit 1
}
Start-Sleep -Seconds 12
[Win]::SetForegroundWindow($hwnd) | Out-Null; Start-Sleep -Milliseconds 500

# Runner screens are small (1024x768), so keep every point we touch on screen:
# move a little, then resize from the top-left corner (the taskbar covers the bottom).
$r = Rect $hwnd; Show "start" $r; Shot "start"
Drag ($r.Left + 600) ($r.Top + 19) (-10) 30
$r2 = Rect $hwnd; Show "dragged" $r2
Drag ($r2.Left + 3) ($r2.Top + 3) (-8) (-50)
$r3 = Rect $hwnd; Show "resized" $r3
Click ($r3.Left + 152) ($r3.Top + 19); Start-Sleep -Milliseconds 600; Shot "menu"
[System.Windows.Forms.SendKeys]::SendWait("{ESC}"); Start-Sleep -Milliseconds 400   # close the menu
Click ($r3.Left + 700) ($r3.Top + 19); Click ($r3.Left + 700) ($r3.Top + 19); Start-Sleep -Seconds 1
$r4 = Rect $hwnd; Show "dblclick" $r4; "maximized: $([Win]::IsZoomed($hwnd))"; Shot "maximized"
Click ($r4.Right - 23) ($r4.Top + 19)
$proc.WaitForExit(8000) | Out-Null
"closed by close button: $($proc.HasExited)"
if (-not $proc.HasExited) { $proc.Kill() }
if (Test-Path $log) { "--- app log ---"; Get-Content $log -Tail 40 }
exit 0
