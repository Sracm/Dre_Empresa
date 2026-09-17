
[System.Reflection.Assembly]::LoadFrom("C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll") | Out-Null
$port = 55192
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Timeout=30;")
$conn.Open()

# Query all distinct BLOCO and TITULO with their Realizado and Orçado in 2026
$dax = @"
EVALUATE
SUMMARIZECOLUMNS(
    VMQ_CADDRE[BLOCO],
    VMQ_CADDRE[TITULO],
    FILTER(DCALENDARIO, DCALENDARIO[ANO] = 2026),
    "REALIZADO", [REALIZADO.],
    "ORCADO", [ORCAMENTO]
)
ORDER BY VMQ_CADDRE[BLOCO], VMQ_CADDRE[TITULO]
"@

$cmd = $conn.CreateCommand()
$cmd.CommandText = $dax
$adapter = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
$dt = New-Object System.Data.DataTable
$adapter.Fill($dt) | Out-Null

$rows = @()
foreach ($r in $dt.Rows) {
    Write-Host "Bloco: '$($r[0])' | Titulo: '$($r[1])' | Real: $($r[2]) | Orc: $($r[3])"
    $rows += [PSCustomObject]@{
        Bloco = $r[0].ToString()
        Titulo = $r[1].ToString()
        Realizado = $r[2]
        Orcado = $r[3]
    }
}

$rows | ConvertTo-Json -Depth 3 | Out-File -FilePath "C:\Users\amello\.gemini\antigravity-ide\brain\ca663c80-894f-49a6-af49-a492a9ff99fc\scratch\empresa_all_lines.json" -Encoding utf8
Write-Host "Total lines: $($rows.Count)"
$conn.Close()
