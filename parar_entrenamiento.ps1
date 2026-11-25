# Para el entrenamiento si está corriendo (aunque esté oculto).
$procesos = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*entrenar.py*' }
if ($procesos) {
    $procesos | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Write-Host "Entrenamiento anterior parado."
} else {
    Write-Host "No había ningún entrenamiento corriendo."
}
