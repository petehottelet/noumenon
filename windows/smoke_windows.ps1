param(
    [string]$Binary = (Join-Path $PSScriptRoot '..\dist\Noumenon.scr'),
    [string]$Output = (Join-Path ([IO.Path]::GetTempPath()) 'noumenon-windows-smoke.png'),
    [string]$CatalogManifest = (Join-Path $PSScriptRoot '..\native-catalog.json')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Runtime.InteropServices;

public static class GlyphSmokePixels
{
    public static int[] Capture(Bitmap bitmap)
    {
        var pixels = new int[((bitmap.Width + 3) / 4) * ((bitmap.Height + 3) / 4)];
        int index = 0;
        for (int y = 0; y < bitmap.Height; y += 4)
            for (int x = 0; x < bitmap.Width; x += 4)
                pixels[index++] = bitmap.GetPixel(x, y).ToArgb();
        return pixels;
    }

    public static int[] Inspect(int[] pixels, int[] before)
    {
        int green = 0, dark = 0, changed = 0;
        for (int i = 0; i < pixels.Length; i++)
        {
            Color pixel = Color.FromArgb(pixels[i]);
            if (pixel.G > 60 && pixel.G > pixel.R * 1.15 && pixel.G > pixel.B * 1.15) green++;
            if (Math.Max(pixel.R, Math.Max(pixel.G, pixel.B)) < 20) dark++;
            if (before != null)
            {
                Color prior = Color.FromArgb(before[i]);
                if (Math.Abs(pixel.R - prior.R) + Math.Abs(pixel.G - prior.G)
                    + Math.Abs(pixel.B - prior.B) > 12) changed++;
            }
        }
        return new int[] { pixels.Length, green, dark, changed };
    }
}

public static class GlyphSmokeWindow
{
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, IntPtr className, IntPtr title);
    [DllImport("user32.dll")]
    public static extern IntPtr GetParent(IntPtr window);
    [DllImport("user32.dll")]
    public static extern bool GetClientRect(IntPtr window, out RECT rectangle);
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
}
'@

function Inspect-Frame([Drawing.Bitmap]$Bitmap, [int[]]$Before = $null) {
    $samples = [GlyphSmokePixels]::Capture($Bitmap)
    $counts = [GlyphSmokePixels]::Inspect($samples, $Before)
    $greenFraction = $counts[1] / [double]$counts[0]
    $darkFraction = $counts[2] / [double]$counts[0]
    $changedFraction = $counts[3] / [double]$counts[0]
    if ($greenFraction -lt 0.005 -or $greenFraction -gt 0.75 -or $darkFraction -lt 0.10) {
        throw "Native frame lacks glyphs or black gaps: green=$greenFraction dark=$darkFraction"
    }
    if ($null -ne $Before -and $changedFraction -lt 0.005) {
        throw "Native scene did not animate: changed=$changedFraction"
    }
    return [ordered]@{
        width = $Bitmap.Width
        height = $Bitmap.Height
        sampled_pixels = $counts[0]
        green_pixels = $counts[1]
        dark_pixels = $counts[2]
        changed_pixels = $counts[3]
        green_fraction = $greenFraction
        dark_fraction = $darkFraction
        changed_fraction = $changedFraction
    }
}

