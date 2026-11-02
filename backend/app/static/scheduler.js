function initializeSchedulerForm(){
  const strategy=$('schedulerStrategy');
  if(strategy&&!strategy.options.length)strategy.innerHTML=$('strategySelect').innerHTML;
  const asset=$('schedulerAsset');
  if(asset&&!asset.options.length)asset.innerHTML=$('backtestAsset').innerHTML;
  if(!$('schedulerStart').value)$('schedulerStart').value=$('backtestStart').value;
  if(!$('schedulerEnd').value)$('schedulerEnd').value=$('backtestEnd').value;
}

function renderSchedulerTasks(tasks){
  const el=$('schedulerTasks');
  if(!tasks.length){
    el.innerHTML='<div class="empty-state">No hay tareas programadas. Crea una ejecución periódica con datos históricos disponibles.</div>';
    return;
  }
  el.innerHTML=tasks.map(task=>{
    const cancelled=Boolean(task.cancelled_at);
    const state=cancelled?'Cancelada':task.enabled?'Activa':'Pausada';
    const interval=Number(task.interval_seconds);
    const intervalLabel=interval>=86400?`Cada ${fmt(interval/86400,0)} día(s)`:interval>=3600?`Cada ${fmt(interval/3600,0)} hora(s)`:interval>=60?`Cada ${fmt(interval/60,0)} minuto(s)`:'Frecuencia no disponible';
    const action=task.enabled?'pause':'resume';
    const actionLabel=task.enabled?'Pausar':'Reanudar';
    return `<article class="scheduler-task"><div class="scheduler-task-info"><div class="scheduler-task-title"><b>${escapeHtml(task.name)}</b><span class="state-pill ${task.enabled?'completed':cancelled?'failed':'pending'}">${state}</span></div><p>${escapeHtml(intervalLabel)} · Prioridad ${fmt(task.priority,0)} · Concurrencia ${fmt(task.max_concurrency,0)} · Hasta ${fmt(task.max_attempts,0)} intentos</p><small>Próxima: ${escapeHtml(task.next_run_at?new Date(task.next_run_at).toLocaleString():'—')} · Última: ${escapeHtml(task.last_run_at?new Date(task.last_run_at).toLocaleString():'Sin ejecuciones')}</small></div><div class="scheduler-task-actions">${!cancelled?`<button class="secondary-button" data-scheduler-action="${action}" data-task-id="${escapeHtml(task.id)}">${actionLabel}</button>`:''}${task.enabled?`<button class="secondary-button danger-button" data-scheduler-action="cancel" data-task-id="${escapeHtml(task.id)}">Cancelar</button>`:''}</div></article>`;
  }).join('');
}

function renderSchedulerRuns(runs,tasks){
  const el=$('schedulerRuns');
  if(!runs.length){
    el.innerHTML='<div class="empty-state">Todavía no hay ejecuciones del planificador.</div>';
    return;
  }
  const names=new Map(tasks.map(task=>[task.id,task.name]));
  const statusLabels={pending:'Pendiente',running:'En ejecución',completed:'Completada',failed:'Fallida',cancelled:'Cancelada'};
  el.innerHTML=`<table class="scheduler-history-table"><thead><tr><th>TAREA</th><th>PROGRAMADA</th><th>ESTADO</th><th>WORKER</th><th>INTENTO</th><th>CREADA</th></tr></thead><tbody>${runs.map(run=>`<tr><td>${escapeHtml(names.get(run.scheduled_task_id)||String(run.scheduled_task_id||'').slice(0,8))}</td><td>${escapeHtml(run.scheduled_for?new Date(run.scheduled_for).toLocaleString():'—')}</td><td><span class="state-pill ${escapeHtml(run.status==='completed'?'completed':run.status==='failed'?'failed':run.status==='running'?'running':'pending')}">${escapeHtml(statusLabels[run.status]||run.status||'—')}</span></td><td>${escapeHtml(run.node_id||'—')}</td><td>${fmt(run.attempt_count,0)} / ${fmt(run.max_attempts,0)}</td><td>${escapeHtml(run.created_at?new Date(run.created_at).toLocaleString():'—')}</td></tr>`).join('')}</tbody></table>`;
}

async function loadScheduler(){
  initializeSchedulerForm();
  $('schedulerTasks').innerHTML='<div class="empty-state">Consultando tareas programadas…</div>';
  try{
    const [taskReport,runReport]=await Promise.all([
      api('/scheduler/tasks?limit=100'),
      api('/scheduler/runs?limit=100')
    ]);
    const tasks=taskReport.tasks||[];
    renderSchedulerTasks(tasks);
    renderSchedulerRuns(runReport.runs||[],tasks);
  }catch(error){
    $('schedulerTasks').innerHTML=`<div class="empty-state">No se pudieron cargar las tareas: ${escapeHtml(error.message)}</div>`;
    $('schedulerRuns').innerHTML='<div class="empty-state">El historial de ejecuciones no está disponible.</div>';
  }
}

async function createScheduledTask(){
  const button=$('createScheduleBtn');
  setBusy(button,true,'Programando…');
  try{
    const payload={
      name:$('schedulerName').value.trim(),
      strategy_id:$('schedulerStrategy').value,
      asset_id:$('schedulerAsset').value,
      timeframe:$('schedulerTimeframe').value,
      start_date:new Date(`${$('schedulerStart').value}T00:00:00Z`).toISOString(),
      end_date:new Date(`${$('schedulerEnd').value}T23:59:59Z`).toISOString(),
      initial_capital:Number($('schedulerCapital').value),
      interval_seconds:Number($('schedulerInterval').value),
      priority:Number($('schedulerPriority').value),
      max_concurrency:Number($('schedulerConcurrency').value),
      max_attempts:Number($('schedulerAttempts').value),
      parameters:{}
    };
    const result=await api('/scheduler/tasks',{method:'POST',body:JSON.stringify(payload)});
    $('schedulerMessage').textContent=`${result.task.name}: próxima ejecución ${new Date(result.task.next_run_at).toLocaleString()}. Solo backtesting DEMO.`;
    toast('Tarea periódica programada.');
    await loadScheduler();
  }catch(error){
    $('schedulerMessage').textContent=error.message;
    toast(error.message,true);
  }finally{
    setBusy(button,false);
  }
}

async function changeScheduledTask(taskId,action){
  if(action==='cancel'&&!window.confirm('Se detendrán futuras ejecuciones y se cancelarán las pendientes. Una ejecución activa podrá terminar. ¿Continuar?'))return;
  try{
    const result=await api(`/scheduler/tasks/${encodeURIComponent(taskId)}/${action}`,{method:'POST'});
    $('schedulerMessage').textContent=result.message;
    toast(result.message);
    await loadScheduler();
  }catch(error){
    $('schedulerMessage').textContent=error.message;
    toast(error.message,true);
  }
}

document.querySelector('[data-page="backtesting"]').addEventListener('click',loadScheduler);
$('createScheduleBtn').addEventListener('click',createScheduledTask);
$('reloadSchedules').addEventListener('click',loadScheduler);
$('schedulerTasks').addEventListener('click',event=>{
  const button=event.target.closest('[data-scheduler-action]');
  if(button)changeScheduledTask(button.dataset.taskId,button.dataset.schedulerAction);
});
