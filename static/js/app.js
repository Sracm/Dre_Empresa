/* ═══════════════════════════════════════════════════════════════════════
   DRE GESTORES — app.js
   Sistema de polling assíncrono para queries Oracle lentas
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

// ── Estado global ────────────────────────────────────────────────────────
const state = {
  anos: [2026],
  meses: [8],
  emps: [],   // [] ou todas = ALL
  cenc: [],   // [] ou todas = ALL
  anosLista: [],
  mesesLista: [],
  empresasLista: [],
  centrosLista: [],
  get ano() { return this.anos && this.anos.length ? this.anos[0] : 2026; },
  get mes() { return this.meses && this.meses.length ? this.meses[this.meses.length - 1] : 8; },
  get emp() { return (!this.emps || !this.emps.length || this.emps.length === this.empresasLista.length) ? 'ALL' : this.emps.join(','); },
  dre: [],
  bonifTotal: 0,
  chartMensal: null,
  chartEmpresa: null,
  chartAcumulado: null,
  expandAll: false,
  selectedLine: null,
  mensalData: [],
  congelado: true,
  mesesCongeladosCache: {},
  desviosSortCol: 'diff',
  desviosSortAsc: true,
  tabelaAcumuladoData: null,
  acumuladoExpandAll: false,
  margemAcumuladaAberta: true,
  blocosAcumuladoAbertos: new Set(),
  polling: {},  // { key: intervalId }
};

// ── Formatadores ─────────────────────────────────────────────────────────
const fmtBRL = v => {
  if (v == null || v === '') return '—';
  return Number(v).toLocaleString('pt-BR', {
    style: 'currency', currency: 'BRL',
    minimumFractionDigits: 0, maximumFractionDigits: 0
  });
};
const fmtPct = v => v == null ? '—' : Number(v).toFixed(1) + '%';
const fmtRO  = v => {
  if (v == null) return '—';
  const n = Number(v);
  return (n >= 0 ? '+' : '') + n.toFixed(1) + '%';
};

// Formatação em valor completo sem decimais (ex: 3.450.800)
const fmtCompact = v => {
  if (v == null || Math.abs(v) < 0.001) return '';
  const n = Number(v);
  return Math.round(n).toLocaleString('pt-BR');
};

// ── Helper para Subtítulo dos KPI Cards (Orçado, R/O, MoM, YoY, YTD YoY, % VB Orç., % VB Real.)
function renderKpiSub(orc, roPct, momPct, yoyPct, ytdYoyPct, pctOrc, pctReal) {
  // R/O
  const roStr = roPct != null ? (roPct >= 0 ? '+' : '') + Number(roPct).toFixed(1) + '%' : '—';
  const roClass = (roPct || 0) >= 0 ? 'up' : 'down';

  // MoM
  const momStr = momPct != null ? (momPct > 0 ? `▲ +${Number(momPct).toFixed(1)}%` : momPct < 0 ? `▼ ${Number(momPct).toFixed(1)}%` : '0.0%') : '—';
  const momClass = momPct == null ? 'zero' : ((momPct || 0) >= 0 ? 'up' : 'down');

  // YoY
  const yoyStr = yoyPct != null ? (yoyPct > 0 ? `▲ +${Number(yoyPct).toFixed(1)}%` : yoyPct < 0 ? `▼ ${Number(yoyPct).toFixed(1)}%` : '0.0%') : '—';
  const yoyClass = yoyPct == null ? 'zero' : ((yoyPct || 0) >= 0 ? 'up' : 'down');

  // YTD YoY
  const ytdStr = ytdYoyPct != null ? (ytdYoyPct > 0 ? `▲ +${Number(ytdYoyPct).toFixed(1)}%` : ytdYoyPct < 0 ? `▼ ${Number(ytdYoyPct).toFixed(1)}%` : '0.0%') : '—';
  const ytdClass = ytdYoyPct == null ? 'zero' : ((ytdYoyPct || 0) >= 0 ? 'up' : 'down');

  // % VB Orç. e % VB Real.
  const pctOrcStr = pctOrc != null ? `${Number(pctOrc).toFixed(1)}%` : '—';
  const pctRealStr = pctReal != null ? `${Number(pctReal).toFixed(1)}%` : '—';

  return `
    <div class="kpi-sub-line">
      <span class="kpi-sub-lbl">Orçado: <strong class="kpi-val-white">${fmtBRL(orc)}</strong></span>
      <span class="kpi-sub-badge ${roClass}" title="Variação Real vs Orçado">R/O: ${roStr}</span>
    </div>

    <div class="kpi-metrics-row">
      <div class="kpi-metric-col" title="Evolução vs Mês Anterior (MoM)">
        <span class="kpi-m-lbl">MoM</span>
        <span class="kpi-m-badge ${momClass}">${momStr}</span>
      </div>
      <div class="kpi-metric-col" title="Evolução vs Mesmo Mês do Ano Anterior (YoY)">
        <span class="kpi-m-lbl">YoY</span>
        <span class="kpi-m-badge ${yoyClass}">${yoyStr}</span>
      </div>
      <div class="kpi-metric-col" title="Evolução Acumulada no Ano vs Ano Anterior (YTD YoY)">
        <span class="kpi-m-lbl">YTD YoY</span>
        <span class="kpi-m-badge ${ytdClass}">${ytdStr}</span>
      </div>
    </div>

    <div class="kpi-sub-line-pct">
      <span class="kpi-sub-lbl">% VB Orç: <strong class="kpi-val-pct">${pctOrcStr}</strong></span>
      <span class="kpi-sub-lbl">% VB Real: <strong class="kpi-val-pct">${pctRealStr}</strong></span>
    </div>
  `;
}

// ── Análise de Evolução (Mês Anterior e Ano Anterior) ────────────────────
const fmtEvol = v => {
  if (v == null) return '—';
  const n = Number(v);
  if (n > 0) return `▲ +${n.toFixed(1)}%`;
  if (n < 0) return `▼ ${n.toFixed(1)}%`;
  return '0.0%';
};
function evolClass(v) {
  if (v == null) return 'val-zero';
  const n = Number(v);
  return n < 0 ? 'val-neg' : n > 0 ? 'val-pos' : 'val-zero';
}

function renderYtdCell(v) {
  return `<td class="col-var ${evolClass(v)}">${fmtEvol(v)}</td>`;
}

// ── Toast ────────────────────────────────────────────────────────────────
function showToast(msg, type = '') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + type;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.className = 'toast'; }, 4000);
}

// ── Init ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await carregarFiltros();
  carregarTudo(false); // Carga inicial completa de todo o histórico

  const btnCarregar = document.getElementById('btnCarregar');
  if (btnCarregar) btnCarregar.addEventListener('click', () => carregarTudo(true));

  const btnAplicar = document.getElementById('btnAplicar');
  if (btnAplicar) btnAplicar.addEventListener('click', () => carregarTudo(true));

  const btnExportExcel = document.getElementById('btnExportExcel');
  if (btnExportExcel) btnExportExcel.addEventListener('click', exportarParaExcel);

  const btnExportExcelTop = document.getElementById('btnExportExcelTop');
  if (btnExportExcelTop) btnExportExcelTop.addEventListener('click', exportarParaExcel);

  const btnRefresh = document.getElementById('btnRefresh'); if(btnRefresh) btnRefresh.addEventListener('click', () => {
    Object.values(state.polling).forEach(id => clearInterval(id));
    state.polling = {};
    carregarTudo(true);
  });

  const btnExp = document.getElementById('btnExpandAll');
  if (btnExp) {
    btnExp.textContent = state.expandAll ? 'Recolher tudo' : 'Expandir tudo';
    btnExp.addEventListener('click', toggleExpandAll);
  }

  const btnReset = document.getElementById('btnResetLinha');
  if (btnReset) {
    btnReset.addEventListener('click', resetarFiltroLinha);
  }

  const btnExpAcum = document.getElementById('btnToggleExpandAcumulado');
  if (btnExpAcum) {
    btnExpAcum.addEventListener('click', toggleExpandAllAcumulado);
  }

  // Interatividade nos KPI cards para filtrar gráficos diretamente
  document.querySelectorAll('.kpi-card[data-kpi]').forEach(card => {
    card.addEventListener('click', () => {
      const kpiKey = card.getAttribute('data-kpi');
      onKpiCardClick(kpiKey, card);
    });
  });
});

// ── Helpers de Parâmetros de Filtro ───────────────────────────────────────
function getAnoParam() {
  if (!state.anos || state.anos.length === 0 || (state.anosLista && state.anos.length === state.anosLista.length)) {
    return state.anos && state.anos.length ? state.anos.join(',') : '2026';
  }
  return state.anos.join(',');
}

function getMesParam() {
  if (!state.meses || state.meses.length === 0) {
    return '8';
  }
  return state.meses.join(',');
}

function getEmpParam() {
  if (!state.emps || state.emps.length === 0 || (state.empresasLista && state.emps.length === state.empresasLista.length)) {
    return 'ALL';
  }
  return state.emps.join(',');
}

function getCencParam() {
  if (!state.cenc || state.cenc.length === 0 || (state.centrosLista && state.cenc.length === state.centrosLista.length)) {
    return 'ALL';
  }
  return state.cenc.join(',');
}

// ── Componente Reutilizável Multi-Select ──────────────────────────────────
function setupMultiSelect({
  idPrefix,
  items,
  getValue,
  getLabel,
  getSearchText,
  getSelected,
  setSelected,
  allLabel,
  unitPlural
}) {
  const listEl = document.getElementById(`${idPrefix}OptionsList`);
  const btnText = document.getElementById(`${idPrefix}BtnText`);
  const btn = document.getElementById(`${idPrefix}Btn`);
  const dropdown = document.getElementById(`${idPrefix}Dropdown`);
  const searchInput = document.getElementById(`${idPrefix}Search`);
  const btnSelectAll = document.getElementById(`btnSelectAll${idPrefix.charAt(0).toUpperCase() + idPrefix.slice(1)}`);
  const btnClear = document.getElementById(`btnClear${idPrefix.charAt(0).toUpperCase() + idPrefix.slice(1)}`);

  if (!listEl || !btnText || !btn || !dropdown) return;

  function updateBtnText() {
    const selected = getSelected();
    if (!selected || selected.length === 0 || selected.length === items.length) {
      btnText.textContent = allLabel;
    } else if (selected.length === 1) {
      const item = items.find(it => String(getValue(it)) === String(selected[0]));
      btnText.textContent = item ? getLabel(item) : selected[0];
    } else {
      btnText.innerHTML = `${selected.length} ${unitPlural} <span class="cenc-badge-count">${selected.length}</span>`;
    }
  }

  // Gera os checkboxes
  const selected = getSelected();
  const html = items.map(it => {
    const val = String(getValue(it));
    const lbl = getLabel(it);
    const isChecked = selected.includes(val) ? 'checked' : '';
    const search = getSearchText ? getSearchText(it).toLowerCase() : `${val.toLowerCase()} ${lbl.toLowerCase()}`;
    return `
      <label class="multi-select-option" data-search="${search}">
        <input type="checkbox" value="${val}" ${isChecked}>
        <span class="cenc-name" title="${lbl}">${lbl}</span>
      </label>
    `;
  }).join('');

  listEl.innerHTML = html;
  updateBtnText();

  // Evento em cada checkbox
  listEl.querySelectorAll('input[type="checkbox"]').forEach(chk => {
    chk.addEventListener('change', () => {
      const val = chk.value;
      let curr = [...getSelected()];
      if (chk.checked) {
        if (!curr.includes(val)) curr.push(val);
      } else {
        curr = curr.filter(x => x !== val);
      }
      setSelected(curr);
      updateBtnText();
    });
  });

  // Toggle abrir / fechar
  btn.onclick = (e) => {
    e.stopPropagation();
    // Fecha outros dropdowns abertos
    document.querySelectorAll('.multi-select-dropdown').forEach(d => {
      if (d !== dropdown) d.style.display = 'none';
    });
    document.querySelectorAll('.multi-select-btn').forEach(b => {
      if (b !== btn) b.classList.remove('active');
    });

    const isHidden = dropdown.style.display === 'none';
    dropdown.style.display = isHidden ? 'flex' : 'none';
    btn.classList.toggle('active', isHidden);
    if (isHidden && searchInput) {
      searchInput.value = '';
      filtrarOpcoes('');
      searchInput.focus();
    }
  };

  // Filtro de busca
  function filtrarOpcoes(term) {
    const q = (term || '').trim().toLowerCase();
    listEl.querySelectorAll('.multi-select-option').forEach(opt => {
      const text = opt.getAttribute('data-search') || '';
      opt.style.display = text.includes(q) ? 'flex' : 'none';
    });
  }

  if (searchInput) {
    searchInput.oninput = () => {
      filtrarOpcoes(searchInput.value);
    };
  }

  // Ação Selecionar Todos
  if (btnSelectAll) {
    btnSelectAll.onclick = (e) => {
      e.stopPropagation();
      const allVals = items.map(it => String(getValue(it)));
      setSelected(allVals);
      listEl.querySelectorAll('input[type="checkbox"]').forEach(chk => chk.checked = true);
      updateBtnText();
    };
  }

  // Ação Limpar
  if (btnClear) {
    btnClear.onclick = (e) => {
      e.stopPropagation();
      setSelected([]);
      listEl.querySelectorAll('input[type="checkbox"]').forEach(chk => chk.checked = false);
      updateBtnText();
    };
  }

  // Fechar ao clicar fora
  document.addEventListener('click', (e) => {
    const wrapper = document.getElementById(`multiSelect${idPrefix.charAt(0).toUpperCase() + idPrefix.slice(1)}`);
    if (wrapper && !wrapper.contains(e.target)) {
      dropdown.style.display = 'none';
      btn.classList.remove('active');
    }
  });
}

// ── Filtros ──────────────────────────────────────────────────────────────
async function carregarFiltros() {
  const MESES = [
    { NUM: 1, NOME: 'Janeiro' }, { NUM: 2, NOME: 'Fevereiro' },
    { NUM: 3, NOME: 'Março' }, { NUM: 4, NOME: 'Abril' },
    { NUM: 5, NOME: 'Maio' }, { NUM: 6, NOME: 'Junho' },
    { NUM: 7, NOME: 'Julho' }, { NUM: 8, NOME: 'Agosto' },
    { NUM: 9, NOME: 'Setembro' }, { NUM: 10, NOME: 'Outubro' },
    { NUM: 11, NOME: 'Novembro' }, { NUM: 12, NOME: 'Dezembro' }
  ];

  try {
    const res = await fetch('/api/filtros');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    state.anosLista = data.anos || [2026, 2025, 2024, 2023];
    state.mesesLista = data.meses || MESES;
    state.empresasLista = data.empresas || [];
    state.centrosLista = data.centros || [];

  } catch (e) {
    const anoAtual = new Date().getFullYear();
    state.anosLista = [anoAtual, anoAtual - 1, anoAtual - 2];
    state.mesesLista = MESES;
    state.empresasLista = [];
    state.centrosLista = [];
    showToast('Filtros: ' + e.message + ' — usando padrão', 'error');
  }

  // 1. Multi-Select de Ano (padrão: 2026)
  setupMultiSelect({
    idPrefix: 'ano',
    items: state.anosLista,
    getValue: it => it,
    getLabel: it => String(it),
    getSelected: () => state.anos.map(String),
    setSelected: vals => { state.anos = vals.map(Number); },
    allLabel: 'Todos os Anos',
    unitPlural: 'Anos'
  });

  // 2. Multi-Select de Mês (padrão: Agosto / 8)
  setupMultiSelect({
    idPrefix: 'mes',
    items: state.mesesLista,
    getValue: it => it.NUM,
    getLabel: it => it.NOME,
    getSelected: () => state.meses.map(String),
    setSelected: vals => { state.meses = vals.map(Number).sort((a, b) => a - b); },
    allLabel: 'Todos os Meses',
    unitPlural: 'Meses'
  });

  // 3. Multi-Select de Empresa (padrão: Todas)
  setupMultiSelect({
    idPrefix: 'emp',
    items: state.empresasLista,
    getValue: it => it.CODEMP,
    getLabel: it => it.NOME || it.CODEMP,
    getSelected: () => state.emps,
    setSelected: vals => { state.emps = vals; },
    allLabel: 'Todas as Empresas',
    unitPlural: 'Empresas'
  });

  // 4. Multi-Select de Centro de Custo (padrão: Todos)
  setupMultiSelect({
    idPrefix: 'cenc',
    items: state.centrosLista,
    getValue: it => it.CODCENCUS,
    getLabel: it => it.NOME || String(it.CODCENCUS),
    getSearchText: it => `${it.CODCENCUS} ${it.NOME}`,
    getSelected: () => state.cenc,
    setSelected: vals => { state.cenc = vals; },
    allLabel: 'Todos os Centros',
    unitPlural: 'Centros'
  });
}

// ── Carrega o dashboard completo com polling ─────────────────────────────
function carregarTudo(somenteDoisMeses = false) {
  const mesAtual = state.mes || 8;
  const mesAnt = mesAtual > 1 ? mesAtual - 1 : 12;

  const p = new URLSearchParams({
    ano: getAnoParam(),
    mes: mesAtual,
    emp: getEmpParam(),
    cenc: getCencParam(),
  });

  const pMensal = new URLSearchParams({
    ano: getAnoParam(),
    emp: getEmpParam(),
    cenc: getCencParam(),
  });

  if (somenteDoisMeses && state.mensalData && state.mensalData.length > 0) {
    pMensal.set('refresh_meses', `${mesAnt},${mesAtual}`);
    setLoadingDRE(`Atualizando mês atual (${mesAtual}) e anterior (${mesAnt}) — meses fechados congelados…`);
  } else {
    setLoadingDRE('Carregando dashboard completo…');
  }

  // Dispara DRE, Evolução Mensal e Tabela Acumulada em paralelo
  fetchComPolling('/api/dre?' + p, 'dre', (data) => onDRELoaded(data, somenteDoisMeses));
  fetchComPolling('/api/dre/mensal?' + pMensal, 'mensal', (data) => onMensalLoaded(data, somenteDoisMeses, mesAnt, mesAtual));
  carregarTabelaAcumulado();
}

// ── Fetch com polling automático ─────────────────────────────────────────
async function fetchComPolling(url, tag, onDone) {
  try {
    const res  = await fetch(url);
    const data = await res.json();

    if (res.status === 202 && data.status === 'running') {
      // Polling a cada 4 segundos
      const key = data.key || tag;
      if (tag === 'dre') setLoadingDRE('Oracle processando… aguarde.');

      clearInterval(state.polling[tag]);
      state.polling[tag] = setInterval(async () => {
        try {
          const poll = await fetch('/api/dre/status?key=' + encodeURIComponent(key));
          const pd   = await poll.json();

          if (pd.status === 'done') {
            clearInterval(state.polling[tag]);
            delete state.polling[tag];
            onDone(pd);
          } else if (pd.status === 'error') {
            clearInterval(state.polling[tag]);
            delete state.polling[tag];
            if (tag === 'dre') setErrorDRE(pd.error || 'Erro desconhecido');
          }
          // 'running' → continua polling
        } catch (e) {
          clearInterval(state.polling[tag]);
          delete state.polling[tag];
          if (tag === 'dre') setErrorDRE(e.message);
        }
      }, 4000);

    } else if (data.error) {
      throw new Error(data.error);
    } else {
      onDone(data);
    }
  } catch (e) {
    if (tag === 'dre') setErrorDRE(e.message);
    else showToast(`Erro ${tag}: ${e.message}`, 'error');
  }
}

// ── Callbacks ────────────────────────────────────────────────────────────
function onDRELoaded(data, somenteDoisMeses = false) {
  state.dre        = data.dre || [];
  state.bonifTotal = data.bonif_total || 0;
  renderizarDRE();
  renderizarQuadroDesvios();
  atualizarKPIs();
  atualizarTimestamp();
  if (somenteDoisMeses) {
    showToast('Mês atual e mês anterior atualizados. Outros meses congelados!', 'success');
  } else {
    showToast('Dashboard carregado com sucesso!', 'success');
  }
}

function onMensalLoaded(data, somenteDoisMeses = false, mesAnt = null, mesAtual = null) {
  const novosMeses = data.mensal || [];
  
  if (somenteDoisMeses && mesAnt && mesAtual && state.mensalData && state.mensalData.length > 0) {
    // Mantém todos os meses congelados que não sejam o mês atual nem o mês anterior
    const congelados = state.mensalData.filter(d => d.mes !== mesAnt && d.mes !== mesAtual);
    state.mensalData = [...congelados, ...novosMeses];
  } else {
    state.mensalData = novosMeses;
  }

  renderizarGraficoMensal(state.mensalData);
  renderizarGraficoAcumulado(state.mensalData, state.mes);
}

// ── Tabela Acumulada YTD (Margem de Contribuição e MARGEM) ─────────────────
async function carregarTabelaAcumulado() {
  const tbody = document.getElementById('tabelaAcumuladoBody');
  if (tbody) {
    tbody.innerHTML = '<tr><td colspan="5" class="loading-row"><div class="spinner"></div> Atualizando acumulado…</td></tr>';
  }
  try {
    const p = new URLSearchParams({
      ano: getAnoParam(),
      mes: getMesParam(),
      emp: getEmpParam(),
      cenc: getCencParam(),
    });
    const res = await fetch('/api/dre/tabela-acumulado?' + p);
    const data = await res.json();
    state.tabelaAcumuladoData = data;
    renderizarTabelaAcumulado(data);
  } catch (e) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="5" class="loading-row" style="color:var(--danger)">⚠ Erro ao carregar acumulado: ${e.message}</td></tr>`;
    }
  }
}

function fmtAcumInt(v) {
  if (v == null || isNaN(v)) return '0';
  const n = Math.round(Number(v));
  return n.toLocaleString('pt-BR');
}

function fmtAcumDec(v) {
  if (v == null || isNaN(v)) return '0,00';
  const n = Number(v);
  return n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtAcumPct(v) {
  if (v == null || isNaN(v)) return '0,00%';
  const n = Number(v);
  return n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%';
}

function renderizarTabelaAcumulado(data) {
  const tbody = document.getElementById('tabelaAcumuladoBody');
  if (!tbody) return;
  if (!data || !data.margem) {
    tbody.innerHTML = '<tr><td colspan="5" class="loading-row">Nenhum dado acumulado disponível.</td></tr>';
    return;
  }

  const mc = data.margem_contribuicao || {};
  const margem = data.margem || {};
  const blocos = margem.blocos || [];

  let html = '';

  // 1. Linha Margem de Contribuição
  const mcDifClass = (mc.dif || 0) >= 0 ? 'val-pos' : 'val-neg';
  html += `
    <tr class="row-total-mc row-desvio">
      <td class="col-desvio-bloco">
        <span class="exp-icon" style="visibility:hidden;">−</span>
        <strong style="color:#ffffff;">${mc.nome || 'Margem de Contribuição'}</strong>
      </td>
      <td class="col-num"><strong style="color:#ffffff;">${fmtAcumInt(mc.orcado)}</strong></td>
      <td class="col-num"><strong style="color:#ffffff;">${fmtAcumInt(mc.realizado)}</strong></td>
      <td class="col-num ${mcDifClass}"><strong>${fmtAcumDec(mc.dif)}</strong></td>
      <td class="col-ro"><strong style="color:#ffffff;">${fmtAcumPct(mc.pct)}</strong></td>
    </tr>
  `;

  // 2. Linha MARGEM
  const isMargemAberta = state.acumuladoExpandAll || state.margemAcumuladaAberta;
  const margemIcon = isMargemAberta ? '−' : '+';
  const margemDifClass = (margem.dif || 0) >= 0 ? 'val-pos' : 'val-neg';
  html += `
    <tr class="row-total-margem row-desvio" onclick="toggleMargemAcumulada()" title="Clique para expandir/recolher blocos">
      <td class="col-desvio-bloco">
        <span class="exp-icon">${margemIcon}</span>
        <strong style="color:var(--gold);">${margem.nome || 'MARGEM'}</strong>
      </td>
      <td class="col-num"><strong style="color:#ffffff;">${fmtAcumInt(margem.orcado)}</strong></td>
      <td class="col-num"><strong style="color:#ffffff;">${fmtAcumInt(margem.realizado)}</strong></td>
      <td class="col-num ${margemDifClass}"><strong>${fmtAcumDec(margem.dif)}</strong></td>
      <td class="col-ro"><strong style="color:#ffffff;">${fmtAcumPct(margem.pct)}</strong></td>
    </tr>
  `;

  // 3. Filhos de MARGEM (Blocos 1 a 7)
  if (isMargemAberta) {
    blocos.forEach((b) => {
      const bKey = b.bloco;
      const isBlocoAberto = state.acumuladoExpandAll || state.blocosAcumuladoAbertos.has(bKey);
      const blocoIcon = isBlocoAberto ? '−' : '+';
      const bLower = (b.bloco || '').toLowerCase();
      const isReceita = bLower.includes('venda') && !bLower.includes('despesa');
      const bDifClass = isReceita ? ((b.dif || 0) >= 0 ? 'val-pos' : 'val-neg') : ((b.dif || 0) >= 0 ? 'val-pos' : 'val-neg');

      html += `
        <tr class="row-bloco row-desvio" onclick="toggleBlocoAcumulado('${bKey.replace(/'/g, "\\'")}')" title="Clique para expandir títulos">
          <td class="col-desvio-bloco" style="padding-left: 24px;">
            <span class="exp-icon">${blocoIcon}</span>
            <span style="color:#ffffff;">${b.bloco}</span>
          </td>
          <td class="col-num">${fmtAcumInt(b.orcado)}</td>
          <td class="col-num">${fmtAcumInt(b.realizado)}</td>
          <td class="col-num ${bDifClass}">${fmtAcumDec(b.dif)}</td>
          <td class="col-ro">${fmtAcumPct(b.pct)}</td>
        </tr>
      `;

      // 4. Filhos do Bloco (Títulos)
      if (isBlocoAberto && b.titulos && b.titulos.length > 0) {
        b.titulos.forEach(t => {
          const tDifClass = (t.dif || 0) >= 0 ? 'val-pos' : 'val-neg';
          html += `
            <tr class="row-titulo row-desvio">
              <td class="col-desvio-tit" style="padding-left: 52px;">
                <span style="display:inline-block; width:8px; height:1px; background:rgba(203, 151, 39, 0.6); margin-right:8px; vertical-align:middle;"></span>
                <span>${t.titulo}</span>
              </td>
              <td class="col-num" style="opacity:0.85;">${fmtAcumInt(t.orcado)}</td>
              <td class="col-num" style="opacity:0.85;">${fmtAcumInt(t.realizado)}</td>
              <td class="col-num ${tDifClass}">${fmtAcumDec(t.dif)}</td>
              <td class="col-ro" style="opacity:0.9;">${fmtAcumPct(t.pct)}</td>
            </tr>
          `;
        });
      }
    });
  }

  tbody.innerHTML = html;

  // Atualiza subtítulo com período acumulado
  const sub = document.getElementById('subtituloTabelaAcumulado');
  if (sub) {
    const NOMES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
    const mNome = NOMES[(data.mes || 8) - 1];
    sub.textContent = `Valores acumulados de Janeiro até ${mNome} de ${data.ano || 2026}`;
  }
}

function toggleMargemAcumulada() {
  state.margemAcumuladaAberta = !state.margemAcumuladaAberta;
  if (state.tabelaAcumuladoData) renderizarTabelaAcumulado(state.tabelaAcumuladoData);
}

function toggleBlocoAcumulado(bKey) {
  if (state.blocosAcumuladoAbertos.has(bKey)) {
    state.blocosAcumuladoAbertos.delete(bKey);
  } else {
    state.blocosAcumuladoAbertos.add(bKey);
  }
  if (state.tabelaAcumuladoData) renderizarTabelaAcumulado(state.tabelaAcumuladoData);
}

function toggleExpandAllAcumulado() {
  state.acumuladoExpandAll = !state.acumuladoExpandAll;
  const btn = document.getElementById('btnToggleExpandAcumulado');
  if (btn) {
    btn.textContent = state.acumuladoExpandAll ? 'Recolher tudo' : 'Expandir tudo';
  }
  if (state.acumuladoExpandAll && state.tabelaAcumuladoData && state.tabelaAcumuladoData.margem) {
    (state.tabelaAcumuladoData.margem.blocos || []).forEach(b => state.blocosAcumuladoAbertos.add(b.bloco));
    state.margemAcumuladaAberta = true;
  } else {
    state.blocosAcumuladoAbertos.clear();
  }
  if (state.tabelaAcumuladoData) renderizarTabelaAcumulado(state.tabelaAcumuladoData);
}


// ── UI Loading/Error ─────────────────────────────────────────────────────
function setLoadingDRE(msg) {
  document.getElementById('dreBody').innerHTML =
    `<tr><td colspan="9" class="loading-row">
       <div class="spinner"></div>
       ${msg}
     </td></tr>`;
}

function setErrorDRE(msg) {
  document.getElementById('dreBody').innerHTML =
    `<tr><td colspan="9" class="loading-row" style="color:var(--danger)">⚠ ${msg}</td></tr>`;
  showToast('Erro DRE: ' + msg, 'error');
}

// ── Quadro de Desvios Executivos (|R/O| >= 10%) ──────────────────────────
function renderizarQuadroDesvios() {
  const tbody = document.getElementById('desviosBody');
  const countBadge = document.getElementById('desviosCount');
  if (!tbody) return;

  const dre = state.dre || [];
  const desvios = [];

  dre.forEach(b => {
    if (b.is_total) return;
    (b.titulos || []).forEach(t => {
      const ro = t.ro;
      if (ro != null && Math.abs(ro) >= 10) {
        const orc = t.orcado || 0;
        const real = t.realizado || 0;
        const diff = real - orc;
        const bLower = (b.bloco || '').toLowerCase();
        const isReceita = bLower.includes('venda') && !bLower.includes('despesa') && orc >= 0;

        let statusTxt = '';
        let statusClass = '';

        if (isReceita) {
          if (real >= orc) {
            statusTxt = '▲ Superávit s/ Meta';
            statusClass = 'status-fav';
          } else {
            statusTxt = '▼ Déficit s/ Meta';
            statusClass = 'status-desfav';
          }
        } else {
          // Despesas e Custos:
          // Gastar menos em magnitude do que o orçado é economia (Favorável / Abaixo do Orçado)
          // Ex: Guelta orçado -20.806 e realizado -573 => economizou R$ 20.233 (Abaixo do Orçado)
          const orcMag = Math.abs(orc);
          const realMag = Math.abs(real);

          if (realMag > orcMag) {
            // Estouro orçamentário: gastou a mais do que o teto
            statusTxt = '▲ Acima do Orçado';
            statusClass = 'status-desfav blink-intermitente';
          } else {
            // Economia orçamentária: gastou menos que o teto
            statusTxt = '▼ Abaixo do Orçado';
            statusClass = 'status-fav';
          }
        }

        desvios.push({
          bloco: b.bloco,
          titulo: t.titulo,
          orcado: t.orcado,
          realizado: t.realizado,
          diff: diff,
          ro: ro,
          statusTxt: statusTxt,
          statusClass: statusClass
        });
      }
    });
  });

  // Ordenação dinâmica configurável por coluna (padrão: menor para maior)
  const col = state.desviosSortCol || 'diff';
  const asc = state.desviosSortAsc !== false; // true = menor para o maior (crescente)

  desvios.sort((a, b) => {
    let vA = a[col];
    let vB = b[col];

    // Para colunas de texto (bloco, titulo, statusTxt)
    if (typeof vA === 'string' || typeof vB === 'string') {
      const sA = String(vA || '').toLowerCase();
      const sB = String(vB || '').toLowerCase();
      return asc ? sA.localeCompare(sB, 'pt-BR') : sB.localeCompare(sA, 'pt-BR');
    }

    // Para colunas numéricas (orcado, realizado, diff, ro)
    const nA = vA != null ? Number(vA) : (asc ? Infinity : -Infinity);
    const nB = vB != null ? Number(vB) : (asc ? Infinity : -Infinity);
    return asc ? nA - nB : nB - nA;
  });

  // Atualiza indicadores visuais no cabeçalho da tabela de desvios
  ['bloco', 'titulo', 'orcado', 'realizado', 'diff', 'ro', 'statusTxt'].forEach(c => {
    const el = document.getElementById('sort-desvio-' + c);
    if (el) {
      if (c === col) {
        el.textContent = asc ? ' ▲' : ' ▼';
        el.className = 'sort-indicator sort-active';
      } else {
        el.textContent = ' ⇅';
        el.className = 'sort-indicator';
      }
    }
  });

  if (countBadge) {
    countBadge.textContent = `${desvios.length} ${desvios.length === 1 ? 'desvio relevante' : 'desvios relevantes (≥ 10%)'}`;
  }

  if (desvios.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading-row" style="color:var(--success)">✓ Nenhum título com desvio ≥ 10% no período selecionado. Todos dentro da meta orçamentária!</td></tr>`;
    return;
  }

  const rows = desvios.map(d => `
    <tr class="row-desvio" onclick="filtrarLinhaPorNome('${d.bloco}', '${d.titulo}')" title="Clique para filtrar nos gráficos">
      <td class="col-desvio-bloco" style="color: #ffffff !important;">${d.bloco}</td>
      <td class="col-desvio-tit"><strong>${d.titulo}</strong></td>
      <td class="col-num ${numClass(d.orcado)}">${fmtBRL(d.orcado)}</td>
      <td class="col-num ${numClass(d.realizado)}">${fmtBRL(d.realizado)}</td>
      <td class="col-num ${numClass(d.diff)}">${d.diff >= 0 ? '+' : ''}${fmtBRL(d.diff)}</td>
      <td class="col-ro ${roClass(d.ro)}">${fmtRO(d.ro)}</td>
      <td class="col-status"><span class="desvio-badge ${d.statusClass}">${d.statusTxt}</span></td>
    </tr>
  `).join('');

  tbody.innerHTML = rows;
}

// ── Função Global para Ordenar por Cabeçalho (Menor para Maior) ──────────
window.ordenarDesvios = function(col) {
  if (state.desviosSortCol === col) {
    // Alterna entre menor para maior (asc) e maior para menor (desc)
    state.desviosSortAsc = !state.desviosSortAsc;
  } else {
    // Primeiro clique na coluna: sempre classifica do MENOR para o MAIOR!
    state.desviosSortCol = col;
    state.desviosSortAsc = true;
  }
  renderizarQuadroDesvios();
};

function filtrarLinhaPorNome(bloco, titulo) {
  state.selectedLine = { tipo: 'titulo', nome: titulo, bloco: bloco, titulo: titulo };
  carregarGraficoLinha(state.selectedLine);

  document.querySelectorAll('.dre-table tbody tr').forEach(tr => {
    if (tr.getAttribute('data-titulo') === titulo) {
      tr.classList.add('row-selected');
      tr.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else {
      tr.classList.remove('row-selected');
    }
  });
}

// ── Renderiza tabela DRE ─────────────────────────────────────────────────
function isRowSelected(tipo, nome) {
  if (!state.selectedLine) return false;
  return state.selectedLine.tipo === tipo && state.selectedLine.nome === nome;
}

function renderizarDRE() {
  const tbody = document.getElementById('dreBody');
  const rows  = [];

  state.dre.forEach((bloco, bi) => {
    const blocoId = `bloco-${bi}`;
    const isTotal = bloco.is_total;

    if (isTotal) {
      const selClass = isRowSelected('margem', 'Margem de Contribuição') ? 'row-selected' : '';
      rows.push(`
        <tr class="row-margem ${selClass}"
            data-tipo="margem" data-nome="Margem de Contribuição"
            onclick="onLinhaClick(event, this)">
          <td class="col-descr">${bloco.bloco}</td>
          <td class="col-num ${numClass(bloco.orcado)}">${fmtBRL(bloco.orcado)}</td>
          <td class="col-num ${numClass(bloco.realizado)}">${fmtBRL(bloco.realizado)}</td>
          <td class="col-pct">${pctBadge(bloco.pct_orc)}</td>
          <td class="col-pct">${pctBadge(bloco.pct_real)}</td>
          <td class="col-var ${evolClass(bloco.mom)}">${fmtEvol(bloco.mom)}</td>
          <td class="col-var ${evolClass(bloco.yoy)}">${fmtEvol(bloco.yoy)}</td>
          <td class="col-var ${evolClass(bloco.ytd_yoy)}">${fmtEvol(bloco.ytd_yoy)}</td>
          <td class="col-ro ${roClass(bloco.ro)}">${fmtRO(bloco.ro)}</td>
        </tr>`);
      return;
    }

    const bSelClass = isRowSelected('bloco', bloco.bloco) ? 'row-selected' : '';
    rows.push(`
      <tr class="row-bloco ${bSelClass}"
          data-bloco-id="${blocoId}" data-tipo="bloco" data-bloco="${bloco.bloco}" data-nome="${bloco.bloco}"
          onclick="onLinhaClick(event, this)">
        <td class="col-descr">
          <div class="row-bloco-header">
            <span class="chevron" onclick="event.stopPropagation(); toggleBloco('${blocoId}')">▼</span>
            <span>${bloco.bloco}</span>
          </div>
        </td>
        <td class="col-num ${numClass(bloco.orcado)}">${fmtBRL(bloco.orcado)}</td>
        <td class="col-num ${numClass(bloco.realizado)}">${fmtBRL(bloco.realizado)}</td>
        <td class="col-pct">${pctBadge(bloco.pct_orc)}</td>
        <td class="col-pct">${pctBadge(bloco.pct_real)}</td>
        <td class="col-var ${evolClass(bloco.mom)}">${fmtEvol(bloco.mom)}</td>
        <td class="col-var ${evolClass(bloco.yoy)}">${fmtEvol(bloco.yoy)}</td>
        <td class="col-var ${evolClass(bloco.ytd_yoy)}">${fmtEvol(bloco.ytd_yoy)}</td>
        <td class="col-ro ${roClass(bloco.ro)}">${fmtRO(bloco.ro)}</td>
      </tr>`);

    (bloco.titulos || []).forEach((titulo, ti) => {
      const tituloId   = `titulo-${bi}-${ti}`;
      const tCollClass = state.expandAll ? '' : 'collapsed';
      const tSelClass  = isRowSelected('titulo', titulo.titulo) ? 'row-selected' : '';

      rows.push(`
        <tr class="row-titulo ${tCollClass} ${blocoId}-content ${tSelClass}"
            data-titulo-id="${tituloId}" data-tipo="titulo" data-bloco="${bloco.bloco}" data-titulo="${titulo.titulo}" data-nome="${titulo.titulo}"
            onclick="onLinhaClick(event, this)">
          <td class="col-descr">
            <span class="chevron" onclick="event.stopPropagation(); toggleTitulo('${tituloId}')">▼</span>
            <span>${titulo.titulo}</span>
          </td>
          <td class="col-num ${numClass(titulo.orcado)}">${fmtBRL(titulo.orcado)}</td>
          <td class="col-num ${numClass(titulo.realizado)}">${fmtBRL(titulo.realizado)}</td>
          <td class="col-pct">${pctBadge(titulo.pct_orc)}</td>
          <td class="col-pct">${pctBadge(titulo.pct_real)}</td>
          <td class="col-var ${evolClass(titulo.mom)}">${fmtEvol(titulo.mom)}</td>
          <td class="col-var ${evolClass(titulo.yoy)}">${fmtEvol(titulo.yoy)}</td>
          <td class="col-var ${evolClass(titulo.ytd_yoy)}">${fmtEvol(titulo.ytd_yoy)}</td>
          <td class="col-ro ${roClass(titulo.ro)}">${fmtRO(titulo.ro)}</td>
        </tr>`);

      (titulo.linhas || []).forEach(ln => {
        const dSelClass = isRowSelected('detalhe', ln.descr) ? 'row-selected' : '';
        rows.push(`
          <tr class="row-detalhe ${tituloId}-content ${blocoId}-content ${dSelClass}"
              data-tipo="detalhe" data-bloco="${bloco.bloco}" data-titulo="${titulo.titulo}" data-descr="${ln.descr}" data-nome="${ln.descr}"
              style="display:${state.expandAll ? '' : 'none'}"
              onclick="onLinhaClick(event, this)">
            <td class="col-descr" style="padding-left:44px">${ln.descr || '—'}</td>
            <td class="col-num ${numClass(ln.orcado)}">${fmtBRL(ln.orcado)}</td>
            <td class="col-num ${numClass(ln.realizado)}">${fmtBRL(ln.realizado)}</td>
            <td class="col-pct">${pctBadge(ln.pct_orc)}</td>
            <td class="col-pct">${pctBadge(ln.pct_real)}</td>
            <td class="col-var ${evolClass(ln.mom)}">${fmtEvol(ln.mom)}</td>
            <td class="col-var ${evolClass(ln.yoy)}">${fmtEvol(ln.yoy)}</td>
            <td class="col-var ${evolClass(ln.ytd_yoy)}">${fmtEvol(ln.ytd_yoy)}</td>
            <td class="col-ro ${roClass(ln.ro)}">${fmtRO(ln.ro)}</td>
          </tr>`);
      });
    });
  });

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="loading-row" style="color:var(--text-muted)">
      Nenhum dado encontrado para o período selecionado.
    </td></tr>`;
  } else {
    tbody.innerHTML = rows.join('');
  }
}

// ── Toggles ──────────────────────────────────────────────────────────────
function toggleBloco(blocoId) {
  const header = document.querySelector(`[data-bloco-id="${blocoId}"] .row-bloco-header`) ||
                 document.querySelector(`[data-bloco="${blocoId}"] .row-bloco-header`);
  if (!header) return;
  const isOpen = !header.classList.contains('collapsed');
  header.classList.toggle('collapsed', isOpen);

  if (isOpen) {
    document.querySelectorAll(`.${blocoId}-content`).forEach(el => { el.style.display = 'none'; });
  } else {
    document.querySelectorAll(`.row-titulo.${blocoId}-content`).forEach(tRow => {
      tRow.style.display = '';
      const tId = tRow.getAttribute('data-titulo-id') || tRow.getAttribute('data-titulo');
      const tOpen = !tRow.classList.contains('collapsed');
      if (tId) {
        document.querySelectorAll(`.${tId}-content`).forEach(dRow => {
          dRow.style.display = tOpen ? '' : 'none';
        });
      }
    });
  }
}

function toggleTitulo(tituloId) {
  const row = document.querySelector(`[data-titulo-id="${tituloId}"]`) ||
              document.querySelector(`[data-titulo="${tituloId}"]`);
  if (!row) return;
  const isOpen = !row.classList.contains('collapsed');
  row.classList.toggle('collapsed', isOpen);
  const content = document.querySelectorAll(`.${tituloId}-content`);
  content.forEach(el => { el.style.display = isOpen ? 'none' : ''; });
}

function toggleExpandAll() {
  state.expandAll = !state.expandAll;
  const btn = document.getElementById('btnExpandAll');
  if (btn) {
    btn.textContent = state.expandAll ? 'Recolher tudo' : 'Expandir tudo';
  }
  renderizarDRE();
}

// ── Interatividade Cruzada: Clique em qualquer linha do DRE ──────────────
function onLinhaClick(event, trEl) {
  if (event.target.classList.contains('chevron')) {
    return;
  }

  const tipo     = trEl.getAttribute('data-tipo');
  const nome     = trEl.getAttribute('data-nome');
  const bloco    = trEl.getAttribute('data-bloco');
  const titulo   = trEl.getAttribute('data-titulo');
  const descrnat = trEl.getAttribute('data-descr');

  if (trEl.classList.contains('row-selected')) {
    resetarFiltroLinha();
    return;
  }

  // Se o usuário clicar em uma linha que estiver fechada, expande para mostrar os detalhes
  if (trEl.classList.contains('row-bloco')) {
    const blocoId = trEl.getAttribute('data-bloco-id');
    const header = trEl.querySelector('.row-bloco-header');
    if (header && header.classList.contains('collapsed')) {
      toggleBloco(blocoId);
    }
  } else if (trEl.classList.contains('row-titulo')) {
    const tituloId = trEl.getAttribute('data-titulo-id');
    if (trEl.classList.contains('collapsed')) {
      toggleTitulo(tituloId);
    }
  }

  document.querySelectorAll('.dre-table tbody tr.row-selected').forEach(r => r.classList.remove('row-selected'));
  document.querySelectorAll('.kpi-card').forEach(c => c.classList.remove('kpi-active'));
  trEl.classList.add('row-selected');

  state.selectedLine = { tipo, nome, bloco, titulo, descrnat };
  carregarGraficoLinha(state.selectedLine);
}

function resetarFiltroLinha() {
  document.querySelectorAll('.dre-table tbody tr.row-selected').forEach(r => r.classList.remove('row-selected'));
  document.querySelectorAll('.kpi-card').forEach(c => c.classList.remove('kpi-active'));
  state.selectedLine = null;

  const btnReset = document.getElementById('btnResetLinha');
  if (btnReset) btnReset.style.display = 'none';

  const tit = document.getElementById('tituloGraficoMensal');
  if (tit) tit.textContent = 'Evolução Mensal (Mês a Mês)';

  if (state.mensalData) {
    renderizarGraficoMensal(state.mensalData);
    renderizarGraficoAcumulado(state.mensalData, state.mes);
  }
}

function onKpiCardClick(key, cardEl) {
  if (cardEl.classList.contains('kpi-active')) {
    cardEl.classList.remove('kpi-active');
    resetarFiltroLinha();
    return;
  }
  document.querySelectorAll('.kpi-card').forEach(c => c.classList.remove('kpi-active'));
  cardEl.classList.add('kpi-active');

  const dre = state.dre || [];
  const allTitulos = dre.flatMap(b => b.titulos || []);

  if (key === 'vb') {
    const vb = allTitulos.find(t => (t.titulo || '').toLowerCase().includes('venda bruta'));
    if (vb) carregarGraficoLinha({ tipo: 'titulo', nome: vb.titulo, bloco: '1.Venda Liquida', titulo: vb.titulo });
  } else if (key === 'margem') {
    carregarGraficoLinha({ tipo: 'margem', nome: 'Margem de Contribuição' });
  } else if (key === 'bonif') {
    const bonif = allTitulos.find(t => (t.titulo || '').toLowerCase().includes('bonifica') && (t.titulo || '').toLowerCase().includes('client'))
               || allTitulos.find(t => (t.titulo || '').toLowerCase().includes('bonifica'));
    if (bonif) carregarGraficoLinha({ tipo: 'titulo', nome: bonif.titulo, bloco: '3.Despesas com Vendas', titulo: bonif.titulo });
  } else if (key === 'comissao') {
    const despVendas = dre.find(b => (b.bloco || '').toLowerCase().includes('despesas com vendas')) || {};
    const comiss = (despVendas.titulos || []).find(t => (t.titulo || '').toLowerCase().includes('comiss'))
                || allTitulos.find(t => (t.titulo || '').toLowerCase().includes('comiss'));
    if (comiss) carregarGraficoLinha({ tipo: 'titulo', nome: comiss.titulo, bloco: '3.Despesas com Vendas', titulo: comiss.titulo });
  } else if (key === 'guelta') {
    const guelta = allTitulos.find(t => (t.titulo || '').toLowerCase().includes('guelta'));
    if (guelta) carregarGraficoLinha({ tipo: 'titulo', nome: guelta.titulo, bloco: '3.Despesas com Vendas', titulo: guelta.titulo });
  } else if (key === 'despCom') {
    const desp = dre.find(b => (b.bloco || '').toLowerCase().includes('comercial operacional'));
    if (desp) carregarGraficoLinha({ tipo: 'bloco', nome: desp.bloco, bloco: desp.bloco });
  } else if (key === 'folha') {
    const folha = allTitulos.find(t => (t.titulo || '').toLowerCase().includes('folha') && !(t.titulo || '').toLowerCase().includes('comercial'))
               || allTitulos.find(t => (t.titulo || '').toLowerCase().includes('folha'));
    if (folha) {
      carregarGraficoLinha({
        tipo: 'titulo',
        nome: folha.titulo,
        bloco: '5.Despesas Administrativa Operacional',
        titulo: folha.titulo
      });
    }
  }
}

async function carregarGraficoLinha(filtro) {
  const btnReset = document.getElementById('btnResetLinha');
  const tit = document.getElementById('tituloGraficoMensal');
  if (btnReset) btnReset.style.display = 'inline-block';
  if (tit) tit.textContent = `Evolução Mensal — ${filtro.nome}`;

  const p = new URLSearchParams({
    ano: getAnoParam(),
    emp: getEmpParam(),
    cenc: getCencParam()
  });

  if (filtro.tipo === 'bloco' && filtro.bloco) {
    p.set('bloco', filtro.bloco);
  } else if (filtro.tipo === 'titulo') {
    if (filtro.bloco) p.set('bloco', filtro.bloco);
    if (filtro.titulo) p.set('titulo', filtro.titulo);
  } else if (filtro.tipo === 'detalhe') {
    if (filtro.bloco) p.set('bloco', filtro.bloco);
    if (filtro.titulo) p.set('titulo', filtro.titulo);
    if (filtro.descrnat) p.set('descrnat', filtro.descrnat);
  }

  try {
    const res = await fetch('/api/dre/mensal?' + p);
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    const mensal = data.mensal || [];
    renderizarGraficoMensal(mensal);
    renderizarGraficoAcumulado(mensal, state.mes, filtro.nome);
  } catch (e) {
    showToast('Erro ao carregar linha: ' + e.message, 'error');
  }
}

// ── Atualização dos 6 KPI Cards com Métricas e Mês Anterior ─────────────
function atualizarKPIs() {
  const dre = state.dre;
  if (!dre || dre.length === 0) return;

  const allTitulos = dre.flatMap(b => b.titulos || []);

  // 1. Venda Bruta
  const vb = allTitulos.find(t => t.titulo?.toLowerCase().includes('venda bruta')) || {};
  const elVBVal = document.getElementById('kpiVBVal');
  const elVBSub = document.getElementById('kpiVBSub');
  if (elVBVal) elVBVal.textContent = fmtBRL(vb.realizado);
  if (elVBSub) elVBSub.innerHTML = renderKpiSub(vb.orcado, vb.ro, vb.mom, vb.yoy, vb.ytd_yoy, vb.pct_orc, vb.pct_real);

  // 2. Margem de Contribuição
  const margem = dre.find(b => b.is_total) || {};
  const elMVal = document.getElementById('kpiMargemVal');
  const elMSub = document.getElementById('kpiMargemSub');
  if (elMVal) elMVal.textContent = fmtBRL(margem.realizado);
  if (elMSub) elMSub.innerHTML = renderKpiSub(margem.orcado, margem.ro, margem.mom, margem.yoy, margem.ytd_yoy, margem.pct_orc, margem.pct_real);

  // 3. Bonificação (Bonificação Clientes)
  const bonif = allTitulos.find(t => {
    const s = (t.titulo || '').toLowerCase();
    return s.includes('bonifica') && s.includes('client');
  }) || allTitulos.find(t => (t.titulo || '').toLowerCase().includes('bonifica')) || {};
  const elBVal = document.getElementById('kpiBonifVal');
  const elBSub = document.getElementById('kpiBonifSub');
  if (elBVal) elBVal.textContent = fmtBRL(bonif.realizado);
  if (elBSub) elBSub.innerHTML = renderKpiSub(bonif.orcado, bonif.ro, bonif.mom, bonif.yoy, bonif.ytd_yoy, bonif.pct_orc, bonif.pct_real);

  // 4. Comissão (Comissões)
  const despVendas = dre.find(b => (b.bloco || '').toLowerCase().includes('despesas com vendas')) || {};
  const comissao = (despVendas.titulos || []).find(t => (t.titulo || '').toLowerCase().includes('comiss'))
                || allTitulos.find(t => (t.titulo || '').toLowerCase().includes('comiss')) || {};
  const elCVal = document.getElementById('kpiComissaoVal');
  const elCSub = document.getElementById('kpiComissaoSub');
  if (elCVal) elCVal.textContent = fmtBRL(comissao.realizado);
  if (elCSub) elCSub.innerHTML = renderKpiSub(comissao.orcado, comissao.ro, comissao.mom, comissao.yoy, comissao.ytd_yoy, comissao.pct_orc, comissao.pct_real);

  // 5. Guelta
  const guelta = allTitulos.find(t => (t.titulo || '').toLowerCase().includes('guelta')) || {};
  const elGVal = document.getElementById('kpiGueltaVal');
  const elGSub = document.getElementById('kpiGueltaSub');
  if (elGVal) elGVal.textContent = fmtBRL(guelta.realizado);
  if (elGSub) elGSub.innerHTML = renderKpiSub(guelta.orcado, guelta.ro, guelta.mom, guelta.yoy, guelta.ytd_yoy, guelta.pct_orc, guelta.pct_real);

  // 6. Despesa Comercial Operacional
  const despCom = dre.find(b => (b.bloco || '').toLowerCase().includes('comercial operacional')) || {};
  const elDVal = document.getElementById('kpiDespComercialVal');
  const elDSub = document.getElementById('kpiDespComercialSub');
  if (elDVal) elDVal.textContent = fmtBRL(despCom.realizado);
  if (elDSub) elDSub.innerHTML = renderKpiSub(despCom.orcado, despCom.ro, despCom.mom, despCom.yoy, despCom.ytd_yoy, despCom.pct_orc, despCom.pct_real);

  // 7. Folha de Pagamento e Benefícios
  const folha = allTitulos.find(t => (t.titulo || '').toLowerCase().includes('folha') && !(t.titulo || '').toLowerCase().includes('comercial'))
             || allTitulos.find(t => (t.titulo || '').toLowerCase().includes('folha')) || {};
  const elFVal = document.getElementById('kpiFolhaVal');
  const elFSub = document.getElementById('kpiFolhaSub');
  if (elFVal) elFVal.textContent = fmtBRL(folha.realizado);
  if (elFSub) elFSub.innerHTML = renderKpiSub(folha.orcado, folha.ro, folha.mom, folha.yoy, folha.ytd_yoy, folha.pct_orc, folha.pct_real);
}

// ── Plugin para Exibir Valores Compactos sobre as Colunas (Opção 2) ──────
const barValueLabelsPlugin = {
  id: 'barValueLabels',
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    ctx.save();
    ctx.font = '700 8.5px Montserrat, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';

    chart.data.datasets.forEach((dataset, datasetIndex) => {
      const meta = chart.getDatasetMeta(datasetIndex);
      if (meta.hidden) return;

      meta.data.forEach((bar, index) => {
        const val = dataset.data[index];
        if (val == null || Math.abs(val) < 0.001) return;

        const strVal = fmtCompact(val);
        if (!strVal) return;

        ctx.fillStyle = datasetIndex === 0 ? '#CB9727' : '#ffffff';
        const yPos = val >= 0 ? bar.y - 3 : bar.y + 13;
        ctx.fillText(strVal, bar.x, yPos);
      });
    });
    ctx.restore();
  }
};

// ── Gráficos ─────────────────────────────────────────────────────────────
function renderizarGraficoMensal(data) {
  const canvas = document.getElementById('chartMensal');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (state.chartMensal) state.chartMensal.destroy();
  if (!data || data.length === 0) return;

  const tit = document.getElementById('tituloGraficoMensal');
  if (tit && !state.selectedLine) {
    tit.textContent = 'Margem — Evolução Mensal (Mês a Mês)';
  }

  const NOMES = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  const porMes = {};
  data.forEach(r => {
    const m = r.MES;
    if (!porMes[m]) porMes[m] = { real: 0, orc: 0 };
    porMes[m].real += Number(r.REALIZADO || 0);
    porMes[m].orc  += Number(r.ORCADO    || 0);
  });

  // Mostrar apenas até o mês atual/selecionado e excluir meses onde o realizado é igual a zero (evita poluição)
  const mesLimite = Number(state.mes) || 12;
  let keys = Object.keys(porMes)
    .map(Number)
    .sort((a,b) => a-b)
    .filter(m => m <= mesLimite && Math.abs(porMes[m].real) > 10);

  // Fallback se não houver nenhum mês com realizado > 10
  if (keys.length === 0) {
    keys = Object.keys(porMes)
      .map(Number)
      .sort((a,b) => a-b)
      .filter(m => m <= mesLimite);
  }

  const labels  = keys.map(m => NOMES[m-1]);
  const realArr = keys.map(m => porMes[m].real);
  const orcArr  = keys.map(m => porMes[m].orc);

  state.chartMensal = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Realizado',
          data: realArr,
          backgroundColor: '#CB9727',
          borderRadius: 4,
          borderSkipped: false,
          categoryPercentage: 0.82,
          barPercentage: 0.88,
        },
        {
          label: 'Orçado',
          data: orcArr,
          backgroundColor: 'rgba(255, 255, 255, 0.2)',
          borderColor: 'rgba(255, 255, 255, 0.45)',
          borderWidth: 1,
          borderRadius: 4,
          borderSkipped: false,
          categoryPercentage: 0.82,
          barPercentage: 0.88,
        },
      ],
    },
    plugins: [barValueLabelsPlugin],
    options: chartOpts(),
  });
}

function renderizarGraficoAcumulado(data, mesFiltro, filtroNome) {
  const canvas = document.getElementById('chartAcumulado');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (state.chartAcumulado) state.chartAcumulado.destroy();

  const NOMES = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  const MESES_COMPLETO = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                         'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];

  const porMes = {};
  (data || []).forEach(r => {
    const m = Number(r.MES);
    if (!porMes[m]) porMes[m] = { real: 0, orc: 0 };
    porMes[m].real += Number(r.REALIZADO || 0);
    porMes[m].orc  += Number(r.ORCADO    || 0);
  });

  const mMax = Math.min(Math.max(Number(mesFiltro) || 1, 1), 12);
  const labels = [];
  const realAcumArr = [];
  const orcAcumArr = [];
  let cumReal = 0;
  let cumOrc = 0;

  for (let m = 1; m <= mMax; m++) {
    labels.push(NOMES[m - 1]);
    cumReal += (porMes[m]?.real || 0);
    cumOrc  += (porMes[m]?.orc  || 0);
    realAcumArr.push(cumReal);
    orcAcumArr.push(cumOrc);
  }

  const totalReal = cumReal;
  const totalOrc = cumOrc;
  const diff = totalReal - totalOrc;
  const pctDesvio = totalOrc ? ((totalReal - totalOrc) / Math.abs(totalOrc)) * 100 : 0;
  const isDentro = totalReal >= totalOrc;

  // Atualiza título dinâmico e status badge
  const elTitulo = document.getElementById('tituloAcumulado');
  if (elTitulo) {
    if (filtroNome) {
      elTitulo.textContent = `Margem — Acumulado até ${MESES_COMPLETO[mMax - 1]} (${filtroNome})`;
    } else {
      elTitulo.textContent = `Margem — Acumulado até ${MESES_COMPLETO[mMax - 1]} (Jan–${NOMES[mMax - 1]})`;
    }
  }

  const elBadge = document.getElementById('badgeStatusPlanejado');
  if (elBadge) {
    elBadge.className = 'status-badge ' + (isDentro ? 'dentro' : 'fora');
    elBadge.innerHTML = isDentro ? '● DENTRO DO PLANEJADO' : '▲ FORA DO PLANEJADO';
  }

  // Atualiza mini-cards de diagnóstico
  const elOrc = document.getElementById('acumOrcVal');
  if (elOrc) elOrc.textContent = fmtBRL(totalOrc);

  const elReal = document.getElementById('acumRealVal');
  if (elReal) elReal.textContent = fmtBRL(totalReal);

  const elDiff = document.getElementById('acumDiffVal');
  if (elDiff) {
    elDiff.textContent = (diff >= 0 ? '+' : '') + fmtBRL(diff);
    elDiff.className = 'diag-val ' + (diff >= 0 ? 'val-pos' : 'val-neg');
  }

  const elPct = document.getElementById('acumPctVal');
  if (elPct) {
    elPct.textContent = (pctDesvio >= 0 ? '+' : '') + pctDesvio.toFixed(1) + '%';
    elPct.className = 'diag-val ' + (pctDesvio >= 0 ? 'val-pos' : 'val-neg');
  }

  // Cria gráfico Chart.js (Orçado primeiro, Realizado segundo)
  state.chartAcumulado = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Orçado Acum.',
          data: orcAcumArr,
          backgroundColor: 'rgba(255,255,255,.16)',
          borderColor: 'rgba(255,255,255,.4)',
          borderWidth: 1,
          borderRadius: 4,
        },
        {
          label: 'Realizado Acum.',
          data: realAcumArr,
          backgroundColor: 'rgba(203,151,39,.85)',
          borderColor: '#CB9727',
          borderWidth: 1,
          borderRadius: 4,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top',
          align: 'end',
          labels: {
            boxWidth: 10, boxHeight: 10, padding: 8,
            color: '#ffffff',
            font: { family: 'Montserrat', size: 10, weight: '600' }
          }
        },
        tooltip: {
          backgroundColor: '#1e1e1e', borderColor: '#CB9727', borderWidth: 1,
          titleColor: '#CB9727', bodyColor: '#f5f5f5',
          callbacks: {
            label: ctx => ` ${ctx.dataset.label}: ${fmtBRL(ctx.parsed.y)}`,
            afterBody: ctx => {
              const idx = ctx[0].dataIndex;
              const r = realAcumArr[idx] || 0;
              const o = orcAcumArr[idx] || 0;
              const d = r - o;
              const p = o ? ((r - o) / Math.abs(o)) * 100 : 0;
              return `Diferença: ${d >= 0 ? '+' : ''}${fmtBRL(d)} (${p >= 0 ? '+' : ''}${p.toFixed(1)}%)`;
            }
          }
        }
      },
      scales: {
        x: {
          ticks: { color: '#aaa', font: { family: 'Montserrat', size: 10, weight: '600' } },
          grid: { display: false }
        },
        y: {
          ticks: {
            color: '#aaa',
            font: { family: 'Montserrat', size: 9, weight: '500' },
            callback: v => (v >= 1000000 || v <= -1000000) ? (v/1000000).toFixed(1)+'M' : (v >= 1000 || v <= -1000) ? (v/1000).toFixed(0)+'k' : v
          },
          grid: { color: 'rgba(255,255,255,.05)' }
        }
      }
    }
  });
}

function chartOpts() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    layout: {
      padding: { top: 24, bottom: 4 }
    },
    plugins: {
      legend: {
        position: 'top',
        align: 'end',
        labels: { boxWidth: 12, boxHeight: 12, padding: 12, color: '#ffffff', font: { family: 'Montserrat', size: 11, weight: '600' } }
      },
      tooltip: {
        backgroundColor: '#181818',
        borderColor: '#CB9727',
        borderWidth: 1,
        titleColor: '#CB9727',
        titleFont: { family: 'Montserrat', size: 12, weight: '700' },
        bodyColor: '#f5f5f5',
        bodyFont: { family: 'Montserrat', size: 11, weight: '500' },
        padding: 10,
        cornerRadius: 6,
        callbacks: { label: ctx => ` ${ctx.dataset.label}: ${fmtBRL(ctx.parsed.y)}` },
      },
    },
    scales: {
      x: { ticks: { color: '#aaa', font: { family: 'Montserrat', size: 11, weight: '500' } }, grid: { display: false } },
      y: {
        grace: '15%',
        ticks: {
          color: '#aaa',
          font: { family: 'Montserrat', size: 10, weight: '500' },
          callback: v => (v >= 1000000 || v <= -1000000) ? (v/1000000).toFixed(1)+'M' : (v >= 1000 || v <= -1000) ? (v/1000).toFixed(0)+'k' : v
        },
        grid: { color: 'rgba(255,255,255,.05)' }
      },
    },
  };
}

// ── Utilitários ──────────────────────────────────────────────────────────
function numClass(v) { return Number(v)<0 ? 'val-neg' : Number(v)>0 ? 'val-pos' : 'val-zero'; }
function roClass(v)  { return Number(v)<0 ? 'val-neg' : Number(v)>0 ? 'val-pos' : ''; }
function pctBadge(v) {
  if (v==null) return '<span class="pct-badge neu">—</span>';
  const n = Number(v);
  return `<span class="pct-badge ${n>0?'pos':n<0?'neg':'neu'}">${fmtPct(n)}</span>`;
}

function atualizarTimestamp() {
  document.getElementById('lastUpdate').textContent =
    'Atualizado: ' + new Date().toLocaleString('pt-BR', {
      day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'
    });
}

// ── Export CSV ───────────────────────────────────────────────────────────
function exportarCSV() {
  if (!state.dre?.length) { showToast('Sem dados para exportar', 'error'); return; }
  const linhas = [['Bloco','Título','Descrição','Orçado (R$)','Realizado (R$)','MoM','YoY','YTD Real.','% VB Orç.','% VB Real.','R/O']];
  state.dre.forEach(bloco => {
    if (bloco.is_total) {
      linhas.push([bloco.bloco,'','',bloco.orcado,bloco.realizado,bloco.mom,bloco.yoy,bloco.real_ytd,bloco.pct_orc,bloco.pct_real,bloco.ro]);
    } else {
      linhas.push([bloco.bloco,'Subtotal','',bloco.orcado,bloco.realizado,bloco.mom,bloco.yoy,bloco.real_ytd,bloco.pct_orc,bloco.pct_real,bloco.ro]);
      (bloco.titulos||[]).forEach(t => {
        linhas.push([bloco.bloco,t.titulo,'',t.orcado,t.realizado,t.mom,t.yoy,t.real_ytd,t.pct_orc,t.pct_real,t.ro]);
        (t.linhas||[]).forEach(ln => {
          linhas.push([bloco.bloco,t.titulo,ln.descr,ln.orcado,ln.realizado,ln.mom,ln.yoy,ln.real_ytd,ln.pct_orc,ln.pct_real,ln.ro]);
        });
      });
    }
  });
  const csv  = linhas.map(r => r.map(c => `"${c??''}"`).join(',')).join('\n');
  const blob = new Blob(['\uFEFF'+csv], {type:'text/csv;charset=utf-8;'});
  const a    = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(blob),
    download: `DRE_${state.ano}_M${String(state.mes).padStart(2,'0')}.csv`
  });
  a.click();
  showToast('CSV exportado!', 'success');
}

// ── Exportar para Excel (.xlsx) no Modelo Oficial Power BI (Mês a Mês Jan..Dez + Total) ──
function exportarParaExcel() {
  const p = new URLSearchParams({
    ano: getAnoParam(),
    emp: getEmpParam(),
    cenc: getCencParam(),
  });

  showToast('Gerando DRE no Modelo Oficial Power BI (Mês a Mês)...', 'info');
  window.location.href = '/api/dre/exportar-excel?' + p.toString();
}


// ════ AGENTE DE IA (N8N WEBHOOK) ═════════════════════════════════════════════
const DEFAULT_WEBHOOK = 'https://n8n.seu-dominio.com.br/webhook/dre-agent';
function getWebhookUrl() {
  return localStorage.getItem('n8n_webhook_url') || DEFAULT_WEBHOOK;
}

document.addEventListener('DOMContentLoaded', () => {
  const widget = document.getElementById('ai-chat-widget');
  const header = document.getElementById('ai-chat-header');
  const btnToggle = document.getElementById('ai-chat-toggle');
  const input = document.getElementById('ai-chat-input');
  const btnSend = document.getElementById('ai-chat-send');
  const body = document.getElementById('ai-chat-body');

  if(!widget) return;

  // Arrastar widget
  let isDragging = false;
  let currentX;
  let currentY;
  let initialX;
  let initialY;
  let xOffset = 0;
  let yOffset = 0;

  header.addEventListener('mousedown', dragStart);
  document.addEventListener('mousemove', drag);
  document.addEventListener('mouseup', dragEnd);

  function dragStart(e) {
    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;
    if (e.target === header || header.contains(e.target)) {
      isDragging = true;
    }
  }

  function drag(e) {
    if (isDragging) {
      e.preventDefault();
      currentX = e.clientX - initialX;
      currentY = e.clientY - initialY;
      xOffset = currentX;
      yOffset = currentY;
      setTranslate(currentX, currentY, widget);
    }
  }

  function dragEnd(e) {
    initialX = currentX;
    initialY = currentY;
    isDragging = false;
  }

  function setTranslate(xPos, yPos, el) {
    el.style.transform = `translate3d(${xPos}px, ${yPos}px, 0)`;
  }

  function toggleChat(e) {
    // Só expande/colapsa se não estiver arrastando
    if(xOffset !== currentX || yOffset !== currentY) return; 
    widget.classList.toggle('ai-chat-collapsed');
    btnToggle.textContent = widget.classList.contains('ai-chat-collapsed') ? '↑' : '_';
    if(!widget.classList.contains('ai-chat-collapsed')) {
      input.focus();
    }
  }

  // Header click now handles dragging vs toggling 
  // We'll make it only toggle if movement was small
  let startX, startY;
  header.addEventListener('mousedown', (e) => {
      startX = e.clientX; startY = e.clientY;
  });
  header.addEventListener('mouseup', (e) => {
      let diffX = Math.abs(e.clientX - startX);
      let diffY = Math.abs(e.clientY - startY);
      if(diffX < 5 && diffY < 5) {
          toggleChat(e);
      }
  });

  const btnConfig = document.getElementById('ai-chat-config');
  if(btnConfig) {
    btnConfig.addEventListener('click', (e) => {
      e.stopPropagation(); // Prevent toggling the chat when clicking the gear
      let currentUrl = getWebhookUrl();
      let newUrl = prompt('Configuração do Agente IA\n\nInsira a URL do Webhook do n8n:', currentUrl);
      if(newUrl !== null && newUrl.trim() !== '') {
        localStorage.setItem('n8n_webhook_url', newUrl.trim());
        alert('Webhook configurado com sucesso!');
      }
    });
  }
  
  function addMessage(text, sender) {
    const msg = document.createElement('div');
    msg.className = `ai-message ${sender}`;
    msg.textContent = text;
    body.appendChild(msg);
    body.scrollTop = body.scrollHeight;
  }

  async function sendMessage() {
    const text = input.value.trim();
    if(!text) return;
    
    addMessage(text, 'user');
    input.value = '';
    
    const loadingId = 'loading-' + Date.now();
    const loading = document.createElement('div');
    loading.className = 'ai-message ai';
    loading.id = loadingId;
    loading.textContent = 'Analisando...';
    body.appendChild(loading);
    body.scrollTop = body.scrollHeight;

    try {
      const contextoDRE = {
        filtros: { ano: state.ano, mes: state.mes, empresa: state.empresa, centroCusto: state.centroCusto },
        margem: document.getElementById('kpiMargemVal')?.textContent || '',
        vendaBruta: document.getElementById('kpiVBVal')?.textContent || ''
      };

      const url = getWebhookUrl();
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text, contexto: contextoDRE })
      });

      const result = await response.json();
      document.getElementById(loadingId).remove();
      
      if(result && result.resposta) {
        addMessage(result.resposta, 'ai');
      } else {
        addMessage('Resposta recebida, mas em formato desconhecido.', 'ai');
      }
    } catch(err) {
      document.getElementById(loadingId).remove();
      addMessage('Desculpe, não consegui conectar ao Agente de IA. Verifique a URL do Webhook.', 'ai');
      console.error('Erro N8N:', err);
    }
  }

  btnSend.addEventListener('click', sendMessage);
  input.addEventListener('keypress', (e) => {
    if(e.key === 'Enter') sendMessage();
  });
});
