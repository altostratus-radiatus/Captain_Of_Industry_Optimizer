import os
import sys
import pickle
import json
from collections import defaultdict
from copy import deepcopy
from math import prod
from itertools import chain

import optuna
from ortools.init.python import init
from ortools.linear_solver import pywraplp

from settlement_mega_recipe import make_settlement_mega_recipe
from config import BASE_RESEARCH_TARGET, MAINTENANCE_DIFFICULTY_MULTIPLIER

# Big-M constant: must exceed any possible contract flow value
BIG_M = 10

# Consider solutions with extremely close objective costs equivalent
OBJECTIVE_SIGNIFICANT_DIGITS = 4

# Penalty for factory logistics (minimize total factory i/o)
LOGISTICS_COST = 1
# Penalty for factory building sizes (minimize total factory footprint/building areas)
SIZE_COST = 0.1
# Penalty applied to raw resource extraction in the objective (set to very high to drive the solver towards contracts)
RAW_RESOURCE_COSTS = {
    'Rock': 1, # 'Dirt': 1000, 'IronOre': 5, 'CopperOre': 5, 'Coal': 5, 'Limestone': 5, 'Sand': 5, 'Quartz': 5, 'GoldOre': 5, 'UraniumOre': 5, 'Bauxite': 5, 'TitaniumOre': 5
}
# Tiny penalty to discourage activating contracts whose flow ends up at zero
CONTRACT_ACTIVATION_PENALTY = 10

# Minimum monthly production required for each target item
PRODUCTION_TARGETS = {
    'Research': BASE_RESEARCH_TARGET,
    'SpaceResearch': BASE_RESEARCH_TARGET,
    'Worker': 3000, # add some extra workers because LP underestimates real worker count due to fractional flows/machine counts
    'Truck': 200,
}
ALLOW_OVERPRODUCTION = {
    # 'UraniumDepleted', 'SpentMox', 'Dirt', 'Rock', 'Compost', 'Slag'
} - PRODUCTION_TARGETS.keys()
# Unity/Upoints are handled separately, this parameter requires the optimizer to overproduce Unity at this rate
UNITY_BUFFER = 0.5

SPECIAL_RESOURCES = {
    'Electricity', 'MechPower', 'Upoints', 'Research', 'Worker', 'MaintenanceT1', 'MaintenanceT2', 'MaintenanceT3', 'Computing',
}

STATUS_MAP = {
    pywraplp.Solver.OPTIMAL:    'OPTIMAL',
    pywraplp.Solver.FEASIBLE:   'FEASIBLE',
    pywraplp.Solver.INFEASIBLE: 'INFEASIBLE',
    pywraplp.Solver.UNBOUNDED:  'UNBOUNDED',
    pywraplp.Solver.ABNORMAL:   'ABNORMAL',
}

# Scrap materials (before recycling efficiency scaling) produced by each recipe.
RECYCLING_OUTPUTS = {
    'ResearchLab5 (ResearchLab5)':              [('CopperScrap', 65), ('IronScrap', 32), ('BrokenGlass', 21), ('GoldScrap', 3)],
    'MaintenanceT1Recipe (MaintenanceDepotT1)': [('CopperScrap', 12), ('IronScrap', 24)],
    'MaintenanceT2Recipe (MaintenanceDepotT2)': [('CopperScrap', 27), ('IronScrap', 18), ('BrokenGlass', 3)],
    'MaintenanceT3Recipe (MaintenanceDepotT3)': [('CopperScrap', 31), ('IronScrap',  9), ('BrokenGlass', 3), ('GoldScrap', 3)],
}

class EarlyStoppingCallback:
    def __init__(self, early_stopping_rounds, startup_trials):
        self.early_stopping_rounds = early_stopping_rounds
        self.startup_trials = startup_trials
        self._best_value = None
        self._rounds_without_improvement = 0

    def __call__(self, study, trial):
        if trial.state != optuna.trial.TrialState.COMPLETE:
            return

        # Do not track early stopping during the random startup phase
        if len(study.trials) <= self.startup_trials:
            return

        current_value = study.best_value
        if self._best_value is None or current_value < self._best_value:
            self._best_value = current_value
            self._rounds_without_improvement = 0
        else:
            self._rounds_without_improvement += 1
        
        if self._rounds_without_improvement >= self.early_stopping_rounds:
            print(f"\n[Optuna] Early stopping triggered: No improvement for {self.early_stopping_rounds} trials.")
            study.stop()

