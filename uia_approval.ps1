param([string]$Action = "approve", [switch]$Diagnose)

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$resultFile = Join-Path $PSScriptRoot "uia_result.txt"
function Write-Result([string]$msg) {
  try {
    [System.IO.File]::WriteAllText($resultFile, $msg,
      (New-Object System.Text.UTF8Encoding($false)))
  } catch {}
  Write-Output $msg
}

# Candidate button labels. Chinese labels are built via [char] codepoints
# so the script stays pure ASCII (Windows PowerShell 5.1 reads no-BOM files as ANSI).
$chAllow     = [string][char]0x5141 + [char]0x8BB8
$chAllowOnce = [string][char]0x5141 + [char]0x8BB8 + [char]0x4E00 + [char]0x6B21
$chAllowConv = [string][char]0x5141 + [char]0x8BB8 + [char]0x5BF9 + [char]0x8BDD
$chAlways    = [string][char]0x603B + [char]0x662F + [char]0x5141 + [char]0x8BB8
$chDeny      = [string][char]0x62D2 + [char]0x7EDD
$chDenyReq   = [string][char]0x62D2 + [char]0x7EDD + [char]0x8BF7 + [char]0x6C42

switch ($Action) {
  "approve" {
    $candidates = @(
      "Approve request", "Approve", "Allow request", "Allow",
      "Allow once", "Allow conversation",
      $chAllow, $chAllowOnce, $chAllowConv
    )
  }
  "always" {
    $candidates = @("Always allow", $chAlways)
  }
  "deny" {
    $candidates = @("Deny", "Decline request", "Decline", $chDeny, $chDenyReq)
  }
  "detect" {
    $candidates = @(
      "Approve request", "Approve", "Allow request", "Allow",
      "Allow once", "Allow conversation", "Always allow",
      "Deny", "Decline request", "Decline",
      $chAllow, $chAllowOnce, $chAllowConv, $chAlways, $chDeny, $chDenyReq
    )
  }
  default {
    $candidates = @("Approve request", "Approve", "Allow", "Allow once", "Deny", $chAllow, $chDeny)
  }
}

# 1) Find the Codex app main window by process first
#    The Codex desktop app window is hosted by the "ChatGPT" process on this machine.
$proc = Get-Process -ErrorAction SilentlyContinue |
  Where-Object {
    ($_.ProcessName -ieq "ChatGPT" -or $_.ProcessName -ieq "codex") -and
    $_.MainWindowHandle -ne 0
  } |
  Select-Object -First 1

$root = $null
if ($proc) {
  $root = [System.Windows.Automation.AutomationElement]::FromHandle($proc.MainWindowHandle)
} else {
  # 2) Fallback: enumerate visible top-level windows; match "ChatGPT",
  #    or "Codex" while excluding this pet's own windows (title contains pet names)
  Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class CodexWinEnum {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  public delegate bool EnumProc(IntPtr h, IntPtr lp);
}
"@
  $hwnd = [IntPtr]::Zero
  [CodexWinEnum]::EnumWindows({ param($h, $lp)
    if ([CodexWinEnum]::IsWindowVisible($h)) {
      $sb = New-Object System.Text.StringBuilder 512
      [CodexWinEnum]::GetWindowText($h, $sb, 512) | Out-Null
      $t = $sb.ToString()
      $isPet = ($t -match ([string][char]0x684C + [char]0x5BA0)) -or
               ($t -match ([string][char]0x5BA0 + [char]0x7269)) -or
               ($t -match ([string][char]0x5BA0 + [char]0x4E50))
      if ((-not $isPet) -and ($t -match "ChatGPT" -or $t -match "Codex")) {
        $script:hwnd = $h; return $false
      }
    }
    return $true
  }, [IntPtr]::Zero) | Out-Null
  if ($hwnd -ne [IntPtr]::Zero) {
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
  }
}

if ($null -eq $root) { Write-Result "NO_WINDOW"; exit 1 }

Start-Sleep -Milliseconds 800

if ($Diagnose) {
  Write-Result "DIAGNOSE"
  Write-Output ("WINDOW_TITLE=" + $root.Current.Name)
  $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                       [System.Windows.Automation.Condition]::TrueCondition)
  $count = 0
  foreach ($el in $all) {
    if ($count -ge 120) { break }
    $name = $el.Current.Name
    $ct = $el.Current.ControlType.ProgrammaticName
    $aid = $el.Current.AutomationId
    Write-Output ("ELEM name=[{0}] type=[{1}] aid=[{2}]" -f $name, $ct, $aid)
    $count++
  }
  exit 0
}

# Detect mode: probe for approval buttons only, never click.
# Returns FOUND:<button name> or NOT_FOUND. In "approve for me" mode the pet
# pops its approval window only when a real card exists (FOUND).
if ($Action -eq "detect") {
  function Find-Only([System.Windows.Automation.AutomationElement]$scope) {
    $btnCond = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::Button)
    $btns = $scope.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond)
    if ($null -ne $btns) {
      foreach ($b in $btns) {
        $n = $b.Current.Name
        if ($n -eq "") { continue }
        foreach ($name in $candidates) {
          if ($name -eq "") { continue }
          if ($n -ieq $name -or $n -like ("*" + $name + "*")) {
            Write-Result ("FOUND:" + $n)
            return $true
          }
        }
      }
    }
    return $false
  }
  if (Find-Only $root) { exit 0 }
  $desktop = [System.Windows.Automation.AutomationElement]::RootElement
  if (Find-Only $desktop) { exit 0 }
  Write-Result "NOT_FOUND"
  exit 2
}

$invokeType = [System.Windows.Automation.InvokePattern]::Pattern

function Find-And-Invoke([System.Windows.Automation.AutomationElement]$scope) {
  # Pass 1: exact Name match
  foreach ($name in $candidates) {
    if ($name -eq "") { continue }
    $cond = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::NameProperty, $name)
    $el = $scope.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
    if ($null -ne $el) {
      $pattern = $null
      if ($el.TryGetCurrentPattern($invokeType, [ref]$pattern)) {
        $pattern.Invoke()
        Write-Result ("CLICKED:" + $name)
        return $true
      }
    }
  }
  # Pass 2: Button controls whose Name CONTAINS a candidate (no reverse wildcard)
  $btnCond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button)
  $btns = $scope.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond)
  if ($null -ne $btns) {
    foreach ($b in $btns) {
      $n = $b.Current.Name
      if ($n -eq "") { continue }
      foreach ($name in $candidates) {
        if ($name -eq "") { continue }
        if ($n -ieq $name -or $n -like ("*" + $name + "*")) {
          $pattern = $null
          if ($b.TryGetCurrentPattern($invokeType, [ref]$pattern)) {
            $pattern.Invoke()
            Write-Result ("CLICKED_BTN:" + $n)
            return $true
          }
        }
      }
    }
  }
  return $false
}

if (Find-And-Invoke $root) { exit 0 }
$desktop = [System.Windows.Automation.AutomationElement]::RootElement
if (Find-And-Invoke $desktop) { exit 0 }

Write-Result "NOT_FOUND"
exit 2
