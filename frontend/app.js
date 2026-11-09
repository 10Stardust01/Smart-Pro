import {courseManagement,courseStageEditor,notificationPanel,assessmentSummary,stageCorrectionPanel} from './course-management.js';
import {reviewPlanning,reviewManagement} from './coordination.js';
import {policyPayload,stageEditor,criterionRow,instructionFields} from './setup-policy.js';
import {proposalForm,projectLifecycle} from './proposal.js';
import {setupUI,departmentOverview,departmentRecords} from './setup.js';
import {natural,offeringProjects,pdfUploadResult,workspaceOpenError} from './workflow.js';
import {documentsUI} from './documents.js';
import {facultyReferencePanel,openFacultyReference} from './faculty-reference.js';
const $ = (q, root = document) => root.querySelector(q);
let previewURL;
const selectedOffering = () => state.offeringId || state.workspace?.department?.offeringId;
const documentsBase = () => `/api/v1/documents/departments/${state.workspace.department.id}`;
const documentCommand = (action,body) => api(documentsBase(),'POST',{action,...body});
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {alias:sessionStorage.getItem('smartpro.identity'),view:'overview',workspace:null,profile:null,offerings:[],memberships:[],projects:[],staff:null,academic:null,reviewId:null,result:null,error:'',busy:false,generation:0,navigationPending:false,forceFullRefresh:false,studentMetadataValidUntil:0};
state.role=sessionStorage.getItem('smartpro.role.'+state.alias);
let controller = new AbortController();
const uiContext=await (await fetch('/api/v1/ui/context')).json();
if(uiContext.reviewerAuth && !uiContext.identities.includes(state.alias)){
  state.alias=null;
  state.role=null;
  sessionStorage.removeItem('smartpro.identity');
}
function csrfToken(){
  return decodeURIComponent((document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/)||[])[1]||'');
}
function reviewerHeaders(alias){
  return uiContext.reviewerAuth ? {'X-CSRFToken':csrfToken()} : {'X-Demo-User':alias};
}
const identities=uiContext.identities.map(alias=>[alias,uiContext.people?.[alias]||alias.replaceAll('-',' '),(uiContext.responsibilities?.[alias]?.join(' · ')||'Restricted access'),(uiContext.people?.[alias]||alias).split(' ').map(p=>p[0]).slice(0,2).join('')]);
const courseSections = new Set(['overview','appointments','requirements','plan','evaluation','assignments','submissions','deadlines','results','history']);
const departmentRole=()=>['Admin','HOD'].includes(state.role);
const departmentViews=new Set(['overview','documents','setup','records','courses','audit','notifications','projects','department','evaluations']);
function readCourseLocation(){
  const query=new URLSearchParams(location.search);
  state.courseId=null; state.courseSection='overview'; state.courseReviewId=null; state.courseProjectId=null;
  if(departmentRole()){
    state.departmentOfferingSearch=query.get('departmentOfferingSearch')?.slice(0,120)||'';
    state.departmentAvailability=['ACTIVE','PAUSED','ARCHIVED'].includes(query.get('departmentAvailability'))?query.get('departmentAvailability'):'ALL';
    const page=name=>/^[1-9][0-9]{0,7}$/.test(query.get(name)||'')?Number(query.get(name)):1;
    state.departmentOfferingPage=page('departmentOfferingPage');
    state.appointmentPage=page('appointmentPage');
    state.leadershipPage=page('leadershipPage');
    state.leadershipSearch=typeof history.state?.leadershipSearch==='string'?history.state.leadershipSearch.slice(0,120):'';
    const view=query.get('departmentView');
    state.view=departmentViews.has(view)?view:'overview';
    state.intakeKind=query.get('recordsKind')==='FACULTY'?'FACULTY':'STUDENT';
    state.intakeQuery=typeof history.state?.intakeSearch==='string'?history.state.intakeSearch.slice(0,120):'';
    state.departmentRecordId=query.get('record');
    state.recordScope=query.get('recordsScope')==='intake'?'intake':'directory';
    state.intakePage=/^[1-9][0-9]{0,7}$/.test(query.get('recordsPage')||'')?Number(query.get('recordsPage')):1;
    state.batchPage=/^[1-9][0-9]{0,7}$/.test(query.get('batchPage')||'')?Number(query.get('batchPage')):1;
    state.staffOfferingId=state.view==='documents'?query.get('offering'):null;
    if(state.view!=='courses')return;
  }else if(state.role!=='Coordinator'||!uiContext.courseManagement)return;
  state.view='courses';
  state.courseId=query.get('offering');
  const section=query.get('section');
  if(courseSections.has(section))state.courseSection=section;
  if(state.courseId){state.courseReviewId=query.get('assessment');state.courseProjectId=query.get('project');}
  state.queueQuery=query.get('q')?.slice(0,120)||'';
  state.queueStatus=['all','unassigned','in-progress','published'].includes(query.get('status'))?query.get('status'):'all';
  state.queuePage=/^[1-9][0-9]{0,8}$/.test(query.get('page')||'')?Number(query.get('page')):1;
   state.finalRevisionPageNumber=/^[1-9][0-9]{0,7}$/.test(query.get('correctionPage')||'')?Number(query.get('correctionPage')):1;
   state.finalRevisionAnchor=query.get('correctionAnchor')||null;
}
function writeCourseLocation(replace=false){
  const url=new URL(location.href);
  for(const key of ['offering','section','assessment','project','q','status','page','correctionPage','correctionAnchor'])url.searchParams.delete(key);
  for(const key of ['departmentView','recordsKind','recordsSearch','recordsPage','batchPage','recordsScope','departmentOfferingSearch','departmentAvailability','departmentOfferingPage','appointmentPage','leadershipPage','record'])url.searchParams.delete(key);
  if(departmentRole()){
    if(state.view!=='overview')url.searchParams.set('departmentView',state.view);
    if(state.departmentOfferingSearch)url.searchParams.set('departmentOfferingSearch',state.departmentOfferingSearch);
    if(state.departmentAvailability&&state.departmentAvailability!=='ALL')url.searchParams.set('departmentAvailability',state.departmentAvailability);
    if(state.departmentOfferingPage>1)url.searchParams.set('departmentOfferingPage',state.departmentOfferingPage);
    if(state.appointmentPage>1)url.searchParams.set('appointmentPage',state.appointmentPage);
    if(state.leadershipPage>1)url.searchParams.set('leadershipPage',state.leadershipPage);
    if(state.view==='records'&&state.departmentRecordId)url.searchParams.set('record',state.departmentRecordId);
    if(state.recordScope==='intake')url.searchParams.set('recordsScope','intake');
    if(state.intakeKind==='FACULTY')url.searchParams.set('recordsKind','FACULTY');
    if(state.intakePage>1)url.searchParams.set('recordsPage',state.intakePage);
    if(state.batchPage>1)url.searchParams.set('batchPage',state.batchPage);
    if(state.view==='documents'&&state.staffOfferingId)url.searchParams.set('offering',state.staffOfferingId);
  }
  if((state.role==='Coordinator'||departmentRole())&&state.view==='courses'&&state.courseId){
    url.searchParams.set('offering',state.courseId);
    url.searchParams.set('section',state.courseSection||'overview');
    if(state.courseReviewId)url.searchParams.set('assessment',state.courseReviewId);
    if(state.courseProjectId)url.searchParams.set('project',state.courseProjectId);
    if(state.queueQuery)url.searchParams.set('q',state.queueQuery);
    if(state.queueStatus&&state.queueStatus!=='all')url.searchParams.set('status',state.queueStatus);
    if(state.queuePage>1)url.searchParams.set('page',state.queuePage);
    if(state.courseSection==='results'&&state.finalRevisionPageNumber>1)url.searchParams.set('correctionPage',state.finalRevisionPageNumber);
    if(state.courseSection==='results'&&state.finalRevisionAnchor)url.searchParams.set('correctionAnchor',state.finalRevisionAnchor);
  }
  const intakeSearch=departmentRole()?state.intakeQuery||'':'';
  const leadershipSearch=departmentRole()?state.leadershipSearch||'':'';
  if(url.href!==location.href||intakeSearch!==(history.state?.intakeSearch||'')||leadershipSearch!==(history.state?.leadershipSearch||'')){
    history[replace?'replaceState':'pushState']({intakeSearch,leadershipSearch},'',url);
  }
}
const personalRole=()=>['Student','Faculty'].includes(state.role);
function readWorkLocation(){
  if(!personalRole())return;
  const query=new URLSearchParams(location.search),view=query.get('work');
  state.view=['documents','evaluations','results'].includes(view)?view:'overview';
  state.projectId=query.get('workProject');
  state.reviewId=query.get('workReview');
  state.workQuery=query.get('workSearch')?.slice(0,120)||'';
  state.workPage=/^[1-9][0-9]{0,8}$/.test(query.get('workPage')||'')?Number(query.get('workPage')):1;
  state.workOffering=query.get('workOffering')||'';
   state.guideCorrectionPage=/^[1-9][0-9]{0,7}$/.test(query.get('guideCorrectionPage')||'')?Number(query.get('guideCorrectionPage')):1;
   state.guideCorrectionAnchor=query.get('guideCorrectionAnchor')||null;
}
function writeWorkLocation(replace=false){
  const url=new URL(location.href);
  for(const key of ['work','workProject','workReview','workSearch','workPage','workOffering','guideCorrectionPage','guideCorrectionAnchor'])url.searchParams.delete(key);
  if(personalRole()&&['documents','evaluations','results'].includes(state.view)){
    url.searchParams.set('work',state.view);
    if(state.projectId)url.searchParams.set('workProject',state.projectId);
    if(state.reviewId&&state.view!=='documents')url.searchParams.set('workReview',state.reviewId);
    if(state.workQuery)url.searchParams.set('workSearch',state.workQuery);
    if(state.workPage>1)url.searchParams.set('workPage',state.workPage);
     if(state.view==='documents'&&state.projectId&&state.guideCorrectionPage>1)url.searchParams.set('guideCorrectionPage',state.guideCorrectionPage);
     if(state.view==='documents'&&state.projectId&&state.guideCorrectionAnchor)url.searchParams.set('guideCorrectionAnchor',state.guideCorrectionAnchor);
    if(state.role==='Student'&&state.workOffering)url.searchParams.set('workOffering',state.workOffering);
  }
  if(url.href!==location.href)history[replace?'replaceState':'pushState'](null,'',url);
}

