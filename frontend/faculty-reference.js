const normalize = value => value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const expertiseFor = record => record.expertise.length ? record.expertise : record.earlierReference?.expertise || [];
const searchableExpertise = record => [...record.expertise,...(record.earlierReference?.expertise || [])];

export function filterFaculty(records, {name='', designation='', expertise=''} = {}) {
  const query=normalize(name);
  return records.filter(record =>
    [record.name,record.earlierReference?.name].some(value => value && normalize(value).includes(query)) &&
    (!designation || record.designation === designation) &&
    (!expertise || searchableExpertise(record).some(topic => normalize(topic) === expertise)));
}

export function facultyReferencePanel(state, context, esc, offeringId=null) {
  const department=context.facultyReferenceDepartmentId;
  if(!department || state.workspace.department?.id!==department) return '';
  const role=state.role;
  if(role==='Coordinator' ? !offeringId : !['Admin','HOD'].includes(role) || offeringId) return '';
  return `<details class="panel" data-faculty-reference data-department="${esc(department)}" data-offering="${esc(offeringId)}">
    <summary>Faculty directory <span class="reference-context">Search faculty records</span></summary>
    <div data-reference-content aria-live="polite"></div>
  </details>`;
}

function sourceLink(url,label,esc) {
  if(!url) return '';
  let source;
  try { source=new URL(url); } catch { return ''; }
  if(source.protocol!=='https:' || !['bit-bangalore.edu.in','bit-bangalore.irins.org'].includes(source.hostname))return '';
  return `<a href="${esc(source.href)}" target="_blank" rel="noopener noreferrer">${esc(label)} (opens in a new tab)</a>`;
}

function facultyCard(record,esc){
 const earlier=record.earlierReference,topics=expertiseFor(record);
 const titleDiffers=earlier&&normalize(earlier.designation)!==normalize(record.designation);
 const prior=earlier&&record.expertise.length?earlier.expertise.filter(t=>!record.expertise.some(v=>normalize(t)===normalize(v))):[];
 return `<article class="faculty-entry"><div class="faculty-entry-main"><h3>${esc(record.name)}</h3><p class="muted">${esc(record.designation)} · ${esc(record.department)}</p>${topics.length?`<p class="faculty-expertise">${topics.slice(0,4).map(esc).join(' · ')}</p>`:''}</div><details class="faculty-evidence"><summary>Source details</summary><p>${esc(record.evidenceStatus)}</p>${record.auditNote?`<p>${esc(record.auditNote)}</p>`:''}${titleDiffers?`<p>Earlier record: ${esc(earlier.designation)}</p>`:''}${prior?.length?`<p>Earlier expertise: ${prior.map(esc).join(', ')}</p>`:''}<p>${sourceLink(record.bitProfileUrl,'Institutional profile',esc)} ${sourceLink(record.irinsProfileUrl||earlier?.sourceUrl,'Research profile',esc)}</p></details></article>`;
}
export async function openFacultyReference(panel,get,esc) {
  const content=panel.querySelector('[data-reference-content]');
  if(content.dataset.state) return;
  content.dataset.state='loading';
  content.textContent='Loading Faculty Reference…';
  try {
    const query=panel.dataset.offering?`?offeringId=${encodeURIComponent(panel.dataset.offering)}`:'';
    const snapshot=await get(`/api/v1/faculty-reference/departments/${panel.dataset.department}${query}`);
    if(!panel.isConnected)return;
    const records=snapshot.records;
    const designations=[...new Set(records.map(record=>record.designation))].sort();
    const topics=new Map(records.flatMap(searchableExpertise).map(topic=>[normalize(topic),topic]));
    const options=items=>items.map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');
    content.removeAttribute('aria-live');
    content.innerHTML=`<div class="directory-head"><p class="muted">Reference faculty records for appointments and assignments.</p><details class="directory-provenance"><summary>Data sources and verification notes</summary><p>Reference retrieved ${esc(snapshot.retrievedOn)}. Employment and appointments are verified independently.</p><p>${sourceLink(snapshot.rosterUrl,'BIT teaching roster',esc)} · ${sourceLink(snapshot.irinsIndexUrl,'IRINS index',esc)}</p><p>The index reported ${esc(snapshot.irinsReportedProfiles)} profiles; ${records.length} entries are in this snapshot. These counts are not reconciled.</p></details></div><div class="directory-filters"><label>Search faculty<input type="search" name="name" placeholder="Name"></label><label>Designation<select name="designation"><option value="">All designations</option>${options(designations.map(value=>[value,value]))}</select></label><label>Expertise<select name="expertise"><option value="">All subjects</option>${options([...topics].sort(([l],[r])=>l.localeCompare(r)))}</select></label></div><p class="directory-count" role="status"></p><div class="faculty-directory" data-reference-results></div>`;

    const update=()=>{
      const filters=Object.fromEntries([...content.querySelectorAll('input,select')].map(control=>[control.name,control.value]));
      const matches=filterFaculty(records,filters);
      content.querySelector('[role=status]').textContent=matches.length?`${matches.length} of ${records.length} faculty entries`:'No faculty entries match these filters.';
      content.querySelector('[data-reference-results]').innerHTML=matches.map(record=>facultyCard(record,esc)).join('');
    };
    content.addEventListener('input',update);
    content.dataset.state='ready';
    update();
  } catch {
    content.textContent='Faculty Reference could not be loaded. Close and reopen this section to retry.';
    delete content.dataset.state;
  }
}
