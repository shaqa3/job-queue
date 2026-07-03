.PHONY: install backend frontend dev docker clean

# One-time setup: Python venv + npm deps.
install:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install

# Run the API + workers on :8000
backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# Run the dashboard on :5173 (proxies /api -> :8000)
frontend:
	cd frontend && npm run dev

# Run both together (needs two terminals, or use `make dev`).
dev:
	@echo "Starting backend (:8000) and frontend (:5173)..."
	@trap 'kill 0' INT; \
	( cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000 ) & \
	( cd frontend && npm run dev ) & \
	wait

docker:
	docker compose up --build

clean:
	rm -rf backend/.venv backend/data frontend/node_modules frontend/dist
