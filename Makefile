.PHONY: install run test crawl index-full reindex reindex-all rebuild-index index-status update-stale fmt

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -q

crawl:
	python scripts/manage.py crawl

index-full:
	python scripts/manage.py index-full

reindex:
	python scripts/manage.py reindex

reindex-all:
	python scripts/manage.py reindex-all

rebuild-index:
	python scripts/manage.py rebuild-index

index-status:
	python scripts/manage.py index-status

update-stale:
	python scripts/manage.py reindex
