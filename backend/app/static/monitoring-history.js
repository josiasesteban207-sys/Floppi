const historyStatusLabels = {
  healthy: 'Saludable',
  degraded: 'Degradado',
  unhealthy: 'No saludable',
  unknown: 'Desconocido',
  online: 'En línea',
  busy: 'Ocupado',
  idle: 'Inactivo',
  offline: 'Desconectado',
  active: 'Activo',
  inactive: 'Inactivo',
  disconnected: 'Desconectado',
  pending: 'Pendiente',
  completed: 'Completada',
  failed: 'Fallida'
};

const historyStatusColors = {
  healthy: '#159b77',
  degraded: '#bd852c',
  unhealthy: '#d66d65',
  unknown: '#b7bfcc',
  online: '#159b77',
  busy: '#4d8df5',
  idle: '#bd852c',
  offline: '#d66d65',
  active: '#159b77',
  inactive: '#bd852c',
  disconnected: '#d66d65'
};

function historyEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[character]);
}

function historyNumber(value, digits = 2) {
  return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
    ? new Intl.NumberFormat('es-EC', { maximumFractionDigits: digits }).format(Number(value))
    : '—';
}

function historyPercent(value) {
  return value === null || value === undefined ? '—' : `${historyNumber(value)}%`;
}

function statusDistributionRows(distribution) {
  return Object.entries(distribution || {}).map(([status, values]) => {
    const percentage = values.percentage;
    const color = historyStatusColors[status] || historyStatusColors.unknown;
    return `<div class="history-distribution-row">
      <div class="history-distribution-label"><span>${historyEscape(historyStatusLabels[status] || status)}</span><b>${historyPercent(percentage)}</b></div>
      <div class="history-distribution-track"><i style="width:${Math.max(0, Math.min(100, Number(percentage) || 0))}%;background:${color}"></i></div>
      <small>${historyNumber(values.count, 0)} observaciones</small>
    </div>`;
  }).join('');
}

function resourceHistorySvg(history) {
  const series = [
    ['CPU', 'cpu_percent', '#7867ed'],
    ['RAM', 'memory_percent', '#4d8df5'],
    ['Disco', 'disk_percent', '#159b77']
  ];
  const width = 900;
  const height = 190;
  const padding = 28;
  const valid = history.filter(item => series.some(([, key]) => (
    item[key] !== null && item[key] !== undefined && Number.isFinite(Number(item[key]))
  )));
  if (!valid.length) return '<div class="empty-state">No hay métricas de recursos guardadas en este periodo.</div>';
  const paths = series.map(([label, key, color]) => {
    const segments = [];
    let points = [];
    valid.forEach((item, index) => {
      const value = Number(item[key]);
      if (item[key] === null || item[key] === undefined || !Number.isFinite(value)) {
        if (points.length) segments.push(points);
        points = [];
        return;
      }
      const x = padding + (index / Math.max(valid.length - 1, 1)) * (width - padding * 2);
      const y = height - padding - (Math.max(0, Math.min(100, value)) / 100) * (height - padding * 2);
      points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    });
    if (points.length) segments.push(points);
    return segments.map(segment => (
      `<polyline points="${segment.join(' ')}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><title>${label}</title></polyline>`
    )).join('');
  }).join('');
  const firstAt = valid[0].sampled_at ? new Date(valid[0].sampled_at).toLocaleString() : '';
  const lastAt = valid.at(-1).sampled_at ? new Date(valid.at(-1).sampled_at).toLocaleString() : '';
  return `<div class="history-resource-chart">
    <div class="history-chart-legend">${series.map(([label, , color]) => `<span><i style="background:${color}"></i>${label}</span>`).join('')}</div>
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="CPU, RAM y disco observados en el periodo">
      <g stroke="#edf0f5" stroke-width="1"><path d="M${padding} ${padding}H${width - padding}"/><path d="M${padding} ${height / 2}H${width - padding}"/><path d="M${padding} ${height - padding}H${width - padding}"/></g>
      <text x="2" y="${padding + 3}">100%</text><text x="2" y="${height / 2 + 3}">50%</text><text x="2" y="${height - padding + 3}">0%</text>
      ${paths}
    </svg>
    <div class="history-chart-range"><span>${historyEscape(firstAt)}</span><span>${historyEscape(lastAt)}</span></div>
  </div>`;
}

