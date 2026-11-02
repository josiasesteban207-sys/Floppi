const diagnosticSeverityLabels={critical:'Crítico',error:'Error',warning:'Advertencia',info:'Informativo'};
const diagnosticStatusLabels={open:'Abierto',resolved:'Resuelto'};
let eventLogPage=1;
const eventLogPageSize=50;

function diagnosticsPeriodStart(){
  const hours=Number($('diagnosticsPeriod').value||24);
  return new Date(Date.now()-hours*3600000).toISOString();
}

function diagnosticsQuery(){
  const params=new URLSearchParams({since:diagnosticsPeriodStart(),limit:'200'});
  const severity=$('diagnosticsSeverity').value;
  const status=$('diagnosticsStatus').value;
  if(severity)params.set('severity',severity);
  if(status)params.set('status',status);
  return params.toString();
}

function renderDiagnosticIncidents(data){
  const incidents=data.incidents||[];
  $('diagnosticsTimestamp').textContent=`Actualizado ${new Date(data.generated_at).toLocaleString()}`;
  $('diagnosticsMeta').textContent=`${data.total} incidente(s) · Modo ${data.storage||'desconocido'} · La frecuencia cuenta eventos/muestras observados, no disponibilidad.`;
  if(!incidents.length){
    $('diagnosticsIncidentList').innerHTML='<div class="empty-state">No hay incidentes observados para estos filtros y este periodo.</div>';
    return;
  }
  $('diagnosticsIncidentList').innerHTML=incidents.map(item=>{
    const severity=diagnosticSeverityLabels[item.severity]||item.severity||'Desconocido';
    const status=diagnosticStatusLabels[item.status]||item.status||'Desconocido';
    const causes=(item.possible_causes||[]).map(cause=>`<li>${escapeHtml(cause)}</li>`).join('');
    const actions=(item.recommended_actions||[]).map(action=>`<li>${escapeHtml(action)}</li>`).join('');
    const affected=(item.affected_components||[]).map(escapeHtml).join(', ');
    const evidence=item.evidence&&Object.keys(item.evidence).length
      ?`<details class="diagnostic-evidence"><summary>Evidencia observada</summary><pre>${escapeHtml(JSON.stringify(item.evidence,null,2))}</pre></details>`
      :'';
    const resolveButton=item.status==='open'
      ?`<button class="secondary-button diagnostic-resolve" data-incident-id="${escapeHtml(item.id)}">Marcar resuelto</button>`
      :'';
    return `<article class="diagnostic-incident ${escapeHtml(item.severity||'')}">
      <div class="diagnostic-incident-head"><div><span class="diagnostic-severity ${escapeHtml(item.severity||'')}">${escapeHtml(severity)}</span><span class="state-pill ${item.status==='resolved'?'completed':'pending'}">${escapeHtml(status)}</span><h3>${escapeHtml(item.description||item.code||'Incidente')}</h3></div>${resolveButton}</div>
      <div class="diagnostic-incident-meta"><span><b>Componente</b>${escapeHtml(item.component||'—')}</span><span><b>Código</b>${escapeHtml(item.code||'—')}</span><span><b>Frecuencia</b>${fmt(item.occurrence_count,0)}</span><span><b>Afectados</b>${affected||'—'}</span></div>
      <div class="diagnostic-time-meta"><span>Primera observación: ${item.first_seen?new Date(item.first_seen).toLocaleString():'—'}</span><span>Última: ${item.last_seen?new Date(item.last_seen).toLocaleString():'—'}</span>${item.resolved_at?`<span>Resuelto: ${new Date(item.resolved_at).toLocaleString()}</span>`:''}</div>
      <div class="diagnostic-guidance"><div><b>Posibles causas</b><ul>${causes||'<li>No hay causas sugeridas.</li>'}</ul></div><div><b>Comprobaciones seguras</b><ul>${actions||'<li>No hay acciones sugeridas.</li>'}</ul></div></div>
      ${item.resolution_note?`<p class="diagnostic-resolution-note"><b>Nota de resolución:</b> ${escapeHtml(item.resolution_note)}</p>`:''}${evidence}
    </article>`;
  }).join('');
}

