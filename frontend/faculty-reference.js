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
    <summary>Faculty Reference</summary>
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

function facultyCard(record,esc) {
  const earlier=record.earlierReference;
  const topics=expertiseFor(record);
  const titleDiffers=earlier && normalize(earlier.designation)!==normalize(record.designation);
  const earlierTopics=earlier && record.expertise.length &&
    earlier.expertise.filter(topic=>!record.expertise.some(current=>normalize(current)===normalize(topic)));
  return `<article class="project-card">
    <h3>${esc(record.name)}</h3>
    <p>${esc(record.designation)} · ${esc(record.department)}</p>
    <p>${topics.length?`Expertise${record.expertise.length?' (IRINS audit)':' (earlier reference)'} · ${topics.map(esc).join(', ')}`:'Expertise unavailable in the supplied references'}</p>
    <p class="muted">${esc(record.evidenceStatus)}</p>
    ${record.auditNote?`<p class="hint">${esc(record.auditNote)}</p>`:''}
    ${titleDiffers?`<p class="hint">Earlier reference lists ${esc(earlier.designation)}.</p>`:''}
    ${earlierTopics?.length?`<p class="hint">Earlier reference also lists ${earlierTopics.map(esc).join(', ')}.</p>`:''}
    <p>${sourceLink(record.bitProfileUrl,`BIT profile for ${record.name}`,esc)}</p>
    ${record.irinsProfileUrl?`<p>${sourceLink(record.irinsProfileUrl,`IRINS profile for ${record.name}`,esc)}</p>`:
      earlier?`<p>${sourceLink(earlier.sourceUrl,`Earlier IRINS reference for ${record.name}`,esc)} · ${esc(earlier.retrievedOn)}</p>`:''}
  </article>`;
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
    content.innerHTML=`<p>Public BIT main-CSE reference · Retrieved ${esc(snapshot.retrievedOn)}. Employment and SMART-PRO appointments are verified separately.</p>
      <p>${sourceLink(snapshot.rosterUrl,'BIT main-CSE teaching roster',esc)} · The supplied audit counted ${esc(snapshot.irinsReportedProfiles)} profiles in the ${sourceLink(snapshot.irinsIndexUrl,'BIT IRINS index',esc)}. The difference from the ${records.length} roster entries remains unresolved.</p>
      <div class="form-grid">
        <label>Search faculty by name<input type="search" name="name"></label>
        <label>Published designation<select name="designation"><option value="">All designations</option>${options(designations.map(value=>[value,value]))}</select></label>
        <label>Sourced expertise<select name="expertise"><option value="">All expertise</option>${options([...topics].sort(([left],[right])=>left.localeCompare(right)))}</select></label>
      </div>
      <p role="status"></p><div class="course-cards" data-reference-results></div>`;
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
