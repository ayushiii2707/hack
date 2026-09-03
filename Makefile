.PHONY: setup seed sync migrate backend frontend test lint build compose

setup:
	cd backend && python -m venv .venv && ./.venv/bin/pip install -r requirements.txt ruff
	cd frontend && npm install
	@echo "Now: cp backend/.env.example backend/.env  and fill in the keys."

migrate:
	cd backend && ./.venv/bin/alembic upgrade head

seed:
	cd backend && ./.venv/bin/python -m app.database.seed

sync:
	cd backend && ./.venv/bin/python -m app.integrations.catalog.sync

backend:
	cd backend && ./.venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && ./.venv/bin/python -m pytest

lint:
	cd backend && ./.venv/bin/ruff check .

build:
	cd frontend && npm run build

compose:
	docker compose up --build
