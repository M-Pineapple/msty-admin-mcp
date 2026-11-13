<div align="center">

<img src="assets/logo.svg" alt="Msty Admin MCP logo" width="240"/>

# Msty Admin MCP v6.3.0

[![Licence: MIT](https://img.shields.io/github/license/M-Pineapple/msty-admin-mcp)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Stars](https://img.shields.io/github/stars/M-Pineapple/msty-admin-mcp)](https://github.com/M-Pineapple/msty-admin-mcp/stargazers)
[![M-Pineapple/msty-admin-mcp MCP server](https://glama.ai/mcp/servers/M-Pineapple/msty-admin-mcp/badges/score.svg)](https://glama.ai/mcp/servers/M-Pineapple/msty-admin-mcp)

</div>

> Unofficial community project. Not affiliated with, or endorsed by, Msty. Msty is a trademark of its owner.

> [!NOTE]
> **Msty Studio 3.0 support (v6.3.0).** Supported Studio versions are 2.4 to 2.9.x and 3.0.x. Studio 3.1 and later are refused until their storage is checked. On Studio 3.0 the server finds every workspace, reads the active one by default, and takes a `workspace` argument on the Studio read tools. It reads file-based workspace storage, custom workspace folders and the Home workspace in browser storage, and it never reads the stale browser-storage copy that Studio leaves behind when storage moves to files. A non-Home workspace that is still in browser storage is listed but cannot be read. Persona and prompt writes need a detected Studio 2.4 to 2.9.x or 3.0.x. On 3.0 a write also needs persona and prompt tables that match the schema checked on a real Studio 3.0.0 install, Studio fully closed, and a read-back of every new row before the change is kept. On Windows and Linux the Studio version cannot be read yet, so persona and prompt writes are refused there. Import the saved JSON pack in Persona Studio instead. Studio 3.0 storage was checked on a Linux install. The macOS paths follow the same Electron rules but were not checked on a Mac. The detail is in [docs/msty-3-layout.md](docs/msty-3-layout.md).

<img src="assets/demo.gif" alt="msty-admin-mcp answering initialize and listing its tools" width="720"/>

**Let the AI you already use plan, check and look after your local AI in Msty Studio, and let your local model ask for stronger help only when it needs it.**

## What this does

Msty Studio lets you run AI models privately on your own Mac. Msty Admin MCP lets the AI app you already use, such as Claude Desktop or Cursor, look after that setup for you. You ask in plain words, and it does the technical work.

- **Picks the right model for your Mac.** It checks your chip and memory and suggests a local model that will run well, not one that grinds to a halt.
- **Installs and tunes it.** It downloads the model and can make a tuned copy, for example a calmer, more precise version with a lower temperature and its own instructions.
- **Tests it honestly.** It compares models side by side on the same question, runs standard test prompts, and can check behaviour such as flattery or made-up answers.
- **Sets up Studio.** It can add personas and prompts to Studio, and prepare tool and skill files for you to import.
- **Keeps an eye on things.** It reports health, usage, speed and cost per model.
- **Gets help when needed.** A local model in a Msty chat can pass a question it cannot handle to Cursor, Grok or Claude, and the answer comes back in the same chat.

**Safe by default.** Looking around never changes anything. Nothing is written into Studio unless you confirm it and have switched writes on yourself, Studio is closed, and a backup has been taken first. Tools and skills are only ever saved as files for you to import. Keys and passwords are hidden from the AI. The detail is in [Security and data access](#security-and-data-access).

## The hybrid setup

Your Mac does the everyday work for free and in private. A stronger cloud AI steps in only for the hard questions.

1. **Recommend.** Your AI reads your hardware and suggests a model that fits, preferring one you already use if it still fits.
2. **Set up.** It installs that model in Msty's Local AI once you confirm.
3. **Test.** It runs test prompts, compares models on the same question, and can run Bloom behaviour checks.
4. **Tune.** It makes a tuned copy of the model with your chosen temperature, length limit and instructions. Your original model is left alone.
5. **Configure Studio.** It writes personas and prompts into Studio when you allow it, and saves tools and skills as import files.
6. **Work locally.** You chat with your local model in Msty as usual.
7. **Escalate.** When a question is too hard, the local model hands it to Cursor, Grok or Claude and shows you the answer.

```mermaid
flowchart LR
    R["Recommend"] --> S["Set up"]
    S --> T["Test"]
    T --> U["Tune"]
    U --> C["Configure Studio"]
    C --> W["Work locally"]
    W --> E["Escalate when needed"]
    E --> W
```

### Your AI as the architect

```mermaid
flowchart LR
    Y["You describe the setup you want"] --> A["Your AI (Claude Desktop, Cursor or another MCP app)"]
    A --> M["msty-admin-mcp"]
    subgraph Reads["Reads your Studio"]
        I["Personas, prompts, skills, turnstiles, Knowledge Stacks, Toolbox tools"]
    end
    subgraph Writes["Writes"]
        P["Personas and prompts: only when you allow it"]
        V["Tools, toolsets and skills: saved as import files"]
    end
    M --> Reads
    M --> Writes
    Writes --> X["A backup is taken before any change"]
```

### A local chat asking for help

```mermaid
sequenceDiagram
    participant You
    participant Local as Local model in Msty
    participant F as Frontier helper
    participant C as Cursor, Grok or Claude
    You->>Local: Ask a question
    Local->>F: Hard question
    F->>C: Pass the question on
    C-->>F: Answer
    F-->>Local: Answer
    Local-->>You: Answer in the same chat
```

For this to work, the chat uses a small toolset holding only the Frontier helper, and you need an API key for the service that answers. Setup is in [Hybrid local model and Cursor agent](#hybrid-local-model-and-cursor-agent).

## What you can do

Once the server is added to your AI app, ask as you normally would. You never need to name a tool, because the AI picks the right one. The groups below cover all 54 tools. The full names are in [Tools summary](#tools-summary-54-in-total).

### Know your machine and pick a model

It reads your chip, memory and graphics, then recommends a model sized to run well on them, preferring one you already use.

- "What hardware is this Mac, and which local model fits?"
- "Recommend a model for summarising long documents."
- "Which local models do I have, and are Local AI, MLX and llama.cpp running?"

### Install and tune local models

It installs models in Msty's Local AI once you confirm, and makes tuned copies with your settings. MLX and llama.cpp models still download inside Msty, but you can chat with them from here.

- "Install llama3.2:3b on Local AI."
- "Make a cooler variant of that model with temperature 0.2."
- "Chat with this local model / MLX model / llama.cpp model."

### Keep Msty healthy

It checks that Msty is installed and running, which version you have, which services are up, and how your providers are set up, with keys hidden. It can also show which tools you have in Claude Desktop but not in Msty.

- "Is my Msty install healthy, and which version is it?"
- "What is the MCP server status?"
- "Show the delta between my Claude Desktop MCP servers and Msty Toolbox."

### See what is in Studio

It lists what you have built in Studio, such as workspaces, personas, crews, Knowledge Stacks, prompts, skills and Toolbox tools, without changing anything. It can also export a workspace as a file.

- "List my personas, knowledge stacks and workspaces."
- "Show the tools in my Toolbox and export one config."
- "Export a workflow pack for this workspace."

### Bring personas, prompts, skills and tool configs into Studio safely

Everything it creates is first saved as a file in `~/.msty-admin/imports/`. Personas and prompts go straight into Studio only when you confirm and have switched writes on (`MSTY_ALLOW_STUDIO_WRITES=1`). Tools and skills stay as files you import in Toolbox, and any tool that would run a program on your Mac is flagged.

Personas are written in the same shape Studio 2.9 uses for its own. Quit Studio before a write, because writes are refused while it is running. If your Msty plan does not include Persona Studio, the persona is still saved in Studio but the persona list does not show it.

- "Write a persona called Research Assistant into Studio."
- "Save this tool config as a pack I can import in Toolbox."
- "How could my personas and Knowledge Stacks be better?"

### Compare, calibrate and Bloom-evaluate

It shows two models' answers side by side, runs built-in test prompts, and scores a single reply. With Anthropic's Bloom framework and an Anthropic key, it also checks behaviour such as flattery, made-up answers and overconfidence. Without them it says so rather than inventing a score.

- "Compare qwen2.5 and mistral on this prompt."
- "Test llama3.2 on reasoning and coding."
- "Run a Bloom evaluation for sycophancy on this model."

### Escalate to Grok, Claude or Cursor

From a local-model chat, a hard question can go to Cursor, Grok or Claude, and the answer comes back in the same chat. It can also decide for you whether a question needs handing off. See [Hybrid local model and Cursor agent](#hybrid-local-model-and-cursor-agent).

- "Ask Grok why this SwiftUI view is not updating."
- "Ask the Cursor agent on this Mac."
- "Should this question be handed off?"

### Usage insights and cost

It shows how much each model is used, how fast it is and what it costs, along with patterns in your conversations.

- "Show model performance metrics and cost for the last 7 days."
- "Analyse my conversation patterns."
- "What did I use on Nexus, and which models does it expose?"

### What it can see in Studio

```mermaid
flowchart TD
    Q["Your question in plain words"] --> M["msty-admin-mcp"]
    M --> P["Personas"]
    M --> K["Knowledge Stacks"]
    M --> W["Workspaces"]
    M --> T["Toolbox tools"]
    M --> CS["Context Studio"]
    M --> CR["Crews"]
    M --> PR["Prompts and skills"]
    M --> TU["Turnstiles"]
    M --> LM["Local models"]
    M --> IN["Usage insights"]
```

## Who this is for

Msty Studio users who want their usual AI app to help choose, test and organise their local models, and who want local models to call on a stronger agent only when a question is beyond them, without leaving the chat. You do not need to know how MCP works beyond adding a server to your app.

## Security and data access

- Inventory, analytics and free-form SQL stay **read only**. Credential columns always read as NULL. Secrets typed into free text, such as a chat message or a note, are out of scope.
- Write tools always save a JSON pack under `~/.msty-admin/imports/` (mode `0600`, directory `0700`). `import_tool_config` and the tools, toolsets and skills keys of `import_studio_pack` never write the Studio database. Import that pack in Toolbox. Configs with `command`, `args` or `env` are flagged as running a program on your machine.
- Personas and prompts insert into Studio SQLite only when `confirm=true`, the operator env `MSTY_ALLOW_STUDIO_WRITES=1` and a detected Studio 2.4 to 2.9.x or 3.0.x are all present. On Studio 3.0 the write goes only to the active workspace, refuses unless the persona and prompt tables match a verified Studio 3.0 schema, and is rolled back unless every new row reads back the way Studio writes it. On Windows and Linux the Studio version cannot be read yet, so these writes are refused there. The LLM cannot set that env through a tool argument. Writes take a SQLite backup (including WAL) under `~/.msty-admin/backups/` and refuse while Msty Studio is running against the live database. On Studio 3.0 any running Studio refuses the write. Tests use fixture copies, never the live DB.
- `query_local_ai_service` is allow-listed (tags, version, show, chat). Pull and create go through `install_model` and `set_model_settings`, which also need `confirm=true`.
- Calibration and Bloom history live under `~/.msty-admin/`, not in Studio.
- Frontier needs `CURSOR_API_KEY` for Cursor, `XAI_API_KEY` for Grok, or `ANTHROPIC_API_KEY` for Claude. Keys stay in Msty's toolbox environment and never belong in this repository. In ask mode the Cursor agent does not send mail, move or delete files, or use trading tools.

**Requirements**: Python 3.10+, MCP SDK v1.0.0+, psutil 5.9.0+

macOS ships `python3` 3.9. This package will not install on that interpreter. Use Homebrew Python 3.12 (or any 3.10+) as shown below.

> **New to Bloom?** Jump to the [Bloom Behavioural Evaluation](#bloom-behavioural-evaluation) section or read the [full Bloom guide](docs/BLOOM_GUIDE.md).

---

## Installation

### Quick Start

Python 3.10 or newer is required. On macOS the system `python3` is 3.9, so create the venv with Homebrew Python:

```bash
brew install python@3.12
python3.12 -m venv .venv
source .venv/bin/activate
pip install msty-admin-mcp
msty-admin-mcp  # Runs on stdio (default MCP transport)
```

If you already have Python 3.10+ as `python3`, `python3 -m venv .venv` is enough. Then `pip install msty-admin-mcp` as above.

If `pip install msty-admin-mcp` cannot find the package, install the release straight from GitHub:
```bash
pip install "msty-admin-mcp @ git+https://github.com/M-Pineapple/msty-admin-mcp@v6.3.0"
```

### With HTTP Transport
```bash
pip install "msty-admin-mcp[http]"
msty-admin-mcp --transport streamable-http  # Runs on http://localhost:8000
```

### From Source
```bash
git clone https://github.com/M-Pineapple/msty-admin-mcp
cd msty-admin-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest tests/ -v
```

This server targets the 1.x MCP Python SDK (`mcp>=1.0.0,<2`).

### Claude Desktop and Cursor

After `pip install msty-admin-mcp`, the console script `msty-admin-mcp` is on that environment's PATH. Point the host at it.

**Claude Desktop**: merge into `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "msty-admin": {
      "command": "msty-admin-mcp"
    }
  }
}
```

**Cursor**: merge into `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "msty-admin": {
      "command": "msty-admin-mcp"
    }
  }
}
```

If the host cannot see the script, set `command` to the absolute path of `msty-admin-mcp` inside the venv (`…/bin/msty-admin-mcp`). Restart the host after editing.

The Frontier one-tool server is separate. See [Hybrid local model and Cursor agent](#hybrid-local-model-and-cursor-agent).

---

## Configuration

Environment variables (all optional, sensible defaults):

```bash
# Msty installation host
MSTY_HOST=127.0.0.1

# Service backend ports (also read from Studio Gifnoc.nosj when present)
MSTY_AI_PORT=11964           # Local AI (Ollama)
MSTY_MLX_PORT=11973          # MLX service
MSTY_LLAMACPP_PORT=11454     # LLaMA.cpp service
MSTY_VIBE_PORT=8317          # Vibe CLI Proxy
MSTY_NEXUS_PORT=11434        # Msty Nexus OpenAI-compatible gateway

# Service timeout
MSTY_TIMEOUT=10              # Seconds

# Bloom integration (required for Phase 6 tools)
ANTHROPIC_API_KEY=sk-...     # Required for Bloom judge model
```

---

## Architecture

### Studio 2.9+ data layout

Msty Studio no longer uses a top-level `msty.db`. The workspace SQLite lives under the Chromium File System API path, for example:

```
~/Library/Application Support/MstyStudio/
├── Gifnoc.nosj                          # service config (ports / model paths)
├── models/  models-mlx/
└── File System/000/t/00/00000000        # Drizzle SQLite workspace DB
```

The MCP auto-detects `/Applications/MstyStudio.app`, reads the bundle version, resolves the SQLite blob, and opens it **read-only**.

### Studio 3.0 data layout

Studio 3.0 can keep each workspace in its own file. A fresh 3.0 install uses files from the start. An upgrade from 2.x keeps the browser-storage database until you turn on file-based storage in Settings, Data.

```
<Studio data folder>/
├── data/
│   ├── workspaces/default/msty.cloud.db     # Home workspace
│   ├── workspaces/<slug>/msty.cloud.db      # other workspaces
│   └── workspace-locations.json             # custom folders, {"<slug>": {"parentPath": "/abs"}}
├── secrets.json                             # encrypted by Studio, never read by this MCP
└── File System/000/t/00/00000000            # browser storage, stale once Home moves to a file
```

The workspace list and the active workspace come from the `workspaces` table in the Home database. Each database is matched against schema fingerprints taken from real Studio 2.9.12 and 3.0.0 installs, reported as `schema_fingerprint` by `get_msty_installation`. See [docs/msty-3-layout.md](docs/msty-3-layout.md) for what was checked and what is assumed.

### Service discovery

```
Msty Studio Desktop
├── Local AI (Ollama) → port 11964
├── MLX → port 11973
├── LLaMA.cpp → port 11454
├── Vibe CLI Proxy → port 8317
└── Msty Nexus (optional) → port 11434

         ↓

MCP Server (stdio / HTTP)
├── Phase 1: Foundational (5)
├── Phase 2: Configuration (5)
├── Phase 3: Service Integration (9)
├── Phase 4: Intelligence (5)
├── Phase 5: Calibration (5)
├── Phase 6: Bloom Evaluation (6)
├── Phase 7: Studio Inventory (15)
├── Phase 8: Nexus Bridge (3)
└── Phase 9: Frontier handoff (1)
```

---

## Hybrid local model and Cursor agent

A local model does the ordinary work. When a question is past it, that model calls `ask_frontier`. The default provider is the Cursor agent on this machine. Set `provider` to `grok` (`XAI_API_KEY`) or `claude` (`ANTHROPIC_API_KEY`) to use those APIs instead. A follow-up resumes that provider's session.

Msty Studio has no hook API. `escalate_if_needed` and the "Local with frontier escalation" persona are the honest equivalent: the local model must emit a real tool call.

Use a **separate one-tool server** for the local-model chat. The full admin server has 54 tools. A small model will call those other tools (GitHub, search, schema, and so on) instead of waiting for the answer.

### Fresh install

1. Install this package and the Cursor agent CLI (`cursor-agent`). It must be on the PATH seen by Msty, or at `~/.local/bin/cursor-agent`. Login and API keys: [Cursor CLI authentication](https://cursor.com/docs/cli/reference/authentication).
2. Create a **user** API key in Cursor Dashboard, API Keys. An admin key does not work. Do not commit the key and do not put it in this repo.
3. In Msty, add a toolbox server named Frontier. From a source checkout:

```json
{
  "command": "/absolute/path/to/venv/bin/python",
  "args": ["-m", "src.frontier_main"],
  "env": {
    "PYTHONPATH": "/absolute/path/to/msty-admin-mcp",
    "CURSOR_API_KEY": "your-user-api-key"
  }
}
```

After `pip install`, the console script `msty-frontier` is the same one-tool server. You can set `command` to that script and omit `PYTHONPATH`. For Grok or Claude, add `XAI_API_KEY` or `ANTHROPIC_API_KEY`, and optionally `MSTY_FRONTIER_PROVIDER`.

4. Create a toolset that contains **only** this Frontier server. Do not put GitHub, Brave, Trello, or the full admin server in that toolset.
5. On the local-model chat, select that toolset in the composer (the active-toolset control). The toolset stored on the chat is not what is sent if the composer still has another toolset selected.
6. Quit Msty and open it again after any toolbox or environment change.
7. Ask a question the local model cannot already answer. Success is one `ask_frontier` card, then the Cursor reply under it. A normal paragraph with no card means the model answered by itself and Cursor was not asked.

### Optional project folder

By default the Cursor agent reads an empty folder under `~/.msty-admin/frontier-workspace`. It cannot see your repositories. To let it read one project, set:

```json
"MSTY_FRONTIER_WORKSPACE": "/absolute/path/to/that/project"
```

Ask mode does not send mail, move or delete files, or use trading tools. It can read that folder.

### Update from v6.0.0

The admin server still has the Studio inventory tools. Add the Frontier server and the one-server toolset as above. Do not point the local-model chat at the full `msty-admin-mcp` command.

### Caveats

- The local model must emit a real tool call. Some small models never do, and then no amount of "please call the tool" in the user message will reach Cursor. A model that can call tools will. It may rewrite your question into a search command. That is still a successful handoff if the card is `ask_frontier` and the text under it came from Cursor.
- `cursor-agent status` can say "not logged in" while ask mode still works with `CURSOR_API_KEY`. The frontier process passes that variable as `--api-key`. A browser `cursor-agent login` in your terminal is not always visible to the process Msty starts.
- Several `ask_frontier` calls in one reply share the first Cursor answer. They do not each start a new chat.
- The last Cursor chat id is stored in `~/.msty-admin/frontier-session.json` (mode `0600`). Delete that file to start a fresh Cursor chat.
- `identify_handoff_triggers` scores past speed and latency. `escalate_if_needed` is the tool that actually sends the question.
- Grok and Claude sessions are stored in `~/.msty-admin/frontier-grok-session.json` and `frontier-claude-session.json` (mode `0600`).

---

## Tools summary (54 in total)

### Phase 1: Foundational (5)
- `get_msty_installation`: app, version, DB path, ports
- `read_msty_database`: `stats` / `tables` / read-only SQL
  - In read-only SQL, credential columns (key, token, secret, password, auth and header names, URL, config/JSON and command-line columns) always read as NULL. Secrets typed into arbitrary free-text columns, such as a chat message or a note, are out of scope for this tool.
- `list_configured_tools`: Toolbox MCP tools, each with a `connection` summary (transport, auth type, OAuth mode, URL host, header and env names). No secret value is returned. OAuth tokens sit in Studio's encrypted secrets store, not the workspace database, so OAuth status reads as `not_stored_in_workspace`
- `get_model_providers`: services and Studio providers (keys redacted)
  - Header and environment lists stored as name and value pairs show the name and hide the value when the name looks like a credential, for example `Authorization` or `X-Api-Key`.
- `get_status`: MCP, install and local service health. `scope` is `all`, `server`, `install` or `services`

### Phase 2: Configuration (5)
- `export_tool_config`: export a tool by name/id
- `sync_claude_preferences`: Claude to Msty delta report, with `missing_in_msty`. Reads the Claude Desktop config on macOS, Windows and Linux
- `generate_persona`: persona JSON pack. SQLite insert needs `confirm=true`, `MSTY_ALLOW_STUDIO_WRITES=1` and a detected Studio 2.4 to 2.9.x or 3.0.x, so it is refused on Windows and Linux
- `import_tool_config`: JSON pack for Toolbox. Never writes the Studio database
- `import_studio_pack`: tools, toolsets and skills stay in the JSON pack. Personas and prompts need the env gate

### Phase 3: Service Integration (9)
- `list_models`: Local AI, MLX, llama.cpp, Vibe and Nexus. `backend` defaults to `all`
- `query_local_ai_service` (allow-listed)
- `chat_with_model`: Local AI, MLX or llama.cpp. `backend` defaults to `local_ai`
- `get_hardware_profile`, `recommend_model`
- `install_model`, `set_model_settings`
- `get_vibe_proxy_status`, `query_vibe_proxy`

### Phase 4: Intelligence (5)
- `get_model_performance_metrics`: from Studio `insightsLanguageModelUsage`
- `get_conversation_patterns`
- `compare_model_responses`
- `optimise_knowledge_stacks`: live Next Gen / draft / compose status
- `suggest_persona_improvements`

### Phase 5: Calibration (5)
- `run_calibration_test`, `evaluate_response_quality`
- `identify_handoff_triggers`, `escalate_if_needed`, `get_calibration_history`

### Phase 6: Bloom Evaluation (6)
- `bloom_evaluate_model` (real evaluator or an honest error, never a fake score)
- `bloom_check_handoff`, `bloom_get_history`
- `bloom_list_behaviors`, `bloom_get_thresholds`, `bloom_validate_model`

### Phase 7: Studio 2.9 and 3.0 Inventory (15)
- `list_studio_catalogue`, `list_workspaces`, `list_personas`
- `list_shadow_personas`, `list_crews`, `list_knowledge_stacks`
- `list_turnstiles`, `list_skills`, `list_live_contexts`, `list_prompts`
- `list_context_studio`, `list_agent_plans`
- `get_studio_entity` (plural keys such as `personas`, plus singular aliases such as `persona`), `get_schema_migrations`, `export_workflow_pack`
- Every Phase 7 tool except `list_workspaces` takes an optional `workspace` (name, slug or id). Omit it for the active workspace. `read_msty_database`, `list_configured_tools` and `export_tool_config` take it too
- `list_workspaces` adds a `storage` key on Studio 3.0 with each workspace's storage, the active workspace and any stale copy
- `list_crews` adds crew `folders` on Studio 3.0
- A column missing from a newer Studio schema is skipped and listed in `missing_columns`, so the read still works

### Phase 8: Nexus Bridge (3)
- `get_nexus`, `query_nexus`, `get_insights_usage`

### Phase 9: Frontier handoff (1)
- `ask_frontier`: hand one question to Cursor (default), Grok, or Claude and return the answer in the Msty chat. Use the one-tool server (`msty-frontier` or `python -m src.frontier_main`) for a local-model chat. See [Hybrid local model and Cursor agent](#hybrid-local-model-and-cursor-agent).

---

## Bloom Behavioural Evaluation

Phase 6 introduces behavioural evaluation powered by [Anthropic's Bloom framework](https://www.anthropic.com/research/bloom). Rather than testing what a model knows, Bloom tests how it behaves. It detects failure modes such as sycophancy, hallucination, and overconfidence that standard benchmarks miss.

See the **[Bloom Knowledge Base Guide](docs/BLOOM_GUIDE.md)**.

---

## Testing

```bash
pytest tests/ -v
```

v6 ships unit tests for path resolution, read-only SQL guards, redaction, inventory/analytics, and MCP tool JSON contracts. Live smoke on Studio 2.9.2 was verified during release. The Studio 3.0 tests use schema dumps and Studio-created rows from disposable Studio 2.9.12 and 3.0.0 installs, stored in `tests/fixtures/studio/`. A persona and a prompt written by v6.3.0 were opened, edited and saved in a real Studio 3.0.0 on Linux.

---

## FAQ

### Q: How does a local model ask Cursor, Grok, or Claude?
**A**: Run the one-tool server, put only that server in the chat's toolset, and set `CURSOR_API_KEY`, `XAI_API_KEY`, or `ANTHROPIC_API_KEY`. Pass `provider` as `cursor`, `grok`, or `claude`. Steps and caveats are in [Hybrid local model and Cursor agent](#hybrid-local-model-and-cursor-agent). Keys stay in Msty's toolbox environment. They do not belong in this repository.

### Q: Why did detection fail on older MCP versions?
**A**: v5 looked for `~/Library/Application Support/Msty/msty.db`. Studio 2.x stores data under `MstyStudio` and the Chromium File System SQLite path. v6 fixes this.

### Q: Can I use this with Msty &lt; 2.4.0?
**A**: No. v6 targets Studio 2.9 and 3.0.x (works on 2.4+ layouts when the File System DB is present). Use v4.x for older process-based detection.

### Q: Does this write to the Studio database?
**A**: Inventory and analytics stay read-only. Write tools always save a JSON pack under `~/.msty-admin/imports/`. Tools, toolsets and skills are import-file only. Personas and prompts insert into Studio SQLite only with `confirm=true`, `MSTY_ALLOW_STUDIO_WRITES=1` in the MCP server environment and a detected Studio 2.4 to 2.9.x or 3.0.x, after a timestamped SQLite backup that includes WAL, and they refuse while Msty Studio is running against the live database. Quit Studio first, or import the JSON pack in Persona Studio or Toolbox. On Windows and Linux the Studio version cannot be read yet, so these writes are refused there.

### Q: What is the Nexus integration?
**A**: [Msty Nexus](https://msty.ai/nexus/) is the local runtime/gateway. `get_nexus` detects it. `list_models` with `backend=nexus` lists models on its OpenAI-compatible endpoint (`MSTY_NEXUS_PORT`).

---

## Licence

MIT Licence. See the LICENSE file.

## Contributing

Contributions are welcome. Please open issues or PRs on GitHub.

## More MCP servers by M-Pineapple

Other MCP servers in this portfolio:

- [Dev Project Coordinator](https://github.com/M-Pineapple/Dev-Project-Coordinator). Local desk for AI agents to track coding and non-coding projects, with Analytics and Kanban views.
- [CryptoAnalysisMCP](https://github.com/M-Pineapple/CryptoAnalysisMCP). Cryptocurrency technical analysis for Claude Desktop.
- [Warp Command Runner](https://github.com/M-Pineapple/warp-command-runner). Give any chat AI a real terminal.
- [Member Berries](https://github.com/M-Pineapple/member-berries-apple-mcp). Apple Calendar, Notes and Reminders with personality.
- [SeaShell](https://github.com/M-Pineapple/seashell). Talk to Claude from any terminal block.
- [TextEdit MCP](https://github.com/M-Pineapple/TextEdit-MCP). Formatted RTF documents via macOS TextEdit.
- [HubSpot Auditor](https://github.com/M-Pineapple/hubspot-auditor). Read-only HubSpot portal audit.

## Support this project

If this project has helped enhance your development workflow or saved you time, please support it:

<a href="https://www.buymeacoffee.com/mpineapple" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

Your support helps me:

* Maintain and improve this project with new features
* Keep the project open source and free for everyone
* Dedicate more time to addressing user requests and bug fixes
* Explore new terminal integrations and command intelligence

Thank you for considering supporting my work.

## Support

For issues, questions, or feature requests, visit: https://github.com/M-Pineapple/msty-admin-mcp
