# Signal Atlas

Signal Atlas is a quantitative research platform and point-in-time backtesting infrastructure engineered specifically for the National Stock Exchange of India (NSE) cash equities market.

## Architectural Objectives

1. **Controlled & Reduced Survivorship Bias**: Implements point-in-time universe construction across verified source coverage, retaining delisted instruments (e.g., historical inclusion of HDFC prior to delisting) and surveillance segment transitions (`EQ` and `BE` series) on dates when actively trading to systematically reduce survivorship bias within available exchange archives.
2. **Zero Future-Data Leakage**: Strict point-in-time (PIT) information boundaries for universe construction, corporate action adjustments, and calendar lookbacks.
3. **Audit-Grade Corporate Actions**: Explicit, decomposed corporate action modeling (stock splits, bonus issues, capital consolidations/reverse splits, and concurrent events) with verifiable regulatory circular provenance.
4. **Deterministic Point-in-Time Liquidity Universe**: Trailing lookback evaluation based strictly on exchange-reported traded value (`traded_value`), preserving genuine zero vs. missing turnover semantics.

## Technology Stack

- **Language**: Python 3.11+
- **Database**: PostgreSQL 16+ with SQLAlchemy 2.0 & Alembic migrations
- **Data Validation & Modeling**: Pydantic v2
- **Testing**: Pytest (128+ integration and unit tests passing against PostgreSQL)
- **Containerization**: Docker Compose for localized PostgreSQL database service

## Repository Structure

```text
.
├── alembic/              # Database migration scripts and schema evolution
├── docs/                 # Architectural Decision Records (ADRs) and progress logs
│   ├── decisions/        # ADR 0001 through 0009
│   └── PROGRESS.md       # Comprehensive milestone progress and audit trails
├── spikes/               # Feasibility spikes and forensic audit tools
├── src/signal_atlas/     # Core application package
│   ├── db/               # PostgreSQL ORM models and session management
│   ├── ingestion/        # Raw bhavcopy ingestion and normalization pipelines
│   ├── providers/nse/    # NSE downloaders, calendars, and report parsers
│   ├── quality/          # Bulk and dynamic point-in-time price adjustment engines
│   └── universe/         # Point-in-time liquidity universe policy and service
└── tests/                # Test suite
    ├── fixtures/         # Test fixtures and sample data
    ├── integration/      # PostgreSQL integration tests
    └── unit/             # Parser, downloader, normalizer, and validator tests
```

## Quickstart

### 1. Environment Setup

Clone the repository and create a Python virtual environment:

```bash
git clone https://github.com/debkrm/Signal-Atlas.git
cd Signal-Atlas
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Configure Local Database

Copy the template environment file:

```bash
cp .env.example .env
```

Start the PostgreSQL service using Docker:

```bash
docker compose up -d
```

Run Alembic database migrations:

```bash
alembic upgrade head
```

### 3. Run Test Suite

Verify complete test execution against PostgreSQL:

```bash
pytest -v
```

## Current Milestone Status

- **Phase 1A**: Data Ingestion & Integrity Verification (Closed)
- **Phase 1B-i**: Full Historical Coverage 2022–2024 (Closed)
- **Phase 1B-ii**: Corporate Action Registry & Candidate Price Adjustment Dataset `v1.4` (Closed)
- **Phase 1B-iii & 1B-iii.1**: Point-in-Time Liquidity Universe & Data Integrity Closure (Complete & Reviewed)
- **Phase 2**: Indicators and One Strategy (Awaiting Review)

## License

Proprietary / All rights reserved.
