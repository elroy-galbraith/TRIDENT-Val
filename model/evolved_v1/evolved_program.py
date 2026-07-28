"""Evolvable model-construction step for a third TRIDENT-Val AVM challenger.

`build_model` is mutated generation-over-generation by OpenEvolve (see config.yaml's
system_message for the constraints it evolves under — scikit-learn only, fixed function
signature, must predict log1p(SalePrice)). scripts/evolve_challenger.py takes the winning
version, refits it on the full training split, and writes model/evolved_v1/ in the same
{model.joblib, feature_spec.json, manifest.json} shape as scripts/train_model.py's
lgbm_v1/linear_v1 artifacts, registering it as a Challenger alongside them.

The seed below (bagged extremely-randomized trees) is deliberately a different family from
both the LightGBM champion (boosted, sequential) and the Ridge linear challenger (a single
global linear fit) — evolution is free to change the estimator, hyperparameters, or feature
engineering entirely, as long as it stays inside those constraints.
"""
# EVOLVE-BLOCK-START
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, VotingRegressor
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def build_model(X_train, y_train, categories, numeric_ordinal, categorical):
    """Bagging + boosting + instance-based blend predicting log1p(SalePrice)."""
    prep = ColumnTransformer([
        ("num", StandardScaler(), numeric_ordinal),
        ("cat", OneHotEncoder(categories=[categories[c] for c in categorical],
                               handle_unknown="ignore"), categorical),
    ])
    reg = VotingRegressor([
        ("et", ExtraTreesRegressor(n_estimators=350, min_samples_leaf=2,
                                    random_state=42, n_jobs=-1)),
        ("hgb", HistGradientBoostingRegressor(max_depth=4, learning_rate=0.08,
                                               max_iter=200, l2_regularization=0.1,
                                               random_state=42)),
        ("knn", KNeighborsRegressor(n_neighbors=9, weights="distance", p=1)),
    ], weights=[0.42, 0.38, 0.2])
    model = Pipeline([("prep", prep), ("reg", reg)])
    model.fit(X_train, y_train)
    return model
# EVOLVE-BLOCK-END
