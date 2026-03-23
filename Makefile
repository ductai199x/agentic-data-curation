.PHONY: stats stats-detailed metadata sync help

help: ## Show available commands
	@echo ""
	@echo "  \033[1mAgentic Data Curation\033[0m"
	@echo ""
	@echo "  \033[36mstats\033[0m              Short dataset summary table"
	@echo "  \033[36mstats-detailed\033[0m     Detailed per-dataset breakdown"
	@echo "  \033[36mmetadata\033[0m           Rebuild metadata.csv for all datasets"
	@echo "  \033[36msync\033[0m               Sync data/ to weka (images + metadata.csv only)"
	@echo ""
	@echo "  \033[1mSync examples:\033[0m"
	@echo "    make sync                                    # sync all datasets to default weka path"
	@echo "    make sync ARGS=\"--dry-run\"                    # preview without copying"
	@echo "    make sync ARGS=\"--dataset grok\"               # sync single dataset"
	@echo "    make sync ARGS=\"--dst /other/path\"            # custom destination"
	@echo "    make sync ARGS=\"--dst /tmp/test --dry-run\"    # combine flags"
	@echo ""

stats: ## Short dataset summary table
	uv run python scripts/stats.py

stats-detailed: ## Detailed per-dataset breakdown
	uv run python scripts/stats.py --detailed

metadata: ## Rebuild metadata.csv for all datasets
	uv run python scripts/build_all_metadata.py

sync: ## Sync data/ to weka
	bash scripts/sync_data.sh $(ARGS)
