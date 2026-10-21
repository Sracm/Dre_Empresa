/* ═══════════════════════════════════════════════════════════════════════
   DRE GESTORES — app.js
   Sistema de polling assíncrono para queries Oracle lentas
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

// ── Estado global ────────────────────────────────────────────────────────
const state = {
  anos: [2026],
  meses: [9],
  emps: [],   // [] ou todas = ALL
  cenc: [],   // [] ou todas = ALL
  anosLista: [],
  mesesLista: [],
  empresasLista: [],
  centrosLista: [],
  get ano() { return this.anos && this.anos.length ? this.anos[0] : 2026; },
  get mes() { return this.meses && this.meses.length ? this.meses[this.meses.length - 1] : 9; },
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
  modoTabelaTopo: 'mensal', // 'mensal' ou 'acumulado'
  acumuladoExpandAll: false,
  margemAcumuladaAberta: true,
  blocosAcumuladoAbertos: new Set(),
  tabelaMensalData: null,
  mensalExpandAll: false,
  centrosMensalAbertos: new Set(),
  mensalSortCol: 'realizado',
  mensalSortAsc: false,
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
const fmtPct = v => v == null ? '—' : Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '%';
const fmtRO  = v => {
  if (v == null || isNaN(v)) return '—';
  const n = Number(v);
  return (n >= 0 ? '+' : '') + n.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '%';
};

// Formatação em valor completo sem decimais (ex: 3.450.800)
const fmtCompact = v => {
  if (v == null || Math.abs(v) < 0.001) return '';
  const n = Number(v);
  return Math.round(n).toLocaleString('pt-BR');
};

// ── Helper para Subtítulo dos KPI Cards (Orçado, R/O, MoM, YoY, YTD YoY, % VB Orç., % VB Real.)
function renderKpiSub(orc, roPct, momPct, yoyPct, ytdYoyPct, pctOrc, pctReal, isDespesa = false) {
  // R/O
  const roStr = roPct != null ? (roPct >= 0 ? '+' : '') + Number(roPct).toFixed(1) + '%' : '—';
  const roClass = (roPct || 0) >= 0 ? 'up' : 'down';

  // MoM
  const momStr = momPct != null ? (momPct > 0 ? `▲ +${Number(momPct).toFixed(1)}%` : momPct < 0 ? `▼ ${Number(momPct).toFixed(1)}%` : '0.0%') : '—';
  const momClass = momPct == null ? 'zero' : (isDespesa ? (momPct > 0 ? 'down' : momPct < 0 ? 'up' : 'zero') : (momPct >= 0 ? 'up' : 'down'));

  // YoY
  const yoyStr = yoyPct != null ? (yoyPct > 0 ? `▲ +${Number(yoyPct).toFixed(1)}%` : yoyPct < 0 ? `▼ ${Number(yoyPct).toFixed(1)}%` : '0.0%') : '—';
  const yoyClass = yoyPct == null ? 'zero' : (isDespesa ? (yoyPct > 0 ? 'down' : yoyPct < 0 ? 'up' : 'zero') : (yoyPct >= 0 ? 'up' : 'down'));

  // YTD YoY
  const ytdStr = ytdYoyPct != null ? (ytdYoyPct > 0 ? `▲ +${Number(ytdYoyPct).toFixed(1)}%` : ytdYoyPct < 0 ? `▼ ${Number(ytdYoyPct).toFixed(1)}%` : '0.0%') : '—';
  const ytdClass = ytdYoyPct == null ? 'zero' : (isDespesa ? (ytdYoyPct > 0 ? 'down' : ytdYoyPct < 0 ? 'up' : 'zero') : (ytdYoyPct >= 0 ? 'up' : 'down'));

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
function evolClass(v, isDespesa = false) {
  if (v == null) return 'val-zero';
  const n = Number(v);
  if (n === 0) return 'val-zero';
  if (isDespesa) {
    return n > 0 ? 'val-neg' : 'val-pos';
  } else {
    return n > 0 ? 'val-pos' : 'val-neg';
  }
}

function renderYtdCell(v) {
  return `<td class="col-num">${fmtBRL(v)}</td>`;
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
  iniciarContadorProximaCarga();
  carregarUltimaSincronizacao();
  await carregarFiltros();
  carregarTudo(false, false); // Carga inicial rápida a partir do cache (sem barra de progresso e sem sincronização com GitHub)

  const btnCarregar = document.getElementById('btnCarregar');
  if (btnCarregar) btnCarregar.addEventListener('click', () => iniciarSincronizacaoOracle());

  const btnAplicar = document.getElementById('btnAplicar');
  if (btnAplicar) btnAplicar.addEventListener('click', () => carregarTudo(false, false));

  const btnExportExcel = document.getElementById('btnExportExcel');
  if (btnExportExcel) btnExportExcel.addEventListener('click', (e) => exportarParaExcel(e));

  const btnExportExcelTop = document.getElementById('btnExportExcelTop');
  if (btnExportExcelTop) btnExportExcelTop.addEventListener('click', (e) => exportarParaExcel(e));

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
  document.querySelectorAll('.metric-kpi-card[data-kpi], .kpi-card[data-kpi]').forEach(card => {
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

// ── Gerenciador da Barra de Progresso de Carga do Report ─────────────────────
const ReportProgressBar = {
  container: null,
  fill: null,
  pct: null,
  title: null,
  msg: null,
  icon: null,
  simTimer: null,
  currentVal: 0,
  targetVal: 0,
  isActive: false,
  pendingLoads: 0,

  init() {
    this.container = document.getElementById('reportProgressBarContainer');
    this.fill = document.getElementById('reportProgressFill');
    this.pct = document.getElementById('reportProgressPct');
    this.title = document.getElementById('reportProgressTitle');
    this.msg = document.getElementById('reportProgressMsg');
    this.icon = document.getElementById('reportProgressIcon');
  },

  start(title = 'Sincronizando com o Banco Oracle Sankhya...') {
    if (!this.container) this.init();
    if (!this.container) return;

    this.isActive = true;
    if (this.pollTimer) clearInterval(this.pollTimer);

    this.container.style.display = 'block';
    this.container.style.opacity = '1';
    
    if (this.fill) {
      this.fill.classList.remove('success');
      this.fill.classList.remove('error');
      this.fill.style.width = '8%';
    }
    if (this.pct) this.pct.textContent = '8%';
    if (this.title) this.title.textContent = title;
    if (this.msg) this.msg.textContent = 'Conectando ao Oracle Sankhya e consultando lançamentos analíticos...';
    if (this.icon) {
      this.icon.className = 'material-symbols-outlined report-progress-icon';
      this.icon.textContent = 'sync';
    }

    const btnCarregar = document.getElementById('btnCarregar');
    if (btnCarregar) {
      btnCarregar.disabled = true;
      btnCarregar.style.opacity = '0.65';
      btnCarregar.style.pointerEvents = 'none';
    }
  },

  step(pct, msg) {
    if (!this.isActive) return;
    this.currentVal = pct;
    this.updateView(pct);
    if (msg && this.msg) this.msg.textContent = msg;
  },

  notifyPartDone(partName) {
    if (!this.isActive) return;
    if (typeof this.pendingLoads !== 'number' || isNaN(this.pendingLoads) || this.pendingLoads <= 0) {
      this.pendingLoads = 3;
    }
    this.pendingLoads--;
    if (this.pendingLoads === 2) {
      this.step(55, 'Demonstrativo DRE processado com sucesso...');
    } else if (this.pendingLoads === 1) {
      this.step(85, 'Processando evolução mensal e acumulado...');
    } else if (this.pendingLoads <= 0) {
      this.complete();
    }
  },

  complete(title = 'Banco Oracle sincronizado com sucesso!', msg = 'Demonstrativo, gráficos e indicadores 100% atualizados.') {
    if (!this.isActive) return;
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.currentVal = 100;
    this.updateView(100);

    if (this.fill) {
      this.fill.classList.remove('error');
      this.fill.classList.add('success');
    }
    if (this.icon) {
      this.icon.className = 'material-symbols-outlined report-progress-icon success';
      this.icon.textContent = 'check_circle';
    }
    if (this.title) this.title.textContent = title;
    if (this.msg) this.msg.textContent = msg;

    const btnCarregar = document.getElementById('btnCarregar');
    if (btnCarregar) {
      btnCarregar.disabled = false;
      btnCarregar.style.opacity = '1';
      btnCarregar.style.pointerEvents = 'auto';
    }

    showToast(title, 'success');

    setTimeout(() => {
      if (this.container) {
        this.container.style.transition = 'opacity 0.6s ease';
        this.container.style.opacity = '0';
        setTimeout(() => {
          this.container.style.display = 'none';
          this.container.style.transition = '';
          this.isActive = false;
        }, 600);
      }
    }, 2800);
  },

  error(msg = 'Erro na sincronização com o Oracle.') {
    if (this.pollTimer) clearInterval(this.pollTimer);
    if (this.fill) {
      this.fill.classList.remove('success');
      this.fill.classList.add('error');
    }
    if (this.icon) {
      this.icon.className = 'material-symbols-outlined report-progress-icon error';
      this.icon.textContent = 'error';
    }
    if (this.title) this.title.textContent = 'Falha ao sincronizar com Oracle';
    if (this.msg) this.msg.textContent = msg;

    const btnCarregar = document.getElementById('btnCarregar');
    if (btnCarregar) {
      btnCarregar.disabled = false;
      btnCarregar.style.opacity = '1';
      btnCarregar.style.pointerEvents = 'auto';
    }
    showToast(msg, 'error');

    setTimeout(() => {
      if (this.container) {
        this.container.style.transition = 'opacity 0.6s ease';
        this.container.style.opacity = '0';
        setTimeout(() => {
          this.container.style.display = 'none';
          this.container.style.transition = '';
          this.isActive = false;
        }, 600);
      }
    }, 4500);
  },

  updateView(val) {
    if (this.fill) this.fill.style.width = val + '%';
    if (this.pct) this.pct.textContent = val + '%';
  }
};

// ── Sincronização Real com o Oracle ao Clicar em Carregar ────────────────
async function iniciarSincronizacaoOracle() {
  const ano = getAnoParam();
  const mes = state.mes || 9;

  ReportProgressBar.start(`Sincronizando ${mes}/${ano} com Oracle...`);

  try {
    const res = await fetch(`/api/dre/sincronizar-oracle?ano=${ano}&mes=${mes}&modo=dois_meses`, {
      method: 'POST'
    });
    const data = await res.json();

    if (res.status === 409) {
      showToast(data.msg || 'Sincronização já em andamento.', 'info');
    }

    // Polling contínuo do status no backend
    ReportProgressBar.pollTimer = setInterval(async () => {
      try {
        const sRes = await fetch('/api/dre/sincronizar-status');
        const sData = await sRes.json();

        if (sData.status === 'running') {
          const detalheStr = sData.detalhe ? ` (${sData.detalhe})` : '';
          ReportProgressBar.step(sData.pct || 15, `${sData.msg}${detalheStr}`);
        } else if (sData.status === 'success') {
          clearInterval(ReportProgressBar.pollTimer);
          ReportProgressBar.complete(
            'Banco Oracle sincronizado com sucesso!',
            `${sData.linhas_afetadas || 0} lançamentos gravados em ${Math.round(sData.duracao_seg || 0)}s.`
          );

          // Salva status no Git em background
          fetch('/api/git/salvar')
            .then(r => r.json())
            .then(d => console.log('[GIT SYNC]', d))
            .catch(err => console.warn('Erro ao disparar git sync:', err));

          // Recarrega todos os componentes da tela com os números frescos
          carregarTudo(false, false);
        } else if (sData.status === 'error') {
          clearInterval(ReportProgressBar.pollTimer);
          ReportProgressBar.error(sData.msg || 'Erro na extração dos dados Oracle.');
        }
      } catch (err) {
        console.warn('Erro ao consultar status da sincronização:', err);
      }
    }, 1500);

  } catch (err) {
    ReportProgressBar.error('Erro ao conectar ao servidor: ' + err.message);
  }
}

// ── Carrega o dashboard completo com polling ─────────────────────────────
function carregarTudo(somenteDoisMeses = false, isUserClick = false) {
  // Limpa barra de progresso se não for sincronização ativa
  if (!ReportProgressBar.isActive) {
    const pContainer = document.getElementById('reportProgressBarContainer');
    if (pContainer) pContainer.style.display = 'none';
  }

  // Limpa cache de meses antigos ao carregar ou aplicar filtros para que os números correspondam exatamente ao banco
  if (!somenteDoisMeses) {
    state.mensalData = [];
  }

  const mesAtual = state.mes || 9;
  const mesAnt = mesAtual > 1 ? mesAtual - 1 : 12;

  const p = new URLSearchParams({
    ano: getAnoParam(),
    mes: getMesParam(),
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
    setLoadingDRE(`Atualizando mês atual (${mesAtual}) e anterior (${mesAnt})…`);
  } else {
    setLoadingDRE('Carregando demonstrativo completo do banco…');
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
  carregarUltimaSincronizacao();
  try { ReportProgressBar?.notifyPartDone?.('dre'); } catch (_) {}
  if (somenteDoisMeses) {
    showToast('Mês atual e anterior atualizados. Sincronizado no GitHub!', 'success');
  } else if (!ReportProgressBar.isActive) {
    showToast('Report carregado com sucesso!!', 'success');
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
  try { ReportProgressBar?.notifyPartDone?.('mensal'); } catch (_) {}
}

// ── Tabela Acumulada / Mensal da Margem (Margem de Contribuição e MARGEM) ──
function setModoTabelaTopo(modo) {
  state.modoTabelaTopo = modo;
  carregarTabelaAcumulado();
}
window.setModoTabelaTopo = setModoTabelaTopo;

async function carregarTabelaAcumulado() {
  const tbody = document.getElementById('tabelaAcumuladoBody');
  if (tbody) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading-row"><div class="spinner"></div> Atualizando demonstrativo…</td></tr>';
  }
  try {
    const p = new URLSearchParams({
      ano: getAnoParam(),
      mes: getMesParam(),
      emp: getEmpParam(),
      cenc: getCencParam(),
      modo: state.modoTabelaTopo || 'mensal',
    });
    const res = await fetch('/api/dre/tabela-acumulado?' + p);
    const data = await res.json();
    state.tabelaAcumuladoData = data;
    renderizarTabelaAcumulado(data);
  } catch (e) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" class="loading-row" style="color:var(--danger)">⚠ Erro ao carregar demonstrativo: ${e.message}</td></tr>`;
    }
  } finally {
    try { ReportProgressBar?.notifyPartDone?.('acumulado'); } catch (_) {}
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
  if (v == null || isNaN(v)) return '—';
  const n = Number(v);
  if (Math.abs(n) > 999) return '—'; // Proteção contra bases irrisórias
  return n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%';
}

function renderizarTabelaAcumulado(data) {
  const tbody = document.getElementById('tabelaAcumuladoBody');
  if (!tbody) return;
  if (!data || !data.margem) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading-row">Nenhum dado disponível.</td></tr>';
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
      <td class="col-pct"><strong style="color:#94a3b8;">${fmtPct(mc.pct_orc)}</strong></td>
      <td class="col-pct"><strong style="color:#94a3b8;">${fmtPct(mc.pct_real)}</strong></td>
      <td class="col-num ${mcDifClass}"><strong>${fmtAcumDec(mc.dif)}</strong></td>
      <td class="col-ro ${mcDifClass}"><strong>${fmtRO(mc.pct)}</strong></td>
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
      <td class="col-pct"><strong style="color:#94a3b8;">${fmtPct(margem.pct_orc)}</strong></td>
      <td class="col-pct"><strong style="color:#94a3b8;">${fmtPct(margem.pct_real)}</strong></td>
      <td class="col-num ${margemDifClass}"><strong>${fmtAcumDec(margem.dif)}</strong></td>
      <td class="col-ro ${margemDifClass}"><strong>${fmtRO(margem.pct)}</strong></td>
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
      const bDifClass = (b.dif || 0) >= 0 ? 'val-pos' : 'val-neg';

      html += `
        <tr class="row-bloco row-desvio" onclick="toggleBlocoAcumulado('${bKey.replace(/'/g, "\\'")}')" title="Clique para expandir títulos">
          <td class="col-desvio-bloco" style="padding-left: 24px;">
            <span class="exp-icon">${blocoIcon}</span>
            <span style="color:#ffffff;">${b.bloco}</span>
          </td>
          <td class="col-num">${fmtAcumInt(b.orcado)}</td>
          <td class="col-num">${fmtAcumInt(b.realizado)}</td>
          <td class="col-pct" style="color:#94a3b8;">${fmtPct(b.pct_orc)}</td>
          <td class="col-pct" style="color:#94a3b8;">${fmtPct(b.pct_real)}</td>
          <td class="col-num ${bDifClass}">${fmtAcumDec(b.dif)}</td>
          <td class="col-ro ${bDifClass}">${fmtRO(b.pct)}</td>
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
              <td class="col-pct" style="color:#94a3b8; opacity:0.85;">${fmtPct(t.pct_orc)}</td>
              <td class="col-pct" style="color:#94a3b8; opacity:0.85;">${fmtPct(t.pct_real)}</td>
              <td class="col-num ${tDifClass}">${fmtAcumDec(t.dif)}</td>
              <td class="col-ro ${tDifClass}" style="opacity:0.9;">${fmtRO(t.pct)}</td>
            </tr>
          `;
        });
      }
    });
  }

  tbody.innerHTML = html;

  // Atualiza título dinâmico com período
  const isMensal = (data.modo || state.modoTabelaTopo || 'mensal') === 'mensal';
  const tit = document.getElementById('tituloTabelaAcumulado');
  const NOMES_MES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  const MES_ABREV = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  const mNum = Number(data.mes || state.mes || 9);
  const mNome = NOMES_MES[mNum - 1] || 'Setembro';
  const mAbrev = MES_ABREV[mNum - 1] || 'Set';

  const btnM = document.getElementById('btnModoMensalTopo');
  const btnA = document.getElementById('btnModoAcumTopo');
  if (btnM && btnA) {
    btnM.textContent = `MÊS (${mAbrev.toUpperCase()})`;
    btnA.textContent = `ACUMULADO (JAN–${mAbrev.toUpperCase()})`;
    if (isMensal) {
      btnM.style.background = 'var(--brand-secondary-dourado)';
      btnM.style.color = '#000';
      btnA.style.background = 'transparent';
      btnA.style.color = '#9ca3af';
    } else {
      btnA.style.background = 'var(--brand-secondary-dourado)';
      btnA.style.color = '#000';
      btnM.style.background = 'transparent';
      btnM.style.color = '#9ca3af';
    }
  }

  if (tit) {
    tit.textContent = isMensal 
      ? `Detalhe da Margem — Mensal (${mNome})`
      : `Detalhe da Margem — Acumulado até ${mNome} (Jan–${mAbrev})`;
  }

  const sub = document.getElementById('subtituloTabelaAcumulado');
  if (sub) {
    sub.textContent = isMensal
      ? `Demonstrativo contábil mensal oficial (100% alinhado com Power BI e Qlik)`
      : `Valores acumulados de Janeiro até ${mNome} de ${data.ano || 2026}`;
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
  const card = document.getElementById('cardAcumulado');
  const iconFs = document.getElementById('iconFullscreenAcumulado');

  if (btn) {
    btn.textContent = state.acumuladoExpandAll ? 'RECOLHER TUDO' : 'EXPANDIR TUDO';
  }

  // Quando clicar em expandir, deixar em tela cheia (grid-column: 1 / -1)
  if (state.acumuladoExpandAll) {
    if (card) card.classList.add('fullscreen-mode');
    if (iconFs) iconFs.textContent = 'close_fullscreen';
    if (state.tabelaAcumuladoData && state.tabelaAcumuladoData.margem) {
      (state.tabelaAcumuladoData.margem.blocos || []).forEach(b => state.blocosAcumuladoAbertos.add(b.bloco));
      state.margemAcumuladaAberta = true;
    }
  } else {
    if (card) card.classList.remove('fullscreen-mode');
    if (iconFs) iconFs.textContent = 'open_in_full';
    state.blocosAcumuladoAbertos.clear();
  }

  if (state.tabelaAcumuladoData) renderizarTabelaAcumulado(state.tabelaAcumuladoData);
}

function toggleFullscreenAcumulado() {
  const card = document.getElementById('cardAcumulado');
  const iconFs = document.getElementById('iconFullscreenAcumulado');
  if (!card) return;
  const isFs = card.classList.toggle('fullscreen-mode');
  if (iconFs) iconFs.textContent = isFs ? 'close_fullscreen' : 'open_in_full';
}
window.toggleFullscreenAcumulado = toggleFullscreenAcumulado;

// ── Tabela Mensal (Orçado & Realizado — Sem Centros de Custo, Apenas Itens com Movimento) ──
async function carregarTabelaMensal() {
  const tbody = document.getElementById('tabelaMensalOrcRealBody');
  if (tbody) {
    tbody.innerHTML = '<tr><td colspan="5" class="loading-row"><div class="spinner"></div> Carregando visão do mês…</td></tr>';
  }
  try {
    const p = new URLSearchParams({
      ano: getAnoParam(),
      mes: getMesParam(),
      emp: getEmpParam(),
      cenc: getCencParam(),
      so_ambos: 'true',
    });
    const res = await fetch('/api/dre/tabela-mensal?' + p);
    const data = await res.json();
    state.tabelaMensalData = data;
    renderizarTabelaMensalOrcReal(data);
  } catch (e) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="5" class="loading-row" style="color:var(--danger)">⚠ Erro ao carregar visão do mês: ${e.message}</td></tr>`;
    }
  }
}

function fmtDesvioPct(v) {
  if (v == null || isNaN(v)) return '0,00%';
  const n = Number(v);
  const sign = n > 0 ? '+' : '';
  return sign + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%';
}

function renderizarTabelaMensalOrcReal(data) {
  const tbody = document.getElementById('tabelaMensalOrcRealBody');
  if (!tbody) return;
  if (!data || !data.centros || data.centros.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="loading-row">Nenhum centro de resultado com orçado e realizado encontrado.</td></tr>';
    return;
  }

  const tot = data.total || {};
  const centros = data.centros ? [...data.centros] : [];

  // Ordenação configurável por coluna (padrão: maior para o menor)
  const col = state.mensalSortCol || 'realizado';
  const asc = state.mensalSortAsc === true; // false = maior para o menor (DESC)

  centros.sort((a, b) => {
    let vA = a[col];
    let vB = b[col];
    if (col === 'nome') {
      const sA = String(vA || '').toLowerCase();
      const sB = String(vB || '').toLowerCase();
      return asc ? sA.localeCompare(sB, 'pt-BR') : sB.localeCompare(sA, 'pt-BR');
    }
    const nA = vA != null ? Number(vA) : (asc ? Infinity : -Infinity);
    const nB = vB != null ? Number(vB) : (asc ? Infinity : -Infinity);
    return asc ? nA - nB : nB - nA;
  });

  // Atualiza indicadores visuais no cabeçalho
  ['nome', 'orcado', 'realizado', 'dif', 'pct'].forEach(c => {
    const el = document.getElementById('sort-mensal-' + c);
    if (el) {
      if (c === col) {
        el.textContent = asc ? ' ▲' : ' ▼';
        el.style.color = 'var(--gold)';
        el.style.fontWeight = 'bold';
      } else {
        el.textContent = ' ⇅';
        el.style.color = '';
        el.style.fontWeight = '';
      }
    }
  });

  let html = '';

  // 1. Linha Total Consolidado dos Centros de Resultados
  // LÓGICA DE CONTROLADORIA:
  // Se dif >= 0: o resultado superou o orçado -> VERDE (val-pos)
  // Se dif < 0: o resultado ficou abaixo do orçado -> VERMELHO (val-neg)
  const totClass = (tot.dif || 0) >= 0 ? 'val-pos' : 'val-neg';

  html += `
    <tr class="row-total-mc row-desvio">
      <td class="col-desvio-bloco">
        <span class="exp-icon" style="visibility:hidden;">−</span>
        <strong style="color:#ffffff;">${tot.nome || 'TOTAL CENTROS DE RESULTADO'}</strong>
      </td>
      <td class="col-num"><strong style="color:#ffffff;">${fmtAcumInt(tot.orcado)}</strong></td>
      <td class="col-num"><strong style="color:#ffffff;">${fmtAcumInt(tot.realizado)}</strong></td>
      <td class="col-num ${totClass}"><strong>${fmtAcumDec(tot.dif)}</strong></td>
      <td class="col-ro ${totClass}"><strong>${fmtDesvioPct(tot.pct)}</strong></td>
    </tr>
  `;

  // 2. Linhas de cada Centro de Resultado
  centros.forEach((c) => {
    const cNome = c.nome || 'Sem Nome';
    const hasBlocos = c.blocos && c.blocos.length > 0;
    const isAberto = state.mensalExpandAll || state.centrosMensalAbertos.has(cNome);
    const expIcon = hasBlocos ? (isAberto ? '−' : '+') : '';

    // REGRA DE CONTROLADORIA:
    // Para canais comerciais: dif >= 0 superou a meta de margem (VERDE); dif < 0 abaixo da meta (VERMELHO)
    // Para centros de custo: dif >= 0 economizou despesa (VERDE); dif < 0 estourou o orçamento de gastos (VERMELHO)
    const cClass = (c.dif || 0) >= 0 ? 'val-pos' : 'val-neg';

    html += `
      <tr class="row-bloco row-desvio" onclick="toggleCentroMensal('${cNome.replace(/'/g, "\\'")}')" style="cursor: pointer;" title="Clique para expandir/recolher os blocos deste centro de resultado">
        <td class="col-desvio-bloco" style="padding-left: 18px;">
          <span class="exp-icon">${expIcon}</span>
          <strong style="color:var(--gold);">${cNome}</strong>
        </td>
        <td class="col-num"><strong style="color:#ffffff;">${fmtAcumInt(c.orcado)}</strong></td>
        <td class="col-num"><strong style="color:#ffffff;">${fmtAcumInt(c.realizado)}</strong></td>
        <td class="col-num ${cClass}"><strong>${fmtAcumDec(c.dif)}</strong></td>
        <td class="col-ro ${cClass}"><strong>${fmtDesvioPct(c.pct)}</strong></td>
      </tr>
    `;

    // 3. Filhos do Centro de Resultado: Blocos da DRE
    if (isAberto && hasBlocos) {
      c.blocos.forEach(b => {
        // LÓGICA DE DRE:
        // Se for Custo/Despesa (valores contábeis negativos no DRE):
        //   gasto acima do orçado gera dif < 0 -> ESTOURO DE ORÇAMENTO -> VERMELHO (val-neg)
        //   gasto abaixo do orçado gera dif >= 0 -> ECONOMIA DE ORÇAMENTO -> VERDE (val-pos)
        // Se for Receita/Venda (valores positivos):
        //   venda acima do orçado gera dif >= 0 -> META SUPERADA -> VERDE (val-pos)
        //   venda abaixo do orçado gera dif < 0 -> META NÃO ATINGIDA -> VERMELHO (val-neg)
        const bClass = (b.dif || 0) >= 0 ? 'val-pos' : 'val-neg';

        html += `
          <tr class="row-titulo row-desvio">
            <td class="col-desvio-tit" style="padding-left: 48px;">
              <span style="display:inline-block; width:8px; height:1px; background:rgba(203, 151, 39, 0.6); margin-right:8px; vertical-align:middle;"></span>
              <span style="color:#e2e8f0;">${b.bloco}</span>
            </td>
            <td class="col-num" style="opacity:0.9;">${fmtAcumInt(b.orcado)}</td>
            <td class="col-num" style="opacity:0.9;">${fmtAcumInt(b.realizado)}</td>
            <td class="col-num ${bClass}">${fmtAcumDec(b.dif)}</td>
            <td class="col-ro ${bClass}">${fmtDesvioPct(b.pct)}</td>
          </tr>
        `;
      });
    }
  });

  tbody.innerHTML = html;

  // Atualiza título dinâmico com período mensal
  const tit = document.getElementById('tituloTabelaMensalOrcReal');
  const NOMES_MES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  const mNum = Number(data.mes || state.mes || 9);
  const mNome = NOMES_MES[mNum - 1] || 'Setembro';
  if (tit) {
    tit.textContent = `Centros de Resultados — Mês de ${mNome}`;
  }

  const sub = document.getElementById('subtituloTabelaMensalOrcReal');
  if (sub) {
    sub.textContent = `Centros com Orçado e Realizado em ${mNome} de ${data.ano || 2026}`;
  }
}

window.ordenarTabelaMensal = function(col) {
  if (state.mensalSortCol === col) {
    state.mensalSortAsc = !state.mensalSortAsc;
  } else {
    state.mensalSortCol = col;
    state.mensalSortAsc = false; // Primeiro clique na coluna: SEMPRE do maior para o menor!
  }
  if (state.tabelaMensalData) {
    renderizarTabelaMensalOrcReal(state.tabelaMensalData);
  }
};

function toggleCentroMensal(cNome) {
  if (state.centrosMensalAbertos.has(cNome)) {
    state.centrosMensalAbertos.delete(cNome);
  } else {
    state.centrosMensalAbertos.add(cNome);
  }
  if (state.tabelaMensalData) renderizarTabelaMensalOrcReal(state.tabelaMensalData);
}

function toggleExpandAllMensal() {
  state.mensalExpandAll = !state.mensalExpandAll;
  const btn = document.getElementById('btnToggleExpandMensal');
  const card = document.getElementById('cardMensalOrcReal');
  const iconFs = document.getElementById('iconFullscreenMensal');

  if (btn) {
    btn.textContent = state.mensalExpandAll ? 'RECOLHER TUDO' : 'EXPANDIR TUDO';
  }

  if (state.mensalExpandAll) {
    if (card) card.classList.add('fullscreen-mode');
    if (iconFs) iconFs.textContent = 'close_fullscreen';
    if (state.tabelaMensalData && state.tabelaMensalData.centros) {
      state.tabelaMensalData.centros.forEach(c => state.centrosMensalAbertos.add(c.nome));
    }
  } else {
    if (card) card.classList.remove('fullscreen-mode');
    if (iconFs) iconFs.textContent = 'open_in_full';
    state.centrosMensalAbertos.clear();
  }

  if (state.tabelaMensalData) renderizarTabelaMensalOrcReal(state.tabelaMensalData);
}

function toggleFullscreenMensal() {
  const card = document.getElementById('cardMensalOrcReal');
  const iconFs = document.getElementById('iconFullscreenMensal');
  if (!card) return;
  const isFs = card.classList.toggle('fullscreen-mode');
  if (iconFs) iconFs.textContent = isFs ? 'close_fullscreen' : 'open_in_full';
}

window.toggleExpandAllMensal = toggleExpandAllMensal;
window.toggleFullscreenMensal = toggleFullscreenMensal;
window.toggleCentroMensal = toggleCentroMensal;


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
          <td class="col-var ${evolClass(bloco.mom, bloco.is_despesa)}">${fmtEvol(bloco.mom)}</td>
          <td class="col-var ${evolClass(bloco.yoy, bloco.is_despesa)}">${fmtEvol(bloco.yoy)}</td>
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
        <td class="col-var ${evolClass(bloco.mom, bloco.is_despesa)}">${fmtEvol(bloco.mom)}</td>
        <td class="col-var ${evolClass(bloco.yoy, bloco.is_despesa)}">${fmtEvol(bloco.yoy)}</td>
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
          <td class="col-var ${evolClass(titulo.mom, titulo.is_despesa)}">${fmtEvol(titulo.mom)}</td>
          <td class="col-var ${evolClass(titulo.yoy, titulo.is_despesa)}">${fmtEvol(titulo.yoy)}</td>
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
            <td class="col-var ${evolClass(ln.mom, ln.is_despesa)}">${fmtEvol(ln.mom)}</td>
            <td class="col-var ${evolClass(ln.yoy, ln.is_despesa)}">${fmtEvol(ln.yoy)}</td>
            <td class="col-ro ${roClass(ln.ro)}">${fmtRO(ln.ro)}</td>
          </tr>`);
      });
    });
  });

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="loading-row" style="color:var(--text-muted)">
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
  document.querySelectorAll('.metric-kpi-card, .kpi-card').forEach(c => c.classList.remove('kpi-active'));
  cardEl.classList.add('kpi-active');

  const dre = state.dre || [];
  const allTitulos = dre.flatMap(b => b.titulos || []);

  if (key === 'vl') {
    const vl = dre.find(b => (b.bloco || '').toLowerCase().includes('venda liquida'));
    if (vl) carregarGraficoLinha({ tipo: 'bloco', nome: vl.bloco || '1.Venda Liquida', bloco: vl.bloco || '1.Venda Liquida' });
  } else if (key === 'vb') {
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

// ── Atualização dos KPI Cards com Métricas e Mês Anterior ─────────────
function atualizarKPIs() {
  const dre = state.dre;
  if (!dre || dre.length === 0) return;

  const allTitulos = dre.flatMap(b => b.titulos || []);

  // 0. Venda Líquida
  const vl = dre.find(b => (b.bloco || '').toLowerCase().includes('venda liquida')) || {};
  const elVLVal = document.getElementById('kpiVLVal');
  const elVLSub = document.getElementById('kpiVLSub');
  if (elVLVal) elVLVal.textContent = fmtBRL(vl.realizado);
  if (elVLSub) elVLSub.innerHTML = renderKpiSub(vl.orcado, vl.ro, vl.mom, vl.yoy, vl.ytd_yoy, vl.pct_orc, vl.pct_real, false);

  // 1. Venda Bruta
  const vb = allTitulos.find(t => t.titulo?.toLowerCase().includes('venda bruta')) || {};
  const elVBVal = document.getElementById('kpiVBVal');
  const elVBSub = document.getElementById('kpiVBSub');
  if (elVBVal) elVBVal.textContent = fmtBRL(vb.realizado);
  if (elVBSub) elVBSub.innerHTML = renderKpiSub(vb.orcado, vb.ro, vb.mom, vb.yoy, vb.ytd_yoy, vb.pct_orc, vb.pct_real, false);

  // 2. Margem de Contribuição
  const margem = dre.find(b => b.is_total) || {};
  const elMVal = document.getElementById('kpiMargemVal');
  const elMSub = document.getElementById('kpiMargemSub');
  if (elMVal) elMVal.textContent = fmtBRL(margem.realizado);
  if (elMSub) elMSub.innerHTML = renderKpiSub(margem.orcado, margem.ro, margem.mom, margem.yoy, margem.ytd_yoy, margem.pct_orc, margem.pct_real, false);

  // 3. Bonificação (Bonificação Clientes)
  const bonif = allTitulos.find(t => {
    const s = (t.titulo || '').toLowerCase();
    return s.includes('bonifica') && s.includes('client');
  }) || allTitulos.find(t => (t.titulo || '').toLowerCase().includes('bonifica')) || {};
  const elBVal = document.getElementById('kpiBonifVal');
  const elBSub = document.getElementById('kpiBonifSub');
  if (elBVal) elBVal.textContent = fmtBRL(bonif.realizado);
  if (elBSub) elBSub.innerHTML = renderKpiSub(bonif.orcado, bonif.ro, bonif.mom, bonif.yoy, bonif.ytd_yoy, bonif.pct_orc, bonif.pct_real, true);

  // 4. Comissão (Comissões)
  const despVendas = dre.find(b => (b.bloco || '').toLowerCase().includes('despesas com vendas')) || {};
  const comissao = (despVendas.titulos || []).find(t => (t.titulo || '').toLowerCase().includes('comiss'))
                || allTitulos.find(t => (t.titulo || '').toLowerCase().includes('comiss')) || {};
  const elCVal = document.getElementById('kpiComissaoVal');
  const elCSub = document.getElementById('kpiComissaoSub');
  if (elCVal) elCVal.textContent = fmtBRL(comissao.realizado);
  if (elCSub) elCSub.innerHTML = renderKpiSub(comissao.orcado, comissao.ro, comissao.mom, comissao.yoy, comissao.ytd_yoy, comissao.pct_orc, comissao.pct_real, true);

  // 5. Guelta
  const guelta = allTitulos.find(t => (t.titulo || '').toLowerCase().includes('guelta')) || {};
  const elGVal = document.getElementById('kpiGueltaVal');
  const elGSub = document.getElementById('kpiGueltaSub');
  if (elGVal) elGVal.textContent = fmtBRL(guelta.realizado);
  if (elGSub) elGSub.innerHTML = renderKpiSub(guelta.orcado, guelta.ro, guelta.mom, guelta.yoy, guelta.ytd_yoy, guelta.pct_orc, guelta.pct_real, true);

  // 6. Despesa Comercial Operacional
  const despCom = dre.find(b => (b.bloco || '').toLowerCase().includes('comercial operacional')) || {};
  const elDVal = document.getElementById('kpiDespComercialVal');
  const elDSub = document.getElementById('kpiDespComercialSub');
  if (elDVal) elDVal.textContent = fmtBRL(despCom.realizado);
  if (elDSub) elDSub.innerHTML = renderKpiSub(despCom.orcado, despCom.ro, despCom.mom, despCom.yoy, despCom.ytd_yoy, despCom.pct_orc, despCom.pct_real, true);

  // 7. Folha de Pagamento e Benefícios
  const folha = allTitulos.find(t => (t.titulo || '').toLowerCase().includes('folha') && !(t.titulo || '').toLowerCase().includes('comercial'))
             || allTitulos.find(t => (t.titulo || '').toLowerCase().includes('folha')) || {};
  const elFVal = document.getElementById('kpiFolhaVal');
  const elFSub = document.getElementById('kpiFolhaSub');
  if (elFVal) elFVal.textContent = fmtBRL(folha.realizado);
  if (elFSub) elFSub.innerHTML = renderKpiSub(folha.orcado, folha.ro, folha.mom, folha.yoy, folha.ytd_yoy, folha.pct_orc, folha.pct_real, true);

  // Variantes semânticas dos cards conforme valores orçados vs realizados:
  // Para despesas: se orçado >= realizado, positivo (economia); se realizado > orçado, negativo (estouro).
  // Para receitas/margem: se realizado >= orçado, positivo (meta superada); se realizado < orçado, negativo.
  applyKpiVariant('kpiVL', false, vl.realizado, vl.orcado);
  applyKpiVariant('kpiVB', false, vb.realizado, vb.orcado);
  applyKpiVariant('kpiMargem', false, margem.realizado, margem.orcado);
  applyKpiVariant('kpiBonif', true, bonif.realizado, bonif.orcado);
  applyKpiVariant('kpiComissao', true, comissao.realizado, comissao.orcado);
  applyKpiVariant('kpiGuelta', true, guelta.realizado, guelta.orcado);
  applyKpiVariant('kpiDespComercial', true, despCom.realizado, despCom.orcado);
  applyKpiVariant('kpiFolha', true, folha.realizado, folha.orcado);
}

function applyKpiVariant(cardId, isDespesa, realizado, orcado) {
  const cardEl = document.getElementById(cardId);
  if (!cardEl) return;
  cardEl.classList.remove('variant-positivo', 'variant-negativo', 'variant-neutro');
  if (orcado == null || isNaN(Number(orcado)) || Number(orcado) === 0) {
    cardEl.classList.add('variant-neutro');
    return;
  }
  const r = Number(realizado) || 0;
  const o = Number(orcado) || 0;
  if (isDespesa) {
    if (Math.abs(r) <= Math.abs(o)) {
      cardEl.classList.add('variant-positivo');
    } else {
      cardEl.classList.add('variant-negativo');
    }
  } else {
    if (r >= o) {
      cardEl.classList.add('variant-positivo');
    } else {
      cardEl.classList.add('variant-negativo');
    }
  }
}

// ── Alternância de Modos da Tabela DRE e Busca Instantânea ─────────────────
function setDRETableMode(mode) {
  const btnDev = document.getElementById('btn-mode-deviations');
  const btnTree = document.getElementById('btn-mode-tree');
  const cardDev = document.getElementById('cardDesvios');
  const cardTree = document.getElementById('dreTableWrapper');
  const mainHeading = document.getElementById('dreMainHeading');
  const subHeading = document.getElementById('dreSubHeading');
  
  if (mode === 'deviations') {
    if (btnDev) btnDev.classList.add('active');
    if (btnTree) btnTree.classList.remove('active');
    if (cardDev) cardDev.style.display = 'block';
    if (cardTree) cardTree.style.display = 'none';
    if (mainHeading) mainHeading.textContent = 'Quadro de Desvios Executivos (|R/O| ≥ 10%)';
    if (subHeading) subHeading.textContent = 'Títulos com desvio orçamentário igual ou superior a 10% no período';
  } else {
    if (btnDev) btnDev.classList.remove('active');
    if (btnTree) btnTree.classList.add('active');
    if (cardDev) cardDev.style.display = 'none';
    if (cardTree) cardTree.style.display = 'block';
    if (mainHeading) mainHeading.textContent = 'Demonstrativo de Resultado & Desvios';
    if (subHeading) subHeading.textContent = 'Visão contábil detalhada por Bloco, Título e Centro de Custo';
  }
}

function filterDRETable(query) {
  query = (query || '').toLowerCase().trim();
  const rows = document.querySelectorAll('#dreBody tr');
  rows.forEach(tr => {
    if (!query) {
      tr.style.display = '';
      return;
    }
    const text = tr.textContent.toLowerCase();
    tr.style.display = text.includes(query) ? '' : 'none';
  });
}

function setAcumuladoMode(mode) {
  const tableWrap = document.getElementById('wrapTabelaAcumuladoSwitch');
  const chartWrap = document.getElementById('chartAcumuladoContainer');
  const btnChart = document.getElementById('btn-view-acum-chart');
  const btnTable = document.getElementById('btn-view-acum-table');
  if (mode === 'table') {
    if (tableWrap) tableWrap.style.display = 'block';
    if (chartWrap) chartWrap.style.display = 'none';
    if (btnTable) btnTable.classList.add('active');
    if (btnChart) btnChart.classList.remove('active');
  } else {
    if (tableWrap) tableWrap.style.display = 'none';
    if (chartWrap) chartWrap.style.display = 'block';
    if (btnTable) btnTable.classList.remove('active');
    if (btnChart) btnChart.classList.add('active');
  }
}

function setMensalMode(mode) {
  const tableWrap = document.getElementById('wrapTabelaMensalSwitch');
  const chartWrap = document.getElementById('chartMensalContainer');
  const btnChart = document.getElementById('btn-view-mom-chart');
  const btnTable = document.getElementById('btn-view-mom-table');
  if (mode === 'table') {
    if (tableWrap) tableWrap.style.display = 'block';
    if (chartWrap) chartWrap.style.display = 'none';
    if (btnTable) btnTable.classList.add('active');
    if (btnChart) btnChart.classList.remove('active');
    renderizarTabelaMensal(state.mensalData);
  } else {
    if (tableWrap) tableWrap.style.display = 'none';
    if (chartWrap) chartWrap.style.display = 'block';
    if (btnTable) btnTable.classList.remove('active');
    if (btnChart) btnChart.classList.add('active');
  }
}

function renderizarTabelaMensal(mensalData) {
  const tbody = document.getElementById('momTableBody');
  if (!tbody || !mensalData || !mensalData.length) return;
  tbody.innerHTML = mensalData.map(m => {
    const ating = m.orcado > 0 ? ((m.realizado / m.orcado) * 100).toFixed(1) + '%' : '—';
    const diff = (m.realizado || 0) - (m.orcado || 0);
    return `<tr>
      <td style="font-weight: 700; color: #fff;">${m.mes_nome || m.mes}</td>
      <td class="col-num">${fmtBRL(m.realizado)}</td>
      <td class="col-num">${fmtBRL(m.orcado)}</td>
      <td class="col-num ${diff < 0 ? 'val-neg' : 'val-pos'}">${fmtBRL(diff)}</td>
      <td class="col-num">${ating}</td>
    </tr>`;
  }).join('');
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
    const m = Number(r.mes ?? r.MES);
    if (!m) return;
    if (!porMes[m]) porMes[m] = { real: 0, orc: 0 };
    porMes[m].real += Number(r.realizado ?? r.REALIZADO ?? 0);
    porMes[m].orc  += Number(r.orcado ?? r.ORCADO ?? 0);
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
    const m = Number(r.mes ?? r.MES);
    if (!m) return;
    if (!porMes[m]) porMes[m] = { real: 0, orc: 0 };
    porMes[m].real += Number(r.realizado ?? r.REALIZADO ?? 0);
    porMes[m].orc  += Number(r.orcado ?? r.ORCADO ?? 0);
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

// ── Próxima atualização: contagem regressiva até a carga diária do ETL ───
const ETL_HORA_CARGA = 21; // agendamento diário (21:00) — manter igual a DRE_SYNC_HORA no app.py/.env
let contadorProximaCarga = null;

function proximaCargaETL() {
  const agora = new Date();
  const alvo = new Date(agora);
  alvo.setHours(ETL_HORA_CARGA, 0, 0, 0);
  if (alvo <= agora) alvo.setDate(alvo.getDate() + 1);
  return alvo;
}

function renderProximaCarga() {
  const el = document.getElementById('nextUpdate');
  if (!el) return;
  const seg = Math.max(0, Math.floor((proximaCargaETL() - new Date()) / 1000));
  const h = String(Math.floor(seg / 3600)).padStart(2, '0');
  const m = String(Math.floor((seg % 3600) / 60)).padStart(2, '0');
  const s = String(seg % 60).padStart(2, '0');
  el.textContent = `Próxima atualização em: ${h}:${m}:${s}`;
}

function iniciarContadorProximaCarga() {
  if (contadorProximaCarga) return;
  renderProximaCarga();
  contadorProximaCarga = setInterval(renderProximaCarga, 1000);
}

// Busca no backend a data da última sincronização com o Oracle (data_sync_status.json)
async function carregarUltimaSincronizacao() {
  try {
    const res = await fetch('/api/dre/ultima-sincronizacao');
    const data = await res.json();
    atualizarTimestamp(data.ultima_sincronizacao);
  } catch (err) {
    console.warn('Erro ao buscar data da última sincronização:', err);
    atualizarTimestamp(null);
  }
}

function atualizarTimestamp(dataRef = null) {
  const el = document.getElementById('lastUpdate');
  if (!el) return;
  iniciarContadorProximaCarga();
  // "2026-10-14 21:00:05" → "2026-10-14T21:00:05" (horário local, aceito por todos os navegadores)
  const ts = dataRef ? new Date(String(dataRef).replace(' ', 'T')) : null;
  if (!ts || isNaN(ts)) {
    el.textContent = 'Última atualização: --/--/---- --:--:--';
    return;
  }
  state.dadosAtualizadosEm = ts.toISOString();
  el.textContent = 'Última atualização: ' + ts.toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  });
}

// ── Export CSV ───────────────────────────────────────────────────────────
function exportarCSV() {
  if (!state.dre?.length) { showToast('Sem dados para exportar', 'error'); return; }
  const linhas = [['Bloco','Título','Descrição','Orçado (R$)','Realizado (R$)','MoM','YoY','% VB Orç.','% VB Real.','R/O']];
  state.dre.forEach(bloco => {
    if (bloco.is_total) {
      linhas.push([bloco.bloco,'','',bloco.orcado,bloco.realizado,bloco.mom,bloco.yoy,bloco.pct_orc,bloco.pct_real,bloco.ro]);
    } else {
      linhas.push([bloco.bloco,'Subtotal','',bloco.orcado,bloco.realizado,bloco.mom,bloco.yoy,bloco.pct_orc,bloco.pct_real,bloco.ro]);
      (bloco.titulos||[]).forEach(t => {
        linhas.push([bloco.bloco,t.titulo,'',t.orcado,t.realizado,t.mom,t.yoy,t.pct_orc,t.pct_real,t.ro]);
        (t.linhas||[]).forEach(ln => {
          linhas.push([bloco.bloco,t.titulo,ln.descr,ln.orcado,ln.realizado,ln.mom,ln.yoy,ln.pct_orc,ln.pct_real,ln.ro]);
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

// ── Exportar para Excel (.xlsx) no Modelo Oficial Analítico Hierárquico ──
function exportarParaExcel(e) {
  if (e && e.preventDefault) e.preventDefault();
  try {
    const p = new URLSearchParams({
      ano: getAnoParam(),
      mes: getMesParam(),
      emp: getEmpParam(),
      cenc: getCencParam(),
    });

    showToast('Gerando DRE em Excel no modelo analítico...', 'info');
    const url = '/api/dre/exportar-excel?' + p.toString();
    const a = document.createElement('a');
    a.href = url;
    a.setAttribute('download', `DRE_MQ_EMPRESA_${getAnoParam()}_M${getMesParam()}.xlsx`);
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      if (a.parentNode) a.parentNode.removeChild(a);
    }, 1000);
  } catch (err) {
    console.error('Erro ao exportar Excel:', err);
    window.location.href = '/api/dre/exportar-excel?' + new URLSearchParams({
      ano: getAnoParam(),
      mes: getMesParam(),
      emp: getEmpParam(),
      cenc: getCencParam(),
    }).toString();
  }
}
window.exportarParaExcel = exportarParaExcel;
window.toggleExpandAll = toggleExpandAll;
window.toggleExpandAllAcumulado = toggleExpandAllAcumulado;
window.toggleFullscreenAcumulado = toggleFullscreenAcumulado;


// ════ AGENTE DE IA (NATIVO GEMINI / WEBHOOK OPCIONAL) ═════════════════════════
const DEFAULT_WEBHOOK = '/api/ia/perguntar';
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

  // ── Saudação Dinâmica com base no Horário e Usuário da Intranet ──
  function obterSaudacaoPeriodo() {
    const hora = new Date().getHours();
    if (hora >= 5 && hora < 12) return 'Bom dia';
    if (hora >= 12 && hora < 18) return 'Boa tarde';
    return 'Boa noite';
  }

  function formatarNomeUsuario(rawName) {
    if (!rawName) return '';
    let name = String(rawName).trim();
    if (name.includes('@')) name = name.split('@')[0];
    if (name.includes('.')) name = name.replace(/\./g, ' ');
    const parts = name.split(/\s+/).map(p => {
      const lower = p.toLowerCase();
      if (['da', 'de', 'do', 'das', 'dos', 'e'].includes(lower)) return lower;
      return p.charAt(0).toUpperCase() + p.slice(1).toLowerCase();
    });
    const fullName = parts.join(' ');
    const lowerName = fullName.toLowerCase();
    if (lowerName.includes('vagner')) return 'Vagner';
    if (lowerName.includes('pinhata')) return 'Rodrigo Pinhata';
    if (lowerName.includes('nobrega')) return 'Rodrigo Nobrega';
    if (lowerName.includes('iara')) return 'Iara Teixeira';
    if (lowerName.includes('antonio') || lowerName.includes('mello') || lowerName === 'admin' || lowerName.includes('administrador') || lowerName.includes('amello')) return 'Antônio';
    return fullName;
  }

  function obterCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return decodeURIComponent(parts.pop().split(';').shift());
    return null;
  }

  function obterNomeUsuario() {
    // 1. URL Param
    const params = new URLSearchParams(window.location.search);
    const uUrl = params.get('user') || params.get('usuario') || params.get('nome');
    if (uUrl) {
      const formatted = formatarNomeUsuario(uUrl);
      try { localStorage.setItem('mq_user_name', formatted); } catch (e) {}
      return formatted;
    }
    // 2. LocalStorage compartilhado
    try {
      const uStorage = localStorage.getItem('mq_user_name') || localStorage.getItem('usuario_intranet_nome') || localStorage.getItem('usuario_nome') || localStorage.getItem('user_name');
      if (uStorage) {
        return formatarNomeUsuario(uStorage);
      }
    } catch (e) {}
    // 3. Cookie compartilhado da Intranet
    const cUser = obterCookie('mq_user_name') || obterCookie('mq_user');
    if (cUser) {
      return formatarNomeUsuario(cUser);
    }
    // 4. Fallback para ambiente local (localhost ou 127.0.0.1)
    const host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1') {
      return 'Antônio';
    }
    return '';
  }

  function atualizarMensagemBoasVindas() {
    const nome = obterNomeUsuario();
    const periodo = obterSaudacaoPeriodo();
    const saudacao = nome ? `${periodo}, ${nome}!` : `${periodo}!`;
    
    const textoHtml = `
      <p style="margin: 0 0 8px 0; font-size: 14px;"><strong>${saudacao}</strong></p>
      <p style="margin: 0 0 8px 0;">Sou a <strong>MQIA</strong>.</p>
      <p style="margin: 0 0 8px 0;">Minha análise cruza dados e objetivos para trazer clareza às suas decisões.</p>
      <p style="margin: 0;">Estou pronta e à disposição para o diagnóstico de hoje. Por qual indicador começamos?</p>
    `;
    
    const msgInicial = body.querySelector('.ai-message.ai');
    if (msgInicial) {
      msgInicial.innerHTML = textoHtml;
    }
  }

  // Executa saudação inicial
  atualizarMensagemBoasVindas();

  // Ouve mensagens da Intranet via postMessage (caso o DRE esteja em um <iframe>)
  window.addEventListener('message', (event) => {
    if (event.data && (event.data.tipo === 'SET_USUARIO' || event.data.type === 'SET_USER')) {
      const nome = (event.data.nome || event.data.usuario || event.data.user || '').trim().split(' ')[0];
      if (nome) {
        localStorage.setItem('usuario_intranet_nome', nome);
        atualizarMensagemBoasVindas();
      }
    }
  });

  function toggleChat(forceOpen = null) {
    if (forceOpen === true) {
      widget.classList.remove('ai-chat-collapsed');
    } else if (forceOpen === false) {
      widget.classList.add('ai-chat-collapsed');
    } else {
      widget.classList.toggle('ai-chat-collapsed');
    }
    const isCollapsed = widget.classList.contains('ai-chat-collapsed');
    if (btnToggle) btnToggle.textContent = isCollapsed ? '↑' : '_';
    if (!isCollapsed && input) {
      setTimeout(() => input.focus(), 120);
    }
  }

  // Quando recolhido (avatar flutuante), clique no widget abre o chat imediatamente!
  widget.addEventListener('click', (e) => {
    if (widget.classList.contains('ai-chat-collapsed')) {
      toggleChat(true);
    }
  });

  if (btnToggle) {
    btnToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleChat();
    });
  }

  // Arrastar widget pelo cabeçalho
  let isDragging = false;
  let hasMoved = false;
  let startMouseX = 0;
  let startMouseY = 0;
  let initialX = 0;
  let initialY = 0;
  let currentX = 0;
  let currentY = 0;
  let xOffset = 0;
  let yOffset = 0;

  header.addEventListener('mousedown', (e) => {
    if (e.target.closest('#ai-chat-config') || e.target.closest('#ai-chat-toggle')) return;
    startMouseX = e.clientX;
    startMouseY = e.clientY;
    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;
    isDragging = true;
    hasMoved = false;
  });

  document.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    const diffX = Math.abs(e.clientX - startMouseX);
    const diffY = Math.abs(e.clientY - startMouseY);
    if (diffX > 4 || diffY > 4) {
      hasMoved = true;
      e.preventDefault();
      currentX = e.clientX - initialX;
      currentY = e.clientY - initialY;
      xOffset = currentX;
      yOffset = currentY;
      widget.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
    }
  });

  document.addEventListener('mouseup', (e) => {
    if (!isDragging) return;
    isDragging = false;
    // Se foi apenas clique (sem arrastar) no header, alterna o chat
    if (!hasMoved && !e.target.closest('#ai-chat-config') && !e.target.closest('#ai-chat-toggle')) {
      toggleChat();
    }
  });

  const btnConfig = document.getElementById('ai-chat-config');
  if(btnConfig) {
    btnConfig.addEventListener('click', (e) => {
      e.stopPropagation();
      let currentUrl = getWebhookUrl();
      let isDefault = currentUrl === DEFAULT_WEBHOOK;
      let newUrl = prompt(
        'Configuração do Agente de IA\n\n' +
        'Endpoint atual: ' + (isDefault ? 'Agente Nativo Interno (Mistral AI /api/ia/perguntar)' : currentUrl) +
        '\n\nPara usar um Webhook personalizado (ex: n8n), insira a URL.\nPara usar o Agente Nativo Mistral interno, deixe em branco:',
        isDefault ? '' : currentUrl
      );
      if(newUrl !== null) {
        if(newUrl.trim() === '') {
          localStorage.removeItem('n8n_webhook_url');
          alert('Configurado para o Agente Nativo Mistral interno!');
        } else {
          localStorage.setItem('n8n_webhook_url', newUrl.trim());
          alert('Endpoint personalizado configurado com sucesso!');
        }
      }
    });
  }
  
  function formatMarkdown(text) {
    if(!text) return '';
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/### (.*?)(?:\n|$)/g, '<h4 style="margin: 8px 0 4px; color: var(--gold); font-size: 13px;">$1</h4>')
      .replace(/## (.*?)(?:\n|$)/g, '<h3 style="margin: 10px 0 6px; color: var(--gold); font-size: 14px;">$1</h3>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/^\s*[\*•-]\s+(.*?)(?:\n|$)/gm, '<div style="padding-left: 10px; margin: 2px 0;">• $1</div>')
      .replace(/\n\n/g, '<div style="height: 6px;"></div>')
      .replace(/\n/g, '<br>');
    return html;
  }

  function renderContentWithCharts(containerEl, text) {
    const chartConfigs = [];
    const chartHtmlParts = [];
      // Extrai blocos ```chart ... ``` ou ```grafico ... ```
      let processedText = text.replace(/```(?:chart|grafico)\s*([\s\S]*?)\s*```/gi, (match, jsonStr) => {
        const chartId = 'ai-chart-' + Math.random().toString(36).substring(2, 9);
        try {
          let cleanJson = jsonStr.trim();
          // Remove comentários JS //... ou /* ... */
          cleanJson = cleanJson.replace(/\/\/.*$/gm, '');
          cleanJson = cleanJson.replace(/\/\*[\s\S]*?\*\//g, '');
          // Remove pontos de milhar em números para evitar erro de JSON (ex: 2.800.000 -> 2800000)
          cleanJson = cleanJson.replace(/(\d+)\.(\d{3})\.(\d{3})(?:\.(\d{3}))?/g, '$1$2$3$4');
          cleanJson = cleanJson.replace(/(\d+)\.(\d{3})(?=[,\s\]\}])/g, '$1$2');
          // Remove vírgulas residuais antes de fechar arrays ou objetos
          cleanJson = cleanJson.replace(/,\s*([}\]])/g, '$1');

          // Isola o objeto JSON caso haja texto residual antes/depois
          const firstBrace = cleanJson.indexOf('{');
          const lastBrace = cleanJson.lastIndexOf('}');
          if (firstBrace !== -1 && lastBrace !== -1 && lastBrace > firstBrace) {
            cleanJson = cleanJson.substring(firstBrace, lastBrace + 1);
          }
          
          let config = null;
          try {
            config = JSON.parse(cleanJson);
          } catch(e1) {
            try {
              const cleanSingle = cleanJson.replace(/'/g, '"').replace(/,\s*([}\]])/g, '$1');
              config = JSON.parse(cleanSingle);
            } catch(e2) {
              console.error("Erro ao analisar JSON do gráfico:", e1, jsonStr);
              return '';
            }
          }

          if (!config || typeof config !== 'object') return '';

          // Assegura valores positivos para gráficos de pizza ou rosca
          if (config.type === 'pie' || config.type === 'doughnut') {
            if (config.datasets && Array.isArray(config.datasets)) {
              config.datasets.forEach(ds => {
                if (ds && Array.isArray(ds.data)) {
                  ds.data = ds.data.map(v => Math.abs(Number(v) || 0));
                }
              });
            }
          }

          chartConfigs.push({ id: chartId, config });
          // Usa placeholder em vez de HTML direto para não ser escapado pelo formatMarkdown
          const placeholder = `CHARTPLACEHOLDER${chartConfigs.length - 1}END`;
          chartHtmlParts.push({
            placeholder,
            html: `<div class="ai-chart-wrapper" style="margin: 12px 0; background: #141416; border: 1px solid rgba(224,170,62,0.3); border-radius: 8px; padding: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
                    <div style="font-size: 11px; font-weight: 700; color: #e0aa3e; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
                      <span>📊 Gráfico Interativo MQIA</span>
                    </div>
                    <div style="position: relative; height: 210px; width: 100%;">
                      <canvas id="${chartId}"></canvas>
                    </div>
                  </div>`
          });
          return placeholder;
        } catch(e) {
          console.error("Erro ao processar bloco do gráfico:", e, jsonStr);
          return ''; // Não exibe bloco de código corrompido se falhar
        }
      });

    // Remove qualquer bloco de código residual (```chart, ```json, etc.) para manter resposta 100% executiva
    processedText = processedText.replace(/```[a-zA-Z0-9_-]*\s*[\s\S]*?```/gi, '');
    processedText = processedText.replace(/```[a-zA-Z0-9_-]*/g, '');

    // Aplica formatMarkdown no texto com placeholders (não no HTML dos gráficos)
    let htmlContent = formatMarkdown(processedText.trim());

    // Substitui os placeholders pelo HTML real dos gráficos
    chartHtmlParts.forEach(({ placeholder, html }) => {
      htmlContent = htmlContent.replace(placeholder, html);
    });

    containerEl.innerHTML = htmlContent;

      // Renderiza os gráficos com Chart.js
      if (chartConfigs.length > 0 && window.Chart) {
        setTimeout(() => {
          chartConfigs.forEach(({ id, config }) => {
            const cvs = document.getElementById(id);
            if (!cvs) return;
            const ctx = cvs.getContext('2d');
            const defaultColors = ['#e0aa3e', '#00d26a', '#3b82f6', '#a855f7', '#ec4899', '#f97316', '#06b6d4'];
            
            const isPie = config.type === 'pie' || config.type === 'doughnut';
            const labels = config.labels || (config.data && config.data.labels) || [];
            let rawDatasets = config.datasets || (config.data && config.data.datasets);
            if (!rawDatasets || !Array.isArray(rawDatasets) || rawDatasets.length === 0) {
              const d = config.data || [];
              rawDatasets = [{
                label: config.title || 'Valores (R$)',
                data: Array.isArray(d) ? d : []
              }];
            }

            const datasets = rawDatasets.map((ds, idx) => ({
              ...ds,
              backgroundColor: ds.backgroundColor || (isPie ? defaultColors : (defaultColors[idx % defaultColors.length] || '#e0aa3e')),
              borderColor: '#18181b',
              borderWidth: 1,
              borderRadius: isPie ? 0 : 4
            }));

            try {
              new window.Chart(ctx, {
                type: config.type || 'bar',
                data: {
                  labels: labels,
                  datasets: datasets
                },
                options: {
                  responsive: true,
                  maintainAspectRatio: false,
                  plugins: {
                    legend: {
                      display: isPie || (datasets.length > 1),
                      position: 'top',
                      labels: { color: '#d1d5db', font: { family: 'Montserrat', size: 10 } }
                    },
                    title: {
                      display: !!(config.title || (config.options && config.options.plugins && config.options.plugins.title && config.options.plugins.title.text)),
                      text: config.title || (config.options && config.options.plugins && config.options.plugins.title && config.options.plugins.title.text) || '',
                      color: '#ffffff',
                      font: { family: 'Montserrat', size: 11, weight: '600' },
                      padding: { bottom: 8 }
                    },
                    tooltip: {
                      callbacks: {
                        label: function(c) {
                          const val = c.raw || 0;
                          return `${c.dataset.label || ''}: R$ ${Number(val).toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
                        }
                      }
                    }
                  },
                  scales: isPie ? {} : {
                    x: {
                      ticks: { color: '#9ca3af', font: { family: 'Montserrat', size: 9 } },
                      grid: { color: 'rgba(255,255,255,0.05)' }
                    },
                    y: {
                      ticks: {
                        color: '#9ca3af',
                        font: { family: 'Montserrat', size: 9 },
                        callback: v => (Math.abs(v) >= 1e6 ? (v/1e6).toFixed(1)+'M' : (Math.abs(v) >= 1e3 ? (v/1e3).toFixed(0)+'k' : v))
                      },
                      grid: { color: 'rgba(255,255,255,0.05)' }
                    }
                  }
                }
              });
            } catch (chartErr) {
              console.error("Falha ao inicializar Chart.js, aplicando fallback visual:", chartErr);
              const wrapper = cvs.closest('.ai-chart-wrapper');
              if (wrapper) {
                const listHtml = labels.map((lbl, idx) => {
                  const v = Math.abs(Number(datasets[0]?.data[idx] || 0));
                  return `<div style="display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 11px;">
                    <span style="color: #d1d5db;">${lbl}</span>
                    <span style="font-weight: 700; color: #e0aa3e;">R$ ${v.toLocaleString('pt-BR', {minimumFractionDigits: 2})}</span>
                  </div>`;
                }).join('');
                wrapper.innerHTML = `
                  <div style="font-size: 11px; font-weight: 700; color: #e0aa3e; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
                    <span>📊 ${config.title || 'Demonstrativo Visual MQIA'}</span>
                  </div>
                  <div style="padding: 4px 0;">${listHtml}</div>
                `;
              }
            }
          });
        }, 50);
    }
  }

  function addMessage(text, sender) {
    const msg = document.createElement('div');
    msg.className = `ai-message ${sender}`;
    if (sender === 'ai') {
      renderContentWithCharts(msg, text);
    } else {
      msg.textContent = text;
    }
    body.appendChild(msg);
    body.scrollTop = body.scrollHeight;
  }

  async function sendMessage() {
    const text = input.value.trim();
    if(!text) return;
    
    addMessage(text, 'user');
    input.value = '';

    // Scroll imediato após a mensagem do usuário
    body.scrollTop = body.scrollHeight;

    // 1. Balão temporário de "Digitando..." com 3 pontinhos pulsando em CSS
    const typingBubble = document.createElement('div');
    typingBubble.className = 'ai-typing-bubble';
    typingBubble.id = 'ai-typing-indicator';
    typingBubble.innerHTML = `
      <span class="ai-typing-dots">
        <span class="ai-typing-dot"></span>
        <span class="ai-typing-dot"></span>
        <span class="ai-typing-dot"></span>
      </span>
      <span class="ai-typing-label">Digitando...</span>
    `;
    body.appendChild(typingBubble);
    body.scrollTop = body.scrollHeight;

    const contextoDRE = {
      usuario: obterNomeUsuario(),
      saudacao: obterSaudacaoPeriodo(),
      filtros: { 
        ano: (typeof state !== 'undefined' && state.ano) ? state.ano : 2026, 
        mes: (typeof state !== 'undefined' && state.mes) ? state.mes : 9, 
        empresa: (typeof state !== 'undefined' && state.emp) ? state.emp : 'ALL', 
        centroCusto: (typeof state !== 'undefined' && Array.isArray(state.cenc) && state.cenc.length) ? state.cenc.join(',') : 'ALL' 
      },
      margem: document.getElementById('kpiMargemVal')?.textContent || '',
      vendaBruta: document.getElementById('kpiVBVal')?.textContent || ''
    };

    function showFriendlyError(msg) {
      if (typingBubble && typingBubble.parentNode) typingBubble.remove();
      if (cursorSpan && cursorSpan.parentNode) cursorSpan.remove();

      const errBox = document.createElement('div');
      errBox.className = 'ai-error-bubble';
      errBox.innerHTML = `
        <span style="font-size: 16px; line-height: 1;">⚠️</span>
        <div>
          <strong style="color: #fca5a5;">Assistente MQIA:</strong><br>
          <span>${msg}</span>
        </div>
      `;
      body.appendChild(errBox);
      body.scrollTop = body.scrollHeight;
    }

    const currentUrl = getWebhookUrl();
    const isStreamSupported = currentUrl === DEFAULT_WEBHOOK || currentUrl.includes('/api/ia/perguntar');

    if (!isStreamSupported) {
      // Modo legado/Webhook customizado sem suporte a SSE
      try {
        const response = await fetch(currentUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: text, contexto: contextoDRE })
        });
        const result = await response.json();
        if (typingBubble && typingBubble.parentNode) typingBubble.remove();
        if(result && result.resposta) {
          addMessage(result.resposta, 'ai');
        } else if (result && result.error) {
          showFriendlyError('Erro na análise: ' + result.error);
        } else {
          showFriendlyError('Resposta recebida em formato inesperado.');
        }
      } catch(err) {
        if (typingBubble && typingBubble.parentNode) typingBubble.remove();
        showFriendlyError('Desculpe, não foi possível conectar ao endpoint externo configurado.');
      }
      return;
    }

    // ── Modo Streaming em Tempo Real com a API Mistral ───────────────────
    let msgAi = null;
    let textSpan = null;
    let cursorSpan = null;
    let accumulatedText = '';
    let receivedFirstChunk = false;

    try {
      const response = await fetch('/api/ia/perguntar/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text, contexto: contextoDRE })
      });

      if (!response.ok || !response.body) {
        throw new Error(`Falha na conexão de streaming (${response.status}).`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop(); // Mantém eventual chunk incompleto

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data: ')) continue;
          const jsonStr = trimmed.slice(6).trim();
          try {
            const data = JSON.parse(jsonStr);

            if (data.tipo === 'status') {
              // Mantém exibição de "Digitando..." conforme preferência visual
              if (!receivedFirstChunk && typingBubble && typingBubble.parentNode) {
                const labelEl = typingBubble.querySelector('.ai-typing-label');
                if (labelEl) {
                  labelEl.textContent = 'Digitando...';
                }
              }
            } else if (data.tipo === 'token') {
              // ── Assim que o primeiro chunk de texto chega da Mistral ──
              if (!receivedFirstChunk) {
                receivedFirstChunk = true;
                // Substitui o "Digitando..." pelo início da resposta
                if (typingBubble && typingBubble.parentNode) {
                  typingBubble.remove();
                }

                msgAi = document.createElement('div');
                msgAi.className = 'ai-message ai';

                textSpan = document.createElement('span');
                textSpan.className = 'ai-text-content';

                cursorSpan = document.createElement('span');
                cursorSpan.className = 'ai-typing-cursor';
                cursorSpan.textContent = '▌';

                msgAi.appendChild(textSpan);
                msgAi.appendChild(cursorSpan);
                body.appendChild(msgAi);
              }

              // Concatena palavra por palavra / token em tempo real
              accumulatedText += data.texto;
              // Durante o streaming, se o bloco de gráfico estiver sendo recebido, oculta o código bruto
              let displayText = accumulatedText;
              if (displayText.includes('```chart') || displayText.includes('```grafico')) {
                displayText = displayText.split(/```(?:chart|grafico)/i)[0] + '\n\n*(📊 Renderizando gráfico interativo...)*';
              }
              textSpan.innerHTML = formatMarkdown(displayText);
              // Garante o scroll automático para o final da conversa
              body.scrollTop = body.scrollHeight;

            } else if (data.tipo === 'fim') {
              if (typingBubble && typingBubble.parentNode) typingBubble.remove();
              if (cursorSpan && cursorSpan.parentNode) cursorSpan.remove();
              const finalText = data.resposta_completa || accumulatedText;
              if (msgAi) {
                renderContentWithCharts(msgAi, finalText);
              }
              body.scrollTop = body.scrollHeight;
              return;

            } else if (data.tipo === 'erro') {
              showFriendlyError(data.erro || 'Desculpe, ocorreu uma instabilidade na consulta analítica.');
              return;
            }
          } catch(e) {
            console.error('Erro ao interpretar SSE da Mistral:', e, jsonStr);
          }
        }
      }

      // Finalização preventiva se a conexão fechar sem evento 'fim'
      if (typingBubble && typingBubble.parentNode) typingBubble.remove();
      if (cursorSpan && cursorSpan.parentNode) cursorSpan.remove();
      if (msgAi && accumulatedText) {
        renderContentWithCharts(msgAi, accumulatedText);
      }
      body.scrollTop = body.scrollHeight;

    } catch(err) {
      console.error('Erro no streaming da Mistral AI:', err);
      showFriendlyError('Desculpe, ocorreu uma instabilidade ao conectar com a Mistral AI. Verifique sua conexão e tente novamente.');
    }
  }

  btnSend.addEventListener('click', sendMessage);
  input.addEventListener('keypress', (e) => {
    if(e.key === 'Enter') sendMessage();
  });

  // ── Inicialização do Modo Tela Cheia ────────────────────────────────────
  initFullscreenToggle();
});

// ── Gerenciador de Modo Tela Cheia Universal (F11 / Tecla F / Botão / Iframe Intranet) ──────
function initFullscreenToggle() {
  const btnFs = document.getElementById('btnFullscreen');
  if (!btnFs) return;
  const fsIcon = document.getElementById('fsIcon');
  const fsText = document.getElementById('fsText');

  function isCurrentlyFullscreen() {
    return !!(
      document.fullscreenElement ||
      document.webkitFullscreenElement ||
      document.mozFullScreenElement ||
      document.msFullscreenElement
    );
  }

  function updateFsUI() {
    const isFs = isCurrentlyFullscreen();
    if (fsIcon) {
      fsIcon.textContent = isFs ? 'fullscreen_exit' : 'fullscreen';
    }
    if (fsText) {
      fsText.textContent = isFs ? 'Sair Tela Cheia' : 'Modo Tela Cheia';
    }
    btnFs.classList.toggle('active', isFs);
    btnFs.title = isFs
      ? 'Sair do Modo Tela Cheia (Esc ou F11)'
      : 'Ativar Modo Tela Cheia (F11 ou tecla F)';
    document.body.classList.toggle('is-fullscreen-mode', isFs);

    // Disparar resize nos gráficos do Chart.js para readaptação imediata
    window.dispatchEvent(new Event('resize'));
  }

  btnFs.addEventListener('click', async () => {
    try {
      if (!isCurrentlyFullscreen() && !document.body.classList.contains('is-fullscreen-mode')) {
        const docEl = document.documentElement;
        if (docEl.requestFullscreen) {
          await docEl.requestFullscreen();
        } else if (docEl.webkitRequestFullscreen) {
          await docEl.webkitRequestFullscreen();
        } else if (docEl.mozRequestFullScreen) {
          await docEl.mozRequestFullScreen();
        } else if (docEl.msRequestFullscreen) {
          await docEl.msRequestFullscreen();
        } else {
          // Navegador sem API de fullscreen nativo
          throw new Error('Native Fullscreen API not supported');
        }
      } else {
        if (document.exitFullscreen) {
          await document.exitFullscreen();
        } else if (document.webkitExitFullscreen) {
          await document.webkitExitFullscreen();
        } else if (document.mozCancelFullScreen) {
          await document.mozCancelFullScreen();
        } else if (document.msExitFullscreen) {
          await document.msExitFullscreen();
        } else {
          throw new Error('Native Exit Fullscreen not supported');
        }
      }
    } catch (err) {
      console.warn('Fullscreen native request failed, toggling CSS fullscreen:', err);
      // Fallback robusto para ambientes incorporados/iframes
      const isFs = !document.body.classList.contains('is-fullscreen-mode');
      document.body.classList.toggle('is-fullscreen-mode', isFs);
      if (fsIcon) fsIcon.textContent = isFs ? 'fullscreen_exit' : 'fullscreen';
      if (fsText) fsText.textContent = isFs ? 'Sair Tela Cheia' : 'Modo Tela Cheia';
      btnFs.classList.toggle('active', isFs);
      window.dispatchEvent(new Event('resize'));
    }
  });

  document.addEventListener('fullscreenchange', updateFsUI);
  document.addEventListener('webkitfullscreenchange', updateFsUI);
  document.addEventListener('mozfullscreenchange', updateFsUI);
  document.addEventListener('MSFullscreenChange', updateFsUI);

  // Escutar evento de tela cheia disparado pela Intranet caso incorporado em iframe
  window.addEventListener('message', (event) => {
    if (event.data && (event.data.type === 'MQ_FULLSCREEN_CHANGE' || event.data.type === 'FULLSCREEN_STATE')) {
      const isFs = Boolean(event.data.isFullscreen);
      document.body.classList.toggle('is-fullscreen-mode', isFs);
      if (fsIcon) fsIcon.textContent = isFs ? 'fullscreen_exit' : 'fullscreen';
      if (fsText) fsText.textContent = isFs ? 'Sair Tela Cheia' : 'Modo Tela Cheia';
      btnFs.classList.toggle('active', isFs);
      window.dispatchEvent(new Event('resize'));
    }
  });

  // Tecla 'f' ou 'F' ativa/desativa tela cheia se não estiver em formulário
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
    if (e.key === 'f' || e.key === 'F') {
      e.preventDefault();
      btnFs.click();
    }
    // Suporte a tecla Esc no modo CSS fullscreen
    if (e.key === 'Escape' && document.body.classList.contains('is-fullscreen-mode') && !isCurrentlyFullscreen()) {
      document.body.classList.remove('is-fullscreen-mode');
      if (fsIcon) fsIcon.textContent = 'fullscreen';
      if (fsText) fsText.textContent = 'Modo Tela Cheia';
      btnFs.classList.remove('active');
      window.dispatchEvent(new Event('resize'));
    }
  });
}
