# Agendador externo do catálogo

Este diretório adiciona uma alternativa gratuita para quando o GitHub Actions atrasar ou perder um evento schedule. O agendador apenas consulta os runs de pages.yml e solicita workflow_dispatch para a branch main quando o slot mais recente está atrasado e não existe coleta ativa ou bem-sucedida.

A coleta e o cron nativo do GitHub permanecem intactos. O agendador não edita public-data, não cancela runs e não acessa Telegram ou botwhats.

## Contrato operacional

Os slots são mantidos em UTC no código:

- 11:00 UTC = 08:00 BRT;
- 14:00 UTC = 11:00 BRT;
- 18:00 UTC = 15:00 BRT;
- 23:00 UTC = 20:00 BRT.

O timer acorda a cada 15 minutos em UTC. O script aguarda 30 minutos após o slot. Em seguida, nesta ordem:

1. adquire um lock flock não bloqueante;
2. consulta os runs de pages.yml na main;
3. não faz dispatch se houver run queued ou in_progress;
4. não faz dispatch se houver run concluído com sucesso no slot;
5. não repete um slot registrado no estado local após um POST confirmado;
6. faz um único POST de workflow_dispatch com {"ref":"main"};
7. grava o estado somente após o POST retornar sucesso.

A coleta pode continuar atrasada: enquanto pages.yml estiver ativa o agendador sai sem dispatch, e a próxima execução do timer volta a verificar o mesmo slot. O POST não é repetido automaticamente em caso de resposta ambígua de rede, pois isso poderia duplicar a coleta; a próxima rodada decide novamente com base nos runs e no estado local.

O estado fica fora do repositório em ~/.local/state/todas-as-vagas/github-scheduler.json, com diretório 0700, arquivo 0600 e substituição atômica. O lock fica no mesmo diretório. Os logs úteis aparecem no journal com SCHEDULER_STATUS, SCHEDULER_DISPATCHED, slot UTC e slot BRT.

## Token GitHub

Crie um token fine-grained no GitHub com:

- apenas o repositório edsonjunioor32/todas-as-vagas;
- Actions: Read and write;
- Metadata: Read.

O script usa o token para consultar runs e chamar o endpoint de dispatch. Não coloque o token no repositório, no unit file ou na linha de comando. A variável esperada é GITHUB_SCHEDULER_TOKEN.

## Instalação segura na VPS

Pré-requisito: Python 3.9+ com zoneinfo e Linux com flock. A Oracle Linux atual atende esse contrato. O checkout deve estar em ~/todas-as-vagas; se outro caminho for usado, ajuste apenas ExecStart no unit file.

Depois de obter o checkout na VPS, esta é a única etapa operacional necessária:

~~~bash
cd "$HOME/todas-as-vagas"
install -d -m 700 "$HOME/.config/todas-as-vagas" "$HOME/.local/state/todas-as-vagas" "$HOME/.config/systemd/user"
umask 077
read -rsp "GITHUB_SCHEDULER_TOKEN: " TOKEN; printf "\\n"
printf "GITHUB_SCHEDULER_TOKEN=%s\\n" "$TOKEN" > "$HOME/.config/todas-as-vagas/github-scheduler.env"
unset TOKEN
chmod 600 "$HOME/.config/todas-as-vagas/github-scheduler.env"
chmod 0755 ops/github_scheduler.py
install -m 0644 ops/systemd/todas-as-vagas-github-scheduler.service "$HOME/.config/systemd/user/"
install -m 0644 ops/systemd/todas-as-vagas-github-scheduler.timer "$HOME/.config/systemd/user/"
systemd-analyze verify "$HOME/.config/systemd/user/todas-as-vagas-github-scheduler.service" "$HOME/.config/systemd/user/todas-as-vagas-github-scheduler.timer"
systemctl --user daemon-reload
systemctl --user enable --now todas-as-vagas-github-scheduler.timer
systemctl --user start todas-as-vagas-github-scheduler.service
~~~

Para o timer continuar ativo após logout ou reboot, habilite linger para o usuário da VPS conforme a política local:

~~~bash
loginctl enable-linger "$(id -un)"
~~~

O último systemctl --user start é seguro e idempotente; ele apenas valida a instalação e faz catch-up se houver slot perdido.

## Observação e diagnóstico

~~~bash
systemctl --user status todas-as-vagas-github-scheduler.timer
journalctl --user -u todas-as-vagas-github-scheduler.service --since "today" --no-pager
~~~

Exemplos esperados:

~~~text
SCHEDULER_STATUS=wait reason=within_grace ...
SCHEDULER_STATUS=skip reason=collection_active ...
SCHEDULER_STATUS=skip reason=slot_succeeded ...
SCHEDULER_STATUS=dispatch reason=slot_missing ...
SCHEDULER_DISPATCHED=true ...
~~~

Se o token estiver ausente, o serviço termina com erro explícito sem chamar o GitHub. Se a API falhar, o GET tenta novamente com backoff para erros transitórios; o POST falha fechado e será reavaliado na próxima rodada. Nenhum segredo é impresso.
