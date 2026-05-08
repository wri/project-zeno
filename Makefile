# Project Zeno Development Makefile
# Usage: make <target>

.PHONY: help dev dev-api dev-frontend up down restart logs api frontend test clean

# Default target - show help
help: ## Show available commands
	@echo "🚀 Project Zeno Development Commands"
	@echo ""
	@echo "Development Workflows:"
	@echo "  make dev          - Start full development environment (infrastructure + API + frontend)"
	@echo ""
	@echo "Infrastructure Management:"
	@echo "  make up           - Start Docker services (PostgreSQL + Langfuse)"
	@echo "  make down         - Stop Docker services"
	@echo "  make restart      - Restart Docker services"
	@echo "  make logs         - Show Docker service logs"
	@echo ""
	@echo "Local Services:"
	@echo "  make api          - Run API locally (requires infrastructure)"
	@echo "  make frontend     - Run frontend locally (requires infrastructure + API)"
	@echo ""
	@echo "Utilities:"
	@echo "  make test         - Run tests"
	@echo "  make clean        - Clean up containers and volumes"
	@echo "  make help         - Show this help message"
	@echo ""
	@echo "Production Workflows:"
	@echo "  make prod-up      - Start full production environment"
	@echo "  make prod-down    - Stop production environment"
	@echo "  make prod-logs    - Show production logs"

# Development Workflows
dev: up ## Start full development environment
	@echo "🚀 Starting full development environment..."
	@echo "📊 Langfuse: http://localhost:3001"
	@echo "🗄️  PostgreSQL: localhost:5433"
	@echo "🔧 API: http://localhost:8000"
	@echo "🎨 Frontend: http://localhost:8501"
	@echo ""
	@echo "Starting API and Frontend in parallel..."
	@$(MAKE) -j2 api frontend

# Infrastructure Management
up: ## Start Docker services (PostgreSQL + Langfuse)
	@echo "🐳 Starting infrastructure services..."
	@docker compose -f docker-compose.dev.yaml up -d
	@echo "⏳ Waiting for services to be ready..."
	@sleep 10
	@echo "✅ Infrastructure services are running!"

down: ## Stop Docker services
	@echo "🛑 Stopping infrastructure services..."
	@docker compose -f docker-compose.dev.yaml down
	@echo "✅ Infrastructure services stopped!"

restart: down up ## Restart Docker services

logs: ## Show Docker service logs
	@docker compose -f docker-compose.dev.yaml logs -f

# Local Services
api: ## Run API locally
	@echo "🔧 Starting API locally..."
	@echo "📄 Using .env for configuration"
	@uv run uvicorn src.api.app:app --reload --reload-dir src --host 0.0.0.0 --port 8000

frontend: ## Run frontend locally
	@echo "🎨 Starting frontend locally..."
	@echo "📄 Using .env for configuration"
	@uv run streamlit run frontend/app.py --server.port=8501 --server.runOnSave=True

# Utilities
test: ## Run tests
	@echo "🧪 Running tests..."
	@uv run pytest tests/ -v

clean: ## Clean up containers and volumes
	@echo "🧹 Cleaning up Docker resources..."
	@docker compose -f docker-compose.dev.yaml down -v --remove-orphans
	@docker system prune -f
	@echo "✅ Cleanup complete!"

# Production (full docker-compose)
prod-up: ## Start full production environment
	@echo "🚀 Starting production environment..."
	@docker compose up -d

prod-down: ## Stop production environment
	@echo "🛑 Stopping production environment..."
	@docker compose down

prod-logs: ## Show production logs
	@docker compose logs -f
