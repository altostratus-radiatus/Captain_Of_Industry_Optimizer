from config import GOODS_DIFFICULTY_MULTIPLIER, FOOD_DIFFICULTY_MULTIPLIER, UNITY_DIFFICULTY_MULTIPLIER

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
        ('Electricity',         1100 * m[0] * GOODS_DIFFICULTY_MULTIPLIER),
        ('Water',               47   * m[1] * GOODS_DIFFICULTY_MULTIPLIER),
        ('MedicalSupplies3',    5.4 * GOODS_DIFFICULTY_MULTIPLIER),
        ('HouseholdGoods',      10   * m[2] * hg_cost_mult * GOODS_DIFFICULTY_MULTIPLIER),
        ('HouseholdAppliances', 7    * m[3] * ha_cost_mult * GOODS_DIFFICULTY_MULTIPLIER),
        ('ConsumerElectronics', 3.6  * m[4] * ce_cost_mult * GOODS_DIFFICULTY_MULTIPLIER),
        ('LuxuryGoods',         4    * m[5] * luxury_goods * GOODS_DIFFICULTY_MULTIPLIER),
        ('Computing',           58   * computing * GOODS_DIFFICULTY_MULTIPLIER),
        ('Potato',     4.20 / 12 * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Corn',       3.00 / 12 * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Bread',      2.00 / 12 * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Meat',       2.70 / 16 * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Eggs',       3.00 / 16 * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Tofu',       1.80 / 16 * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Sausage',    3.35 / 16 * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Vegetables', 4.20 / 8  * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Fruit',      3.15 / 8  * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Snack',      2.60 / 8  * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
        ('Cake',       2.50 / 8  * 10 * food_multiplier * FOOD_DIFFICULTY_MULTIPLIER),
    ]

    products = [
        ('Worker',    1000),
        ('Waste',     29.3), # apparently waste doesn't increase with GOODS_DIFFICULTY_MULTIPLIER?
        ('Biomass',   4.1 * FOOD_DIFFICULTY_MULTIPLIER + (4.2 if unity_multiplier >= 1.75 else 0)),  # depends on food and household goods
        ('WasteWater', 39.2 * m[1] * GOODS_DIFFICULTY_MULTIPLIER),
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
    Upoints = 1.2 + 1 + UNITY_DIFFICULTY_MULTIPLIER * ( # health, decoration (and space station) are not affected by Unity difficulty multiplier?
            3 # food variety
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