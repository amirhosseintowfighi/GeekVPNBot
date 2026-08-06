.DEFAULT_GOAL := help
COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: help install up down logs ps shell fmt lint type arch test cov check migrate revision reset

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install dev dependencies and git hooks
	python -m pip install -e ".[dev]"
	pre-commit install

up: ## Start the full stack (detached)
	$(COMPOSE_DEV) up -d --build

down: ## Stop the stack
	$(COMPOSE_DEV) down

reset: ## Stop the stack and delete all volumes (DESTRUCTIVE)
	$(COMPOSE_DEV) down -v

logs: ## Tail logs
	$(COMPOSE_DEV) logs -f --tail=100

ps: ## Show container status
	$(COMPOSE_DEV) ps

shell: ## Shell into the api container
	$(COMPOSE_DEV) exec api bash

fmt: ## Format the codebase
	ruff format src tests
	ruff check --fix src tests

lint: ## Lint without fixing
	ruff check src tests
	ruff format --check src tests

type: ## Static type check
	mypy

arch: ## Verify Clean Architecture layering
	lint-imports

test: ## Run the test suite
	pytest

cov: ## Run tests with coverage
	pytest --cov --cov-report=term-missing --cov-report=xml

check: lint type arch test ## Everything CI runs

migrate: ## Apply migrations
	alembic upgrade head

revision: ## Autogenerate a migration: make revision m="add users"
	alembic revision --autogenerate -m "$(m)"

# ---------------------------------------------------------------------------
# Production deployment (phase 14)
#
# Every target here is a thin wrapper over a script. The scripts are the real
# interface, because an operator debugging an outage at 3am should not have to
# reverse-engineer make variables to find out what actually runs.
# ---------------------------------------------------------------------------

COMPOSE_PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml
COMPOSE_FULL := $(COMPOSE_PROD) -f docker-compose.monitoring.yml

.PHONY: deploy rollback deploy-status deploy-gate prod-up prod-down prod-logs \
        monitoring backup restore restore-check verify-config

deploy: deploy-gate ## Blue/green deploy with no downtime
	@scripts/deploy.sh deploy

rollback: ## Flip traffic back to the previous colour (fast, ~1s)
	@scripts/deploy.sh rollback

deploy-status: ## Show which colour is currently serving
	@scripts/deploy.sh status

deploy-gate: ## Check alerts, scrape targets, upstreams and env vars agree with the code
	@python scripts/deploy_gate.py

verify-config: deploy-gate ## Full pre-deploy validation, including compose and nginx
	@$(COMPOSE_FULL) config --quiet && echo "compose: valid"
	@for s in scripts/*.sh docker/nginx/entrypoint.sh; do bash -n "$$s" || sh -n "$$s"; done \
		&& echo "shell scripts: valid"
	@python scripts/sqli_gate.py

prod-up: ## Start the production stack (first boot; use `deploy` afterwards)
	@$(COMPOSE_FULL) up -d

prod-down: ## Stop the production stack, keeping volumes
	@$(COMPOSE_FULL) down

prod-logs: ## Follow logs from the edge and both API colours
	@$(COMPOSE_PROD) logs -f --tail=100 nginx api_blue api_green

monitoring: ## Start Prometheus, Alertmanager and Grafana only
	@docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
	@echo "Grafana is NOT published to the internet by design."
	@echo "Reach it with an SSH tunnel:  ssh -L 3000:localhost:3000 <host>"

backup: ## Take an encrypted, verified database backup
	@scripts/backup.sh

restore-check: ## Validate the newest backup WITHOUT changing anything
	@scripts/restore.sh --latest --dry-run

restore: ## DESTRUCTIVE. Restore the newest backup over the live database
	@scripts/restore.sh --latest --yes
