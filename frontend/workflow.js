// Pure workflow rules shared by views; no fabricated progress or requirements.
export const natural = value => String(value||'Not submitted').toLowerCase().replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
export const megabytes = bytes => bytes<1048576 ? `${Math.max(1,Math.ceil(bytes/1024))} KB` : `${(bytes/1048576).toFixed(2).replace(/\.00$/,'')} MB`;
export function windowState(project, now=Date.now()) {
  if(project.requirementDisposition==='NOT_REQUIRED') return 'NOT_REQUIRED';
  if(!project.requirement) return project.configurationPending?'AWAITING_AUTHORIZATION':'NOT_CONFIGURED';
  if(now<Date.parse(project.requirement.opensAt)) return 'NOT_YET_OPEN';
  if(now>=Date.parse(project.requirement.closesAt)) return 'CLOSED';
  return 'OPEN';
}
export function documentState(project, now=Date.now()) {
  return project.case?.state&&project.case.state!=='DRAFT'?project.case.state:windowState(project,now);
}
export function canUpload(project,now=Date.now()) {
  return Boolean(project.canSubmit && project.requirement &&
    Date.parse(project.requirement.opensAt)<=now && now<Date.parse(project.requirement.closesAt) &&
    (!project.case || ['DRAFT','CHANGES_REQUESTED'].includes(project.case.state)));
}
export function offeringProjects(projects,offeringId) { return projects.filter(p=>p.offeringId===offeringId); }


export function workspaceOpenError(error, localDevelopment) {
  if (error.status === 401 || error.status === 403) {
    return `Could not open this workspace. ${error.serverMessage || 'This account or responsibility is unavailable.'} Select an eligible account or responsibility and try again.`;
  }
  if (localDevelopment && [400, 404, 405].includes(error.status)) {
    return 'The local server could not load this workspace. Restart SMART-PRO from the current checkout, then try again.';
  }
  return 'Could not load this workspace. Check that SMART-PRO is running and try again.';
}
export async function pdfUploadResult(request, settled = () => {}) {
  const uncertain = 'The upload could not be confirmed. Check project history, or retry with the same PDF in this tab.';
  let response, result;
  try {
    response = await request;
    if (response.status >= 500) throw new Error(uncertain);
    result = await response.json();
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error(uncertain);
  }
  if (response.ok && !result?.documentVersionId) throw new Error(uncertain);
  settled();
  if (!response.ok) throw new Error(result?.detail?.message || 'Check that the file is a valid PDF within the size limit.');
  return result;
}
