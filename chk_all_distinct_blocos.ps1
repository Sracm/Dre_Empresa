
[System.Reflection.Assembly]::LoadFrom("C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll") | Out-Null
$port = 55192
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Timeout=15;")
$conn.Open()

$dax = @"
EVALUATE
SUMMARIZECOLUMNS(
    VMQ_CADDRE[BLOCO],
    "Q", 1
)
ORDER BY VMQ_CADDRE[BLOCO]
"@

$cmd = $conn.CreateCommand()
$cmd.CommandText = $dax
$adapter = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
$dt = New-Object System.Data.DataTable
$adapter.Fill($dt) | Out-Null

Write-Host "DISTINCT BLOCOS IN MODEL:"
foreach ($r in $dt.Rows) {
    Write-Host "  '$($r[0])'"
}
$conn.Close()
