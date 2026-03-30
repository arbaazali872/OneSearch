"""
Telco Customer Intelligence MCP Server
=======================================
Unified MCP server combining:
  - Database analytics tools (query telco_churn.db)
  - ML prediction tool (calls churn prediction FastAPI)

Start the FastAPI first:
    cd ../churn_ml_project
    python -m uvicorn src.app.app_api_only:app --host 0.0.0.0 --port 8000

Then seed the database (first time only):
    python seed_db.py --input data/WA_Fn-UseC_-Telco-Customer-Churn.csv
"""

import json
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# ── Config ────────────────────────────────────────────────────────────────────
_default_db = f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'telco_churn.db')}"
DB_URL  = os.environ.get("DB_URL", _default_db)
API_URL = os.environ.get("CHURN_API_URL", "http://localhost:8000")

engine = create_engine(DB_URL)
mcp    = FastMCP("telco_intelligence")


# ── DB Helpers ────────────────────────────────────────────────────────────────
def query_db(sql: str, params: dict = None) -> list[dict]:
    params = params or {}
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        keys   = result.keys()
        return [dict(zip(keys, row)) for row in result.fetchall()]


def fmt(rows: list[dict]) -> str:
    if not rows:
        return "No results found."
    return json.dumps(rows, indent=2, default=str)


# ── Input Models ──────────────────────────────────────────────────────────────
class SqlInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    sql: str = Field(..., description="A read-only SQL SELECT statement", min_length=5)


class CustomerFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract:         Optional[str] = Field(None, description="'Month-to-month', 'One year', or 'Two year'")
    internet_service: Optional[str] = Field(None, description="'DSL', 'Fiber optic', or 'No'")
    churn:            Optional[int] = Field(None, description="1 = churned, 0 = retained")
    min_tenure:       Optional[int] = Field(None, description="Minimum tenure in months")
    max_tenure:       Optional[int] = Field(None, description="Maximum tenure in months")
    limit:            int           = Field(20,   description="Max rows to return", ge=1, le=100)


class ChurnRiskFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract:         Optional[str] = Field(None, description="Filter by contract type")
    internet_service: Optional[str] = Field(None, description="Filter by internet service type")
    max_tenure:       Optional[int] = Field(None, description="Max tenure — lower = higher risk")
    limit:            int           = Field(20,   description="Max rows to return", ge=1, le=100)


class CustomerData(BaseModel):
    """18 features required by the churn prediction model."""
    gender:           str   = Field(..., description="'Male' or 'Female'")
    Partner:          str   = Field(..., description="'Yes' or 'No'")
    Dependents:       str   = Field(..., description="'Yes' or 'No'")
    PhoneService:     str   = Field(..., description="'Yes' or 'No'")
    MultipleLines:    str   = Field(..., description="'Yes', 'No', or 'No phone service'")
    InternetService:  str   = Field(..., description="'DSL', 'Fiber optic', or 'No'")
    OnlineSecurity:   str   = Field(..., description="'Yes', 'No', or 'No internet service'")
    OnlineBackup:     str   = Field(..., description="'Yes', 'No', or 'No internet service'")
    DeviceProtection: str   = Field(..., description="'Yes', 'No', or 'No internet service'")
    TechSupport:      str   = Field(..., description="'Yes', 'No', or 'No internet service'")
    StreamingTV:      str   = Field(..., description="'Yes', 'No', or 'No internet service'")
    StreamingMovies:  str   = Field(..., description="'Yes', 'No', or 'No internet service'")
    Contract:         str   = Field(..., description="'Month-to-month', 'One year', or 'Two year'")
    PaperlessBilling: str   = Field(..., description="'Yes' or 'No'")
    PaymentMethod:    str   = Field(..., description="'Electronic check', 'Mailed check', 'Bank transfer (automatic)', or 'Credit card (automatic)'")
    tenure:           int   = Field(..., description="Months with the company", ge=0)
    MonthlyCharges:   float = Field(..., description="Monthly charges in dollars", ge=0)
    TotalCharges:     float = Field(..., description="Total charges to date in dollars", ge=0)


# ── DB Tools ──────────────────────────────────────────────────────────────────

@mcp.tool(name="telco_churn_summary", annotations={"readOnlyHint": True, "destructiveHint": False})
async def churn_summary() -> str:
    """
    Get a high-level summary of churn across the customer base.
    Shows total customers, churn rate, average tenure, and average monthly charges.
    Use this as the starting point for any churn analysis.
    """
    sql = """
        SELECT
            COUNT(*)                                        AS total_customers,
            SUM(Churn)                                      AS total_churned,
            ROUND(100.0 * SUM(Churn) / COUNT(*), 1)        AS churn_rate_pct,
            ROUND(AVG(tenure), 1)                          AS avg_tenure_months,
            ROUND(AVG(MonthlyCharges), 2)                  AS avg_monthly_charges,
            ROUND(AVG(CASE WHEN Churn=1 THEN MonthlyCharges END), 2) AS avg_charges_churned,
            ROUND(AVG(CASE WHEN Churn=0 THEN MonthlyCharges END), 2) AS avg_charges_retained
        FROM customers
    """
    return fmt(query_db(sql))