async function loadDiagnostics(){
  $('diagnosticsIncidentList').innerHTML='<div class="empty-state">Consultando historial persistente…</div>';
  try{
    const [summary,history]=await Promise.all([
      api('/diagnostics/summary'),
      api(`/diagnostics/incidents?${diagnosticsQuery()}`)
    ]);
    $('diagnosticsOpen').textContent=fmt(summary.open,0);
    $('diagnosticsCritical').textContent=fmt(summary.by_severity?.critical,0);
    $('diagnosticsErrors').textContent=fmt(summary.by_severity?.error,0);
    $('diagnosticsResolved').textContent=fmt(summary.resolved,0);
    if(summary.truncated)$('diagnosticsMeta').textContent=`Resumen limitado a 200 incidentes recientes (${summary.storage}).`;
    history.storage=summary.storage;
    renderDiagnosticIncidents(history);
    await loadSystemEvents();
  }catch(error){
    $('diagnosticsTimestamp').textContent='Sin conexión con el diagnóstico';
    $('diagnosticsIncidentList').innerHTML=`<div class="empty-state">${escapeHtml(error.message)}. Comprueba el entorno de desarrollo y la disponibilidad de la migración 011.</div>`;
    $('diagnosticsMeta').textContent='No se pudieron consultar los incidentes; no se muestran datos ficticios.';
    ['diagnosticsOpen','diagnosticsCritical','diagnosticsErrors','diagnosticsResolved'].forEach(id=>$(id).textContent='—');
    toast(error.message,true);
  }
}

function eventLogQueryParams(page=eventLogPage){
  const hours=Number($('diagnosticsPeriod').value||24);
  const params=new URLSearchParams({
    since:new Date(Date.now()-hours*3600000).toISOString(),
    page:String(page),
    page_size:String(eventLogPageSize)
  });
  const level=$('eventLogLevel').value;
  const component=$('eventLogComponent').value;
  const search=$('eventLogSearch').value.trim();
  if(level)params.set('level',level);
  if(component)params.set('component',component);
  if(search)params.set('search',search);
  return params;
}