const brand = '<div class="brand"><span class="brand-mark">S</span><span>SMART-PRO<small>DEPARTMENT WORKSPACE</small></span></div>';
const badge = (text, color = '') => `<span class="badge ${color}">${esc(text)}</span>`;
const empty = (title, text) => `<div class="empty"><span class="pill-icon">◇</span><strong>${esc(title)}</strong><p>${esc(text)}</p></div>`;
const button = (label, action, extra = '', kind = 'primary') => `<button class="${kind}" data-action="${action}" ${extra}>${esc(label)}</button>`;
const option = (id, label, selected) => `<option value="${esc(id)}" ${String(id) === String(selected) ? 'selected' : ''}>${esc(label)}</option>`;
const field = (label, name, value = '', type = 'text', more = '') => `<div><label for="${name}">${esc(label)}</label><input id="${name}" name="${name}" type="${type}" value="${esc(value)}" ${more}></div>`;
let reasonSequence = 0;
const reason = () => {
  const id = 'reason-'+(++reasonSequence);
  return `<div class="wide"><label for="${id}">Note (optional)</label><input id="${id}" name="reason" maxlength="500" placeholder="Additional context, if useful"></div>`;
};
const deptBase = () => `/api/v1/academic/departments/${state.workspace.department.id}`;
const staffBase = () => `/api/v1/staff/departments/${state.workspace.department.id}`;
const staffOffering = () => state.staff?.results.find(o=>o.id===state.staffOfferingId) || state.staff?.results[0];
const currentReview = () => state.workspace?.reviews.find(r => r.id === state.reviewId);
const displayDate = value => value ? new Date(value).toLocaleString(undefined, {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
const localDate = value => { const d = new Date(value); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0,16); };

async function api(path, method = 'GET', body, context = {alias:state.alias,role:state.role,signal:controller.signal}) {
  const headers = {Accept:'application/json',...reviewerHeaders(context.alias)};
  if(context.role)headers['X-Smartpro-Role']=context.role;
  const privateCommand=path.endsWith('/intake')||path.includes('/records/')||path.endsWith('/appointment-candidates')||path.endsWith('/leadership')&&body?.action==='HISTORY';
  const fingerprint = privateCommand?'':`${context.alias}:${path}:${JSON.stringify(body)}`;
  const pendingKey = 'smartpro.pending.'+context.alias;
  const pending = JSON.parse(sessionStorage.getItem(pendingKey) || '{}');
  if (method !== 'GET') {
    if(!(body instanceof FormData))headers['Content-Type'] = 'application/json';
    headers['Idempotency-Key'] = context.key || pending[fingerprint] || crypto.randomUUID();
    if(!privateCommand){
      pending[fingerprint] = headers['Idempotency-Key'];
      sessionStorage.setItem(pendingKey, JSON.stringify(pending));
    }
  }
  const response = await fetch(path, {method,headers,signal:context.signal,body:body === undefined || body instanceof FormData ? body : JSON.stringify(body)});
  let value;
  try { value=await response.json(); }
  catch {
    const error=new Error('The service could not complete this request. Please try again.');
    error.status=response.status;
    throw error;
  }
  if (method !== 'GET' && !privateCommand && response.status < 500) {
    delete pending[fingerprint]; sessionStorage.setItem(pendingKey, JSON.stringify(pending));
  }
  if (!response.ok) {
    const error = new Error(value.detail?.message || `Request rejected (${response.status})`);
    error.status = response.status;
    error.serverMessage = value.detail?.message;
    if(response.status===400)error.message='Check the required details, file and configured dates, then try again.';
    if(response.status===403)error.message='This action is not available for your current responsibility or assignment. Refresh to check your access.';
    if(response.status===409&&![
      'Appoint a replacement or pause the offering before removing its last coordinator',
      'Appoint a course coordinator before activation'
    ].includes(error.message))error.message='This item changed while you were working. Refresh it, review the latest details and try again. Saved work is preserved.';
    if(response.status>=500)error.message='This service is temporarily unavailable. Please retry shortly; saved work is preserved.';
    throw error;
  }
  return value;
}

async function load({reuseWorkspace=false}={}) {
  if(!state.alias)return;
  const generation = state.generation;
  const context = {alias:state.alias,role:state.role,signal:controller.signal};
  const get = path => api(path,'GET',undefined,context);
  const w = reuseWorkspace && state.workspace && !state.workspace.chooseRole && state.workspace.activeRole===state.role
    ? state.workspace : await get('/api/v1/workspace');
  if (generation !== state.generation) return;
  if(w.chooseRole){state.workspace=w;return;}
  const previousRole=state.role;
  state.role=w.activeRole||state.role;
  context.role=state.role;
  if(!previousRole&&personalRole()&&new URLSearchParams(location.search).has('work'))readWorkLocation();
  if(!previousRole&&(departmentRole()||state.role==='Coordinator'))readCourseLocation();
  const next = {departmentRecord:null,appointmentCandidates:null,directoryListing:null,intakeListing:null,intakeTargets:null,courses:null,courseDetail:null,courseEvaluationQueue:null,courseEvaluationError:'',finalRevisionListing:null,guideCorrectionError:'',workListing:null,courseDocumentListing:null,courseNotifications:null,guideFinalCorrections:null,reviewManagement:null,requirementManagement:null,assignmentManagement:null,configurationManagement:null,management:null,proposalConfig:null,proposalError:'',documentError:'',setup:null,workspace:w,profile:null,offerings:[],memberships:[],projects:[],staff:null,academic:null,result:null,error:''};
  // Resolve the role first, then load independent panels together.
  const staffCourse=['Coordinator','HOD'].includes(state.role)&&state.view==='courses';
  const workBrowser=personalRole()||state.role==='HOD'&&state.view==='documents';
  const assessmentEvidence=w.reviews.find(r=>r.id===state.reviewId)?.projectId;
  const courseDocuments=['assignments','submissions'].includes(state.courseSection);
  const coursePage=staffCourse&&state.courseId&&['assignments','submissions','plan','results','deadlines'].includes(state.courseSection);
  const selectedEvidence=staffCourse?(state.courseReviewId?w.reviews.find(r=>r.id===state.courseReviewId)?.projectId:
    (state.courseSection==='evaluation'||courseDocuments)?state.courseProjectId:null):workBrowser?
    (state.view==='documents'?state.projectId:['evaluations','results'].includes(state.view)?assessmentEvidence:null):null;
  const loadProjects=async()=>{
    if (w.access.student && w.enrolled && !w.access.admin) {
      // Reuse only short-lived, in-memory details for navigation, never after a write.
      // Memberships and projects always come from authorized server requests.
      const reused = reuseWorkspace && Date.now() < state.studentMetadataValidUntil
        && state.profile && state.offerings?.length;
      const [profile,offerings,memberships] = await Promise.all([
        reused ? Promise.resolve(state.profile) : get('/api/v1/me/profile'),
        reused ? Promise.resolve({results:state.offerings}) : get('/api/v1/me/curriculum-offerings'),
        get('/api/v1/me/memberships')
      ]);
      if(!reused)next.studentMetadataValidUntil=Date.now()+8000;
      next.profile = profile;
      next.offerings = offerings.results;
      next.offeringId = offerings.results.some(o=>o.id===state.offeringId)?state.offeringId:(offerings.results.find(o=>o.id===w.department?.offeringId)?.id||offerings.results[0]?.id);
      next.offerings=[...next.offerings].sort((a,b)=>a.id===next.offeringId?-1:b.id===next.offeringId?1:0);
      next.memberships = memberships.results.filter(m => m.offeringId === next.offeringId);
      if(next.offeringId&&state.view==='projects'){try{next.proposalConfig=await get(`/api/v1/curriculum-offerings/${next.offeringId}/proposal`);}catch(error){next.proposalError=error.message;}}
      next.projects=state.view==='history'?(await get('/api/v1/me/projects')).results:next.offeringId?(await get('/api/v1/me/projects?offeringId='+next.offeringId)).results:[];
    } else if(w.access.admin||w.access.faculty) {
      next.projects=w.assignedProjects;
    }
  };
  const loadDocuments=async()=>{
    if (w.department&&(selectedEvidence||workBrowser&&state.view==='documents'||coursePage||state.role==='Admin'&&state.view==='documents')) {
      if(state.role==='Student')await projects;
      const base=`/api/v1/documents/departments/${w.department.id}`;
      try {
        if(selectedEvidence)next.documents=await get(`${base}?project=${encodeURIComponent(selectedEvidence)}`);
        else if(state.role==='Admin')next.documents=await get(`${base}?configuration=1`);
        else {
          const filters=new URLSearchParams({listing:'1',q:staffCourse?state.queueQuery||'':state.workQuery||'',page:staffCourse?state.queuePage||1:state.workPage||1});
          if(staffCourse)filters.set('offering',state.courseId);
          else if(state.role==='Student'&&next.offerings.some(o=>o.id===state.workOffering))filters.set('offering',state.workOffering);
          const listing=await get(`${base}?${filters}`);
          if(staffCourse){next.courseDocumentListing=listing;next.queuePage=listing.page;}
          else{next.workListing=listing;next.workPage=listing.page;}
        }
      }catch(error){if(error.name==='AbortError')throw error;next.documents=null;next.documentError=error.message;}
    }
  };
  const loadSetup=async()=>{
    if((w.access.operations||w.access.admin)&&state.role!=='Coordinator') {try{next.setup=await get(`/api/v1/staff/departments/${w.department.id}/setup?intake=metadata`);}catch(error){if(error.status!==403)throw error;next.setup=null;}}
    if(departmentRole()&&state.view==='overview'&&next.setup?.leadership){
      try{
        next.setup.leadership=await api(`/api/v1/staff/departments/${w.department.id}/leadership`,'POST',{
          action:'HISTORY',page:state.leadershipPage||1,q:state.leadershipSearch||''
        },context);
      }catch(error){if(error.status!==503)throw error;}
    }
    if(state.role==='Admin'&&state.view==='records'&&state.departmentRecordId){
      next.departmentRecord=await get(`/api/v1/staff/departments/${w.department.id}/records/${encodeURIComponent(state.departmentRecordId)}`);
    }
    if(state.role==='Admin'&&state.view==='records'&&!state.departmentRecordId&&next.setup?.intake){
      const base=`/api/v1/staff/departments/${w.department.id}/intake`;
      const filters={kind:state.intakeKind||'STUDENT',q:state.intakeQuery||'',page:state.intakePage||1};
      const intakeMode=state.recordScope==='intake';
      try{
        next.intakeListing=await api(base,'POST',{action:'LIST',...filters,q:intakeMode?filters.q:'',page:intakeMode?filters.page:1,batchPage:state.batchPage||1},context);
        if(!intakeMode)next.directoryListing=await api(base,'POST',{action:'DIRECTORY',...filters},context);
        else if(next.intakeListing.records.length)next.intakeTargets=await api(base,'POST',{
          action:'DIRECTORY',kind:filters.kind,q:state.targetQuery||'',page:state.targetPage||1
        },context);
      }catch(error){if(error.status!==503&&error.status!==405)throw error;}
    }
  };
  const loadCandidates=async()=>{
    if(departmentRole()&&['overview','courses','setup','department'].includes(state.view)){
      try{
        next.appointmentCandidates=await appointmentCandidates(w.department.id,context);
      }catch(error){if(error.status!==503)throw error;}
    }
  };
  const loadCourses=async()=>{
    if(uiContext.courseManagement){
      if(['HOD','Admin','Coordinator'].includes(state.role)){
        const catalog=`/api/v1/courses/departments/${w.department.id}`;
        if(departmentRole()){
          const filters=new URLSearchParams({page:state.departmentOfferingPage||1,q:state.departmentOfferingSearch||'',
            availability:state.departmentAvailability||'ALL',appointmentPage:state.appointmentPage||1});
          const selected=state.view==='courses'?state.courseId:state.view==='documents'?state.staffOfferingId:null;
          if(selected)filters.set('selected',selected);
          try{next.courses=await get(`${catalog}?${filters}`);}
          catch(error){if(error.status!==503)throw error;}
        }
        if(!next.courses)next.courses=await get(catalog);
        if(w.access.operations)next.management=next.courses.page?next.courses:
          await get(`/api/v1/staff/departments/${w.department.id}/offering-management`);
        const offeringId=state.courseId;
        if(!offeringId||!next.courses.offerings.some(o=>o.id===offeringId))return;
        const base=`/api/v1/courses/offerings/${offeringId}`;
        const detail=get(base+'/details').then(value=>{next.courseDetail=value;});
         const revisions=state.courseSection==='results'?get(base+'/final-revisions?'+new URLSearchParams({page:state.finalRevisionPageNumber||1,...(state.finalRevisionAnchor?{anchor:state.finalRevisionAnchor}:{})})).then(value=>{next.finalRevisionListing=value;next.finalRevisionAnchor=value.anchor;}):Promise.resolve();
        const queue=async()=>{
          if(state.role!=='Coordinator'||!(state.courseSection==='evaluation'||state.courseReviewId))return;
          const focus=state.courseReviewId&&w.reviews.find(r=>r.id===state.courseReviewId)?.projectId;
          const filters=new URLSearchParams(focus?{q:focus}:{q:state.queueQuery||'',status:state.queueStatus||'all',page:state.queuePage||1});
          try {
            next.courseEvaluationQueue=await get(`${base}/evaluation-queue?${filters}`);
            if(!focus)next.queuePage=next.courseEvaluationQueue.page;
          }
          catch(error){if(error.name==='AbortError')throw error;next.courseEvaluationError=error.message;}
        };
        await Promise.all([detail,queue(),revisions]);
      }
    }
    if(w.access.operations&&!next.management)next.management=await get(`/api/v1/staff/departments/${w.department.id}/offering-management`);
  };
  const staffUrl=`/api/v1/staff/departments/${w.department?.id}`;
  const loadConfiguration=async()=>{
    await Promise.all([
      state.view==='setup'&&w.access.admin&&state.role!=='Coordinator'&&get(staffUrl+'/assignment-management').then(value=>{next.assignmentManagement=value;}),
      state.view==='setup'&&w.access.operations&&get(staffUrl+'/configuration-management').then(value=>{next.configurationManagement=value;}),
      state.view==='setup'&&w.access.operations&&get(staffUrl+'/document-requirements').then(value=>{next.requirementManagement=value;}),
      w.access.admin&&state.role!=='Coordinator'&&['setup','department','projects'].includes(state.view)&&
        get(`/api/v1/academic/departments/${w.department.id}/policies`).then(value=>{next.academic=value;})
    ]);
  };
  const projects=loadProjects();
  await Promise.all([
    projects,loadDocuments(),loadSetup(),loadCandidates(),loadCourses(),loadConfiguration(),
    uiContext.courseManagement&&['overview','notifications'].includes(state.view)&&get('/api/v1/me/course-notifications').then(value=>{next.courseNotifications=value;}),
    uiContext.courseManagement&&state.role==='Faculty'&&state.view==='documents'&&state.projectId&&get('/api/v1/me/published-corrections?'+new URLSearchParams({projectId:state.projectId,page:state.guideCorrectionPage||1,...(state.guideCorrectionAnchor?{anchor:state.guideCorrectionAnchor}:{})})).then(value=>{next.guideFinalCorrections=value;next.guideCorrectionAnchor=value.anchor;}).catch(error=>{if(error.name==='AbortError')throw error;next.guideCorrectionError=error.message;})
  ]);
  if(generation!==state.generation)return;
  if((w.access.faculty||w.access.admin)&&next.documents) next.projects=[...new Map([...next.projects,...next.documents.projects].map(p=>[p.id,p])).values()];
  if(next.documents && next.offeringId && w.access.student && !w.access.admin && !selectedEvidence && state.view!=='history' && !state.openFromHistory) next.documents={...next.documents,projects:offeringProjects(next.documents.projects,next.offeringId)};
  const scopedAssessment=state.role==='Coordinator'&&state.view==='courses'&&state.courseReviewId;
  const requestedReview=scopedAssessment||state.reviewId;
  const matchedReview=w.reviews.find(r=>r.id===requestedReview&&(!scopedAssessment||
    (next.courseDetail&&next.documents?.projects.some(p=>p.id===r.projectId&&p.offeringId===state.courseId))));
  next.reviewId=matchedReview?.id||(scopedAssessment?null:w.reviews[0]?.id)||null;
  if ((scopedAssessment||state.view==='evaluations'||state.view==='results') && next.reviewId) {
    next.result = await get(`/api/v1/academic/departments/${w.department.id}/reviews/${next.reviewId}/results`);
    if(w.access.admin)next.reviewManagement=await get(`/api/v1/academic/departments/${w.department.id}/reviews/${next.reviewId}/management`);
  }
  if (generation === state.generation) {
    Object.assign(state,next);
    if(!state.courseReviewId&&(next.courseEvaluationQueue||next.courseDocumentListing))writeCourseLocation(true);
  }
}

function appointmentCandidates(departmentId,context){
  return api(`/api/v1/staff/departments/${departmentId}/appointment-candidates`,'POST',
    {q:state.candidateQuery||'',page:state.candidatePage||1},context);
}

let toastTimer;
function clearToast() {
  clearTimeout(toastTimer);
  $('#toast').textContent='';
}
function toast(text) {
  clearToast();
  $('#toast').textContent=text;
  toastTimer=setTimeout(clearToast,5000);
}

function login() {
  $('#app').innerHTML = `<div class="login"><section class="login-story">${brand}<div class="eyebrow">ONE DEPARTMENT. EVERY MILESTONE.</div><h1>Good projects start<br>with a connected<br>department.</h1><p>A shared place for students, faculty and department leaders to move from an idea to a confident evaluation.</p><div class="story-bottom">ENROLL &nbsp; / &nbsp; COLLABORATE &nbsp; / &nbsp; BUILD &nbsp; / &nbsp; EVALUATE</div></section><main class="login-form" id="main" tabindex="-1"><div class="login-box"><div class="eyebrow">${uiContext.demo?'LOCAL DEVELOPMENT':uiContext.reviewerAuth?'AUTHORIZED REVIEWER':'SMART-PRO'}</div><h1>${uiContext.demo?'Choose your workspace':uiContext.reviewerAuth?'Continue to your workspace':'Sign-in configuration pending'}</h1><p>${uiContext.demo?'Use an explicit test identity to exercise real departmental workflows.':uiContext.reviewerAuth?'This reviewer session has been verified. Continue with your assigned academic responsibilities.':'Verified institutional sign-in must be configured before access is enabled.'}</p>${state.error ? `<div class="error" role="alert">${esc(state.error)}</div>` : ''}${identities.map(([alias,name,description,initials]) => `<button class="person-option" data-action="login" data-alias="${alias}"><span class="avatar">${initials}</span><span><strong>${name}</strong><small>${description}</small></span><span>→</span></button>`).join('')}<p class="login-foot">${uiContext.demo?'Synthetic test identities only. Real-user access remains disabled.':uiContext.reviewerAuth?'Permissions are checked on every request.':'Verified institutional sign-in is required. Contact your application administrator.'}</p></div></main></div>`;
}

function navigation() {
  const access = state.workspace.access;
  const documents=['documents','▣',personalRole()?'Project work':'Submissions & reviews'];
  if(access.operations&&!access.admin)return [['overview','▦','Department Operations'],['documents','▣','Offerings'],['records','◇','Department records'],['setup','⚙','Academic setup']];
  if(state.role==='Coordinator'&&uiContext.courseManagement)return [['courses','▦','Course Management'],...(state.view==='evaluations'?[['evaluations','▤','Assessment detail']]:[]),['audit','◷','Activity & history']];
  if(state.role==='HOD'&&access.admin)return [['overview','▦','Department Governance'],['setup','⚙','Policy & configuration'],['projects','◇','Projects & assignments'],['department','⚙','Department settings'],['evaluations','▤','Evaluations & results'],['audit','◷','Activity & audit']];
  if (access.admin) return [['overview','▦','Overview'],['projects','◇','Projects & assignments'],['department','⚙','Department settings'],['evaluations','▤','Evaluations & results'],['audit','◷','Activity & audit']];
  if (access.student) return [['overview','▦','Overview'],['enrollment','▣','My enrollment'],['teams','♧','Teams & membership'],['projects','◇','My projects'],['history','◷','Project history'],['results','▤','My results'],['audit','◷','My activity']];
  if (access.faculty) return [['overview','▦','Overview'],['evaluations','▤','Assigned evaluations'],['audit','◷','My audit trail']];
  return [['overview','▦','Access status']];
}

function render() {
  if (!state.alias || !state.workspace) return login();
  if(state.workspace.chooseRole)return roleChooser();
  const w = state.workspace, nav = navigation();
  if(uiContext.courseManagement)nav.push(['notifications','◷','Deadlines & alerts']);
  if(uiContext.courseManagement&&['HOD','Admin'].includes(state.role))nav.push(['courses','▦','Course Management']);
  if((w.access.operations||w.access.admin)&&state.role!=='Coordinator'&&!nav.some(n=>n[0]==='setup')) nav.push(['setup','⚙','Academic setup']);
  if ((personalRole()||state.role==='HOD'||state.documents||state.documentError) && !(state.role==='Coordinator'&&uiContext.courseManagement) && !nav.some(n=>n[0]==='documents')) nav.push(['documents','▣',personalRole()?'Project work':'Submissions & reviews']);
  if (!nav.some(n => n[0] === state.view)) state.view = 'overview';
  const role=({Student:'Student',Faculty:'Faculty member',Coordinator:'Course coordinator',HOD:'Head of department',Admin:'Department administrator'})[state.role]||'Department member';
  const sectionBody = state.navigationPending
    ? '<section class="panel navigation-loading" role="status" aria-live="polite"><span class="loading-indicator" aria-hidden="true"></span><strong>Loading your selected workspace…</strong><p class="muted">Checking the latest authorized records.</p></section>'
    : content();
  $('#app').innerHTML = `<div class="shell"><aside class="sidebar">${brand}<div class="nav-label">${esc(state.role||'Academic')} workspace</div><nav class="nav" aria-label="Main navigation">${nav.map(([id,icon,label]) => `<button class="${state.view === id ? 'active' : ''}" data-go="${id}" ${state.view === id ? 'aria-current="page"' : ''}><span class="symbol" aria-hidden="true">${icon}</span>${label}</button>`).join('')}</nav><div class="sidebar-bottom"><strong>${esc(academicText(w.department?.name || 'SMART-PRO'))}</strong>Academic project management</div></aside><div class="main-wrap"><header class="topbar"><div class="breadcrumbs">${esc(academicText(w.department?.name || 'Department workspace'))}<strong>${esc(nav.find(n => n[0] === state.view)[2])}</strong></div><div class="account"><span class="avatar">${esc(w.actor.name.split(' ').map(v => v[0]).slice(0,2).join(''))}</span><span><strong>${esc(w.actor.name)}</strong><small>${role}</small></span>${w.roleChoices?.length>1?`<label class="role-switch">Working as<select id="activeRole">${w.roleChoices.map(r=>option(r,r,state.role)).join('')}</select></label>`:''}<button class="quiet" data-action="logout">${uiContext.demo?'Switch test account':'Sign out'}</button></div></header><main id="main" tabindex="-1" class="main ${state.busy ? 'loading' : ''}" aria-busy="${state.busy}">${state.error ? `<div class="error" role="alert">${esc(state.error)}</div>` : ''}${sectionBody}${!state.navigationPending&&state.view==='overview'&&uiContext.courseManagement&&(state.courseNotifications?.tasks?.length||state.courseNotifications?.alerts?.length)?notificationPanel(state,esc,displayDate):''}<div class="footer"><span>SMART-PRO</span><span>Academic project records</span></div></main></div></div>`;
}

function heading(eyebrow,title,subtitle) {
 return `<header class="heading"><div class="heading-copy"><span class="eyebrow">${esc(eyebrow)}</span><h1>${esc(title)}</h1>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div><div class="heading-tools">${badge(academicText(state.workspace.department?.code||'Department'))} ${button('Refresh','refresh','','secondary')}</div></header>`;
}
function stats(items) {
 return `<div class="dashboard-metrics">${items.map(([label,value,detail])=>`<div class="metric"><span class="metric-label">${esc(label)}</span><strong class="metric-value">${esc(value)}</strong>${detail?`<small>${esc(detail)}</small>`:''}</div>`).join('')}</div>`;
}
function projectCards(projects=state.projects) {
  return projects.length ? projects.map(p => {
    const reviews = state.workspace.reviews.filter(r => r.projectId === p.id);
    const submission=state.documents?.projects.find(d=>d.id===p.id);

    return `<article class="project-card" data-search-record="${esc(p.title)}" data-review-status="${submission?.case?.state||'DRAFT'}"><div class="project-top"><div><div class="eyebrow">Project proposal</div><h3>${esc(p.title)}</h3></div></div>${projectLifecycle(p,submission,reviews,esc,natural)}<div class="actions">${button('Open project','open-project',`data-project="${p.id}"`,'secondary')}${reviews.length?button('View evaluation','open-review',`data-review="${reviews[0].id}"`,'quiet'):''}</div></article>`;
  }).join('') : (state.role==='Student'?empty('Your next project starts here','Create or join a team, then submit a proposal for the selected offering.'):empty('No projects yet',state.role==='Faculty'?'Projects will appear when you are assigned as a guide, reviewer or evaluator.':'Student proposals will appear here after submission.'));
}

function activity(limit = 5) {
  return state.workspace.audit.length ? `<div class="timeline">${state.workspace.audit.slice(0,limit).map(a => `<div class="timeline-item"><small>${displayDate(a.occurred_at)}</small><p>${esc(a.action.replaceAll('_',' ').toLowerCase())}</p></div>`).join('')}</div>` : empty('A fresh start','Your authorized activity will appear here as you work.');
}

function academicPriority(w) {
 if(w.access.student){
   const current=state.projects[0],offering=state.offerings.find(o=>o.id===selectedOffering());
   const [title,action,destination]=!w.enrolled?['Complete enrollment','View enrollment','enrollment']:current?['Continue your project','Open project work','documents']:!state.memberships.length?['Join or create a team','Browse teams','teams']:['Register your project','Open proposals','projects'];
   return `<section class="dashboard-hero"><div class="hero-copy"><span class="eyebrow">NEXT STEP</span><h2>${esc(title)}</h2>${current?`<p class="hero-detail">${esc(current.title)}</p>`:offering?`<p class="hero-detail">${esc(displayOffering(offering))}</p>`:''}<div class="actions"><button class="primary" data-go="${destination}">${esc(action)} <span aria-hidden="true">→</span></button>${current?'<button class="secondary" data-go="history">Project history</button>':''}</div></div><div class="hero-decoration" aria-hidden="true"><span class="hero-circle"></span><span class="hero-orbit"></span><span class="hero-mark">S</span></div></section>`;
 }
 if(w.access.faculty&&!w.access.admin)return `<section class="dashboard-hero"><div class="hero-copy"><span class="eyebrow">FACULTY DESK</span><h2>Assigned work</h2><p class="hero-detail">${state.projects.length} project${state.projects.length===1?'':'s'} in your workspace</p><div class="actions"><button class="primary" data-go="documents">View assigned projects →</button><button class="secondary" data-go="evaluations">Evaluations</button></div></div><div class="hero-decoration" aria-hidden="true"><span class="hero-circle"></span><span class="hero-orbit"></span><span class="hero-mark">S</span></div></section>`;
 return '';
}
function overview(){
 const w=state.workspace;
 if(departmentRole())return departmentOverview(state,esc,heading);
 if(!w.access.student&&!w.access.faculty)return heading('ACCESS','Workspace unavailable','Contact your department administrator.')+`<section class="panel">${empty('No academic access','Your account has no current academic assignment.')}</section>`;
 const student=w.access.student;
 return heading(student?'STUDENT WORKSPACE':'FACULTY WORKSPACE',student?'Overview':'Faculty overview',student?'Current project and academic records.':'Assigned projects, assessments and feedback.')+
  academicPriority(w)+stats([['Projects',state.projects.length,'Authorized records'],['Reviews',w.reviews.length,'Assigned or historical'],['Published results',w.reviews.filter(r=>r.state==='PUBLISHED').length,'Available releases']])+
  `<div class="dashboard-grid"><section class="panel dashboard-primary"><div class="panel-title"><div><span class="section-kicker">PROJECTS</span><h2>${student?'My projects':'Assigned projects'}</h2></div><button class="quiet" data-go="${student?'projects':'documents'}">View all →</button></div>${projectCards(state.projects.slice(0,3))}${state.projects.length>3?`<div class="actions"><button class="secondary" data-go="${student?'projects':'documents'}">More projects</button></div>`:''}</section><aside class="dashboard-aside"><section class="panel"><h2>${student?'Enrollment':'Evaluation desk'}</h2>${student?enrollmentSummary():`<p class="muted">${w.reviews.length} assigned or historical reviews.</p><button class="secondary" data-go="evaluations">Open evaluations</button>`}</section><section class="panel"><div class="panel-title"><h2>Recent activity</h2><button class="quiet" data-go="audit">View all</button></div>${activity(4)}</section></aside></div>`;
}
document.addEventListener('toggle',event=>{
  const panel=event.target;
  if(panel instanceof HTMLDetailsElement && panel.open && panel.hasAttribute('data-faculty-reference')){
    openFacultyReference(panel,path=>api(path),esc);
  }
},true);

function enrollmentSummary() {
  const p = state.profile, w = state.workspace;
  return p ? `${badge('Enrollment verified','green')}<dl class="profile-grid"><div><dt>USN</dt><dd>${esc(p.usn)}</dd></div><div><dt>Section</dt><dd>${esc(p.section)}</dd></div><div><dt>Semester</dt><dd>${esc(academicText(p.semester))}</dd></div><div><dt>Department</dt><dd>${esc(academicText(p.department.code))}</dd></div></dl>` : !state.workspace.admission ? `<p>Your department eligibility record has not been configured. Contact your department administrator.</p>` : `${badge('Confirmation pending','amber')}<p class="notice">Your department eligibility record is ready. Confirm enrollment to access the offerings in your home department.</p>${button('Confirm my enrollment','enroll')}`;
}

function enrollment() {
  const w = state.workspace;
  return heading('STUDENT RECORD','My department enrollment','Your department maintains your enrollment and eligibility.')+`<div class="grid"><section class="panel"><h2>${esc(w.actor.name)}</h2><p class="muted">${esc(academicText(w.department?.name))}</p>${enrollmentSummary()}${w.admission && !w.enrolled ? `<dl class="profile-grid"><div><dt>Approved USN</dt><dd>${esc(w.admission.usn)}</dd></div><div><dt>Semester</dt><dd>${esc(academicText(w.admission.semester))}</dd></div></dl>` : ''}</section><aside class="panel"><h2>Department-specific access</h2><p class="notice">Enrollment confirmation uses your approved department record. A request cannot change your identity, department or semester.</p><p class="muted">After confirmation, offerings, teams and project registration are filtered by the backend for your eligible scope.</p></aside></div>`;
}

function teamView() {
  if (!state.workspace.enrolled) return enrollment();
  const membership = state.memberships[0];
  return heading('COLLABORATE','Find your team. Build together.','One current team per offering, with preserved membership history.')+`<div class="grid"><div><section class="panel"><h2>Current membership</h2>${membership ? `<div class="row"><div><h3>${esc(membership.teamName)}</h3><p class="muted">Joined ${displayDate(membership.joinedAt)}</p></div>${badge('Active','green')}</div><div class="notice">Leaving or transferring ends this membership prospectively. Previous submissions, evaluations and results remain preserved.</div>${button('Leave current team','leave',`data-id="${membership.id}"`,'danger')}` : empty('You’re ready to join a team','Choose an eligible team below or create a new one.')}</section><section class="panel"><div class="panel-title"><h2>Available teams</h2>${badge('Your offering')}</div><div id="team-list"><p class="muted">Loading eligible teams…</p></div></section></div><aside><section class="panel"><h2>Create a team</h2><p class="muted">For ${esc(state.offerings[0]?.label || 'No offering selected')}</p>${membership ? '<p class="notice">You already have a current team in this offering. You can transfer to another eligible team below.</p>' : state.offerings.length ? `<form data-form="create-team" class="section-spacer"><label for="teamName">Team name</label><input id="teamName" name="name" maxlength="120" required placeholder="e.g. Aster Robotics"><div class="actions"><button class="primary" type="submit">Create team →</button></div></form>` : empty('Offering unavailable','The department has not published an eligible offering.')}</section><section class="panel"><h2>Membership policy</h2><p class="muted">Joining, leaving and transfers follow the configured offering policy. Available places and your current membership are checked before changes are saved.</p></section></aside></div>`;
}

async function loadTeams() {
  const target = $('#team-list'); if (!target) return;
  try {
    const teams = (await api(`/api/v1/curriculum-offerings/${selectedOffering()}/teams`)).results;
    if (!target.isConnected) return;
    const membership = state.memberships[0];
    target.innerHTML = teams.length ? teams.map(t => `<div class="row"><div class="row-start"><span class="pill-icon">♧</span><div><h3>${esc(t.name)}</h3><p class="muted">${esc(t.memberCount)} current members</p></div></div>${membership?.teamId === t.id ? badge('Your team','green') : button(membership ? 'Transfer here' : 'Join team',membership ? 'transfer' : 'join',`data-id="${t.id}"`,'secondary')}</div>`).join('') : empty('Be the first team','Create a team to begin this offering’s project journey.');
  } catch (e) { if (target.isConnected) target.innerHTML = `<div class="error">${esc(e.message)}</div>`; }
}

function projectsView() {
  const w = state.workspace;
  if (w.access.student && !w.enrolled) return enrollment();
  let form;
  if (w.access.admin) {
    const policies = state.academic?.policies || [];
    form = `<section class="panel"><h2>Assign a project review</h2><p class="muted">Uses the applicable active rubric and a pinned academic policy.</p>${state.projects.length ? `<form data-form="assign" class="form-grid section-spacer"><div class="wide"><label for="projectId">Project</label><select id="projectId" name="projectId">${state.projects.map(p => option(p.id,p.title)).join('')}</select></div><div class="wide"><label for="policyId">Academic policy</label><select id="policyId" name="policyId" required>${policies.map(p => option(p.id,`Department assessment policy · approved ${displayDate(p.approved_at)}`)).join('')}</select></div><fieldset class="wide faculty-options"><legend>Faculty evaluators</legend>${w.faculty.map(f => `<label class="check"><input type="checkbox" name="facultyIds" value="${f.id}" >${esc(f.name)}</label>`).join('')}<p class="hint">Choose enough eligible evaluators to satisfy the selected policy’s quorum.</p></fieldset>${reason()}<div class="actions wide"><button class="primary" type="submit">Assign review →</button></div></form>` : empty('No projects to assign','A student can register a project first.')}</section>`;
  } else {
    form = proposalForm(state,esc,selectedOffering,displayOffering);
  }
  return heading(w.access.admin ? 'DEPARTMENT OVERSIGHT' : 'BUILD WITH PURPOSE',w.access.admin ? 'Projects & assignments' : 'My projects','Follow proposals, assignments and academic progress in one place.')+`<div class="grid"><section class="panel"><div class="panel-title"><h2>${w.access.admin ? 'Department projects' : 'Your project proposals'}</h2>${badge(state.projects.length+' projects','green')}</div>${projectCards()}</section><aside>${form}</aside></div>`;
}

function departmentView() {
 const academic=state.academic?.policies[0];
 return heading('DEPARTMENT GOVERNANCE','Evaluation policy','Set approved evaluation rules. Admin maintains offering schedules and operational configuration.')+(state.role==='HOD'?`<section class="panel"><div class="panel-title"><h2>Academic policy</h2>${badge('Version '+(academic?.version_no || '—'),'green')}</div><p class="muted">New versions apply when explicitly bound to a review.</p><form data-form="academic-policy" class="form-grid section-spacer">${field('Evaluator quorum','quorum',academic?.evaluator_quorum ?? '','number','min="1" required')}<div><label for="aggregation">Aggregation strategy</label><select id="aggregation" name="aggregation" required><option value="">Choose the approved calculation</option>${['MEAN','MIN','MAX','WEIGHTED_MEAN'].map(v => option(v,({MEAN:'Average',MIN:'Lowest',MAX:'Highest',WEIGHTED_MEAN:'Weighted average'})[v],academic?.aggregation)).join('')}</select></div><fieldset class="wide faculty-options"><legend>Evaluator weights · weighted mean only</legend>${state.workspace.faculty.map(f => field(f.name,'weight-'+f.id,academic?.evaluator_weights?.[f.id] ?? '','number','min="0.01" step="0.01"')).join('')}<p class="hint">Leave unassigned evaluators blank. Each selected evaluator needs a positive weight.</p></fieldset>${reason()}<div class="actions wide"><button class="primary" type="submit">Create academic version</button></div></form></section>`:'<section class="panel"><h2>Approved evaluation rules</h2><p>Your appointed responsibilities determine which reviews you may coordinate. Policy decisions remain with the HOD.</p></section>');
}

function queueStage(reviewId){
  return state.courseEvaluationQueue?.projects.flatMap(p=>p.stages).find(s=>s.reviewId===reviewId);
}
function canMarkHere(reviewId,assessmentId){
  return state.role==='Coordinator'&&state.view==='courses'&&state.courseReviewId===reviewId&&
    state.workspace.roleChoices?.includes('Faculty')&&assessmentId&&queueStage(reviewId)?.ownAssessmentId===assessmentId;
}
function evaluatorContext(){
  return {alias:state.alias,role:state.role==='Coordinator'?'Faculty':state.role,signal:controller.signal};
}
function evaluationView(student = false, scoped = false) {
  const reviews = state.workspace.reviews, r = currentReview();
  const header = scoped && r ? heading('ASSESSMENT',r.label,`${r.projectTitle} · Round ${r.round||1}`) : heading(student ? 'YOUR ACADEMIC RECORD' : 'RUBRIC-BASED & AUDITED',student ? 'My results' : 'Evaluations & publication',student ? 'Only your own released totals are shown. Prior result versions remain preserved.' : 'Save draft marks, finalize the assessment, and publish through the pinned policy.');
  if (!r) return header+`<section class="panel">${empty('No assigned review yet','A department administrator can assign a review to a registered project.')}</section>`;
  const selector = scoped ? '' : `<label for="reviewSelect">Project review</label><select id="reviewSelect" class="review-select">${reviews.map(v => option(v.id,`${v.projectTitle} · ${v.label}${v.round?' · Round '+v.round:''}`,state.reviewId)).join('')}</select>`;
  const assessment = r.assessments?.find(a => a.facultyId === state.workspace.actor.id);
  const reviewProject=state.documents?.projects.find(p=>p.id===r.projectId);
  const courseFinal=uiContext.courseManagement&&reviewProject?.overallFinalPublished;
  const stage=scoped?queueStage(r.id):null;
  const exceptional=false; // Published overall results do not reopen recorded stage marks.
  const markHere=assessment&&canMarkHere(r.id,assessment.id);
  let editor = '';
  if (assessment && (state.role==='Faculty'||markHere) && !student) {
    const inputs = r.criteria.flatMap(c => (c.scope === 'TEAM' ? [null] : r.roster).map(member => {
      const studentId = member?.id || null, saved = assessment.scores.find(s => s.criterionId === c.id && s.studentId === studentId);
      return `<div class="rubric-row"><div><strong>${esc(c.label)}</strong><small>${c.scope === 'TEAM' ? 'Team contribution' : esc(member.name)} · maximum ${esc(c.maximum)}</small></div><input aria-label="${esc(c.label+' '+(member?.name || 'team'))}" name="mark" type="number" min="0" max="${esc(c.maximum)}" step="0.01" required value="${esc(saved?.marks ?? '')}" data-criterion="${c.id}" data-student="${studentId || ''}"></div>`;
    })).join('');
    const finalized = assessment.state === 'FINALIZED';
    const savedMarks = finalized ? r.criteria.flatMap(c => (c.scope === 'TEAM' ? [null] : r.roster).map(member => {
      const score = assessment.scores.find(s => s.criterionId === c.id && s.studentId === (member?.id || null));
      return `<div class="row"><span>${esc(c.label)} · ${esc(member?.name || 'Team')}</span><strong>${esc(score?.marks ?? '—')} / ${esc(c.maximum)}</strong></div>`;
    })).join('') : '';
    editor = `<section class="panel"><div class="panel-title"><div><h2>${finalized ? 'Your finalized evaluation' : 'Your draft evaluation'}</h2><p class="muted">${esc(r.projectTitle)} · ${esc(assessment.facultyName)}</p></div>${badge(assessment.state,finalized ? 'green' : 'amber')}</div>${savedMarks}${finalized&&courseFinal&&!exceptional?'<p class="notice">Overall results are published. Recorded stage marks are unchanged; the assigned Project Guide can request a direct overall correction in Project work.</p>':`${finalized?`<details class="secondary-task"><summary>${exceptional?'Propose exceptional stage evidence':'Request correction'}</summary>${exceptional?'<p class="notice">The published overall result stays in force. The proposed stage evidence needs separate authorization before it can support an exceptional overall revision.</p>':''}`:''}<form data-form="marks">${inputs}<div class="section-spacer">${reason()}</div><div class="actions"><button class="primary" type="submit">${finalized ? (uiContext.courseManagement?(exceptional?'Submit exceptional proposal':'Submit revised scores'):r.state === 'PUBLISHED' ? 'Publish correction' : 'Save finalized revision') : 'Save draft marks'}</button>${!finalized ? button('Finalize assessment','finalize',`type="button" data-id="${assessment.id}" data-version="${assessment.version}" ${assessment.scores.length < r.criteria.reduce((n,c) => n+(c.scope === 'TEAM' ? 1 : r.roster.length),0) ? 'disabled' : ''}`,'secondary') : ''}</div><p class="hint">${finalized ? (exceptional?'The responsible offering Coordinator reviews this exact exceptional change; no separate independent authorizer is required.':uiContext.courseManagement?'Submit revised scores for these criteria. Your course coordinator must authorize an ordinary correction. If you are the effective coordinator for this offering with correction responsibility, the service can apply your own correction immediately before overall publication. Previous marks stay in history.':'Only the original evaluator may revise this historical contribution. Earlier versions remain preserved.') : 'Save all marks before finalizing. Finalization locks the assessment; later corrections require specific authorization.'}</p></form>${finalized?'</details>':''}`}</section>`;
  } else if (state.workspace.access.admin && !student) {
    editor = `<section class="panel"><div class="panel-title"><h2>Evaluation oversight</h2>${badge(r.state,r.state === 'PUBLISHED' ? 'green' : 'amber')}</div>${r.assessments.map(a => `<div class="row"><div><h3>${esc(a.facultyName)}</h3><p class="muted">Assigned faculty evaluator</p></div>${badge(a.state,a.state === 'FINALIZED' ? 'green' : 'amber')}</div>`).join('')}<div class="notice">Publication requires the pinned policy’s quorum and complete finalized source marks. A roster correction does not award marks automatically.</div>${scoped?'':`<form data-form="publish">${reason()}<div class="actions"><button class="primary" type="submit">Publish stage results</button></div></form>`}</section>`;
  }
  const publishForm=`<form data-form="publish">${reason()}<div class="actions"><button class="primary" type="submit">Publish stage results</button></div></form>`;
  if(scoped){
    const blocker=stage?.blocker||(stage?'':'Publication readiness is unavailable for this assessment.');
    editor+=`<section class="panel"><h2>Stage publication</h2><p>${esc(blocker||'Finalized sources meet the pinned publication checks. The service will recheck at publication.')}</p>${blocker&&state.courseSection==='evaluation'?'':blocker&&stage?'':publishForm}</section>`;
  }
  if(uiContext.courseManagement&&(state.role==='Faculty'||markHere))editor+=`<section class="panel"><h2>Your correction requests</h2>${(markHere?(state.courseDetail?.corrections||[]).filter(c=>c.requester_id===state.workspace.actor.id):state.courseNotifications?.corrections||[]).filter(c=>c.review_id===r.id).map(c=>`<article class="project-card"><p>${c.applied?'Applied and preserved in result history':c.approved===true?'Authorized specific change':c.approved===false?'Declined':'Awaiting appointed coordinator'}</p>${(!courseFinal&&!c.exceptional_result_id||exceptional&&c.exceptional_result_id)&&c.approved&&!c.applied?`<button class="secondary" data-action="apply-course-correction" data-exceptional="${c.exceptional_result_id?'yes':'no'}" data-id="${c.id}" data-offering="${c.offering_id}">Apply authorized correction</button>`:''}</article>`).join('')||'<p>No correction has been requested.</p>'}</section>`;
  if(scoped){
    editor+=`<details class="panel"><summary>Pinned rubric criteria</summary><ul>${r.criteria.map(c=>`<li>${esc(c.label)} · ${esc(c.scope==='TEAM'?'Team':'Individual')} · maximum ${esc(c.maximum)}</li>`).join('')}</ul></details>`;
    editor+=stageCorrectionPanel(state,stage,r,esc);
  }
  const releases = state.result?.results || [];
  const results = `<section class="panel"><div class="panel-title"><div><h2>Published result history</h2><p class="muted">Newest versions appear last; source records remain immutable.</p></div>${badge(releases.length+' versions','green')}</div>${releases.length ? releases.map(v => `<article class="project-card"><div class="project-top"><h3>Result version ${v.version}</h3>${badge('Published','green')}</div><p class="muted">Published ${displayDate(v.createdAt)}</p><div class="result-list">${Object.entries(v.results).map(([id,value]) => `<div class="result-item"><span>${student ? 'Your total' : esc(r.roster.find(m => m.id === id)?.name || 'Historical roster member')}</span><span class="result-number">${esc(value)}</span></div>`).join('')}</div><p class="hint">${v.supersedesId ? 'Supersedes the previous result while preserving it.' : 'First result under the pinned academic policy.'}</p></article>`).join('') : empty('No result published yet','Finalized evaluations must satisfy the configured policy before publication.')}</section>`;
  const hasTeam=r.criteria?.some(c=>c.scope==='TEAM'),hasIndividual=r.criteria?.some(c=>c.scope==='STUDENT');
  const mode=hasTeam&&hasIndividual?'Combined marking':hasIndividual?'Individual marking':hasTeam?'Team marking':'';
  const evidenceLink=personalRole()?button('← Project evidence','open-project',`data-project="${esc(r.projectId)}"`,'secondary'):'';
  if(mode&&state.role==='Faculty')editor=`<p class="hint">Pinned rubric · ${mode}</p>`+editor;
  return evidenceLink+header+selector+reviewPlanning(r,state,esc,localDate)+`<div class="grid"><div>${editor || ''}${state.workspace.access.admin?reviewManagement(r,state,esc,displayDate):''}${student ? results : ''}</div><aside>${student ? '<section class="panel"><h2>A preserved academic history</h2><p class="muted">Corrections append new result versions. Your original totals, frozen rosters and evaluator attribution remain recorded.</p></section>' : results}</aside></div>`;
}

function auditView(){return heading('ACTIVITY','Your academic activity','Changes retain their actor, date and history.')+`<section class="panel"><h2>Recent activity</h2>${state.workspace.audit.map(a=>`<article class="project-card"><h3>${esc(natural(a.action))}</h3><p>${displayDate(a.occurred_at)}</p><p>${esc(a.metadata?.reason||a.metadata?.input?.reason||a.metadata?.request?.reason||'Recorded in the academic audit history.')}</p></article>`).join('')||empty('No activity in this workspace yet','Completed actions will appear here.')}</section>`;}

function referencePanel(){
 // Keep research reference available in specific administrative and assignment contexts.
 if(state.role==='Admin'&&state.view==='records')return facultyReferencePanel(state,uiContext,esc);
 if(state.role==='HOD'&&state.view==='department')return facultyReferencePanel(state,uiContext,esc);
 if(state.view==='courses'&&state.role==='Coordinator'&&['appointments','assignments'].includes(state.courseSection)&&state.courses?.offerings.some(o=>o.id===state.courseId))return facultyReferencePanel(state,uiContext,esc,state.courseId);
 return '';
}
function courseAssessment(){
  const course=state.courses?.offerings.find(o=>o.id===state.courseId);
  if(!course)return courseManagement(state,esc,displayDate,localDate);
  const review=currentReview();
  const section=courseReturnLabel(state.courseSection);
  return `<nav class="assessment-path" aria-label="Assessment breadcrumb"><button class="quiet" data-action="close-course">Course Management</button><span>${esc(course.label)} · ${esc(course.semester_key)} · ${esc(course.cycle_label)}</span>${review?`<span>${esc(review.projectTitle)} · ${esc(review.label)}</span>`:''}</nav>
    <button class="secondary" data-action="return-to-course">← Back to ${esc(section)}</button> <button class="quiet" data-action="course-section" data-section="deadlines">Offering deadlines</button> ${review?`<button class="quiet" data-action="assessment-evidence" data-project="${esc(review.projectId)}">Project evidence</button>`:''}`+
    (review?`<p class="hint">${assessmentSummary(review,esc,displayDate)}</p>`+evaluationView(false,true):heading('COURSE MANAGEMENT','Assessment unavailable','This assessment is outside your current offering scope or is no longer available.'));
}
function courseReturnLabel(section){
  return ({plan:'Reviews & marking',evaluation:'Project evaluation',results:'Results',overview:'Offering overview'})[section]||'offering';
}

function personalDocuments(){
  const back=button(state.role==='Student'?'← My project work':'← Assigned project work','all-documents','','secondary');
  if(state.projectId){
    const project=state.documents?.projects.find(p=>p.id===state.projectId);
    const offering=state.offerings.find(o=>o.id===project?.offeringId);
    return `<nav class="assessment-path" aria-label="Project context">${back}${offering?`<span>${esc(displayOffering(offering))}</span>`:''}</nav>`+
      documentsUI({state,esc,displayDate,localDate,embedded:true});
  }
  const result=state.workListing;
  const offeringFilter=state.role==='Student'?`<label>Academic offering<select name="offering"><option value="">All eligible offerings</option>${state.offerings.map(o=>option(o.id,displayOffering(o),state.workOffering)).join('')}</select></label>`:'';
  const search=`<form class="form-grid" data-form="work-search"><label>Search projects or teams<input name="q" type="search" maxlength="120" value="${esc(state.workQuery||'')}"></label>${offeringFilter}<button class="primary">Search</button></form>`;
  const header=heading('PROJECT WORK',state.role==='HOD'?'Department project evidence':state.role==='Faculty'?'Assigned project work':'My project work',
    state.role==='Faculty'?'Open a project to review submitted evidence or work on an assigned assessment.':'Open a project to submit work, read feedback or review published results.');
  if(!result)return header+search+`<p role="status">${esc(state.documentError||'Project work could not be loaded.')}</p>`;
  const first=(result.page-1)*result.pageSize;
  return header+search+`<nav class="actions" aria-label="Project work pages">
    <button class="secondary" data-action="work-page" data-page="${result.page-1}" ${result.page===1?'disabled':''}>Previous page</button>
    <p role="status">${result.total?`Showing ${first+1}–${first+result.projects.length} of ${result.total} projects`:'No matching projects'}</p>
    <button class="secondary" data-action="work-page" data-page="${result.page+1}" ${first+result.projects.length>=result.total?'disabled':''}>Next page</button></nav>`+
    result.projects.map(p=>`<article class="panel"><h2>${esc(p.title)}</h2><p>${esc(p.team)} · Guide: ${esc(p.guide||'Unassigned')} · ${esc(natural(p.submissionStatus||'NO_SUBMISSION'))}</p>
      ${button('Open project','open-project',`data-project="${esc(p.id)}"`,'secondary')}</article>`).join('');
}

function content() { if(state.role==='Coordinator'&&state.view==='courses'&&state.courseReviewId)return courseAssessment(); return ({notifications:()=>notificationPanel(state,esc,displayDate),courses:()=>courseManagement(state,esc,displayDate,localDate),setup:()=>setupUI(state,esc),records:()=>departmentRecords(state,esc),documents:()=>personalRole()||state.role==='HOD'?personalDocuments():documentsUI({state,esc,displayDate,localDate}),overview, enrollment,teams:teamView,projects:projectsView,history:()=>heading('ACADEMIC RECORDS','Project history','Your authorized project records across offerings, including paused and archived offerings.')+`<section class="panel">${projectCards()}</section>`,department:departmentView,evaluations:() => evaluationView(),results:() => evaluationView(true),audit:auditView}[state.view] || overview)()+referencePanel(); }
function instructionAuthority(values){return {source:'EXTERNAL_INSTRUCTION',hodMandateId:values.hodMandateId,reference:values.instructionReference||'',confirmed:values.instructionConfirmed==='on'};}
async function recordConfiguration(kind,configuration,values){return api(staffBase()+'/setup','POST',{action:'RECORD',kind,configuration,reason:values.reason||'',authority:{source:'EXTERNAL_INSTRUCTION',hodMandateId:values.hodMandateId,reference:values.instructionReference||'',confirmed:values.instructionConfirmed==='on'}});}
function updateSynopsisControls(form){if(!form)return;const required=form.elements.requiresSynopsis?.checked;form.querySelectorAll('[data-synopsis-field]').forEach(block=>{block.hidden=!required;block.querySelectorAll('input,select').forEach(control=>{control.disabled=!required;if(control.type!=='checkbox')control.required=required;});});}
function keepActiveNavigationVisible() {
  document.querySelectorAll('.nav, .course-tabs').forEach(nav=>{
    const active=$('[aria-current=page]',nav);
    if(!active||nav.scrollWidth<=nav.clientWidth)return;
    const rail=nav.getBoundingClientRect(), item=active.getBoundingClientRect();
    if(item.left<rail.left||item.right>rail.right)nav.scrollLeft+=item.left-rail.left-8;
  });
}
window.addEventListener('resize',keepActiveNavigationVisible);

function afterRender() {
  keepActiveNavigationVisible();
  document.querySelectorAll('[data-progress]').forEach(el=>{el.style.width=el.dataset.progress+'%';});
  if(!state.navigationPending&&state.view==='teams'&&state.workspace?.enrolled)loadTeams();
}
function fillReviewSchemes() {
 const form=document.querySelector('form[data-form="assign"]');if(!form)return;
 let box=form.querySelector('[data-scheme-choice]');if(!box){box=document.createElement('div');box.dataset.schemeChoice='yes';box.className='wide';form.querySelector('fieldset').before(box);}
 const choices=(state.setup?.reviewChoices||[]).filter(c=>c.projectId===form.elements.projectId.value);
 box.innerHTML=`<label for="reviewScheme">Applicable approved review stage and rubric</label><select name="reviewScheme" id="reviewScheme" required>${choices.map(c=>`<option value="${c.schemeVersionId}:${c.schemeModeId}">${esc(c.label)} · ${esc(({TEAM:'Team marks',INDIVIDUAL:'Individual marks',COMBINED:'Team and individual marks'})[c.mode]||c.mode)}</option>`).join('')}</select>${choices.length?'':'<p>No active approved review rubric is available for this project.</p>'}`;
 form.querySelector('[type=submit]').disabled=!choices.length;
}
function show() {
  render(); afterRender();
  if(state.intakeDraft) $('form[data-form=intake-file]')?.closest('details')?.setAttribute('open','');
  if(state.role==='Admin')document.querySelectorAll('form[data-form^=setup-],form[data-form^=policy-],form[data-form=configure-instruction]').forEach(form=>(form.querySelector('button.primary')||form.querySelector('button.secondary')).before(document.createRange().createContextualFragment(instructionFields(state,esc))));
  if(state.role==='Coordinator'){const form=document.querySelector('form[data-form=academic-policy]');if(form){const note=document.createElement('p');note.className='notice';note.textContent='Academic assessment rules are authorized by the HOD. This workspace coordinates assigned reviews.';form.replaceWith(note);}}
  if((state.view==='projects'||state.view==='documents'&&!personalRole())&&document.querySelector('[data-search-record]')){
   const filter=document.createElement('section');filter.className='panel record-filter';filter.innerHTML='<label for="projectSearch">Find a project<input type="search" id="projectSearch" placeholder="Search project titles"></label><label for="reviewFilter">Synopsis review<select id="reviewFilter"><option value="">All review states</option><option value="DRAFT">Not submitted</option><option value="SUBMITTED">Awaiting review</option><option value="CHANGES_REQUESTED">Changes requested</option><option value="APPROVED">Approved</option></select></label><p id="searchEmpty" hidden>No projects match these filters.</p>';$('#main .heading')?.after(filter);
  }
  if(state.role==='Admin'&&state.editOfferingId){
   const offering=state.management?.offerings.find(o=>o.id===state.editOfferingId),form=document.querySelector('form[data-form=configure-instruction]');
   if(offering?.configuration&&form){for(const [key,value] of Object.entries(offering.configuration)){const control=form.elements.namedItem(key);if(!control)continue;if(control.type==='checkbox')control.checked=value;else control.value=control.type==='datetime-local'?localDate(value):value;}form.elements.requiresSynopsis.checked=offering.configuration.requiresSynopsis!==false;form.querySelector('button.primary').textContent='Save offering changes';const task=form.closest('details');task.open=true;task.querySelector('summary').textContent='Edit '+offering.label;form.insertAdjacentHTML('beforeend','<button type="button" class="quiet" data-action="cancel-offering-edit">Cancel editing</button>');}
  }
  if(state.role==='Admin'&&state.reviseSetupId){
   const request=state.setup?.requests.find(r=>r.id===state.reviseSetupId),forms={PROJECT_POLICY:'policy-project',TEAM_POLICY:'policy-team',REVIEW_BLUEPRINT:'policy-reviews'},form=request&&document.querySelector(`form[data-form="${forms[request.kind]}"]`);
   if(form){const cfg=request.configuration;for(const [key,value] of Object.entries(cfg)){const control=form.elements.namedItem(key);if(!control)continue;if(control.type==='checkbox')control.checked=value;else control.value=value??'';}
    if(cfg.stages){form.querySelector('.stages-editor').innerHTML=cfg.stages.map(()=>stageEditor()).join('');[...form.querySelectorAll('.stage-editor')].forEach((stage,index)=>{const data=cfg.stages[index];stage.querySelector('[name=stageCode]').value=data.code;stage.querySelector('[name=stageLabel]').value=data.label;stage.querySelector('[name=stageMode]').value=data.mode;stage.querySelector('.criteria-editor').innerHTML=data.criteria.map(()=>criterionRow()).join('');[...stage.querySelectorAll('.criterion-editor')].forEach((criterion,i)=>{criterion.querySelector('[name=criterionLabel]').value=data.criteria[i].label;criterion.querySelector('[name=criterionScope]').value=data.criteria[i].scope;criterion.querySelector('[name=criterionMaximum]').value=data.criteria[i].maximum;});});}
    form.closest('details').open=true;form.querySelector('button.primary').textContent='Save revised approved configuration';form.scrollIntoView({block:'start'});
   }
  }
  updateSynopsisControls(document.querySelector('form[data-form=configure-instruction]'));
  fillReviewSchemes();
  if(state.view==='department'&&state.staff?.results.length){const section=document.createElement('section');section.className='panel';section.innerHTML=`<label for="staffOfferingChoice">Offering to configure</label><select id="staffOfferingChoice">${state.staff.results.map(o=>option(o.id,academicText(o.curriculumCode)+' · '+academicText(o.semester),staffOffering()?.id)).join('')}</select>`;$('#main .heading')?.after(section);}
  const classification=$('#projectType');
  if(classification) {
    const types=state.offerings.find(o=>o.id===selectedOffering())?.projectTypes||[];
    classification.innerHTML=types.map(t=>`<option value="${esc(t)}">${esc(t)} · configured offering policy</option>`).join('');
    classification.required=true;
    if(!types.length) { classification.innerHTML='<option value="">No open configured registration class</option>'; classification.closest('form').querySelector('[type=submit]').disabled=true; }
  }
  if (['teams'].includes(state.view) && state.workspace?.access.student && state.offerings.length) {
    const section=document.createElement('section'); section.className='panel';
    section.innerHTML=`<label for="offeringChoice">Select eligible departmental offering</label><select id="offeringChoice">${state.offerings.map(o=>`<option value="${o.id}" ${o.id===selectedOffering()?'selected':''}>${esc(o.label)} · ${esc(academicText(o.semester))} · ${esc(academicText(o.cycle.code))}</option>`).join('')}</select>`;
    $('#main .heading')?.after(section);
  }
}

async function work(fn, message, refresh=load) {
  if (state.busy) return;
  const generation = state.generation;
  state.busy = true; state.error = ''; clearToast();
  if(state.navigationPending) show();
  else {
    const main=$('#main');
    main?.classList.add('loading');
    main?.setAttribute('aria-busy','true');
    main?.insertAdjacentHTML('afterbegin','<p class="request-status" role="status">Working on your request…</p>');
  }
  try {
    await fn();
    if(generation !== state.generation)return;
    if(!state.navigationPending)state.studentMetadataValidUntil=0;
    await refresh({reuseWorkspace:state.navigationPending&&!state.forceFullRefresh});
    if(message && generation===state.generation)toast(typeof message==='function'?message():message);
  }
  catch (error) {
    if (error.name !== 'AbortError' && generation === state.generation) {
      state.error=state.workspace?error.message:workspaceOpenError(error,uiContext.demo);
    }
  }
  finally { if (generation === state.generation) { state.busy = false; state.navigationPending=false; state.forceFullRefresh=false; show(); } }
}

function confirmChange(message, label) {
  const dialog = $('#action-confirmation');
  if (dialog.open) return Promise.resolve(false);
  $('#confirmation-message').textContent = message;
  $('button[value=confirm]', dialog).textContent = label;
  dialog.returnValue = '';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), {once:true});
    dialog.showModal();
  });
}

