# Recyclable consumer goods consumed by the settlement.
# Each entry: (output_count, [copper, iron, aluminum, gold, glass] per batch)
# Corresponds to: MedicalSupplies3, HouseholdGoods, HouseholdAppliances, ConsumerElectronics, LuxuryGoods
RECYCLABLES = [
    (48, [0,      54, 0, 0,  6]),
    (64, [0,      32, 0, 0, 32]),
    (48, [68,     32, 0, 0,  4]),
    (6,  [10.333,  0, 3, 1,  1]),
    (32, [0,       0, 0, 8,  0]),
]
RECYCLING_PRODUCTS = ['CopperScrap', 'IronScrap', 'AluminumScrap', 'GoldScrap', 'BrokenGlass']

# Per-settlement-level multipliers for [electricity, water, household_goods, appliances, electronics, luxury_goods]
UNITY_MULTIPLIERS_TO_SETTLEMENT_MULTIPLIERS = {
    1:    [0,   0,    0,    0,   0,   1  ],
    1.5:  [1.1, 1.05, 0,    0,   0,   1  ],
    1.75: [1.2, 1.1,  1.05, 0,   0,   1  ],
    2:    [1.2, 1.1,  1.05, 1,   0,   1  ],
    2.25: [1.4, 1.2,  1.1,  1.1, 1,   1.1],
}

SETTLEMENT_SIZE_PER_1000_WORKERS = 2.5 * 28 * 28

def make_settlement_mega_recipe(unity_multiplier, hg_cost_mult, hg_unity_mult, ha_cost_mult, ha_unity_mult, ce_cost_mult, ce_unity_mult, food_multiplier=1, recycling_efficiency=0.2, luxury_goods=True, computing=True):
    """Build the settlement mega-recipe representing aggregate settlement consumption/production."""
    m = UNITY_MULTIPLIERS_TO_SETTLEMENT_MULTIPLIERS[unity_multiplier]

    # ingredients[2:7] are the five consumer goods that correspond to RECYCLABLES
    ingredients = [
        ('Electricity',         1100 * m[0]),
        ('Water',               47   * m[1]),
        ('MedicalSupplies3',    5.4),
        ('HouseholdGoods',      10   * m[2] * hg_cost_mult),
        ('HouseholdAppliances', 7    * m[3] * ha_cost_mult),
        ('ConsumerElectronics', 3.6  * m[4] * ce_cost_mult),
        ('LuxuryGoods',         4    * m[5] * luxury_goods),
        ('Computing',           58   * computing),
        ('Potato',     4.20 / 12 * 10 * food_multiplier),
        ('Corn',       3.00 / 12 * 10 * food_multiplier),
        ('Bread',      2.00 / 12 * 10 * food_multiplier),
        ('Meat',       2.70 / 16 * 10 * food_multiplier),
        ('Eggs',       3.00 / 16 * 10 * food_multiplier),
        ('Tofu',       1.80 / 16 * 10 * food_multiplier),
        ('Sausage',    3.35 / 16 * 10 * food_multiplier),
        ('Vegetables', 4.20 / 8  * 10 * food_multiplier),
        ('Fruit',      3.15 / 8  * 10 * food_multiplier),
        ('Snack',      2.60 / 8  * 10 * food_multiplier),
        ('Cake',       2.50 / 8  * 10 * food_multiplier),
    ]

    products = [
        ('Worker',    1000),
        ('Waste',     29.3),
        ('Biomass',   8.3 if unity_multiplier >= 1.75 else 4.1),  # depends on food and household goods
        ('WasteWater', 39.2 * m[1]),
    ]

    # Consumer goods produce scraps when recycled; scale by consumption rate and recycling efficiency
    recycling_output = [
        recycling_efficiency * sum(
            ingredients[i + 2][1] / RECYCLABLES[i][0] * RECYCLABLES[i][1][j]
            for i in range(len(RECYCLABLES))
        )
        for j in range(len(RECYCLING_PRODUCTS))
    ]
    products.extend(zip(RECYCLING_PRODUCTS, recycling_output))

    # Unity points
    Upoints = (
        3 + 1.2 + 1 # food variety, health, decoration
        + unity_multiplier * (
            1 + 1  # food satisfaction, hospital
            + luxury_goods * 1
            + computing * 1
            + (unity_multiplier >= 1.5)  * (1 + 1.2)
            + (unity_multiplier >= 1.75) * 1.4 * hg_unity_mult
            + (unity_multiplier >= 2)    * 1.4 * ha_unity_mult
            + (unity_multiplier >= 2.25) * 1.4 * ce_unity_mult
        )
    )

    return Upoints, ('SettlementMegaRecipe', ingredients, products, SETTLEMENT_SIZE_PER_1000_WORKERS)