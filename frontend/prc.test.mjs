import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

// Load the standalone ES module without changing the repository's Node format.
const source=readFileSync(new URL('./prc.js',import.meta.url),'utf8');
const ui=await import('data:text/javascript;charset=utf-8,'+encodeURIComponent(source));
const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

test('Coordinator PRC desk contains explicit activation and assignments',()=>{
 const state={role:'Coordinator',courses:{faculty:[{id:'fac-1',display_name:'Faculty A'}]},prcOverview:{activated:false,projects:[{id:'proj-1',title:'Study <a>',members:[],synopsisState:'AWAITING_REVIEW',guideAssigned:false,prcApproved:false}]}};
 const course={id:'off-1',responsibilities:['EVALUATORS']};
 const html=ui.prcCoordinatorSection(state,course,escape);
 assert.match(html,/data-form="prc-activate"/);
 assert.doesNotMatch(html,/data-form="prc-assign"/);
 assert.match(html,/Study &lt;a&gt;/);
});
test('Enabled Coordinator PRC desk allocates members on actual projects',()=>{
 const state={role:'Coordinator',courses:{faculty:[{id:'fac-1',display_name:'Faculty A'}]},prcOverview:{activated:true,projects:[{id:'proj-1',title:'Project',members:[],synopsisState:'AWAITING_REVIEW',guideAssigned:false,prcApproved:false}]}};
 const html=ui.prcCoordinatorSection(state,{id:'off-1',responsibilities:['EVALUATORS']},escape);
 assert.match(html,/data-form="prc-assign"/);
 assert.match(html,/name="facultyId"/);
});
test('PRC faculty can record all three documented outcomes',()=>{
 const state={projectId:'proj-1',prcOffering:'off-1',prcOverview:{activated:true,projects:[{id:'proj-1',title:'Project',latestAttemptId:'attempt-1',caseVersion:2,synopsisState:'AWAITING_REVIEW',members:[{facultyId:'f-1'}]}]}};
 const html=ui.prcFacultySection(state,escape);
 for(const x of ['APPROVE','REQUEST_MODIFICATION','REJECT'])assert.match(html,new RegExp(x));
 assert.match(html,/data-form="prc-decision"/);
});
test('Student rejection requires another synopsis, not project deletion',()=>{
 const html=ui.prcStudentSection({enabled:true,approved:false,latestDecision:'REJECT',synopsisState:'CHANGES_REQUESTED',history:[{attemptNo:1,decision:'REJECT',comment:'New proposal <required>'}]},escape);
 assert.match(html,/Submit another synopsis/);
 assert.match(html,/New proposal &lt;required&gt;/);
 assert.doesNotMatch(html,/project deletion/);
});
