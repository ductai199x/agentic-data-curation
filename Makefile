.PHONY: stats stats-detailed metadata sync help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

stats: ## Short dataset summary table
	uv run python scripts/stats.py

stats-detailed: ## Detailed per-dataset breakdown
	uv run python scripts/stats.py --detailed

metadata: ## Rebuild metadata.csv for all datasets
	uv run python scripts/build_all_metadata.py

sync: ## Sync data/ to weka (images + metadata.csv only)
	bash scripts/sync_data.sh

sweep-grok: ## Run Grok caption+pipeline sweep loop
	bash scripts/sweep_grok.sh
