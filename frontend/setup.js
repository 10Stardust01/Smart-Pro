import {offeringPager,candidateSearch} from './offering-management.js';
import {requirementSetup} from './document-requirements.js';
import {configurationManagement} from './offering-management.js';
import {coordinatorPanel,assignmentManagement} from './coordination.js';
import {policySetupForms,readableRequest} from './setup-policy.js';
export function setupUI(state,esc) {
 const w=state.setup;
 if(!w)return '<section class="panel"><h1>Department setup</h1><p>Department setup is not enabled for this account yet. An authorized institution administrator must provision the required department authority. No academic access is granted automatically.</p></section>';
 const requests=w.requests.map(r=>`<article class="project-card">${readableRequest(r,state,esc)}<p>${r.approval_source==='EXTERNAL_INSTRUCTION'?'External HOD instruction · recorded by Admin · ':''}${r.configured_at?'Configured':r.approved_at?'Authorized — ready for Admin':'Awaiting HOD authorization'}</p>${(state.role==='HOD')&&!r.approved_at?`<button class="primary" data-action="approve-setup" data-id="${r.id}" ${r.kind==='REVIEW_BLUEPRINT'&&!w.canApproveRubric?'disabled title="Scheme approval authority has not been granted"':''}>Authorize setup</button>`:''}${state.workspace.access.operations&&r.requested_by===state.workspace.actor.id&&r.approved_at&&!r.configured_at?`<button class="primary" data-action="apply-setup" data-id="${r.id}">Apply authorized setup</button>`:''}</article>`).join('');
 const admin=state.workspace.access.operations&&!(state.role==='HOD');
 const html=`<div class="heading"><div><h1>Department setup</h1><p>Build your department’s academic context. Admin records and implements HOD-approved instructions, including instructions received outside SMART-PRO.</p></div></div>${admin?`<section class="panel"><h2>Academic cycle</h2><form data-form="setup-cycle" class="form-grid"><label>Cycle code<input name="code" required maxlength="80"></label><label>Starts on<input type="date" name="startsOn" required></label><label>Ends on<input type="date" name="endsOn" required></label><label>Note (optional)<input name="reason" maxlength="500"></label><button class="primary">Save configuration</button></form></section><section class="panel"><h2>Curriculum type</h2><form data-form="setup-type" class="form-grid"><label>Classification code<input name="code" required maxlength="80" pattern="[A-Z0-9_-]+"></label><label>Classification name<input name="label" required maxlength="120"></label><label>Note (optional)<input name="reason" maxlength="500"></label><button class="primary">Save configuration</button></form></section><section class="panel"><h2>Document exemption</h2><p>For an offering with no configured synopsis requirement, record an approved “not required” decision. Existing required submissions cannot be removed.</p><form data-form="setup-exemption"><label>Offering<select name="offeringId" required>${w.offerings.map(o=>`<option value="${o.id}">${esc(o.label)} · ${esc(o.semester_key.replace(/SYNTHETIC-SEM-?(\d+)/g,'Semester $1'))}</option>`).join('')}</select></label><label>Note (optional)<input name="reason" maxlength="500"></label><button class="secondary">Record approved exemption</button></form></section>`:''}${w.leadership?'':coordinatorPanel(state,esc)}${policySetupForms(state,esc)}<section class="panel"><h2>Configuration history</h2>${requests||'<p>No configuration has been recorded. Start with the approved academic cycle and curriculum type.</p>'}</section>`;
 return (html+requirementSetup(state,esc,v=>v?new Date(v).toLocaleString():'—')+configurationManagement(state,esc)+assignmentManagement(state,esc,v=>v?new Date(v).toLocaleString():'—')).replace(/<section class="panel"><h2>([^<]+)<\/h2>/g,(_,title)=>`<details class="panel setup-section"><summary>${title}</summary>`).replaceAll('</section>','</details>');
}
function importCounts(counts){
 if(!counts)return '';
 return `Created: ${counts.created} · Updated: ${counts.updated} · Unchanged: ${counts.unchanged} · Rejected: ${counts.rejected} · Conflicts: ${counts.conflicts}`;
}
function intakeForms(setup,state,esc,pager){
 const intake=setup.intake,draft=state.intakeDraft;
 if(!intake)return '';
 const records=state.recordScope==='intake'?state.intakeListing?.records||[]:[];
 const targets=state.intakeTargets;
 const candidates=targets?targets.records.filter(row=>row.account_status==='ACTIVE'):setup.options.people||[];
 const people=candidates.map(p=>`<option value="${esc(p.id)}">${esc(p.display_name)}</option>`).join('');
 const columns=draft?.kind==='FACULTY'?{key:'Official faculty reference',name:'Name',department:'Department code'}:
  {key:'Record reference',name:'Name',department:'Department code',usn:'Student number / USN',semester:'Semester',section:'Section'};
 const mapping=draft?Object.entries(columns).map(([name,label])=>`<label>${label}<select required name="${name}"><option value="">Choose a column</option>${draft.headers.map(header=>`<option value="${esc(header)}" ${draft.mapping?.[name]===header?'selected':''}>${esc(header)}</option>`).join('')}</select></label>`).join(''):'';
 const steps=['Choose a file','Map columns','Review and import'];
 const step=draft?.preview?2:draft?1:0;
 return `<section class="panel"><h2>Department records import</h2>
 <ol class="import-steps" aria-label="Import steps">${steps.map((label,i)=>`<li ${i===step?'aria-current="step"':''}>${label}</li>`).join('')}</ol>
 <p>Use a UTF-8 CSV export or a single-sheet XLSX export. Department code for this workspace is <strong>${esc(intake.departmentCode)}</strong>. Imported records are separate from login and appointments.</p>
 <form data-form="intake-file" class="form-grid">
 <label>Record source<select name="source"><option value="OFFICIAL">Official department export</option><option value="FORM_EXPORT">Downloaded Google Forms responses</option></select></label>
 <label>Record type<select name="kind"><option value="STUDENT">Students</option><option value="FACULTY">Faculty</option></select></label>
 <label>Export file<input name="file" type="file" accept=".csv,.xlsx" required></label>
 <button class="secondary">Preview file</button></form>
 ${draft?`<h3>File preview</h3><div class="table-wrap" tabindex="0" role="region" aria-label="Export file preview"><table aria-label="Export file sample"><thead><tr>${draft.headers.map(header=>`<th scope="col">${esc(header)}</th>`).join('')}</tr></thead><tbody>${draft.sample.map(row=>`<tr>${row.map(cell=>`<td>${esc(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
 <form data-form="intake-map" class="form-grid section-spacer">${mapping}<button class="secondary">Check mapped records</button></form>
 ${draft.preview?.counts?`<p><strong>Proposed outcome</strong> · ${importCounts(draft.preview.counts)}</p>`:''}
 ${draft.preview?.issues.length?`<ul role="alert">${draft.preview.issues.map(issue=>`<li>Record ${issue.row} · ${esc(issue.message)}</li>`).join('')}</ul><button class="secondary" type="button" data-action="export-intake-issues">Download correction report</button>`:draft.preview?`<form data-form="intake-apply" class="form-grid section-spacer"><p>${draft.preview.count} records ready to import</p><label>Source reference<input name="reference" required maxlength="500"></label><label class="check"><input name="confirmed" type="checkbox" required> I verified the source and the mapped records</label><button class="primary">Import checked records</button></form>`:''}`:''}
 ${records.length?`<h3 id="intake-link">Reconcile a record with an existing verified account</h3>
 ${targets?`<form data-form="intake-target-search" class="form-grid"><label>Verified account name or reference<input name="q" type="search" maxlength="120" value="${esc(state.targetQuery)}"></label><button class="secondary">Find accounts</button></form><p>${targets.total} matching department records · Page ${targets.page}</p>${pager('accounts',targets.page,targets.total)}`:''}
 <form data-form="intake-reconcile" class="form-grid">
 <label>Intake record<select name="recordIndex" required><option value="">Choose a record</option>${records.map((row,index)=>`<option value="${index}">${esc(row.record.name)} · ${esc(row.record.usn||row.identity_key)} · ${row.source==='OFFICIAL'?'Official':'Form response'}${row.linked_user_id?' · linked':''}</option>`).join('')}</select></label>
 <label>Verified account<select name="userId" required><option value="">Choose an account</option>${people}</select></label>
 <label class="check"><input type="checkbox" name="confirmed" required> I verified that the record and account belong to the same person</label>
 <label>Verification reference (optional)<input name="evidenceReference" maxlength="500"></label>
 <button class="secondary" ${people?'':'disabled'}>Link verified record</button></form>`:''}
 </section>`;
}
function leadershipForms(data,state,esc){
 if(!data)return '';
 const active=data.appointments.filter(term=>term.active);
 const admins=active.filter(term=>term.role_code==='ACADEMIC_ADMIN');
 const hod=active.find(term=>term.role_code==='HOD');
 const people=(state.appointmentCandidates?.records||data.people).filter(person=>person.id!==state.workspace.actor.id&&!admins.some(term=>term.user_id===person.id));
 const options=(rows)=>rows.map(row=>`<option value="${esc(row.id)}">${esc(row.display_name)}</option>`).join('');
 const person=label=>`<label>${label}<select name="userId" required><option value="">Choose a faculty member</option>${options(people)}</select></label>`;
 const currentAdmin=`<label>Current Admin<select name="appointmentId" required><option value="">Choose an Admin</option>${options(admins)}</select></label>`;
 const form=(action,label,fields)=>`<form data-form="leadership" data-leadership="${action}" class="form-grid section-spacer">${fields}<button class="secondary">${label}</button></form>`;
 let actions='';
 if(state.role==='HOD'){
  if(admins.length<data.adminCapacity)actions+=form('APPOINT_ADMIN','Appoint Admin',person('New Admin'));
  if(admins.length){
   actions+=form('REPLACE_ADMIN','Replace Admin',currentAdmin+person('Successor Admin'));
   actions+=form('END_ADMIN','End Admin appointment',currentAdmin);
  }
  actions+=form('SET_ADMIN_CAPACITY','Save Admin capacity',`<label>Authorized Admin capacity<input type="number" name="capacity" required min="1" max="50" value="${data.adminCapacity}"></label>`);
  if(hod)actions+=`<details><summary>HOD succession</summary><p>After you resign, an authorized Admin can appoint a successor.</p>${form('RESIGN_HOD','Resign as HOD',`<input type="hidden" name="appointmentId" value="${esc(hod.id)}">`)}</details>`;
 }else if(data.vacancyByResignation){
  actions=form('APPOINT_HOD','Appoint successor HOD',person('Successor HOD'));
 }
 const history=(data.history||data.appointments).map(term=>`<p>${esc(term.display_name)} · ${term.role_code==='HOD'?'HOD':'Admin'} · ${term.active?'Current':'Ended'} · ${esc(new Date(term.valid_from).toLocaleDateString())}${term.valid_until?' to '+esc(new Date(term.valid_until).toLocaleDateString()):''}${term.appointed_by?' · Appointed by '+esc(term.appointed_by):''}</p>`).join('');
 return `<section class="panel"><h2>Department leadership</h2><p>${hod?'HOD · '+esc(hod.display_name):'HOD vacancy'} · ${admins.length} of ${data.adminCapacity} Admin places occupied</p>${admins.map(term=>`<p><strong>Current Admin</strong> · ${esc(term.display_name)}</p>`).join('')}${actions?candidateSearch(state,esc):''}${actions}<details ${data.historyPage>1||state.leadershipSearch?'open':''}><summary id="leadership-history">Appointment history</summary>
 ${data.historyPage?`<form data-form="leadership-history-search" class="form-grid"><label>Appointment holder<input name="q" type="search" maxlength="120" value="${esc(state.leadershipSearch)}"></label><button class="secondary">Search appointment history</button></form><p>${data.historyTotal} matching terms · Page ${data.historyPage}</p>`:''}${history||'<p>No matching appointments on this page.</p>'}${offeringPager('leadership',data.historyPage,data.historyTotal)}</details></section>`;
}


export function departmentOverview(state,esc,heading){
 const hod=state.role==='HOD',setup=state.setup;
 const missing=state.courses?.offerings.filter(o=>!o.has_coordinator&&o.availability!=='ARCHIVED');
 return heading('DEPARTMENT WORKSPACE',hod?'Department Governance':'Department Operations',
   hod?'Review academic progress and manage department leadership.':'Manage offerings, coordinator appointments and departmental records.')
 + `<section class="panel priority-panel"><h2>${hod?'Academic oversight':'Operational tasks'}</h2>
 <div class="actions">${hod?'<button class="primary" data-go="courses">Review offering progress</button><button class="secondary" data-go="setup">Policy and configuration history</button>':
 '<button class="primary" data-go="documents">Manage offerings</button><button class="secondary" data-go="records">Search or import records</button><button class="secondary" data-go="setup">Cycles, curriculum and configuration</button>'}</div>
 </section><section class="panel"><h2>Offering attention</h2>${missing?.length?missing.map(o=>`<article class="project-card"><h4>${esc(o.label)}</h4><p>${esc(o.cycle_label)} · ${esc(o.semester_key)}. Student access is withheld until the department Admin appoints an effective coordinator.</p><button class="secondary" data-action="open-course" data-section="appointments" data-id="${esc(o.id)}">${hod?'Review coordinators':'Manage coordinators'}</button></article>`).join(''):missing?'<p>No offerings on this page are flagged for a missing coordinator.</p>':'<p>Coordinator coverage is unavailable in this workspace.</p>'}</section>`
 +leadershipForms(setup?.leadership,state,esc);
}

export function departmentRecords(state,esc){
 if(state.departmentRecordId)return recordDetails(state.departmentRecord,esc);
 const setup=state.setup,listing=state.intakeListing;
 if(!setup?.intake)return '<section class="panel"><h1>Department records</h1><p>Records intake is unavailable for this account.</p></section>';
 const pager=(list,page,total)=>`<div class="actions">${[['Previous',page-1,page>1],['Next',page+1,page*25<total]].filter(([, ,show])=>show).map(([label,target])=>`<form data-form="department-record-page" data-list="${list}" data-page="${target}"><button class="secondary">${label} ${list}</button></form>`).join('')}</div>`;
 const outcome=state.intakeOutcome;
 const intakeMode=state.recordScope==='intake';
 const directory=state.directoryListing;
 const scopedRows=intakeMode?listing?.records:directory?.records;
 const recordList=intakeMode?listing:directory;
 const recordCount=intakeMode?listing?.recordCount:directory?.total;
 return `<div class="heading"><div><h1>Department records</h1><p>Search departmental intake, link verified accounts and review import provenance.</p></div></div>
 ${outcome?`<p class="notice" role="status">Import recorded: ${esc(outcome.reference)} · ${outcome.count} checked records in this batch${outcome.counts?` · ${importCounts(outcome.counts)}`:''}</p>`:''}
 <section class="panel"><h2 id="intake-records">Search department records</h2>
 <form data-form="department-record-search" class="form-grid"><label>Source<select name="scope"><option value="directory">Department directory</option><option value="intake" ${intakeMode?'selected':''}>Imported records</option></select></label><label>Record type<select name="kind"><option value="STUDENT">Students</option><option value="FACULTY" ${state.intakeKind==='FACULTY'?'selected':''}>Faculty</option></select></label>
 <label>Name or record reference<input type="search" name="q" maxlength="120" value="${esc(state.intakeQuery)}"></label><button class="secondary">Search records</button></form>
 ${recordList?`<p>${recordCount} matching records · Page ${recordList.page} · ${esc(setup.intake.departmentCode)}</p>
 <ul class="record-results">${scopedRows.map(row=>intakeMode?`<li><span>${esc(row.record.name)} · ${esc(row.record.usn||row.identity_key)} · ${row.linked_user_id?'Linked to a verified account':row.possible_match?'Possible directory match. Verify identity before linking.':'Awaiting reconciliation'}</span>${row.linked_user_id?` <button class="quiet" data-action="open-department-record" data-id="${esc(row.linked_user_id)}">Open record</button>`:''}</li>`:
 `<li><span><strong>${esc(row.display_name)}</strong> ${row.usn?`· ${esc(row.usn)} · ${esc(row.semester_key)} · Section ${esc(row.section)}`:''}
 · ${row.officiallyLinked?'Linked official intake':'Department record'} · ${row.account_status==='ACTIVE'?'Active account':'Inactive account'}</span> <button class="quiet" data-action="open-department-record" data-id="${esc(row.id)}">Open record</button></li>`).join('')||'<li>No matching records on this page.</li>'}</ul>${pager('records',recordList.page,recordCount)}`:
 '<p>Search is unavailable until the departmental paging update is installed.</p>'}</section>
 ${intakeForms(setup,state,esc,pager)}
 <section class="panel"><h2 id="intake-history">Import batch history</h2>
 ${listing?`<p>${listing.batchCount} batches · Page ${listing.batchPage}</p>${listing.batches.map(batch=>`<p>${esc(batch.reference)} · ${batch.count} ${batch.count===1?'record':'records'} · ${batch.kind==='FACULTY'?'Faculty':'Students'} · ${batch.source==='OFFICIAL'?'Official export':'Form export'} · ${esc(batch.actor_name)} · ${esc(new Date(batch.created_at).toLocaleString())}${batch.outcome?` · ${importCounts(batch.outcome)}`:''}</p>`).join('')||'<p>No imports on this page.</p>'}${pager('batches',listing.batchPage,listing.batchCount)}`:'<p>Batch history is unavailable.</p>'}</section>`;
}


function recordDetails(record,esc){
 const back='<button class="quiet" data-action="close-department-record">Back to department records</button>';
 if(!record)return '<h1>Department record</h1>'+back;
 const renderHistory=(rows,render,empty)=>rows.length?`<ul>${rows.map(row=>`<li>${render(row)}</li>`).join('')}</ul>`:`<p>${empty}</p>`;
 const date=value=>esc(new Date(value).toLocaleString());
 const evidence='<label>Verification evidence reference<input name="evidence" required maxlength="500"></label>';
 const review=(link,operation,label)=>`<form data-form="faculty-identity" data-operation="${operation}" class="form-grid">
   <input type="hidden" name="linkId" value="${esc(link.id)}">${evidence}<button class="secondary">${label}</button></form>`;
 return `${back}<section class="panel"><h1>${esc(record.name)}</h1>
 <p>Account status · ${esc(record.status)}</p>
 ${record.student?`<p>Student · ${esc(record.student.usn)} · ${esc(record.student.semester)} · Section ${esc(record.student.section)}</p>`:''}
 ${record.faculty?'<p>Department faculty record</p>':''}</section>
 <section class="panel"><h2>Import history</h2>${renderHistory(record.imports,b=>`${esc(b.reference)} · ${esc(b.source)} · ${esc(b.actor)} · ${date(b.created_at)}`,'No linked imports recorded.')}</section>
 <section class="panel"><h2>Reconciliation history</h2>${renderHistory(record.history,e=>`${esc(e.action.replaceAll('_',' ').toLowerCase())} · ${esc(e.actor||'Recorded by system')} · ${date(e.occurred_at)}${e.evidence?' · '+esc(e.evidence):''}`,'No reconciliation recorded.')}</section>
 ${record.faculty?`<section class="panel"><h2>Faculty identity evidence</h2>
 <p>Choose an entry only after checking the institutional identifier. A verified association records evidence for this operational account. Sign-in and academic appointments follow their existing rules.</p>
 ${record.roster?.length?`<form data-form="faculty-identity" data-operation="PROPOSE" class="form-grid">
 <label>Directory entry<select name="directoryRef" required><option value="">Choose an entry</option>${record.roster.map(r=>`<option value="${esc(r.ref)}">${esc(r.name)} · ${esc(r.designation)}</option>`).join('')}</select></label>
 <label>Institutional source<input name="source" required maxlength="120"></label><label>Institutional identifier<input name="identifier" required maxlength="120"></label>${evidence}<button class="primary">Propose association</button></form>`:''}
 ${record.links.map(link=>`<article class="project-card"><h3>${esc(link.state)}</h3><p>${esc(link.identifier_source)} · ${esc(link.external_identifier)} · ${esc(link.evidence)}</p><p>${esc(record.roster?.find(r=>r.ref===link.directory_ref)?.name||link.directory_ref)}</p>
 ${link.state==='PROPOSED'?review(link,'VERIFY','Verify association')+review(link,'REJECT','Reject association'):link.state==='VERIFIED'?review(link,'REVOKE','Revoke association'):''}</article>`).join('')}</section>`:''}`;
}