@mcp.tool(name="telco_churn_by_segment", annotations={"readOnlyHint": True, "destructiveHint": False})
async def churn_by_segment() -> str:
    """
    Break down churn rate by key segments: contract type, internet service, and payment method.
    Use this to identify which customer segments have the highest churn risk.
    """
    results = {}

    for col in ["Contract", "InternetService", "PaymentMethod"]:
        sql = f"""
            SELECT {col} AS segment,
                   COUNT(*) AS customers,
                   SUM(Churn) AS churned,
                   ROUND(100.0 * SUM(Churn) / COUNT(*), 1) AS churn_rate_pct
            FROM customers
            GROUP BY {col}
            ORDER BY churn_rate_pct DESC
        """
        results[col] = query_db(sql)

    return json.dumps(results, indent=2)


@mcp.tool(name="telco_get_customers", annotations={"readOnlyHint": True, "destructiveHint": False})
async def get_customers(params: CustomerFilter) -> str:
    """
    List customers with optional filters. Use to find customers matching
    specific criteria — e.g. all churned customers on fiber optic, or
    new customers (low tenure) on month-to-month contracts.
    """
    sql = """
        SELECT customerID, gender, tenure, Contract, InternetService,
               PaymentMethod, MonthlyCharges, TotalCharges,
               CASE WHEN Churn=1 THEN 'Yes' ELSE 'No' END AS Churn
        FROM customers
        WHERE 1=1
    """
    args = {}
    if params.contract:
        sql += " AND Contract = :contract"
        args["contract"] = params.contract
    if params.internet_service:
        sql += " AND InternetService = :internet"
        args["internet"] = params.internet_service
    if params.churn is not None:
        sql += " AND Churn = :churn"
        args["churn"] = params.churn
    if params.min_tenure is not None:
        sql += " AND tenure >= :min_tenure"
        args["min_tenure"] = params.min_tenure
    if params.max_tenure is not None:
        sql += " AND tenure <= :max_tenure"
        args["max_tenure"] = params.max_tenure
    sql += " ORDER BY MonthlyCharges DESC LIMIT :lim"
    args["lim"] = params.limit
    return fmt(query_db(sql, args))


@mcp.tool(name="telco_high_risk_customers", annotations={"readOnlyHint": True, "destructiveHint": False})
async def high_risk_customers(params: ChurnRiskFilter) -> str:
    """
    Find customers at highest churn risk based on known risk factors:
    month-to-month contract, fiber optic internet, electronic check payment,
    and low tenure. Use for targeted retention campaigns.
    """
    sql = """
        SELECT customerID, gender, tenure, Contract, InternetService,
               PaymentMethod, MonthlyCharges,
               CASE WHEN Churn=1 THEN 'Yes' ELSE 'No' END AS Churn,
               (
                   CASE WHEN Contract = 'Month-to-month'       THEN 3 ELSE 0 END +
                   CASE WHEN InternetService = 'Fiber optic'   THEN 2 ELSE 0 END +
                   CASE WHEN PaymentMethod = 'Electronic check' THEN 2 ELSE 0 END +
                   CASE WHEN tenure < 12                        THEN 2 ELSE 0 END +
                   CASE WHEN OnlineSecurity = 'No'             THEN 1 ELSE 0 END +
                   CASE WHEN TechSupport = 'No'                THEN 1 ELSE 0 END
               ) AS risk_score
        FROM customers
        WHERE 1=1
    """
    args = {}
    if params.contract:
        sql += " AND Contract = :contract"
        args["contract"] = params.contract
    if params.internet_service:
        sql += " AND InternetService = :internet"
        args["internet"] = params.internet_service
    if params.max_tenure is not None:
        sql += " AND tenure <= :max_tenure"
        args["max_tenure"] = params.max_tenure
    sql += " ORDER BY risk_score DESC, MonthlyCharges DESC LIMIT :lim"
    args["lim"] = params.limit
    return fmt(query_db(sql, args))


