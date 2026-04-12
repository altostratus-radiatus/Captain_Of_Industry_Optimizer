import json
import pickle
import csv

from building_sizes import building_sizes

TIME_INDEPENDENT = {
    'Electricity', 'MechPower', 'Upoints', 'Research', 'Worker',
    'MaintenanceT1', 'MaintenanceT2', 'MaintenanceT3', 'Computing',
}

REMOVE_RECIPE_GROUPS = {
    'FarmT1', 'StorageUnit', 'StorageLoose', 'StorageFluid',
    'AnyVirtualStorage', 'AnyMoltenStorage', 'Contract',
}

REMOVE_RECIPES = {
    'OilGroundPumping', 'LandWaterPumping',
    'ResearchLab1', 'ResearchLab2', 'ResearchLab21',
    'ResearchLab3', 'ResearchLab31', 'ResearchLab4', 'ResearchLab41',
    'NuclearWasteStorageIn', 'UraniumEnrichedAssemblyT1', 'MaintenanceT0Recipe',
    'ShreddingRetiredWaste', 'ShreddingPolyCells', 'PressingOfRecyclables',
    'MaintenanceT1Recycling', 'MaintenanceT2Recycling', 'MaintenanceT3Recycling',
    'ResearchLab51', 'WasteSortingPlant', 'WasteSortingPlant1',
}

# REMOVE_RECIPES |= {'RainwaterHarvester', 'SolarPanel', 'SolarPanelMono'}

# REMOVE_RECIPES |= {'DieselGenerator', 'DieselGeneratorT2', 'SteamGenerationCoal', 'SteamGenerationAnimalFeed', 'SteamGenerationHeavyOil', 'SteamGenerationMediumOil', 'SteamGenerationLightOil', 'SteamGenerationWood', 'SteamGenerationNaphtha','SteamGenerationEthanol', 'SteamGenerationFuelGas', 'SteamGenerationBiomass', 'SteamGenerationHydrogen'}

ITEM_NAMES = set()

# Hand-crafted recipes not present in the game data files
AREA_FOR_1_WOOD_PER_MONTH = 324 # 20 designations
AREA_FOR_1_WOOD_PER_MONTH *= 0.1 # don't penalize wood harvesting too much?
MANUAL_RECIPES = [
    (
        'NuclearWasteStorage',
        [('FissionProduct', 2)],
        [('RetiredWaste', 2)],
        building_sizes['NuclearWasteStorage']
    ),
    (
        'RetiredWasteToRecyclablesWhichDontExist (Shredder)',
        [('RetiredWaste', 6), ('Worker', 1), ('MaintenanceT1', 1), ('Electricity', 100)],
        [],
        building_sizes['Shredder']
    ),
    # (
    #     'TruckDiesel',
    #     [('Worker', 1), ('MaintenanceT1', 4), ('Diesel', 1.1)],
    #     [('Truck', 1)],
    #     0.000001
    # ),
    (
        'TruckHydrogen',
        [('Worker', 1), ('MaintenanceT1', 3.6), ('Hydrogen', 1.3)],
        [('Truck', 1)],
        0.000001
    ),
    # (
    #     'PollutedAirVoid',
    #     [('PollutedAir', 1)],
    #     [('Upoints', -0.044 * 0.02), ('Worker', -1)],
    #     1
    # ),
    # (
    #     'PollutedWaterVoid',
    #     [('PollutedWaterVoid', 1)],
    #     [('Upoints', -0.11 * 0.02), ('Worker', -1)],
    #     1
    # ),
    # One large tree harvester + one planter
    ('TreePlantingAndHarvesting',
     [('TreeSapling', 2.5), ('Worker', 4), ('MaintenanceT1', 12)], # 1 large tree harvester, 1 planter, and 2 trucks
     [('Wood', 50)],
     50 * AREA_FOR_1_WOOD_PER_MONTH) # 1000 designations
]

