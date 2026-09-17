import {buildTaxonomyIndex,containsAlias,evaluateCandidateFit,extractRequirementsFromDescription} from './fit-engine.js';

const MAX_FILE_BYTES=12*1024*1024;
const MAX_PDF_PAGES=40;
const MIN_RESUME_CHARS=120;
const MIN_JOB_DESCRIPTION_CHARS=80;
const THEME_KEY='todas-as-vagas-theme';

const state={resumeText:'',resumeName:'',taxonomy:null,taxonomyIndex:null,selectedAnalysis:null,selectedJob:null};

const el={
  themeToggle:document.querySelector('#themeToggle'),
  themeIcon:document.querySelector('#themeIcon'),
  themeLabel:document.querySelector('#themeLabel'),
  uploadZone:document.querySelector('#uploadZone'),
  resumeFile:document.querySelector('#resumeFile'),
  resumePaste:document.querySelector('#resumePaste'),
  clearResume:document.querySelector('#clearResume'),
  resumeStatus:document.querySelector('#resumeStatus'),
  resumeSignals:document.querySelector('#resumeSignals'),
  resumeChars:document.querySelector('#resumeChars'),
  resumeSkills:document.querySelector('#resumeSkills'),
  jobTitleInput:document.querySelector('#jobTitleInput'),
  jobCompanyInput:document.querySelector('#jobCompanyInput'),
  jobUrlInput:document.querySelector('#jobUrlInput'),
  jobDescription:document.querySelector('#jobDescription'),
  jobDescriptionStatus:document.querySelector('#jobDescriptionStatus'),
  analyzeJob:document.querySelector('#analyzeJob'),
  analysisSection:document.querySelector('#analysisSection'),
  analysisTitle:document.querySelector('#analysisTitle'),
  fitScore:document.querySelector('#fitScore'),
  fitLabel:document.querySelector('#fitLabel'),
  mandatoryScore:document.querySelector('#mandatoryScore'),
  mandatoryDetail:document.querySelector('#mandatoryDetail'),
  coverageScore:document.querySelector('#coverageScore'),
  matchedList:document.querySelector('#matchedList'),
  gapList:document.querySelector('#gapList'),
  optionalList:document.querySelector('#optionalList'),
  manualList:document.querySelector('#manualList'),
  downloadReport:document.querySelector('#downloadReport')
};

function normalize(value){return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim()}

function setTheme(theme,persist=false){
  const selected=theme==='light'?'light':'dark',dark=selected==='dark';
  document.documentElement.dataset.theme=selected;
  el.themeToggle?.setAttribute('aria-pressed',String(dark));
  el.themeToggle?.setAttribute('aria-label',dark?'Ativar tema claro':'Ativar tema escuro');
  if(el.themeIcon)el.themeIcon.textContent=dark?'☾':'☀';
  if(el.themeLabel)el.themeLabel.textContent='Mudar Tema';
  const meta=document.querySelector('meta[name="theme-color"]');
  if(meta)meta.content=dark?'#061317':'#ffffff';
  if(persist){try{localStorage.setItem(THEME_KEY,selected)}catch{}}
}