def build_solver(unity_budget, recipes, contract_monthly_unity_costs, solver_type="SCIP", fixed_contracts=None):
    """Construct the LP problem and return the solver and variable dicts."""
    solver = pywraplp.Solver.CreateSolver(solver_type)
    inf = solver.infinity()

    recipe_vars = {name: solver.NumVar(0, inf, name) for name, _, _, _ in recipes}
    extraction_vars = {name: solver.NumVar(0, inf, f'Mining_{name}') for name in RAW_RESOURCE_COSTS.keys()}
    contract_active_vars = {}
    constraints = {}
    all_items = set()
    
    net = defaultdict(lambda: defaultdict(float))
    for recipe_name, ingredients, products, _ in recipes:
        # Net coefficient of each item across all recipes
        for name, count in ingredients:
            net[name][recipe_name] -= count
            all_items.add(name)
        for name, count in products:
            net[name][recipe_name] += count
            all_items.add(name)

        # Create a boolean variable for each contract that is true when contract is active
        if recipe_name.startswith('Contract'):
            if fixed_contracts is not None:
                # Freeze the boolean variables for the shadow price LP pass
                fixed_val = fixed_contracts[recipe_name]
                active = solver.NumVar(fixed_val, fixed_val, f'Active_{recipe_name}')
            else:
                active = solver.BoolVar(f'Active_{recipe_name}')
            
            contract_active_vars[recipe_name] = active
            # Big-M: if flow > 0 then active must equal 1
            cons = solver.Constraint(0, inf, f'BigM_{recipe_name}')
            cons.SetCoefficient(recipe_vars[recipe_name], -1)
            cons.SetCoefficient(active, BIG_M)
            constraints[cons.name()] = cons
            
    all_items.discard('Upoints')

    for item in all_items:
        if item in ALLOW_OVERPRODUCTION:
            constraint = solver.Constraint(0, inf, f'Unbalanced_{item}')
        elif item in PRODUCTION_TARGETS:
            # constraint = solver.Constraint(PRODUCTION_TARGETS[item], inf, f'Target_{item}') # struggles probably becase space station produces Unity
            constraint = solver.Constraint(PRODUCTION_TARGETS[item], PRODUCTION_TARGETS[item], f'Target_{item}')
        else:
            constraint = solver.Constraint(0, 0, f'Balance_{item}')
        for recipe_name, coeff in net[item].items():
            constraint.SetCoefficient(recipe_vars[recipe_name], coeff)
        if item in extraction_vars:
            constraint.SetCoefficient(extraction_vars[item], 1)
        constraints[constraint.name()] = constraint

    # --- Unity budget constraint ---
    unity_cons = solver.Constraint(0, unity_budget, 'Unity_Budget')
    for recipe_name, ingredients, products, _ in recipes:
        upoints_consumption = next((c for n, c in ingredients if n == 'Upoints'), 0)
        upoints_production = next((c for n, c in products if n == 'Upoints'), 0)
        net_upoints = upoints_consumption - upoints_production
        if net_upoints:
            unity_cons.SetCoefficient(recipe_vars[recipe_name], net_upoints)
        if recipe_name in contract_active_vars:
            unity_cons.SetCoefficient(contract_active_vars[recipe_name], contract_monthly_unity_costs[recipe_name])
    constraints[unity_cons.name()] = unity_cons

    # --- Objective ---
    objective = solver.Objective()
    for recipe_name, ingredients, products, size in recipes:
        logistic_volume = sum(count for name, count in ingredients if name not in SPECIAL_RESOURCES)
        logistic_volume += sum(count for name, count in products if name not in SPECIAL_RESOURCES)
        objective.SetCoefficient(recipe_vars[recipe_name], LOGISTICS_COST * logistic_volume + SIZE_COST * size)
    for name, var in extraction_vars.items():
        objective.SetCoefficient(var, RAW_RESOURCE_COSTS[name])
    for active_var in contract_active_vars.values():
        objective.SetCoefficient(active_var, CONTRACT_ACTIVATION_PENALTY)
    objective.SetMinimization()

    return solver, recipe_vars, contract_active_vars, extraction_vars, constraints

