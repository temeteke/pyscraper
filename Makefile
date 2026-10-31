.DEFAULT_GOAL := help

COMPOSE := docker compose -f compose.yaml -f compose.traefik.yaml
COMPOSE_DEVCONTAINER := $(COMPOSE) -f .devcontainer/compose.yaml
TRAEFIK_NETWORK := traefik

.PHONY: help guard-host traefik-network
.PHONY: up down restart logs ps ps-all config build pull
.PHONY: devcontainer-stop devcontainer-down devcontainer-logs devcontainer-config

help:
	@printf '%s\n' \
	  'PyScraper Compose targets' \
	  '' \
	  'Normal stack (compose.yaml + compose.traefik.yaml)' \
	  '  up                   Start the stack (no forced rebuild)' \
	  '  down                 Remove normal services (volumes kept; workspace may remain)' \
	  '  restart              Restart existing containers' \
	  '  logs                 Follow logs' \
	  '  ps                   Show running project containers' \
	  '  ps-all               Show all project containers, including stopped' \
	  '  config               Show the merged Compose configuration' \
	  '  build                Build the images locally' \
	  '  pull                 Pull the published images' \
	  '' \
	  'Dev Container (compose.yaml + compose.traefik.yaml + .devcontainer/compose.yaml)' \
	  '  devcontainer-stop    Stop all containers in the shared project' \
	  '  devcontainer-down    Remove all containers and networks in the shared project' \
	  '  devcontainer-logs    Follow logs from the shared project (Dev Container configuration)' \
	  '  devcontainer-config  Show the merged Dev Container configuration' \
	  '' \
	  'Utilities' \
	  '  traefik-network      Create the external traefik network if needed' \
	  '  help                 Show this help' \
	  '' \
	  'Start, stop, restart, and build targets must run on the Docker host.'

guard-host:
	@if [ -f /.dockerenv ] || [ -f /run/.containerenv ]; then \
		echo "error: run this target on the Docker host, not inside a container" >&2; \
		exit 1; \
	fi

up: guard-host traefik-network
	$(COMPOSE) up -d

down: guard-host
	$(COMPOSE) down

restart: guard-host
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

ps-all:
	$(COMPOSE) ps -a

config:
	$(COMPOSE) config

build: guard-host
	$(COMPOSE) build

pull:
	$(COMPOSE) pull

devcontainer-stop: guard-host
	$(COMPOSE_DEVCONTAINER) stop

devcontainer-down: guard-host
	$(COMPOSE_DEVCONTAINER) down

devcontainer-logs:
	$(COMPOSE_DEVCONTAINER) logs -f

devcontainer-config:
	$(COMPOSE_DEVCONTAINER) config

traefik-network: guard-host
	@docker network inspect $(TRAEFIK_NETWORK) >/dev/null 2>&1 || docker network create $(TRAEFIK_NETWORK)
