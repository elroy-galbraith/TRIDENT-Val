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
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def build_model(X_train, y_train, categories, numeric_ordinal, categorical):
    """Fit and return a regressor predicting log1p(SalePrice).

    Args:
        X_train: training feature frame — numeric/ordinal columns as numbers, categorical
            columns as pandas `category` dtype (see scripts/train_model.py's `prepare()`).
        y_train: log1p(SalePrice) training target, aligned with X_train.
        categories: {categorical_col: sorted list of every category value} — the full
            category universe (not just what appears in X_train), so one-hot encoders behave
            consistently across train/holdout/live inference.
        numeric_ordinal: numeric + ordinal column names, in X_train's column order.
        categorical: categorical column names, in X_train's column order.

    Returns:
        A fitted object exposing .predict(X) -> array of log1p(SalePrice) predictions, where
        X has the same columns/dtypes as X_train.
    """
    prep = ColumnTransformer(transformers=[
        ("num", StandardScaler(), numeric_ordinal),
        ("cat", OneHotEncoder(categories=[categories[c] for c in categorical],
                              handle_unknown="ignore"), categorical),
    ])
    model = Pipeline(steps=[
        ("prep", prep),
        ("reg", ExtraTreesRegressor(n_estimators=300, max_depth=None,
                                     min_samples_leaf=2, random_state=42, n_jobs=-1)),
    ])
    model.fit(X_train, y_train)
    return model
# EVOLVE-BLOCK-END
