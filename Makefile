.PHONY: install dev test run docker-build docker-run

install:
	pip install .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -q

run:
	eda-server

docker-build:
	docker build -f docker/Dockerfile -t eda-vne:1.0.0 .

docker-run:
	docker compose -f docker/docker-compose.yml up --build
