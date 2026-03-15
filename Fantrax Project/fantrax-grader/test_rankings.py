import auth
from fantraxapi import League
from prospects import get_consensus_rankings
from milb_stats import get_milb_production_scores
from dynasty import _age_multiplier
import pandas as pd

print("Loading MiLB production scores...")
production = get_milb_production_scores(season=2025)
print(f"Got {len(production)} qualifying players\n")

rankings = get_consensus_rankings()
rankings = rankings.merge(
    production[["name", "production_score"]].rename(columns={}),
    on="name", how="left"
)
rankings["pedigree_score"] = 101 - rankings["consensus_rank"]

def blend(row):
    if pd.notna(row.get("production_score")) and row["production_score"] > 0:
        return round(0.5 * row["pedigree_score"] + 0.5 * row["production_score"], 1)
    return round(float(row["pedigree_score"]), 1)

rankings["blended_score"] = rankings.apply(blend, axis=1)
rankings["age_multiplier"] = rankings["age"].apply(_age_multiplier)
rankings["dynasty_value"] = (rankings["blended_score"] * rankings["age_multiplier"]).round(1)
rankings = rankings.sort_values("dynasty_value", ascending=False).reset_index(drop=True)

print("Top 10 dynasty values:")
print(rankings[["name", "consensus_rank", "age", "pedigree_score", "production_score", "blended_score", "age_multiplier", "dynasty_value"]].head(10).to_string())

print("\n--- Blake Mitchell specifically ---")
bm = rankings[rankings["name"] == "Blake Mitchell"]
print(bm[["name", "consensus_rank", "age", "pedigree_score", "production_score", "blended_score", "age_multiplier", "dynasty_value"]].to_string())

# Check if he appears in production data
bm_prod = production[production["name"].str.contains("Mitchell", case=False)] if not production.empty else pd.DataFrame()
print("\nMitchell in MiLB stats:", bm_prod[["name","ab","ops","production_score"]].to_string() if not bm_prod.empty else "NOT FOUND")
