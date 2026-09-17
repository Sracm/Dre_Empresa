
[System.Reflection.Assembly]::LoadFrom("C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll") | Out-Null
$ports = @(55192, 60316, 60317)

foreach ($port in $ports) {
    Write-Host "=== TESTING PORT $port ==="
    try {
        $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Timeout=10;")
        $conn.Open()
        
        $dax = @"
EVALUATE
SUMMARIZECOLUMNS(
    DCALENDARIO[ANO],
    DCALENDARIO[NUMEROMES],
    VMQ_CADDRE[BLOCO],
    VMQ_CADDRE[TITULO],
    FILTER(DCALENDARIO, DCALENDARIO[ANO] = 2026),
    FILTER(VMQ_CADDRE, VMQ_CADDRE[BLOCO] = "2.Custo Mercadoria Vendida"),
    "REALIZADO_EMPRESA", [REALIZADO.],
    "ORCADO_EMPRESA", [ORCAMENTO],
    "REALIZADO_GESTORES", [REALIZADO (R$)..],
    "ORCADO_GESTORES", [ORÇADO (R$).]
)
ORDER BY DCALENDARIO[NUMEROMES], VMQ_CADDRE[TITULO]
"@
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $dax
        $adapter = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
        $dt = New-Object System.Data.DataTable
        $adapter.Fill($dt) | Out-Null
        
        Write-Host "PORT $port returned $($dt.Rows.Count) rows for 2.Custo Mercadoria Vendida!"
        if ($dt.Rows.Count -gt 0) {
            foreach ($r in $dt.Rows | Select-Object -First 10) {
                Write-Host "  Mês: $($r['DCALENDARIO[NUMEROMES]']) | Titulo: $($r['VMQ_CADDRE[TITULO]']) | RealEmp: $($r['[REALIZADO_EMPRESA]']) | OrcEmp: $($r['[ORCADO_EMPRESA]'])"
            }
        }
        $conn.Close()
    } catch {
        Write-Host "PORT $port ERROR: $($_.Exception.Message)"
    }
}
