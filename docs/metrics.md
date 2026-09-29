# OddVision — Dicionário de Métricas (MVP v1)

Este documento é a **fonte oficial** da metodologia das 8 métricas do MVP. Toda view do schema `analytics` que calcula uma métrica deve citar a seção correspondente daqui.

---

## 0. Como ler este documento

### 0.1 Classes de origem

Todo valor exibido pelo OddVision pertence a uma destas classes:

| Selo | Classe | Significado | Exemplo |
|---|---|---|---|
| 🟦 **FONTE** | Fornecido pelo StatsBomb | Valor copiado da fonte sem alteração | `statsbomb_xg` de uma finalização; `home_score` |
| 🟩 **DERIVAÇÃO** | Derivação estrutural do OddVision | Reinterpretação determinística da estrutura da fonte, sem julgamento analítico. Fica em `core` | `is_complete` = passe sem `outcome` |
| 🟨 **CÁLCULO** | Cálculo do OddVision | Aritmética simples sobre dados da fonte (soma, contagem, razão), com filtros declarados. Fica em `analytics` | xG total da equipe; `npxg`; `xg_acumulado` |
| 🟥 **CONVENÇÃO** | Convenção metodológica do OddVision | Envolve **escolhas** (limiares, exclusões, mapeamentos) que outras fontes fazem de forma diferente. Fica em `analytics` | `passes_progressivos`; `conducoes_progressivas`; "no alvo" |

**Regra:** métricas 🟥 **CONVENÇÃO** aparecem na interface com o rótulo **"OddVision v1"** e **não devem ser comparadas** com números de outros provedores (FBref, Opta, Wyscout etc.).

### 0.2 Resumo

| # | Métrica | Identificadores (`analytics`) | Classe | Nível |
|---|---|---|---|---|
| M1 | Placar e gols | `gols`, `gols_contra_a_favor`, `penaltis_disputa` | 🟦 placar · 🟨 gols por evento | Time, jogador |
| M2 | Finalizações e no alvo | `finalizacoes`, `finalizacoes_no_alvo` | 🟨 contagem · 🟥 mapeamento "no alvo" | Time, jogador |
| M3 | xG | `xg`, `npxg`, `npxg_por_finalizacao_sem_penalti` | 🟦 xG por finalização · 🟨 agregados | Time, jogador |
| M4 | Passes e % de acerto | `passes_tentados`, `passes_completos`, `pct_acerto_passes` | 🟥 regras de exclusão | Time, jogador |
| M5 | Passes progressivos | `passes_progressivos` | 🟥 **CONVENÇÃO OddVision v1** | Time, jogador |
| M6 | Conduções progressivas | `conducoes_progressivas` | 🟥 **CONVENÇÃO OddVision v1** | Time, jogador |
| M7 | Passes para a área | `passes_para_area` | 🟥 convenção geométrica | Time, jogador |
| M8 | xG acumulado | `xg_acumulado` | 🟨 cálculo | Time (série temporal) |

