from strategy import model as m


def test_case_analysis_headline_numbers():
    assert round(m.M["excess_share"], 2) == 0.31            # 31% of contacts from the higher contact rate
    assert round(m.M["carrier_net"], 2) == -1.43             # carrier change, net £M a year
    assert round(m.M["d_steady"], 2) == 0.94                 # option D steady state, £M a year
    assert round(m.NPV["D. Build"], 2) == 2.13 and round(m.NPV["B. Outsource"], 2) == 1.82
    assert m.M["e_mid"] < 0                                  # platform costs more per resolution than people
    assert max(m.BASE, key=m.BASE.get) == "D. Build" and m.M["robust_share"] == 1.0
