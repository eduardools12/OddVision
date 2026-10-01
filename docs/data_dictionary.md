# OddVision — Dicionário de Dados (modelo inicial, MVP v1)

Este documento descreve o modelo **planejado** do banco `oddvision` (PostgreSQL 18). Nada foi criado ainda: o DDL será escrito no passo 4 do roadmap, a partir deste documento.

---

## 0. Convenções

### 0.1 Legenda das colunas

| Coluna da tabela | Significado |
|---|---|
| **Tipo** | Tipo PostgreSQL |
| **Nulo?** | `NÃO` = `NOT NULL`; `SIM` = opcional |
| **Origem no JSON** | Caminho no arquivo do StatsBomb. `[i]` = posição em um array. `⟨arquivo⟩` = valor que vem do **nome do arquivo**, não do conteúdo |
| **Classe** | 🟦 FONTE (copiado da fonte) · 🟩 DERIVAÇÃO (derivação estrutural determinística). Métricas 🟨/🟥 **não existem em `core`**: ficam em `analytics` (ver `metrics.md`) |

### 0.2 Regras gerais

1. **Nomes:** tabelas e colunas de `core` em inglês e minúsculas, alinhados aos nomes da fonte para facilitar o rastreio. Veja [D14](decisions.md#d14--nomenclatura-inglês-no-core-português-minúsculo-no-analytics).
2. **Objetos `{id, name}` da fonte:** por exemplo, `"type": {"id": 30, "name": "Pass"}`. Armazenamos o `name` em uma coluna `TEXT`. O `id` só é armazenado quando é uma chave de entidade (time, jogador, partida).
3. **Números reais:** `DOUBLE PRECISION` (equivale ao `float64` do pandas; evita conversões).
4. **Booleanos presentes só quando verdadeiros** (por exemplo, `pass.cross`, `under_pressure`): armazenados como `BOOLEAN NOT NULL DEFAULT false`. A ausência do campo na fonte vira `false` (🟩).
5. **`extra JSONB`:** guarda **as chaves da fonte que não foram mapeadas para colunas**. Regra precisa: `extra` = objeto de origem − chaves mapeadas. Veja [D07](decisions.md#d07--uso-de-extra-jsonb).
   - Pode ser lido por notebooks, checks (`sql/checks`) e exploração.
   - **Nunca** pode ser lido pelo schema `analytics` (garantido por teste).
   - Quando um campo do `extra` passar a ser usado em uma métrica, ele vira coluna tipada, com documentação e migração.
6. **`match_id` nos eventos e escalações:** os JSONs de `events` e `lineups` **não contêm `match_id`**. Ele vem do nome do arquivo (`events/3869685.json`) e é protegido pelo check C08.
7. **Caminhos confirmados (✅):** os 7 caminhos que estavam marcados ⚠️ foram confirmados no Passo 2, nos dados reais do commit fixado `4b73468f`. A evidência está em [`data_notes.md`](data_notes.md) §3 e em `notebooks/01_exploracao.ipynb`.

### 0.3 Schemas

| Schema | Conteúdo |
|---|---|
| `core` | 12 tabelas descritas abaixo |
| `analytics` | Somente views (seção 13). Não lê JSONB |

---

## 1. `core.competitions`

**Granularidade:** uma linha por par (competição, temporada).
**Fonte:** `competitions.json` (array de objetos).

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `competition_id` | `INTEGER` | NÃO | `competition_id` | 🟦 | ID da competição |
| `season_id` | `INTEGER` | NÃO | `season_id` | 🟦 | ID da temporada |
| `competition_name` | `TEXT` | NÃO | `competition_name` | 🟦 | Por exemplo, "FIFA World Cup" |
| `season_name` | `TEXT` | NÃO | `season_name` | 🟦 | Por exemplo, "2022" |
| `country_name` | `TEXT` | SIM | `country_name` | 🟦 | País ou região da competição |
| `competition_gender` | `TEXT` | NÃO | `competition_gender` | 🟦 | `male` / `female` |
| `competition_youth` | `BOOLEAN` | NÃO | `competition_youth` | 🟦 | Competição de base |
| `competition_international` | `BOOLEAN` | NÃO | `competition_international` | 🟦 | Competição de seleções |
| `extra` | `JSONB` | NÃO (`'{}'`) | demais chaves | 🟦 | `match_updated`, `match_updated_360`, `match_available`, `match_available_360` |

- **PK:** (`competition_id`, `season_id`)
- **Carga:** upsert (`ON CONFLICT DO UPDATE`). No MVP, só a linha (43, 106) é carregada; as outras 79 linhas do arquivo são ignoradas.

---

## 2. `core.teams`

**Granularidade:** uma linha por time (seleção).
**Fonte:** `matches/43/106.json` → objetos `home_team` e `away_team`.

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `team_id` | `INTEGER` | NÃO | `home_team.home_team_id` / `away_team.away_team_id` | 🟦 | ID do time |
| `team_name` | `TEXT` | NÃO | `home_team.home_team_name` / `away_team.away_team_name` | 🟦 | Nome |
| `team_gender` | `TEXT` | SIM | `home_team.home_team_gender` / `away_team.away_team_gender` | 🟦 | Gênero |
| `country_name` | `TEXT` | SIM | `home_team.country.name` / `away_team.country.name` | 🟦 | País |

- **PK:** `team_id`
- **Carga:** upsert.
- Dados que dependem da partida (grupo, técnicos) ficam em `matches.extra`, não aqui.

---

## 3. `core.players`

**Granularidade:** uma linha por jogador.
**Fonte:** `lineups/{match_id}.json` → `[i].lineup[j]`.

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `player_id` | `INTEGER` | NÃO | `lineup[j].player_id` | 🟦 | ID do jogador |
| `player_name` | `TEXT` | NÃO | `lineup[j].player_name` | 🟦 | Nome completo |
| `player_nickname` | `TEXT` | SIM | `lineup[j].player_nickname` | 🟦 | Nome curto (frequentemente nulo) |
| `country_name` | `TEXT` | SIM | `lineup[j].country.name` | 🟦 | Nacionalidade |

- **PK:** `player_id`
- **Carga:** upsert.
- **Qualidade:** o mesmo `player_id` com nomes diferentes entre arquivos gera o aviso C11.
- **Achado A2 (Passo 2):** na Copa 2022, 4 jogadores têm grafias diferentes entre arquivos (por exemplo, "Phil Foden" / "Philip Foden"). A regra determinística para escolher o nome gravado será decidida no Passo 6. A proposta é o nome mais frequente entre os arquivos.

---

## 4. `core.matches`

**Granularidade:** uma linha por partida.
**Fonte:** `matches/43/106.json` (array com 64 objetos).

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `match_id` | `INTEGER` | NÃO | `match_id` | 🟦 | ID da partida |
| `competition_id` | `INTEGER` | NÃO | `competition.competition_id` | 🟦 | Competição |
| `season_id` | `INTEGER` | NÃO | `season.season_id` | 🟦 | Temporada |
| `match_date` | `DATE` | NÃO | `match_date` | 🟦 | Data local |
| `kick_off` | `TIME` | SIM | `kick_off` (`"15:00:00.000"`) | 🟦 | Horário de início |
| `home_team_id` | `INTEGER` | NÃO | `home_team.home_team_id` | 🟦 | Mandante |
| `away_team_id` | `INTEGER` | NÃO | `away_team.away_team_id` | 🟦 | Visitante |
| `home_score` | `SMALLINT` | NÃO | `home_score` | 🟦 | Gols do mandante (regulamentar + prorrogação; **sem** disputa de pênaltis) |
| `away_score` | `SMALLINT` | NÃO | `away_score` | 🟦 | Gols do visitante (idem) |
| `match_week` | `SMALLINT` | SIM | `match_week` | 🟦 | Rodada |
| `competition_stage` | `TEXT` | SIM | `competition_stage.name` | 🟦 | Fase ("Group Stage", "Final"…) |
| `stadium_name` | `TEXT` | SIM | `stadium.name` | 🟦 | Estádio |
| `referee_name` | `TEXT` | SIM | `referee.name` | 🟦 | Árbitro. A chave `referee` **não existe** em 1 partida (achado A3): a transformação deve tolerar chave ausente |
| `match_status` | `TEXT` | SIM | `match_status` | 🟦 | Status de disponibilidade na fonte |
| `data_version` | `TEXT` | SIM | `metadata.data_version` | 🟦 | Versão do formato de dados |
| `shot_fidelity_version` | `TEXT` | SIM | `metadata.shot_fidelity_version` | 🟦 | Versão do modelo e precisão de finalizações (afeta o xG) |
| `xy_fidelity_version` | `TEXT` | SIM | `metadata.xy_fidelity_version` | 🟦 | Precisão das coordenadas |
| `last_updated` | `TIMESTAMP` | SIM | `last_updated` | 🟦 | Última atualização na fonte |
| `extra` | `JSONB` | NÃO (`'{}'`) | demais chaves | 🟦 | Origem menos o que virou coluna **de `matches` ou das tabelas geradas do mesmo objeto** (`competitions`, `teams`). Sobram: técnicos (`home_team.managers`, `away_team.managers`), grupos (`home_team_group`, `away_team_group`, nulos no mata-mata), `country.id` dos times, `id` e país de estádio e árbitro, `competition_stage.id`, `match_status_360` e `last_updated_360`. Implementado em `transform/matches.py` (`MATCH_MAPPED_PATHS`) |

**Chaves e restrições:**
- **PK:** `match_id`
- **FK:** (`competition_id`, `season_id`) → `competitions`; `home_team_id` → `teams`; `away_team_id` → `teams`
- **CHECK:** `home_team_id <> away_team_id`; `home_score >= 0`; `away_score >= 0`

---

## 5. `core.lineups`

**Granularidade:** uma linha por jogador relacionado em uma partida (inclui quem não entrou).
**Fonte:** `lineups/{match_id}.json` → `[i]` (time) → `lineup[j]` (jogador).

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `match_id` | `INTEGER` | NÃO | ⟨arquivo⟩ | 🟩 | Partida |
| `team_id` | `INTEGER` | NÃO | `[i].team_id` | 🟦 | Time do jogador na partida |
| `player_id` | `INTEGER` | NÃO | `lineup[j].player_id` | 🟦 | Jogador |
| `jersey_number` | `SMALLINT` | SIM | `lineup[j].jersey_number` | 🟦 | Número da camisa |
| `is_starter` | `BOOLEAN` | NÃO | `lineup[j].positions[0].start_reason = 'Starting XI'` ✅ | 🟩 | Titular. Coincide com o evento `Starting XI` em 128 de 128 times; independe da ordenação |
| `played` | `BOOLEAN` | NÃO | `len(lineup[j].positions) > 0` | 🟩 | Entrou em campo. Na final, 15 relacionados não entraram |
| `first_position` | `TEXT` | SIM | `positions[0].position`, **após ordenação estável** por (`from_period`, `from`) | 🟦 | Primeira posição ocupada (nula se não entrou). A fonte nem sempre ordena `positions` (achado A1) |
| `extra` | `JSONB` | NÃO (`'{}'`) | demais chaves | 🟦 | `positions` (intervalos completos: from/to, período, motivos), `cards` |

**Chaves e restrições:**
- **PK:** (`match_id`, `player_id`)
- **FK:** `match_id` → `matches` (`ON DELETE CASCADE`); `team_id` → `teams`; `player_id` → `players`
- **CHECK:** `NOT is_starter OR played`

**Observações:**
- `positions` é ordenado por `from`/`from_period` antes da derivação.
- Os minutos jogados, que seriam derivados de `positions`, estão **fora do MVP**.
- O check C09 lê `extra->'cards'`. Isso é permitido porque checks não são `analytics`.

---

## 6. `core.events`

**Granularidade:** um evento. É o núcleo do modelo.
**Fonte:** `events/{match_id}.json` (array; 4.407 eventos na final e 234.637 na Copa).

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `event_id` | `UUID` | NÃO | `id` | 🟦 | ID global do evento |
| `match_id` | `INTEGER` | NÃO | ⟨arquivo⟩ | 🟩 | Partida |
| `idx` | `INTEGER` | NÃO | `index` | 🟦 | Ordem do evento na partida (renomeado porque `index` é palavra reservada) |
| `period` | `SMALLINT` | NÃO | `period` | 🟦 | 1–2 tempos normais · 3–4 prorrogação · 5 disputa de pênaltis |
| `ts_in_period` | `INTERVAL` | NÃO | `timestamp` (`"00:00:39.227"`) | 🟦 | Tempo desde o início do período |
| `minute` | `SMALLINT` | NÃO | `minute` | 🟦 | Minuto de jogo. **Não é monotônico entre períodos**: P1 chega a 59 e P2 começa em 45 |
| `second` | `SMALLINT` | NÃO | `second` | 🟦 | Segundo (0–59) |
| `type_name` | `TEXT` | NÃO | `type.name` | 🟦 | Tipo do evento (33 tipos na Copa, por exemplo `Pass`, `Ball Receipt*`) |
| `team_id` | `INTEGER` | NÃO | `team.id` | 🟦 | Time que executa o evento |
| `player_id` | `INTEGER` | SIM | `player.id` | 🟦 | Jogador. Nulo em `Starting XI`, `Half Start`, `Half End`, `Tactical Shift`, `Own Goal For`, `Referee Ball-Drop` |
| `position_name` | `TEXT` | SIM | `position.name` | 🟦 | Posição do jogador no momento do evento |
| `possession` | `INTEGER` | NÃO | `possession` | 🟦 | Número sequencial da posse |
| `possession_team_id` | `INTEGER` | NÃO | `possession_team.id` | 🟦 | Time com a posse |
| `play_pattern` | `TEXT` | NÃO | `play_pattern.name` | 🟦 | Padrão de jogo ("Regular Play", "From Corner"…) |
| `x` | `DOUBLE PRECISION` | SIM | `location[0]` | 🟦 | Coordenada x (0–120), do ponto de vista de quem executa |
| `y` | `DOUBLE PRECISION` | SIM | `location[1]` | 🟦 | Coordenada y (0–80), com origem no canto superior |
| `duration` | `DOUBLE PRECISION` | SIM | `duration` | 🟦 | Duração do evento em segundos. Ausente em todos os `Ball Receipt*` e em 1 `Pass` (achado A4) |
| `under_pressure` | `BOOLEAN` | NÃO (`false`) | `under_pressure` (presente só se verdadeiro) | 🟩 | Ação sob pressão |
| `extra` | `JSONB` | NÃO (`'{}'`) | demais chaves | 🟦 | `type.id`, `related_events`, `tactics`, `counterpress`, `off_camera`, `out` e o **objeto específico** de tipos sem tabela própria (`duel`, `pressure`, `goalkeeper`, `clearance`, `dribble`, `interception`, `ball_receipt` etc.) |

**Chaves e restrições:**
- **PK:** `event_id`
- **UNIQUE:** (`match_id`, `idx`)
- **FK:** `match_id` → `matches` (`ON DELETE CASCADE`); `team_id` e `possession_team_id` → `teams`; `player_id` → `players`
- **CHECK:** `period BETWEEN 1 AND 5`; `second BETWEEN 0 AND 59`; `x BETWEEN 0 AND 120`; `y BETWEEN 0 AND 80`; `(x IS NULL) = (y IS NULL)`

**Observações:**
- Eventos sem `location` são esperados: 55 na final (por exemplo, `Half Start`, `Substitution`).
- Os objetos `shot`, `pass`, `carry`, `substitution` e os cartões **não** vão para `events.extra`. Eles vão para as tabelas específicas, e o que sobra deles vai para o `extra` dessas tabelas.

---

## 7. `core.shots`

**Granularidade:** uma finalização. Relação 1:1 com `events` onde `type_name = 'Shot'`.
**Fonte:** `events/{match_id}.json` → objeto `shot`.

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `event_id` | `UUID` | NÃO | `id` | 🟦 | Evento |
| `statsbomb_xg` | `DOUBLE PRECISION` | NÃO | `shot.statsbomb_xg` | 🟦 | **xG do modelo do StatsBomb.** O OddVision não calcula xG |
| `end_x` | `DOUBLE PRECISION` | NÃO | `shot.end_location[0]` | 🟦 | Destino x |
| `end_y` | `DOUBLE PRECISION` | NÃO | `shot.end_location[1]` | 🟦 | Destino y |
| `end_z` | `DOUBLE PRECISION` | SIM | `shot.end_location[2]` ✅ (opcional) | 🟦 | Altura no plano do gol. **Nula exatamente quando `outcome` ∈ {`Blocked`, `Wayward`}** (464 de 1.494 na Copa) |
| `outcome` | `TEXT` | NÃO | `shot.outcome.name` | 🟦 | Blocked, Goal, Off T, Post, Saved, Saved Off Target, Saved to Post, Wayward |
| `shot_type` | `TEXT` | NÃO | `shot.type.name` | 🟦 | Open Play, Free Kick, Penalty, Corner |
| `body_part` | `TEXT` | SIM | `shot.body_part.name` | 🟦 | Pé direito/esquerdo, cabeça… |
| `technique` | `TEXT` | SIM | `shot.technique.name` | 🟦 | Técnica (voleio, normal…) |
| `key_pass_id` | `UUID` | SIM | `shot.key_pass_id` | 🟦 | Passe que originou a finalização |
| `extra` | `JSONB` | NÃO (`'{}'`) | demais chaves de `shot` | 🟦 | `freeze_frame`, `first_time`, `one_on_one`, `aerial_won`, `deflected`, `open_goal` etc. |

**Chaves e restrições:**
- **PK:** `event_id`
- **FK:** `event_id` → `events` (`ON DELETE CASCADE`); `key_pass_id` → `events` (**`DEFERRABLE INITIALLY DEFERRED`**: conferida no `COMMIT`; sem isso, apagar uma partida falha porque o banco checa a chave antes de a cascata remover a finalização — descoberto no Passo 4, veja [D22](decisions.md))
- **CHECK:** `statsbomb_xg BETWEEN 0 AND 1`

---

## 8. `core.passes`

**Granularidade:** um passe. Relação 1:1 com `events` onde `type_name = 'Pass'`.
**Fonte:** `events/{match_id}.json` → objeto `pass`.

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `event_id` | `UUID` | NÃO | `id` | 🟦 | Evento |
| `recipient_id` | `INTEGER` | SIM | `pass.recipient.id` | 🟦 | Destinatário pretendido ou efetivo |
| `end_x` | `DOUBLE PRECISION` | NÃO | `pass.end_location[0]` | 🟦 | Destino x |
| `end_y` | `DOUBLE PRECISION` | NÃO | `pass.end_location[1]` | 🟦 | Destino y |
| `length` | `DOUBLE PRECISION` | SIM | `pass.length` | 🟦 | Comprimento (jardas) |
| `angle` | `DOUBLE PRECISION` | SIM | `pass.angle` | 🟦 | Ângulo (radianos) |
| `height` | `TEXT` | SIM | `pass.height.name` | 🟦 | Ground / Low / High Pass |
| `pass_type` | `TEXT` | SIM | `pass.type.name` | 🟦 | **Nulo = passe regular.** Recovery, Throw-in, Free Kick, Goal Kick, Corner, Interception, Kick Off |
| `body_part` | `TEXT` | SIM | `pass.body_part.name` | 🟦 | Parte do corpo |
| `outcome` | `TEXT` | SIM | `pass.outcome.name` | 🟦 | **Nulo = completo.** Incomplete, Out, Unknown, Pass Offside, Injury Clearance |
| `is_complete` | `BOOLEAN` | NÃO | ausência de `pass.outcome` | 🟩 | Passe completo |
| `is_cross` | `BOOLEAN` | NÃO (`false`) | `pass.cross` | 🟩 | Cruzamento |
| `is_switch` | `BOOLEAN` | NÃO (`false`) | `pass.switch` | 🟩 | Inversão de jogo |
| `is_through_ball` | `BOOLEAN` | NÃO (`false`) | `pass.through_ball` ✅ | 🟩 | Passe em profundidade. Equivale a `pass.technique.name = 'Through Ball'` (os mesmos 254 passes na Copa) |
| `is_shot_assist` | `BOOLEAN` | NÃO (`false`) | `pass.shot_assist` | 🟩 | Passe que gerou finalização sem gol |
| `is_goal_assist` | `BOOLEAN` | NÃO (`false`) | `pass.goal_assist` | 🟩 | Assistência para gol |
| `extra` | `JSONB` | NÃO (`'{}'`) | demais chaves de `pass` | 🟦 | `technique`, `assisted_shot_id`, `aerial_won`, `deflected`, `inswinging`, `outswinging`, `cut_back`, `miscommunication`, `no_touch`, `straight` etc. |

**Chaves e restrições:**
- **PK:** `event_id`
- **FK:** `event_id` → `events` (`ON DELETE CASCADE`); `recipient_id` → `players`
- **CHECK:** `is_complete = (outcome IS NULL)`; `end_x BETWEEN 0 AND 120`; `end_y BETWEEN 0 AND 80`

**Observação:** `assisted_shot_id` fica em `extra` porque o xA está fora do MVP. Vira coluna quando entrar.

---

## 9. `core.carries`

**Granularidade:** uma condução. Relação 1:1 com `events` onde `type_name = 'Carry'`.
**Fonte:** `events/{match_id}.json` → objeto `carry` (contém só `end_location`).

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `event_id` | `UUID` | NÃO | `id` | 🟦 | Evento |
| `end_x` | `DOUBLE PRECISION` | NÃO | `carry.end_location[0]` | 🟦 | Destino x |
| `end_y` | `DOUBLE PRECISION` | NÃO | `carry.end_location[1]` | 🟦 | Destino y |

- **PK:** `event_id`
- **FK:** `event_id` → `events` (`ON DELETE CASCADE`)
- **CHECK:** coordenadas no intervalo do campo
- Sem `extra`: o objeto `carry` não tem outras chaves na Copa 2022.

---

## 10. `core.cards`

**Granularidade:** um cartão mostrado.
**Fonte:** eventos `Foul Committed` e `Bad Behaviour` que tenham cartão.

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `event_id` | `UUID` | NÃO | `id` | 🟦 | Evento de origem |
| `card_type` | `TEXT` | NÃO | `foul_committed.card.name` ou `bad_behaviour.card.name` ✅ | 🟦 | `Yellow Card` / `Second Yellow` / `Red Card`. Não há outro caminho para `card` nos eventos; 228 cartões conciliados 1:1 com as escalações |

- **PK:** `event_id`
- **FK:** `event_id` → `events` (`ON DELETE CASCADE`)
- **Domínio:** check C04.
- **Conciliação:** aviso C09 contra `lineups.extra->'cards'`.
- Jogador, time e momento vêm de `core.events`, sem duplicação.

---

## 11. `core.substitutions`

**Granularidade:** uma substituição.
**Fonte:** eventos `Substitution`.

| Coluna | Tipo | Nulo? | Origem no JSON | Classe | Significado |
|---|---|---|---|---|---|
| `event_id` | `UUID` | NÃO | `id` | 🟦 | Evento. O jogador que **sai** é `core.events.player_id` |
| `player_on_id` | `INTEGER` | NÃO | `substitution.replacement.id` ✅ | 🟦 | Jogador que **entra** |
| `reason` | `TEXT` | SIM | `substitution.outcome.name` ✅ | 🟦 | Domínio na Copa: `Tactical` / `Injury` |

- **PK:** `event_id`
- **FK:** `event_id` → `events` (`ON DELETE CASCADE`); `player_on_id` → `players`

---

## 12. `core.ingestion_log`

**Granularidade:** um arquivo bruto.
**Fonte:** `data/manifests/statsbomb_manifest.csv` (gerado pela ingestão), com o momento da carga acrescentado.

| Coluna | Tipo | Nulo? | Origem | Classe | Significado |
|---|---|---|---|---|---|
| `file_path` | `TEXT` | NÃO | manifest | 🟩 | Caminho relativo a `data/raw/statsbomb/` |
| `source_url` | `TEXT` | NÃO | manifest | 🟩 | URL exata, com o commit |
| `source_commit` | `TEXT` | NÃO | manifest | 🟩 | SHA do commit fixado |
| `sha256` | `CHAR(64)` | NÃO | manifest | 🟩 | Hash do arquivo |
| `size_bytes` | `BIGINT` | NÃO | manifest | 🟩 | Tamanho |
| `record_count` | `INTEGER` | SIM | manifest | 🟩 | Nº de elementos do array JSON (eventos, partidas, times) |
| `downloaded_at` | `TIMESTAMPTZ` | NÃO | manifest | 🟩 | Momento do download |
| `loaded_at` | `TIMESTAMPTZ` | SIM | pipeline | 🟩 | Momento da última carga **deste arquivo** no `core`. Fica nulo para arquivos ainda não carregados (no Passo 5, só `competitions.json` e o arquivo de partidas; `events` e `lineups` passam a ter valor nos Passos 6 a 8 e 13). Registrar o manifest de novo nunca apaga um `loaded_at` já gravado |

- **PK:** `file_path`
- Sem FK: é uma tabela de rastreabilidade.
- Esperado no MVP: **130 linhas**.

---

## 13. Schema `analytics` (views planejadas)

As fórmulas estão em [`metrics.md`](metrics.md). Todas as colunas de `analytics` são 🟨 **CÁLCULO** ou 🟥 **CONVENÇÃO**, exceto as copiadas diretamente da fonte, como `statsbomb_xg` e o placar oficial. **Nenhuma view lê colunas `extra`.**

| View | Granularidade | Conteúdo principal |
|---|---|---|
| `analytics.match_summary` | partida | Placar oficial, placar reconstruído, `penaltis_disputa` |
| `analytics.match_lineups` | partida × jogador | Camisa, `is_starter`, `played`, `first_position` |
| `analytics.team_match_stats` | partida × time | M1–M7 |
| `analytics.player_match_stats` | partida × jogador | M1–M7 |
| `analytics.shot_events` | finalização | Tempo, jogador, tipo, resultado, `statsbomb_xg`, `is_no_alvo`, coordenadas para o mapa |
| `analytics.pass_events` | passe | `is_jogo_corrido`, `is_progressivo`, `is_passe_para_area`, coordenadas |
| `analytics.carry_events` | condução | `is_progressiva`, coordenadas |
| `analytics.xg_timeline` | partida × time × degrau | `tempo_decorrido_s`, `rotulo_tempo`, `xg_acumulado` |
| `analytics.match_timeline` | incidente | Gols, gols contra, cartões, substituições |

Os parâmetros das convenções (`MIN_START_X`, `MIN_GAIN_YD`, limites da área) são declarados em uma CTE `params` no topo de cada view que os usa, com um comentário apontando para `metrics.md`.