Os identificadores usam **minúsculas** (`xg`, `npxg`, `xg_acumulado`): no PostgreSQL, nomes sem aspas são convertidos para minúsculas. A grafia "xG" é usada apenas nos rótulos da interface. Veja [D14](decisions.md#d14--nomenclatura-inglês-no-core-português-minúsculo-no-analytics).

### 0.3 Convenções comuns a todas as métricas

| Termo | Definição | Classe |
|---|---|---|
| **Tempo de jogo válido** | `period ∈ {1, 2, 3, 4}`. **O período 5 (disputa de pênaltis) fica excluído de todas as métricas.** Na Copa 2022: 5 disputas, 106 eventos | 🟥 |
| **Passe completo** | `Pass` sem o campo `pass.outcome` na fonte, armazenado como `passes.is_complete = true`. Verificado: os 56.346 passes nessa condição têm recebedor | 🟩 |
| **Passe de jogo corrido** | `pass_type` nulo (passe regular), `'Recovery'` ou `'Interception'`. Exclui `'Corner'`, `'Free Kick'`, `'Goal Kick'`, `'Kick Off'` e `'Throw-in'` | 🟥 |
| **Área penal** | `x ≥ 102` **e** `18 ≤ y ≤ 62`, limites inclusivos (área de 18 × 44 jardas no campo de 120 × 80 do StatsBomb) | 🟥 |
| **Entrada na área** | Início **fora** da área **e** fim **dentro** da área | 🟥 |
| **Distância ao gol** | `dist_gol(x, y) = √((120 − x)² + (40 − y)²)`, em jardas, até o centro do gol adversário | 🟥 |
| **Coordenadas** | Relativas ao time que executa a ação, que sempre ataca da esquerda (x = 0) para a direita (x = 120). Evidência: o menor `x` de uma finalização na Copa 2022 é 59,0 | 🟦 |
| **Ordem temporal** | `(period, idx)`, **nunca** `minute`. O minuto não é monotônico entre períodos (P1 chega a 59; P2 começa em 45) | 🟩 |

### 0.4 Valores de referência

Os exemplos usam a **final da Copa 2022**, Argentina 3–3 França (`match_id = 3869685`).

- Foram calculados em 2026-09-29 por um **script exploratório independente** (Python puro, fora do pipeline), a partir do branch `master` da fonte.
- Servem como **valores de referência**: as views de `analytics` precisam reproduzi-los.
- **Pendência:** reconfirmar os valores quando o commit da fonte for fixado (passo 3 do roadmap).

---

## M1 — Placar e gols

| Campo | Conteúdo |
|---|---|
| **Nome** | Placar e gols (`gols`, `gols_contra_a_favor` = gols contra marcados pelo adversário em favor do time, `penaltis_disputa`) |
| **Classe** | 🟦 **FONTE** para o placar oficial (`matches.home_score`, `away_score`). 🟨 **CÁLCULO** para os gols por jogador e para o placar reconstruído a partir dos eventos. 🟨 **CÁLCULO** para o resultado da disputa de pênaltis (informação complementar) |
| **Definição** | Gols marcados por cada time no tempo regulamentar e na prorrogação. Os gols por jogador são atribuídos ao autor da finalização. O resultado da disputa de pênaltis é exibido **separadamente** e **não faz parte do placar** |
| **Origem dos dados** | `matches/43/106.json` → `home_score`, `away_score`. `events/{id}.json` → eventos `Shot` (`shot.outcome.name`) e `Own Goal For` / `Own Goal Against` |
| **Fórmula** | Placar oficial = `matches.home_score` / `away_score`. `gols_time` (reconstruído) = `#Shot[outcome = 'Goal'] + #'Own Goal For'`, com `period ∈ {1..4}` e `team_id` = time. `gols_jogador` = `#Shot[outcome = 'Goal']`, `period ∈ {1..4}`, `player_id` = jogador. `penaltis_disputa_time` = `#Shot[outcome = 'Goal', period = 5]` |
| **Eventos incluídos** | `Shot` com `outcome = 'Goal'`; `Own Goal For` (crédito ao time beneficiado) |
| **Eventos excluídos** | Período 5 (exceto para `penaltis_disputa`). `Own Goal Against` não é contado de novo: serve só para identificar o autor do gol contra na timeline. Gols contra **não** entram nos gols de nenhum jogador |
| **Valores ausentes** | `Own Goal For` não tem `player` na fonte (esperado; 3 casos na Copa). Placar nulo em `matches` é **erro** (NOT NULL). Partida sem período 5 → `penaltis_disputa` = `NULL`, não 0 |
| **Unidade** | Gols (inteiro ≥ 0) |
| **Limitações** | O placar oficial vem da fonte. Se a fonte tiver um erro de placar, o check C02 o detecta, mas não o corrige |
| **Exemplos** | Final: **Argentina 3 – 3 França**; disputa de pênaltis **4 – 2** (apenas informativo). Autores: Messi 2, Di María 1 (Argentina); Mbappé 3 (França) |
| **Critério de validação** | Check **C02**: placar reconstruído = placar oficial em **64/64** partidas (verificado na exploração: 0 divergências, 3 gols contra). Teste de referência: a final retorna 3–3 e 4–2 na disputa. Invariante: `Σ gols_jogador + gols_contra_a_favor = gols_time` |

---

## M2 — Finalizações e finalizações no alvo

| Campo | Conteúdo |
|---|---|
| **Nome** | Finalizações (`finalizacoes`) e finalizações no alvo (`finalizacoes_no_alvo`) |
| **Classe** | 🟨 **CÁLCULO** para a contagem de finalizações. 🟥 **CONVENÇÃO** para o mapeamento de "no alvo": a fonte não tem um campo booleano "no alvo", então o mapeamento dos resultados é escolha do OddVision, alinhada à prática comum |
| **Definição** | Finalizações são todas as tentativas de gol. Finalizações no alvo são as que iriam entrar sem a intervenção do goleiro, ou que entraram |
| **Origem dos dados** | `events/{id}.json` → `type.name = 'Shot'`; `shot.outcome.name` |
| **Fórmula** | `finalizacoes = #Shot`, com `period ∈ {1..4}`. `finalizacoes_no_alvo = #Shot[outcome ∈ {'Goal', 'Saved', 'Saved to Post'}]`, com `period ∈ {1..4}` |
| **Eventos incluídos** | Todo `Shot` em tempo válido: jogo corrido, faltas diretas, escanteios diretos e **pênaltis durante o jogo** |
| **Eventos excluídos** | Período 5. Na contagem de "no alvo", ficam de fora: `'Blocked'`, `'Off T'`, `'Wayward'`, `'Post'` (trave sem defesa) e `'Saved Off Target'` (defendida, mas iria para fora) |
| **Valores ausentes** | `shot.outcome` é obrigatório (NOT NULL). Um valor fora do domínio conhecido é **erro** (check C04) |
| **Unidade** | Contagem (inteiro ≥ 0) |
| **Limitações** | O mapeamento depende da grafia literal da fonte (`'Saved to Post'`, com "to" minúsculo). Classificar `'Post'` como fora do alvo é convenção; alguns provedores tratam o caso de outra forma |
| **Exemplos** | Final: Argentina **20** finalizações / **10** no alvo; França **10** / **5** |
| **Critério de validação** | Invariante `finalizacoes_no_alvo ≤ finalizacoes`. Check **C04**: o domínio de `outcome` é exatamente {Blocked, Goal, Off T, Post, Saved, Saved Off Target, Saved to Post, Wayward}. Check **C05**: `#core.shots` = `#core.events[type_name = 'Shot']`. Teste de referência da final |

---

## M3 — xG (e npxG)

| Campo | Conteúdo |
|---|---|
| **Nome** | xG (`xg`), npxG (`npxg`), npxG por finalização sem pênalti (`npxg_por_finalizacao_sem_penalti`) |
| **Classe** | 🟦 **FONTE** para o xG de cada finalização (`statsbomb_xg`), vindo do **modelo proprietário do StatsBomb**. **O OddVision não calcula xG.** 🟨 **CÁLCULO** para `xg` (soma), `npxg` (soma filtrada) e `npxg_por_finalizacao_sem_penalti` (razão) |
| **Definição** | O xG de uma finalização é a probabilidade estimada pelo StatsBomb de ela virar gol. O `xg` de um time ou jogador é a soma dessas probabilidades. O `npxg` é a mesma soma **sem pênaltis** |
| **Origem dos dados** | `events/{id}.json` → `shot.statsbomb_xg`, `shot.type.name` |
| **Fórmula** | `xg = Σ statsbomb_xg`, com `period ∈ {1..4}`. `npxg = Σ statsbomb_xg`, com `period ∈ {1..4}` e `shot_type ≠ 'Penalty'`. `npxg_por_finalizacao_sem_penalti = npxg ÷ #Shot[period ∈ {1..4}, shot_type ≠ 'Penalty']` |
| **Eventos incluídos** | `Shot` em tempo válido. No `xg`, inclusive pênaltis durante o jogo |
| **Eventos excluídos** | Período 5 (os pênaltis da disputa também têm xG = 0,7835 e ficam de fora). No `npxg` e na taxa, pênaltis durante o jogo também ficam de fora |
| **Valores ausentes** | `statsbomb_xg` nulo é **erro** (check C06). Gols contra não têm xG e não entram. Denominador zero → **`NULL`**, nunca 0 |
| **Unidade** | Gols esperados (decimal). Exibição com 2 casas em `xg`/`npxg` e 3 casas na taxa |
| **Limitações** | O modelo é proprietário e versionado (`matches.shot_fidelity_version`); **não é comparável** com o xG de outros provedores. Em uma única partida, o xG tem alta variância. Pênaltis têm xG fixo de 0,7835 (observado nos 64 pênaltis da Copa) e dominam o total quando existem |
| **Exemplos** | Final: **Argentina** xg 2,76 · npxg 1,97 · 19 finalizações sem pênalti · taxa **0,104**. **França** xg 2,27 · npxg 0,71 · 8 finalizações sem pênalti · taxa **0,088**. Na França, 1,57 dos 2,27 vêm de dois pênaltis: é por isso que o npxG existe |
| **Critério de validação** | Constraint `0 ≤ statsbomb_xg ≤ 1` + check **C06**. Invariante `npxg ≤ xg`. Aviso **C10**: xG de pênalti ≠ 0,7835. Invariante com M8: último ponto de `xg_acumulado` = `xg`. Teste de referência da final |

### Nomenclatura de xG

| Termo | Uso no OddVision | Motivo |
|---|---|---|
| **xG da finalização** | ✅ Atributo de **um** chute (`statsbomb_xg`) | Não é taxa; é uma propriedade do evento |
| **xG** / **npxG** | ✅ Somas | Definição direta |
| **npxG por finalização sem pênalti** | ✅ Única taxa exibida | Numerador e denominador excluem **os mesmos** eventos (pênaltis e período 5) |
| **xG por finalização** (com pênaltis) | ❌ **Não usado** | O valor fixo de 0,7835 dos pênaltis distorce a média; misturaria dois fenômenos diferentes |
| **npxG ÷ todas as finalizações** | ❌ **Não usado** | Numerador sem pênaltis e denominador com pênaltis: fórmula inconsistente |

---

## M4 — Passes e percentual de acerto

| Campo | Conteúdo |
|---|---|
| **Nome** | Passes tentados (`passes_tentados`), completos (`passes_completos`), percentual de acerto (`pct_acerto_passes`) |
| **Classe** | 🟥 **CONVENÇÃO**. A fonte indica o resultado de cada passe (🟦), mas **quais passes entram no denominador** é escolha do OddVision |
| **Definição** | Volume de passes feitos com o pé e a proporção que chegou a um companheiro |
| **Origem dos dados** | `events/{id}.json` → `type.name = 'Pass'`; `pass.type.name`; `pass.outcome.name` (a **ausência** do campo significa passe completo) |
| **Fórmula** | `passes_tentados = #Pass[period ∈ {1..4}, pass_type ≠ 'Throw-in' (ou nulo), outcome ∉ {'Unknown', 'Injury Clearance'} (ou nulo)]`. `passes_completos = #passes_tentados[is_complete]`. `pct_acerto_passes = 100 × passes_completos ÷ passes_tentados` |
| **Eventos incluídos** | Passes com o pé, **incluindo bolas paradas**: tiro de meta, falta, escanteio, saída de bola, passes de recuperação e interceptação |
| **Eventos excluídos** | `'Throw-in'` (cobrado com a mão). `outcome = 'Unknown'`: o resultado não foi determinado pela fonte (394 casos na Copa, cerca de 0,6%). `outcome = 'Injury Clearance'`: bola chutada para fora de propósito por causa de lesão, que não é tentativa de passe (42 casos). Período 5 |
| **Valores ausentes** | **`outcome` ausente significa passe completo, não dado faltante** (derivação 🟩 `is_complete`). `passes_tentados = 0` → `pct_acerto_passes = NULL` |
| **Unidade** | Contagem (inteiro); percentual de 0 a 100 com 1 casa decimal |
| **Limitações** | O percentual não mede dificuldade, risco nem valor do passe: um recuo seguro vale o mesmo que um passe entre linhas. Incluir bolas paradas é escolha; outras fontes podem excluí-las |
| **Exemplos** | Final: Argentina **538 / 661 = 81,4%**; França **414 / 544 = 76,1%** |
| **Critério de validação** | Invariante `passes_completos ≤ passes_tentados`. Reconciliação: completos + `Incomplete` + `Out` + `Pass Offside` = `passes_tentados`. Constraint `is_complete = (outcome IS NULL)`. Teste de referência da final |

---

## M5 — Passes progressivos (`passes_progressivos`)

> 🟥 **CONVENÇÃO OddVision v1. Não é uma definição universal.**
>
> Não existe uma definição oficial de "passe progressivo". Provedores e sites públicos usam regras diferentes, por exemplo:
> - O **FBref** mede o avanço em direção à linha de fundo em relação ao ponto mais avançado dos últimos passes e exclui passes do terço defensivo.
> - A **Wyscout** usa limiares diferentes conforme a metade do campo onde o passe começa e termina.
>
> A regra abaixo é **inspirada** nessas abordagens, mas **não é igual** a nenhuma delas. Portanto, os números **não são comparáveis** com esses provedores.
>
> *Pendência:* citar as definições externas com links verificados antes da publicação do projeto.

| Campo | Conteúdo |
|---|---|
| **Nome** | Passes progressivos (OddVision v1) |
| **Classe** | 🟥 **CONVENÇÃO OddVision v1** |
| **Definição** | Passe completo, de jogo corrido, que começa fora dos 40% defensivos do campo e aproxima a bola do gol adversário em pelo menos 10 jardas **ou** a leva para dentro da área |
| **Origem dos dados** | `core.events` (`x`, `y`, `period`) + `core.passes` (`end_x`, `end_y`, `is_complete`, `pass_type`). Todos são colunas tipadas vindas de `location`, `pass.end_location`, `pass.outcome` e `pass.type` |
| **Parâmetros** | `MIN_START_X = 48` (40% de 120: exclui o terço defensivo ampliado) · `MIN_GAIN_YD = 10` · gol em `(120, 40)` |
| **Fórmula** | `Δd = dist_gol(x, y) − dist_gol(end_x, end_y)`. **É progressivo** ⇔ `is_complete` **E** jogo corrido **E** `period ∈ {1..4}` **E** `x ≥ 48` **E** (`Δd ≥ 10` **OU** entrada na área) |
| **Eventos incluídos** | Passes completos de jogo corrido (`pass_type` nulo, `'Recovery'`, `'Interception'`) |
| **Eventos excluídos** | Passes incompletos; bolas paradas (`'Corner'`, `'Free Kick'`, `'Goal Kick'`, `'Kick Off'`, `'Throw-in'`); passes com `x < 48`; passes de dentro da área para dentro da área (não são "entrada"); período 5 |
| **Valores ausentes** | `end_location` nunca faltou na Copa (0 casos). Se faltar: o passe é excluído da métrica e contabilizado por um check. Não há imputação |
| **Unidade** | Contagem (inteiro ≥ 0) |
| **Escolhas e seus efeitos** | **Distância ao centro do gol, e não ganho em x:** favorece passes que se aproximam do gol, e não da bandeira de escanteio. Efeito colateral: passes diagonais de fora para o meio podem contar com pouco ganho em x. **Sem a regra de sequência** (os "últimos N passes" do FBref): simplificação deliberada do MVP, que fica para a v1.2 |
| **Limitações** | Os limiares são arbitrários. A métrica ignora pressão, linhas adversárias e a situação de quem recebe. Um passe curto de 10 jardas no terço final conta o mesmo que uma inversão longa |
| **Exemplos** | Final: Argentina **56**, França **39** |
| **Critério de validação** | (1) **Testes de fronteira** com eventos sintéticos: Δd = 9,99 → não conta; Δd = 10,00 → conta; `x` = 47,9 → não conta; `x` = 48,0 → conta; área → área → não conta; fora → exatamente em `x = 102` → conta. (2) Subconjunto: `passes_progressivos ≤` passes completos de jogo corrido. (3) Teste de referência da final. (4) Inspeção visual de 20 passes marcados e 20 não marcados, desenhados no campo |

---

## M6 — Conduções progressivas (`conducoes_progressivas`)

> 🟥 **CONVENÇÃO OddVision v1. Não é uma definição universal.**
>
> Aplica **a mesma regra geométrica da M5** às conduções. O FBref, por exemplo, usa uma regra diferente para conduções (exclui as que *terminam* na metade defensiva). O OddVision usa a mesma regra de início dos passes, por consistência. Veja [D09](decisions.md#d09--definição-das-métricas-progressivas-convenção-oddvision-v1).

| Campo | Conteúdo |
|---|---|
| **Nome** | Conduções progressivas (OddVision v1) |
| **Classe** | 🟥 **CONVENÇÃO OddVision v1** |
| **Definição** | Condução de bola (`Carry`) que começa fora dos 40% defensivos e aproxima a bola do gol adversário em pelo menos 10 jardas **ou** a leva para dentro da área |
| **Origem dos dados** | `core.events` (`x`, `y`, `period`) + `core.carries` (`end_x`, `end_y`), vindos de `location` e `carry.end_location` |
| **Parâmetros** | Os mesmos da M5: `MIN_START_X = 48`, `MIN_GAIN_YD = 10`, gol em `(120, 40)` |
| **Fórmula** | `Δd = dist_gol(x, y) − dist_gol(end_x, end_y)`. **É progressiva** ⇔ `period ∈ {1..4}` **E** `x ≥ 48` **E** (`Δd ≥ 10` **OU** entrada na área) |
| **Eventos incluídos** | Todos os `Carry` em tempo válido. Um `Carry` **não tem resultado** na fonte: a perda de bola aparece como outro evento (`Dispossessed`, `Miscontrol`) |
| **Eventos excluídos** | Conduções com `x < 48`; de dentro da área para dentro da área; período 5 |
| **Valores ausentes** | `carry.end_location` nunca faltou na Copa (0 casos). Se faltar: excluída e contabilizada por um check |
| **Unidade** | Contagem (inteiro ≥ 0) |
| **Limitações** | O StatsBomb **fragmenta** arrancadas em vários `Carry` (por exemplo, ao redor de um drible). Uma corrida de 15 jardas dividida em duas de 8 conta **zero**. Conduções muito curtas (entre o domínio e o passe) são frequentes e raramente progressivas. Os números não são comparáveis com outros provedores |
| **Exemplos** | Final: Argentina **30**, França **31** |
| **Critério de validação** | Os mesmos testes de fronteira da M5, aplicados a `Carry`. Check **C05**: `#core.carries` = `#core.events[type_name = 'Carry']`. Teste de referência da final. Inspeção visual por amostragem |

---

## M7 — Passes para a área (`passes_para_area`)

| Campo | Conteúdo |
|---|---|
| **Nome** | Passes para a área |
| **Classe** | 🟥 **CONVENÇÃO** (geométrica). A área é definida pelas dimensões do campo do StatsBomb; a restrição a jogo corrido é escolha do OddVision |
| **Definição** | Passes completos de jogo corrido que levam a bola de fora para dentro da área penal adversária |
| **Origem dos dados** | `core.events` (`x`, `y`) + `core.passes` (`end_x`, `end_y`, `is_complete`, `pass_type`) |
| **Fórmula** | `passes_para_area = #Pass[is_complete, jogo corrido, period ∈ {1..4}, NOT na_area(x, y), na_area(end_x, end_y)]`, onde `na_area(x, y) = x ≥ 102 AND y BETWEEN 18 AND 62` |
| **Eventos incluídos** | Passes completos de jogo corrido |
| **Eventos excluídos** | Bolas paradas (escanteio, falta, lateral, tiro de meta, saída), por consistência com a M5; passes que começam dentro da área; passes incompletos; período 5 |
| **Valores ausentes** | Como na M5 |
| **Unidade** | Contagem (inteiro ≥ 0) |
| **Limitações** | Passes perto da linha da área são sensíveis à precisão das coordenadas (`matches.xy_fidelity_version`). Cruzamentos de bola parada não entram e podem virar outra métrica no futuro. A métrica não diz se o passe gerou finalização |
| **Exemplos** | Final: Argentina **7**, França **3** |
| **Critério de validação** | Testes geométricos com pontos exatamente em `x = 102`, `y = 18` e `y = 62` (contam como dentro) e em `x = 101,99` (fora). Subconjunto dos passes completos de jogo corrido. Teste de referência da final |

---

## M8 — xG acumulado ao longo da partida (`xg_acumulado`)

| Campo | Conteúdo |
|---|---|
| **Nome** | xG acumulado |
| **Classe** | 🟨 **CÁLCULO** (soma acumulada do `statsbomb_xg` da fonte). A construção do eixo de tempo é uma **decisão de apresentação** documentada abaixo |
| **Definição** | Para cada time, a soma acumulada do xG das finalizações ao longo da partida, na forma de uma função em degraus |
| **Origem dos dados** | `core.shots` (`statsbomb_xg`) + `core.events` (`period`, `idx`, `ts_in_period`, `team_id`); eventos `Half End` para a duração de cada período |
| **Fórmula** | `xg_acumulado(t) = Σ statsbomb_xg` das finalizações do time com `(period, idx) ≤ t`. **Eixo de tempo:** `tempo_decorrido = Σ duração real dos períodos anteriores + ts_in_period`. A duração real de cada período vem do `ts_in_period` do seu `Half End`. **Rótulo:** estilo futebol, por exemplo "45+14" |
| **Eventos incluídos** | `Shot` em tempo válido, **incluindo pênaltis** (usa xG, não npxG). Cada pênalti aparece como um degrau de 0,7835 |
| **Eventos excluídos** | Período 5 |
| **Valores ausentes** | Herda a regra da M3. Partida sem finalizações de um time → a série desse time é constante em 0 |
| **Unidade** | Gols esperados acumulados (decimal, 2 casas) ao longo do tempo decorrido (segundos, rotulados em minutos) |
| **Limitações** | Mostra **criação de chances**, não domínio nem posse. É sensível a pênaltis. O eixo por tempo real torna partidas com acréscimos longos visualmente mais extensas, o que é intencional |
| **Exemplos** | Final: a curva termina em Argentina **2,76** e França **2,27**, com degraus de pênalti aos 23' (Argentina) e aos 80' e 118' (França) |
| **Critério de validação** | (1) O último ponto de cada time é igual ao `xg` da M3. (2) Série monotonicamente não decrescente. (3) Sem sobreposição temporal entre períodos: teste com uma partida cujo 1º tempo passou do minuto 45 (na Copa, o 1º tempo chegou ao minuto 59). (4) Ordenação por `(period, idx)`, conferida em teste |

---

## Histórico

| Data | Versão | Mudança |
|---|---|---|
| 2026-09-29 | v1 | Versão inicial aprovada com a especificação do MVP |
