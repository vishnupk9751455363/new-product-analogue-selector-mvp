"""
app.py
FastAPI Web Application Backend for the New-Product Analogue Selector.
Exposes REST APIs for:
- Cold-start catalogue browsing
- Interactive analogue retrieval with per-attribute explainability
- Launch curve forecasting vs. naive baseline
- Immutable audit trail queries and planner overrides
- Benchmark evaluation results
"""

import os
import sys
import json
import sqlite3
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.analogue_selector import AnalogueSelector
from src.baseline import CategoryAverageBaselineForecaster
from src.audit_log import PlanAuditLogger
from src.evaluate import run_benchmark

DB_PATH = os.path.join(BASE_DIR, "db", "warehouse.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(
    title="New-Product Analogue Selector API",
    description="Decision-support system for grocery cold-start launch forecasting",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global models initialized at startup
selector_engine: Optional[AnalogueSelector] = None
baseline_engine: Optional[CategoryAverageBaselineForecaster] = None
audit_logger = PlanAuditLogger(DB_PATH)


def get_db():
    if not os.path.exists(DB_PATH):
        raise RuntimeError("Database not found. Please run scripts/generate_synthetic_data.py first.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_models():
    global selector_engine, baseline_engine
    if not os.path.exists(DB_PATH):
        from scripts.generate_synthetic_data import main as gen_data
        gen_data()

    conn = get_db()
    products_df = pd.read_sql("SELECT * FROM products", conn)
    sales_df = pd.read_sql("SELECT * FROM sales_history", conn)
    conn.close()

    selector_engine = AnalogueSelector()
    selector_engine.fit(products_df, sales_df)

    baseline_engine = CategoryAverageBaselineForecaster(use_price_tier=True)
    baseline_engine.fit(products_df, sales_df)


@app.on_event("startup")
def on_startup():
    init_models()


# Models for API requests
class AnalogueRequest(BaseModel):
    product_id: Optional[str] = None
    custom_product: Optional[Dict[str, Any]] = None
    k: int = 5
    custom_weights: Optional[Dict[str, float]] = None


class OverrideRequest(BaseModel):
    product_id: str
    changed_by: str
    field_changed: str
    old_value: Any
    new_value: Any
    reason: str


@app.get("/api/health")
def health_check():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM products")
    total_prods = cur.fetchone()[0]
    conn.close()
    return {
        "status": "online",
        "database": "connected",
        "total_products": total_prods,
        "models_loaded": selector_engine is not None and baseline_engine is not None
    }


@app.get("/api/products")
def list_products(is_historical: Optional[int] = Query(None)):
    conn = get_db()
    cur = conn.cursor()
    if is_historical is not None:
        cur.execute("SELECT * FROM products WHERE is_historical = ? ORDER BY product_id", (is_historical,))
    else:
        cur.execute("SELECT * FROM products ORDER BY is_historical ASC, product_id ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"products": rows}


@app.post("/api/analogues")
def get_analogues(req: AnalogueRequest):
    global selector_engine, baseline_engine
    if selector_engine is None or baseline_engine is None:
        init_models()

    target_prod = None

    if req.product_id:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE product_id = ?", (req.product_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail=f"Product {req.product_id} not found.")
        target_prod = dict(row)
    elif req.custom_product:
        target_prod = req.custom_product
        if "product_id" not in target_prod:
            target_prod["product_id"] = "PRD_CUSTOM_EXP"
    else:
        raise HTTPException(status_code=400, detail="Must provide either product_id or custom_product.")

    # Configure custom weights if provided
    local_selector = selector_engine
    if req.custom_weights:
        local_selector = AnalogueSelector(weights=req.custom_weights)
        conn = get_db()
        products_df = pd.read_sql("SELECT * FROM products", conn)
        sales_df = pd.read_sql("SELECT * FROM sales_history", conn)
        conn.close()
        local_selector.fit(products_df, sales_df)

    # 1. Retrieve analogues
    analogues = local_selector.find_analogues(target_prod, k=req.k)

    # 2. Compute launch forecast
    fc_result = local_selector.forecast_launch_curve(target_prod, k=req.k)

    # 3. Compute baseline forecast
    base_forecast = baseline_engine.forecast(target_prod)

    return {
        "target_product": target_prod,
        "analogues": [a.to_dict() for a in analogues],
        "forecast": fc_result.to_dict(),
        "baseline_forecast": base_forecast,
        "weights_used": local_selector.weights
    }


@app.post("/api/audit/override")
def record_planner_override(req: OverrideRequest):
    try:
        change_id = audit_logger.record_change(
            product_id=req.product_id,
            changed_by=req.changed_by,
            field_changed=req.field_changed,
            old_value=req.old_value,
            new_value=req.new_value,
            reason=req.reason,
            source="planner_override"
        )
        return {"status": "success", "change_id": change_id, "message": "Override recorded into immutable audit log."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/audit/trail")
def get_audit_trail(product_id: Optional[str] = Query(None)):
    trail = audit_logger.get_audit_trail(product_id=product_id)
    return {"audit_trail": trail, "total_records": len(trail)}


@app.post("/api/audit/test-tamper")
def test_tamper(change_id: int = Query(1)):
    """Attempts to update an existing audit log entry to verify database-level trigger prevention."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE plan_changes SET reason = 'Unauthorized Modification' WHERE change_id = ?", (change_id,))
        conn.commit()
        conn.close()
        return {"tamper_successful": True, "message": "CRITICAL: Immutability trigger failed!"}
    except sqlite3.DatabaseError as e:
        conn.close()
        return {
            "tamper_successful": False,
            "trigger_blocked": True,
            "error_message": str(e),
            "description": "Database triggers actively rejected unauthorized UPDATE operation."
        }


@app.get("/api/benchmark")
def get_benchmark_results():
    try:
        res = run_benchmark(db_path=DB_PATH, k=5, horizon_weeks=8)
        return {
            "overall": res["overall"],
            "weekly": res["weekly"].to_dict(orient="records"),
            "per_product": res["per_product"].to_dict(orient="records")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Mount static assets
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Frontend static file is generating..."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
