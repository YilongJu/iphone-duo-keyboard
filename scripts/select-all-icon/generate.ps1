# Generates candidates for the icon of the Select All key with the image tool of Codex (ChatGPT
# login, gpt-image). Each candidate is one `codex exec` call that saves <name>.png in candidates/.
# The prompts name no person, app or repository, only the idea of the icon.
# make_icon.py then turns the chosen candidate into the template images of the key.
$ErrorActionPreference = 'Stop'
$dir = Join-Path $PSScriptRoot 'candidates'
New-Item -ItemType Directory -Force $dir | Out-Null

$common = 'One user interface glyph for a keyboard key, 1024x1024 pixels. Solid pure black shapes on a pure white background. Flat, no gradient, no shadow, no gray, no color, no text, no letters, no border around the image. Thick even strokes with round ends, like an Apple SF Symbol at regular weight. The glyph is centered and fills about 70 percent of the image. It must stay clear when shown 22 points wide.'

$prompts = [ordered]@{
  'a' = 'Meaning: select all text. Three horizontal text lines of equal length, stacked, inside a dashed rounded rectangle that frames all of them. The dashed frame has few, long dashes.'
  'b' = 'Meaning: select all text. Three thick horizontal text lines, stacked, inside a solid rounded rectangle outline. At the top left corner and at the bottom right corner of the outline sits a small filled round selection handle.'
  'c' = 'Meaning: select all text. Four corner brackets that mark the corners of a square, like a crop frame. Inside the frame, three thick horizontal text lines, stacked, the last one a little shorter.'
  'd' = 'Meaning: select all text. A solid filled rounded rectangle, and inside it three horizontal text lines cut out in white, as text that is fully highlighted. At the left edge a thin vertical selection bar with a small round knob on top, and at the right edge the same bar with a knob at the bottom.'
}

$jobs = @()
foreach ($name in $prompts.Keys) {
  $text = "Use your image generation tool (gpt-image) to make one image, then save it as the PNG file $name.png in the current folder, 1024x1024. Do not edit the image after it is made. Reply only with the file name. The image: $common $($prompts[$name])"
  $jobs += Start-Job -Name $name -ScriptBlock {
    param($d, $t)
    Set-Location $d
    codex exec --skip-git-repo-check -s workspace-write $t 2>&1 | Select-Object -Last 3
  } -ArgumentList $dir, $text
}
$jobs | Wait-Job | Out-Null
foreach ($j in $jobs) { "== $($j.Name)"; Receive-Job $j }
Get-ChildItem $dir -Filter *.png | Select-Object Name, Length
