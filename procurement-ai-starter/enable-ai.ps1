$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Virtual environment not found. Run .\setup.ps1 first."
}

Write-Host "Installing the Agents SDK dependency..." -ForegroundColor Cyan
& $venvPython -m pip install -r requirements-ai.txt
if ($LASTEXITCODE -ne 0) {
    throw "Agents SDK installation failed. The local configuration was not changed."
}

Write-Host "Enter a newly rotated API key here. The input stays hidden and is written only to this project's ignored .env file." -ForegroundColor Yellow
$secureKey = Read-Host "OpenAI API key" -AsSecureString
$keyPointer = [IntPtr]::Zero
$apiKey = $null

try {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer).Trim()
    if ([string]::IsNullOrWhiteSpace($apiKey) -or -not $apiKey.StartsWith("sk-")) {
        throw "A non-empty OpenAI API key is required. No configuration was changed."
    }

    $envPath = Join-Path $PSScriptRoot ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot ".env.example") -Destination $envPath
    }

    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in [System.IO.File]::ReadAllLines($envPath)) { $lines.Add($line) }
    $settings = [ordered]@{
        OPENAI_API_KEY = $apiKey
        PROCUREMENT_LLM_INTAKE = "1"
        PROCUREMENT_AGENT_REVIEW = "1"
    }

    foreach ($name in $settings.Keys) {
        $found = $false
        for ($index = 0; $index -lt $lines.Count; $index++) {
            if ($lines[$index] -match "^\s*$([regex]::Escape($name))=") {
                $lines[$index] = "$name=$($settings[$name])"
                $found = $true
                break
            }
        }
        if (-not $found) { $lines.Add("$name=$($settings[$name])") }
    }

    [System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Agents SDK enabled. Restart the app with .\api.ps1; natural-language procurement requests will use SDK intake and plan review." -ForegroundColor Green
}
finally {
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
    if ($null -ne $secureKey) { $secureKey.Dispose() }
    $apiKey = $null
}
