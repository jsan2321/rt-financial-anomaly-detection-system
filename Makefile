.PHONY: help up down restart logs ps clean health seed simulate test lint

# Default target
help:
	@echo "========================================================================"
	@echo " RT-FADS — Real-Time Financial Anomaly Detection System CLI"
	@echo "========================================================================"
	@echo " Infrastructure Management:"
	@echo "   make up        - Start backing infrastructure (Postgres, Redis, Jaeger, OTel)"
	@echo "   make down      - Stop infrastructure containers"
	@echo "   make restart   - Restart all containers"
	@echo "   make ps        - List container status and health"
	@echo "   make logs      - Follow container logs"
	@echo "   make clean     - Teardown containers and wipe persistent volumes"
	@echo "   make health    - Verify healthcheck status of all backing services"
	@echo "   make migrate   - Execute Alembic and Django database migrations"
	@echo "   make verify-db - Run schema and hypertable integrity verification"
	@echo ""
	@echo " Operations & Simulation (Phase 14+):"
	@echo "   make seed      - Execute manual database seeding script"
	@echo "   make simulate  - Launch live transaction simulator process"
	@echo "   make test      - Run comprehensive test suite"
	@echo "   make lint      - Run code quality linters"
	@echo "========================================================================"

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

ps:
	docker compose ps

logs:
	docker compose logs -f

clean:
	docker compose down -v

health:
	@echo "=== Checking PostgreSQL (TimescaleDB) ==="
	docker compose exec postgres pg_isready -U postgres -d rt_fads || exit 1
	@echo "=== Checking Redis ==="
	docker compose exec redis redis-cli ping || exit 1
	@echo "=== Checking OTel Collector Health Probe ==="
	docker compose exec otel-collector wget -qO- http://localhost:13133/ || exit 1
	@echo "=== All infrastructure health checks passed successfully! ==="

migrate:
	@echo "=== Running Django Migrations (Admin Control Plane) ==="
	python services/admin/manage.py migrate
	@echo "=== Running Alembic Migrations (FastAPI Microservices) ==="
	cd services/gateway && alembic upgrade head
	@echo "=== All database migrations applied successfully! ==="

verify-db:
	python scripts/verify_migrations.py

seed:
	@echo "Seed target will execute 'python scripts/seed_data.py' (Implemented in Phase 14)"

simulate:
	@echo "Simulate target will execute 'python scripts/simulate_live.py' (Implemented in Phase 15)"

test:
	@echo "Running tests with pytest..."
	pytest tests/ -v

lint:
	@echo "Running code linters..."
	ruff check .