def write_outputs(file_prefix, solver, recipe_vars, contract_active_vars, extraction_vars,
                  recipes, contract_monthly_unity_costs, unity_budget, shadow_prices=None, reduced_costs=None):
    """Write detailed solution files to the out/ directory."""

    factory_summary = defaultdict(lambda: defaultdict(dict))
    factory_summary['Upoints']['Supply']['UnityBudget'] = unity_budget

    recipes_summary = {}

    for recipe_name, active_var in contract_active_vars.items():
        if active_var.solution_value():
            if recipe_vars[recipe_name].solution_value() < 1e-7:
                print(f'  Warning: contract {recipe_name} is active but has no flow')
            factory_summary['Upoints']['Demand'][f'Active {recipe_name}'] = contract_monthly_unity_costs[recipe_name]

    for recipe_name, ingredients, products, size in recipes:
        flow = recipe_vars[recipe_name].solution_value()
        if not flow:
            continue
        for name, count in ingredients:
            factory_summary[name]['Demand'][recipe_name] = count * flow
        for name, count in products:
            factory_summary[name]['Supply'][recipe_name] = count * flow
        recipe_cost = solver.Objective().GetCoefficient(recipe_vars[recipe_name])
        recipe_size_cost = SIZE_COST * size
        recipes_summary[recipe_name] = {'Flow': flow, 'Recipe cost': recipe_cost, 'Recipe size cost': recipe_size_cost, 'Recipe logistic cost': recipe_cost - recipe_size_cost, 'Objective cost share': flow * recipe_cost}

    total_mining_excluding_rock = 0
    for name, var in extraction_vars.items():
        recipe_name = f'Mining {name}'
        flow = var.solution_value()
        if flow:
            factory_summary[name]['Supply'][recipe_name] = flow
            if name != 'Rock':
                total_mining_excluding_rock += flow
            recipe_cost = solver.Objective().GetCoefficient(var)
            recipes_summary[recipe_name] = {'Flow': flow, 'Recipe cost': recipe_cost, 'Objective cost share': flow * recipe_cost}
    if total_mining_excluding_rock:
        print('  Total mining (excluding rock):', total_mining_excluding_rock)

    for name, sd in factory_summary.items():
        total_demand = sum(sd.get('Demand', {}).values())
        total_supply = sum(sd.get('Supply', {}).values())
        if abs(total_demand - total_supply) > 1e-5 and name not in PRODUCTION_TARGETS and name != 'Upoints':
            print(f'  Warning: supply/demand mismatch for {name}: supply={total_supply:.4f}, demand={total_demand:.4f}')
        factory_summary[name]['Total'] = total_demand

    for recipe_name in {'RainwaterHarvester (RainwaterHarvester)', 'SolarPanel (SolarPanel)', 'SolarPanelMono (SolarPanelMono)'}:
        if recipe_name in recipes_summary:
            print(f'  Note: using {recipe_name}')

    for name in {'PollutedAir', 'PollutedWater'}:
        if name in factory_summary:
            print(f'  Warning: producing {factory_summary[name]["Total"]} {name}')

    with open(f'out/recipes_{file_prefix}.txt', 'w') as f:
        print('\n'.join(str(r) for r in recipes), file=f)
    with open(f'out/solver_problem_summary_{file_prefix}.txt', 'w') as f:
        print(solver.ExportModelAsLpFormat(False), file=f)
    with open(f'out/factory_summary_{file_prefix}.json', 'w') as f:
        json.dump(factory_summary, f, indent=1)
    with open(f'out/recipes_summary_{file_prefix}.json', 'w') as f:
        json.dump(recipes_summary, f, indent=1)
    
    if shadow_prices:
        with open(f'out/shadow_prices_{file_prefix}.json', 'w') as f:
            sorted_prices = dict(sorted(shadow_prices.items(), key=lambda x: x[1], reverse=True))
            json.dump(sorted_prices, f, indent=1)

    if reduced_costs:
        with open(f'out/reduced_costs_{file_prefix}.json', 'w') as f:
            reduced_costs = {name: format(cost, '.15f') for name, cost in reduced_costs.items()}
            json.dump(reduced_costs, f, indent=1)

