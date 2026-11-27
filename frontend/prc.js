// Read-only progress. Committee appointment and decision powers are not inferred.
export function prcStatus(status,escape){
  if(!status?.enabled)return '';
  const line=status.approved?'PRC approved. Guide allocation may proceed.':
    status.latestDecision==='REJECT'?'PRC rejected this synopsis. Submit a fresh synopsis for review.':
    status.latestDecision==='REQUEST_MODIFICATION'?'PRC requested modifications. Revise and resubmit the synopsis.':
    status.synopsisState==='AWAITING_REVIEW'?'The synopsis is awaiting PRC review.':
    'PRC approval is required before Guide allocation.';
  return `<section class="panel"><h2>PRC progress</h2><p role="status">${escape(line)}</p>
    ${(status.history||[]).length?`<details><summary>PRC decision history</summary>${status.history.map(h=>
      `<article class="project-card"><h3>Submission ${escape(h.attemptNo)} · ${escape(h.decision)}</h3><p>${escape(h.comment)}</p></article>`).join('')}</details>`:''}</section>`;
}

export function prcOffering(state,escape){
  if(state.prcError)return `<section class="panel"><h2>PRC progress</h2><p role="alert">${escape(state.prcError)}</p></section>`;
  const data=state.prcOverview;
  if(!data)return '<section class="panel"><h2>PRC progress</h2><p>Loading PRC progress…</p></section>';
  const pages=Math.max(1,Math.ceil(data.total/data.pageSize));
  return `<section class="panel"><h2>PRC activities</h2><p>Track synopsis progress for your assigned offering. ${data.enabled?'PRC approval precedes Guide allocation.':'The PRC entry gate is not active for this offering.'}</p>
    ${data.projects.map(p=>`<article class="project-card"><h3>${escape(p.title)}</h3><button class="secondary" data-action="course-project-evidence" data-project="${escape(p.id)}">Open project evidence</button>${prcStatus(p.status,escape)}</article>`).join('')||'<p>No projects in this offering.</p>'}
    <nav aria-label="PRC project pages"><p>Page ${escape(data.page)} of ${escape(pages)} · ${escape(data.total)} projects</p>
      ${data.page>1?`<button class="secondary" data-action="queue-page" data-page="${data.page-1}">Previous page</button>`:''}
      ${data.page<pages?`<button class="secondary" data-action="queue-page" data-page="${data.page+1}">Next page</button>`:''}</nav></section>`;
}