function initTheme(){setTheme(document.documentElement.dataset.theme||'dark');el.themeToggle?.addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark',true))}

async function fetchJson(path){
  const response=await fetch(path,{cache:'no-store',credentials:'same-origin'});
  if(!response.ok)throw new Error('Falha ao carregar '+path+' ('+response.status+')');
  return response.json();
}

function currentResumeText(){return (el.resumePaste?.value||state.resumeText||'').trim()}
function currentJobDescription(){return (el.jobDescription?.value||'').trim()}

function recognizedSkills(text){
  if(!state.taxonomyIndex||!text)return[];
  const normalized=normalize(text),found=[];
  for(const entry of state.taxonomyIndex.entries||[]){
    if([entry.label,...(entry.aliases||[])].some(alias=>containsAlias(normalized,alias)))found.push(entry.label);
  }
  return [...new Set(found)];
}

function updateAnalyzeButton(){
  const ready=currentResumeText().length>=MIN_RESUME_CHARS&&currentJobDescription().length>=MIN_JOB_DESCRIPTION_CHARS&&state.taxonomy;
  if(el.analyzeJob)el.analyzeJob.disabled=!ready;
}

function updateResumeUi(message=''){
  const text=currentResumeText(),skills=recognizedSkills(text),ready=text.length>=MIN_RESUME_CHARS;
  if(el.resumeStatus)el.resumeStatus.textContent=message||(ready?(state.resumeName?state.resumeName+' pronto para análise.':'Texto do currículo pronto para análise.'):'Adicione um currículo com conteúdo suficiente para analisar.');
  if(el.resumeSignals)el.resumeSignals.hidden=!ready;
  if(el.resumeChars)el.resumeChars.textContent=new Intl.NumberFormat('pt-BR').format(text.length);
  if(el.resumeSkills)el.resumeSkills.textContent=new Intl.NumberFormat('pt-BR').format(skills.length);
  if(el.clearResume)el.clearResume.hidden=!text;
  updateAnalyzeButton();
}

function updateJobUi(message=''){
  const length=currentJobDescription().length,ready=length>=MIN_JOB_DESCRIPTION_CHARS;
  if(el.jobDescriptionStatus)el.jobDescriptionStatus.textContent=message||(ready?'Descrição pronta para comparação ('+new Intl.NumberFormat('pt-BR').format(length)+' caracteres).':'Cole uma descrição com pelo menos '+MIN_JOB_DESCRIPTION_CHARS+' caracteres para continuar.');
  updateAnalyzeButton();
}

async function extractPdf(file){
  const pdfjs=await import('../vendor/pdf.mjs');
  pdfjs.GlobalWorkerOptions.workerSrc=new URL('../vendor/pdf.worker.mjs',import.meta.url).href;
  const data=new Uint8Array(await file.arrayBuffer()),pdf=await pdfjs.getDocument({data}).promise,pages=[];
  const limit=Math.min(pdf.numPages,MAX_PDF_PAGES);
  for(let pageNumber=1;pageNumber<=limit;pageNumber+=1){
    const page=await pdf.getPage(pageNumber),content=await page.getTextContent(),text=content.items.map(item=>item.str||'').join(' ').replace(/\s+/g,' ').trim();
    if(text)pages.push(text);
  }
  if(pdf.numPages>MAX_PDF_PAGES)pages.push('[Leitura limitada às primeiras '+MAX_PDF_PAGES+' páginas]');
  return pages.join('\n');
}

async function extractDocx(file){
  if(!window.mammoth?.extractRawText)throw new Error('Leitor DOCX não foi carregado.');
  const result=await window.mammoth.extractRawText({arrayBuffer:await file.arrayBuffer()});
  return String(result.value||'').replace(/\n{3,}/g,'\n\n').trim();
}

async function extractFile(file){
  if(!file)throw new Error('Arquivo não selecionado.');
  if(file.size>MAX_FILE_BYTES)throw new Error('O arquivo excede o limite de 12 MB.');
  const ext=(file.name||'').toLowerCase().split('.').pop();
  if(ext==='pdf'||file.type==='application/pdf')return extractPdf(file);
  if(ext==='docx'||file.type==='application/vnd.openxmlformats-officedocument.wordprocessingml.document')return extractDocx(file);
  if(['txt','md','markdown'].includes(ext)||file.type.startsWith('text/'))return file.text();
  throw new Error('Formato não suportado. Use PDF, DOCX, TXT ou Markdown.');
}

async function handleFile(file){
  try{
    updateResumeUi('Lendo o currículo localmente…');
    const text=(await extractFile(file)).trim();
    if(text.length<MIN_RESUME_CHARS)throw new Error('Não foi possível extrair texto suficiente. Tente outro arquivo ou cole o texto do currículo.');
    state.resumeText=text;
    state.resumeName=file.name||'Currículo';
    if(el.resumePaste)el.resumePaste.value=text;
    updateResumeUi();
  }catch(error){
    state.resumeText='';
    state.resumeName='';
    if(el.resumePaste)el.resumePaste.value='';
    updateResumeUi(error.message||'Não foi possível ler o currículo.');
  }finally{if(el.resumeFile)el.resumeFile.value=''}
}

function clearResume(){
  state.resumeText='';
  state.resumeName='';
  state.selectedAnalysis=null;
  if(el.resumePaste)el.resumePaste.value='';
  if(el.analysisSection)el.analysisSection.hidden=true;
  updateResumeUi('Nenhum currículo carregado.');
}

function initUpload(){
  el.resumeFile?.addEventListener('change',event=>handleFile(event.target.files?.[0]));
  el.clearResume?.addEventListener('click',clearResume);
  let timer;
  el.resumePaste?.addEventListener('input',()=>{
    clearTimeout(timer);
    timer=setTimeout(()=>{
      if(el.resumePaste.value.trim()){state.resumeText='';state.resumeName=''}
      updateResumeUi();
    },160);
  });
  for(const name of['dragenter','dragover'])el.uploadZone?.addEventListener(name,event=>{event.preventDefault();el.uploadZone.classList.add('is-dragging')});
  for(const name of['dragleave','drop'])el.uploadZone?.addEventListener(name,event=>{event.preventDefault();el.uploadZone.classList.remove('is-dragging')});
  el.uploadZone?.addEventListener('drop',event=>handleFile(event.dataTransfer?.files?.[0]));
}

function jobFromInputs(){
  return{
    title:(el.jobTitleInput?.value||'').trim()||'Vaga informada manualmente',
    company:(el.jobCompanyInput?.value||'').trim()||'Empresa não informada',
    url:(el.jobUrlInput?.value||'').trim()
  };
}

function chip(text,variant=''){
  const span=document.createElement('span');
  span.className='fit-chip'+(variant?' '+variant:'');
  span.textContent=text;
  return span;
}

function renderChipList(container,values,emptyMessage,variant=''){
  const unique=[...new Set(values||[])];
  if(!unique.length){
    const empty=document.createElement('span');
    empty.className='fit-empty';
    empty.textContent=emptyMessage;
    container.replaceChildren(empty);
    return;
  }
  container.replaceChildren(...unique.map(value=>chip(value,variant)));
}

function renderAnalysis(job,result){
  state.selectedJob=job;
  state.selectedAnalysis=result;
  el.analysisSection.hidden=false;
  const scored=result.status==='scored'&&Number.isFinite(result.score);
  if(el.analysisTitle)el.analysisTitle.textContent='Análise: '+job.title;
  el.fitScore.textContent=scored?result.score+'%':'—';
  el.fitLabel.textContent=scored?result.label:'Dados insuficientes';
  const total=result.mandatory.total||0,matched=result.mandatory.matched.length;
  el.mandatoryScore.textContent=scored&&total?Math.round(matched/total*100)+'%':'—';
  el.mandatoryDetail.textContent=scored?(total?matched+' de '+total+' requisitos obrigatórios identificados.':'Nenhum requisito obrigatório foi identificado com confiança.'):'Não foi possível identificar requisitos suficientes na descrição colada.';
  el.coverageScore.textContent=scored&&Number.isFinite(result.coverage)?result.coverage+'%':'—';
  renderChipList(el.matchedList,result.matched,scored?'Nenhuma evidência explícita foi encontrada.':'Nenhuma competência reconhecida foi encontrada.','match');
  renderChipList(el.gapList,result.gaps,scored?'Nenhuma lacuna obrigatória foi identificada.':'Não calculadas sem requisitos reconhecidos.','gap');
  renderChipList(el.optionalList,result.optionalMissing,scored?'Nenhum diferencial ausente identificado.':'Não calculados sem requisitos reconhecidos.','optional');
  renderChipList(el.manualList,result.manual,scored?'Nada adicional para confirmar manualmente.':'Confirme manualmente as condições do anúncio.','manual');
  el.analysisSection.scrollIntoView({behavior:'smooth',block:'start'});
}

function analyzeJob(){
  const resume=currentResumeText(),description=currentJobDescription();
  if(resume.length<MIN_RESUME_CHARS||description.length<MIN_JOB_DESCRIPTION_CHARS||!state.taxonomy){
    updateResumeUi();
    updateJobUi();
    return;
  }
  el.analyzeJob.disabled=true;
  const original=el.analyzeJob.textContent;
  el.analyzeJob.textContent='Analisando…';
  try{
    const requirements=extractRequirementsFromDescription(description,state.taxonomy);
    renderAnalysis(jobFromInputs(),evaluateCandidateFit(requirements,resume,state.taxonomy));
  }catch(error){
    updateJobUi('Não foi possível analisar a descrição: '+(error.message||'erro desconhecido'));
  }finally{
    el.analyzeJob.textContent=original;
    updateAnalyzeButton();
  }
}

function makeReport(){
  if(!state.selectedAnalysis)return'';
  const r=state.selectedAnalysis,j=state.selectedJob||{},scored=r.status==='scored'&&Number.isFinite(r.score);
  const scoreLine=scored?'Aderência estimada: '+r.score+'% — '+r.label:'Aderência estimada: não calculada — dados insuficientes da descrição';
  const coverageLine=scored?'Cobertura da análise: '+r.coverage+'%':'Cobertura da análise: não calculada';
  const mandatoryLine=scored?'Obrigatórios atendidos: '+r.mandatory.matched.length+'/'+r.mandatory.total:'Obrigatórios atendidos: não calculado';
  return[
    'Todas as Vagas — Relatório de aderência',
    '',
    'Vaga: '+(j.title||'Não informada'),
    'Empresa: '+(j.company||'Não informada'),
    'Link: '+(j.url||'Não informado'),
    '',
    scoreLine,
    coverageLine,
    mandatoryLine,
    '',
    'Evidências encontradas:',
    ...(r.matched.length?r.matched.map(x=>'- '+x):['- Nenhuma evidência explícita']),
    '',
    'Lacunas obrigatórias:',
    ...(r.gaps.length?r.gaps.map(x=>'- '+x):[scored?'- Nenhuma lacuna obrigatória identificada':'- Não calculadas sem requisitos reconhecidos']),
    '',
    'Diferenciais não encontrados:',
    ...(r.optionalMissing.length?r.optionalMissing.map(x=>'- '+x):[scored?'- Nenhum':'- Não calculados sem requisitos reconhecidos']),
    '',
    'Itens para confirmação manual:',
    ...(r.manual.length?r.manual.map(x=>'- '+x):['- Nenhum']),
    '',
    'Observação: a comparação foi feita localmente com a descrição colada pelo usuário. A pontuação é uma estimativa e não representa probabilidade de contratação.'
  ].join('\n');
}

function downloadReport(){
  const text=makeReport();
  if(!text)return;
  const blob=new Blob([text],{type:'text/plain;charset=utf-8'});
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a');
  const slug=normalize(state.selectedJob?.company||'vaga').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
  link.href=url;
  link.download='aderencia-'+(slug||'vaga')+'.txt';
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function initData(){
  try{
    const taxonomy=await fetchJson('../data/fit-taxonomy.json');
    state.taxonomy=taxonomy;
    state.taxonomyIndex=buildTaxonomyIndex(taxonomy);
    updateResumeUi('Nenhum currículo carregado.');
    updateJobUi();
  }catch(error){
    updateResumeUi('O analisador não pôde ser inicializado: '+error.message);
    updateJobUi('O analisador não pôde ser inicializado.');
    if(el.resumeFile)el.resumeFile.disabled=true;
    if(el.resumePaste)el.resumePaste.disabled=true;
    if(el.jobDescription)el.jobDescription.disabled=true;
  }
}

el.jobDescription?.addEventListener('input',()=>updateJobUi());
el.jobTitleInput?.addEventListener('input',()=>updateAnalyzeButton());
el.jobCompanyInput?.addEventListener('input',()=>updateAnalyzeButton());
el.jobUrlInput?.addEventListener('input',()=>updateAnalyzeButton());
el.analyzeJob?.addEventListener('click',analyzeJob);
el.downloadReport?.addEventListener('click',downloadReport);

initTheme();
initUpload();
initData();
