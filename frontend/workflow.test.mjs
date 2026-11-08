import assert from 'node:assert/strict';
import {documentState,windowState,canUpload,offeringProjects,megabytes,workspaceOpenError,pdfUploadResult} from './workflow.js';
import {proposalForm,projectLifecycle} from './proposal.js';
import {natural} from './workflow.js';
import {facultyReferencePanel,filterFaculty} from './faculty-reference.js';
import {readFileSync} from 'node:fs';
const now=Date.parse('2026-11-05T12:00:00Z');
let settled=0;
const settle=()=>settled++;
await assert.rejects(pdfUploadResult(Promise.resolve(new Response('Service Unavailable',{status:503})),settle),/retry with the same PDF/);
await assert.rejects(pdfUploadResult(Promise.reject(new TypeError('connection lost')),settle),/could not be confirmed/);
await assert.rejects(pdfUploadResult(Promise.resolve(new Response('{}')),settle),/could not be confirmed/);
assert.equal(settled,0);
await assert.rejects(pdfUploadResult(Promise.resolve(Response.json({detail:{message:'PDF too large'}},{status:400})),settle),/PDF too large/);
assert.equal((await pdfUploadResult(Promise.resolve(Response.json({documentVersionId:'version'})),settle)).documentVersionId,'version');
assert.equal(settled,2);
const p={canSubmit:true,requirement:{opensAt:'2026-11-05T11:00:00Z',closesAt:'2026-11-05T13:00:00Z'}};
assert.equal(documentState(p,now),'OPEN');assert.equal(canUpload(p,now),true);
assert.equal(documentState(p,now+7200000),'CLOSED');assert.equal(canUpload(p,now+7200000),false);
assert.equal(documentState(p,now-7200000),'NOT_YET_OPEN');
assert.equal(documentState({}),'NOT_CONFIGURED');
assert.equal(documentState({configurationPending:true}),'AWAITING_AUTHORIZATION');
assert.equal(documentState({requirementDisposition:'NOT_REQUIRED'}),'NOT_REQUIRED');
assert.equal(documentState({...p,case:{state:'APPROVED'}},now),'APPROVED');
assert.equal(canUpload({...p,case:{state:'APPROVED'}},now),false);
assert.equal(canUpload({...p,case:{state:'CHANGES_REQUESTED'}},now),true);
assert.equal(windowState({...p,case:{state:'CHANGES_REQUESTED'}},now+7200000),'CLOSED');
assert.deepEqual(offeringProjects([{id:'a',offeringId:'one'},{id:'b',offeringId:'two'}],'one'),[{id:'a',offeringId:'one'}]);
assert.deepEqual(offeringProjects([{offeringId:'one'}],'empty'),[]);
assert.equal(megabytes(628),'1 KB');assert.equal(megabytes(2097152),'2 MB');
const esc=value=>String(value??'');
const state={offerings:[{id:'offering',label:'Department studio'}],memberships:[{teamId:'team',teamName:'Research team'}],proposalConfig:{submissionState:'OPEN',requiresSynopsis:true,maxBytes:2097152}};
const proposal=proposalForm(state,esc,()=> 'offering',o=>o.label);
assert.match(proposal,/Synopsis PDF/);assert.match(proposal,/Review proposal/);
assert.doesNotMatch(proposal,/name="projectCode"|name="projectType"|Classification/);
assert.match(proposalForm({...state,proposalConfig:{submissionState:'CLOSED'}},esc,()=> 'offering',o=>o.label),/closed/);
assert.doesNotMatch(proposalForm({...state,proposalConfig:{submissionState:'CLOSED'}},esc,()=> 'offering',o=>o.label),/Review proposal/);
const lifecycle=projectLifecycle({}, {managedProposal:true,case:{state:'APPROVED',attempts:[{}]},guide:{name:'Faculty guide'}},[{label:'Design review',state:'PUBLISHED'}],esc,natural);
assert.match(lifecycle,/<dt>Proposal<\/dt><dd>Submitted/);
assert.match(lifecycle,/<dt>Synopsis review<\/dt><dd>Approved/);
assert.match(lifecycle,/<dt>Primary guide<\/dt><dd>Faculty guide/);
assert.match(lifecycle,/<dt>Evaluation<\/dt><dd>Design review · Completed/);
console.log('Workflow states, offering scope, deadlines, managed proposal and separate lifecycle assertions passed');

const {records}=JSON.parse(readFileSync(new URL('../backend/smartpro/reference_data/bit_main_cse_2026-11-07.json',import.meta.url)));
assert.equal(filterFaculty(records,{name:' j GIRiJA '}).length,1);
assert.equal(filterFaculty(records,{name:'Prashanth Kumar K N'}).length,1);
assert.equal(filterFaculty(records,{designation:'Professor',expertise:'image processing'}).length,0);
assert.equal(filterFaculty(records,{expertise:'image processing'})[0].name,'Dr. Savitha S K');
assert.equal(filterFaculty(records,{expertise:'advanced networking systems'})[0].name,'Prof. N Thanuja');
assert.match(filterFaculty(records,{expertise:'programming languages'})[0].name,/Geetha/);
assert.equal(filterFaculty(records,{name:'nonexistent entry'}).length,0);
const referenceContext={facultyReferenceDepartmentId:'cse'};
const referenceState={workspace:{department:{id:'cse'}}};
for(const role of ['Student','Faculty','Coordinator']){
  assert.equal(facultyReferencePanel({...referenceState,role},referenceContext,esc),'');
}
assert.match(facultyReferencePanel({...referenceState,role:'Coordinator'},referenceContext,esc,'assigned'),/data-offering="assigned"/);
assert.match(facultyReferencePanel({...referenceState,role:'Admin'},referenceContext,esc),/Faculty Reference/);
assert.equal(facultyReferencePanel({...referenceState,role:'HOD'},{},esc),'');

assert.match(lifecycle,/<dt>Results<\/dt><dd>Published · history available/);
assert.match(proposal,/name="description" required/);
assert.match(projectLifecycle({}, {managedProposal:true,requirementDisposition:'NOT_REQUIRED'},[],esc,natural),/<dt>Proposal<\/dt><dd>Submitted/);

const {guideForm,assignmentManagement}=await import('./coordination.js');
const guideState={workspace:{access:{admin:true},faculty:[],actor:{id:'hod'}},setup:{coordination:{canGuide:true}},role:'HOD'};
assert.match(guideForm({id:'project'},guideState,esc),/records synopsis-review responsibility/);
const assignments={assignments:[{id:'linked',title:'Project',display_name:'Faculty',assignment_type:'REVIEWER',source_guide_id:'guide',valid_from:'2020-01-01'}],operationGrants:[],facultyRoles:[],routineGrants:[]};
const history=assignmentManagement({...guideState,assignmentManagement:assignments},esc,String);
assert.match(history,/Synopsis reviewer · linked to primary guide/);
assert.doesNotMatch(history,/data-action="end-assignment"/);


assert.match(workspaceOpenError({status:400},true), /Restart SMART-PRO/);
assert.match(workspaceOpenError({status:404},true), /Restart SMART-PRO/);
assert.doesNotMatch(workspaceOpenError({status:400},false), /local server|Restart/);
assert.match(workspaceOpenError({status:401,serverMessage:'This responsibility is not assigned to your account'},true), /not assigned/);
