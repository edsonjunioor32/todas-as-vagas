import assert from 'node:assert/strict';
import fs from 'node:fs';
import {buildTaxonomyIndex,decodeRequirementEntry,evaluateCandidateFit,matchRequirement,rankJobs} from '../docs/aderencia/fit-engine.js';

const taxonomy=JSON.parse(fs.readFileSync(new URL('../docs/data/fit-taxonomy.json',import.meta.url),'utf8'));
const index=buildTaxonomyIndex(taxonomy);
assert.equal(matchRequirement('Experiência com C# e .NET Framework','C#',index),true);
assert.equal(matchRequirement('Experiência com Java e Spring Boot','C#',index),false);
assert.equal(matchRequirement('English fluent','Inglês intermediário',index),true);
assert.equal(matchRequirement('MBA em Gestão e graduação em Sistemas de Informação','Ensino superior completo',index),true);

const supportResume='Analista de Suporte N2. Experiência com SQL, Oracle, APIs REST, logs, Splunk, Datadog, Grafana, troubleshooting, gestão de incidentes e RCA. Atendimento B2B e meios de pagamento.';
const dotnetFit=evaluateCandidateFit({mandatory:['C#','.NET','ASP.NET','SQL Server','JavaScript'],preferred:['APIs REST','Git'],context:[],manual:[],confidence:95},supportResume,taxonomy);
assert.ok(dotnetFit.score<=55,`vaga .NET deveria sofrer forte penalidade; recebido ${dotnetFit.score}`);
assert.ok(dotnetFit.gaps.includes('C#')&&dotnetFit.gaps.includes('.NET'));
const supportFit=evaluateCandidateFit({mandatory:['Suporte N2 / L2','SQL','Análise de logs','Gestão de incidentes','Troubleshooting'],preferred:['APIs REST','Datadog'],context:[],manual:['Disponibilidade de horário/turno'],confidence:95},supportResume,taxonomy);
assert.ok(supportFit.score>=85,`vaga de suporte deveria ter alta aderência; recebido ${supportFit.score}`);
assert.deepEqual(supportFit.manual,['Disponibilidade de horário/turno']);
const fitData={terms:['C#','.NET','SQL','Suporte N2 / L2'],jobs:{'https://example.com/dotnet':{m:[0,1,2],p:[],c:[],x:[],q:95},'https://example.com/support':{m:[2,3],p:[],c:[],x:[],q:95}}};
const ranked=rankJobs([{title:'.NET Support',url:'https://example.com/dotnet',skills:''},{title:'N2 Support',url:'https://example.com/support',skills:''}],fitData,supportResume,taxonomy,2);
assert.equal(ranked[0].job.url,'https://example.com/support');
assert.equal(decodeRequirementEntry(fitData.jobs['https://example.com/support'],fitData.terms).mandatory.length,2);
console.log('fit-engine tests: OK');
