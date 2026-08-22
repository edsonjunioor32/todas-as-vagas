(() => {
  'use strict';
  function analysisUrl(jobUrl,title,company){const target=new URL('./aderencia/',location.href);target.searchParams.set('job',jobUrl);if(title)target.searchParams.set('title',title);if(company)target.searchParams.set('company',company);return target.href}
  function decorateCard(card){if(!card||card.dataset.fitDecorated==='1')return;const original=card.querySelector('.job-footer .primary-link[href]'),footer=card.querySelector('.job-footer');if(!original?.href||!footer)return;const title=card.querySelector('h3')?.textContent?.trim()||'',company=card.querySelector('.company-name')?.textContent?.replace('✦','').trim()||'';const actions=document.createElement('div');actions.className='job-fit-actions';const fit=document.createElement('a');fit.className='fit-link';fit.href=analysisUrl(original.href,title,company);fit.textContent='Analisar aderência';fit.setAttribute('aria-label',`Analisar aderência do seu currículo à vaga ${title||'selecionada'}`);original.parentNode.insertBefore(actions,original);actions.append(fit,original);card.dataset.fitDecorated='1'}
  function scan(root=document){root.querySelectorAll?.('.job-card').forEach(decorateCard);if(root.matches?.('.job-card'))decorateCard(root)}
  const observer=new MutationObserver(mutations=>{for(const mutation of mutations)for(const node of mutation.addedNodes)if(node.nodeType===Node.ELEMENT_NODE)scan(node)});
  document.addEventListener('DOMContentLoaded',()=>{scan();const list=document.querySelector('#jobList');if(list)observer.observe(list,{childList:true,subtree:true})});
})();