@mcp.tool(name="telco_run_query", annotations={"readOnlyHint": True, "destructiveHint": False})
async def run_query(params: SqlInput) -> str:
    """
    Execute any read-only SQL SELECT query against the telco churn database.
    Use for complex or custom analytics not covered by other tools.
    The database has one table: customers
    Columns: customerID, gender, SeniorCitizen, Partner, Dependents, tenure,
             PhoneService, MultipleLines, InternetService, OnlineSecurity,
             OnlineBackup, DeviceProtection, TechSupport, StreamingTV,
             StreamingMovies, Contract, PaperlessBilling, PaymentMethod,
             MonthlyCharges, TotalCharges, Churn (1=churned, 0=retained)
    Only SELECT statements are permitted.
    """
    sql = params.sql.strip()
    if not sql.lower().startswith("select"):
        return "Error: Only SELECT statements are allowed."
    try:
        return fmt(query_db(sql))
    except SQLAlchemyError as e:
        return f"Query error: {e}"


# ── ML Tools ──────────────────────────────────────────────────────────────────

@mcp.tool(name="churn_api_health", annotations={"readOnlyHint": True, "destructiveHint": False})
async def churn_api_health() -> str:
    """
    Check if the churn prediction API is running and healthy.
    Always call this before predict_customer_churn to verify the service is available.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_URL}/", timeout=5.0)
            if response.status_code == 200:
                return f"✅ Churn prediction API is healthy at {API_URL}"
            return f"⚠️ API responded with status {response.status_code}"
        except httpx.ConnectError:
            return (
                f"❌ Cannot reach API at {API_URL}. "
                "Start it with: python -m uvicorn src.app.app_api_only:app --host 0.0.0.0 --port 8000"
            )


@mcp.tool(name="predict_customer_churn", annotations={"readOnlyHint": True, "destructiveHint": False})
async def predict_customer_churn(params: CustomerData) -> str:
    """
    Predict whether a telecom customer is likely to churn using the XGBoost ML model.
    Returns prediction with key risk factors explained in business terms.

    Use when asked about:
    - Churn risk for a specific customer profile
    - Whether a customer is likely to leave
    - Retention risk assessment
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_URL}/predict",
                json=params.model_dump(),
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            if "error" in result:
                return f"Prediction error: {result['error']}"

            prediction = result.get("prediction", "Unknown")

            risk_factors = []
            if params.Contract == "Month-to-month":
                risk_factors.append("month-to-month contract")
            if params.InternetService == "Fiber optic" and params.OnlineSecurity == "No":
                risk_factors.append("fiber optic with no security add-ons")
            if params.PaymentMethod == "Electronic check":
                risk_factors.append("electronic check payment")
            if params.tenure < 12:
                risk_factors.append(f"low tenure ({params.tenure} months)")

            output = f"Prediction: {prediction}\n"
            if risk_factors and prediction == "Likely to churn":
                output += f"Key risk factors: {', '.join(risk_factors)}"
            elif prediction == "Not likely to churn":
                output += "No major risk factors detected."

            return output

        except httpx.ConnectError:
            return (
                "❌ Cannot connect to the churn prediction API. "
                "Start it with: python -m uvicorn src.app.app_api_only:app --host 0.0.0.0 --port 8000"
            )
        except httpx.TimeoutException:
            return "Error: Request timed out."
        except Exception as e:
            return f"Unexpected error: {str(e)}"


# ── Prompts ───────────────────────────────────────────────────────────────────

@mcp.prompt(name="daily_churn_report")
def daily_churn_report() -> str:
    """Generate a daily churn intelligence report across the customer base."""
    return """Generate a daily customer churn intelligence report by doing the following in order:

1. Call telco_churn_summary to get overall churn rate and key metrics
2. Call telco_churn_by_segment to identify highest-risk segments
3. Call telco_high_risk_customers with limit=10 to surface top at-risk customers
4. Call churn_api_health to verify the prediction model is available

Then summarize findings as a concise executive report with:
- 🔴 Critical: segments or customers needing immediate retention action
- 🟡 Watch: trends worth monitoring
- 🟢 Healthy: segments performing well
Keep it brief and business-focused — translate numbers into actionable insights.
"""


@mcp.prompt(name="retention_analysis")
def retention_analysis() -> str:
    """Analyse a specific customer and recommend a retention strategy."""
    return """You are a customer retention analyst with access to telco customer data and an ML churn model.

When asked to analyse a customer:
1. Call churn_api_health to verify the prediction service is available
2. Call predict_customer_churn with the customer's full profile
3. If they are high risk, query telco_get_customers to find similar retained customers
   for comparison — what do low-risk customers in the same segment look like?
4. Recommend concrete retention actions:
   - Contract upgrade discount
   - Security/support bundle offer
   - Payment method switch incentive
   - Loyalty reward for tenure milestone

Always explain risk in plain business language, never technical jargon.
"""


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")