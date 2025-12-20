# 🍍 Msty Admin MCP

**AI-Powered Administration for Msty Studio Desktop**

An MCP (Model Context Protocol) server that transforms Claude into an intelligent system administrator for [Msty Studio Desktop](https://msty.ai). Query databases, manage configurations, orchestrate local AI models, and build tiered AI workflows—all through natural conversation.

[![Version](https://img.shields.io/badge/version-4.0.0-blue.svg)](https://github.com/M-Pineapple/msty-admin-mcp/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-yellow.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://apple.com)

---

## What is This?

Msty Admin MCP lets you manage your entire Msty Studio installation through Claude Desktop. Instead of clicking through menus or manually editing config files, just ask Claude:

> "Show me my Msty personas and suggest improvements"

> "Compare my local models on a coding task"

> "Run calibration tests to see which model handles reasoning best"

> "What's the health status of my Msty installation?"

Claude handles the rest—querying databases, calling APIs, analysing results, and presenting actionable insights.

---

## Key Features

### 🔍 **Database Insights**
Query your Msty database directly through conversation. Access conversations, personas, prompts, knowledge stacks, and MCP tools without touching SQLite.

### 🏥 **Health Monitoring**
Comprehensive health checks for your Msty installation—database integrity, storage usage, model cache status, and actionable recommendations.

### ⚙️ **Configuration Sync**
Export and import MCP tool configurations between Claude Desktop and Msty. Generate personas from templates. Convert your Claude preferences to Msty format.

### 🤖 **Local Model Orchestration**
Direct integration with Msty's Sidecar API. Chat with local models, compare responses across models, and get hardware-aware recommendations.

### 📊 **Performance Analytics**
Track tokens per second, latency, and error rates across your local models. Privacy-respecting conversation analytics. Identify usage patterns.

### 🎯 **Model Calibration**
Test your local models against standardised prompts across categories (reasoning, coding, writing, analysis, creative). Score response quality. Track improvement over time.

### 🔄 **Tiered AI Workflow**
Identify which tasks your local models handle well and which should escalate to Claude. Build efficient hybrid workflows.

---

## Available Tools (24 Total)

### Installation & Health
| Tool | What It Does |
|------|--------------|
| `detect_msty_installation` | Find Msty Studio, verify paths, check running status |
| `analyse_msty_health` | Database integrity, storage, model cache, recommendations |
| `get_server_status` | MCP server info and capabilities |

### Database Queries
| Tool | What It Does |
|------|--------------|
| `read_msty_database` | Query conversations, personas, prompts, tools |
| `list_configured_tools` | View MCP toolbox configuration |
| `get_model_providers` | List AI providers and local models |

### Configuration Management
| Tool | What It Does |
|------|--------------|
| `export_tool_config` | Export MCP configs for backup or sync |
| `import_tool_config` | Validate and prepare tools for Msty import |
| `generate_persona` | Create personas from templates (opus, coder, writer, minimal) |
| `sync_claude_preferences` | Convert Claude Desktop preferences to Msty persona |

### Local Model Integration
| Tool | What It Does |
|------|--------------|
| `get_sidecar_status` | Check Sidecar and Local AI Service health |
| `list_available_models` | Query models via Ollama-compatible API |
| `query_local_ai_service` | Direct low-level API access |
| `chat_with_local_model` | Send messages with automatic metric tracking |
| `recommend_model` | Hardware-aware model recommendations by use case |

### Intelligence & Analytics
| Tool | What It Does |
|------|--------------|
| `get_model_performance_metrics` | Tokens/sec, latency, error rates over time |
| `analyse_conversation_patterns` | Privacy-respecting usage analytics |
| `compare_model_responses` | Same prompt to multiple models, compare quality/speed |
| `optimise_knowledge_stacks` | Analyse and recommend improvements |
| `suggest_persona_improvements` | AI-powered persona optimization |

### Calibration & Workflow
| Tool | What It Does |
|------|--------------|
| `run_calibration_test` | Test models across categories with quality scoring |
| `evaluate_response_quality` | Score any response using heuristic evaluation |
| `identify_handoff_triggers` | Track patterns that should escalate to Claude |
| `get_calibration_history` | Historical results with trends and statistics |

---

## Installation

### Prerequisites

- **macOS** (Apple Silicon or Intel)
- **Python 3.10+**
- **[Msty Studio Desktop](https://msty.ai)** installed
- **Msty Sidecar** running (for local model features)

### Quick Start

```bash
# Clone the repository
git clone https://github.com/M-Pineapple/msty-admin-mcp.git
cd msty-admin-mcp

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "msty-admin": {
      "command": "/absolute/path/to/msty-admin-mcp/.venv/bin/python",
      "args": ["-m", "src.server"],
      "cwd": "/absolute/path/to/msty-admin-mcp"
    }
  }
}
```

Restart Claude Desktop. You should see "msty-admin" in your available tools.

---

## Usage Examples

### Check Your Installation

```
You: What's the status of my Msty installation?

Claude: Your Msty Studio is installed at /Applications/MstyStudio.app 
        (version 1.2.3). Sidecar is running with 3 models available.
        Database is healthy at 45MB. No issues detected.
```

### Query Your Data

```
You: Show me my Msty personas

Claude: You have 5 personas configured:
        1. "Opus Assistant" - British English, quality focus (temp: 0.7)
        2. "Code Helper" - Development focused (temp: 0.3)
        ...
```

### Compare Local Models

```
You: Compare my local models on this coding task: 
     "Write a Python function to find duplicates in a list"

Claude: Tested 3 models:
        
        qwen2.5-coder:7b
        ├─ Quality: 0.85 | Speed: 45 tok/s | Latency: 2.1s
        └─ Clean implementation with list comprehension
        
        gemma3:4b  
        ├─ Quality: 0.72 | Speed: 62 tok/s | Latency: 1.4s
        └─ Works but less elegant
        
        Winner (balanced): qwen2.5-coder:7b
```

### Run Calibration

```
You: Run calibration tests on my Qwen model for reasoning tasks

Claude: Calibration Results for qwen2.5:7b (Reasoning)
        
        Test 1: Bat and ball problem
        ├─ Score: 0.82 ✅ PASSED
        └─ Correctly identified $0.05
        
        Test 2: Widget machines problem  
        ├─ Score: 0.78 ✅ PASSED
        └─ Showed step-by-step reasoning
        
        Summary: 2/2 passed, average score 0.80
```

### Get Performance Metrics

```
You: How are my local models performing this week?

Claude: Model Performance (Last 7 Days)
        
        qwen2.5-coder:7b
        ├─ 142 requests | 98% success rate
        ├─ Avg: 38 tok/s | 2.3s latency
        └─ ✅ Excellent speed
        
        gemma3:4b
        ├─ 67 requests | 100% success rate  
        ├─ Avg: 55 tok/s | 1.1s latency
        └─ ✅ Excellent speed (best for quick tasks)
```

---

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Claude Desktop                        │
│                         │                                │
│                    MCP Protocol                          │
│                         │                                │
│              ┌──────────┴──────────┐                    │
│              ▼                     ▼                    │
│    ┌─────────────────┐   ┌─────────────────┐           │
│    │ Msty Admin MCP  │   │  Other MCPs     │           │
│    │   (24 tools)    │   │ (Memory, etc.)  │           │
│    └────────┬────────┘   └─────────────────┘           │
└─────────────┼───────────────────────────────────────────┘
              │
   ┌──────────┴──────────┐
   ▼                     ▼
┌──────────┐      ┌──────────────┐
│  Msty    │      │   Sidecar    │
│ Database │      │  Local AI    │
│ (SQLite) │      │   Service    │
└──────────┘      └──────────────┘
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
        ┌──────────┐       ┌──────────┐
        │ Qwen 2.5 │       │ Gemma 3  │
        │   7B     │       │   4B     │
        └──────────┘       └──────────┘
```

### Data Storage

| Location | Purpose |
|----------|---------|
| Msty Database | Read-only queries (conversations, personas, etc.) |
| `~/.msty-admin/` | MCP's own metrics and calibration data |

The MCP never writes to Msty's database—it only reads. All metrics and calibration results are stored separately.

---

## FAQ

### General

**Q: Do I need Msty Studio Desktop installed?**  
A: Yes. This MCP is specifically designed to administer Msty Studio. Without it, most tools won't function.

**Q: Does this work on Windows or Linux?**  
A: Currently macOS only. Msty Studio Desktop is a macOS application.

**Q: Is my data safe?**  
A: The MCP only reads from Msty's database—it never writes to it. Metrics and calibration data are stored separately in `~/.msty-admin/`. No data is sent externally.

### Local Models

**Q: Do I need local models installed?**  
A: For basic features (database queries, health checks), no. For local model features (chat, compare, calibrate), you need Msty Sidecar running with at least one model.

**Q: Which local models work best?**  
A: Use `recommend_model` with your use case. Generally:
- **Coding**: qwen2.5-coder (7B or 32B depending on your RAM)
- **General**: qwen2.5 (7B for speed, 32B for quality)
- **Fast responses**: gemma3:4b or qwen3:0.6b

**Q: What's the Sidecar?**  
A: Msty Sidecar is the background service that hosts local models. It provides an Ollama-compatible API on port 11964.

### Calibration

**Q: What is calibration?**  
A: Calibration tests your local models against standardised prompts to measure quality. Categories include reasoning, coding, writing, analysis, and creative tasks.

**Q: What's a good calibration score?**  
A: Scores range 0.0-1.0. Generally:
- 0.8+ = Excellent
- 0.6-0.8 = Good (passes threshold)
- 0.4-0.6 = Fair
- Below 0.4 = Poor

**Q: What are handoff triggers?**  
A: Patterns that indicate a task should be handled by Claude instead of a local model. The MCP learns these from failed calibration tests.

### Troubleshooting

**Q: Claude doesn't see the msty-admin tools**  
A: Check your `claude_desktop_config.json` paths are absolute (not relative). Restart Claude Desktop after changes.

**Q: "Sidecar not running" error**  
A: Start Msty Sidecar from the Msty Studio menu bar icon, or run: `open -a MstySidecar`

**Q: "Database not found" error**  
A: Msty stores its database in `~/Library/Application Support/MstySidecar/SharedStorage`. Ensure Msty has been launched at least once.

**Q: Model comparison takes too long**  
A: Each model runs sequentially. Limit comparisons to 3-5 models. Larger models (32B+) take longer.

---

## Project Structure

```
msty-admin-mcp/
├── src/
│   ├── __init__.py
│   ├── server.py           # Main MCP server (24 tools)
│   └── phase4_5_tools.py   # Metrics and calibration utilities
├── tests/
│   └── test_server.py
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Acknowledgements

- [Msty Studio](https://msty.ai) - The excellent local AI application this MCP administers
- [Anthropic](https://anthropic.com) - For Claude and the MCP protocol
- [Model Context Protocol](https://modelcontextprotocol.io) - The foundation making this possible

---

**Created by Pineapple 🍍**

*Making local AI administration effortless.*
