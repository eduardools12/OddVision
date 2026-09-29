# OddVision — Notas da exploração dos dados (Passo 2)

| Campo | Valor |
|---|---|
| Data | 2026-09-29 |
| Evidência | [`notebooks/01_exploracao.ipynb`](../notebooks/01_exploracao.ipynb) (Python puro, executado do zero sem erros) |
| Escopo | Copa do Mundo 2022 (`competition_id = 43`, `season_id = 106`): 64 partidas |

---

## 1. Fonte fixada

| Item | Valor |
|---|---|
| Repositório | **`hudl/open-data`**. O antigo `statsbomb/open-data` foi transferido e ainda redireciona |
| Commit fixado | `4b73468fc5b0f1950f9f66fada70ad3a4f9327cb` (2026-09-07, topo do `master` em 2026-09-29) |
| URL base | `https://raw.githubusercontent.com/hudl/open-data/4b73468fc5b0f1950f9f66fada70ad3a4f9327cb/data/` |
| Arquivos da ingestão | **130** = 1 `competitions.json` + 1 `matches/43/106.json` + 64 `events/*.json` + 64 `lineups/*.json` |

- As URLs pelos nomes `hudl` e `statsbomb` devolvem o mesmo arquivo, byte a byte (conferido com `events/3869685.json`, 3.757.121 bytes).
- O Passo 3 usa o nome canônico `hudl/open-data`.

## 2. Números confirmados no commit fixado

Os números são **iguais** aos do perfil exploratório feito no `master` em 2026-09-29.

| Fato | Valor |
|---|---|
| Partidas / seleções | 64 / 32 |
| Eventos | 234.637 (final: 4.407), 33 tipos, `id` único entre todas as partidas |
| `index` | Contínuo de 1 a N em todas as partidas |
| Eventos por período | P1 116.337 · P2 112.708 · P3 2.885 · P4 2.601 · P5 106 |
| Minuto por período | P1 0–**59** · P2 **45**–103 · P3 90–108 · P4 105–124 · P5 120–127 |
| Coordenadas | `location` sempre com 2 elementos; x ∈ [0,1; 120]; y ∈ [0,1; 80] |
| Finalizações | 1.494; menor `x` (P1–P4) = 59,0; xG de pênalti = 0,7835 em todos os 64 pênaltis |
| Placar reconstruído (C02) | 0 divergências em 64 partidas; 3 gols contra |
| Times dos eventos (C08) | 0 eventos de time fora da partida |
| Jogadores dos eventos (FK) | 0 ausentes das escalações (inclusive os recebedores de passe) |
| Disputas de pênaltis | 5 partidas: 3869219, 3869220, 3869321, 3869420, 3869685 |
| Versões (`metadata`) | Iguais nas 64 partidas: `data_version 1.1.0`, `shot_fidelity_version 2`, `xy_fidelity_version 2` |

## 3. Os 7 caminhos ⚠️: resolução

| # | Caminho | Resultado | Evidência (notebook) |
|---|---|---|---|
| 1 | **Titular:** `positions[0].start_reason = 'Starting XI'` | ✅ **Confirmado.** 1.408 titulares = 128 combinações de time e partida × 11. A regra coincide com o evento `Starting XI` em 128 de 128 times, e a ordenação das posições não muda nenhum titular | Seções 5 e 5.1 |
| 2 | **`end_z`:** `shot.end_location[2]` | ✅ **Confirmado e opcional.** 3 elementos em 1.030 finalizações; **2 elementos (sem z) em 464, exatamente os resultados `Blocked` (379) e `Wayward` (85)** | Seção 6 |
| 3 | **Passe em profundidade:** `pass.through_ball` | ✅ **Confirmado.** 254 passes com `through_ball = true`, os mesmos 254 com `technique = 'Through Ball'`. Os dois caminhos são equivalentes nesta fonte; usamos `pass.through_ball` | Seção 7 |
| 4 | **Cartão:** `foul_committed.card.name` | ✅ **Confirmado.** 184 ocorrências | Seção 8 |
| 5 | **Cartão:** `bad_behaviour.card.name` | ✅ **Confirmado.** 44 ocorrências. Não há chave `card` em nenhum outro lugar dos eventos. Total de 228 = 228 cartões nas escalações, com conciliação exata por (partida, jogador, tipo) | Seção 8 |
| 6 | **Substituição (entra):** `substitution.replacement.id` | ✅ **Confirmado** nas 587 substituições | Seção 9 |
| 7 | **Motivo:** `substitution.outcome.name` | ✅ **Confirmado.** Domínio: `Tactical` (547) e `Injury` (40) | Seção 9 |

