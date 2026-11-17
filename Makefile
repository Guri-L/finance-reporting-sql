# Shortcuts. Everything here also works as the plain command shown.
.PHONY: up down reset setup checks test lint data

up:          ## start database, load data, run controls, start the app
	docker compose up --build

down:
	docker compose down

reset:       ## throw away the local database and start again
	docker compose down -v && docker compose up --build

setup:       ## migrate, load and check against DATABASE_URL (e.g. a server)
	python -m scripts.setup

checks:      ## run the controls only
	python -m scripts.run_checks

test:        ## needs DATABASE_URL and REPORTING_DATABASE_URL
	python -m pytest -q

lint:
	ruff check .

data:        ## write the generated ledger to data/generated as CSV
	python -m datagen.generate --out data/generated
