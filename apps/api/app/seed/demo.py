from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data


def main() -> None:
    with SessionLocal() as db:
        result = generate_mock_market_data(db, days=365)
    print(f"Seeded Phase 2 mock market data: {result}")


if __name__ == "__main__":
    main()
