# Tutorial: How This Generative-Agents Simulator Works (and How to Bend It)

This repo is a fork of the code behind *Generative Agents: Interactive Simulacra of Human Behavior* (Park et al., 2023, "Smallville"). It keeps the original architecture and adds structured LLM outputs, a headless mode, automatic checkpointing, map-label remapping, "noncognitive/nonembodied" agent flags, urgency-based event prioritization, an MQTT transport, and several experiment scenarios (elections, hide-and-seek, search-and-rescue, bomb-disposal "ops").

The tutorial covers the concepts first, then shows where each concept lives in the code and config. Paths are relative to the repo root unless noted. `file:line` references point at the code as of this writing.

---

## Contents

1. [The 60-second mental model](#1-the-60-second-mental-model)
2. [Paper terms and code names](#2-paper-terms-and-code-names)
3. [Repository map](#3-repository-map)
4. [Architecture: backend, frontend, and the file handshake](#4-architecture-backend-frontend-and-the-file-handshake)
5. [One simulation step, end to end](#5-one-simulation-step-end-to-end)
6. [Inside an agent: the cognitive loop](#6-inside-an-agent-the-cognitive-loop)
7. [Memory in detail](#7-memory-in-detail)
8. [The world: maps, sectors, arenas, objects](#8-the-world-maps-sectors-arenas-objects)
9. [The LLM layer and prompt templates](#9-the-llm-layer-and-prompt-templates)
10. [Initial state vs. outputs](#10-initial-state-vs-outputs)
11. [Running simulations](#11-running-simulations)
12. [Interviewing agents (yes, it's built in)](#12-interviewing-agents-yes-its-built-in)
13. [Customization cookbook](#13-customization-cookbook)
14. [The bundled scenarios](#14-the-bundled-scenarios)
15. [Analysis and utility scripts](#15-analysis-and-utility-scripts)
16. [Limitations, bugs, and improvement opportunities](#16-limitations-bugs-and-improvement-opportunities)
17. [Cheat sheet](#17-cheat-sheet)

---

## 1. The 60-second mental model

- A **simulation** is a folder under `environment/frontend_server/storage/<sim_name>/`. It holds the world clock (`reverie/meta.json`), the agents' full mental state (`personas/<Name>/bootstrap_memory/`), and, after running, per-step logs (`environment/`, `movement/`).
- You never start from nothing. You always **fork** an existing simulation: the backend copies `<origin>` to `<target>` and runs from there. The "base" simulations (`base_*`) are hand-written starting states.
- Time advances in **steps**. Each step is `sec_per_step` game-seconds (10 by default), so 360 steps is one game hour and 8,640 steps is one game day.
- At every step, every agent runs **perceive → retrieve → plan → reflect → execute**. The result is one tile of movement, an emoji, a text description of what they are doing, and (sometimes) a conversation.
- Nearly every "decision" is an LLM call: when to wake up, the day's plan, the hourly schedule, how to break a task into 5–15 minute sub-tasks, which building/room/object to use, whether to talk to someone, what to say, how important a memory is, what insights to draw.
- **Memory** is a time-ordered list of natural-language nodes (events, thoughts, chats) with embeddings. It is retrieved by a weighted mix of recency, importance, and relevance.
- **Personality** is plain text in `scratch.json` (`innate`, `learned`, `currently`, `lifestyle`, `daily_plan_req`), pasted into almost every prompt. **Background knowledge** can be injected as "whispers", which become thought memories.
- **Interviews** are built in: `call -- analysis <Name>` in the backend shell, or `persona.open_convo_session("analysis", direct=True, question=...)` from Python.

---

## 2. Paper terms and code names

The original author used internal names that differ from the paper. You'll see both.

| Paper | Code | Where |
|---|---|---|
| Generative agent | `Persona` | `reverie/backend_server/persona/persona.py` |
| The simulation / game server | "Reverie", `ReverieServer` | `reverie/backend_server/reverie.py` |
| Memory stream | `AssociativeMemory` (`a_mem`) | `persona/memory_structures/associative_memory.py` |
| Memory object | `ConceptNode` | same file |
| Agent summary / seed description | "Identity Stable Set" (ISS), `Scratch.get_str_iss()` | `persona/memory_structures/scratch.py:407` |
| Short-term / working state | `Scratch` (`scratch`) | `persona/memory_structures/scratch.py` |
| Environment tree knowledge | `MemoryTree` (`s_mem`), spatial memory | `persona/memory_structures/spatial_memory.py` |
| Importance | `poignancy` | node field; scored by LLM |
| Smallville | "the Ville", `maze_name: "the_ville"` | `environment/frontend_server/static_dirs/assets/the_ville/` |
| Area hierarchy | world → sector → arena → game_object | `maze.py`, `special_blocks/*.csv` |
| Inception / seeding a memory | "whisper" | `converse.py:294` (`load_history_via_whisper`) |
| Interview | `open_convo_session("analysis")` | `converse.py:312` |
| Emoji status | `pronunciatio` | `scratch.act_pronunciatio` |

---

## 3. Repository map

```
agentic_collab/
├── README.md, README_origin.md     # setup + the original repo's README
├── TUTORIAL.md                      # this file
├── PROGRESS.md                      # append-only work log
├── pyproject.toml, uv.lock          # deps (uv); Python 3.11
├── .env                             # OPENAI_API_KEY=... (gitignored; you create it)
├── openai_config.json               # optional LLM overrides (gitignored; you create it)
├── run_backend.sh                   # interactive backend (reverie.py)
├── run_backend_automatic.sh         # checkpointing runner (automatic_execution.py)
├── run_frontend.sh                  # Django visualizer on :8000
├── run_mqtt.sh                      # start a mosquitto broker (MQTT mode only)
│
├── reverie/
│   ├── compress_sim_storage.py      # pack a finished sim for the /demo/ viewer
│   └── backend_server/              # ← THE SIMULATION ENGINE (run from this dir)
│       ├── reverie.py               # ReverieServer: fork, main loop, save, CLI commands
│       ├── automatic_execution.py   # multi-stage runner with checkpoints + error recovery
│       ├── maze.py                  # world grid, tile metadata, events on tiles
│       ├── path_finder.py           # BFS pathfinding over the collision grid
│       ├── utils.py                 # config: API keys, model, paths, debug flag, MQTT
│       ├── mqtt_client.py           # MQTT transport (optional)
│       ├── survey.ipynb             # batch-interview agents across checkpoints (elections)
│       └── persona/
│           ├── persona.py           # Persona: owns memories, runs the cognitive loop
│           ├── cognitive_modules/   # perceive, retrieve, plan, reflect, execute, converse
│           ├── memory_structures/   # scratch, associative_memory, spatial_memory
│           └── prompt_template/     # every LLM prompt + the OpenAI wrapper
│               ├── run_gpt_prompt.py      # index: re-exports every run_gpt_prompt_* function
│               ├── gpt_structure.py       # OpenAI/Azure clients, retries, embeddings, cost log
│               ├── common.py              # shared pydantic response models
│               ├── v1/, v2/, v3_ChatGPT/  # the live prompt modules (*.py)
│               ├── */unused/              # older .txt templates, not loaded
│               ├── eg_prompts/            # example rendered prompts (documentation only)
│               └── safety/                # "anthropomorphization" safety scorer for interviews
│
├── environment/frontend_server/     # Django + Phaser visualizer (also hosts all sim data)
│   ├── storage/                     # ← ALL SIMULATIONS (inputs and outputs) live here
│   ├── compressed_storage/          # packed sims for /demo/
│   ├── temp_storage/                # curr_sim_code.json, curr_step.json (backend→frontend signal)
│   ├── static_dirs/assets/the_ville/
│   │   ├── matrix/maze/*.csv        # the grid layers (collision, sector, arena, object, spawn)
│   │   ├── matrix/special_blocks/*.csv  # color-ID → name tables for those layers
│   │   ├── matrix/maze_meta_info.json   # width/height/tile size
│   │   ├── visuals/the_ville_jan7.json  # Tiled map rendered by Phaser
│   │   └── agent_history_init_n3.csv, _n25.csv   # whisper files
│   ├── static_dirs/assets/characters/   # per-agent sprite PNGs (used by /demo/)
│   ├── templates/                   # home (live/replay), demo, persona_state, path_tester
│   └── translator/views.py          # HTTP endpoints
│
├── mqtt_gateway/                    # optional MQTT gateway (for non-browser frontends)
├── utils/                           # print conversations, monitor headless runs, cleanup, cost viz
├── nlp/                             # conversation text mining (keywords, topics, summaries)
├── elections/                       # election-experiment notes + NEGex dataset
├── logs/                            # stdout logs of runs (tee'd by the run scripts)
└── api/tf/main.tf                   # Terraform for an AWS EC2 box (deployment helper)
```

---

## 4. Architecture: backend, frontend, and the file handshake

Two processes cooperate, and in the default mode they talk only through JSON files on disk.

```
            ┌───────────────────────────────┐        ┌────────────────────────────────┐
            │ Backend: reverie.py            │        │ Frontend: Django + Phaser (JS)  │
            │ (reverie/backend_server)       │        │ (environment/frontend_server)   │
            │                                │        │                                 │
 step N:    │ waits for environment/N.json ◄─┼────────┼─ browser writes agent x,y        │
            │ runs every agent's cognition   │        │                                 │
            │ writes movement/N.json ────────┼────────┼─► browser animates, then        │
            │ step += 1, time += 10s         │        │   writes environment/N+1.json   │
            └───────────────────────────────┘        └────────────────────────────────┘
                      both under environment/frontend_server/storage/<sim>/
```

- `environment/<step>.json` holds agent positions: `{"Isabella Rodriguez": {"maze": "the_ville", "x": 72, "y": 14}, ...}`.
- `movement/<step>.json` holds what each agent does next: target tile, emoji, description, current chat. It also carries `meta.curr_time`.
- **Headless mode** removes the browser. After computing step N the backend writes `environment/N+1.json` itself (`reverie.py:378-392`), so it drives itself. This is the most reliable way to run (see §16).
- **MQTT mode** (`--mqtt`, or answering `y` at the prompt) publishes movements to `backend/movement` and listens on `gateway/environment` in place of the files. It's meant for external frontends such as robots or game engines, routed through `mqtt_gateway/`. Treat it as experimental.
- The backend also writes `temp_storage/curr_sim_code.json` and `curr_step.json`. That is how `/simulator_home` knows which sim to show.

The backend is always launched from `reverie/backend_server/`, because all paths in `utils.py` are relative to it (`../../environment/frontend_server/storage`).

---

## 5. One simulation step, end to end

Code: `ReverieServer.start_server` (`reverie.py:394`) and `_process_environment_update` (`reverie.py:215`).

1. **Wait** until `storage/<sim>/environment/<step>.json` exists.
2. **Reset object states.** Objects that agents "used" last step (for example `bed` is `being slept in`) go back to idle (`game_obj_cleanup`).
3. **Sync positions.** Each agent's event is moved to its new tile on the backend grid. If an agent has arrived at its destination (`planned_path` empty), its *object event* is stamped on that tile, so others can perceive that "the coffee machine is brewing coffee".
4. **Think.** For each persona, `persona.move(maze, personas, tile, curr_time)` runs the cognitive loop (§6) and returns `(next_tile, emoji, description)`.
5. **Write** `movement/<step>.json` (and publish to MQTT if enabled).
6. **Advance** `step += 1`, `curr_time += sec_per_step`.
7. In headless mode, **write** `environment/<step+1>.json` with the new positions.

**Save** (`fin` or `save`, `reverie.py:471`) writes `reverie/meta.json` (clock, step, persona list, remaps) and each persona's `bootstrap_memory/` (scratch, spatial memory, associative memory). **Nothing about agent minds is persisted until you save.** The per-step movement files are the only continuous output.

Agents are processed **sequentially** in `meta.json` order within a step, and they share the same `personas` dict. Agent B at step N can therefore see state that agent A changed earlier in the same step, such as a conversation A started with B.

---

## 6. Inside an agent: the cognitive loop

Entry point: `Persona.move` (`persona/persona.py:180`).

```
move()
 ├─ new_day?  ("First day" if scratch.curr_time is None; "New day" if the date changed)
 ├─ perceive(maze)            → new ConceptNodes (events) written into a_mem
 ├─ retrieve(perceived)       → for each new event: related events + thoughts
 ├─ plan(maze, personas, new_day, retrieved)
 │    ├─ _long_term_planning  (if new day): wake hour, revise identity, daily plan, hourly schedule
 │    ├─ _determine_action    (if current action finished): decompose schedule, choose place/object
 │    ├─ _choose_retrieved    pick ONE perceived event to consider (LLM urgency ranking if several)
 │    └─ _should_react        chat? wait? ignore? → _chat_react / _wait_react rewrite the schedule
 ├─ reflect()                 (skipped for noncognitive agents)
 └─ execute(maze, personas, plan) → path-find to target, return next tile
```

### 6.1 Perceive — `cognitive_modules/perceive.py`

- **Space:** every tile within `vision_r` is added to the spatial memory tree, so agents *discover* rooms and objects as they walk around.
- **Events:** events on nearby tiles *in the same arena* (room) are collected, sorted by distance, and truncated to the nearest `att_bandwidth`.
- **Novelty filter:** an event is stored only if its (subject, predicate, object) triple isn't among the last `retention` events in memory.
- Each stored event gets an **embedding** (API call unless cached) and a **poignancy** score from 1 to 10 (LLM call; "is idle" is hard-coded to 1). The poignancy is subtracted from `importance_trigger_curr`, the reflection budget.
- If the agent observes *its own* ongoing chat, a `chat` node is also stored with the full transcript in `filling`.

### 6.2 Retrieve — `cognitive_modules/retrieve.py`

There are two retrieval functions:

- **`retrieve()`** (line 14) runs every step on the newly perceived events. It gets candidates by **keyword match** on subject/predicate/object (`kw_to_event`, `kw_to_thought`), then ranks them only by cosine similarity to the event, top 5 each. It doesn't use recency or importance.
- **`new_retrieve(persona, focal_points, n)`** (line 227) is the paper's scoring function, used for conversations, reflection, identity revision, and interviews. For every non-idle event or thought node:

  ```
  score = recency_w * recency * 0.5  +  relevance_w * relevance * 3  +  importance_w * importance * 2
  ```

  Each component is min-max normalized to [0, 1]. `recency_w/relevance_w/importance_w` come from `scratch.json`; the global multipliers `gw = [0.5, 3, 2]` are hard-coded (`retrieve.py:276`). Recency is `recency_decay ** rank`, with nodes sorted by `last_accessed`. Relevance is cosine similarity to the focal point's embedding. Importance is the node's poignancy. Retrieved nodes get `last_accessed = now`.

### 6.3 Plan — `cognitive_modules/plan.py` (the biggest module)

**Long-term planning** (`_long_term_planning`, line 629), once per game day:
1. `generate_wake_up_hour` (LLM, uses `lifestyle`).
2. `revise_identity` (line 490): retrieves memories about "today's plan" and "important recent events", then asks the LLM for a plan note and a feelings summary. It **overwrites `scratch.currently`** with a new status and **overwrites `scratch.daily_plan_req`** with a new 4–6 item plan. Your hand-written `currently` is therefore rewritten at the very first step. Put durable facts in `learned`/`innate`, or in whispers.
3. On the first day, `generate_first_daily_plan` fills `daily_req`, a broad-strokes list. On later days `daily_req` is *not* regenerated (there is a `TODO` at line 658).
4. `generate_hourly_schedule`: 24 hourly slots, compressed into `[["sleeping", 360], ["working on her painting", 180], ...]` (minutes). The result is stored in `f_daily_schedule` and in `f_daily_schedule_hourly_org` (the untouched original).
5. A "plan" thought ("This is X's plan for Monday February 13: ...") is added to memory with poignancy 5.

**Short-term planning** (`_determine_action`, line 697) runs whenever the current action's duration has elapsed (`act_check_finished`):
1. **Lazy decomposition:** hourly blocks of 60 minutes or more that are about to start are split by `generate_task_decomp` into 5–15 minute sub-tasks such as `"working on painting (mixing colors)"`. Sleep isn't decomposed.
2. **Location choice**, three LLM calls down the hierarchy, each constrained to what the agent's *spatial memory* knows: sector (`action_location_sector_v1.py`, which also uses `living_area`), then arena, then game object. The result is an address like `the Ville:Hobbs Cafe:cafe:behind the cafe counter`.
3. Emoji (`pronunciatio`), event triple `(Isabella, is, serving coffee)`, and an **object** description and triple `(…:coffee machine, is, brewing coffee)`.
4. `scratch.add_new_action(...)` commits it.

**Reacting to others** (`_choose_retrieved`, `_should_react`):
- Self-events are dropped. Events whose subject is another *persona* are prioritized over object events. If several remain, **this fork asks the LLM for an urgency score** for each (`generate_prioritized_event_reaction`, line 542, prompt `v2/prioritized_event_reaction.py`), with poignancy as a tie-breaker. Only the top event is considered.
- `lets_talk` has guards (not asleep, not 11pm, no one already chatting, `chatting_with_buffer` cooldown) and then asks the LLM `decide_to_talk`.
- If the agent doesn't talk, `lets_react` may decide to **wait** (for example, for a shared bathroom) when both target the same address.
- `_chat_react` (line 1044) generates the entire conversation **at once** (`agent_chat_v2` in `converse.py:172`, up to 8 turns each). For each utterance it retrieves memories about the partner, summarizes the relationship, and generates one line plus an `end` flag. The conversation's length in characters sets its game-time duration. Both agents' schedules are then rewritten around the chat (`generate_new_decomp_schedule`), and both get a `chatting_with_buffer` of 800 steps before they can chat again.

### 6.4 Reflect — `cognitive_modules/reflect.py`

- **Trigger:** `importance_trigger_curr <= 0`. It starts at `importance_trigger_max` (150) and each perceived event subtracts its poignancy.
- **Process:** generate 3 focal questions from the last `importance_ele_n` memories, run `new_retrieve` for each, and ask for 5 insights with evidence indices. Store each insight as a `thought` node (depth = 1 + max evidence depth, 30-day expiration). Then reset the counter.
- **After every conversation ends,** two more thoughts are written: a "For X's planning: …" note and a memo about the conversation. Both cite the chat node as evidence.

### 6.5 Execute — `cognitive_modules/execute.py`

Turns the action address into tiles (`maze.address_tiles`), samples up to 4 candidate tiles, prefers tiles not already occupied by a persona, and BFS path-finds (`path_finder.py`) over the collision grid. One tile is consumed per step. Special addresses:
- `<persona> Name`: walk toward the conversation partner (midpoint of the path).
- `<waiting> x y`: stand still.
- `<random>`: pick a random tile in the arena.
- Unknown address: falls back to `the Ville:Johnson Park:park:park garden`, which is hard-coded.

**Nonembodied agents** (`nonembodied: true`) plan normally but never move (`execute.py:153`).

---

## 7. Memory in detail

Every persona folder has the same shape:

```
personas/<Full Name>/bootstrap_memory/
├── scratch.json                  # identity, hyperparameters, current plan & action
├── spatial_memory.json           # what places/objects this agent knows exist
└── associative_memory/
    ├── nodes.json                # the memory stream
    ├── embeddings.json           # text → vector cache
    └── kw_strength.json          # keyword frequency counters
```

### 7.1 `scratch.json`: identity, knobs, and working state

Loaded by `Scratch.__init__` (`scratch.py:166`). The keys fall into four groups.

**Identity.** This is what makes an agent *who they are*. It is concatenated into the ISS and pasted into almost every prompt:

| Key | Meaning | Example | Notes |
|---|---|---|---|
| `name`, `first_name`, `last_name`, `age` | | `"Isabella Rodriguez"`, 34 | `name` must equal the folder name and the key in `meta.json`/`environment/0.json`. |
| `innate` | "L0 permanent core traits" | `"friendly, outgoing, hospitable"` | The elections scenario uses Big-Five adjective lists here. |
| `learned` | "L1 stable traits", backstory | `"Isabella is a cafe owner of Hobbs Cafe who…"` | Never rewritten by the engine. The best place for durable facts. |
| `currently` | Current situation and goals | `"…planning a Valentine's Day party…"` | **Rewritten daily** by `revise_identity`, starting at step 0. |
| `lifestyle` | Sleep and meal habits | `"goes to bed around 11pm, awakes up around 6am"` | Drives the wake-up hour. |
| `daily_plan_req` | Daily routine constraints | `"opens Hobbs Cafe at 8am everyday…"` | **Rewritten daily** by `revise_identity`. |
| `living_area` | `world:sector:arena` of home | `"the Ville:Isabella Rodriguez's apartment:main room"` | Must exist in spatial memory. Used by the sector-choice prompt. |

**Perception and retrieval knobs:**

| Key | Effect | Used? |
|---|---|---|
| `vision_r` | Tile radius for perception | yes |
| `att_bandwidth` | Max events perceived per step | yes |
| `retention` | Novelty window (last N events) | yes |
| `recency_w`, `relevance_w`, `importance_w` | Retrieval weights (multiplied by the hard-coded `gw`) | yes |
| `recency_decay` | Recency base (0.995 in base sims) | yes |
| `importance_trigger_max` / `_curr`, `importance_ele_n` | Reflection budget and counter | yes |
| `concept_forget`, `daily_reflection_time`, `daily_reflection_size`, `overlap_reflect_th`, `kw_strg_event_reflect_th`, `kw_strg_thought_reflect_th`, `thought_count` | Legacy reflection knobs | **loaded and saved but never read** |

**Agent-type flags (added by this fork):**

| Key | Effect |
|---|---|
| `noncognitive` | No reflection, no daily identity revision, plan not stored as memory, and a "powered on and awaiting tasks" style daily plan (`v2/daily_planning_v6.py`). Meant for robots or tools. |
| `nonembodied` | Never moves on the map (for example a remote commander on a radio). |

Both default to `false` if absent. The spelling must be exact. See §16 for a scenario that gets this wrong.

**Working state.** Normally leave these `null`/`[]` in a base sim; the engine fills them: `curr_time`, `curr_tile`, `daily_req`, `f_daily_schedule`, `f_daily_schedule_hourly_org`, `act_*` (current action address, start, duration, description, emoji, event triple, object description/event), `chatting_with`, `chat`, `chatting_with_buffer`, `chatting_end_time`, `act_path_set`, `planned_path`.

> `curr_time: null` is what makes the engine treat the first step as "First day" and generate a fresh plan. If you copy a persona out of a *finished* run, its `curr_time` and schedule come along, and it won't re-plan until the next game day.

### 7.2 `associative_memory/`: the memory stream

`nodes.json` maps `node_1…node_N` to:

```json
{
  "node_count": 12, "type_count": 7, "type": "event|thought|chat", "depth": 0,
  "created": "2023-02-13 08:01:20", "expiration": null,
  "subject": "Isabella Rodriguez", "predicate": "is", "object": "serving coffee",
  "description": "Isabella Rodriguez is serving coffee",
  "embedding_key": "serving coffee",
  "poignancy": 3,
  "keywords": ["isabella rodriguez", "serving coffee"],
  "filling": null
}
```

- **event**: something perceived (including your own actions and objects' states). `depth` is 0.
- **thought**: reflections, daily plans, post-chat notes, and **whispers**. `filling` lists evidence node IDs. `depth` is at least 1.
- **chat**: a conversation. `filling` holds the transcript `[[speaker, utterance], ...]`.
- `embeddings.json` caches vectors by `embedding_key`. It is the biggest file, and it's why whisper-seeded base sims aren't empty.
- `kw_strength.json` counts keyword occurrences. It's maintained but not used for anything in the current code.
- `expiration` is set (30 days) but **never enforced**. Nothing is ever forgotten.

The base sims ship with *empty* associative memories (`{}`). Agents start with only their scratch text, plus whatever you whisper in.

### 7.3 `spatial_memory.json`: what the agent knows exists

A nested tree: `{world: {sector: {arena: [objects...]}}}`. It serves two purposes:
1. It **constrains** the location-choice prompts. An agent can only choose a sector, arena, or object it knows. If a place isn't in the tree, the agent will never go there on purpose.
2. It **grows** through perception as the agent walks near new places.

To make an agent aware of a location from step 0, add it here. To keep an agent out of somewhere, leave it out. There is also a special filter: sectors containing `'s house` are offered only if the agent's `last_name` appears in the name (`action_location_sector_v1.py`).

### 7.4 Whispers (seeding memories)

A whisper file is a CSV with columns `Name,Whisper`. Multiple whispers for one agent are separated by `;`:

```csv
Name,Whisper
Maria Lopez,You have a secret crush on Klaus Mueller; You and Klaus Mueller are close friends and classmates
Klaus Mueller,You and Maria Lopez are dormmates
```

Loading it (`call -- load history <file>`, or `--load_history <file>` in automatic mode) runs `load_history_via_whisper` (`converse.py:294`). For **each** whisper the LLM rewrites it into a first-person-ish inner thought (`whisper_inner_thought_v1.py`), then extracts a triple, scores poignancy, and embeds it. The result is stored as a `thought` node. That's about 4 API calls per whisper.

Path rules: a path starting with `./` is relative to the repo root; anything else is relative to `environment/frontend_server/static_dirs/assets/` (so `the_ville/agent_history_init_n3.csv` works).

---

## 8. The world: maps, sectors, arenas, objects

### 8.1 How the map is represented

The map is a Tiled map (`visuals/the_ville_jan7.json`, 140×100 tiles of 32px) with five hidden "meta" layers exported as flat CSVs in `matrix/maze/`:

| Layer CSV | Meaning |
|---|---|
| `collision_maze.csv` | non-`0` means blocked (walls, furniture) |
| `sector_maze.csv` | building/area ID per tile |
| `arena_maze.csv` | room ID per tile |
| `game_object_maze.csv` | object ID per tile |
| `spawning_location_maze.csv` | named spawn points |

The IDs are color-block numbers. The `matrix/special_blocks/*.csv` files translate them to names:

```
sector_blocks.csv:       32165, the Ville, Isabella Rodriguez's apartment
arena_blocks.csv:        32138, the Ville, artist's co-living space, Latoya Williams's room
game_object_blocks.csv:  32227, the Ville, <all>, bed
```

`Maze.__init__` (`maze.py:17`) builds `maze.tiles[y][x]`, a dict per tile with `world, sector, arena, game_object, spawning_location, collision, events`. It also builds a reverse index `maze.address_tiles["the Ville:Hobbs Cafe:cafe:piano"] -> {(x, y), ...}`, which `execute` uses.

Objects are *stateful through events*. Every object tile starts with an idle event `(address, None, None, None)`. While an agent uses it, the event becomes, for example, `(…:bed, is, being slept in, …)`, which others in the room can perceive.

### 8.2 Renaming places without editing the map (`block_remaps`)

This fork lets you relabel existing sectors, arenas, and objects per simulation by adding `block_remaps` to `reverie/meta.json`:

```json
"block_remaps": {
  "sector":      { "Harvey Oak Supply Store": "Fire station" },
  "arena":       { "supply store": "fire station" },
  "game_object": { "supply store product shelf": "fire truck",
                   "supply store counter": "common area",
                   "behind the supply store counter": "bunks" }
}
```

Rules:
- Names must match the CSVs **exactly** (case and spacing).
- **All three keys must be present**, even if empty (`{}`). `"block_remaps": {}` crashes with `KeyError: 'sector'` (verified). Omitting `block_remaps` entirely, or setting it to `null`, is fine.
- You must also rename the places in every agent's `spatial_memory.json` and in `living_area`, or agents won't find them.
- Object remaps apply to *every* object with that name, because object blocks are `<all>`.
- The visuals don't change: the fire station still *looks* like a supply store in the browser.

### 8.3 Building a new map

That requires the Tiled workflow described in `README_origin.md`: paint the meta layers, export CSVs, and write new `special_blocks`. Be aware that the code assumes "the Ville" in several places (§16): `utils.env_matrix` points at `the_ville/matrix` whatever `maze_name` says, the frontend hard-codes `the_ville_jan7.json` and its tilesets, and `execute.py` falls back to a Johnson Park address. A new map currently means *replacing* the_ville assets or parameterizing those spots.

### 8.4 Generating spatial memory for new agents: path-tester mode

In the backend shell, `start path tester mode` (which **deletes the forked sim folder**), then open `http://localhost:8000/path_tester/` and walk the camera around. The backend writes the discovered tree to `temp_storage/path_tester_out.json`, which you can paste into an agent's `spatial_memory.json`. Copying and editing an existing agent's file is usually easier.

---

## 9. The LLM layer and prompt templates

### 9.1 Configuration — `reverie/backend_server/utils.py`

- `.env` at the repo root provides `OPENAI_API_KEY` (or `AZURE_OPENAI_API_KEY`).
- `DEFAULT_OPENAI_CONFIG` sets the model (`gpt-6-luna`), embeddings (`text-embedding-3-small`), prices, `legacy-sampling-params`, `reasoning-effort`, `experiment-name`, and `cost-upperbound`.
- The optional `openai_config.json` at the repo root overrides any subset. See README for OpenAI and Azure examples.
- `debug = True` makes every prompt, input, and output print to stdout (and, via `tee`, to `logs/`). This is how you *watch the agents think*.

### 9.2 How a prompt module is built

Each live prompt is a Python module under `prompt_template/v1|v2|v3_ChatGPT/`. `run_gpt_prompt.py` re-exports them all, so the cognitive modules import from one place. They all follow the same pattern (see `v2/daily_planning_v6.py`):

```python
def create_prompt(prompt_input) -> str: ...            # f-string template
class DailyPlan(BaseModel): daily_plan: list[str]      # structured output schema
def run_gpt_prompt_daily_plan(persona, wake_up_hour):
    prompt_input = {... from persona.scratch ...}      # gather context
    def __func_clean_up(resp): return resp.daily_plan  # post-process
    def __func_validate(resp): ...                     # reject bad output
    def get_fail_safe(): return [...]                  # fallback if all retries fail
    output = safe_generate_structured_response(prompt, gpt_param, DailyPlan, 5, fail_safe, validate, clean)
    return output, [output, prompt, gpt_param, prompt_input, fail_safe]
```

- Structured outputs use **pydantic models** and OpenAI's `response_format` (`GPT_structured_request`), so the model must support Structured Outputs.
- `gpt_param` values (`max_tokens`, `temperature`, `stop`) are **dropped** unless `legacy-sampling-params: true`, because reasoning models reject them.
- Retries default to 5. After that the **fail-safe** value is used silently, apart from a printed `Error: Fail safe triggered.` Grep your logs for that string.
- A few calls bypass the template system and use raw strings with `ChatGPT_single_request`, notably `revise_identity` in `plan.py`.
- The `*.txt` files under `unused/` and `eg_prompts/` are **not loaded**. They are historical templates and rendered examples, useful for reading.

### 9.3 Prompt inventory (what each LLM call decides)

| Stage | Module (under `prompt_template/`) |
|---|---|
| Wake-up hour | `v2/wake_up_hour_v1.py` |
| Daily plan (broad strokes) | `v2/daily_planning_v6.py` |
| Hourly schedule | `v2/generate_hourly_schedule_v2.py` |
| Task decomposition | `v2/task_decomp_v3.py` |
| Sector / arena / object choice | `v1/action_location_sector_v1.py`, `v1/action_location_arena_vMar11.py`, `v1/action_object_v2.py` |
| Emoji | `v3_ChatGPT/generate_pronunciatio_v1.py` |
| Event triple / object state | `v2/generate_event_triple_v1.py`, `v3_ChatGPT/generate_obj_event_v1.py` |
| Event urgency (fork addition) | `v2/prioritized_event_reaction.py` |
| Talk? / wait? | `v2/decide_to_talk_v2.py`, `v2/decide_to_react_v1.py` |
| Conversation turns | `v3_ChatGPT/iterative_convo_v1.py`, `summarize_chat_relationship_v2.py` |
| Conversation summary → action | `v3_ChatGPT/summarize_conversation_v1.py` |
| Reschedule around interruption | `v2/new_decomp_schedule_v1.py` |
| Poignancy | `v3_ChatGPT/poignancy_event_v1.py`, `poignancy_chat_v1.py` |
| Reflection | `v3_ChatGPT/generate_focal_pt_v1.py`, `v2/insight_and_evidence_v1.py` |
| Post-chat thoughts | `v2/planning_thought_on_convo_v1.py`, `v3_ChatGPT/memo_on_convo_v1.py` |
| Whisper → thought | `v2/whisper_inner_thought_v1.py` |
| Interview answer | `v3_ChatGPT/summarize_ideas_v1.py`, `v2/generate_next_convo_line_v1.py` |
| Interview safety filter | `safety/anthromorphosization_v1.py` |

### 9.4 Cost tracking

Every chat and embedding call goes through `openai-cost-logger`. Logs are JSON files in `reverie/backend_server/cost-logs/<experiment-name>_<timestamp>.json`, keyed by `experiment-name` (default `simulacra-test`), not by sim name. When cumulative cost passes `cost-upperbound`, an exception stops the run. `utils/cost_viz.ipynb` plots the spend. README has reference costs (roughly $0.31 for 3 agents over ~5,000 steps on gpt-3.5; ~$18.5 for 25 agents for a full day).

---

## 10. Initial state vs. outputs

This is the part that confuses people most, because **inputs and outputs share the same folder layout and even the same file names.**

### 10.1 A base (input) simulation

```
storage/base_the_ville_isabella_maria_klaus/
├── reverie/meta.json           # INPUT: start date, clock, step=0, sec_per_step, persona list, remaps
├── environment/0.json          # INPUT: initial tile of every agent
└── personas/<Name>/bootstrap_memory/
    ├── scratch.json            # INPUT: personality + knobs (working state null)
    ├── spatial_memory.json     # INPUT: known places
    └── associative_memory/     # INPUT: usually empty {}
```

Some scenario folders also have `plugins/` (see §14; currently inert), `setup_notes.md`, and `personas/agent_history.csv` (a whisper file you load manually).

### 10.2 A run (output) simulation

When you run `origin → target`, the engine **copies the whole origin folder** to `storage/<target>/` and then:

| Path | Kind | Written when |
|---|---|---|
| `environment/<N>.json` | per-step positions | every step (by browser, or by backend in headless) |
| `movement/<N>.json` | **per-step output**: tile, emoji, "description @ address", chat transcript, game time | every step |
| `reverie/meta.json` | **end state**: `curr_time`, `step`, `fork_sim_code` | on `save`/`fin` |
| `personas/*/bootstrap_memory/*` | **end state** of each mind: full memory stream, schedule, rewritten `currently`, discovered places | on `save`/`fin` (overwrites the copied inputs) |

Key points:
- The folder name `bootstrap_memory` is misleading. In an output sim it holds the **final** mental state, which is exactly what makes that sim a valid *origin* for the next run.
- There is **no per-step snapshot of memory.** To see a mind at time T, you need a checkpoint saved at T. Automatic mode gives you one every 200 steps (§11.3).
- Conversations appear in `movement/*.json` (`chat`) and in each participant's `nodes.json` (`type: "chat"`).
- Plans are visible via `f_daily_schedule` in the saved `scratch.json`, or the `print persona schedule` command.

### 10.3 Other output locations

| Where | What |
|---|---|
| `logs/<target>_<timestamp>.txt` | full stdout (every prompt and response when `debug=True`) |
| `reverie/backend_server/cost-logs/` | API cost JSON |
| `environment/frontend_server/temp_storage/` | `curr_sim_code.json`, `curr_step.json` (UI signalling only) |
| `environment/frontend_server/compressed_storage/<sim>/` | `master_movement.json` + `meta.json` + personas, created by `compress_sim_storage.py` for `/demo/` |
| `logs/conversations/` | from `utils/print_conversations.py` |

`.gitignore` ignores `storage/*` except whitelisted base sims, and within those it ignores everything in `environment/` except `0.json`, plus all of `movement/`. Your runs won't be committed unless you whitelist them.

---

## 11. Running simulations

### 11.1 One-time setup

```bash
uv sync                          # add --group analysis for notebooks / nlp
echo 'OPENAI_API_KEY=sk-...' > .env
# optional: openai_config.json to change model / costs / cost-upperbound
```

### 11.2 Headless (recommended)

Run directly with no browser:

```bash
./run_backend_automatic.sh -o base_the_ville_isabella_maria_klaus -t my_run -s 360 --ui None
```

This runs from step 0 to step **360** (one game hour). `-s` is the *end step*, not a count. Default is 8640 (a full day).

### 11.3 What automatic mode actually does — `automatic_execution.py`

- It runs in **stages of 200 steps** (`checkpoint_freq`). Each stage is a separate sim folder named `<target>-s-<stage>-<start>-<end>`, forked from the previous stage, and saved with `fin` at the end.

  ```
  my_run-s-0-0-200/  →  my_run-s-1-200-360/
  ```

- Each stage is a full copy, including all earlier `movement/` files. The **last stage folder contains the complete history**, and the others are intermediate checkpoints. Use `utils/clean_sim_folders.py` to prune them, or keep them for time-series interviews (§12.3).
- If an exception occurs mid-step, the step is rolled back and the stage restarts from the last checkpoint, with up to 5 consecutive "stepbacks".
- `--load_history <csv>` injects whispers at step 0 of the first stage only.
- To resume a run, pass the last stage as `-o` with a larger `-s`. The start step is read from the origin's `movement/` files.
- Other flags: `--ui True` (opens the browser; needs `./run_frontend.sh` running and a `--browser_path`), `--ui False` (headless Chrome), `--mqtt`, and `-p` for the port.

### 11.4 Interactive/manual mode

```bash
./run_backend.sh          # the <origin> <target> args are ignored; answer the prompts instead
# Enter the name of the forked simulation: base_the_ville_isabella_maria_klaus
# Enter the name of the new simulation: my_manual_run
# Would you like to use MQTT? (y/N): n
Enter option: call -- load history the_ville/agent_history_init_n3.csv
Enter option: headless 100          # or: run 100 (needs the browser on /simulator_home)
Enter option: print all persona schedule
Enter option: call -- analysis Klaus Mueller
Enter option: fin                   # save & quit   (exit = quit and DELETE the sim folder)
```

Commands (parsed in `open_server`, `reverie.py:598`):

| Command | Effect |
|---|---|
| `run N` / `headless N` | advance N steps (you can't mix the two in one session) |
| `save` / `fin` | save state / save and quit |
| `exit` | quit **and delete** the target folder |
| `print persona schedule <First Last>` | decomposed schedule |
| `print all persona schedule` | all agents |
| `print hourly org persona schedule <First Last>` | original hourly plan |
| `print persona current tile <First Last>` | position |
| `print persona chatting with buffer <First Last>` | chat cooldowns |
| `print persona associative memory (event\|thought\|chat) <First Last>` | dump memory stream |
| `print persona spatial memory <First Last>` | known-places tree |
| `print current time` | clock and step |
| `print tile event x, y` / `print tile details x, y` | inspect the world |
| `call -- analysis <Full Name>` | interview (see §12) |
| `call -- load history <csv>` | inject whispers |
| `start path tester mode` | spatial-memory authoring tool (deletes the forked sim) |

Commands that take a persona name use the **last two words** of the input as the name (`" ".join(sim_command.split()[-2:])`). Single-word or three-word names won't work there. `call -- analysis` takes the full remainder, so it's fine.

### 11.5 Watching and replaying

- `./run_frontend.sh`, then `http://localhost:8000/simulator_home` (live) or `/replay/<sim>/<step>/`. From reading the code, the live and replay handshake in this fork looks broken (§16), so rely on headless runs for anything important.
- `/demo/<sim>/<step>/<speed 1-6>/` plays a **compressed** sim entirely client-side. Produce one with `reverie/compress_sim_storage.py`: edit the sim name in its `__main__` and run it from `reverie/`. A sample is included: `/demo/July1_the_ville_isabella_maria_klaus-step-3-20/0/3/`.
- `/replay_persona_state/<sim>/<step>/<First_Last>/` renders a persona's saved scratch, spatial memory, and memory stream as HTML. It's handy for a checkpoint folder.
- `python utils/monitor_simulation.py` tails the latest `movement/*.json` of the current sim in the terminal.

---

## 12. Interviewing agents (yes, it's built in)

The paper evaluated agents by **interviewing** them about self-knowledge, memory, plans, reactions, and reflections. This repo includes that mechanism.

### 12.1 How an interview answer is produced

`open_convo_session(persona, "analysis", ...)` (`converse.py:312`) does the following for each question:
1. **Safety screen:** an LLM scores the question for "anthropomorphization" (1–10). At 8 or above (with `safe_mode=True`) it prints a disclaimer and doesn't answer.
2. `new_retrieve(persona, [question], 50)`: the top 50 memories by recency, relevance, and importance.
3. `summarize_ideas_v1`: condenses those memories relative to the question.
4. `generate_next_convo_line_v1`: answers in character, given the ISS, the conversation so far, and the summary, with speaker label "Interviewer".

It's **stateless** with respect to memory: the interview isn't written to `nodes.json`. One small side effect is that retrieved nodes get their `last_accessed` bumped. That only persists if you `save` afterward.

### 12.2 Interactively

```
Enter option: call -- analysis Isabella Rodriguez
Enter Input: What are you planning for February 14th?
...(debug output; the answer is under "~~~ processed output" of generate_next_convo_line_v1.py)
Enter Input: Who have you talked to today?
Enter Input: end_convo
```

Within one session the transcript accumulates, so follow-ups have context. The answer isn't printed on its own: it appears only in the debug dump, and it vanishes entirely if `debug=False`. That's a small UX improvement to make (§16).

You can interview any saved sim without advancing it: fork it into a throwaway target, interview, then `exit` (which deletes the throwaway).

### 12.3 Programmatically (batch surveys)

`Persona.open_convo_session("analysis", direct=True, question=...)` answers one question and returns `[["Interviewer", q], ["<Name>", answer]]`. `reverie/backend_server/survey.ipynb` uses this to poll every agent at every checkpoint of an elections run and chart vote intent over time. A minimal script (run from `reverie/backend_server/`):

```python
import shutil
from reverie import ReverieServer
from utils import fs_storage

rs = ReverieServer("my_run-s-1-200-360", "_interview_tmp")   # forks (copies) the checkpoint
try:
    for name, p in rs.personas.items():
        q = "What did you do today, and what do you plan to do tomorrow?"
        print(name, "→", p.open_convo_session("analysis", direct=True, question=q)[-1][1])
finally:
    shutil.rmtree(f"{fs_storage}/_interview_tmp")              # don't save the probe
```

Differences from the paper's interview protocol: there's no fixed question battery or scoring harness, direct mode is single-turn, and the interviewer has no identity (the paper sometimes interviewed "as" another agent). The `whisper` branch of `open_convo_session` (inject one thought interactively) exists but isn't reachable from the CLI. Use `call -- load history` instead.

---

## 13. Customization cookbook

### 13.1 Start a new scenario (the general recipe)

1. **Copy a base sim:** `cp -r storage/base_the_ville_isabella_maria_klaus storage/base_my_scenario`.
2. **Edit `reverie/meta.json`:** `start_date` and `curr_time` (format `"February 13, 2023"` / `"February 13, 2023, 00:00:00"`), `sec_per_step`, `persona_names`, optional `block_remaps`. Keep `step: 0`. `fork_sim_code` is rewritten automatically.
3. **Edit `environment/0.json`:** one entry per persona with a walkable `x, y`. Check a tile with `print tile details x, y` or `collision_maze.csv`.
4. **Edit each persona's `scratch.json`** (§13.2) and `spatial_memory.json` (§13.4).
5. Optionally **write a whisper CSV** (§13.3).
6. Run it: `./run_backend_automatic.sh -o base_my_scenario -t trial1 -s 720 --ui None --load_history ./environment/frontend_server/storage/base_my_scenario/personas/agent_history.csv`.
7. Read `movement/`, the logs, and saved memories; interview the agents.
8. To version it, whitelist `base_my_scenario` in `.gitignore`.

### 13.2 Change a personality

Edit `scratch.json`. How each field affects behavior:
- **`innate`**: adjectives. Cheap, strong effect on tone; they appear in every ISS.
- **`learned`**: role, relationships, and backstory. Durable (never rewritten).
- **`currently`**: the "hook" for day 1. Rewritten each day by `revise_identity`, which uses retrieved memories, so a goal survives only if it made it into memory. Pair it with a whisper to make it stick.
- **`lifestyle`**: wake and sleep times. Starting at 00:00, agents sleep until the wake hour, so early wake times give you action sooner.
- **`daily_plan_req`**: routine constraints ("works at the counter 8am–8pm").
- Perception knobs (`vision_r`, `att_bandwidth`, `retention`) and retrieval weights change how socially "aware" agents are. Larger values mean more perception, more LLM calls, and more cost.

For controlled experiments, the elections scenario shows the pattern: two otherwise-identical sims with `innate` swapped between candidates (`base_the_ville_smol_elections_5_voters[_swapped_personalities]`).

### 13.3 Give agents shared history or knowledge

Use whispers (§7.4). Tips:
- One fact per `;`-separated clause makes one memory node each.
- Phrase whispers in second person ("You and X are…"). The LLM converts them to inner thoughts.
- The existing files show useful conventions: "This is very important -- …" raises poignancy, and "For planning, you frequent Hobbs Cafe" steers location choices.

### 13.4 Add a new agent

1. Create `personas/<First Last>/bootstrap_memory/` by copying another agent's folder.
2. Set the `name`, `first_name`, and `last_name` fields; they must match the folder name.
3. Reset working state: `curr_time: null`, `curr_tile: null`, empty schedules, `act_*` null, `act_event: ["<Name>", null, null]`.
4. Empty the associative memory: `nodes.json` `{}`, `embeddings.json` `{}`, `kw_strength.json` `{"kw_strength_event": {}, "kw_strength_thought": {}}`.
5. Give it a `living_area` and a `spatial_memory.json` that contains that home and the places it should know.
6. Add the name to `meta.json` → `persona_names` and to `environment/0.json`.
7. For the `/demo/` viewer, add `static_dirs/assets/characters/<First_Last>.png` and `profile/<First_Last>.png`. The live view uses a generic sprite for everyone.

Homes on the map are fixed and named after the original residents (for example `Isabella Rodriguez's apartment`; see `sector_blocks.csv`/`arena_blocks.csv`). A new character either reuses one, which you can relabel with `block_remaps`, or lives somewhere shared like the dorm.

### 13.5 Robots, commanders, and other non-humans

Set `"noncognitive": true` for task-following agents that shouldn't reflect or re-plan their identity. Set `"nonembodied": true` for off-map participants (a radio dispatcher). A nonembodied agent still needs a valid tile in `environment/0.json` and still "perceives" around that tile. It can only chat with agents whose events it perceives (same arena, within vision), so off-map communication isn't really modeled yet (§16).

### 13.6 Change the model or prompts

- **Model:** use `openai_config.json`. Azure is supported. Non-OpenAI providers need changes to `gpt_structure.py` (there are commented-out langchain stubs and a `use_openai` flag). They must support JSON-schema structured outputs, or you need to re-add parsing.
- **A prompt:** edit the `create_prompt` f-string in the module from §9.3. Keep the pydantic schema in sync if you change the output shape. Watch the fail-safes: a prompt that fails validation 5 times degrades silently to canned behavior.
- **A new cognitive step:** write a module following the pattern in §9.2, export it from `run_gpt_prompt.py`, and call it from the relevant cognitive module.

### 13.7 Retrieval, reflection, and timing knobs

| Want | Change |
|---|---|
| More or less frequent reflection | `importance_trigger_max` in scratch (lower means more often) |
| Memory weighting | `recency_w/relevance_w/importance_w`, `recency_decay` in scratch; the global `gw` in `retrieve.py:276` |
| Finer or coarser time | `sec_per_step` in `meta.json` (movement stays one tile per step, so larger values make walking "faster" in game time) |
| Checkpoint frequency | `checkpoint_freq` in `automatic_execution.py:200` |
| Conversation length cap | `range(8)` in `agent_chat_v2` (`converse.py:175`) |
| Chat cooldown | `chatting_with_buffer = 800` in `_chat_react` (`plan.py`) |
| Quieter logs, faster runs | `debug = False` in `utils.py` (but the interview answer then isn't printed) |

---

## 14. The bundled scenarios

All live under `environment/frontend_server/storage/`.

| Sim | Agents | What it's for |
|---|---|---|
| `base_the_ville_isabella_maria_klaus` | 3 | The canonical small start. Pair with `the_ville/agent_history_init_n3.csv` (crushes, friendships, Valentine's party). |
| `base_the_ville_n25` | 25 | Full Smallville. Pair with `agent_history_init_n25.csv`. |
| `skip-morning-s-14` | 25 | A saved ~3,000-step run (to about 8:22am). A good example of *output* layout and a valid origin to resume from. |
| `base_the_ville_smol_elections_5_voters` (+ `_swapped_personalities`) | 7 | Two mayoral candidates with max/min conscientiousness `innate` traits and 5 voters. See `setup_notes.md`, `elections/election_setup.md`, and `survey.ipynb`. |
| `base_hide_and_seek` | 2 | Hide-and-seek game; `plugins/hide-and-seek` is a judge prompt. |
| `base_search_and_rescue` | 3 | Search-and-rescue; `plugins/search_and_rescue` judge prompt. **Crashes at load** because of `"block_remaps": {}`; change it to `null` or add the three keys. |
| `commander_op` | 4 | Bomb-disposal op: three "robots" plus Commander Cody at a remapped fire station. Whispers in `personas/agent_history.csv`. |
| `police_chief_rex_op` | 3 | Same op with a remote Police Chief Rex. Whispers in `personas/agent_history.csv`. |
| `manual_test_1`, `test_1-s-*` | 3 | Scratch runs from local testing (gitignored). |

**About `plugins/`:** each has a `config.json` (a time window and `conversations_only`) and a `prompt_template/*.txt` judge that decides from the conversation whether the game or mission ended. **The plugin runner is commented out** in `reverie.py:333-371`. `run_plugin` is still defined in `run_gpt_prompt.py`, but nothing calls it, so these currently do nothing. `nlp/process_hide_and_seek_results.py` expects their output in `plugins/<name>/output/`.

---

## 15. Analysis and utility scripts

| Script | Use |
|---|---|
| `utils/print_conversations.py <sim_prefix>` | Deduplicated conversations across all stage folders → `logs/conversations/` |
| `utils/print_all_sim.py <sim_prefix>` | Dump every step's movement data into one text file |
| `utils/monitor_simulation.py` | Live tail of the current sim's movement files |
| `utils/clean_sim_folders.py [--execute]` | Delete intermediate `-s-` stage folders, keeping the latest |
| `utils/cost_viz.ipynb` | Cost charts from `cost-logs/` |
| `reverie/backend_server/survey.ipynb` | Batch interviews across checkpoints, extract answers, plot |
| `reverie/compress_sim_storage.py` | Pack a sim for `/demo/` |
| `nlp/raw_text_scrape.py`, `key_words.py`, `topic_modeling.py`, `lexical_diversity.py`, `openai_convo_summary.py` (+ `auto_*.sh`) | Conversation text mining. These expect files in `nlp/convo-analysis/…`, and `openai_convo_summary.py` has a placeholder API key. |

---

## 16. Limitations, bugs, and improvement opportunities

These come from reading the code for this tutorial. Items marked **(verified)** were reproduced; the rest are from code reading.

### Correctness bugs

1. **`"block_remaps": {}` crashes `Maze`** with `KeyError: 'sector'` **(verified)**. It affects `base_search_and_rescue`. Fix: use `.get("sector", {})` in `maze.py`.
2. **Commander Cody's type flags are ignored.** `commander_op/.../Commander Cody/.../scratch.json` uses `"congnative": true, "embodied": false`, but the code reads `noncognitive`/`nonembodied`. He runs as an ordinary embodied, cognitive agent. The intent was probably `"nonembodied": true`.
3. **Live UI and replay handshake appear broken.** In `templates/home/main_script.html` the "process" phase sends positions with an XHR **GET** body to `get_movements` (browsers drop GET bodies, so `json.loads` fails), and the "update" phase POSTs to `send_environment` without an `environment` key, which would write `{}` as the environment file. The endpoint names look swapped relative to the original `process_environment`/`update_environment` design. PROGRESS.md verified only that the pages load, not a browser-driven `run`. Headless is the dependable path.
4. **MQTT topic mismatch.** Django publishes to `reverie/<sim>/environment`, but the gateway listens on `frontend/environment`.
5. **Recency looks inverted.** `extract_recency` sorts nodes oldest-first and assigns `decay**1` (the highest score) to the *oldest*. Recency is also rank-based, not time-based. This is inherited from upstream and worth an issue.
6. **`run_backend.sh` ignores its arguments.** `reverie.py` prompts interactively.
7. **Name parsing in CLI commands** assumes two-word names.
8. **Hard-coded fallbacks** to `the Ville:Johnson Park:park:park garden` in `execute.py` break on any other map.
9. **Cost-log key mismatch.** Auto-exec prints the cost for the sim name, but logs are keyed by `experiment-name`, so it reports `0`.

### Things that look configurable but aren't (yet)

- **`maze_name` is effectively ignored.** `utils.env_matrix` is hard-wired to `the_ville/matrix`, and the frontend hard-codes the Ville tilemap and tilesets. *Opportunity:* derive paths from `meta.json.maze_name` and pass the map name to the templates.
- **Unused scratch knobs:** `concept_forget`, `daily_reflection_*`, `overlap_reflect_th`, `kw_strg_*_reflect_th`, `thought_count`. *Opportunity:* remove them or implement them.
- **Memory expiration is never enforced.** Nothing is forgotten, and memory grows without bound (and so does `new_retrieve`'s O(N) scan with an embedding call per focal point).
- **`daily_req` isn't regenerated on day 2+** (`plan.py:658`, `TODO`). Multi-day runs reuse day 1's broad plan while `revise_identity` changes `currently`/`daily_plan_req`.
- **Plugins are disabled**, so the scenario "judges" don't run. *Opportunity:* restore the plugin hook as a generic per-step evaluator with outputs in `plugins/<name>/output/`.
- **Retrieval weights `gw`, chat length (8 turns), chat cooldown (800), checkpoint size (200), and the reflection count (3 focal points × 5 insights) are code constants.** *Opportunity:* move them to `meta.json` or per-persona scratch.
- **Prompt templates are Python code**, not data. Changing an agent's "voice" or a scenario's framing means editing shared modules. *Opportunity:* allow per-scenario prompt overrides (a `prompts/` folder in the sim that shadows modules by name).
- **Communication is proximity-only.** Agents talk only when they see each other in the same arena. Radios, phones, broadcasts, or a commander giving remote orders (what the `*_op` scenarios want) aren't modeled. `nonembodied` removes movement but not the proximity requirement. *Opportunity:* a channel abstraction, such as "whisper to all in group X each step" or a message bus the planner can perceive.
- **No world events or scripted injections mid-run.** You can inject whispers only at load time, or by stopping, whispering, and resuming. *Opportunity:* a timed-events file in the sim (`at 08:00, whisper X to all`).
- **Object state is ephemeral.** It resets every step and exists only as a string event, with no inventory or persistent world state, so scenarios like "cut the red wire" are purely narrative. *Opportunity:* a small persistent object-state store that prompts can read and write.
- **Scenario metadata is scattered** across `meta.json`, `environment/0.json`, each `scratch.json`, each `spatial_memory.json`, whisper CSVs, and `block_remaps`, all of which must agree on exact strings. *Opportunity:* a single `scenario.yaml` compiled into a base sim, with validation (names match, tiles walkable, living areas exist in spatial memory, remap keys exist in the CSVs).

### Interview and evaluation gaps

- Interview answers are printed only inside the debug dump. The `whisper` mode isn't exposed. There is no built-in question battery, rubric, or export. `survey.ipynb` is elections-specific and hard-codes paths. *Opportunity:* a `interview.py` CLI: `--sim X --questions q.txt --out answers.csv`, across all checkpoints, with no side effects.
- There's no per-step memory snapshot, so "what did the agent know at 10:15?" needs a checkpoint at 10:15. *Opportunity:* make `checkpoint_freq` a flag.

### Performance and cost

- `retrieve()` calls `get_embedding` for **every** keyword-matched memory on **every** step, even though vectors are cached in `a_mem.embeddings` under `embedding_key`. That's a large, avoidable API cost.
- All agents are processed serially, with many sequential LLM calls per action. *Opportunity:* parallelize across agents within a step (careful: agents read each other's state).
- Each checkpoint stage copies the whole sim folder, including every `movement/` and `environment/` file, so disk use grows quadratically with run length.

### Robustness

- Silent fail-safes can quietly replace LLM outputs with canned behavior (someone "reads a book from 8 to 12"). Grep logs for `Fail safe triggered`.
- Errors inside a step trigger a rollback and restart, but agent state mutated before the error (memories, schedules) isn't rolled back within that process. The restart reloads from the last checkpoint, so up to 199 steps can be recomputed.

---

## 17. Cheat sheet

```bash
# setup
uv sync && echo 'OPENAI_API_KEY=sk-...' > .env

# one game hour, headless, 3 agents, with their shared history
./run_backend_automatic.sh -o base_the_ville_isabella_maria_klaus -t demo1 -s 360 --ui None \
    --load_history the_ville/agent_history_init_n3.csv

# resume that run to 2 hours
./run_backend_automatic.sh -o demo1-s-1-200-360 -t demo1b -s 720 --ui None

# interactive: inspect & interview a saved checkpoint without changing it
./run_backend.sh
#   origin: demo1-s-1-200-360   target: probe   MQTT: n
#   print all persona schedule
#   print persona associative memory (thought) Klaus Mueller
#   call -- analysis Klaus Mueller     … end_convo
#   exit                                  # deletes 'probe'

# read outputs
ls environment/frontend_server/storage/demo1-s-1-200-360/movement | head
python utils/print_conversations.py demo1
./run_frontend.sh   # then /replay_persona_state/demo1-s-1-200-360/0/Klaus_Mueller/
```

| I want to change… | Edit |
|---|---|
| Who an agent is | `personas/<Name>/bootstrap_memory/scratch.json` (`innate`, `learned`, `currently`, `lifestyle`, `daily_plan_req`) |
| What an agent remembers at start | whisper CSV → `--load_history` / `call -- load history` |
| Where agents can go | `spatial_memory.json` (+ `living_area`) |
| Where agents start | `environment/0.json` |
| Cast of agents | `reverie/meta.json` `persona_names` + persona folders |
| Start date / time step | `reverie/meta.json` `start_date`, `curr_time`, `sec_per_step` |
| Place names | `reverie/meta.json` `block_remaps` (all three keys!) + spatial memories |
| The map itself | Tiled + `matrix/` CSVs (and un-hard-code `the_ville`) |
| How agents think | `prompt_template/**.py` |
| Memory weighting / reflection rate | scratch knobs; `gw` in `retrieve.py` |
| LLM / cost cap | `openai_config.json`, `.env` |