function Test-PreviewProcess([string]$BinaryPath) {
    $hostForm = [Windows.Forms.Form]::new()
    $process = $null
    try {
        $hostForm.ClientSize = [Drawing.Size]::new(320, 180)
        # Handle creation does not show the parent; its child cannot become visible.
        $parentHandle = $hostForm.Handle
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = (Resolve-Path -LiteralPath $BinaryPath).Path
        $start.Arguments = '/p ' + $parentHandle.ToInt64()
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
        $process = [Diagnostics.Process]::Start($start)
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        $child = [IntPtr]::Zero
        do {
            [Windows.Forms.Application]::DoEvents()
            $child = [GlyphSmokeWindow]::FindWindowEx($parentHandle, [IntPtr]::Zero, [IntPtr]::Zero, [IntPtr]::Zero)
            if ($child -ne [IntPtr]::Zero -or $process.HasExited) { break }
            Start-Sleep -Milliseconds 50
        } while ([DateTime]::UtcNow -lt $deadline)
        if ($child -eq [IntPtr]::Zero -or $process.HasExited) {
            throw "Compiled /p entrypoint did not attach a live preview child (exited=$($process.HasExited), parent=$parentHandle)"
        }
        $rectangle = [GlyphSmokeWindow+RECT]::new()
        if (-not [GlyphSmokeWindow]::GetClientRect($child, [ref]$rectangle) -or
            $rectangle.Right -ne 320 -or $rectangle.Bottom -ne 180 -or
            [GlyphSmokeWindow]::GetParent($child) -ne $parentHandle) {
            throw 'Compiled /p entrypoint attached the wrong preview geometry or parent'
        }
        if ([GlyphSmokeWindow]::IsWindowVisible($parentHandle) -or
            [GlyphSmokeWindow]::IsWindowVisible($child)) {
            throw 'Preview smoke unexpectedly displayed a native window'
        }
        [GlyphSmokeWindow]::PostMessage($child, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        while (-not $process.HasExited -and [DateTime]::UtcNow -lt $deadline) {
            [Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 25
        }
        if (-not $process.HasExited -or $process.ExitCode -ne 0) {
            throw 'Compiled /p preview failed to close cleanly'
        }
        return [ordered]@{
            status = 'passed'
            argument = '/p'
            width = 320
            height = 180
            parent_hidden = $true
            child_hidden = $true
            clean_exit = $true
        }
    } finally {
        if ($null -ne $process) {
            if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
            $process.Dispose()
        }
        $hostForm.Dispose()
    }
}

function Invoke-LiveReport([string]$BinaryPath, [string]$Folder, [string]$ReportPath) {
    # CreateProcess, not the shell: the shell opens a .scr as a fullscreen saver.
    $start = [Diagnostics.ProcessStartInfo]::new((Resolve-Path -LiteralPath $BinaryPath).Path,
        "/live-report `"$Folder`" `"$ReportPath`"")
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $process = [Diagnostics.Process]::Start($start)
    try {
        if (-not $process.WaitForExit(30000)) { $process.Kill(); throw "/live-report did not finish: $Folder" }
        if ($process.ExitCode -ne 0) { throw "/live-report failed with exit $($process.ExitCode)" }
    } finally { $process.Dispose() }
}

function Test-LiveFeed($Assembly, [Type]$FormType, [string]$BinaryPath, [string]$OutputPath) {
    # The same fixture and edge cases every native port is checked against.
    $root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $python) { throw 'The live feed check needs Python on PATH' }
    $fixture = Join-Path $root 'tests\fixtures\live-feed'
    $edgeFeed = Join-Path ([IO.Path]::GetTempPath()) ('noumenon-live-feed-' + [Guid]::NewGuid().ToString('N'))
    Push-Location $root
    try {
        & $python.Source -m live.feedcheck build $edgeFeed | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not build the live feed test folder' }
        $reports = [ordered]@{}
        foreach ($case in @(@('fixture', $fixture), @('edge_cases', $edgeFeed))) {
            $reportPath = [IO.Path]::ChangeExtension($OutputPath, "live-$($case[0]).json")
            Invoke-LiveReport $BinaryPath $case[1] $reportPath
            $checked = & $python.Source -m live.feedcheck check $case[1] $reportPath
            if ($LASTEXITCODE -ne 0) { throw "Live feed report differs ($($case[0]))" }
            $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
            $reports[$case[0]] = [ordered]@{ files = $report.files; live = $report.live;
                rejected = @($report.rejected).Count; pool = $report.pool; check = "$checked" }
        }
    } finally {
        Pop-Location
        if (Test-Path -LiteralPath $edgeFeed) { Remove-Item -LiteralPath $edgeFeed -Recurse -Force -Confirm:$false }
    }

    $staticFlags = [Reflection.BindingFlags]'Static,NonPublic'
    $flags = [Reflection.BindingFlags]'Instance,NonPublic'
    $liveType = $Assembly.GetType('Noumenon.LiveGlyphs', $true)
    $liveType.GetMethod('Use', $staticFlags).Invoke($null, @([string]$fixture)) | Out-Null
    $liveForm = $null
    try {
        $atlas = $liveType.GetMethod('Atlas', $staticFlags).Invoke($null, $null)
        try { $atlas.Save([IO.Path]::ChangeExtension($OutputPath, 'live.png'), [Drawing.Imaging.ImageFormat]::Png) }
        finally { $atlas.Dispose() }
        $liveForm = [Activator]::CreateInstance($FormType, $flags, $null,
            @([Drawing.Rectangle]::new(0, 0, 1280, 720), $true, $false), $null)
        $FormType.GetMethod('OnLoad', $flags).Invoke($liveForm, @([EventArgs]::Empty)) | Out-Null
        $FormType.GetField('_timer', $flags).GetValue($liveForm).Stop()
        $draw = $FormType.GetMethod('DrawFrame', $flags)
        for ($frame = 0; $frame -lt 90; $frame++) { $draw.Invoke($liveForm, @([single]0.025)) | Out-Null }
        $drawnLive = 0L
        foreach ($layer in $FormType.GetField('_layers', $flags).GetValue($liveForm)) {
            $drawnLive += $layer.GetType().GetField('DrawnLive', $flags).GetValue($layer)
        }
        if ($drawnLive -le 0) { throw 'Live glyphs were read but never drawn' }
        $bitmap = $FormType.GetField('_buffer', $flags).GetValue($liveForm)
        $frame = Inspect-Frame $bitmap
        $bitmap.Save([IO.Path]::ChangeExtension($OutputPath, 'live-frame.png'), [Drawing.Imaging.ImageFormat]::Png)
    } finally {
        if ($null -ne $liveForm) { $liveForm.Dispose() }
        $liveType.GetMethod('Use', $staticFlags).Invoke($null, @($null)) | Out-Null
    }
    return [ordered]@{ status = 'passed'; reports = $reports; drawn_live = $drawnLive; frame = $frame }
}

$outputPath = [IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($outputPath)) | Out-Null
$assembly = [Reflection.Assembly]::LoadFile((Resolve-Path -LiteralPath $Binary).Path)
$formType = $assembly.GetType('Noumenon.SaverForm', $true)
$flags = [Reflection.BindingFlags]'Instance,NonPublic'
$staticFlags = [Reflection.BindingFlags]'Static,NonPublic'
$diagnostics = $assembly.GetType('Noumenon.CatalogDiagnostics', $true)
$catalog = $diagnostics.GetMethod('Verify', $staticFlags).Invoke($null, $null)
$expectedCatalog = Get-Content -LiteralPath $CatalogManifest -Raw | ConvertFrom-Json
if ($catalog.catalog_sha256 -ne $expectedCatalog.catalog_sha256 -or
    $catalog.reference_sha256 -ne $expectedCatalog.source_sha256.'svg-preview/reference/catalog.json' -or
    $catalog.original_sha256 -ne $expectedCatalog.source_sha256.'catalog/manifest.json') {
    throw 'Compiled catalog identities do not match the expected native catalog manifest'
}
$binaryVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo((Resolve-Path -LiteralPath $Binary).Path).FileVersion
if ($binaryVersion -ne '1.1.0.0') { throw "Unexpected screensaver version: $binaryVersion" }
$atlas = $diagnostics.GetMethod('Atlas', $staticFlags).Invoke($null, $null)
try { $atlas.Save([IO.Path]::ChangeExtension($outputPath, 'catalog.png'), [Drawing.Imaging.ImageFormat]::Png) }
finally { $atlas.Dispose() }
$licenseStream = $assembly.GetManifestResourceStream('Noumenon.ReferenceLicense')
if ($null -eq $licenseStream) { throw 'The compiled screensaver is missing its MIT notice' }
$licenseReader = [IO.StreamReader]::new($licenseStream)
try { $license = $licenseReader.ReadToEnd() } finally { $licenseReader.Dispose() }
if (-not $license.Contains('Permission is hereby granted') -or -not $license.Contains('Rezmason')) {
    throw 'The embedded reference artwork license is incomplete'
}
$form = [Activator]::CreateInstance(
    $formType, $flags, $null,
    @([Drawing.Rectangle]::new(0, 0, 1280, 720), $true, $false), $null
)
try {
    # Exercise the compiled form's load path and renderer without showing a window.
    $formType.GetMethod('OnLoad', $flags).Invoke($form, @([EventArgs]::Empty)) | Out-Null
    # Advance deterministic frames directly; keep its timer out of the parent
    # message pump used by the separate preview-process integration check.
    $formType.GetField('_timer', $flags).GetValue($form).Stop()
    $field = $formType.GetField('_buffer', $flags)
    $bitmap = $field.GetValue($form)
    $initialSamples = [GlyphSmokePixels]::Capture($bitmap)
    $initial = Inspect-Frame $bitmap
    $bitmap.Save([IO.Path]::ChangeExtension($outputPath, 'initial.png'), [Drawing.Imaging.ImageFormat]::Png)
    $draw = $formType.GetMethod('DrawFrame', $flags)
    for ($frame = 0; $frame -lt 90; $frame++) {
        $draw.Invoke($form, @([single]0.025)) | Out-Null
    }
    $bitmap = $field.GetValue($form)
    $animated = Inspect-Frame $bitmap $initialSamples
    $drawn = [ordered]@{ reference = 0L; original = 0L; blank = 0L }
    foreach ($layer in $formType.GetField('_layers', $flags).GetValue($form)) {
        $layerFlags = [Reflection.BindingFlags]'Instance,NonPublic'
        $drawn.reference += $layer.GetType().GetField('DrawnReference', $layerFlags).GetValue($layer)
        $drawn.original += $layer.GetType().GetField('DrawnOriginal', $layerFlags).GetValue($layer)
        $drawn.blank += $layer.GetType().GetField('DrawnBlank', $layerFlags).GetValue($layer)
    }
    if ($drawn.reference -le 0 -or $drawn.original -le 0 -or $drawn.blank -le 0) {
        throw 'Normal animation did not render both catalogs and preserve reference blanks'
    }
    $bitmap.Save($outputPath, [Drawing.Imaging.ImageFormat]::Png)
    # Setting ClientSize exercises the compiled OnResize path and sprite disposal.
    $form.ClientSize = [Drawing.Size]::new(320, 180)
    $bitmap = $field.GetValue($form)
    if ($bitmap.Width -ne 320 -or $bitmap.Height -ne 180) {
        throw 'Native resize retained a stale rendering buffer'
    }
    $resized = Inspect-Frame $bitmap
    $bitmap.Save([IO.Path]::ChangeExtension($outputPath, 'resized.png'), [Drawing.Imaging.ImageFormat]::Png)
    $live = Test-LiveFeed $assembly $formType $Binary $outputPath
    $preview = Test-PreviewProcess $Binary
    $receipt = [ordered]@{
        status = 'passed'
        binary = [IO.Path]::GetFileName($Binary)
        binary_sha256 = (Get-FileHash -LiteralPath $Binary -Algorithm SHA256).Hash.ToLowerInvariant()
        binary_version = $binaryVersion
        catalog_manifest_sha256 = (Get-FileHash -LiteralPath $CatalogManifest -Algorithm SHA256).Hash.ToLowerInvariant()
        catalog_atlas_sha256 = (Get-FileHash -LiteralPath ([IO.Path]::ChangeExtension($outputPath, 'catalog.png')) -Algorithm SHA256).Hash.ToLowerInvariant()
        checks = @('compiled_assembly_load', 'filled_svg_catalog_249_slots', 'nonzero_compound_paths', 'cubic_curves', 'visible_248_and_blank_slot', 'both_catalogs_have_counters', 'weighted_original_share', 'both_catalogs_drawn', 'embedded_mit_notice', 'native_form_load', 'green_glyphs', 'black_gaps', 'motion', 'native_resize', 'live_feed_report', 'live_feed_rejections', 'live_report_entrypoint', 'live_glyphs_drawn', 'preview_process_entrypoint', 'hidden_parent_embedding', 'preview_clean_exit')
        animation_frames = 90
        catalog = $catalog
        normal_animation_draws = $drawn
        embedded_mit_notice = $true
        initial = $initial
        animated = $animated
        resized = $resized
        live = $live
        preview_process = $preview
        scope = 'Compiled .scr exact compound SVG catalog, native form load, both-family rendering, motion, resize, live feed reading and drawing, and /p subprocess embedding/exit; /s multi-monitor dispatch is not exercised'
    }
    $receiptPath = [IO.Path]::ChangeExtension($outputPath, 'json')
    [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 5) + "`n", [Text.UTF8Encoding]::new($false))
    Write-Output "Windows native load, motion, and resize passed: $receiptPath"
} finally {
    $form.Dispose()
}