Domínio de `card_type`: `Yellow Card` (224), `Second Yellow` (3), `Red Card` (1).

## 4. Achados novos (não previstos na spec)

| # | Achado | Impacto | Onde foi tratado |
|---|---|---|---|
| A1 | **`positions` nem sempre vem em ordem cronológica.** 56 jogadores têm "Tactical Shift" como primeira posição listada. Após ordenar por `(from_period, from)`, 11 passam a começar com substituição e **45 continuam com "Tactical Shift"**: são reservas cuja entrada a fonte registrou como mudança tática. 28 jogadores têm empate na chave de ordenação | `first_position` exige ordenação **estável** antes da derivação. O OddVision **não** usa `start_reason` para identificar reservas utilizados; usa `played AND NOT is_starter` | `data_dictionary.md` §5 |
| A2 | **4 jogadores com mais de um nome** entre arquivos: 4354 (Phil / Philip Foden), 50494 (Yeremy / Yeremi Pino Santos), 10603 (`N'Diaye` / `N''Diaye`, com apóstrofo duplicado) e 24475 (Awer Mabil / Awer Denis Bul Mabil) | O upsert de `players` precisa de uma regra **determinística** para o nome. Proposta, a decidir no Passo 6: usar o nome mais frequente entre os arquivos (os 4 casos têm maioria clara). O aviso C11 continua ativo | `data_dictionary.md` §3 |
| A3 | **A chave `referee` está ausente** em 1 partida | `referee_name` é nulo. A transformação deve tolerar a chave ausente, não apenas o valor `null` | `data_dictionary.md` §4 |
| A4 | **1 passe sem `duration`** (além de todos os `Ball Receipt*`) | `duration` continua anulável | `data_dictionary.md` §6 |
| A5 | **`minute` é o minuto decorrido e começa em 0** | O rótulo em estilo futebol é `minute + 1` (por exemplo, `minute = 22` vira "23'"). Afeta a M8 e a timeline | `metrics.md` M8 |
| A6 | **`Half End`: exatamente 2 por (partida, período)**, um por time, com `timestamp` **idêntico** (143 pares, diferença máxima de 0 s) | A duração de um período pode usar qualquer um dos dois; a spec usa o maior, por segurança | `metrics.md` M8 |
| A7 | **O repositório da fonte mudou de dono** (`hudl/open-data`) | O Passo 3 usa o nome novo; o commit fixado garante o conteúdo | Seção 1 deste documento |

## 5. Partidas-sentinela

As sentinelas foram escolhidas pelos dados, na seção 12 do notebook. Os Passos 6 a 10 usam estas 3 partidas antes da escala para 64.

| match_id | Partida | Por quê |
|---|---|---|
| **3869685** | Argentina x France (final, 18/12/2022) | Disputa de pênaltis, prorrogação, 3 pênaltis durante o jogo |
| **3857276** | Canada x Morocco (01/12/2022) | Gol contra. É a primeira, por data, das 3 partidas com gol contra (as outras são 3857292 e 3869151) |
| **3857271** | England x Iran | **1º tempo mais longo da Copa**: 59:03 de duração real (o `minute` chega a 59). É o caso que quebraria uma ordenação por minuto |

## 6. Valores de referência

Os valores estão em [`tests/fixtures/reference_final_3869685.json`](../tests/fixtures/reference_final_3869685.json). Foram copiados à mão da seção 13 e **são iguais** aos exemplos de `metrics.md`.
