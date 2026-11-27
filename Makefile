.PHONY: bronze bronze-validate bronze-plan

bronze-validate:
	uv run indusense bronze validate

bronze-plan:
	uv run indusense bronze plan

# Première exécution : base dédiée existante et migration relue.
# Exemple : make bronze BRONZE_DATABASE=modele-1 BRONZE_APPROVED_PLAN_SHA256=<empreinte>
bronze: bronze-validate
	uv run indusense bronze load --database "$(BRONZE_DATABASE)" --approved-plan-sha256 "$(BRONZE_APPROVED_PLAN_SHA256)"
