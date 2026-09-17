
[System.Reflection.Assembly]::LoadFrom("C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll") | Out-Null
$ports = @(55192, 60316, 60317)

foreach ($port in $ports) {
    try {
        $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Timeout=5;")
        $conn.Open()
        Write-Host "PORT $port CONNECTED! Database: $($conn.Database)"

        # Check measures
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = "SELECT TOP 5 [MEASURE_NAME] FROM `$SYSTEM.MDSCHEMA_MEASURES"
        $r = $cmd.ExecuteReader()
        $ms = @()
        while ($r.Read()) { $ms += $r[0].ToString() }
        $r.Close()
        Write-Host "  Measures: $($ms -join ', ')"
        $conn.Close()
    } catch {
        Write-Host "PORT $port ERROR: $($_.Exception.Message)"
    }
}
