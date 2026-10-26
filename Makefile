.PHONY: stats stats-detailed metadata sync help adapt adapt-status adapt-report adapt-dry-run

help: ## Show available commands
	@echo ""
	@echo "  \033[1mAgentic Data Curation\033[0m"
	@echo ""
	@echo "  \033[36mstats\033[0m              Short dataset summary table"
	@echo "  \033[36mstats-detailed\033[0m     Detailed per-dataset breakdown"
	@echo "  \033[36mmetadata\033[0m           Rebuild metadata.csv for all datasets"
	@echo "  \033[36msync\033[0m               Sync data/images/ to weka (images + metadata.csv only)"
	@echo "  \033[36madapt\033[0m              New-generator adaptation: run every new row in configs/adapt/releases.md"
	@echo "  \033[36madapt-status\033[0m       Stage of every adaptation run"
	@echo "  \033[36madapt-report\033[0m       Rebuild the time-to-adapt report and halving curve"
	@echo "  \033[36madapt-dry-run\033[0m      Safe end-to-end dry run (ARGS=\"--only ltx_2_5\")"
	@echo ""
	@echo "  \033[1mSync examples:\033[0m"
	@echo "    make sync                                    # sync all datasets to default weka path"
	@echo "    make sync ARGS=\"--dry-run\"                    # preview without copying"
	@echo "    make sync ARGS=\"--dataset grok\"               # sync single dataset"
	@echo "    make sync ARGS=\"--dst /other/path\"            # custom destination"
	@echo "    make sync ARGS=\"--dst /tmp/test --dry-run\"    # combine flags"
	@echo ""

stats: ## Short dataset summary table
	uv run curate stats

stats-detailed: ## Detailed per-dataset breakdown
	uv run curate stats --detailed

metadata: ## Rebuild metadata.csv for all datasets
	uv run curate build-metadata

sync: ## Sync data/images/ to weka
	bash scripts/sync_data.sh $(ARGS)

adapt: ## New-generator adaptation (docs/ADAPT.md)
	uv run adapt run $(ARGS)

adapt-status: ## Stage of every adaptation run
	uv run adapt status

adapt-report: ## Time-to-adapt report + halving curve
	uv run adapt report $(ARGS)

adapt-dry-run: ## Safe end-to-end dry run in data/adapt_dryrun
	bash scripts/adapt_dry_run.sh $(ARGS)