def run_scip_pass(unity_budget, recipes, contract_monthly_unity_costs, verbose=False):
    """Run the MIP solver (SCIP) to find the optimal objective and discrete choices."""
    solver, recipe_vars, contract_active_vars, extraction_vars, _ = build_solver(
        unity_budget, recipes, contract_monthly_unity_costs, solver_type="SCIP"
    )

    # Set a 120-second limit per factory solve
    solver.SetTimeLimit(120 * 1000)

    # solver.EnableOutput()

    result_status = solver.Solve()
    if verbose:
        status_name = STATUS_MAP.get(result_status, 'UNKNOWN')
        print(f"  SCIP Status: {status_name}, iterations: {solver.iterations()}")

    if result_status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return None, None
    
    # Store variable states to freeze for the shadow price pass later
    frozen_contracts = {name: var.solution_value() for name, var in contract_active_vars.items()}
    return solver.Objective().Value(), (solver, recipe_vars, contract_active_vars, extraction_vars, frozen_contracts)

def apply_edicts(recipes, maintenance_multiplier, recycling_efficiency):
    """Apply edict effects to a recipe list in place."""
    for recipe_name, ingredients, products, _ in recipes:
        for i, (name, count) in enumerate(ingredients):
            if name.startswith('Maintenance'):
                ingredients[i] = (name, count * maintenance_multiplier * MAINTENANCE_DIFFICULTY_MULTIPLIER)
        if recipe_name in RECYCLING_OUTPUTS:
            products.extend(
                (scrap, amount * recycling_efficiency)
                for scrap, amount in RECYCLING_OUTPUTS[recipe_name]
            )

