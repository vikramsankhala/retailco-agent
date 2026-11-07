"""RetailCo case: strategy evaluation model (Lab 0).

Reproduces every number in the case analysis from the case exhibits:
volume decomposition, carrier economics, option economics, three-year NPV,
weighted scoring with a robustness test, break-even and the decision tree.
Run:  python -m strategy.model
"""
import itertools

# ---------------- Inputs from the case ----------------
COST_PER_AGENT_CONTACT = 0.72
CHAT_PER_DAY = 8000
EMAIL_TO_AGENT = 3000
ORDERS = 3.4e6
ORDERS_PER_DAY = ORDERS / 365
CPO_NOW, CPO_BEFORE = 1.6, 1.1
AGENT_SHARE = 12200 / 15000
TIER1_SHARE = 0.68
CARRIER_SAVING = 0.70 * ORDERS / 1e6          # £M
GUARANTEE_COST = 2.81                          # £M, Exhibit 10
DISC = 0.10

M = {}
M["contacts_now"] = ORDERS_PER_DAY * CPO_NOW
M["contacts_before"] = ORDERS_PER_DAY * CPO_BEFORE
M["excess_contacts"] = M["contacts_now"] - M["contacts_before"]
M["excess_share"] = M["excess_contacts"] / M["contacts_now"]
M["excess_support_cost"] = M["excess_contacts"] * AGENT_SHARE * 365 * COST_PER_AGENT_CONTACT / 1e6
M["carrier_net"] = CARRIER_SAVING - GUARANTEE_COST - M["excess_support_cost"]
M["refund_per_point"] = 0.01 * ORDERS * 53 / 1e6

chat_year = CHAT_PER_DAY * 365 / 1e6            # M contacts


def d_steady(c=0.75, p=0.15, maint=0.20):
    return c * chat_year * COST_PER_AGENT_CONTACT - chat_year * p - maint


M["d_gross"] = 0.75 * chat_year * COST_PER_AGENT_CONTACT
M["d_run"] = chat_year * 0.15
M["d_steady"] = d_steady()
M["d_steady_nomaint"] = d_steady(maint=0)
M["be_steady"] = (chat_year * 0.15 + 0.20) / (chat_year * COST_PER_AGENT_CONTACT)
M["be_year1"] = (chat_year * 0.15 + 0.20 + 0.35) / (chat_year * COST_PER_AGENT_CONTACT)
email_year = EMAIL_TO_AGENT * 365 / 1e6
M["email_steady"] = 0.65 * email_year * COST_PER_AGENT_CONTACT - email_year * 0.15
tier1_agent_year = 15000 * TIER1_SHARE * AGENT_SHARE * 365 / 1e6
M["b_gross"] = tier1_agent_year * (COST_PER_AGENT_CONTACT - 0.38)
M["b_retained"] = 0.10 * tier1_agent_year * 0.38
M["b_steady"] = M["b_gross"] - M["b_retained"]
M["c_steady"] = 0.15 * chat_year * COST_PER_AGENT_CONTACT - 0.18
M["e_mid"] = 0.75 * chat_year * (COST_PER_AGENT_CONTACT - 0.775)
M["e_low"] = 0.75 * chat_year * (COST_PER_AGENT_CONTACT - 0.60)
M["e_high"] = 0.75 * chat_year * (COST_PER_AGENT_CONTACT - 0.95)
M["e_breakeven_price"] = COST_PER_AGENT_CONTACT

# Three-year cash flows (£M), relative to status quo
CF = {
    "A. Hire": [-1.10, -1.10, -1.10],
    "B. Outsource": [M["b_steady"] * 8 / 12 - tier1_agent_year * 0.38 * 4 / 12 * 0.5, M["b_steady"], M["b_steady"]],
    "C. Scripted bot": [M["c_steady"] * 10 / 12, M["c_steady"], M["c_steady"]],
    "D. Build": [-0.35 + M["d_steady_nomaint"] * 8 / 12 - 0.20 * 8 / 12,
                 M["d_steady"] + M["email_steady"] * 0.75 - 0.10,
                 M["d_steady"] + M["email_steady"]],
    "E. Buy platform": [M["e_mid"] * 0.5 - 0.15, M["e_mid"], M["e_mid"]],
}
NPV = {k: sum(v / (1 + DISC) ** (i + 1) for i, v in enumerate(cf)) for k, cf in CF.items()}

# Weighted scoring
CRIT = [("Economics", 25), ("Service recovery", 20), ("Control and compliance", 20), ("People and attrition", 15),
        ("Reversibility", 10), ("Delivery risk (5 = low)", 10)]
SCORES = {"A. Hire": [1, 4, 5, 2, 3, 4], "B. Outsource": [4, 3, 3, 1, 1, 3], "C. Scripted bot": [2, 2, 4, 2, 5, 5],
          "D. Build": [5, 4, 4, 4, 5, 2], "E. Buy platform": [2, 4, 2, 4, 3, 3]}


def weighted(weights):
    tot = sum(weights)
    return {k: sum(w * s for w, s in zip(weights, sc)) / tot for k, sc in SCORES.items()}


BASE = weighted([w for _, w in CRIT])
wins = 0
combos = 0
for mult in itertools.product([0.5, 1, 1.5], repeat=len(CRIT)):
    ws = [w * m for (_, w), m in zip(CRIT, mult)]
    r = weighted(ws)
    combos += 1
    wins += max(r, key=r.get) == "D. Build"
M["robust_share"] = wins / combos
M["robust_combos"] = combos

# Decision tree (assumed probabilities)
TREE = [("Containment ≥ 60%: scale to chat and email", 0.60, NPV["D. Build"]),
        ("Containment 40–60%: keep for tier-1 chat only", 0.25, 0.80),
        ("Containment < 40%: stop after pilot", 0.15, -0.35)]
M["tree_ev"] = sum(p * v for _, p, v in TREE)



if __name__ == "__main__":
    print("RetailCo strategy model (all figures in £M unless stated)\n")
    for k, v in M.items():
        print(f"  {k:24s} {v:,.3f}")
    print("\nThree-year cash flows and NPV at 10%:")
    for k, cf in CF.items():
        print(f"  {k:18s} {' '.join(f'{x:+.2f}' for x in cf)}   NPV {NPV[k]:+.2f}")
    print("\nWeighted scores:", {k: round(v, 2) for k, v in BASE.items()})
    print(f"D ranks first in {M['robust_share']:.0%} of {M['robust_combos']} weight combinations")
    print(f"Decision-tree expected value of D: {M['tree_ev']:.2f}")
