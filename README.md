# New-Product Analogue Selector (Decision-Support System)

> **University Capstone Project — Phase 1 Deliverable (35% Milestone)**  
> Decision-support system for regional grocery distribution planning: cold-start launch forecasting via interpretable analogue selection and immutable audit logging.

---

## 1. Overview & Problem Context

When regional grocery distributors introduce new products (cold-start SKUs), they have zero past sales history. Planners currently rely on manual guesswork (e.g. *"this new pastry is kind of like that one cookie"*), causing frequent Week 1 stockouts or severe perishable inventory waste.

This decision-support system solves the cold-start problem by:
1. **Intelligently Retrieving Historical Analogues**: Matching new product attributes (category, subcategory, price tier, pack size, shelf life, festival link, weather sensitivity) against established historical products.
2. **Transparent Explainability**: Breaking down the exact percentage contribution of each attribute to the similarity score.
3. **Explicit Confidence Scoring**: Factoring analogue quality, pool depth, and trajectory variance among analogues.
4. **Predicting Launch Curves**: Combining top-$k$ analogue historical trajectories into an 8-week launch forecast ($W_1 \dots W_8$).
5. **Immutable Audit Trail**: Recording every system recommendation and human planner override in an append-only SQLite audit table protected by database triggers.
6. **Defeating the Naive Baseline**: Quantitatively evaluated on held-out cold-start products.

---

## 2. Project Architecture & Repository Layout

```
COE PROJECT/
├── db/
│   ├── schema.sql                 # Formal SQLite schema + immutability triggers
│   └── warehouse.db               # SQLite database instance
├── docs/
│   ├── data_schema.md             # ER diagram (Mermaid) & data dictionary
│   ├── architecture_diagram.md    # Component diagram (implemented vs Phase 2 stubs)
│   ├── stakeholder_assumptions.md # User personas (planners, managers) & assumptions
│   ├── risk_register.md           # 7 operational/ML risks, impact, and mitigations
│   └── PROGRESS.md                # 35% milestone deliverables matrix
├── scripts/
│   └── generate_synthetic_data.py # Deterministic synthetic generator (seed=42)
├── src/
│   ├── __init__.py
│   ├── baseline.py                # Deliberately naive category-average benchmark
│   ├── analogue_selector.py       # Weighted Gower similarity, explainability, confidence
│   ├── audit_log.py               # Append-only audit logger for plan changes
│   ├── evaluate.py                # Benchmarking harness (MAPE & WAPE metrics)
│   └── disruption_scenarios.py   # [Phase 2 Stub] Stress-testing engine
├── tests/
│   ├── __init__.py
│   └── test_pipeline.py           # 8 unit and integration tests (unittest)
├── demo.py                        # Complete interactive end-to-end demo
├── README.md                      # Project documentation
└── requirements.txt               # Dependencies
```

---

## 3. Quickstart & Execution Guide

### Prerequisites
- Python 3.11+
- Virtual environment (recommended)

### Installation
```bash
pip install -r requirements.txt
```

### 1. Generate Synthetic Dataset
Initializes the SQLite schema and generates 15 retail stores, 80 established catalog products (with empirical launch curves), 12 held-out cold-start test products, and seed audit records:
```bash
python scripts/generate_synthetic_data.py
```

### 2. Run Interactive End-to-End Demo
Executes the full pipeline: catalog indexing, cold-start candidate retrieval, per-attribute explainability printout, forecast generation, planner override audit logging, trigger security verification, and novel category graceful degradation:
```bash
python demo.py
```

### 3. Run Benchmark Evaluation Harness
Benchmarks the Analogue Selector against the Naive Category Baseline across the 12 held-out test products over the 8-week launch horizon:
```bash
python src/evaluate.py
```

### 4. Run Automated Test Suite
Runs all 8 unit and integration tests covering schema creation, trigger immutability, data generation, selector contract, explainability breakdowns, and edge cases:
```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## 4. Phase 1 Quantitative Benchmark Results

Evaluated on 12 held-out cold-start products across an 8-week launch window:

| Model | WAPE (Weighted Error) | MAPE | Relative Error Reduction |
| :--- | :--- | :--- | :--- |
| **Naive Baseline Forecaster** | **31.82%** | 40.12% | Reference Benchmark |
| **Analogue Selector (v1)** | **25.36%** | 32.69% | **+6.46% pts improvement (20.3% error reduction)** |

### Week-by-Week Breakdown
- **Week 1 (Initial Stocking Surge)**: Baseline WAPE **27.63%** vs. Selector WAPE **21.27%** (+6.36% pts)
- **Week 2 (Early Repeat / Promo)**: Baseline WAPE **31.81%** vs. Selector WAPE **22.12%** (+9.69% pts)
- **Week 4 (Post-Trial Stabilization)**: Baseline WAPE **30.77%** vs. Selector WAPE **22.47%** (+8.30% pts)
- **Week 7 (Steady-State)**: Baseline WAPE **30.03%** vs. Selector WAPE **20.18%** (+9.85% pts)

---

## 5. Key Design Highlights

### Weighted Gower Similarity & Explainability
Instead of a black box, each attribute distance $d_m \in [0, 1]$ yields an affinity $s_m = 1 - d_m$. The contributing breakdown is transparently logged:
- `category` (weight 0.25)
- `subcategory` (weight 0.20)
- `festival` (weight 0.15)
- `price_tier` (weight 0.15)
- `pack_size` (weight 0.10)
- `shelf_life` (weight 0.08)
- `weather_sensitivity` (weight 0.07)

### Explicit Confidence Score Formulation
$$C = \min\left(1.0, \, \overline{S}_{top-k} \times \left(1 - \frac{\text{CV}(\text{launch\_curves})}{2}\right) \times \frac{N_{\text{valid}}}{k}\right)$$
Confidence penalizes high variance across analogue launch trajectories and sparse analogue depth.

### Immutable Audit Ledger
The `plan_changes` table records every automated recommendation and planner override. SQLite triggers (`trg_prevent_plan_changes_update` and `trg_prevent_plan_changes_delete`) enforce non-repudiation at the engine level.

---

## 6. Milestone Tracker & Next Steps

See [`docs/PROGRESS.md`](file:///c:/Users/pkvis/Desktop/COE%20PROJECT/docs/PROGRESS.md) for the complete 16-point deliverables tracker.
- **Phase 1 (Completed)**: Schema, synthetic data, baseline, analogue selector v1, evaluation harness, audit triggers, edge case degradation, documentation, and tests.
- **Phase 2 (Planned)**: Disruption scenario simulation engine (`src/disruption_scenarios.py`), promotional de-biasing, interactive planner dashboard UI, and stakeholder validation.