def main(verbose=False):
    with open('recipes.pkl', 'rb') as f:
        base_recipes = pickle.load(f)
    with open('contract_monthly_unity_costs.pkl', 'rb') as f:
        contract_monthly_unity_costs = pickle.load(f)

    os.makedirs('out', exist_ok=True)

    # --- Full search space ---

    # # Settlement unity multiplers
    # unity_multipliers           = [1, 1.5, 1.75, 2, 2.25]

    # # (effect_multiplier, unity_cost)
    # research_edicts             = [(1, 0), (1.15, -1), (1.25, -2), (1.35, -3), (1.45, -4), (1.6, -6)]
    # food_edicts                 = [(0.7, -2), (0.8, -1), (1.0, 0), (1.2, 1), (1.4, 2)] 
    # maintenance_edicts          = [(1.0, 0), (0.85, -1), (0.75, -2), (0.7, -3)]
    # recycling_edicts            = [(0.20, 0), (0.32, -1), (0.42, -2), (0.50, -3.5), (0.55, -5), (0.60, -7)]

    # # (effect_multiplier, unity_multiplier_for_item)
    # household_goods_edicts      = [(1, 1), (1.2, 1.15), (1.4, 1.3), (1.7, 1.45)]
    # household_appliances_edicts = [(1, 1), (1.2, 1.15), (1.4, 1.3), (1.7, 1.45)]
    # consumer_electronics_edicts = [(1, 1), (1.2, 1.15), (1.4, 1.3), (1.7, 1.45)]

    # luxury_goods = [True, False]
    # computing    = [True, False]

    # --- Most promising search space ---

    # Settlement unity multiplers
    unity_multipliers           = [1.75, 2, 2.25]

    # (effect_multiplier, unity_cost)
    research_edicts             = [(1.6, -6)]
    food_edicts                 = [(0.7, -2), (0.8, -1), (1.0, 0)] 
    maintenance_edicts          = [(1.0, 0), (0.85, -1), (0.75, -2), (0.7, -3)]
    recycling_edicts            = [(0.20, 0), (0.32, -1), (0.42, -2), (0.50, -3.5), (0.55, -5), (0.60, -7)]

    # (effect_multiplier, unity_multiplier_for_item)
    household_goods_edicts      = [(1, 1), (1.2, 1.15), (1.4, 1.3), (1.7, 1.45)]
    household_appliances_edicts = [(1, 1), (1.2, 1.15), (1.4, 1.3), (1.7, 1.45)]
    consumer_electronics_edicts = [(1, 1), (1.2, 1.15), (1.4, 1.3), (1.7, 1.45)]

    luxury_goods = [True, False]
    computing    = [True, False]

    # --- Re-run a combination ---

    # # Settlement unity multiplers
    # unity_multipliers           = [2]

    # # (effect_multiplier, unity_cost)
    # research_edicts             = [(1.6, -6)]
    # food_edicts                 = [(1.0, 0)] 
    # maintenance_edicts          = [(0.75, -2)]
    # recycling_edicts            = [(0.60, -7)]

    # # (effect_multiplier, unity_multiplier_for_item)
    # household_goods_edicts      = [(1, 1)]
    # household_appliances_edicts = [(1, 1)]
    # consumer_electronics_edicts = [(1, 1)]

    # luxury_goods = [True]
    # computing = [False]

    if not verbose:
        optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        unity_multiplier = trial.suggest_categorical('unity_multiplier', unity_multipliers)
        food_index = trial.suggest_int('food_index', 0, len(food_edicts) - 1)
        maintenance_index = trial.suggest_int('maintenance_index', 0, len(maintenance_edicts) - 1)
        recycling_index = trial.suggest_int('recycling_index', 0, len(recycling_edicts) - 1)
        research_index = trial.suggest_int('research_index', 0, len(research_edicts) - 1)

        food_mult, unity_food = food_edicts[food_index]
        maint_mult, unity_maint = maintenance_edicts[maintenance_index]
        recyc_eff, unity_recyc = recycling_edicts[recycling_index]
        research_mult, unity_research = research_edicts[research_index]

        hg_cost_mult, hg_unity_mult = household_goods_edicts[trial.suggest_int('hg_index', 0, len(household_goods_edicts) - 1)]
        ha_cost_mult, ha_unity_mult = household_appliances_edicts[trial.suggest_int('ha_index', 0, len(household_appliances_edicts) - 1)]
        ce_cost_mult, ce_unity_mult = consumer_electronics_edicts[trial.suggest_int('ce_index', 0, len(consumer_electronics_edicts) - 1)]

        provide_luxury_goods = trial.suggest_categorical('luxury_goods', luxury_goods)
        provide_computing = trial.suggest_categorical('computing', computing)

        unity_from_settlement, settlement_recipe = make_settlement_mega_recipe(
            unity_multiplier, hg_cost_mult, hg_unity_mult, ha_cost_mult, ha_unity_mult, ce_cost_mult, ce_unity_mult, food_mult, recyc_eff, provide_luxury_goods, provide_computing
        )
        unity_budget = unity_from_settlement + unity_food + unity_maint + unity_recyc + unity_research - UNITY_BUFFER

        recipes = deepcopy(base_recipes)
        recipes.append(settlement_recipe)
        apply_edicts(recipes, maint_mult, recyc_eff)

        # Run SCIP pass only to get the objective value
        cost, _ = run_scip_pass(unity_budget, recipes, contract_monthly_unity_costs)
        if cost is None:
            raise optuna.TrialPruned()
        # research multiplier is handled in a special way. instead of producing less research with higher research multiplier (which messes up building ratios), all factories produce the same amount of base research, but the total cost of a factory is scaled down based on the research multiplier
        return round(cost / research_mult, OBJECTIVE_SIGNIFICANT_DIGITS)

    search_space = {
        "unity_multiplier": unity_multipliers,
        "food_index": list(range(len(food_edicts))),
        "maintenance_index": list(range(len(maintenance_edicts))),
        "recycling_index": list(range(len(recycling_edicts))),
        "research_index": list(range(len(research_edicts))),
        "hg_index": list(range(len(household_goods_edicts))),
        "ha_index": list(range(len(household_appliances_edicts))),
        "ce_index": list(range(len(consumer_electronics_edicts))),
        "luxury_goods": luxury_goods,
        "computing": computing
    }
    startup_trials = 1000
    early_stopping_rounds = 400
    search_space_size = prod(len(choices) for choices in search_space.values())
    print('Search space size: ', search_space_size)
    if search_space_size < startup_trials + early_stopping_rounds:
        print('Starting grid search')
        study = optuna.create_study(direction='minimize', sampler=optuna.samplers.GridSampler(search_space))
        n_jobs = 1
    else:
        print("Starting Bayesian Optimization (Search Phase)...")
        study = optuna.create_study(direction='minimize', sampler=optuna.samplers.TPESampler(n_startup_trials=startup_trials, constant_liar=True, multivariate=True))
        n_jobs = -1
    early_stop = EarlyStoppingCallback(early_stopping_rounds=early_stopping_rounds, startup_trials=startup_trials)
    
    study.optimize(objective, n_trials=None, n_jobs=n_jobs, callbacks=[early_stop], show_progress_bar=False)

    if len(study.trials) == 0 or not study.best_trials:
        print("No feasible solution found.")
        return

    # --- Reconstruction of the best combination ---
    best = study.best_trial
    best_unity_mult = best.params['unity_multiplier']
    best_food_mult, unity_food_best = food_edicts[best.params['food_index']]
    best_maint_mult, unity_maint_best = maintenance_edicts[best.params['maintenance_index']]
    best_recyc_eff, unity_recyc_best = recycling_edicts[best.params['recycling_index']]
    best_research_mult, unity_research_best = research_edicts[best.params['research_index']]

    hg_cost_mult, hg_unity_mult = household_goods_edicts[best.params.get('hg_index', 0)]
    ha_cost_mult, ha_unity_mult = household_appliances_edicts[best.params.get('ha_index', 0)]
    ce_cost_mult, ce_unity_mult = consumer_electronics_edicts[best.params.get('ce_index', 0)]

    # if these services are not provided, then their multiplier doesn't matter, set it to 1 in the output
    if best_unity_mult < 1.75:
        hg_cost_mult = 1
    if best_unity_mult < 2:
        ha_cost_mult = 1
    if best_unity_mult < 2.25:
        ce_cost_mult = 1

    provide_luxury_goods = best.params['luxury_goods']
    provide_computing = best.params['computing']

    print(f"\nBest objective cost: {best.value:.4f}")
    print(f"  Unity multiplier: {best_unity_mult}")
    print(f"  Research multiplier: {best_research_mult}")
    print(f"  Food multiplier: {best_food_mult}")
    print(f"  Maintenance multiplier: {best_maint_mult}")
    print(f"  Recycling efficiency: {best_recyc_eff}")
    print(f"  Household goods multiplier: {hg_cost_mult}")
    print(f"  Household appliances multiplier: {ha_cost_mult}")
    print(f"  Consumer electronics multiplier: {ce_cost_mult}")
    print(f"  Provide luxury goods: {provide_luxury_goods}")
    print(f"  Provide computing: {provide_computing}")

    # --- Final "Victory Lap" for shadow prices and file output ---
    print("\nRunning final optimization pass and generating shadow prices...")
    
    unity_from_settle_best, settlement_recipe_best = make_settlement_mega_recipe(
        best_unity_mult, hg_cost_mult, hg_unity_mult, ha_cost_mult, ha_unity_mult, ce_cost_mult, ce_unity_mult, best_food_mult, best_recyc_eff, provide_luxury_goods, provide_computing
    )
    final_budget = unity_from_settle_best + unity_food_best + unity_maint_best + unity_recyc_best + unity_research_best - UNITY_BUFFER
    final_recipes = deepcopy(base_recipes)
    final_recipes.append(settlement_recipe_best)
    apply_edicts(final_recipes, best_maint_mult, best_recyc_eff)

    # Re-run SCIP once more to get the variable states for freezing
    _, (scip_solver, recipe_vars, active_vars, extra_vars, frozen_contracts) = run_scip_pass(
        final_budget, final_recipes, contract_monthly_unity_costs, verbose=True
    )

    # Final GLOP run for shadow prices
    glop_solver, glop_recipe_vars, glop_active_vars, glop_extraction_vars, constraints = build_solver(
        final_budget, final_recipes, contract_monthly_unity_costs, 
        solver_type="GLOP", fixed_contracts=frozen_contracts
    )
    glop_status = glop_solver.Solve()
    # marginal costs of each item
    shadow_prices = {name: cons.dual_value() for name, cons in constraints.items()} if glop_status == pywraplp.Solver.OPTIMAL else {}
    # recipe reduced cost = logistics_cost + size_cost + sum(ingredients * shadow_price) - sum(products * shadow_price)
    reduced_costs = {name: var.reduced_cost() for name, var in chain(glop_recipe_vars.items(), glop_active_vars.items(), glop_extraction_vars.items())}

    # Write files for the best solution only
    write_outputs("best", scip_solver, recipe_vars, active_vars, extra_vars,
                  final_recipes, contract_monthly_unity_costs, final_budget, shadow_prices=shadow_prices, reduced_costs=reduced_costs)
    
    print("Optimization complete. Best solution files saved to 'out/' directory.")

if __name__ == "__main__":
    init.CppBridge.init_logging("calculator.py")
    main(verbose='-q' not in sys.argv)