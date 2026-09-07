#!/usr/bin/env python3
"""
demo.py
Interactive End-to-End Demonstration of the New-Product Analogue Selector (Phase 1).

DEMONSTRATES:
1. Catalog indexing & cold-start product selection.
2. Analogue retrieval with transparent weighted Gower similarity and confidence scoring.
3. Per-attribute explainability breakdown ("why" each analogue was chosen).
4. Launch forecast curve generation (similarity-weighted historical trajectories).
5. Human-in-the-loop planner review and immutable audit logging (append-only enforcement).
6. Database-level trigger verification (tamper prevention on plan_changes).
7. Graceful degradation on an out-of-catalog / novel category edge case.
"""

import os
import sys
import json
import sqlite3
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.analogue_selector import AnalogueSelector
from src.baseline import CategoryAverageBaselineForecaster
from src.audit_log import PlanAuditLogger

DB_PATH = os.path.join(BASE_DIR, "db", "warehouse.db")


def main():
    print("=" * 80)
    print("      CAPSTONE PROJECT: NEW-PRODUCT ANALOGUE SELECTOR (PHASE 1 DEMO)")
    print("=" * 80)

    if not os.path.exists(DB_PATH):
        print(f"Error: Database {DB_PATH} not found. Running synthetic data generator first...")
        from scripts.generate_synthetic_data import main as gen_main
        gen_main()

    conn = sqlite3.connect(DB_PATH)
    products_df = pd.read_sql("SELECT * FROM products", conn)
    sales_df = pd.read_sql("SELECT * FROM sales_history", conn)
    conn.close()

    # 1. Initialize & Fit Models
    print("\n[STEP 1] Indexing Established Product Catalogue...")
    selector = AnalogueSelector()
    selector.fit(products_df, sales_df)

    baseline = CategoryAverageBaselineForecaster(use_price_tier=True)
    baseline.fit(products_df, sales_df)

    hist_count = (products_df["is_historical"] == 1).sum()
    cold_count = (products_df["is_historical"] == 0).sum()
    print(f"  Indexed {hist_count} established products as historical analogue pool.")
    print(f"  {cold_count} cold-start products reserved for demand forecasting.")

    # 2. Select a Cold-Start Target Product
    cold_prods = products_df[products_df["is_historical"] == 0].reset_index(drop=True)
    target_product = cold_prods.iloc[2]  # e.g., Confectionery or Beverages item
    p_id = target_product["product_id"]

    print(f"\n[STEP 2] Candidate New Product Introduced by Commercial Team:")
    print("-" * 80)
    print(f"  Product ID:          {target_product['product_id']}")
    print(f"  Product Name:        {target_product['product_name']}")
    print(f"  Category / Subcat:   {target_product['category']} -> {target_product['subcategory']}")
    print(f"  Price Tier:          {target_product['price_tier'].upper()}")
    print(f"  Pack Size:           {int(target_product['pack_size_units'])} units")
    print(f"  Shelf Life:          {target_product['shelf_life_days']} days")
    print(f"  Festival Link:       {bool(target_product['is_festival_linked'])} ({target_product['festival_name'] or 'None'})")
    print(f"  Weather Sensitive:   {bool(target_product['weather_sensitivity'])}")
    print("-" * 80)

    # 3. Retrieve Analogues with Per-Attribute Explainability
    print(f"\n[STEP 3] Retrieving Top-5 Historical Analogues with Explainability Breakdown...")
    analogues = selector.find_analogues(target_product, k=5)

    print(f"  System Confidence Score: {analogues[0].confidence_score:.2%}")
    print(f"  Formula: C = Avg(Sim) * (1 - CV(curves)/2) * (Valid_N / k)\n")

    for i, a in enumerate(analogues, 1):
        print(f"  Analogue #{i}: {a.product_name} [{a.product_id}]")
        print(f"    Similarity: {a.similarity_score:.4f}")
        print(f"    Rationale:  {a.explanation}")
        print(f"    Contributing Attributes Breakdown:")
        for attr, val in a.contributing_attributes.items():
            pct = (val / a.similarity_score) * 100.0 if a.similarity_score > 0 else 0
            print(f"      - {attr:<20}: {val:6.4f} ({pct:4.1f}% of total score)")
        print(f"    Historical 8-Week Launch Curve (avg units/store):")
        curve_str = " | ".join(f"{w}: {a.launch_curve.get(w, 0.0):.1f}" for w in [f"W{x}" for x in range(1, 9)])
        print(f"      {curve_str}\n")

    # 4. Generate Launch Forecast Curve
    print(f"[STEP 4] Synthesizing Multi-Analogue Forecast vs. Naive Baseline:")
    print("-" * 80)
    fc_res = selector.forecast_launch_curve(target_product, k=5)
    base_res = baseline.forecast(target_product)

    print(f"{'Week':<8} | {'Naive Baseline (units/store)':<30} | {'Analogue Selector Forecast':<30}")
    print("-" * 80)
    for w in range(1, 9):
        w_key = f"W{w}"
        print(f"{w_key:<8} | {base_res[w_key]:>28.1f} | {fc_res.forecast_curve[w_key]:>28.1f}")
    print("-" * 80)

    # 5. Planner Review & Immutable Audit Trail Logging
    print(f"\n[STEP 5] Demand Planner Interaction & Immutable Audit Log...")
    audit_logger = PlanAuditLogger(DB_PATH)

    # Log initial system recommendation
    system_change_id = audit_logger.record_change(
        product_id=p_id,
        changed_by="system_analogue_selector_v1",
        field_changed="launch_curve_w1_w8",
        old_value="null",
        new_value=fc_res.forecast_curve,
        reason=f"Top-5 analogue synthesis with {fc_res.confidence_score:.2%} confidence.",
        source="system"
    )
    print(f"  [System] Recommendation recorded into audit log (Change #{system_change_id}).")

    # Planner overrides Week 1 introductory stock due to marketing campaign
    original_w1 = fc_res.forecast_curve["W1"]
    planner_override_w1 = round(original_w1 * 1.25, 1)
    override_change_id = audit_logger.record_change(
        product_id=p_id,
        changed_by="planner_sarah_m",
        field_changed="forecast_w1",
        old_value=original_w1,
        new_value=planner_override_w1,
        reason="Allocated +25% buffer for Week 1 to support regional influencer campaign.",
        source="planner_override"
    )
    print(f"  [Planner Override] Logged manual edit (Change #{override_change_id}):")
    print(f"    Field: launch_curve W1: {original_w1} -> {planner_override_w1} units")
    print(f"    Reason: 'Allocated +25% buffer for Week 1 to support regional influencer campaign.'")

    # 6. Verify Database Immutability Trigger
    print(f"\n[STEP 6] Security Verification: Enforcing Audit Log Immutability...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE plan_changes SET reason = 'Tampered' WHERE change_id = ?", (override_change_id,))
        print("  WARNING: Update was permitted!")
    except sqlite3.DatabaseError as err:
        print(f"  [SUCCESS] UPDATE rejected by trigger: {err}")

    try:
        cur.execute("DELETE FROM plan_changes WHERE change_id = ?", (override_change_id,))
        print("  WARNING: Deletion was permitted!")
    except sqlite3.DatabaseError as err:
        print(f"  [SUCCESS] DELETE rejected by trigger: {err}")
    conn.close()

    # 7. Edge Case Test: Novel / Out-of-Catalog Category
    print(f"\n[STEP 7] Edge Case Resilience Test: Out-of-Catalog Novel Category...")
    novel_product = {
        "product_id": "PRD_EDGE_999",
        "product_name": "Zero-Emissions Plant Milk (Mid 1pk)",
        "category": "Plant-Based Dairy Alternative",  # Completely absent from catalog
        "subcategory": "Oat & Almond Blend",
        "price_tier": "mid",
        "pack_size_units": 1.0,
        "shelf_life_days": 45,
        "is_festival_linked": 0,
        "festival_name": None,
        "weather_sensitivity": 1
    }
    edge_fc = selector.forecast_launch_curve(novel_product, k=5)
    print(f"  Degraded:        {edge_fc.is_degraded}")
    print(f"  Degrade Reason:  {edge_fc.degradation_reason}")
    print(f"  Confidence:      {edge_fc.confidence_score:.2%} (Penalized due to zero category history)")
    print(f"  Safe Fallback Curve: {edge_fc.forecast_curve}")

    print("\n" + "=" * 80)
    print("DEMO RUN COMPLETED SUCCESSFULLY.")
    print("=" * 80)


if __name__ == "__main__":
    main()
