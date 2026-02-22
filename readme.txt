# Manufacturing Intelligence MCP

A Model Context Protocol (MCP) server that gives Claude natural language access to your manufacturing database. Ask questions in plain English — Claude figures out the schema, writes the SQL, and returns the answer.

![Demo](https://img.shields.io/badge/MCP-Compatible-blue) ![Python](https://img.shields.io/badge/Python-3.10+-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## What it does

Instead of writing SQL queries, you just ask:

> *"Which factory has the most emergency maintenance events and what's the total downtime cost?"*

> *"Which operators have the highest defect rates?"*

> *"What parts are below reorder threshold and do we have pending purchase orders for them?"*

> *"Show me all work orders that are critical priority and still in progress"*

Claude reads your database schema, writes the appropriate SQL, executes it, and gives you a structured answer — all in one conversational turn.

---

## How it works

The server exposes two types of tools to Claude:

**Schema discovery**
- `manufacturing_get_schema` — introspects your connected database and returns all tables, columns, and relationships. Claude calls this automatically before writing any query.

**Free-form queries**
- `manufacturing_run_query` — executes any SELECT query Claude generates. This is the core tool — it works against any database schema, not just the demo one.

**Pre-built tools** (convenience shortcuts for common questions)
- `manufacturing_list_factories`
- `manufacturing_get_machines`
- `manufacturing_get_work_orders`
- `manufacturing_quality_summary`
- `manufacturing_maintenance_report`
- `manufacturing_inventory_status`
- `manufacturing_supplier_performance`
- `manufacturing_operator_performance`

---

## Supported databases

| Database   | Connection string format                              | Driver to install  |
|------------|-------------------------------------------------------|--------------------|
| SQLite     | `sqlite:///C:/path/to/your.db`                        | built-in           |
| PostgreSQL | `postgresql://user:pass@host:5432/dbname`             | `psycopg2-binary`  |
| MySQL      | `mysql+pymysql://user:pass@host:3306/dbname`          | `pymysql`          |
| MSSQL      | `mssql+pyodbc://user:pass@host/dbname?driver=...`     | `pyodbc`           |

No connection string? No problem — it defaults to the included SQLite demo database.

---

## Quick start

### Prerequisites
- Python 3.10+
- Claude Desktop (latest version)
- Node.js (for the `mcpb` CLI)

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/manufacturing-mcp
cd manufacturing-mcp
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv env

# Windows
env\Scripts\pip install -r requirements.txt

# macOS / Linux
env/bin/pip install -r requirements.txt
```

If you're connecting to PostgreSQL or MySQL, also install the relevant driver:

```bash
pip install psycopg2-binary   # PostgreSQL
pip install pymysql            # MySQL
```

### 3. Seed the demo database (optional)

If you want to try it with the included fake manufacturing data:

```bash
# Windows
env\Scripts\python seed_db.py

# macOS / Linux
env/bin/python seed_db.py
```

This creates `manufacturing.db` with 5 factories, 16 machines, 200 work orders, 500 quality inspections, and more.

### 4. Pack the extension

```bash
npm install -g @anthropic-ai/mcpb
mcpb pack
```

This produces a `manufacturing-mcp.mcpb` file in the current directory.

### 5. Install in Claude Desktop

1. Open Claude Desktop → **Settings → Extensions**
2. Click **Install Extension…**
3. Select the `manufacturing-mcp.mcpb` file
4. (Optional) Enter your database connection string in the settings field — leave blank to use the demo database
5. Restart Claude Desktop

You should now see the manufacturing tools available in Claude.

---

## Connecting your own database

When you install the extension, Claude Desktop shows a **Database URL** field in the extension settings. Paste your connection string there — it's stored encrypted in your OS keychain (Windows Credential Manager / macOS Keychain), never in plaintext.

The server will introspect your schema automatically. Your tables don't need to match the demo schema — Claude will discover whatever structure you have and write queries accordingly.

> **Note:** The pre-built convenience tools (e.g. `manufacturing_get_machines`) are designed around the demo schema. For your own database, Claude will primarily use `get_schema` + `run_query` to answer questions.

---

## Demo database schema

The included demo database models a multi-factory manufacturing operation:

```
factories
└── production_lines
        └── machines
                └── maintenance_logs

        └── work_orders
                └── work_order_parts
                └── quality_inspections

employees (operators, inspectors, technicians)
suppliers
└── parts
        └── purchase_orders
```

**Sample questions to try:**

```
Which machines have had the most downtime this year?
Which supplier has the worst on-time delivery rate?
Show me all failed quality inspections from the last month
Which production line has the highest defect rate?
What's the total maintenance cost per factory?
Are there any critical work orders where required parts are low in stock?
Which operator has completed the most work orders with zero defects?
```

---

## Project structure

```
manufacturing-mcp/
├── server.py           # MCP server — tools and DB logic
├── seed_db.py          # Demo database generator
├── manifest.json       # Extension metadata for Claude Desktop
├── requirements.txt    # Python dependencies
└── manufacturing.db    # Demo database (generated by seed_db.py, not in repo)
```

---

## Privacy note

Query results are sent to the Anthropic API as part of the Claude conversation. The database itself stays on your machine — only the results of executed queries leave your system. Review [Anthropic's privacy policy](https://www.anthropic.com/privacy) if you're handling sensitive data.

For air-gapped / fully local usage, this MCP server is compatible with any MCP client that supports local stdio servers — including those running local LLMs.

---

## License

MIT