SECONDS_PER_MONTH = 60
CONTRACT_ROUNDTRIP_TIME = 270
CONTRACT_HYDROGEN_PER_TRIP = 1013
CONTRACT_INFRA_COSTS = [('Worker', 8 * 5 + 36), ('MaintenanceT1', 8 * 4), ('Electricity', 8 * 250), ('Hydrogen', CONTRACT_HYDROGEN_PER_TRIP / CONTRACT_ROUNDTRIP_TIME * SECONDS_PER_MONTH)]
CONTRACT_BUILDING_SIZE = 8 * 50 + 80 # whatever
AWKWARD_CONTRACT_PRODUCTS = {'Wheat', 'SugarCane', 'Corn', 'Wood', 'Vegetables', 'ChickenCarcass', 'FuelGas'}

def normalize_count(name, count, time, group_name):
    """Convert a recipe quantity to per-60-second throughput for one machine."""
    is_time_independent = name in TIME_INDEPENDENT
    # MaintenanceDepots are broken in data.json, and their maintenance output scales with time, unlike maintenance everywhere else
    is_maintenance_output = group_name.startswith('MaintenanceDepot') and name.startswith('Maintenance')
    if is_time_independent and not is_maintenance_output:
        return count
    return count * SECONDS_PER_MONTH / time


def load_recipes(data_path):
    """Load and normalize all building recipes from the game data JSON."""
    with open(data_path) as f:
        data = json.load(f)

    recipes = list(MANUAL_RECIPES)
    for group in data['recipeDictionaries']:
        group_name = group['name']
        if group_name in REMOVE_RECIPE_GROUPS:
            continue
        for recipe in group['recipes']:
            recipe_name = recipe['name']
            if recipe_name in REMOVE_RECIPES:
                continue
            time = recipe['time']
            inputs = [
                (item['name'], normalize_count(item['name'], item['count'], time, group_name))
                for item in recipe.get('input', [])
            ]
            outputs = [
                (item['name'], normalize_count(item['name'], item['count'], time, group_name))
                for item in recipe.get('output', [])
            ]
            ITEM_NAMES.update(name for name, _ in inputs)
            ITEM_NAMES.update(name for name, _ in outputs)
            recipes.append((f"{recipe_name} ({group_name})", inputs, outputs, building_sizes[group_name]))
    return recipes


def load_contracts(csv_path):
    """Load trade contracts from CSV and express them as max-throughput recipes."""
    recipes = []
    monthly_unity_costs = {}
    with open(csv_path) as f:
        for ingredient, ingredient_count, product, product_count, unity_per_month, unity_per_shipment in csv.reader(f):
            assert ingredient in ITEM_NAMES and product in ITEM_NAMES
            if product in AWKWARD_CONTRACT_PRODUCTS:
                continue
            name = f'Contract{ingredient}To{product}'
            rate = SECONDS_PER_MONTH / CONTRACT_ROUNDTRIP_TIME
            ingredients = CONTRACT_INFRA_COSTS.copy()
            ingredients.append((ingredient, float(ingredient_count) * rate))
            ingredients.append(('Upoints', float(unity_per_shipment) * rate))
            recipes.append((name, ingredients, [(product, float(product_count) * rate)], CONTRACT_BUILDING_SIZE))
            monthly_unity_costs[name] = float(unity_per_month)
    return recipes, monthly_unity_costs

def main():
    recipes = load_recipes('data.json')
    contract_recipes, contract_unity_costs = load_contracts('contracts.csv')
    recipes.extend(contract_recipes)

    with open('recipes.txt', 'w') as f:
        print('\n'.join(str(r) for r in recipes), file=f)
    with open('recipes.pkl', 'wb') as f:
        pickle.dump(recipes, f)
    with open('contract_monthly_unity_costs.pkl', 'wb') as f:
        pickle.dump(contract_unity_costs, f)


if __name__ == '__main__':
    main()