function workerHistorySvg(history) {
  if (!history.length) return '<div class="empty-state">No hay historial de workers en este periodo.</div>';
  const statuses = ['online', 'busy', 'idle', 'offline', 'unknown'];
  const colorFor = status => historyStatusColors[status] || historyStatusColors.unknown;
  const width = 900;
  const left = 95;
  const rowHeight = 28;
  const plottedHistory = history.length > 900
    ? Array.from({ length: 900 }, (_, index) => history[Math.round(index * (history.length - 1) / 899)])
    : history;
  const plotWidth = width - left - 12;
  const cellWidth = plotWidth / plottedHistory.length;
  const rows = ['blacki', 'blanquita'].map((worker, rowIndex) => {
    const y = 8 + rowIndex * rowHeight;
    const cells = plottedHistory.map((item, index) => {
      const status = statuses.includes(item[worker]) ? item[worker] : 'unknown';
      const x = left + index * cellWidth;
      const title = `${worker} · ${item.sampled_at ? new Date(item.sampled_at).toLocaleString() : 'fecha no disponible'} · ${historyStatusLabels[status] || status}`;
      return `<rect x="${x.toFixed(2)}" y="${y}" width="${Math.max(1, cellWidth - 1).toFixed(2)}" height="17" rx="2" fill="${colorFor(status)}"><title>${historyEscape(title)}</title></rect>`;
    }).join('');
    return `<text x="0" y="${y + 13}">${worker}</text>${cells}`;
  }).join('');
  const range = `<div class="history-chart-range"><span>${historyEscape(plottedHistory[0].sampled_at ? new Date(plottedHistory[0].sampled_at).toLocaleString() : '')}</span><span>${historyEscape(plottedHistory.at(-1).sampled_at ? new Date(plottedHistory.at(-1).sampled_at).toLocaleString() : '')}</span></div>`;
  const legend = ['online', 'busy', 'idle', 'offline', 'unknown'].map(status => (
    `<span><i style="background:${colorFor(status)}"></i>${historyEscape(historyStatusLabels[status])}</span>`
  )).join('');
  return `<div class="history-worker-chart"><div class="history-chart-legend">${legend}</div><svg viewBox="0 0 ${width} ${rowHeight * 2 + 8}" role="img" aria-label="Historial de estado de Blacki y Blanquita">${rows}</svg>${range}</div>`;
}

