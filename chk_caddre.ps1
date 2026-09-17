
[System.Reflection.Assembly]::LoadFrom("C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll") | Out-Null
$port = 52578
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Timeout=30;")
$conn.Open()

$dax = @"
EVALUATE
SUMMARIZECOLUMNS(
    VMQ_CADDRE[BLOCO],
    VMQ_CADDRE[TITULO],
    "Q", COUNTROWS(VMQ_CADDRE)
)
ORDER BY VMQ_CADDRE[BLOCO], VMQ_CADDRE[TITULO]
"@

$cmd = $conn.CreateCommand()
$cmd.CommandText = $dax
$adapter = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
$dt = New-Object System.Data.DataTable
$adapter.Fill($dt) | Out-Null

$res = @()
foreach ($r in $dt.Rows) {
    Write-Host "Bloco: $($r[0]) | Titulo: $($r[1])"
    $res += [PSCustomObject]@{
        Bloco = $r[0].ToString()
        Titulo = $r[1].ToString()
    }
}
$res | ConvertTo-Json | Out-File -FilePath "C:\Users\amello\.gemini\antigravity-ide\brain\ca663c80-894f-49a6-af49-a492a9ff99fc\scratch\all_caddre.json" -Encoding utf8
$conn.Close()
