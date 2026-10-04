COMPOSE := docker compose -f compose.yaml -f compose.traefik.yaml
TRAEFIK_NETWORK := traefik

.PHONY: up down restart logs ps config build rebuild traefik-network

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

traefik-network:
	@docker network inspect $(TRAEFIK_NETWORK) >/dev/null 2>&1 || docker network create $(TRAEFIK_NETWORK)
