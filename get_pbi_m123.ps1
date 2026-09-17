
[System.Reflection.Assembly]::LoadFrom("C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll") | Out-Null
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:55192;Timeout=30;")
$conn.Open()

$dax = @"
EVALUATE
SUMMARIZECOLUMNS(
    DCALENDARIO[NUMEROMES],
    'Margem de Contribuição'[Item],
    VMQ_DREQLIK[MARGEM],
    VMQ_CADDRE[BLOCO],
    FILTER(DCALENDARIO, DCALENDARIO[ANO] = 2026 && DCALENDARIO[NUMEROMES] IN {1, 2, 3}),
    FILTER(VMQ_TSIEMP, VMQ_TSIEMP[CODEMP] <> 9),
    FILTER(VMQ_TSICUS, VMQ_TSICUS[CODCENCUS] <> 21010000),
    FILTER(VMQ_TSIEMP, NOT(VMQ_TSIEMP[RAZAOABREV] IN {"EA88 - SC", "EKOS - SP", "GLOBRAL - SC", "GLOBRAL - SP", "AGGP - SP"})),
    "ORC", [ORCAMENTO],
    "REAL", [REALIZADO.]
)
ORDER BY DCALENDARIO[NUMEROMES], VMQ_CADDRE[BLOCO]
"@

$cmd = $conn.CreateCommand()
$cmd.CommandText = $dax
$adapter = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
$dt = New-Object System.Data.DataTable
$adapter.Fill($dt) | Out-Null

Write-Host "PBI_DATA_START"
foreach ($r in $dt.Rows) {
    Write-Host ("{0}	{1}	{2}	{3}" -f $r[0], $r[3], $r[4], $r[5])
}
Write-Host "PBI_DATA_END"
$conn.Close()
