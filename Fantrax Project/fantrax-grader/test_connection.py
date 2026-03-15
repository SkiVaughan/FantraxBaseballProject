import auth
from fantraxapi import League

league = League("hp3gi9z9mg6wf2p7")
print(f"League: {league.name} {league.year}")

print("\nTesting standings...")
s = league.standings()
print(f"Standings ranks: {list(s.ranks.keys())}")

print("\nTesting first team roster...")
team = league.teams[0]
print(f"Team: {team.name} (id: {team.id})")
roster = league.team_roster(team.id)
print(f"Roster rows: {len(roster.roster)}")
row = roster.roster[0]
print(f"First player: {row.player.name}, pos: {row.player.pos_short_name}, score: {getattr(row, 'score', 'N/A')}")

print("\nTesting scoring period results...")
results = league.scoring_period_results()
print(f"Periods returned: {len(results)}")
