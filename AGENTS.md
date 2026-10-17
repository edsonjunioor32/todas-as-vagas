# Segurança operacional do Todas as Vagas

Antes de alterar coleta, agenda, publicação, branches de dados, notificações ou integrações, leia `ops/ECOSYSTEM_MAP.md` e o inventário de `ops/OPERATIONS_CHANGELOG.md`. Identifique os consumidores no site, Telegram, `botwhats`, agente de vagas e serviços da VPS; verifique a configuração e os runs atuais, não apenas o código.

Em mudanças de workflows ou fontes, explicite no PR o impacto por portal/canal, a redundância restante, a checagem pós-implantação e o plano de reversão. Não ative simultaneamente publicadores legados nem apague checkpoints para forçar envios. Se a árvore de qualquer repositório vinculado mudar, atualize o mapa arquivo a arquivo. Nunca registre segredos, dados pessoais ou descrições privadas na documentação.
