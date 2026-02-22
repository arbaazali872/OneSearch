"""
Manufacturing Intelligence MCP Server
Provides Claude with tools to query a manufacturing SQLite database.
"""

import sqlite3
import json
import os
from typing import Optional
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "manufacturing.db")

mcp = FastMCP("manufacturing_mcp")


# ── DB Helper ────────────────────────────────────────────────────────────────
def query_db(sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fmt(rows: list[dict]) -> str:
    if not rows:
        return "No results found."
    return json.dumps(rows, indent=2, default=str)


# ── Input Models ─────────────────────────────────────────────────────────────
class SqlInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    sql: str = Field(..., description="A read-only SQL SELECT statement", min_length=5)


class FactoryFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factory_id: Optional[int] = Field(None, description="Filter by factory ID (1-5)")


class MachineFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Optional[str] = Field(None, description="Filter by status: operational | maintenance | offline")
    factory_id: Optional[int] = Field(None, description="Filter by factory ID")


class WorkOrderFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Optional[str] = Field(None, description="planned | in_progress | completed | cancelled")
    priority: Optional[str] = Field(None, description="low | medium | high | critical")
    factory_id: Optional[int] = Field(None, description="Filter by factory ID")
    limit: int = Field(20, description="Max rows to return", ge=1, le=100)


class InspectionFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: Optional[str] = Field(None, description="pass | fail | conditional_pass")
    factory_id: Optional[int] = Field(None, description="Filter by factory ID")
    limit: int = Field(20, ge=1, le=100)


class MaintenanceFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: Optional[int] = Field(None, description="Filter by machine ID")
    maintenance_type: Optional[str] = Field(None, description="preventive | corrective | emergency")
    limit: int = Field(20, ge=1, le=100)


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="manufacturing_run_query",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def run_query(params: SqlInput) -> str:
    """
    Execute any read-only SQL SELECT query against the manufacturing database.
    Use this for complex, custom analytics not covered by other tools.
    The database has these tables:
      factories, production_lines, machines, employees, suppliers, parts,
      purchase_orders, work_orders, work_order_parts, quality_inspections, maintenance_logs
    Only SELECT statements are permitted.
    """
    sql = params.sql.strip()
    if not sql.lower().startswith("select"):
        return "Error: Only SELECT statements are allowed."
    try:
        rows = query_db(sql)
        return fmt(rows)
    except Exception as e:
        return f"Query error: {e}"


@mcp.tool(
    name="manufacturing_get_schema",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def get_schema() -> str:
    """
    Return the full schema of the manufacturing database:
    all tables, columns, types, and foreign key relationships.
    Always call this first to understand the data model before writing queries.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        result = {}
        for (tname,) in tables:
            cols = conn.execute(f"PRAGMA table_info({tname})").fetchall()
            fks  = conn.execute(f"PRAGMA foreign_key_list({tname})").fetchall()
            result[tname] = {
                "columns": [{"name": c[1], "type": c[2], "not_null": bool(c[3]), "pk": bool(c[5])} for c in cols],
                "foreign_keys": [{"from": f[3], "to_table": f[2], "to_col": f[4]} for f in fks],
            }
        return json.dumps(result, indent=2)
    finally:
        conn.close()


@mcp.tool(
    name="manufacturing_list_factories",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def list_factories(params: FactoryFilter) -> str:
    """
    List all factories with their production lines and machine counts.
    Optionally filter by factory_id.
    """
    sql = """
        SELECT f.id, f.name, f.location, f.country, f.established_year, f.total_area_sqm,
               COUNT(DISTINCT pl.id) AS production_lines,
               COUNT(DISTINCT m.id)  AS machines
        FROM factories f
        LEFT JOIN production_lines pl ON pl.factory_id = f.id
        LEFT JOIN machines m ON m.production_line_id = pl.id
        WHERE f.active = 1
    """
    args = []
    if params.factory_id:
        sql += " AND f.id = ?"
        args.append(params.factory_id)
    sql += " GROUP BY f.id ORDER BY f.name"
    return fmt(query_db(sql, tuple(args)))


@mcp.tool(
    name="manufacturing_get_machines",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def get_machines(params: MachineFilter) -> str:
    """
    List machines with their production line, factory, current status,
    cumulative downtime hours, and age. Filter by status or factory.
    """
    sql = """
        SELECT m.id, m.name, m.model, m.manufacturer, m.status,
               m.age_years, m.cumulative_downtime_hours,
               m.last_maintenance_date,
               pl.name AS production_line, f.name AS factory
        FROM machines m
        JOIN production_lines pl ON pl.id = m.production_line_id
        JOIN factories f ON f.id = pl.factory_id
        WHERE 1=1
    """
    args = []
    if params.status:
        sql += " AND m.status = ?"
        args.append(params.status)
    if params.factory_id:
        sql += " AND f.id = ?"
        args.append(params.factory_id)
    sql += " ORDER BY m.cumulative_downtime_hours DESC"
    return fmt(query_db(sql, tuple(args)))


@mcp.tool(
    name="manufacturing_get_work_orders",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def get_work_orders(params: WorkOrderFilter) -> str:
    """
    List work orders with operator name, production line, factory,
    completion rate, and priority. Filter by status, priority, or factory.
    """
    sql = """
        SELECT wo.id, wo.product_name, wo.status, wo.priority,
               wo.quantity_target, wo.quantity_produced,
               ROUND(100.0 * wo.quantity_produced / wo.quantity_target, 1) AS completion_pct,
               wo.start_date, wo.end_date,
               e.name AS operator, pl.name AS production_line, f.name AS factory
        FROM work_orders wo
        JOIN employees e ON e.id = wo.operator_id
        JOIN production_lines pl ON pl.id = wo.production_line_id
        JOIN factories f ON f.id = pl.factory_id
        WHERE 1=1
    """
    args = []
    if params.status:
        sql += " AND wo.status = ?"
        args.append(params.status)
    if params.priority:
        sql += " AND wo.priority = ?"
        args.append(params.priority)
    if params.factory_id:
        sql += " AND f.id = ?"
        args.append(params.factory_id)
    sql += f" ORDER BY wo.start_date DESC LIMIT ?"
    args.append(params.limit)
    return fmt(query_db(sql, tuple(args)))


@mcp.tool(
    name="manufacturing_quality_summary",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def quality_summary(params: InspectionFilter) -> str:
    """
    Show quality inspection results: pass/fail rates, top defect types,
    and defect counts. Filter by result type or factory.
    """
    # Overall stats per factory
    sql = """
        SELECT f.name AS factory, qi.result,
               COUNT(*) AS count,
               SUM(qi.defect_count) AS total_defects,
               qi.defect_type
        FROM quality_inspections qi
        JOIN work_orders wo ON wo.id = qi.work_order_id
        JOIN production_lines pl ON pl.id = wo.production_line_id
        JOIN factories f ON f.id = pl.factory_id
        WHERE 1=1
    """
    args = []
    if params.result:
        sql += " AND qi.result = ?"
        args.append(params.result)
    if params.factory_id:
        sql += " AND f.id = ?"
        args.append(params.factory_id)
    sql += f" GROUP BY f.name, qi.result, qi.defect_type ORDER BY total_defects DESC LIMIT ?"
    args.append(params.limit)
    return fmt(query_db(sql, tuple(args)))


@mcp.tool(
    name="manufacturing_maintenance_report",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def maintenance_report(params: MaintenanceFilter) -> str:
    """
    Show maintenance logs with machine name, factory, downtime hours, cost,
    and type. Filter by machine or maintenance type.
    """
    sql = """
        SELECT ml.id, ml.maintenance_date, ml.maintenance_type,
               ml.downtime_hours, ml.cost, ml.description, ml.resolved,
               m.name AS machine, m.status AS machine_status,
               f.name AS factory, e.name AS technician
        FROM maintenance_logs ml
        JOIN machines m ON m.id = ml.machine_id
        JOIN production_lines pl ON pl.id = m.production_line_id
        JOIN factories f ON f.id = pl.factory_id
        JOIN employees e ON e.id = ml.technician_id
        WHERE 1=1
    """
    args = []
    if params.machine_id:
        sql += " AND ml.machine_id = ?"
        args.append(params.machine_id)
    if params.maintenance_type:
        sql += " AND ml.maintenance_type = ?"
        args.append(params.maintenance_type)
    sql += f" ORDER BY ml.maintenance_date DESC LIMIT ?"
    args.append(params.limit)
    return fmt(query_db(sql, tuple(args)))


@mcp.tool(
    name="manufacturing_inventory_status",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def inventory_status() -> str:
    """
    Show current parts inventory with stock levels, reorder thresholds,
    supplier info, and flags for items below reorder threshold.
    Also shows any pending or shipped purchase orders per part.
    """
    sql = """
        SELECT p.id, p.name, p.sku, p.category, p.stock_quantity,
               p.reorder_threshold,
               CASE WHEN p.stock_quantity < p.reorder_threshold THEN 'LOW STOCK' ELSE 'OK' END AS stock_status,
               p.unit_cost,
               s.name AS supplier, s.lead_time_days, s.reliability_score,
               COUNT(po.id) AS open_purchase_orders
        FROM parts p
        JOIN suppliers s ON s.id = p.supplier_id
        LEFT JOIN purchase_orders po ON po.part_id = p.id AND po.status IN ('pending','shipped')
        GROUP BY p.id
        ORDER BY stock_status DESC, p.stock_quantity ASC
    """
    return fmt(query_db(sql))


@mcp.tool(
    name="manufacturing_supplier_performance",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def supplier_performance() -> str:
    """
    Analyze supplier performance: on-time delivery rate, average delay days,
    order counts by status, and reliability scores.
    """
    sql = """
        SELECT s.name AS supplier, s.country, s.reliability_score, s.lead_time_days,
               COUNT(po.id) AS total_orders,
               SUM(CASE WHEN po.status = 'delivered' THEN 1 ELSE 0 END) AS delivered,
               SUM(CASE WHEN po.status = 'pending'   THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN po.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
               ROUND(AVG(
                 CASE WHEN po.actual_delivery IS NOT NULL AND po.expected_delivery IS NOT NULL
                 THEN julianday(po.actual_delivery) - julianday(po.expected_delivery)
                 ELSE NULL END
               ), 1) AS avg_delay_days
        FROM suppliers s
        LEFT JOIN purchase_orders po ON po.supplier_id = s.id
        GROUP BY s.id
        ORDER BY s.reliability_score DESC
    """
    return fmt(query_db(sql))


@mcp.tool(
    name="manufacturing_operator_performance",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def operator_performance() -> str:
    """
    Rank operators by work order completion rate and quality defect rate.
    Shows total work orders, completion %, and associated defect counts.
    """
    sql = """
        SELECT e.name AS operator, e.shift, f.name AS factory,
               COUNT(DISTINCT wo.id) AS total_work_orders,
               SUM(CASE WHEN wo.status = 'completed' THEN 1 ELSE 0 END) AS completed,
               ROUND(100.0 * SUM(CASE WHEN wo.status='completed' THEN 1 ELSE 0 END) / COUNT(wo.id), 1) AS completion_rate_pct,
               COALESCE(SUM(qi.defect_count), 0) AS total_defects,
               SUM(CASE WHEN qi.result = 'fail' THEN 1 ELSE 0 END) AS failed_inspections
        FROM employees e
        JOIN factories f ON f.id = e.factory_id
        LEFT JOIN work_orders wo ON wo.operator_id = e.id
        LEFT JOIN quality_inspections qi ON qi.work_order_id = wo.id
        WHERE e.active = 1
        GROUP BY e.id
        HAVING total_work_orders > 0
        ORDER BY completion_rate_pct DESC, total_defects ASC
    """
    return fmt(query_db(sql))


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="stdio")