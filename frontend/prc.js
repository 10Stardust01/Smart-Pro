// PRC presentation components. All content comes from scoped PRC API reads.
// Existing document versions, faculty accounts and scoring remain authoritative.
const out=(value,escape)=>escape(value??'');
const statusText=p=>p.prcApproved?'PRC approved':p.prcDecision==='REJECT'?'Rejected — fresh synopsis required':p.prcDecision==='REQUEST_MODIFICATION'?'Modifications requested':p.synopsisState==='AWAITING_REVIEW'?'Awaiting PRC review':'Awaiting synopsis';

export function prcCoordinatorSection(state,course,escape){
  if(state.prcError)return `<section class="panel"><h2>PRC entry gate</h2><p role="alert">${out(state.prcError,escape)}</p><p>The PRC workflow must be installed and verified before activation; existing project records are unchanged.</p></section>`;
  const data=state.prcOverview;
  if(!data)return '<section class="panel"><h2>PRC entry gate</h2><p>Loading PRC assignments and decisions…</p></section>';
  const canManage=state.role==='Coordinator'&&course.responsibilities.includes('EVALUATORS');
  return `<section class="panel"><div class="panel-title"><div><span class="section-kicker">SYNOPSIS ENTRY GATE</span><h2>Project Review Committee (PRC)</h2></div><span class="badge">${data.activated?'Enabled':'Not enabled'}</span></div>
    <p>PRC reviews the synopsis <strong>before first Guide allocation</strong>. An approved synopsis allows allocation; modifications require revision, and rejection requires another synopsis. All attempts and official decisions remain in history.</p>
    ${!data.activated?
      (canManage?`<form data-form="prc-activate" data-offering="${out(course.id,escape)}"><p class="hint">Enable only when the approved synopsis requirement already permits approval, changes and resubmission. Existing Guide assignments remain intact.</p><label>Reason (optional)<input name="reason" maxlength="500"></label><button class="primary">Enable PRC entry gate</button></form>`:'<p>Your current appointment cannot activate PRC.</p>'):
      ''}</section>
    <section class="panel"><h2>PRC project queue</h2>
      ${data.projects.map(p=>`<article class="project-card"><div class="panel-title"><h3>${out(p.title,escape)}</h3><span class="badge">${out(statusText(p),escape)}</span></div>
        <p>Synopsis: ${out(p.synopsisState||'Not submitted',escape)} · Guide: ${p.guideAssigned?'Assigned':'Not assigned'}</p>
        <p><strong>PRC Members:</strong> ${p.members.map(m=>out(m.name,escape)).join(', ')||'Not assigned'}</p>
        ${data.activated&&canManage?`<form data-form="prc-assign" data-offering="${out(course.id,escape)}" data-project="${out(p.id,escape)}" class="form-grid">
          <label>Assign PRC Faculty<select name="facultyId" required><option value="">Choose eligible faculty</option>
          ${(state.courses?.faculty||[]).filter(f=>!p.members.some(m=>m.facultyId===f.id)).map(f=>`<option value="${out(f.id,escape)}">${out(f.display_name,escape)}</option>`).join('')}
          </select></label><label>Reason (optional)<input name="reason" maxlength="500"></label>
          <button class="secondary">Assign PRC member</button></form>
          ${p.members.map(m=>`<form data-form="prc-end-member" data-offering="${out(course.id,escape)}" data-member="${out(m.id,escape)}" class="form-grid"><p>End PRC assignment for ${out(m.name,escape)}</p><label>Reason (optional)<input name="reason" maxlength="500"></label><button class="quiet">End assignment</button></form>`).join('')}`:''}
      </article>`).join('')||'<p>No offering projects have been registered.</p>'}</section>`;
}

export function prcFacultySection(state,escape){
  const data=state.prcOverview;
  if(!data||!data.activated||!state.projectId)return '';
  const project=data.projects.find(p=>p.id===state.projectId);
  if(!project)return '';
  const ready=project.latestAttemptId&&project.synopsisState==='AWAITING_REVIEW';
  return `<section class="panel"><span class="section-kicker">ASSIGNED PRC RESPONSIBILITY</span>
      <h2>Synopsis PRC review</h2><p>${out(statusText(project),escape)}</p>
      ${ready?`<form data-form="prc-decision" data-offering="${out(state.prcOffering,escape)}" data-project="${out(project.id,escape)}" data-attempt="${out(project.latestAttemptId,escape)}" data-version="${out(project.caseVersion,escape)}">
        <label>PRC outcome<select name="decision" required>
          <option value="">Choose a decision</option>
          <option value="APPROVE">Approve — eligible for Guide allocation</option>
          <option value="REQUEST_MODIFICATION">Request modifications — revise synopsis</option>
          <option value="REJECT">Reject — submit another synopsis</option>
        </select></label>
        <label>PRC comments<textarea name="comment" maxlength="4000" required></textarea></label>
        <button class="primary">Record official PRC decision</button></form>`:project.prcApproved?'<p>PRC approved this synopsis. Guide allocation may proceed.</p>':'<p>No new synopsis attempt is awaiting a PRC decision.</p>'}
     </section>`;
}

export function prcStudentSection(status,escape){
  if(!status||!status.enabled)return '';
  const outcome=status.latestDecision;
  const line=status.approved?'PRC approved. Your project is eligible for Guide allocation.':
   outcome==='REJECT'?'Synopsis rejected. Submit another synopsis for a fresh PRC review.':
   outcome==='REQUEST_MODIFICATION'?'PRC requested modifications. Revise the synopsis and resubmit.':
   status.synopsisState==='AWAITING_REVIEW'?'Your synopsis is awaiting PRC review.':
   'Submit your synopsis for PRC review before Guide allocation.';
  return `<section class="panel"><span class="section-kicker">PROJECT ENTRY</span><h2>PRC review status</h2><p role="status">${out(line,escape)}</p>
    ${(status.history||[]).length?`<details><summary>Previous PRC decisions</summary>
      ${status.history.map(h=>`<article class="project-card"><strong>Submission ${out(h.attemptNo,escape)} — ${out(h.decision,escape)}</strong><p>${out(h.comment,escape)}</p></article>`).join('')}</details>`:''}
  </section>`;
}
