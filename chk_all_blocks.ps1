
[System.Reflection.Assembly]::LoadFrom("C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll") | Out-Null
$port = 52578
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Timeout=30;")
$conn.Open()

# Query all distinct BLOCO and TITULO in the entire model
$dax = @"
EVALUATE
SUMMARIZE(
    VMQ_CADDRE,
    VMQ_CADDRE[BLOCO],
    VMQ_CADDRE[TITULO]
)
ORDER BY VMQ_CADDRE[BLOCO], VMQ_CADDRE[TITULO]
"@

$cmd = $conn.CreateCommand()
$cmd.CommandText = $dax
$adapter = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
$dt = New-Object System.Data.DataTable
$adapter.Fill($dt) | Out-Null

Write-Host "ALL BLOCKS AND TITULOS IN MODEL:"
$blocks = @()
foreach ($r in $dt.Rows) {
    Write-Host "  Bloco: '$($r[0])' | Titulo: '$($r[1])'"
    $blocks += [PSCustomObject]@{
        Bloco = $r[0].ToString()
        Titulo = $r[1].ToString()
    }
}
$blocks | ConvertTo-Json | Out-File -FilePath "all_model_blocks_titulos.json" -Encoding utf8
$conn.Close()
