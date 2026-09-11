$Cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -match "HealthChat" } | Select-Object -First 1
$ExePath = "D:\projekt\healthchat\healthchat\dist\HealthChatDesktop\HealthChatDesktop.exe"

if ($Cert -and (Test-Path $ExePath)) {
    $SigResult = Set-AuthenticodeSignature -FilePath $ExePath -Certificate $Cert
    Write-Host "✅ Signed $ExePath with Status: $($SigResult.Status)"
} else {
    Write-Host "Cert or EXE not found."
}