function focusHeading(selector) {
  const heading = $(selector);
  if (heading) {
    heading.tabIndex = -1;
    heading.focus();
  }
}

document.addEventListener('click', async event => {
  const nav = event.target.closest('[data-go]');
  if (nav) {
    // Read-only navigation can supersede an in-flight navigation, but not a write.
    if(nav.dataset.go===state.view)return;
    if(state.busy&&!state.navigationPending)return;
    if(state.navigationPending){
      controller.abort();controller=new AbortController();state.generation++;state.busy=false;
    }
    state.view=nav.dataset.go;state.openFromHistory=false;state.projectId=null;state.courseReviewId=null;
    if(state.role==='Coordinator'||departmentRole())writeCourseLocation();
    if(personalRole())writeWorkLocation();
    state.navigationPending=true;
    await work(async () => {},'');
    focusHeading('#main h1');
    return;
  }
  const target = event.target.closest('[data-action]'); if (!target) return;
  const action = target.dataset.action;
  if(['open-department-record','close-department-record'].includes(action)&&!state.busy){
    state.departmentRecordId=target.dataset.id||null;
    writeCourseLocation();
    await work(async()=>{},'');
    focusHeading('#main h1');
    return;
  }
  if(action==='export-intake-issues'){
    const issues=state.intakeDraft?.preview?.issues;
    if(!issues?.length)return;
    const report=['Record,Issue',...issues.map(issue=>`${Number(issue.row)},"${issue.message.replaceAll('"','""')}"`)].join('\r\n');
    const url=URL.createObjectURL(new Blob([report],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');
    link.href=url;link.download='department-import-corrections.csv';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    return;
  }
  if(action==='finalize'&&!await confirmChange('Later changes require a correction.','Finalize evaluation'))return;
  if(action==='add-course-stage'){target.closest('form').querySelector('.course-stages').insertAdjacentHTML('beforeend',courseStageEditor(state.courseDetail,esc));return;}
  if(action==='remove-course-stage'){target.closest('.course-stage').remove();return;}
  if(action==='edit-course-deadline'){state.editCourseDeadline=target.dataset.id;show();return;}
  if(action==='cancel-course-deadline'){state.editCourseDeadline=null;show();return;}
  if(action==='edit-requirement'){state.editRequirementId=target.dataset.id;state.view='setup';show();return;}
  if(action==='cancel-requirement-edit'){state.editRequirementId=null;show();return;}
  if(action==='revise-setup'){state.reviseSetupId=target.dataset.id;state.view='setup';show();return;}
  if(action==='offering-settings'){state.staffOfferingId=target.dataset.id;state.view='documents';writeCourseLocation();await work(async()=>{},'');focusHeading('#main h1');return;}
  if(action==='all-offering-settings'){state.staffOfferingId=null;writeCourseLocation();show();focusHeading('#main h1');return;}
  if(action==='edit-offering'){state.editOfferingId=target.dataset.id;show();$('.offering-task[open] summary')?.focus();return;}
  if(action==='cancel-offering-edit'){state.editOfferingId=null;show();return;}
  if(action==='add-stage'){target.closest('form').querySelector('.stages-editor').insertAdjacentHTML('beforeend',stageEditor());return;}
  if(action==='add-criterion'){target.closest('.stage-editor').querySelector('.criteria-editor').insertAdjacentHTML('beforeend',criterionRow());return;}
  if(action==='choose-role'){await switchRole(target.dataset.role);return;}
  if(action==='edit-proposal'){state.proposalDraft=null;show();return;}
  if(action==='all-documents'&&!personalRole()&&state.role!=='HOD'){state.projectId=null;show();return;}
  if(action==='all-documents')state.projectId=null;
  if(action==='work-page')state.workPage=Number(target.dataset.page);
  if (action === 'close-document') { $('#document-preview')?.close(); return; }
  if (['preview-document','download-document'].includes(action)) {
    try {
      const context={alias:state.alias,role:state.role,generation:state.generation,signal:controller.signal};
      const page=Number(target.dataset.page||1);
      const response=await fetch(`/api/v1/document-versions/${target.dataset.id}/content${action==='download-document'?'?download=1':'?preview=1&page='+page}`,{headers:{...reviewerHeaders(context.alias),...(context.role?{'X-Smartpro-Role':context.role}:{})},signal:context.signal});
      if(!response.ok) throw new Error((await response.json()).detail?.message||'Document access denied');
      const blob=await response.blob(); if(context.generation!==state.generation) return;
      if(action==='download-document') {
        const url=URL.createObjectURL(blob), link=document.createElement('a');
        link.href=url;link.download=target.dataset.filename||'synopsis.pdf';link.click();
        setTimeout(()=>URL.revokeObjectURL(url),1000);
      } else {
        const box=$('#document-preview'),pages=Number(response.headers.get('X-Document-Pages'));
        if(!box)return;
        if(previewURL)URL.revokeObjectURL(previewURL);
        previewURL=URL.createObjectURL(blob);
        $('img',box).src=previewURL;
        $('[data-action=download-document]',box).dataset.id=target.dataset.id;
        $('#preview-pages').innerHTML=`<span role="status">Page ${page} of ${pages}</span>${page>1?`<button class="secondary" data-action="preview-document" data-id="${target.dataset.id}" data-page="${page-1}">Previous page</button>`:''}${page<pages?`<button class="secondary" data-action="preview-document" data-id="${target.dataset.id}" data-page="${page+1}">Next page</button>`:''}`;
        if(!box.open){
          box.onclose=()=>{
            if(previewURL)URL.revokeObjectURL(previewURL);
            previewURL=null;
            if(target.isConnected)target.focus();
          };
          box.showModal();
        } else {
          box.querySelector('[data-action="close-document"]').focus();
        }
      }
    } catch(error) { if(error.name!=='AbortError') {state.error=error.message;show();} }
    return;
  }
  if(['end-assignment','revoke-operation','revoke-faculty-delegation'].includes(action)&&!target.dataset.confirmed){target.insertAdjacentHTML('afterend',`<button class="danger" data-action="${action}" data-id="${target.dataset.id}" data-confirmed="yes">Confirm and preserve history</button>`);target.disabled=true;return;}
  if(action==='revoke-coordinator'&&!target.dataset.confirmed){target.insertAdjacentHTML('afterend',`<button class="danger" data-action="revoke-coordinator" data-id="${target.dataset.id}" data-confirmed="yes">Confirm revocation and end delegated access</button>`);target.disabled=true;return;}
  if(action==='approve-setup'&&!target.dataset.confirmed){const article=target.closest('article');article.querySelector('details').open=true;target.insertAdjacentHTML('afterend',`<button class="primary" data-action="approve-setup" data-id="${target.dataset.id}" data-confirmed="yes">Confirm academic authorization</button>`);target.disabled=true;return;}
  if (action === 'logout' && uiContext.reviewerAuth) {
    const response=await fetch('/reviewer/logout',{method:'POST',headers:reviewerHeaders(state.alias)});
    if(!response.ok){state.error='Sign-out failed. Please try again.';show();return;}
    sessionStorage.removeItem('smartpro.identity');
    location.assign('/reviewer/login');
    return;
  }
  if (action === 'logout' || action === 'login') {
    state.intakeDraft=null;state.intakeOutcome=null;state.departmentRecordId=null;state.candidateQuery='';state.candidatePage=1;state.targetQuery='';state.targetPage=1;state.recordScope='directory';state.departmentOfferingSearch='';state.departmentAvailability='ALL';state.departmentOfferingPage=1;state.appointmentPage=1;state.leadershipPage=1;state.leadershipSearch='';state.intakeQuery='';state.intakeKind='STUDENT';state.intakePage=1;state.batchPage=1;state.workQuery='';state.workPage=1;state.workOffering='';
    if(previewURL) URL.revokeObjectURL(previewURL); state.offeringId=null;state.projectId=null;state.staffOfferingId=null;state.role=null;state.proposalDraft=null;
    controller.abort(); controller = new AbortController(); state.generation++; state.workspace = null; state.busy = false; state.error = '';
    state.alias = action === 'login' ? target.dataset.alias : null; state.view = 'overview'; state.reviewId = null; state.courseReviewId=null; writeCourseLocation(true);writeWorkLocation(true);
    clearToast();
    if (state.alias) {
      sessionStorage.setItem('smartpro.identity',state.alias);
      sessionStorage.removeItem('smartpro.role.'+state.alias);
      await work(async () => {},'');
    }
    else { sessionStorage.removeItem('smartpro.identity'); show(); }
    return;
  }
  if(state.busy)return;
  if(action==='return-to-course')state.courseReviewId=null;
  if(action==='open-course'){state.finalRevisionPageNumber=1;state.finalRevisionAnchor=null;state.queueQuery='';state.queueStatus='all';state.queuePage=1;state.courseProjectId=null;state.courseReviewId=null;state.courseId=target.dataset.id;state.appointmentPage=1;state.editCourseAppointment=null;state.courseSection=target.dataset.section||'overview';state.view='courses';}
  if(action==='close-course'){state.courseProjectId=null;state.courseReviewId=null;state.courseId=null;state.editCourseAppointment=null;}
  if(action==='queue-page')state.queuePage=Number(target.dataset.page);
   if(action==='final-revision-page')state.finalRevisionPageNumber=Number(target.dataset.page);
   if(action==='guide-correction-page')state.guideCorrectionPage=Number(target.dataset.page);
  if(action==='course-section'){state.courseReviewId=null;state.courseProjectId=null;state.courseSection=target.dataset.section;}
  if(action==='assessment-evidence'){state.courseReviewId=null;state.courseSection='evaluation';state.courseProjectId=target.dataset.project;}
  if(action==='course-project-evidence')state.courseProjectId=state.courseProjectId===target.dataset.project?null:target.dataset.project;
  if(action==='edit-course-appointment'){state.editCourseAppointment=target.dataset.id;show();return;}
  if(action==='cancel-course-appointment'){state.editCourseAppointment=null;show();return;}
  if (action === 'open-project') {state.openFromHistory=['history','notifications'].includes(state.view);if(state.projectId!==target.dataset.project){state.guideCorrectionPage=1;state.guideCorrectionAnchor=null;}state.projectId=target.dataset.project;state.view='documents';}
  if (action === 'open-review') {
    state.reviewId = target.dataset.review;
    if(state.role==='Coordinator'&&state.view==='courses'&&state.courseId){state.courseReviewId=state.reviewId;state.courseProjectId=target.dataset.project||currentReview()?.projectId||null;}
    else state.view = state.workspace.access.student ? 'results' : 'evaluations';
  }
  if(personalRole()&&['open-project','open-review','all-documents','work-page','guide-correction-page'].includes(action))writeWorkLocation();
  if((state.role==='Coordinator'||departmentRole())&&['open-review','open-course','close-course','course-section','return-to-course','course-project-evidence','assessment-evidence','queue-page','final-revision-page'].includes(action))writeCourseLocation();
  const readOnlyActions=new Set(['refresh','open-review','open-course','close-course','course-section','return-to-course','course-project-evidence','assessment-evidence','queue-page','work-page','all-documents','open-project','guide-correction-page','final-revision-page']);
  if(readOnlyActions.has(action)){state.navigationPending=true;state.forceFullRefresh=action==='refresh';}
  await work(async () => {
    if(['end-assignment','revoke-operation'].includes(action))await api(staffBase()+'/assignment-management','POST',action==='end-assignment'?{action:'END_ASSIGNMENT',assignmentId:target.dataset.id}:{action:'REVOKE_OPERATION',grantId:target.dataset.id});
    if(action==='revoke-faculty-delegation')await api(deptBase()+'/delegations/revoke','POST',{expectedRevision:state.academic.revision,grantId:target.dataset.id});
    if(action==='revoke-coordinator')await api(deptBase()+'/coordinators/revoke','POST',{expectedRevision:state.academic.revision,mandateId:target.dataset.id,reason:''});
    if(['approve-setup','apply-setup'].includes(action)) await api(staffBase()+'/setup','POST',{action:action==='approve-setup'?'APPROVE':'APPLY',requestId:target.dataset.id});
    if (action === 'configure-offering') await documentCommand('CONFIGURE',{instructionId:target.dataset.id});
    if (action === 'submit-document') await documentCommand('SUBMIT',{projectId:target.dataset.project,documentVersionId:target.dataset.id,expectedCaseVersion:Number(target.dataset.version),...(target.dataset.requirement?{requirementKey:target.dataset.requirement}:{})});
    if (action === 'enroll') await api('/api/v1/demo/enrollment','POST',{});
    if (action === 'join') await api(`/api/v1/teams/${target.dataset.id}/memberships`,'POST',{});
    if (action === 'leave') await api(`/api/v1/memberships/${target.dataset.id}/end`,'POST',{});
    if (action === 'transfer') await api(`/api/v1/memberships/${state.memberships[0].id}/transfer`,'POST',{targetTeamId:target.dataset.id});
    const courseActions={
      'apply-course-requirement':()=>({action:'APPLY_REQUIREMENT',policyId:target.dataset.id,expectedPolicyId:target.dataset.current||null}),
      'complete-course-milestone':()=>({action:'COMPLETE_MILESTONE',deadlineId:target.dataset.id,projectId:target.dataset.project}),

    };
    if(courseActions[action])await api(`/api/v1/courses/offerings/${target.dataset.offering}/commands`,'POST',courseActions[action]());
    if(action==='apply-course-correction')await api(`/api/v1/courses/offerings/${target.dataset.offering}/commands`,'POST',{action:target.dataset.exceptional==='yes'?'APPLY_EXCEPTIONAL_STAGE_CORRECTION':'APPLY_CORRECTION',requestId:target.dataset.id},evaluatorContext());
    if (action === 'finalize'){
      if(state.role==='Coordinator'&&!canMarkHere(state.reviewId,target.dataset.id))throw new Error('This assessment is not assigned to you.');
      await api(deptBase()+`/assessments/${target.dataset.id}/finalize`,'POST',{expectedAssessmentVersion:Number(target.dataset.version),reason:''},evaluatorContext());
    }
  }, ['refresh','open-review','open-course','close-course','course-section','return-to-course','course-project-evidence','assessment-evidence','queue-page','work-page','all-documents','open-project','guide-correction-page','final-revision-page'].includes(action) ? '' : 'Change saved with audit history');
  if (['open-review','open-course','close-course','course-section','return-to-course','course-project-evidence','assessment-evidence','queue-page','work-page','all-documents','open-project','guide-correction-page','final-revision-page'].includes(action)) focusHeading(action==='course-section'?'#main .course-header + .panel h2, #main .course-header + .heading h1':'#main h1, #main .panel h2');
});

document.addEventListener('change', async event => {
  if(event.target.name==='requiresSynopsis'){updateSynopsisControls(event.target.form);return;}
  if(event.target.id==='activeRole'){await switchRole(event.target.value);return;}
  if(event.target.id==='staffOfferingChoice'){state.staffOfferingId=event.target.value;show();return;}
  if(event.target.id==='projectId')fillReviewSchemes();
  if(event.target.id==='offeringChoice') {controller.abort();controller=new AbortController();state.generation++;state.busy=false;state.offeringId=event.target.value;state.workPage=1;state.proposalDraft=null;state.projectId=null;if(personalRole())writeWorkLocation();state.projects=[];state.memberships=[];state.documents=null;show();await work(async()=>{},'');}
  if (event.target.id === 'reviewSelect') { state.reviewId = event.target.value; if(personalRole())writeWorkLocation(); state.navigationPending=true; await work(async () => {},''); }
});
function filterProjects(){const term=($('#projectSearch')?.value||'').toLowerCase(),status=$('#reviewFilter')?.value||'';let count=0;document.querySelectorAll('[data-search-record]').forEach(record=>{record.hidden=!record.dataset.searchRecord.toLowerCase().includes(term)||(status&&record.dataset.reviewStatus!==status);if(!record.hidden)count++;});if($('#searchEmpty'))$('#searchEmpty').hidden=count>0;}
document.addEventListener('change',event=>{if(event.target.id==='courseFramework'){state.selectedCourseFramework=event.target.value;show();}if(event.target.id==='reviewFilter')filterProjects();});
document.addEventListener('input', event => { if(event.target.id==='projectSearch')filterProjects(); if (event.target.name === 'mark') { const finalize = $('[data-action="finalize"]'); if (finalize) { finalize.disabled = true; finalize.title = 'Save the edited marks before finalizing'; } } });
document.addEventListener('submit', async event => {
  const form = event.target.closest('[data-form]'); if (!form) return; event.preventDefault();
  const values = Object.fromEntries(new FormData(form)), type = form.dataset.form;
  const leadershipAction=form.dataset.leadership;
  if(leadershipAction==='RESIGN_HOD'&&!await confirmChange('Your HOD term will end. A department Admin can appoint the successor.','End my HOD term'))return;
  if(leadershipAction==='END_ADMIN'&&!await confirmChange('The selected Admin will lose access to department operations.','End Admin appointment'))return;
  if(type==='course-final'&&!await confirmChange('Publishing the overall result closes ordinary document revisions for this project.','Publish overall result'))return;
  if(type==='publish'&&!await confirmChange('Students will be able to see the results for this assessment stage.','Publish stage results'))return;
  if(type==='prepare-proposal'){const file=form.querySelector('input[type=file]')?.files[0];if(file&&file.size>state.proposalConfig.maxBytes){state.error='The PDF exceeds this offering’s file limit.';show();return;}state.proposalDraft={offeringId:selectedOffering(),teamId:state.memberships[0].teamId,title:values.title.trim(),description:values.description.trim(),file};show();return;}
  if(type==='department-offering-search'||type==='department-offering-page'||type==='leadership-history-search'||type==='appointment-candidate-search'){
    if(state.busy)return;
    const candidateOnly=type==='appointment-candidate-search'||form.dataset.list==='candidates';
    const previousCandidate={candidateQuery:state.candidateQuery,candidatePage:state.candidatePage};
    if(type==='appointment-candidate-search'){
      state.candidateQuery=values.q.trim();state.candidatePage=1;
    }else if(type==='leadership-history-search'){
      state.leadershipSearch=values.q.trim();state.leadershipPage=1;
    }else if(type==='department-offering-search'){
      state.departmentOfferingSearch=values.q.trim();
      state.departmentAvailability=values.availability;
      state.departmentOfferingPage=1;
    }else if(form.dataset.list==='candidates')state.candidatePage=Number(form.dataset.page);
    else if(form.dataset.list==='leadership')state.leadershipPage=Number(form.dataset.page);
    else if(form.dataset.list==='appointments'){
      state.appointmentPage=Number(form.dataset.page);
      state.editCourseAppointment=null;
    }else state.departmentOfferingPage=Number(form.dataset.page);
    writeCourseLocation();
    if(candidateOnly&&state.appointmentCandidates){
      const generation=state.generation;
      const context={alias:state.alias,role:state.role,signal:controller.signal};
      await work(async()=>{},'',async()=>{
        try {
          const listing=await appointmentCandidates(state.workspace.department.id,context);
          if(generation===state.generation)state.appointmentCandidates=listing;
        } catch(error) {
          if(generation===state.generation)Object.assign(state,previousCandidate);
          throw error;
        }
      });
      if(generation===state.generation)$('[data-form="appointment-candidate-search"] input')?.focus();
      return;
    }
    await work(async()=>{},'');
    focusHeading(type==='leadership-history-search'||form.dataset.list==='leadership'?'#leadership-history':form.dataset.list==='appointments'?'#appointment-history':'#department-offerings');
    return;
  }
  if(type==='department-record-search'||type==='department-record-page'||type==='intake-target-search'){
    if(state.busy)return;
    if(type==='intake-target-search'){
      state.targetQuery=values.q.trim();state.targetPage=1;
    }else if(type==='department-record-search'){
      state.targetQuery='';state.targetPage=1;
      state.recordScope=values.scope;state.intakeKind=values.kind;state.intakeQuery=values.q.trim();state.intakePage=1;
    }else if(form.dataset.list==='accounts')state.targetPage=Number(form.dataset.page);
    else if(form.dataset.list==='batches')state.batchPage=Number(form.dataset.page);
    else state.intakePage=Number(form.dataset.page);
    writeCourseLocation();
    await work(async()=>{},'');
    focusHeading(type==='intake-target-search'||form.dataset.list==='accounts'?'#intake-link':form.dataset.list==='batches'?'#intake-history':'#intake-records');
    return;
  }
  if(type==='work-search'){
    state.workQuery=values.q.trim();state.workPage=1;
    state.workOffering=values.offering||'';
    writeWorkLocation();
    await work(async()=>{},'');
    focusHeading('#main h1');
    return;
  }
  if(type==='queue-filters'){
    state.queueQuery=values.q.trim();
    state.queueStatus=values.status||'all';
    state.queuePage=1;
    state.courseProjectId=null;
    writeCourseLocation();
    await work(async()=>{},'');
    focusHeading('#queue-heading');
    return;
  }
  let outcome;
  await work(async () => {
    if(type==='faculty-identity'){
      await api(staffBase()+'/records/'+state.departmentRecordId,'POST',{...values,action:form.dataset.operation});
      return;
    }
    if(type.startsWith('intake-')){
      const send=(body,key)=>api(staffBase()+'/intake','POST',body,{alias:state.alias,role:state.role,signal:controller.signal,key});
      const sendFile=(file,fields,key)=>{
        const body=new FormData();
        body.set('file',file);
        for(const [name,value] of Object.entries(fields))body.set(name,name==='mapping'?JSON.stringify(value):value);
        return send(body,key);
      };
      if(type==='intake-file'){
        const file=values.file;
        if(!file?.size)throw new Error('Choose a CSV or XLSX export.');
        if(values.source==='FORM_EXPORT'&&values.kind!=='STUDENT')throw new Error('Form exports are for student intake.');
        const sample=await sendFile(file,{action:'HEADERS'});
        state.intakeDraft={file,source:values.source,kind:values.kind,...sample};
      }else if(type==='intake-reconcile'){
        const row=state.intakeListing.records[Number(values.recordIndex)];
        await send({action:'RECONCILE',source:row.source,kind:row.kind,identityKey:row.identity_key,
          expectedBatchId:row.batch_id,userId:values.userId,confirmed:values.confirmed==='on',...(values.evidenceReference?{evidenceReference:values.evidenceReference}:{})});
        toast('Verified account linked');
      }else{
        const draft=state.intakeDraft;
        const base={source:draft.source,kind:draft.kind};
        if(type==='intake-map'){
          const preview=await sendFile(draft.file,{action:'PREVIEW',...base,mapping:values});
          Object.assign(draft,{mapping:values,preview,key:crypto.randomUUID()});
        }else{
          const expected=draft.preview.revision?{expectedRevision:draft.preview.revision}:{};
          const imported=await sendFile(draft.file,{action:'APPLY',...base,...expected,mapping:draft.mapping,reference:values.reference,
            confirmed:values.confirmed==='on'},draft.key);
          if(imported.issues.length)draft.preview=imported;
          else { state.intakeOutcome={reference:values.reference,count:draft.preview.count,batchId:imported.batchId,counts:imported.counts}; state.intakeDraft=null; state.batchPage=1; writeCourseLocation(true); toast('Department records imported'); }
        }
      }
      return;
    }
    if(type==='leadership'){
      await api(staffBase()+'/leadership','POST',{action:leadershipAction,...values});
      if(leadershipAction==='RESIGN_HOD'){
        state.role=null;
        state.workspace=null;
        state.view='overview';
        sessionStorage.removeItem('smartpro.role.'+state.alias);
        sessionStorage.removeItem('smartpro.identity');
        state.alias=null;
        writeCourseLocation(true);
        outcome='Your HOD term ended. The department Admin can appoint a successor.';
      }
    }
    const coursePost=(offeringId,action,body)=>api(`/api/v1/courses/offerings/${offeringId}/commands`,'POST',{action,...body});
    if(type==='course-framework'){
      const stages=[...form.querySelectorAll('.course-stage')].map(row=>{const get=name=>row.querySelector(`[name=${name}]`).value,[schemeVersionId,schemeModeId]=get('stageRubric').split(':');return {key:get('stageKey'),name:get('stageName'),schemeVersionId,schemeModeId,policyId:get('stagePolicy'),weight:get('stageWeight'),required:get('stageRequired')==='true',opensAt:new Date(get('stageOpens')).toISOString(),deadline:new Date(get('stageDeadline')).toISOString()};});
      if(!stages.length)throw new Error('Add the approved assessment stage or stages first.');
      const cfg={stages,method:values.method,rounding:values.rounding,decimalPlaces:Number(values.decimalPlaces),scale:values.scale,allowFinalCorrections:values.allowFinalCorrections==='on',outsidePanelAuthorizer:values.outsidePanelAuthorizer==='true',maxExtensionDays:Number(values.maxExtensionDays),publicationRoles:new FormData(form).getAll('publicationRoles'),requirementPolicyIds:new FormData(form).getAll('requirementPolicyIds'),deadlineRules:{kinds:new FormData(form).getAll('deadlineKinds'),earliestAt:new Date(values.deadlineEarliest).toISOString(),latestAt:new Date(values.deadlineLatest).toISOString(),maxReminderHours:Number(values.maxReminderHours),completionRoles:new FormData(form).getAll('milestoneCompletionRoles')}};
      await coursePost(form.dataset.offering,'FRAMEWORK',{expectedVersion:Number(form.dataset.version),configuration:cfg,authority:state.role==='Admin'?instructionAuthority(values):null,reason:values.reason});
    }
    if(type==='course-plan')await coursePost(form.dataset.offering,'PLAN',{expectedVersion:Number(form.dataset.version),frameworkId:values.frameworkId,schedules:Object.fromEntries([...form.querySelectorAll('[data-stage]')].map(el=>[el.dataset.stage,new Date(el.value).toISOString()]))});
    if(type==='course-stage')await coursePost(form.dataset.offering,'CREATE_STAGE',{projectId:values.projectId,stageKey:values.stageKey,facultyIds:new FormData(form).getAll('facultyIds')});
    if(type==='course-final'){outcome='Overall result published. Its release is in project history.';await coursePost(form.dataset.offering,'PUBLISH_FINAL',{projectId:form.dataset.project,expectedVersion:0});}
    if(type==='guide-final-correction'){
      state.guideCorrectionPage=1;state.guideCorrectionAnchor=null;
      outcome='Correction request submitted to the responsible Coordinator. The published result is unchanged.';
      await coursePost(form.dataset.offering,'REQUEST_FINAL_REVISION',{projectId:form.dataset.project,expectedVersion:Number(form.dataset.version),studentId:values.studentId,marks:values.marks,reason:values.reason});
    }
    if(type==='guide-stage-evidence-correction'){
      state.guideCorrectionPage=1;state.guideCorrectionAnchor=null;
      outcome='Updated stage evidence submitted to the Coordinator. The published result remains unchanged until approval.';
      await coursePost(form.dataset.offering,'REQUEST_FINAL_REVISION',{projectId:form.dataset.project,expectedVersion:Number(form.dataset.version),mode:'STAGE_EVIDENCE',reason:values.reason});
    }
    if(type==='final-revision-authorization'){
      state.finalRevisionAnchor=null;
      const approved=values.approved==='true';
      await coursePost(form.dataset.offering,'AUTHORIZE_FINAL_REVISION',{requestId:form.dataset.id,approved});
      outcome=approved?'Correction approved. The revised overall result is published; its predecessor is retained.':'Correction declined. Published marks are unchanged.';
    }
    if(type==='course-correction-authorization')await coursePost(form.dataset.offering,form.dataset.exceptional==='yes'?'AUTHORIZE_EXCEPTIONAL_STAGE_CORRECTION':'AUTHORIZE_CORRECTION',{requestId:form.dataset.id,approved:values.approved==='true'});
    if(type==='course-deadline'){
      const reminderHours=values.reminderHours.trim()?values.reminderHours.split(',').map(v=>Number(v.trim())):[];
      if(reminderHours.some(v=>!Number.isInteger(v)||v<0))throw new Error('Enter reminder timings as nonnegative whole hours.');
      await coursePost(form.dataset.offering,'DEADLINE',{deadlineKey:form.dataset.key||'deadline-'+crypto.randomUUID(),expectedVersion:Number(form.dataset.version),projectId:values.projectId||null,kind:values.kind,target:values.target,name:values.name,dueAt:new Date(values.dueAt).toISOString(),reminderHours,notifyRoles:new FormData(form).getAll('notifyRoles'),completionRole:values.kind==='MILESTONE'?values.completionRole:null,completionScope:values.kind==='MILESTONE'?values.completionScope:null,active:values.active==='true'});state.editCourseDeadline=null;
    }
    if(type==='reopen-synopsis')await coursePost(form.dataset.offering,'REOPEN_SYNOPSIS',{projectId:form.dataset.project,expectedCaseVersion:Number(form.dataset.version),comment:values.comment||''});
    if(type==='course-appointment'){await api(`/api/v1/courses/offerings/${form.dataset.offering}/coordinators`,'POST',{userId:values.userId,expectedVersion:Number(form.dataset.version),active:values.active==='true',validUntil:new Date(values.validUntil).toISOString(),responsibilities:new FormData(form).getAll('responsibilities'),reason:values.reason,authority:null});state.editCourseAppointment=null;}
    if(type==='guide')await api(staffBase()+`/projects/${form.dataset.project}/guide`,'POST',{facultyId:values.facultyId,expectedGuideId:form.dataset.current||null,reason:values.reason});
    if(type==='schedule')await api(deptBase()+`/reviews/${form.dataset.review}/schedule`,'POST',{scheduledAt:new Date(values.scheduledAt).toISOString(),expectedReviewVersion:Number(form.dataset.version),reason:values.reason});
    if(type==='appoint-coordinator')await api(deptBase()+'/coordinators','POST',{expectedRevision:state.academic.revision,userId:values.userId,validUntil:new Date(values.validUntil).toISOString(),reason:values.reason});
    if(type==='delegate-operation')await api(staffBase()+'/coordinator-operations','POST',{mandateId:values.mandateId,operation:values.operation,validUntil:new Date(values.validUntil).toISOString(),reason:values.reason});
    if(type.startsWith('policy-')){const payload=policyPayload(form,values);await recordConfiguration(payload.kind,payload.configuration,values);state.reviseSetupId=null;}
    if(type==='confirm-proposal')await submitProposal(state.proposalDraft);
    if(type.startsWith('setup-')) {const configuration={...values};delete configuration.reason;for(const key of ['hodMandateId','instructionReference','instructionConfirmed'])delete configuration[key];await recordConfiguration(type==='setup-cycle'?'CYCLE':type==='setup-type'?'TYPE':'DOCUMENT_NOT_REQUIRED',configuration,values);}
    if(type==='revise-evaluators')await api(deptBase()+`/reviews/${form.dataset.review}/management`,'POST',{expectedReviewRevision:Number(form.dataset.revision),facultyIds:new FormData(form).getAll('facultyIds')});
    if(type==='revise-roster')await api(deptBase()+`/reviews/${form.dataset.review}/roster`,'POST',{expectedReviewRevision:Number(form.dataset.revision),membershipIds:new FormData(form).getAll('membershipIds')});
    if(type==='revise-proposal')await api(`/api/v1/projects/${form.dataset.project}/proposal-details`,'POST',{expectedRevision:Number(form.dataset.revision),title:values.title,description:values.description});
    if(type==='configure-requirement'){await api(staffBase()+'/document-requirements','POST',{offeringId:values.offeringId,requirementKey:form.dataset.key||null,expectedPolicyId:form.dataset.id||null,name:values.name,opensAt:new Date(values.opensAt).toISOString(),closesAt:new Date(values.closesAt).toISOString(),maxBytes:Number(values.maxBytes),required:values.required==='on',allowApproval:values.allowApproval==='on',allowChanges:values.allowChanges==='on',allowRevisions:values.allowRevisions==='on',reviewerIds:new FormData(form).getAll('reviewerIds'),authority:instructionAuthority(values)});state.editRequirementId=null;}
    if(type==='delegate-faculty')await api(deptBase()+'/delegations','POST',{expectedRevision:state.academic.revision,roleAssignmentId:values.roleAssignmentId,permission:values.permission,projectId:values.projectId||null,validUntil:new Date(values.validUntil).toISOString()});
    if(type==='manage-cycle')await api(staffBase()+'/configuration-management','POST',{action:'CYCLE',cycleId:form.dataset.id,expectedRevision:Number(form.dataset.revision),code:values.code,startsOn:values.startsOn,endsOn:values.endsOn,authority:instructionAuthority(values)});
    if(type==='manage-availability')await api(staffBase()+'/offering-management','POST',{action:'AVAILABILITY',offeringId:form.dataset.id,expectedRevision:Number(form.dataset.revision),availability:values.availability,authority:instructionAuthority(values)});
    if(type==='configure-instruction') {
      const configuration={...values,requiresSynopsis:values.requiresSynopsis==='on',maxBytes:values.requiresSynopsis==='on'?Number(values.maxBytes):null,facultyApprovalEnabled:values.facultyApprovalEnabled==='on',teamCreationEnabled:values.teamCreationEnabled==='on'}; delete configuration.reason;
      for(const field of ['visibleFrom','visibleUntil'])configuration[field]=new Date(values[field]).toISOString();
      for(const field of ['submissionOpensAt','submissionClosesAt'])configuration[field]=configuration.requiresSynopsis?new Date(values[field]).toISOString():null;
      for(const key of ['hodMandateId','instructionReference','instructionConfirmed'])delete configuration[key];configuration.adminRoleId=state.setup.instructionSources.adminRoleId;if(state.editOfferingId){const current=state.management.offerings.find(o=>o.id===state.editOfferingId);await api(staffBase()+'/offering-management','POST',{action:'EDIT',offeringId:current.id,expectedRevision:current.management_revision,configuration,authority:instructionAuthority(values)});state.editOfferingId=null;}else await recordConfiguration('OFFERING',configuration,values);
    }
    if(type==='assign-document-reviewer') await documentCommand('ASSIGN_REVIEWER',{projectId:form.dataset.project,facultyId:values.facultyId});
    if(type==='review-synopsis'){outcome='Faculty decision saved. It appears in submission history.';await documentCommand('DECIDE',{projectId:form.dataset.project,attemptId:form.dataset.attempt,expectedCaseVersion:Number(form.dataset.version),decision:values.decision,comment:values.comment,...(form.dataset.requirement?{requirementKey:form.dataset.requirement}:{})});}
    if(type==='upload-synopsis') {
      const file=form.querySelector('input[type=file]').files[0],context={alias:state.alias,role:state.role,signal:controller.signal};
      const pending='smartpro.upload.'+context.alias+':'+form.dataset.project+':'+(form.dataset.requirement||'SYNOPSIS')+':'+file.name+':'+file.size+':'+file.lastModified;
      const key=sessionStorage.getItem(pending)||crypto.randomUUID();sessionStorage.setItem(pending,key);
      const body=new FormData();body.append('file',file);
      await pdfUploadResult(fetch(documentsBase()+`/projects/${form.dataset.project}/uploads${form.dataset.requirement?'?requirementKey='+encodeURIComponent(form.dataset.requirement):''}`,{method:'POST',headers:{...reviewerHeaders(context.alias),...(context.role?{'X-Smartpro-Role':context.role}:{}),'Idempotency-Key':key},body,signal:context.signal}),()=>sessionStorage.removeItem(pending));
      outcome='PDF version saved. Submit the saved version for faculty review.';
    }
    if (type === 'create-team') await api('/api/v1/teams','POST',{offeringId:selectedOffering(),name:values.name});

    if (type === 'assign') await api(deptBase()+'/reviews','POST',{projectId:values.projectId,schemeVersionId:values.reviewScheme.split(':')[0],schemeModeId:values.reviewScheme.split(':')[1],policyId:values.policyId,facultyIds:new FormData(form).getAll('facultyIds'),reason:values.reason});
    if (type === 'marks') {
      const r = currentReview(), a = r.assessments.find(x => x.facultyId === state.workspace.actor.id);
      const scores = [...form.querySelectorAll('[data-criterion]')].map(input => ({criterionId:input.dataset.criterion,studentId:input.dataset.student || null,marks:input.value}));
      if(state.role==='Coordinator'&&!canMarkHere(r.id,a.id))throw new Error('This assessment is not assigned to you.');
      if (a.state === 'DRAFT') await api(deptBase()+`/assessments/${a.id}/draft`,'POST',{expectedAssessmentVersion:a.version,scores,reason:values.reason},evaluatorContext());
      else if(uiContext.courseManagement){const project=state.documents.projects.find(p=>p.id===r.projectId),offeringId=project?.offeringId;if(!offeringId)throw new Error('Open the assigned project to check its offering.');const result=await api(`/api/v1/courses/offerings/${offeringId}/commands`,'POST',{action:'REQUEST_CORRECTION',reviewId:r.id,expectedReviewRevision:r.revision,assessmentId:a.id,scores,reason:values.reason},evaluatorContext());
        outcome=result.appliedImmediately?'Correction applied. The original scores remain in history.':'Correction submitted for coordinator authorization.';}
      else await api(deptBase()+`/reviews/${r.id}/evaluations`,'POST',{expectedReviewRevision:r.revision,assessmentId:a.id,scores,reason:values.reason});
    }
    if (type === 'publish'){outcome='Stage results published. The new release is in result history.';await api(deptBase()+`/reviews/${state.reviewId}/publish`,'POST',{expectedReviewRevision:currentReview().revision,reason:values.reason});}
    if (type === 'publication') await api(staffBase()+`/offerings/${staffOffering().id}/publication`,'POST',{expectedRevision:state.staff.revision,reason:values.reason,visibleFrom:new Date(values.visibleFrom).toISOString(),visibleUntil:new Date(values.visibleUntil).toISOString(),teamCreationEnabled:values.teamCreationEnabled === 'on'});
    if (type === 'team-policy') await api(staffBase()+`/offerings/${staffOffering().id}/team-policy`,'POST',{expectedRevision:state.staff.revision,reason:values.reason,allowJoin:values.allowJoin === 'on',allowLeave:values.allowLeave === 'on',allowTransfer:values.allowTransfer === 'on',minimumMembers:values.minimumMembers === '' ? null : Number(values.minimumMembers),maximumMembers:values.maximumMembers === '' ? null : Number(values.maximumMembers),sizeMode:values.sizeMode});
    if (type === 'registration-policy') await api(staffBase()+`/offerings/${staffOffering().id}/registration-policy`,'POST',{expectedRevision:state.staff.revision,reason:values.reason,projectType:staffOffering().registrationPolicies[0].projectType,policyVersionId:staffOffering().registrationPolicies[0].policyVersionId,opensAt:new Date(values.opensAt).toISOString(),closesAt:new Date(values.closesAt).toISOString()});
    if (type === 'academic-policy') await api(deptBase()+'/policies','POST',{expectedRevision:state.academic.revision,reason:values.reason,evaluatorQuorum:Number(values.quorum),aggregation:values.aggregation,evaluatorWeights:values.aggregation === 'WEIGHTED_MEAN' ? Object.fromEntries(Object.entries(values).filter(([k,v]) => k.startsWith('weight-') && v !== '').map(([k,v]) => [k.slice(7),v])) : {}});
  }, type.startsWith('intake-')?'':()=>outcome||(type==='confirm-proposal'?'Your proposal has been submitted. Track its review in your project workspace.':'Saved successfully. Previous records are preserved.'));
});

function displayOffering(o){return `${academicText(o.label)} · ${academicText(o.semester)} · ${academicText(o.cycle?.code||'')}`;}
function academicText(value){return String(value||'').replace(/SYNTHETIC-SEM-?(\d+)/g,'Semester $1').replace(/DEMO-(\d{4})/g,'Academic cycle $1').replace(/^DEMO-/,'').replace(/^Demo /,'');}
function roleChooser(){const w=state.workspace;$('#app').innerHTML=`<main id="main" class="role-choice panel">${brand}<h1>Choose your responsibility</h1><p>${esc(w.actor.name)}, choose the workspace you want to use. Your permissions are verified for every request.</p>${w.roleChoices.map(role=>`<button class="person-option" data-action="choose-role" data-role="${role}"><strong>${role==='Admin'?'Department Admin':role}</strong><span>Open workspace →</span></button>`).join('')}<button class="quiet" data-action="logout">Switch test account</button></main>`;}
async function switchRole(role){
  controller.abort();
  controller=new AbortController();
  state.generation++;
  state.busy=false;
  state.role=role;
  state.intakeDraft=null;state.intakeOutcome=null;state.departmentRecordId=null;state.candidateQuery='';state.candidatePage=1;state.targetQuery='';state.targetPage=1;state.recordScope='directory';state.departmentOfferingSearch='';state.departmentAvailability='ALL';state.departmentOfferingPage=1;state.appointmentPage=1;state.leadershipPage=1;state.leadershipSearch='';state.intakeQuery='';state.intakeKind='STUDENT';state.intakePage=1;state.batchPage=1;state.workQuery='';state.workPage=1;state.workOffering='';
  state.view=role==='Coordinator'&&uiContext.courseManagement?'courses':'overview';
  state.courseId=null;
  state.courseProjectId=null;
  state.courseSection='overview';
  state.courseReviewId=null;
  writeCourseLocation(true);writeWorkLocation(true);
  state.workspace=null;
  state.studentMetadataValidUntil=0;
  state.proposalDraft=null;
  state.projectId=null;
  state.offeringId=null;
  state.reviewId=null;
  state.staffOfferingId=null;
  sessionStorage.setItem('smartpro.role.'+state.alias,role);
  await work(async()=>{},'');
}
async function submitProposal(draft){
 const context={alias:state.alias,role:state.role,signal:controller.signal},generation=state.generation,dept=state.workspace.department.id;
 const fingerprint=[draft.offeringId,draft.teamId,draft.title,draft.description];
 const hash=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
 const cacheKey='smartpro.proposal.'+context.alias+':'+await hash(new TextEncoder().encode(JSON.stringify(fingerprint)));
 const digest=draft.file?await hash(await draft.file.arrayBuffer()):null;
 const pending=JSON.parse(sessionStorage.getItem(cacheKey)||'null')||{key:crypto.randomUUID(),fileDigest:digest};
 if(pending.fileDigest!==digest)throw new Error('An unfinished submission uses a different file. Resume with that file, or open the saved project to continue its draft.');
 sessionStorage.setItem(cacheKey,JSON.stringify(pending));
 try{
  const project=await api('/api/v1/projects','POST',{offeringId:draft.offeringId,teamId:draft.teamId,title:draft.title,description:draft.description},{...context,key:pending.key});
  if(draft.file){
   const body=new FormData();body.append('file',draft.file);
   const result=await pdfUploadResult(fetch(`/api/v1/documents/departments/${dept}/projects/${project.id}/uploads`,{method:'POST',headers:{...reviewerHeaders(context.alias),'X-Smartpro-Role':context.role,'Idempotency-Key':pending.key+':file'},body,signal:context.signal}));
   const documents=await api(`/api/v1/documents/departments/${dept}?project=${project.id}`,'GET',undefined,context);
   const current=documents.projects.find(p=>p.id===project.id);
   if(!pending.caseVersion){pending.caseVersion=current.case.version;sessionStorage.setItem(cacheKey,JSON.stringify(pending));}
   await api(`/api/v1/documents/departments/${dept}`,'POST',{action:'SUBMIT',projectId:project.id,documentVersionId:result.documentVersionId,expectedCaseVersion:pending.caseVersion},{...context,key:pending.key+':submit'});
  }
  sessionStorage.removeItem(cacheKey);
  if(generation===state.generation){state.proposalDraft=null;state.projectId=project.id;state.view='documents';writeWorkLocation();}
 }catch(error){if(error.name!=='AbortError')error.message+=' Your proposal has not been confirmed as sent. Saved drafts remain in My projects and can be continued.';throw error;}
}

window.addEventListener('popstate',async()=>{
  if(!personalRole()&&!departmentRole()&&(state.role!=='Coordinator'||!uiContext.courseManagement))return;
  controller.abort();
  controller=new AbortController();
  state.generation++;
  state.busy=false;
  if(personalRole())readWorkLocation();else readCourseLocation();
  state.navigationPending=true;
  await work(async()=>{},'');
  focusHeading('#main h1');
});
if(personalRole())readWorkLocation();else readCourseLocation();
show();
if (state.alias) await work(async () => {},'');

export {esc};
