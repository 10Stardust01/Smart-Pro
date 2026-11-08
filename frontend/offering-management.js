import {instructionFields} from './setup-policy.js';

export function offeringPager(list,page,total){
 if(!page)return '';
 return `<div class="actions">${[['Previous',page-1,page>1],['Next',page+1,page*25<total]].filter(([, ,show])=>show).map(([label,target])=>
   `<form data-form="department-offering-page" data-list="${list}" data-page="${target}"><button class="secondary">${label} ${list}</button></form>`).join('')}</div>`;
}
export function offeringFilters(state,esc,data){
 if(!data?.page)return '';
 return `<form data-form="department-offering-search" class="form-grid">
   <label>Offering, cycle or semester<input type="search" name="q" maxlength="120" value="${esc(state.departmentOfferingSearch)}"></label>
   <label>Availability<select name="availability">${['ALL','ACTIVE','PAUSED','ARCHIVED'].map(v=>
     `<option value="${v}" ${state.departmentAvailability===v?'selected':''}>${v==='ALL'?'All states':v[0]+v.slice(1).toLowerCase()}</option>`).join('')}</select></label>
   <button class="secondary">Search offerings</button></form>
   <p>${data.total} matching offerings · Page ${data.page}</p>`;
}

export function offeringManagement(state,esc,displayDate){
 const offerings=state.management?.offerings||[];
 const selected=offerings.find(o=>o.id===state.staffOfferingId);
 const rows=selected?[selected]:offerings;
 if(!rows.length&&!state.management?.page)return '<section class="panel"><h2>No offerings configured</h2><p>Create the first offering below using the approved departmental settings.</p></section>';
 return `<section class="panel"><h2 id="department-offerings">Department offerings</h2>${selected?'<button class="quiet" data-action="all-offering-settings">← All offering settings</button>':''}<p>Inspect settings, maintain availability and preserve each change.</p>${selected?'':offeringFilters(state,esc,state.management)}${rows.map(o=>{const course=state.courses?.offerings.find(row=>row.id===o.id);return `<article class="project-card"><div class="panel-title"><h3>${esc(o.label)}</h3><span class="badge">${esc(o.availability==='ACTIVE'?'Active':o.availability==='PAUSED'?'Paused':'Archived')}</span></div><p>${esc(o.cycle_label)} · ${esc(o.semester_key)} · ${o.team_count} teams</p><p>Available ${displayDate(o.visible_from)} to ${displayDate(o.visible_until)}</p><details><summary>View settings</summary><dl class="profile-grid"><div><dt>Semester</dt><dd>${esc(o.semester_key)}</dd></div><div><dt>Synopsis opens</dt><dd>${displayDate(o.configuration?.submissionOpensAt)}</dd></div><div><dt>Synopsis closes</dt><dd>${displayDate(o.configuration?.submissionClosesAt)}</dd></div></dl>${Number(o.team_count)?'<p>Teams already use this offering. Department, cycle and semester cannot be changed.</p>':''}</details>${state.role==='Admin'?`<div class="actions"><button class="secondary" data-action="edit-offering" data-id="${o.id}">Edit offering</button>${course?`<button class="secondary" data-action="open-course" data-section="appointments" data-id="${o.id}">Manage coordinators</button>`:''}</div><details><summary>Manage availability</summary>${course&&!course.has_coordinator?`<p class="notice">Appoint an effective Coordinator before activating this offering.</p>`:''}<p>Pausing or archiving stops new enrollment, teams and proposals. Existing academic history remains available.</p><form data-form="manage-availability" data-id="${o.id}" data-revision="${o.management_revision}"><label>Availability<select name="availability" required>${['ACTIVE','PAUSED','ARCHIVED'].map(s=>`<option value="${s}" ${s===o.availability?'selected':''} ${s==='ACTIVE'&&course&&!course.has_coordinator&&o.availability!=='ACTIVE'?'disabled':''}>${s==='ACTIVE'?'Active':s==='PAUSED'?'Paused':'Archived'}</option>`).join('')}</select></label>${instructionFields(state,esc)}<button class="primary">Confirm availability change</button></form></details>`:''}<details><summary>History (${o.history.length})</summary>${o.history.map(h=>`<article><strong>${h.action==='EDIT'?'Offering settings updated':'Availability updated'}</strong><p>${displayDate(h.occurred_at)} · ${esc(h.before_state.offering.availability)} → ${esc(h.after_state.offering.availability)}</p><details><summary>Previous and revised settings</summary><p>Previous semester: ${esc(h.before_state.offering.semester_key)} · Revised semester: ${esc(h.after_state.offering.semester_key)}</p><p>Previous deadline: ${displayDate(h.before_state.configuration?.submissionClosesAt)} · Revised deadline: ${displayDate(h.after_state.configuration?.submissionClosesAt)}</p></details></article>`).join('')||'<p>No management changes recorded yet. Original configuration is retained below.</p>'}</details></article>`;}).join('')||'<p>No matching offerings on this page.</p>'}${selected?'':offeringPager('offerings',state.management?.page,state.management?.total)}</section>`;
}


export function configurationManagement(state,esc){
 const data=state.configurationManagement;
 if(!data)return '';
 return `<details class="panel setup-section"><summary>Manage academic cycles</summary>${data.cycles.map(c=>`<article class="project-card"><h3>${esc(c.code)}</h3><form data-form="manage-cycle" data-id="${c.id}" data-revision="${c.management_revision}"><label>Academic cycle name<input name="code" value="${esc(c.code)}" required maxlength="80"></label><label>Starts on<input name="startsOn" type="date" value="${c.starts_on}" required></label><label>Ends on<input name="endsOn" type="date" value="${c.ends_on}" required></label>${instructionFields(state,esc)}<button class="primary">Save cycle changes</button></form><details><summary>History</summary>${data.history.filter(h=>h.target_id===c.id).map(h=>`<p>${esc(h.metadata.before.code)}: ${h.metadata.before.starts_on} – ${h.metadata.before.ends_on} → ${h.metadata.after.starts_on} – ${h.metadata.after.ends_on}</p>`).join('')||'<p>No date changes recorded.</p>'}</details></article>`).join('')||'<p>No cycles configured yet.</p>'}</details>`;
}

export function candidateSearch(state,esc){
 const data=state.appointmentCandidates;
 if(!data)return '';
 return `<form data-form="appointment-candidate-search" class="form-grid">
  <label>Faculty name<input type="search" name="q" maxlength="120" value="${esc(state.candidateQuery)}"></label>
  <button class="secondary">Find eligible faculty</button></form>
  <p>${data.total} matching faculty · Page ${data.page}</p>
  ${offeringPager('candidates',data.page,data.total)}`;
}