function historyTable(headers, rows) {
  return `<div class="table-scroll"><table class="monitoring-history-table"><thead><tr>${headers.map(item => `<th>${historyEscape(item)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderHistoricalMonitoring(report) {
  const indicators = document.getElementById('monitoringHistoryIndicators');
  const charts = document.getElementById('monitoringHistoryCharts');
  const content = document.getElementById('monitoringHistoryContent');
  if (!report || !indicators || !charts || !content) return;
  const total = Number(report.observations_count) || 0;
  if (!total) {
    indicators.innerHTML = '';
    charts.innerHTML = '';
    content.innerHTML = '<div class="empty-state">No hay observaciones guardadas para el periodo. El sistema no completa huecos con datos estimados.</div>';
    return;
  }

  const overall = report.overall_status_distribution || {};
  const workerCounts = report.worker_status_counts || {};
  const activeWorkers = workerCounts.active || 0;
  const workerObservations = Object.values(workerCounts).reduce((sum, value) => sum + Number(value || 0), 0);
  const healthyPercentage = overall.healthy?.percentage;
  indicators.innerHTML = [
    ['Muestras registradas', historyNumber(total, 0), 'Observaciones persistidas'],
    ['Estado saludable', historyPercent(healthyPercentage), `${historyNumber(overall.healthy?.count, 0)} muestras`],
    ['Workers activos', historyNumber(activeWorkers, 0), `de ${historyNumber(workerObservations, 0)} observaciones de nodo`],
    ['Workers desconectados', historyNumber(workerCounts.disconnected, 0), 'Heartbeat vencido o desconexión observada'],
    ['Workers sin telemetría', historyNumber(workerCounts.unknown, 0), 'Sin registro suficiente para clasificar']
  ].map(([label, value, detail]) => `<article class="history-indicator"><span>${label}</span><strong>${value}</strong><small>${detail}</small></article>`).join('');

  const resources = report.resource_statistics || {};
  const resourceCards = Object.entries(resources).map(([name, value]) => {
    const label = { cpu_percent: 'CPU', memory_percent: 'RAM', disk_percent: 'Disco', process_memory_mb: 'Memoria del proceso' }[name] || name;
    const suffix = name.endsWith('_percent') ? '%' : ' MB';
    const average = value.average === null ? '—' : `${historyNumber(value.average)}${suffix}`;
    const maximum = value.maximum === null ? '—' : `${historyNumber(value.maximum)}${suffix}`;
    return `<div class="history-resource-stat"><b>${historyEscape(label)}</b><span>Promedio <strong>${average}</strong></span><span>Máximo <strong>${maximum}</strong></span></div>`;
  }).join('');
  const resourceSection = `<div class="monitoring-history-block"><h3>Recursos del sistema · valores observados</h3>${resourceHistorySvg(report.resource_history || [])}<div class="history-resource-stats">${resourceCards}</div></div>`;
  const distributionSection = `<div class="monitoring-history-block"><h3>Distribución del estado general</h3>${statusDistributionRows(overall)}</div>`;
  charts.innerHTML = `<div class="monitoring-history-grid">${distributionSection}${resourceSection}<div class="monitoring-history-block history-wide"><h3>Historial de workers por muestra</h3>${workerHistorySvg(report.worker_history || [])}</div></div>`;

  const componentRows = Object.entries(report.component_status_distributions || {}).map(([component, distribution]) => {
    const percentages = Object.entries(distribution).map(([status, values]) => (
      `${historyStatusLabels[status] || status}: ${historyPercent(values.percentage)} (${historyNumber(values.count, 0)})`
    )).join(' · ');
    return `<tr><td>${historyEscape(component)}</td><td>${percentages}</td></tr>`;
  }).join('');
  const workerRows = Object.entries(report.worker_availability || {}).map(([worker, values]) => `<tr>
    <td>${historyEscape(worker)}</td>
    <td>${historyNumber(values.active_observations, 0)}</td>
    <td>${historyNumber(values.inactive_observations, 0)}</td>
    <td>${historyNumber(values.disconnected_observations, 0)}</td>
    <td>${historyNumber(values.unknown_observations, 0)}</td>
    <td>${historyPercent(values.availability_percentage)}</td>
  </tr>`).join('');
  const taskLabels = { pending: 'Pendientes', active: 'En ejecución', completed: 'Completadas', failed: 'Fallidas' };
  const taskRows = Object.entries(report.task_counts || {}).map(([status, values]) => `<tr>
    <td>${historyEscape(taskLabels[status] || status)}</td>
    <td>${historyNumber(values.observations, 0)}</td>
    <td>${values.average_per_observation === null ? '—' : historyNumber(values.average_per_observation)}</td>
    <td>${values.maximum_observed === null ? '—' : historyNumber(values.maximum_observed, 0)}</td>
  </tr>`).join('');
  content.innerHTML = `<div class="monitoring-history-grid">
    <div class="monitoring-history-block"><h3>Estado por componente</h3>${historyTable(['Componente', 'Distribución observada'], componentRows)}</div>
    <div class="monitoring-history-block"><h3>Estado por worker</h3>${historyTable(['Worker', 'Activos', 'Inactivos', 'Desconectados', 'Desconocidos', 'Activo %'], workerRows)}</div>
    <div class="monitoring-history-block history-wide"><h3>Cola de tareas por observación</h3>${historyTable(['Estado', 'Muestras', 'Promedio', 'Máximo'], taskRows)}</div>
  </div>`;
}

const monitoringMeta = document.getElementById('monitoringHistoryMeta');
if (monitoringMeta) {
  new MutationObserver(() => renderHistoricalMonitoring(state.monitoringStats))
    .observe(monitoringMeta, { childList: true, characterData: true, subtree: true });
}
