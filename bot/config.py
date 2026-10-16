"""Every tunable number of the generic strategy (opponent-specific numbers live in opponent_map.py)."""

# --- time: the dealer bans a bot that is too slow, so every decision has a hard budget
decision_budget_ms = 120          # Monte Carlo stops at this deadline
game_time_soft_cap_s = 15         # after this much thinking in one game, skip Monte Carlo (table-only mode)
mc_max_iters = 20000

# --- preflop zones by effective stack in big blinds
pushfold_max_bb = 8               # <= this: shove or fold only (sim vs live-fitted field: 8 > 12 > 15)
z2_max_bb = 25                    # 8..25bb: raise small or shove; deeper: normal opens
open_raise_bb = 2.5
z2_open_raise_bb = 2.2

# --- priors for an unknown opponent (replaced by measured stats after ~min_samples hands)
prior_call_range_vs_shove = 0.35  # calls a shove with its top 35%
prior_shove_range = 0.30
prior_aggr_range = 0.20
prior_fold_to_bet = 0.45
min_samples = 8                   # Beta-prior weight: measured stats take over after this many hands
version_change_decay = 0.2        # opponent redeployed: keep 20% of its old stats

# --- postflop thresholds (equity vs the opponents' estimated ranges)
call_margin_base = 0.03           # call when equity >= pot odds + margin
call_margin_per_extra_opp = 0.02
value_bet_eq_hu = 0.60
value_bet_eq_multi = 0.70
raise_eq_hu = 0.70
raise_eq_multi = 0.80
low_spr_shove = 1.5               # stack-to-pot ratio at or below this: shove or fold
bluff_fold_margin = 0.05          # bluff only if their fold rate beats break-even by this much

# --- tournament
cutoff_mode_s = 150               # games are cut at ~3 minutes; leader by chips wins: adjust variance

# --- protocol / housekeeping
raise_plus_one = False            # flip if the dealer treats exactly call + min_raise as a call
state_ttl_s = 900                 # forget per-game memory after this long