function renderSystemEvents(report){
  const events=report.events||[];
  $('eventLogMeta').textContent=`${fmt(report.total,0)} evento(s) · ${report.storage} · Rango de ${$('diagnosticsPeriod').selectedOptions[0].textContent} · Datos observados, no valores sintéticos.`;
  $('eventLogPageLabel').textContent=`Página ${report.page} de ${Math.max(report.total_pages,1)}`;
  $('eventLogPrevious').disabled=report.page<=1;
  $('eventLogNext').disabled=report.page>=Math.max(report.total_pages,1);
  if(!events.length){
    $('eventLogContent').innerHTML='<div class="empty-state">No hay eventos observados con estos filtros.</div>';
    return;
  }
  const rows=events.map(item=>{
    const metadata=item.metadata&&Object.keys(item.metadata).length
      ?`<details><summary>Detalles</summary><pre>${escapeHtml(JSON.stringify(item.metadata,null,2))}</pre></details>`
      :'—';
    return `<tr><td>${item.occurred_at?new Date(item.occurred_at).toLocaleString():'—'}</td><td><span class="event-level ${escapeHtml(String(item.level||'').toLowerCase())}">${escapeHtml(item.level||'—')}</span></td><td>${escapeHtml(item.component||'—')}</td><td><code>${escapeHtml(item.code||'—')}</code><br/><span>${escapeHtml(item.message||'—')}</span></td><td>${item.request_id?`<code>${escapeHtml(item.request_id)}</code>`:'—'}</td><td>${item.task_id?`<code>${escapeHtml(item.task_id)}</code>`:'—'}</td><td>${metadata}</td></tr>`;
  }).join('');
  $('eventLogContent').innerHTML=`<table class="event-log-table"><thead><tr><th>FECHA UTC</th><th>NIVEL</th><th>COMPONENTE</th><th>EVENTO</th><th>REQUEST ID</th><th>TASK ID</th><th>METADATOS</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function loadSystemEvents(){
  $('eventLogContent').innerHTML='<div class="empty-state">Consultando eventos operativos…</div>';
  try{
    const report=await api(`/events?${eventLogQueryParams().toString()}`);
    renderSystemEvents(report);
  }catch(error){
    $('eventLogMeta').textContent='No se pudo consultar el registro de eventos.';
    $('eventLogContent').innerHTML=`<div class="empty-state">${escapeHtml(error.message)}. Comprueba la disponibilidad de la migración 012.</div>`;
    $('eventLogPrevious').disabled=true;
    $('eventLogNext').disabled=true;
    $('eventLogPageLabel').textContent='Página 1 de 1';
  }
}

function exportDiagnostics(format){
  const params=new URLSearchParams({format,since:diagnosticsPeriodStart()});
  const status=$('diagnosticsStatus').value;
  const severity=$('diagnosticsSeverity').value;
  if(status)params.set('status',status);
  if(severity)params.set('severity',severity);
  apiDownload(`/diagnostics/export?${params.toString()}`,'floppi_diagnostics_report','application/octet-stream').catch(error=>toast(error.message,true));
}

function exportSystemEvents(format){
  const params=eventLogQueryParams(1);
  params.delete('page');
  params.delete('page_size');
  params.set('format',format);
  apiDownload(`/events/export?${params.toString()}`,'floppi_events_report','application/octet-stream').catch(error=>toast(error.message,true));
}

async function resolveDiagnostic(button){
  const incidentId=button.dataset.incidentId;
  if(!incidentId||!window.confirm('¿Confirmas que este incidente fue revisado y puede marcarse como resuelto?'))return;
  button.disabled=true;
  try{
    await api(`/diagnostics/incidents/${encodeURIComponent(incidentId)}/resolve`,{
      method:'POST',
      body:JSON.stringify({resolution_note:'Revisado y marcado manualmente como resuelto desde el panel.'})
    });
    toast('Incidente marcado como resuelto.');
    await loadDiagnostics();
  }catch(error){
    button.disabled=false;
    toast(error.message,true);
  }
}

$('diagnosticsRefresh').addEventListener('click',loadDiagnostics);
['diagnosticsPeriod','diagnosticsSeverity','diagnosticsStatus'].forEach(id=>{
  $(id).addEventListener('change',loadDiagnostics);
});
$('diagnosticsExportJson').addEventListener('click',()=>exportDiagnostics('json'));
$('diagnosticsExportCsv').addEventListener('click',()=>exportDiagnostics('csv'));
$('diagnosticsIncidentList').addEventListener('click',event=>{
  const button=event.target.closest('.diagnostic-resolve');
  if(button)resolveDiagnostic(button);
});
$('eventLogSearchButton').addEventListener('click',()=>{
  eventLogPage=1;
  loadSystemEvents();
});
$('eventLogSearch').addEventListener('keydown',event=>{
  if(event.key==='Enter'){
    eventLogPage=1;
    loadSystemEvents();
  }
});
['eventLogLevel','eventLogComponent'].forEach(id=>{
  $(id).addEventListener('change',()=>{
    eventLogPage=1;
    loadSystemEvents();
  });
});
$('eventLogPrevious').addEventListener('click',()=>{
  if(eventLogPage>1){eventLogPage-=1;loadSystemEvents();}
});
$('eventLogNext').addEventListener('click',()=>{
  eventLogPage+=1;
  loadSystemEvents();
});
$('eventLogExportJson').addEventListener('click',()=>exportSystemEvents('json'));
$('eventLogExportCsv').addEventListener('click',()=>exportSystemEvents('csv'));
