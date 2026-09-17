
[System.Reflection.Assembly]::LoadFrom("C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll") | Out-Null
$port = 55192
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Timeout=30;")
$conn.Open()

# DAX with exact report-level filters of DRE Empresa
$dax = @"
EVALUATE
SUMMARIZECOLUMNS(
    DCALENDARIO[NUMEROMES],
    VMQ_CADDRE[BLOCO],
    VMQ_CADDRE[TITULO],
    FILTER(DCALENDARIO, DCALENDARIO[ANO] = 2026 && DCALENDARIO[NUMEROMES] IN {1, 2, 3}),
    FILTER(VMQ_CADDRE, VMQ_CADDRE[BLOCO] = "2.Custo Mercadoria Vendida"),
    FILTER(VMQ_TSIEMP, VMQ_TSIEMP[CODEMP] <> 9),
    FILTER(VMQ_TSICUS, VMQ_TSICUS[CODCENCUS] <> 21010000),
    FILTER(VMQ_TSIEMP, NOT(VMQ_TSIEMP[RAZAOABREV] IN {"EA88 - SC", "EKOS - SP", "GLOBRAL - SC", "GLOBRAL - SP", "AGGP - SP"})),
    "ORCADO", [ORCAMENTO],
    "REALIZADO", [REALIZADO.]
)
ORDER BY DCALENDARIO[NUMEROMES], VMQ_CADDRE[TITULO]
"@

$cmd = $conn.CreateCommand()
$cmd.CommandText = $dax
$adapter = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
$dt = New-Object System.Data.DataTable
$adapter.Fill($dt) | Out-Null

Write-Host "=== RESULT FOR 2.Custo Mercadoria Vendida ==="
foreach ($r in $dt.Rows) {
    Write-Host ("Mês: {0} | {1,-35} | Orç: {2,12:N0} | Real: {3,12:N0}" -f $r[0], $r[2], $r[3], $r[4])
}
$conn.Close()
