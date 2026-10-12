COMPOSE := docker compose -f compose.yaml -f compose.traefik.yaml
COMPOSE_DEVCONTAINER := $(COMPOSE) -f .devcontainer/compose.yaml
TRAEFIK_NETWORK := traefik

.PHONY: up down restart logs ps config build rebuild traefik-network
.PHONY: devcontainer-stop devcontainer-down devcontainer-ps devcontainer-logs devcontainer-config

up: traefik-network
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

config:
	$(COMPOSE) config

build:
	$(COMPOSE) build

rebuild: traefik-network
	$(COMPOSE) up --build -d

devcontainer-stop:
	$(COMPOSE_DEVCONTAINER) stop

devcontainer-down:
	$(COMPOSE_DEVCONTAINER) down

devcontainer-ps:
	$(COMPOSE_DEVCONTAINER) ps -a

devcontainer-logs:
	$(COMPOSE_DEVCONTAINER) logs -f

devcontainer-config:
	$(COMPOSE_DEVCONTAINER) config

traefik-network:
	@docker network inspect $(TRAEFIK_NETWORK) >/dev/null 2>&1 || docker network create $(TRAEFIK_NETWORK)
